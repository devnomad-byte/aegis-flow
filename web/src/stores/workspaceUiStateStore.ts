import { createStore, type StoreApi } from "zustand/vanilla";

export type WorkspaceUiState = {
  selectedCanvasNodeId: string | null;
  selectedCanvasEdgeId: string | null;
  debugDraft: string;
  currentDebugRunId: string | null;
  inspectorTab: "overview" | "schema" | "trace" | "policy";
  timelineCursor: string | null;
  retrievalPlaygroundQuery: string;
  selectCanvasNode: (nodeId: string | null) => void;
  selectCanvasEdge: (edgeId: string | null) => void;
  setDebugDraft: (draft: string) => void;
  bindDebugRun: (runId: string | null) => void;
  setInspectorTab: (tab: WorkspaceUiState["inspectorTab"]) => void;
  setTimelineCursor: (cursor: string | null) => void;
  setRetrievalQuery: (query: string) => void;
  resetProjectScopedState: () => void;
};

const initialWorkspaceUiState = {
  selectedCanvasNodeId: null,
  selectedCanvasEdgeId: null,
  debugDraft: "",
  currentDebugRunId: null,
  inspectorTab: "overview" as const,
  timelineCursor: null,
  retrievalPlaygroundQuery: "",
};

export type WorkspaceUiStateStore = StoreApi<WorkspaceUiState>;

export function createWorkspaceUiStateStore() {
  return createStore<WorkspaceUiState>((set) => ({
    ...initialWorkspaceUiState,
    selectCanvasNode: (nodeId) => set({ selectedCanvasNodeId: nodeId, selectedCanvasEdgeId: null }),
    selectCanvasEdge: (edgeId) => set({ selectedCanvasEdgeId: edgeId, selectedCanvasNodeId: null }),
    setDebugDraft: (draft) => set({ debugDraft: draft }),
    bindDebugRun: (runId) => set({ currentDebugRunId: runId }),
    setInspectorTab: (tab) => set({ inspectorTab: tab }),
    setTimelineCursor: (cursor) => set({ timelineCursor: cursor }),
    setRetrievalQuery: (query) => set({ retrievalPlaygroundQuery: query }),
    resetProjectScopedState: () => set(initialWorkspaceUiState),
  }));
}
