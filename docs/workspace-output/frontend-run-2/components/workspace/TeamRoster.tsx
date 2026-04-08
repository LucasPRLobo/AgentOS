/* TeamRoster — right panel, agent/human cards with state indicators and progress */

import { useMemo } from 'react'
import type { AgentStatus, AgentState } from '../../types/workspace'

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

// ── State config ──────────────────────────────────────────────────

type StateConfig = { color: string; bg: string; label: string; pulse: boolean }

const STATE_CONFIG: Record<AgentState, StateConfig> = {
  running:   { color: '#f0a500', bg: '#1e1800', label: 'running',   pulse: true  },
  active:    { color: '#f0a500', bg: '#1e1800', label: 'active',    pulse: true  },
  waiting:   { color: '#7eb3e8', bg: '#1a2535', label: 'waiting',   pulse: false },
  pending:   { color: '#6b7a99', bg: '#161b27', label: 'pending',   pulse: false },
  succeeded: { color: '#4db68c', bg: '#152520', label: 'succeeded', pulse: false },
  failed:    { color: '#ff4f6d', bg: '#200f15', label: 'failed',    pulse: false },
  idle:      { color: '#3a4a5c', bg: '#12151a', label: 'idle',      pulse: false },
  dormant:   { color: '#2a3347', bg: '#0f1117', label: 'dormant',   pulse: false },
  suspended: { color: '#4a5a70', bg: '#141820', label: 'suspended', pulse: false },
}

// ── Skeleton ──────────────────────────────────────────────────────

function AgentSkeleton() {
  return (
    <div style={{
      background: '#161b27',
      border: '1px solid #2a3347',
      borderRadius: '8px',
      padding: '12px',
      marginBottom: '8px',
    }}>
      <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
        <div style={{ width: 36, height: 36, borderRadius: 8, background: '#1e2535', flexShrink: 0 }} />
        <div style={{ flex: 1 }}>
          <div style={{ height: 10, width: '50%', background: '#1e2535', borderRadius: 3, marginBottom: 6 }} />
          <div style={{ height: 8, width: '35%', background: '#1a2030', borderRadius: 3 }} />
        </div>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#2a3347' }} />
      </div>
    </div>
  )
}

// ── Agent card ────────────────────────────────────────────────────

