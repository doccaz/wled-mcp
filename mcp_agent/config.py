"""Configuration loading for the WLED MCP agent.

Reads a YAML file (path from $WLED_MCP_CONFIG, default /etc/wled-mcp/config.yaml)
and exposes typed dataclasses to the rest of the app. Environment variables
override broker credentials so secrets can come from a Kubernetes Secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    tls: bool = False
    qos: int = 0
    client_id: str = "wled-mcp-agent"


@dataclass
class DeviceConfig:
    id: str             # short id used by the LLM, e.g. "living-room"
    name: str           # WLED device name (the second segment of the MQTT topic)
    topic_prefix: str = "wled"   # first segment, configurable in WLED's MQTT settings
    description: str | None = None


@dataclass
class AppConfig:
    mqtt: MqttConfig
    devices: list[DeviceConfig]
    # alias -> (wled_effect_id, human description)
    effect_aliases: dict[str, tuple[int, str]] = field(default_factory=dict)

    @property
    def devices_by_id(self) -> dict[str, DeviceConfig]:
        return {d.id: d for d in self.devices}


def load_config(path: str | os.PathLike[str]) -> AppConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")

    raw = yaml.safe_load(p.read_text()) or {}

    mqtt_raw = raw.get("mqtt", {})
    mqtt = MqttConfig(
        host=mqtt_raw.get("host", "localhost"),
        port=int(mqtt_raw.get("port", 1883)),
        # Credentials come from a Secret via env vars; YAML values are a fallback
        # for local development.
        username=os.environ.get("MQTT_USER") or mqtt_raw.get("username"),
        password=os.environ.get("MQTT_PASS") or mqtt_raw.get("password"),
        tls=bool(mqtt_raw.get("tls", False)),
        qos=int(mqtt_raw.get("qos", 0)),
        client_id=mqtt_raw.get("client_id", "wled-mcp-agent"),
    )

    devices = [
        DeviceConfig(
            id=d["id"],
            name=d["name"],
            topic_prefix=d.get("topic_prefix", "wled"),
            description=d.get("description"),
        )
        for d in raw.get("devices", [])
    ]
    if not devices:
        raise ValueError("config.yaml must define at least one device under 'devices:'")

    effect_aliases: dict[str, tuple[int, str]] = {}
    for alias, spec in (raw.get("effects") or {}).items():
        if isinstance(spec, int):
            effect_aliases[alias] = (spec, "")
        else:
            effect_aliases[alias] = (int(spec["id"]), spec.get("description", ""))

    return AppConfig(mqtt=mqtt, devices=devices, effect_aliases=effect_aliases)
