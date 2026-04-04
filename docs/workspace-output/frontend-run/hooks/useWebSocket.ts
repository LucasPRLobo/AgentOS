import { useEffect, useRef, useCallback, useMemo, useState } from "react";
import {
  connectWorkspaceWS,
  connectWorkflowWS,
  type ConnectionStatus,
  type WSConnection,
} from "../api/ws";
import type { WorkspaceWSMessage, WorkflowWSMessage } from "../types/api";

// ---------------------------------------------------------------------------
// Subscriber-based dispatch pattern
// ---------------------------------------------------------------------------

type Unsubscribe = () => void;

/**
 * Connect to a workspace's live WebSocket and dispatch events to subscribers.
 *
 * Usage:
 * ```ts
 * const { subscribe, status } = useWorkspaceWS(workspaceId);
 *
 * useEffect(() => {
 *   return subscribe((msg) => {
 *     if (msg.type === "board_post") { ... }
 *   });
 * }, [subscribe]);
 * ```
 */
export function useWorkspaceWS(workspaceId: string | undefined) {
  const listeners = useRef(new Set<(msg: WorkspaceWSMessage) => void>());
  const connRef = useRef<WSConnection | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");

  useEffect(() => {
    if (!workspaceId) {
      setStatus("disconnected");
      return;
    }

    connRef.current = connectWorkspaceWS(
      workspaceId,
      (msg) => {
        for (const fn of listeners.current) fn(msg);
      },
      setStatus,
    );

    return () => {
      connRef.current?.close();
      connRef.current = null;
    };
  }, [workspaceId]);

  const subscribe = useCallback((fn: (msg: WorkspaceWSMessage) => void): Unsubscribe => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  return useMemo(() => ({ subscribe, status }), [subscribe, status]);
}

/**
 * Connect to a workflow event stream and dispatch events to subscribers.
 *
 * Usage:
 * ```ts
 * const { subscribe, status } = useWorkflowWS(workflowId);
 *
 * useEffect(() => {
 *   return subscribe((msg) => {
 *     if (msg.type === "event") { ... }
 *   });
 * }, [subscribe]);
 * ```
 */
export function useWorkflowWS(workflowId: string | undefined, sinceSeq = 0) {
  const listeners = useRef(new Set<(msg: WorkflowWSMessage) => void>());
  const connRef = useRef<WSConnection | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");

  useEffect(() => {
    if (!workflowId) {
      setStatus("disconnected");
      return;
    }

    connRef.current = connectWorkflowWS(
      workflowId,
      (msg) => {
        for (const fn of listeners.current) fn(msg);
      },
      setStatus,
      sinceSeq,
    );

    return () => {
      connRef.current?.close();
      connRef.current = null;
    };
  }, [workflowId, sinceSeq]);

  const subscribe = useCallback((fn: (msg: WorkflowWSMessage) => void): Unsubscribe => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  }, []);

  return useMemo(() => ({ subscribe, status }), [subscribe, status]);
}