function AgentCard({ agent }: { agent: AgentStatus }) {
  const sc = STATE_CONFIG[agent.state] ?? STATE_CONFIG.idle
  const initials = (agent.agent_name || agent.agent_id).slice(0, 2).toUpperCase()

  // Avatar color by agent type/role
  const roleHue = hashStringToHue(agent.role || agent.agent_id)
  const avatarBg = `hsl(${roleHue}, 30%, 18%)`
  const avatarColor = `hsl(${roleHue}, 60%, 65%)`

  return (
    <div style={{
      background: '#161b27',
      border: `1px solid ${agent.state === 'running' || agent.state === 'active' ? '#2a3a20' : '#2a3347'}`,
      borderLeft: `3px solid ${sc.color}`,
      borderRadius: '8px',
      padding: '12px',
      marginBottom: '8px',
      transition: 'border-color 0.2s',
    }}>
      <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
        {/* Avatar */}
        <div style={{
          width: '36px',
          height: '36px',
          borderRadius: '8px',
          background: avatarBg,
          color: avatarColor,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '12px',
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 700,
          flexShrink: 0,
          border: '1px solid rgba(255,255,255,0.06)',
        }}>
          {initials}
        </div>

        {/* Info */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }}>
            <span style={{
              fontSize: '12px',
              fontWeight: 600,
              color: '#c8d8ee',
              fontFamily: "'Syne', sans-serif",
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {agent.agent_name || agent.agent_id}
            </span>
          </div>
          <div style={{ fontSize: '10px', color: '#4a5a70', fontFamily: "'JetBrains Mono', monospace", marginBottom: '6px' }}>
            {agent.role}
          </div>

          {/* Status indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <div style={{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              background: sc.color,
              boxShadow: sc.pulse ? `0 0 6px ${sc.color}88` : 'none',
              animation: sc.pulse ? 'agentPulse 1.8s ease-in-out infinite' : 'none',
              flexShrink: 0,
            }} />
            <span style={{
              fontSize: '10px',
              color: sc.color,
              fontFamily: "'JetBrains Mono', monospace",
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}>
              {sc.label}
            </span>
          </div>
        </div>

        {/* Last active */}
        <span style={{
          fontSize: '9px',
          color: '#3a4a5c',
          fontFamily: 'monospace',
          flexShrink: 0,
          marginTop: '2px',
        }}>
          {relativeTime(agent.last_active)}
        </span>
      </div>

      {/* Current task */}
      {agent.current_task && (
        <div style={{
          marginTop: '10px',
          padding: '7px 10px',
          background: '#0f1117',
          borderRadius: '5px',
          border: '1px solid #1e2535',
        }}>
          <div style={{ fontSize: '9px', color: '#3a4a5c', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '3px' }}>
            Current task
          </div>
          <div style={{ fontSize: '11px', color: '#8090a8', lineHeight: 1.4, fontFamily: "'JetBrains Mono', monospace" }}>
            {agent.current_task}
          </div>
        </div>
      )}

      {/* Progress summary */}
      {agent.progress_summary && (
        <div style={{
          marginTop: '6px',
          fontSize: '10px',
          color: '#6b7a99',
          lineHeight: 1.45,
          fontStyle: 'italic',
        }}>
          {agent.progress_summary.length > 100
            ? agent.progress_summary.slice(0, 100) + '…'
            : agent.progress_summary}
        </div>
      )}
    </div>
  )
}

// ── Summary stats ─────────────────────────────────────────────────

function RosterStats({ team }: { team: AgentStatus[] }) {
  const counts = useMemo(() => {
    const r: Partial<Record<AgentState, number>> = {}
    for (const a of team) r[a.state] = (r[a.state] ?? 0) + 1
    return r
  }, [team])

  const tiles: { state: AgentState; label: string }[] = [
    { state: 'running', label: 'running' },
    { state: 'active', label: 'active' },
    { state: 'waiting', label: 'waiting' },
    { state: 'idle', label: 'idle' },
    { state: 'failed', label: 'failed' },
  ]

  const visibleTiles = tiles.filter(t => (counts[t.state] ?? 0) > 0 || t.state === 'running')

  return (
    <div style={{
      display: 'flex',
      gap: '6px',
      padding: '8px 16px',
      borderBottom: '1px solid #1e2535',
      overflowX: 'auto',
      scrollbarWidth: 'none',
    }}>
      {visibleTiles.map(({ state, label }) => {
        const c = STATE_CONFIG[state]
        const n = counts[state] ?? 0
        return (
          <div key={state} style={{
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            padding: '3px 8px',
            background: n > 0 ? c.bg : '#12151a',
            border: `1px solid ${n > 0 ? c.color + '33' : '#1e2535'}`,
            borderRadius: '4px',
            flexShrink: 0,
          }}>
            <div style={{
              width: '5px',
              height: '5px',
              borderRadius: '50%',
              background: n > 0 ? c.color : '#2a3347',
              animation: n > 0 && c.pulse ? 'agentPulse 1.8s ease-in-out infinite' : 'none',
            }} />
            <span style={{
              fontSize: '10px',
              fontFamily: "'JetBrains Mono', monospace",
              color: n > 0 ? c.color : '#2a3347',
              fontWeight: 600,
            }}>
              {n}
            </span>
            <span style={{ fontSize: '9px', color: '#3a4a5c', fontFamily: 'monospace' }}>
              {label}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── Main TeamRoster ───────────────────────────────────────────────

interface TeamRosterProps {
  team: AgentStatus[]
  loading?: boolean
  error?: string | null
  onRetry?: () => void
}

export function TeamRoster({ team, loading = false, error = null, onRetry }: TeamRosterProps) {
  const sorted = useMemo(() => {
    const stateOrder: AgentState[] = ['running', 'active', 'waiting', 'pending', 'idle', 'succeeded', 'failed', 'suspended', 'dormant']
    return [...team].sort((a, b) => {
      const ai = stateOrder.indexOf(a.state)
      const bi = stateOrder.indexOf(b.state)
      if (ai !== bi) return ai - bi
      return (a.agent_name || a.agent_id).localeCompare(b.agent_name || b.agent_id)
    })
  }, [team])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0f1117', overflow: 'hidden' }}>
      <style>{`
        @keyframes agentPulse {
          0%, 100% { opacity: 1; box-shadow: 0 0 6px currentColor; }
          50% { opacity: 0.5; box-shadow: 0 0 2px currentColor; }
        }
      `}</style>

      {/* Header */}
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid #2a3347',
        background: '#0f1117',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
      }}>
        <span style={{
          fontSize: '13px',
          fontWeight: 700,
          color: '#e8edf5',
          fontFamily: "'Syne', sans-serif",
          letterSpacing: '0.02em',
          flex: 1,
        }}>
          Team
        </span>
        <span style={{ fontSize: '10px', color: '#3a4a5c', fontFamily: 'monospace' }}>
          {team.length} member{team.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Stats summary */}
      {!loading && !error && team.length > 0 && (
        <RosterStats team={team} />
      )}

      {/* Scrollable list */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '10px 12px',
        scrollbarWidth: 'thin',
        scrollbarColor: '#2a3347 transparent',
      }}>
        {loading && (
          [...Array(4)].map((_, i) => <AgentSkeleton key={i} />)
        )}

        {error && !loading && (
          <div style={{ textAlign: 'center', padding: '32px 16px' }}>
            <div style={{ fontSize: '11px', color: '#ff4f6d', marginBottom: '12px' }}>{error}</div>
            {onRetry && (
              <button onClick={onRetry} style={retryBtnStyle}>Retry</button>
            )}
          </div>
        )}

        {!loading && !error && sorted.length === 0 && (
          <div style={{ textAlign: 'center', padding: '32px 16px', color: '#3a4a5c', fontSize: '12px' }}>
            No team members yet
          </div>
        )}

        {!loading && !error && sorted.map(agent => (
          <AgentCard key={agent.agent_id} agent={agent} />
        ))}
      </div>
    </div>
  )
}

// ── Utilities ─────────────────────────────────────────────────────

function hashStringToHue(str: string): number {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i)
    hash |= 0
  }
  return Math.abs(hash) % 360
}

const retryBtnStyle: React.CSSProperties = {
  background: '#1a3a5c',
  border: '1px solid #2a5080',
  borderRadius: '5px',
  color: '#7eb3e8',
  padding: '6px 16px',
  fontSize: '11px',
  cursor: 'pointer',
  fontFamily: "'JetBrains Mono', monospace",
}
