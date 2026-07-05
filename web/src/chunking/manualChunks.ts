const vendorChunkRules: Array<{ chunk: string; markers: string[] }> = [
  {
    chunk: "react-vendor",
    markers: ["/node_modules/react/", "/node_modules/react-dom/", "/node_modules/scheduler/"],
  },
  {
    chunk: "tanstack-vendor",
    markers: ["/node_modules/@tanstack/react-query/", "/node_modules/@tanstack/react-router/"],
  },
  {
    chunk: "flow-vendor",
    markers: ["/node_modules/@xyflow/"],
  },
  {
    chunk: "ui-vendor",
    markers: ["/node_modules/lucide-react/", "/node_modules/motion/"],
  },
  {
    chunk: "workflow-yaml-vendor",
    markers: ["/node_modules/yaml/"],
  },
];

const featureChunkRules: Array<{ chunk: string; markers: string[] }> = [
  {
    chunk: "workflow-core",
    markers: [
      "/src/modules/workflow-runtime/",
      "/src/modules/workflow-studio/workflowApi.ts",
      "/src/modules/workflow-studio/workflowTypes.ts",
    ],
  },
  { chunk: "agent-console", markers: ["/src/modules/agent-console/"] },
  { chunk: "knowledge-center", markers: ["/src/modules/knowledge-center/"] },
  { chunk: "template-gallery", markers: ["/src/modules/template-gallery/"] },
  { chunk: "workflow-studio", markers: ["/src/modules/workflow-studio/"] },
  { chunk: "run-observatory", markers: ["/src/modules/run-observatory/", "/src/modules/runtime-trace/"] },
  { chunk: "global-command-center", markers: ["/src/modules/global-command-center/"] },
  { chunk: "project-command-center", markers: ["/src/modules/project-command-center/"] },
  { chunk: "model-gateway", markers: ["/src/modules/model-gateway/"] },
  { chunk: "prompt-library", markers: ["/src/modules/prompt-library/"] },
  { chunk: "tool-registry", markers: ["/src/modules/tool-registry/"] },
  { chunk: "tool-gateway", markers: ["/src/modules/tool-gateway/"] },
];

export function resolveAegisManualChunk(id: string): string | undefined {
  const normalizedId = id.replace(/\\/g, "/");
  const rule = [...vendorChunkRules, ...featureChunkRules].find(({ markers }) =>
    markers.some((marker) => normalizedId.includes(marker)),
  );

  return rule?.chunk;
}
