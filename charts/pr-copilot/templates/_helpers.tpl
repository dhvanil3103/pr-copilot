{{- define "pr-copilot.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "pr-copilot.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Usage: include "pr-copilot.selectorLabels" (list . "api") */}}
{{- define "pr-copilot.selectorLabels" -}}
{{- $ctx := index . 0 -}}
app.kubernetes.io/name: {{ $ctx.Chart.Name }}
app.kubernetes.io/instance: {{ $ctx.Release.Name }}
app.kubernetes.io/component: {{ index . 1 }}
{{- end -}}

{{/* Usage: include "pr-copilot.image" (list . .Values.image.api) */}}
{{- define "pr-copilot.image" -}}
{{- $ctx := index . 0 -}}
{{- $name := index . 1 -}}
{{- if $ctx.Values.image.registry -}}
{{- printf "%s/%s:%s" $ctx.Values.image.registry $name $ctx.Values.image.tag -}}
{{- else -}}
{{- printf "%s:%s" $name $ctx.Values.image.tag -}}
{{- end -}}
{{- end -}}

{{- define "pr-copilot.postgresHost" -}}{{ include "pr-copilot.fullname" . }}-postgres{{- end -}}
{{- define "pr-copilot.kafkaHeadless" -}}{{ include "pr-copilot.fullname" . }}-kafka-headless{{- end -}}

{{/* DATABASE_URL built from the Secret's password; $(VAR) expands env vars defined earlier. */}}
{{- define "pr-copilot.databaseEnv" -}}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef: { name: {{ .Values.existingSecret }}, key: postgres-password }
- name: DATABASE_URL
  value: "postgresql+asyncpg://prcopilot:$(POSTGRES_PASSWORD)@{{ include "pr-copilot.postgresHost" . }}:5432/prcopilot"
{{- end -}}

{{- define "pr-copilot.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
seccompProfile: { type: RuntimeDefault }
{{- end -}}

{{- define "pr-copilot.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities: { drop: ["ALL"] }
{{- end -}}

{{- define "pr-copilot.imagePullSecrets" -}}
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}
