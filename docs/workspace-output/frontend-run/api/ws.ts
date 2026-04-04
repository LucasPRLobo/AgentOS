import type { WorkspaceWSMessage, WorkflowWSMessage } from "../types/api";

const WS_BASE = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8420";

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15000] as const;

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export interface WSConnectionOptions<T> {
  url: string;
  onMessage: (msg: T) => void;
  onStatusChange?: (status: ConnectionStatus) => void;
  /** Message to send immediately after connection opens (e.g. subscribe) */
  initMessage?: unknown;
}

export interface WSConnection {
  close(): void;
  send(data: unknown): void;
}

/**
 * Low-level WebSocket connection with exponential backoff reconnection.
 */
export function createWSConnection<T>(opts: WSConnectionOptions<T>): WSConnection {
  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  let disposed = false;

  function setStatus(s: ConnectionStatus) {
    opts.onStatusChange?.(s);
  }

  function connect() {
    if (disposed) return;
    setStatus("connecting");

    ws = new WebSocket(opts.url);

    ws.onopen = () => {
      attempt = 0;
      setStatus("connected");
      if (opts.initMessage != null) {
        ws!.send(JSON.stringify(opts.initMessage));
      }
    };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as T;
        opts.onMessage(data);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      if (disposed) return;
      setStatus("disconnected");
      const delay = RECONNECT_DELAYS[Math.min(attempt, RECONNECT_DELAYS.length - 1)];
      attempt++;
      reconnectTimer = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // onclose will fire after onerror, triggering reconnect
      ws?.close();
    };
  }

  connect();

  return {
    close() {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    },
    send(data: unknown) {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
      }
    },
  };
}

// ---------------------------------------------------------------------------
// Workspace WebSocket (auto-streaming, no subscribe message needed)
// ---------------------------------------------------------------------------

export function connectWorkspaceWS(
  workspaceId: string,
  onMessage: (msg: WorkspaceWSMessage) => void,
  onStatusChange?: (status: ConnectionStatus) => void,
): WSConnection {
  return createWSConnection<WorkspaceWSMessage>({
    url: `${WS_BASE}/ws/workspace/${workspaceId}`,
    onMessage,
    onStatusChange,
  });
}

// ---------------------------------------------------------------------------
// Workflow WebSocket (requires subscribe message after connect)
// ---------------------------------------------------------------------------

export function connectWorkflowWS(
  workflowId: string,
  onMessage: (msg: WorkflowWSMessage) => void,
  onStatusChange?: (status: ConnectionStatus) => void,
  sinceSeq = 0,
): WSConnection {
  return createWSConnection<WorkflowWSMessage>({
    url: `${WS_BASE}/ws`,
    onMessage,
    onStatusChange,
    initMessage: { type: "subscribe", workflow_id: workflowId, since_seq: sinceSeq },
  });
}
