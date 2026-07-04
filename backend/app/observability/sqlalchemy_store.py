from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.model_gateway.openai_compatible import redact_sensitive_text
from backend.app.observability.models import RuntimeTraceSpan
from backend.app.observability.schemas import RuntimeTraceSpanCreate, RuntimeTraceSpanRead

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "auth_token",
    "bearer",
    "credential",
    "credential_ref",
    "lease",
    "password",
    "payload",
    "prompt",
    "query",
    "raw",
    "request",
    "response",
    "secret",
    "secret_lease_id",
    "secret_lease_ref",
    "stderr",
    "stdout",
    "tool_payload",
}

_SUMMARY_KEYS = {"input_summary", "output_summary", "error_message", "schema_validation_error"}


class SqlAlchemyRuntimeTraceStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_span(self, request: RuntimeTraceSpanCreate) -> RuntimeTraceSpanRead:
        sanitized_request = request.model_copy(
            update={
                "attributes": sanitize_trace_value(request.attributes),
                "events": sanitize_trace_value(request.events),
                "links": sanitize_trace_value(request.links),
                "resource": sanitize_trace_value(request.resource),
            }
        )
        span = RuntimeTraceSpan(**sanitized_request.model_dump())
        self._session.add(span)
        await self._session.flush()
        await self._session.refresh(span)
        return RuntimeTraceSpanRead.model_validate(span)

    async def list_spans(
        self,
        *,
        project_id: UUID,
        run_id: str | None = None,
        node_id: str | None = None,
        trace_id: str | None = None,
        source_type: str | None = None,
        limit: int = 500,
    ) -> list[RuntimeTraceSpanRead]:
        conditions = [RuntimeTraceSpan.project_id == project_id]
        if run_id:
            conditions.append(RuntimeTraceSpan.run_id == run_id)
        if node_id:
            conditions.append(RuntimeTraceSpan.node_id == node_id)
        if trace_id:
            conditions.append(RuntimeTraceSpan.trace_id == trace_id)
        if source_type:
            conditions.append(RuntimeTraceSpan.source_type == source_type)
        result = await self._session.scalars(
            select(RuntimeTraceSpan)
            .where(*conditions)
            .order_by(RuntimeTraceSpan.start_time_unix_nano, RuntimeTraceSpan.created_at)
            .limit(limit)
        )
        return [
            _sanitize_span_read(RuntimeTraceSpanRead.model_validate(span)) for span in result.all()
        ]

    async def export_otlp_json(
        self,
        *,
        project_id: UUID,
        run_id: str | None = None,
        node_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        spans = await self.list_spans(
            project_id=project_id,
            run_id=run_id,
            node_id=node_id,
            trace_id=trace_id,
            limit=limit,
        )
        resource_groups: dict[tuple[tuple[str, str], ...], list[RuntimeTraceSpanRead]] = {}
        for span in spans:
            normalized_resource = span.resource or {"service.name": "aegis-flow-runtime"}
            resource_key = tuple(
                sorted(
                    (key, _otlp_scalar_to_string(value))
                    for key, value in normalized_resource.items()
                )
            )
            resource_groups.setdefault(resource_key, []).append(span)

        resource_spans: list[dict[str, Any]] = []
        for resource_key, grouped_spans in resource_groups.items():
            resource_spans.append(
                {
                    "resource": {
                        "attributes": [_otlp_key_value(key, value) for key, value in resource_key],
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "aegis-flow.runtime_trace", "version": "1.0"},
                            "spans": [_span_to_otlp(span) for span in grouped_spans],
                        }
                    ],
                }
            )
        return {"resourceSpans": resource_spans}


def sanitize_trace_value(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in _SUMMARY_KEYS:
                sanitized[key_text] = sanitize_trace_value(item, parent_key="")
            elif _is_sensitive_key(key_text):
                sanitized[key_text] = "[redacted]"
            else:
                sanitized[key_text] = sanitize_trace_value(item, parent_key=key_text)
        return sanitized
    if isinstance(value, list):
        return [sanitize_trace_value(item, parent_key=parent_key) for item in value]
    if isinstance(value, str):
        if parent_key and _is_sensitive_key(parent_key):
            return "[redacted]"
        return redact_sensitive_text(value)
    return value


def _sanitize_span_read(span: RuntimeTraceSpanRead) -> RuntimeTraceSpanRead:
    return span.model_copy(
        update={
            "attributes": sanitize_trace_value(span.attributes),
            "events": sanitize_trace_value(span.events),
            "links": sanitize_trace_value(span.links),
            "resource": sanitize_trace_value(span.resource),
        }
    )


def _span_to_otlp(span: RuntimeTraceSpanRead) -> dict[str, Any]:
    otlp_span: dict[str, Any] = {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "parentSpanId": span.parent_span_id,
        "name": span.span_name,
        "kind": _otlp_span_kind(span.span_kind),
        "startTimeUnixNano": str(span.start_time_unix_nano),
        "endTimeUnixNano": str(span.end_time_unix_nano),
        "attributes": [
            _otlp_key_value(key, value)
            for key, value in sorted(
                {
                    **span.attributes,
                    "aegis.project_id": str(span.project_id),
                    "aegis.run_id": span.run_id,
                    "aegis.node_id": span.node_id,
                    "aegis.workflow_ref": span.workflow_ref,
                    "aegis.component": span.component,
                    "aegis.source_type": span.source_type,
                    "aegis.source_id": span.source_id,
                    "aegis.duration_ms": span.duration_ms,
                }.items()
            )
            if value not in {"", None}
        ],
        "events": [_event_to_otlp(event) for event in span.events],
        "links": span.links,
        "status": {"code": "STATUS_CODE_OK" if span.status == "success" else "STATUS_CODE_ERROR"},
    }
    if not span.parent_span_id:
        otlp_span.pop("parentSpanId")
    return otlp_span


def _event_to_otlp(event: dict[str, Any]) -> dict[str, Any]:
    name = _otlp_scalar_to_string(event.get("name", "event"))
    attributes = event.get("attributes", {})
    return {
        "name": name,
        "attributes": [_otlp_key_value(key, value) for key, value in sorted(attributes.items())]
        if isinstance(attributes, dict)
        else [],
    }


def _otlp_span_kind(span_kind: str) -> str:
    return {
        "server": "SPAN_KIND_SERVER",
        "client": "SPAN_KIND_CLIENT",
        "producer": "SPAN_KIND_PRODUCER",
        "consumer": "SPAN_KIND_CONSUMER",
        "model": "SPAN_KIND_CLIENT",
        "tool": "SPAN_KIND_CLIENT",
        "internal": "SPAN_KIND_INTERNAL",
    }.get(span_kind, "SPAN_KIND_INTERNAL")


def _otlp_key_value(key: str, value: Any) -> dict[str, Any]:
    otlp_value: dict[str, bool | float | str]
    if isinstance(value, bool):
        otlp_value = {"boolValue": value}
    elif isinstance(value, int):
        otlp_value = {"intValue": str(value)}
    elif isinstance(value, float):
        otlp_value = {"doubleValue": value}
    else:
        otlp_value = {"stringValue": _otlp_scalar_to_string(value)}
    return {"key": key, "value": otlp_value}


def _otlp_scalar_to_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    return str(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(".", "_")
    parts = {part for part in normalized.split("_") if part}
    if parts & _SENSITIVE_KEYS:
        return True
    return any(
        phrase in normalized
        for phrase in {
            "api_key",
            "auth_token",
            "secret_lease",
            "tool_payload",
        }
    )
