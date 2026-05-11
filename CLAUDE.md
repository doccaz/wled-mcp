# WLED-MCP Architecture

## What this is

An MCP (Model Context Protocol) server that lets SUSE Rancher Liz (an AI
assistant) control WLED LED-strip devices by publishing JSON commands to an
MQTT broker.

## Component map

```
Liz (AI agent)
  │  Streamable HTTP POST /mcp
  ▼
wled-mcp  (FastMCP, port 8080)
  │  paho-mqtt publish
  ▼
Mosquitto MQTT broker  (port 1883)
  │  topic: wled/<device-name>/api
  ▼
WLED firmware on ESP8266/ESP32
```

## Key files

| Path | Role |
|------|------|
| `mcp_agent/server.py` | MCP server, 10 tool definitions, `MqttPublisher` class |
| `mcp_agent/config.py` | YAML config loader, typed dataclasses (`AppConfig`, `MqttConfig`, `DeviceConfig`) |
| `server.py` | Thin root-level entry point, re-exports `mcp_agent.server` |
| `charts/wled-mcp/` | Helm chart for Kubernetes deployment |
| `charts/wled-mcp/templates/configmap.yaml` | Renders `config.yaml` from Helm values |
| `dev/config.yaml` | Local dev config (used by docker-compose) |
| `docker-compose.yml` | Local testing stack (wled-mcp + Mosquitto + sniffer) |

## Config loading

Config path comes from `$WLED_MCP_CONFIG` (default `/etc/wled-mcp/config.yaml`).
MQTT credentials are overridden by `$MQTT_USER` / `$MQTT_PASS` env vars so
Kubernetes Secrets don't have to live in the YAML file.

**Note:** the YAML config uses `topic_prefix` (snake_case). The Helm
`values.yaml` uses `topicPrefix` (camelCase) which the ConfigMap template
converts before writing the file.

## MQTT payload format

All tools publish to `<topic_prefix>/<device-name>/api`.
Payloads follow the [WLED JSON API](https://kno.wled.ge/interfaces/json-api/).
Examples:

```json
{"on": true, "bri": 200}
{"seg": [{"id": 0, "fx": 9}]}
{"seg": [{"id": 0, "col": [[255,0,0], null, null]}]}
```

## MCP tools (10 total)

| Tool | WLED JSON field(s) |
|------|--------------------|
| `list_wled_devices` | — (config only) |
| `list_wled_effects` | — (config only) |
| `set_wled_power` | `on` |
| `set_wled_brightness` | `bri` |
| `set_wled_effect` | `seg[0].fx`, optional `bri` |
| `set_wled_preset` | `ps` |
| `set_wled_color` | `seg[0].col[slot]` |
| `set_wled_speed` | `seg[0].sx` |
| `set_wled_intensity` | `seg[0].ix` |
| `set_wled_palette` | `seg[0].pal` |

## Running locally (no Kubernetes)

```bash
# Start Mosquitto + wled-mcp (builds image from local Dockerfile)
docker compose up --build

# In another terminal — call any MCP tool directly
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"list_wled_devices","arguments":{}}}'

# Watch MQTT traffic in the sniffer service logs
docker compose logs -f sniffer
```

`dev/config.yaml` defines two sample devices (`living-room`, `desk`) pointing
at the compose Mosquitto service. Since no real WLED hardware is needed, you
can verify the full publish path just by watching the sniffer output.

## Running in Kubernetes

```bash
# Minimal install (embedded broker)
helm install wled-mcp ./charts/wled-mcp --set mqtt.embedded.enabled=true

# Production (external broker, existing Secret for credentials)
helm install wled-mcp ./charts/wled-mcp \
  --set mqtt.host=mosquitto.iot.svc.cluster.local \
  --set mqtt.existingSecret=mqtt-creds
```

The Helm chart creates: Deployment, Service (ClusterIP 80→8080), ConfigMap
(config.yaml), optional Secret, optional embedded Mosquitto, optional
`AIAgentConfig` CRD to register with Liz.

## Liz integration

Set `liz.register=true` in Helm values (or apply `aiagentconfig.yaml` manually)
to create the `AIAgentConfig` CRD. Liz discovers the server at
`http://wled-mcp.<namespace>.svc/mcp` and uses the system prompt in
`values.yaml` to decide when to invoke WLED tools.

## CI pipeline

`.github/workflows/build.yaml` runs on every push:
1. `ruff check mcp_agent` — linting
2. `python -m compileall -q mcp_agent` — syntax check
3. `helm lint` + `helm template` — chart validation

On pushes to `main` or version tags: multi-arch Docker build (amd64/arm64)
pushed to `ghcr.io/<owner>/<repo>`, then Helm chart packaged and published to
GitHub Pages.

## Design notes

- Config is a single YAML file, not a scatter of env vars, to keep device and
  effect definitions discoverable in one place.
- Effect aliases (`solid`, `rainbow`, etc.) are a UX layer over numeric WLED
  IDs so the LLM (and humans) don't need to memorise effect numbers.
- `MqttPublisher` uses `wait_for_publish(timeout=5)` so MQTT errors surface as
  exceptions back to the MCP caller instead of being silently dropped.
- The pod uses a read-only filesystem; only `/tmp` is writable.
