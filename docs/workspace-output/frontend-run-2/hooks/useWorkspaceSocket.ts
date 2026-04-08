/* useWorkspaceSocket — manages WebSocket lifecycle for a workspace */

import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  BoardState,
  BacklogTask,
  AgentStatus,
  BoardPost,
  WsSnapshot,
} from '../types/workspace'

interface UseWorkspaceSocketReturn {
  board: BoardState | null
  backlog: BacklogTask[]
  team: AgentStatus[]
  connected: boolean
  error: string | null
  retry: () => void
}

function buildWsUrl(workspaceId: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws/workspace/${workspaceId}`
}

export function useWorkspaceSocket(workspaceId: string | undefined): UseWorkspaceSocketReturn {
  const [board, setBoard] = useState<BoardState | null>(null)
  const [backlog, setBacklog] = useState<BacklogTask[]>([])
  const [team, setTeam] = useState<AgentStatus[]>([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retryCount, setRetryCount] = useState(0)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    if (!workspaceId || !mountedRef.current) return

    // Clean up existing connection
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.onmessage = null
      wsRef.current.onerror = null
      wsRef.current.close()
      wsRef.current = null
    }

    setError(null)

    try {
      const ws = new WebSocket(buildWsUrl(workspaceId))
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) return
        setConnected(true)
        setError(null)
        ws.send(JSON.stringify({ type: 'subscribe', workspace_id: workspaceId }))
      }

      ws.onmessage = (ev) => {
        if (!mountedRef.current) return
        try {
          const event = JSON.parse(ev.data) as { type: string; data: unknown }
          handleEvent(event)
        } catch {
          // ignore malformed messages
        }
      }

      ws.onerror = () => {
        if (!mountedRef.current) return
        setError('WebSocket connection error')
      }

      ws.onclose = (ev) => {
        if (!mountedRef.current) return
        setConnected(false)
        wsRef.current = null

        // Auto-reconnect with backoff (max 30s)
        if (ev.code !== 1000) {
          const delay = Math.min(1000 * Math.pow(1.5, Math.min(retryCount, 8)), 30000)
          reconnectTimer.current = setTimeout(() => {
            if (mountedRef.current) {
              setRetryCount(c => c + 1)
            }
          }, delay)
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to connect')
    }
  }, [workspaceId, retryCount])

  function handleEvent(event: { type: string; data: unknown }) {
    const d = event.data as Record<string, unknown>

    switch (event.type) {
      case 'snapshot': {
        const snap = d as WsSnapshot
        setBoard(snap.board ?? null)
        setBacklog(snap.backlog ?? [])
        setTeam(snap.team ?? [])
        break
      }
      case 'board_post': {
        const post = d as BoardPost
        setBoard(prev => {
          if (!prev) return prev
          const updatedPosts = [post, ...prev.recent_posts].slice(0, 50)
          return {
            ...prev,
            version: prev.version + 1,
            recent_posts: updatedPosts,
            announcements: post.section === 'announcement'
              ? [...prev.announcements, post]
              : prev.announcements,
            alerts: post.section === 'alert'
              ? [post, ...prev.alerts]
              : prev.alerts,
            open_questions: post.section === 'question'
              ? [...prev.open_questions, post]
              : prev.open_questions,
            decisions: post.section === 'decision'
              ? [...prev.decisions, post]
              : prev.decisions,
          }
        })
        break
      }
      case 'backlog_update': {
        if (Array.isArray(d)) {
          setBacklog(d as BacklogTask[])
        } else {
          // Single task update
          const task = d as BacklogTask
          setBacklog(prev => {
            const idx = prev.findIndex(t => t.task_id === task.task_id)
            if (idx >= 0) {
              const next = [...prev]
              next[idx] = task
              return next
            }
            return [...prev, task]
          })
        }
        break
      }
      case 'agent_status': {
        const updated = d as AgentStatus
        setTeam(prev => {
          const idx = prev.findIndex(a => a.agent_id === updated.agent_id)
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = updated
            return next
          }
          return [...prev, updated]
        })
        break
      }
      case 'error': {
        const errMsg = (d as { message?: string }).message ?? 'Unknown error'
        setError(errMsg)
        break
      }
    }
  }

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close(1000, 'component unmounted')
        wsRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, retryCount])

  const retry = useCallback(() => {
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    setRetryCount(c => c + 1)
  }, [])

  return { board, backlog, team, connected, error, retry }
}
