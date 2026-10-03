{{- define "agentdossier.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "agentdossier.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "agentdossier.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "agentdossier.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
app.kubernetes.io/name: {{ include "agentdossier.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "agentdossier.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agentdossier.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "agentdossier.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "agentdossier.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "agentdossier.secretName" -}}
{{- default (include "agentdossier.fullname" .) .Values.existingSecret -}}
{{- end -}}

{{- define "agentdossier.configMapName" -}}
{{- default (printf "%s-config" (include "agentdossier.fullname" .)) .Values.existingConfigMap -}}
{{- end -}}
