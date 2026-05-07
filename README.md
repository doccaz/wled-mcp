# WLED MCP Agent for SUSE Rancher Liz

A Model Context Protocol server that lets [Liz, the SUSE Rancher Prime AI
Assistant](https://documentation.suse.com/cloudnative/rancher-ai/), control
[WLED](https://kno.wled.ge/) LED-strip devices by publishing JSON commands
to the WLED native `/api` MQTT topic.

Packaged as a Helm chart, built on **SLE BCI Python 3.12**
(`registry.suse.com/bci/python:3.12`), and registered with Liz via an
`AIAgentConfig` (`ai.cattle.io/v1alpha1`) over **Streamable HTTP**
(the transport Liz requires).

## MCP tools exposed

| Tool                  | Purpose                                                       |
|-----------------------|---------------------------------------------------------------|
| `list_wled_devices`   | Enumerate devices configured in `values.yaml`.                |
| `list_wled_effects`   | Enumerate friendly effect aliases.                            |
| `set_wled_effect`     | Activate an effect (alias or numeric WLED id).                |
| `set_wled_preset`     | Activate a saved WLED preset.                                 |
| `set_wled_power`      | Turn a device on or off.                                      |
| `set_wled_color`      | Set primary/secondary/tertiary color (hex).                   |
| `set_wled_brightness` | Set brightness 0-255 without changing the effect.             |
| `set_wled_speed`      | Set effect speed 0-255.                                       |
| `set_wled_intensity`  | Set effect intensity 0-255.                                   |
| `set_wled_palette`    | Apply a WLED palette by id.                                   |

Each tool publishes a JSON payload to `<topicPrefix>/<name>/api`.

## Layout

```
.
├── .github/workflows/build.yaml     # CI: lint + multi-arch build to GHCR
├── .gitignore
├── Dockerfile                       # BCI Python 3.12 image
├── README.md
├── requirements.txt
├── mcp_agent/
│   ├── __init__.py
│   ├── config.py
│   └── server.py
└── charts/
    └── wled-mcp/
        ├── Chart.yaml
        ├── values.yaml              # all configuration lives here
        └── templates/
            ├── _helpers.tpl
            ├── NOTES.txt
            ├── configmap.yaml       # rendered config.yaml for the agent
            ├── secret.yaml          # MQTT creds (when not using existingSecret)
            ├── deployment.yaml
            ├── service.yaml
            ├── mosquitto.yaml       # optional embedded broker (dev/demo)
            └── aiagentconfig.yaml   # registers the agent with Liz
```

## Push to GitHub

From the project root, with the [GitHub CLI](https://cli.github.com/):

```bash
git init -b main
git add .
git commit -m "Initial commit"
gh repo create wled-mcp --private --source=. --push
```

(or create the repo in the UI and `git remote add origin <url> && git push -u origin main`).

## CI

`.github/workflows/build.yaml` runs on every push and PR:

* lints the Python sources with `ruff` and Helm chart with `helm lint`,
* renders the chart with default values **and** with the embedded broker
  enabled to catch template regressions,
* on pushes to `main` and on `vX.Y.Z` tags, builds a **multi-arch
  (amd64 + arm64)** image and pushes to
  `ghcr.io/<owner>/<repo>` using the workflow's auto-provisioned
  `GITHUB_TOKEN` (no extra secrets needed).

The first push will create the package as private — visit your GHCR
package settings to make it public if you want unauthenticated pulls.

## Build and push the image

```bash
docker build -t ghcr.io/<your-org>/wled-mcp:0.1.0 .
docker push  ghcr.io/<your-org>/wled-mcp:0.1.0
```

Set `image.repository` / `image.tag` in your values to match.

## Install

External broker (typical):

```bash
helm install wled-mcp ./charts/wled-mcp \
  -n cattle-ai-agent-system \
  --create-namespace \
  --set image.repository=ghcr.io/<your-org>/wled-mcp \
  --set image.tag=0.1.0 \
  --set mqtt.host=mosquitto.iot.svc.cluster.local \
  --set mqtt.port=1883 \
  --set mqtt.username=wled \
  --set mqtt.password='s3cret'
```

Existing Secret (recommended for production — keys must be `username`
and `password`):

```bash
kubectl -n cattle-ai-agent-system create secret generic mqtt-creds \
  --from-literal=username=wled --from-literal=password='s3cret'

helm install wled-mcp ./charts/wled-mcp \
  -n cattle-ai-agent-system --create-namespace \
  --set mqtt.existingSecret=mqtt-creds \
  --set mqtt.host=mosquitto.iot.svc.cluster.local
```

Embedded Mosquitto for a self-contained demo:

```bash
helm install wled-mcp ./charts/wled-mcp \
  -n cattle-ai-agent-system --create-namespace \
  --set mqtt.embedded.enabled=true
```

After install, restart the assistant so it picks up the new agent:

```bash
kubectl rollout restart deployment -n cattle-ai-agent-system rancher-ai-agent
```

## Configuring devices and effects

Everything is in `charts/wled-mcp/values.yaml`. To add a third strip:

```yaml
devices:
  - id: living-room
    name: wled-livingroom
    topicPrefix: wled
  - id: desk
    name: wled-desk
    topicPrefix: wled
  - id: bedroom
    name: wled-bedroom
    topicPrefix: home/wled         # if you've customised the WLED prefix
    description: Headboard strip
```

Effect aliases just map a friendly name to a numeric WLED effect id from
<https://kno.wled.ge/features/effects/>:

```yaml
effects:
  ocean: { id: 101, description: Ocean wave }
```

## Disabling Liz registration

If you want to deploy the MCP server first and register it with Liz
manually from the UI, install with `--set liz.register=false`.

## References

* SUSE Liz docs — *Bring your own MCP* and *Multi Agent configuration*:
  <https://documentation.suse.com/cloudnative/rancher-ai/latest/en/how-tos/how-to-admin.html>
* WLED MQTT JSON API: <https://kno.wled.ge/interfaces/json-api/>
* SLE BCI Python image: `registry.suse.com/bci/python:3.12`
