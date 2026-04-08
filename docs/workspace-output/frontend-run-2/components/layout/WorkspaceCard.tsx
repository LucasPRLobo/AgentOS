/* WorkspaceCard — individual workspace card in the list grid */

import React from 'react'
import type { WorkspaceSummary, WorkspaceStatus } from '../../types/workspace'

/* ── Time formatting ─────────────────────────────────────────────── */

function formatRelative(iso: string): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 60) return 'just now'
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/* ── Status config ───────────────────────────────────────────────── */

const STATUS_CONFIG: Record<WorkspaceStatus, { color: string; bg: string; label: string; glow: string }> = {
  active: {
    color: '#10b981',
    bg: 'rgba(16, 185, 129, 0.10)',
    label: 'Active',
    glow: 'rgba(16, 185, 129, 0.15)',
  },
  paused: {
    color: '#f59e0b',
    bg: 'rgba(245, 158, 11, 0.10)',
    label: 'Paused',
    glow: 'rgba(245, 158, 11, 0.1)',
  },
  completed: {
    color: '#38bdf8',
    bg: 'rgba(56, 189, 248, 0.10)',
    label: 'Completed',
    glow: 'rgba(56, 189, 248, 0.1)',
  },
}

/* ── WorkspaceCard ───────────────────────────────────────────────── */

export interface WorkspaceCardProps {
  ws: WorkspaceSummary
  index?: number
  onClick: () => void
}

export function WorkspaceCard({ ws, index = 0, onClick }: WorkspaceCardProps) {
  const statusCfg = STATUS_CONFIG[ws.status] ?? STATUS_CONFIG.active
  const taskPct = ws.tasks_total > 0 ? Math.min(100, Math.round((ws.tasks_done / ws.tasks_total) * 100)) : 0
  const budgetPct = Math.min(100, Math.round(ws.budget_used_pct))
  const budgetDanger = ws.budget_used_pct > 80
  const budgetWarn = !budgetDanger && ws.budget_used_pct > 60
  const budgetBarColor = budgetDanger ? '#f43f5e' : budgetWarn ? '#f59e0b' : '#10b981'

  return (
    <div
      style={{
        ...cardStyles.card,
        animationDelay: `${index * 50}ms`,
      }}
      onClick={onClick}
      onMouseEnter={e => {
        const el = e.currentTarget as HTMLDivElement
        el.style.background = '#181b28'
        el.style.borderColor = '#2a2d40'
        el.style.transform = 'translateY(-1px)'
        el.style.boxShadow = `0 4px 20px rgba(0,0,0,0.4), 0 0 0 1px rgba(30,32,48,0.6)`
      }}
      onMouseLeave={e => {
        const el = e.currentTarget as HTMLDivElement
        el.style.background = '#121420'
        el.style.borderColor = '#1e2030'
        el.style.transform = 'translateY(0)'
        el.style.boxShadow = '0 2px 8px rgba(0,0,0,0.3)'
      }}
    >
      {/* Status accent top bar */}
      <div style={{ ...cardStyles.accentBar, background: statusCfg.color, boxShadow: `0 0 8px ${statusCfg.glow}` }} />

      {/* Header row */}
      <div style={cardStyles.header}>
        <h3 style={cardStyles.name}>{ws.name}</h3>
        <span style={{ ...cardStyles.badge, color: statusCfg.color, background: statusCfg.bg }}>
          {ws.status === 'active' && <span style={{ ...cardStyles.pulseDot, background: statusCfg.color }} />}
          {statusCfg.label}
        </span>
      </div>

      {/* Goal */}
      <p style={cardStyles.goal} title={ws.goal}>{ws.goal}</p>

      {/* Task progress */}
      <div style={cardStyles.progressSection}>
        <div style={cardStyles.progressLabel}>
          <span style={cardStyles.labelText}>Tasks</span>
          <span style={cardStyles.labelValue}>
            <span style={cardStyles.countNum}>{ws.tasks_done}</span>
            <span style={cardStyles.countDim}>/{ws.tasks_total}</span>
          </span>
        </div>
        <div style={cardStyles.track}>
          <div
            style={{
              ...cardStyles.trackFill,
              width: `${taskPct}%`,
              background: taskPct >= 100
                ? '#10b981'
                : `linear-gradient(90deg, #10b981 0%, #059669 100%)`,
            }}
          />
        </div>
      </div>

      {/* Metrics row */}
      <div style={cardStyles.metricsRow}>
        {/* Team size */}
        <div style={cardStyles.metric}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#8b8fa8" strokeWidth="2" strokeLinecap="round">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
          <span style={cardStyles.metricNum}>{ws.team_size}</span>
          <span style={cardStyles.metricLabel}>agents</span>
        </div>

        {/* Budget */}
        {ws.budget_used_pct > 0 && (
          <div style={cardStyles.metric}>
            <span style={{ ...cardStyles.dot, background: budgetBarColor }} />
            <span style={{ ...cardStyles.metricNum, color: budgetDanger ? '#f43f5e' : '#e2e4ed' }}>
              {budgetPct}%
            </span>
            <span style={cardStyles.metricLabel}>budget</span>
          </div>
        )}

        {/* Last active — pushed right */}
        <div style={{ ...cardStyles.metric, marginLeft: 'auto' }}>
          <span style={cardStyles.metricLabel}>{formatRelative(ws.last_active)}</span>
        </div>
      </div>

      {/* Budget bar at card bottom */}
      {ws.budget_used_pct > 0 && (
        <div style={cardStyles.budgetTrack}>
          <div
            style={{
              ...cardStyles.budgetFill,
              width: `${budgetPct}%`,
              background: budgetBarColor,
              opacity: budgetDanger ? 1 : 0.7,
            }}
          />
        </div>
      )}
    </div>
  )
}

