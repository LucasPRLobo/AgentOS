/* WorkspacePage — three-panel workspace view: BacklogPanel | BoardFeed | TeamRoster */

import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useWorkspaceSocket } from '../hooks/useWorkspaceSocket'
import { BoardFeed } from '../components/workspace/BoardFeed'
import { BacklogPanel } from '../components/workspace/BacklogPanel'
import { TeamRoster } from '../components/workspace/TeamRoster'
import type { WorkspaceState, WorkspaceConfig, CostBreakdown, WorkspaceStatus } from '../types/workspace'

// ── Utilities ─────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// ── Header ────────────────────────────────────────────────────────

function WorkspaceHeader({
  config,
  status,
  cost,
  connected,
  lastActive,
  onPause,
  onResume,
}: {
  config: WorkspaceConfig
  status: WorkspaceStatus
  cost: CostBreakdown | null
  connected: boolean
  lastActive: string
  onPause: () => void
  onResume: () => void
}) {
  const statusColors: Record<WorkspaceStatus, { color: string; bg: string }> = {
    active:    { color: '#4db68c', bg: '#152520' },
    paused:    { color: '#f0a500', bg: '#1e1800' },
    completed: { color: '#7eb3e8', bg: '#1a2535' },
  }
  const sc = statusColors[status]
  const budgetPct = cost?.consumed_pct ?? 0
  const budgetColor = budgetPct > 80 ? '#ff4f6d' : budgetPct > 50 ? '#f0a500' : '#4db68c'

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '16px',
      padding: '10px 20px',
      background: '#0b0e17',
      borderBottom: '1px solid #2a3347',
      flexShrink: 0,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <h1 style={{
            margin: 0,
            fontSize: '15px',
            fontWeight: 800,
            color: '#e8edf5',
            fontFamily: "'Syne', sans-serif",
            letterSpacing: '-0.01em',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {config.name}
          </h1>
          <span style={{
            padding: '2px 8px',
            borderRadius: '4px',
            fontSize: '10px',
            fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            background: sc.bg,
            color: sc.color,
            border: `1px solid ${sc.color}33`,
            flexShrink: 0,
          }}>
            {status}
          </span>
        </div>
        <div style={{
          fontSize: '11px',
          color: '#4a5a70',
          marginTop: '2px',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          maxWidth: '500px',
        }}>
          {config.goal}
        </div>
      </div>

      {cost && (
        <div style={{ flexShrink: 0, textAlign: 'right' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <div style={{ width: '80px', height: '4px', background: '#1e2535', borderRadius: '2px', overflow: 'hidden' }}>
              <div style={{
                width: `${Math.min(budgetPct, 100)}%`,
                height: '100%',
                background: budgetColor,
                borderRadius: '2px',
                transition: 'width 0.3s, background 0.3s',
              }} />
            </div>
            <span style={{ fontSize: '10px', color: budgetColor, fontFamily: 'monospace', fontWeight: 600 }}>
              {Math.round(budgetPct)}%
            </span>
          </div>
          <div style={{ fontSize: '9px', color: '#3a4a5c', fontFamily: 'monospace', textAlign: 'right' }}>
            ${cost.total_usd.toFixed(4)} used
            {cost.budget_usd ? ` / $${cost.budget_usd.toFixed(2)}` : ''}
          </div>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: '5px', flexShrink: 0 }}>
        <div style={{
          width: '7px',
          height: '7px',
          borderRadius: '50%',
          background: connected ? '#4db68c' : '#3a4a5c',
          boxShadow: connected ? '0 0 6px #4db68c66' : 'none',
        }} />
        <span style={{ fontSize: '9px', color: '#3a4a5c', fontFamily: 'monospace' }}>
          {connected ? 'live' : 'offline'}
        </span>
      </div>

      <div style={{ fontSize: '9px', color: '#2a3347', fontFamily: 'monospace', flexShrink: 0 }}>
        {relativeTime(lastActive)}
      </div>

      <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
        {status === 'active' ? (
          <button onClick={onPause} style={controlBtnStyle('#1e1800', '#5c3800', '#f0a500')}>
            ⏸ Pause
          </button>
        ) : status === 'paused' ? (
          <button onClick={onResume} style={controlBtnStyle('#152520', '#1f5040', '#4db68c')}>
            ▶ Resume
          </button>
        ) : null}
      </div>
    </div>
  )
}

function controlBtnStyle(bg: string, border: string, color: string): React.CSSProperties {
  return {
    background: bg,
    border: `1px solid ${border}`,
    borderRadius: '5px',
    color,
    fontSize: '11px',
    padding: '5px 12px',
    cursor: 'pointer',
    fontFamily: "'JetBrains Mono', monospace",
    fontWeight: 600,
  }
}

// ── Loading skeleton page ─────────────────────────────────────────

function LoadingPage() {
  return (
    <div style={{ ...shellStyle, alignItems: 'center', justifyContent: 'center' }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <div style={{ textAlign: 'center' }}>
        <div style={{
          width: '32px',
          height: '32px',
          border: '2px solid #2a3347',
          borderTop: '2px solid #f0a500',
          borderRadius: '50%',
          margin: '0 auto 16px',
          animation: 'spin 0.8s linear infinite',
        }} />
        <div style={{ fontSize: '13px', color: '#4a5a70', fontFamily: "'JetBrains Mono', monospace" }}>
          Loading workspace…
        </div>
      </div>
    </div>
  )
}

// ── Error page ────────────────────────────────────────────────────

function ErrorPage({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div style={{ ...shellStyle, alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center', maxWidth: '360px' }}>
        <div style={{ fontSize: '36px', marginBottom: '16px', opacity: 0.4 }}>⚠</div>
        <div style={{ fontSize: '14px', color: '#ff4f6d', marginBottom: '8px', fontFamily: "'Syne', sans-serif", fontWeight: 700 }}>
          Failed to load workspace
        </div>
        <div style={{ fontSize: '12px', color: '#4a5a70', marginBottom: '20px', fontFamily: 'monospace' }}>
          {message}
        </div>
        <button
          onClick={onRetry}
          style={{
            background: '#1a3a5c',
            border: '1px solid #2a5080',
            borderRadius: '6px',
            color: '#7eb3e8',
            padding: '8px 20px',
            fontSize: '12px',
            cursor: 'pointer',
            fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 600,
          }}
        >
          Try Again
        </button>
      </div>
    </div>
  )
}

// ── Status bar ────────────────────────────────────────────────────

function StatusBar({ boardVersion, teamCount, runningCount, tasksDone, tasksTotal, connected, workspaceId }: {
  boardVersion?: number
  teamCount: number
  runningCount: number
  tasksDone: number
  tasksTotal: number
  connected: boolean
  workspaceId: string
}) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '20px',
      padding: '5px 20px',
      background: '#080b12',
      borderTop: '1px solid #1e2535',
      flexShrink: 0,
    }}>
      <StatusItem label="board" value={boardVersion !== undefined ? `v${boardVersion}` : '—'} color="#4a5a70" />
      <StatusItem label="team" value={`${runningCount}/${teamCount} active`} color="#4a5a70" />
      <StatusItem label="tasks" value={`${tasksDone}/${tasksTotal} done`} color="#4a5a70" />
      <div style={{ flex: 1 }} />
      <span style={{ fontSize: '9px', color: '#2a3347', fontFamily: 'monospace' }}>
        {workspaceId}
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <div style={{ width: '5px', height: '5px', borderRadius: '50%', background: connected ? '#4db68c' : '#3a4a5c' }} />
        <span style={{ fontSize: '9px', color: '#2a3347', fontFamily: 'monospace' }}>
          {connected ? 'ws:connected' : 'ws:offline'}
        </span>
      </div>
    </div>
  )
}

function StatusItem({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ display: 'flex', gap: '4px', alignItems: 'baseline' }}>
      <span style={{ fontSize: '9px', color: '#2a3040', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
      <span style={{ fontSize: '10px', color, fontFamily: "'JetBrains Mono', monospace" }}>{value}</span>
    </div>
  )
}

// ── Main WorkspacePage ────────────────────────────────────────────

export function WorkspacePage() {
  const { id: workspaceId, workspace_id: workspaceIdAlt } = useParams<{ id?: string; workspace_id?: string }>()
  const resolvedId = workspaceId ?? workspaceIdAlt

  const { board, backlog, team, connected, error: wsError, retry } = useWorkspaceSocket(resolvedId)

  const [wsState, setWsState] = useState<WorkspaceState | null>(null)
  const [restLoading, setRestLoading] = useState(true)
  const [restError, setRestError] = useState<string | null>(null)

  const fetchWorkspaceState = useCallback(async () => {
    if (!resolvedId) return
    setRestLoading(true)
    setRestError(null)
    try {
      const resp = await fetch(`/api/workspaces/${resolvedId}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      const data: WorkspaceState = await resp.json()
      setWsState(data)
    } catch (err) {
      setRestError(err instanceof Error ? err.message : 'Failed to load workspace')
    } finally {
      setRestLoading(false)
    }
  }, [resolvedId])

  useEffect(() => { fetchWorkspaceState() }, [fetchWorkspaceState])

  const handlePause = useCallback(async () => {
    if (!resolvedId) return
    await fetch(`/api/workspaces/${resolvedId}/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'pause' }),
    })
    fetchWorkspaceState()
  }, [resolvedId, fetchWorkspaceState])

  const handleResume = useCallback(async () => {
    if (!resolvedId) return
    await fetch(`/api/workspaces/${resolvedId}/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'resume' }),
    })
    fetchWorkspaceState()
  }, [resolvedId, fetchWorkspaceState])

  const handlePost = useCallback(async (content: string, section = 'post') => {
    if (!resolvedId) return
    await fetch(`/api/workspaces/${resolvedId}/board`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, section, speech_act: 'inform' }),
    })
  }, [resolvedId])

  if (restLoading) return <LoadingPage />
  if (restError || !wsState) return (
    <ErrorPage
      message={restError ?? 'Workspace not found'}
      onRetry={() => { fetchWorkspaceState(); retry() }}
    />
  )

  const liveBoard = board ?? wsState.board
  const liveBacklog = backlog.length > 0 ? backlog : wsState.backlog
  const liveTeam = team.length > 0 ? team : wsState.team

  return (
    <div style={shellStyle}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #2a3347; border-radius: 2px; }
        ::-webkit-scrollbar-thumb:hover { background: #3a4a5c; }
      `}</style>

      <WorkspaceHeader
        config={wsState.config}
        status={wsState.status}
        cost={wsState.cost}
        connected={connected}
        lastActive={wsState.last_active}
        onPause={handlePause}
        onResume={handleResume}
      />

      <div style={bodyStyle}>
        <div style={leftPanelStyle}>
          <BacklogPanel
            tasks={liveBacklog}
            loading={false}
            error={wsError && liveBacklog.length === 0 ? wsError : null}
            onRetry={retry}
          />
        </div>

        <div style={centerPanelStyle}>
          <BoardFeed
            board={liveBoard}
            loading={false}
            error={wsError && !liveBoard ? wsError : null}
            onRetry={retry}
            onPost={handlePost}
          />
        </div>

        <div style={rightPanelStyle}>
          <TeamRoster
            team={liveTeam}
            loading={false}
            error={wsError && liveTeam.length === 0 ? wsError : null}
            onRetry={retry}
          />
        </div>
      </div>

      <StatusBar
        boardVersion={liveBoard?.version}
        teamCount={liveTeam.length}
        runningCount={liveTeam.filter(a => a.state === 'running' || a.state === 'active').length}
        tasksDone={liveBacklog.filter(t => t.status === 'done' || t.status === 'completed').length}
        tasksTotal={liveBacklog.length}
        connected={connected}
        workspaceId={resolvedId ?? ''}
      />
    </div>
  )
}

// ── Layout styles ─────────────────────────────────────────────────

const shellStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  height: '100vh',
  background: '#0f1117',
  overflow: 'hidden',
  fontFamily: "'Syne', sans-serif",
}

const bodyStyle: React.CSSProperties = {
  flex: 1,
  display: 'grid',
  gridTemplateColumns: '280px 1fr 260px',
  overflow: 'hidden',
}

const leftPanelStyle: React.CSSProperties = {
  borderRight: '1px solid #2a3347',
  overflow: 'hidden',
  display: 'flex',
  flexDirection: 'column',
}

const centerPanelStyle: React.CSSProperties = {
  overflow: 'hidden',
  display: 'flex',
  flexDirection: 'column',
  position: 'relative',
}

const rightPanelStyle: React.CSSProperties = {
  borderLeft: '1px solid #2a3347',
  overflow: 'hidden',
  display: 'flex',
  flexDirection: 'column',
}
