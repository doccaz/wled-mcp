"""WLED MCP Agent for SUSE Rancher Liz.

Exposes MCP tools (over Streamable HTTP) that publish JSON commands to
WLED devices via MQTT, using the WLED native /api topic.

Liz reaches this server through the URL configured in its AIAgentConfig
(spec.mcpURL).  The transport must be Streamable HTTP per SUSE's docs.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import paho.mqtt.client as mqtt
from mcp.server.fastmcp import FastMCP

from .config import AppConfig, load_config

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("wled-mcp")


# --------------------------------------------------------------------------- #
# MQTT helper                                                                 #
# --------------------------------------------------------------------------- #
class MqttPublisher:
    """Thin wrapper around paho-mqtt for fire-and-forget JSON publishes."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._client = mqtt.Client(
            client_id=cfg.mqtt.client_id,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        if cfg.mqtt.username:
            self._client.username_pw_set(cfg.mqtt.username, cfg.mqtt.password or "")
        if cfg.mqtt.tls:
            self._client.tls_set()

    def connect(self) -> None:
        log.info("Connecting to MQTT broker %s:%s", self._cfg.mqtt.host, self._cfg.mqtt.port)
        self._client.connect(self._cfg.mqtt.host, self._cfg.mqtt.port, keepalive=60)
        self._client.loop_start()

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def publish_json(self, topic: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"))
        log.info("MQTT publish %s -> %s", topic, body)
        info = self._client.publish(topic, body, qos=self._cfg.mqtt.qos, retain=False)
        # Don't block forever; surface broker errors back to the LLM.
        info.wait_for_publish(timeout=5.0)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed (rc={info.rc})")


# --------------------------------------------------------------------------- #
# MCP server                                                                  #
# --------------------------------------------------------------------------- #
CONFIG: AppConfig = load_config(os.environ.get("WLED_MCP_CONFIG", "/etc/wled-mcp/config.yaml"))
MQTT = MqttPublisher(CONFIG)
MQTT.connect()

# Streamable HTTP is required by Liz.  FastMCP exposes it on /mcp by default.
mcp = FastMCP(
    name="wled-mcp",
    instructions=(
        "Tools to control WLED LED-strip devices over MQTT. "
        "Use list_wled_devices first to discover configured devices, "
        "then set_wled_effect / set_wled_preset / set_wled_power."
    ),
)


def _device_topic(device_id: str) -> str:
    """Resolve a device id to its WLED `<prefix>/<name>/api` topic."""
    if device_id not in CONFIG.devices_by_id:
        valid = ", ".join(CONFIG.devices_by_id) or "(none configured)"
        raise ValueError(f"Unknown device '{device_id}'. Configured devices: {valid}")
    dev = CONFIG.devices_by_id[device_id]
    return f"{dev.topic_prefix.rstrip('/')}/{dev.name}/api"


@mcp.tool()
def list_wled_devices() -> list[dict[str, str]]:
    """List all WLED devices configured on this MCP server.

    Returns one entry per device with its id, friendly name, and MQTT topic.
    Always call this before issuing other commands so the user can confirm
    which device will be addressed.
    """
    return [
        {
            "id": d.id,
            "name": d.name,
            "description": d.description or "",
            "topic": f"{d.topic_prefix.rstrip('/')}/{d.name}/api",
        }
        for d in CONFIG.devices
    ]


@mcp.tool()
def list_wled_effects() -> list[dict[str, Any]]:
    """List the named animation effects (profiles) the user has defined in config.

    These are friendly aliases that map to WLED effect IDs.  If the user asks
    for an effect not in this list, fall back to set_wled_effect with a numeric
    effect_id from the WLED documentation.
    """
    return [
        {"alias": name, "effect_id": eid, "description": desc}
        for name, (eid, desc) in CONFIG.effect_aliases.items()
    ]


@mcp.tool()
def set_wled_effect(
    device_id: str,
    effect: str | int,
    brightness: int | None = None,
) -> str:
    """Activate an animation effect on a WLED device.

    Args:
        device_id: id of a device returned by list_wled_devices.
        effect: either a configured alias (e.g. "rainbow") or a numeric
            WLED effect id (0-186+).
        brightness: optional 0-255 brightness override.

    Returns a confirmation string.
    """
    # Resolve alias to numeric id.
    if isinstance(effect, str) and not effect.isdigit():
        if effect not in CONFIG.effect_aliases:
            valid = ", ".join(CONFIG.effect_aliases) or "(none)"
            raise ValueError(f"Unknown effect alias '{effect}'. Configured: {valid}")
        effect_id = CONFIG.effect_aliases[effect][0]
    else:
        effect_id = int(effect)

    # WLED JSON API: set the effect on segment 0.  See kno.wled.ge/interfaces/json-api/
    payload: dict[str, Any] = {"seg": [{"id": 0, "fx": effect_id}], "on": True}
    if brightness is not None:
        if not 0 <= brightness <= 255:
            raise ValueError("brightness must be between 0 and 255")
        payload["bri"] = brightness

    MQTT.publish_json(_device_topic(device_id), payload)
    return f"Effect {effect_id} activated on '{device_id}'."


@mcp.tool()
def set_wled_preset(device_id: str, preset_id: int) -> str:
    """Activate a saved WLED preset by its numeric id.

    Presets are configured on the WLED device itself (in its web UI) and
    typically bundle effect + colors + speed + intensity.
    """
    if preset_id < 1:
        raise ValueError("preset_id must be >= 1")
    payload = {"ps": preset_id}
    MQTT.publish_json(_device_topic(device_id), payload)
    return f"Preset {preset_id} activated on '{device_id}'."


@mcp.tool()
def set_wled_power(device_id: str, on: bool) -> str:
    """Turn a WLED device on or off."""
    MQTT.publish_json(_device_topic(device_id), {"on": on})
    return f"Device '{device_id}' turned {'on' if on else 'off'}."


# --------------------------------------------------------------------------- #
# Look & feel: color, brightness, speed, intensity, palette                   #
# --------------------------------------------------------------------------- #
def _parse_color(color: str | list[int]) -> list[int]:
    """Accept '#rrggbb', 'rrggbb', or [r,g,b] and return [r,g,b]."""
    if isinstance(color, list):
        if len(color) != 3 or not all(isinstance(c, int) and 0 <= c <= 255 for c in color):
            raise ValueError("Color list must be 3 integers in 0-255")
        return color
    s = color.lstrip("#").strip()
    if len(s) != 6:
        raise ValueError(f"Hex color must be 6 chars, got '{color}'")
    try:
        return [int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)]
    except ValueError as e:
        raise ValueError(f"Invalid hex color '{color}'") from e


