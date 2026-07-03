import { useQuery } from "@tanstack/react-query";

import {
  listModelGatewayInvocations,
  type ModelGatewayInvocation,
} from "./modelGatewayApi";

type ModelInvocationTracePanelProps = {
  projectId: string;
  runId: string;
  nodeId: string;
  traceId: string;
};

export function ModelInvocationTracePanel({
  projectId,
  runId,
  nodeId,
  traceId,
}: ModelInvocationTracePanelProps) {
  const invocationsQuery = useQuery({
    queryFn: () =>
      listModelGatewayInvocations(projectId, {
        run_id: runId,
        node_id: nodeId,
        trace_id: traceId,
      }),
    queryKey: [
      "project",
      projectId,
      "model-gateway",
      "invocations",
      { nodeId, runId, traceId },
    ],
  });

  if (invocationsQuery.isLoading) {
    return <div className="preview-alert">Loading model invocation trace</div>;
  }

  if (invocationsQuery.isError) {
    return (
      <div className="preview-alert preview-alert-danger" role="alert">
        {(invocationsQuery.error as Error).message}
      </div>
    );
  }

  const invocations = invocationsQuery.data?.invocations ?? [];
  if (!invocations.length) {
    return <div className="preview-alert">No model invocations for this run scope</div>;
  }

  return (
    <section className="model-trace-panel" aria-label="Model Invocation Trace">
      <div className="telemetry">MODEL INVOCATION TRACE</div>
      <div className="model-trace-grid">
        {invocations.map((invocation) => (
          <InvocationRow invocation={invocation} key={invocation.id} />
        ))}
      </div>
    </section>
  );
}

function InvocationRow({ invocation }: { invocation: ModelGatewayInvocation }) {
  return (
    <article className={`model-trace-row model-trace-${invocation.status}`}>
      <div className="model-trace-row-main">
        <div>
          <strong>{invocation.model_name}</strong>
          <span className="telemetry">{invocation.provider}</span>
        </div>
        <span className={`status-pill model-trace-status-${invocation.status}`}>
          {invocation.status}
        </span>
      </div>
      <div className="model-trace-metrics">
        <Metric label="Prompt" value={invocation.prompt_version || "unversioned"} />
        <Metric label="Usage" value={`${getTotalTokens(invocation)} tokens`} />
        <Metric label="Latency" value={`${invocation.latency_ms}ms`} />
        <Metric label="Schema" value={invocation.schema_validation_status} />
      </div>
      <div className="model-trace-hash">
        <span className="telemetry">REQUEST HASH</span>
        <code>{invocation.request_hash}</code>
      </div>
      {invocation.output_schema_ref ? (
        <div className="model-trace-hash">
          <span className="telemetry">OUTPUT SCHEMA</span>
          <code>{invocation.output_schema_ref}</code>
        </div>
      ) : null}
      {invocation.error_message || invocation.schema_validation_error ? (
        <div className="preview-alert preview-alert-danger">
          {invocation.schema_validation_error || invocation.error_message}
        </div>
      ) : null}
    </article>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function getTotalTokens(invocation: ModelGatewayInvocation): number {
  const totalTokens = invocation.usage.total_tokens;
  if (typeof totalTokens === "number") {
    return totalTokens;
  }
  return 0;
}
