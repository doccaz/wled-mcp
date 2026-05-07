{{/*
Expand the name of the chart.
*/}}
{{- define "wled-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Fully qualified app name.
*/}}
{{- define "wled-mcp.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Common labels.
*/}}
{{- define "wled-mcp.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "wled-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selector labels.
*/}}
{{- define "wled-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "wled-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Mosquitto sub-resource name.
*/}}
{{- define "wled-mcp.mosquittoFullname" -}}
{{- printf "%s-mosquitto" (include "wled-mcp.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Resolve the effective MQTT host the agent should connect to.
Embedded broker overrides any user-supplied host.
*/}}
{{- define "wled-mcp.mqttHost" -}}
{{- if .Values.mqtt.embedded.enabled -}}
{{- include "wled-mcp.mosquittoFullname" . -}}
{{- else -}}
{{- .Values.mqtt.host -}}
{{- end -}}
{{- end -}}

{{/*
Resolve the effective MQTT port.
*/}}
{{- define "wled-mcp.mqttPort" -}}
{{- if .Values.mqtt.embedded.enabled -}}1883{{- else -}}{{ .Values.mqtt.port }}{{- end -}}
{{- end -}}

{{/*
Name of the Secret that holds MQTT credentials (existing or generated).
Empty string when no credentials are needed (anonymous broker).
*/}}
{{- define "wled-mcp.mqttSecretName" -}}
{{- if .Values.mqtt.existingSecret -}}
{{- .Values.mqtt.existingSecret -}}
{{- else if or .Values.mqtt.username .Values.mqtt.password -}}
{{- printf "%s-mqtt" (include "wled-mcp.fullname" .) -}}
{{- end -}}
{{- end -}}
