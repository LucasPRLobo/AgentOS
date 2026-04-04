import { createContext, useContext, useState, useCallback, useEffect } from "react";
import type { WorkspaceSummary } from "../types/api";
import { listWorkspaces } from "../api/client";

export interface WorkspacesState {
  workspaces: WorkspaceSummary[];
  loading: boolean;
  error: string | null;
  activeWorkspaceId: string | null;
  setActiveWorkspaceId: (id: string | null) => void;
  refresh: () => Promise<void>;
}

export const WorkspacesContext = createContext<WorkspacesState | null>(null);

export function useWorkspaces(): WorkspacesState {
  const ctx = useContext(WorkspacesContext);
  if (!ctx) throw new Error("useWorkspaces must be used within WorkspacesProvider");
  return ctx;
}

export function useWorkspacesProvider(): WorkspacesState {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listWorkspaces();
      setWorkspaces(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load workspaces");
      setWorkspaces([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { workspaces, loading, error, activeWorkspaceId, setActiveWorkspaceId, refresh };
}