@mcp.tool()
def set_wled_color(
    device_id: str,
    color: str,
    slot: int = 0,
) -> str:
    """Set one of the three color slots on a WLED device.

    Args:
        device_id: id from list_wled_devices.
        color: '#rrggbb' or 'rrggbb' hex string.
        slot: 0 = primary (default), 1 = secondary, 2 = tertiary.  Most
            effects only use slot 0; some (e.g. gradient effects) use 1 and 2.
    """
    if slot not in (0, 1, 2):
        raise ValueError("slot must be 0, 1, or 2")
    rgb = _parse_color(color)
    # WLED expects "col" as a 3-element array of [r,g,b] arrays per segment.
    # Build a list with the chosen slot set and the others left as null so
    # they keep their current value.
    col: list[list[int] | None] = [None, None, None]
    col[slot] = rgb
    payload = {"on": True, "seg": [{"id": 0, "col": col}]}
    MQTT.publish_json(_device_topic(device_id), payload)
    return f"Slot {slot} on '{device_id}' set to #{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}."


@mcp.tool()
def set_wled_brightness(device_id: str, brightness: int) -> str:
    """Set overall brightness (0-255) without touching the current effect.

    The user probably means a percentage when they say "dim to 30%".
    Convert before calling: int(round(pct / 100 * 255)).
    """
    if not 0 <= brightness <= 255:
        raise ValueError("brightness must be between 0 and 255")
    MQTT.publish_json(_device_topic(device_id), {"on": brightness > 0, "bri": brightness})
    return f"Brightness on '{device_id}' set to {brightness}/255."


@mcp.tool()
def set_wled_speed(device_id: str, speed: int) -> str:
    """Set the speed (0-255) of the current effect on segment 0.

    Lower = slower animation, higher = faster.
    """
    if not 0 <= speed <= 255:
        raise ValueError("speed must be between 0 and 255")
    MQTT.publish_json(_device_topic(device_id), {"seg": [{"id": 0, "sx": speed}]})
    return f"Effect speed on '{device_id}' set to {speed}/255."


@mcp.tool()
def set_wled_intensity(device_id: str, intensity: int) -> str:
    """Set the intensity (0-255) of the current effect on segment 0.

    Effect-specific: usually controls density, blur, or amount of motion.
    """
    if not 0 <= intensity <= 255:
        raise ValueError("intensity must be between 0 and 255")
    MQTT.publish_json(_device_topic(device_id), {"seg": [{"id": 0, "ix": intensity}]})
    return f"Effect intensity on '{device_id}' set to {intensity}/255."


@mcp.tool()
def set_wled_palette(device_id: str, palette_id: int) -> str:
    """Set the color palette for the current effect on segment 0.

    Palette IDs are documented at https://kno.wled.ge/features/palettes/ .
    Common values: 0=default, 2=Party, 5=Sunset, 6=Rivendell, 8=Pastel,
    35=Sunset_Real, 49=Sherbet.
    """
    if palette_id < 0:
        raise ValueError("palette_id must be >= 0")
    MQTT.publish_json(_device_topic(device_id), {"seg": [{"id": 0, "pal": palette_id}]})
    return f"Palette {palette_id} applied on '{device_id}'."


# --------------------------------------------------------------------------- #
# Entrypoint                                                                  #
# --------------------------------------------------------------------------- #
def main() -> None:
    host = os.environ.get("MCP_HTTP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_HTTP_PORT", "8080"))
    log.info("Starting WLED MCP server (Streamable HTTP) on %s:%s", host, port)
    # FastMCP serves the streamable-http transport on /mcp.
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
