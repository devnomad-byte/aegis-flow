{{- define "aegis-egress-proxy.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "aegis-egress-proxy.fullname" -}}
{{- $name := include "aegis-egress-proxy.name" . -}}
{{- default $name .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "aegis-egress-proxy.labels" -}}
app.kubernetes.io/name: {{ include "aegis-egress-proxy.name" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: aegis-flow
app.kubernetes.io/component: egress-proxy
aegis.flow/project: {{ .Values.projectRef | quote }}
{{- end -}}

{{- define "aegis-egress-proxy.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aegis-egress-proxy.name" . }}
aegis.flow/project: {{ .Values.projectRef | quote }}
{{- end -}}