/* ── Card Skeleton ───────────────────────────────────────────────── */

export function WorkspaceCardSkeleton({ index = 0 }: { index?: number }) {
  return (
    <div
      style={{
        ...cardStyles.card,
        cursor: 'default',
        animationDelay: `${index * 60}ms`,
      }}
    >
      <div style={{ ...cardStyles.accentBar, background: '#1e2030' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <Skel width="55%" height={16} />
        <Skel width={60} height={20} radius={9999} />
      </div>
      <Skel width="85%" height={12} style={{ marginBottom: 6 }} />
      <Skel width="65%" height={12} style={{ marginBottom: 16 }} />
      <Skel width="100%" height={4} style={{ marginBottom: 16 }} />
      <div style={{ display: 'flex', gap: 12 }}>
        <Skel width={60} height={12} />
        <Skel width={60} height={12} />
        <Skel width={50} height={12} style={{ marginLeft: 'auto' }} />
      </div>
    </div>
  )
}

function Skel({
  width,
  height,
  radius,
  style,
}: {
  width: string | number
  height: number
  radius?: number
  style?: React.CSSProperties
}) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius: radius ?? 3,
        background: 'linear-gradient(90deg, #1a1c2a 25%, #1f2235 50%, #1a1c2a 75%)',
        backgroundSize: '200% 100%',
        animation: 'ws-shimmer 1.4s ease infinite',
        flexShrink: 0,
        ...style,
      }}
    />
  )
}

/* ── Styles ─────────────────────────────────────────────────────── */

const cardStyles: Record<string, React.CSSProperties> = {
  card: {
    position: 'relative',
    background: '#121420',
    border: '1px solid #1e2030',
    borderRadius: 10,
    padding: '20px 18px 16px',
    cursor: 'pointer',
    transition: 'background 160ms, border-color 160ms, transform 160ms, box-shadow 160ms',
    boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
    animation: 'ws-slide-up 320ms ease both',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
  },
  accentBar: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: 2,
    borderRadius: '10px 10px 0 0',
  },
  header: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 10,
    marginBottom: 8,
    marginTop: 4,
  },
  name: {
    fontSize: 14,
    fontWeight: 600,
    color: '#e2e4ed',
    letterSpacing: '-0.01em',
    lineHeight: 1.35,
    margin: 0,
  },
  badge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    padding: '3px 8px',
    borderRadius: 9999,
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: '0.02em',
    flexShrink: 0,
  },
  pulseDot: {
    width: 5,
    height: 5,
    borderRadius: '50%',
    flexShrink: 0,
    animation: 'ws-pulse 2s ease infinite',
  },
  goal: {
    fontSize: 12,
    color: '#8b8fa8',
    lineHeight: 1.5,
    margin: '0 0 14px',
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
  },
  progressSection: {
    marginBottom: 12,
  },
  progressLabel: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 5,
  },
  labelText: {
    fontSize: 11,
    fontWeight: 500,
    color: '#555873',
    letterSpacing: '0.02em',
    textTransform: 'uppercase',
  },
  labelValue: {
    fontSize: 12,
    fontFamily: "'Commit Mono', monospace",
  },
  countNum: {
    color: '#e2e4ed',
    fontWeight: 600,
  },
  countDim: {
    color: '#555873',
  },
  track: {
    height: 3,
    background: '#1e2030',
    borderRadius: 9999,
    overflow: 'hidden',
  },
  trackFill: {
    height: '100%',
    borderRadius: 9999,
    transition: 'width 600ms ease',
  },
  metricsRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginTop: 4,
  },
  metric: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  metricNum: {
    fontSize: 12,
    fontWeight: 600,
    color: '#e2e4ed',
    fontFamily: "'Commit Mono', monospace",
  },
  metricLabel: {
    fontSize: 11,
    color: '#555873',
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    flexShrink: 0,
  },
  budgetTrack: {
    height: 2,
    background: '#1e2030',
    borderRadius: 9999,
    overflow: 'hidden',
    marginTop: 14,
  },
  budgetFill: {
    height: '100%',
    borderRadius: 9999,
    transition: 'width 600ms ease',
  },
}
