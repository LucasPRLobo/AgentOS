/* BacklogPanel — left panel, task list with status badges, priority indicators, assignment */

import { useState, useMemo } from 'react'
import type { BacklogTask, BacklogTaskStatus, TaskPriority } from '../../types/workspace'

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

// ── Status config ─────────────────────────────────────────────────

type StatusConfig = { label: string; color: string; bg: string; dot: string }

const STATUS_CONFIG: Record<BacklogTaskStatus, StatusConfig> = {
  proposed:        { label: 'proposed',        color: '#6b7a99', bg: '#161b27', dot: '#3a4a5c' },
  specifying:      { label: 'specifying',      color: '#b39ddb', bg: '#1e1a2e', dot: '#7c5cbf' },
  open:            { label: 'open',            color: '#7eb3e8', bg: '#1a2535', dot: '#4a7eb0' },
  claimed:         { label: 'claimed',         color: '#e8956d', bg: '#201815', dot: '#b05820' },
  in_progress:     { label: 'in progress',     color: '#f0a500', bg: '#1e1800', dot: '#c07800' },
  completed:       { label: 'completed',       color: '#4db68c', bg: '#152520', dot: '#2a8060' },
  in_review:       { label: 'in review',       color: '#4ecdc4', bg: '#122020', dot: '#289090' },
  revision_needed: { label: 'revision',        color: '#e57373', bg: '#201515', dot: '#a03030' },
  done:            { label: 'done',            color: '#4db68c', bg: '#122020', dot: '#2a8060' },
  blocked:         { label: 'blocked',         color: '#ff4f6d', bg: '#200f15', dot: '#c01030' },
  cancelled:       { label: 'cancelled',       color: '#3a4a5c', bg: '#12151a', dot: '#2a3040' },
}

const PRIORITY_CONFIG: Record<TaskPriority, { label: string; color: string; icon: string }> = {
  low:      { label: 'low',      color: '#3a4a5c', icon: '▽' },
  normal:   { label: 'normal',   color: '#6b7a99', icon: '△' },
  high:     { label: 'high',     color: '#f0a500', icon: '▲' },
  critical: { label: 'critical', color: '#ff4f6d', icon: '⬆' },
}

// ── Status groups ─────────────────────────────────────────────────

const STATUS_GROUPS: { label: string; statuses: BacklogTaskStatus[]; accent: string }[] = [
  { label: 'Active',    statuses: ['in_progress', 'claimed', 'in_review'], accent: '#f0a500' },
  { label: 'Open',      statuses: ['open', 'proposed', 'specifying'],      accent: '#7eb3e8' },
  { label: 'Blocked',   statuses: ['blocked', 'revision_needed'],          accent: '#ff4f6d' },
  { label: 'Done',      statuses: ['done', 'completed'],                   accent: '#4db68c' },
  { label: 'Inactive',  statuses: ['cancelled'],                           accent: '#3a4a5c' },
]

// ── Skeleton ──────────────────────────────────────────────────────

function TaskSkeleton() {
  return (
    <div style={{
      background: '#161b27',
      border: '1px solid #2a3347',
      borderRadius: '6px',
      padding: '10px 12px',
      marginBottom: '6px',
    }}>
      <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
        <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#2a3347', marginTop: 5, flexShrink: 0 }} />
        <div style={{ flex: 1 }}>
          <div style={{ height: 10, width: '75%', background: '#1e2535', borderRadius: 3, marginBottom: 6 }} />
          <div style={{ height: 8, width: '40%', background: '#1a2030', borderRadius: 3 }} />
        </div>
        <div style={{ width: 50, height: 16, background: '#1e2535', borderRadius: 3 }} />
      </div>
    </div>
  )
}

// ── Task card ─────────────────────────────────────────────────────

function TaskCard({ task, expanded, onToggle }: {
  task: BacklogTask
  expanded: boolean
  onToggle: () => void
}) {
  const sc = STATUS_CONFIG[task.status] ?? STATUS_CONFIG.open
  const pc = PRIORITY_CONFIG[task.priority] ?? PRIORITY_CONFIG.normal

  return (
    <div
      onClick={onToggle}
      style={{
        background: '#161b27',
        border: `1px solid ${expanded ? '#2a3a50' : '#2a3347'}`,
        borderLeft: `3px solid ${sc.dot}`,
        borderRadius: '6px',
        padding: '10px 12px',
        marginBottom: '6px',
        cursor: 'pointer',
        transition: 'border-color 0.15s, background 0.15s',
      }}
    >
      {/* Title row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
        <div style={{
          width: '6px',
          height: '6px',
          borderRadius: '50%',
          background: sc.dot,
          marginTop: '5px',
          flexShrink: 0,
        }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: '12px',
            fontWeight: 600,
            color: task.status === 'cancelled' ? '#3a4a5c' : '#c8d8ee',
            lineHeight: 1.4,
            textDecoration: task.status === 'cancelled' ? 'line-through' : 'none',
            wordBreak: 'break-word',
          }}>
            {task.title}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '5px', flexWrap: 'wrap' }}>
            {/* Priority */}
            <span style={{ fontSize: '10px', color: pc.color }} title={`Priority: ${pc.label}`}>
              {pc.icon}
            </span>
            {/* Status badge */}
            <span style={{
              fontSize: '9px',
              padding: '1px 6px',
              borderRadius: '3px',
              background: sc.bg,
              color: sc.color,
              border: `1px solid ${sc.dot}22`,
              fontFamily: "'JetBrains Mono', monospace",
              textTransform: 'uppercase',
              letterSpacing: '0.04em',
              fontWeight: 600,
            }}>
              {sc.label}
            </span>
            {/* Assigned to */}
            {task.assigned_to && (
              <span style={{
                fontSize: '9px',
                color: '#4a5a70',
                fontFamily: "'JetBrains Mono', monospace",
              }}>
                → {task.assigned_to}
              </span>
            )}
          </div>
        </div>
        <span style={{ fontSize: '9px', color: '#3a4a5c', fontFamily: 'monospace', flexShrink: 0 }}>
          {relativeTime(task.created_at)}
        </span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div style={{
          marginTop: '10px',
          paddingTop: '10px',
          borderTop: '1px solid #1e2535',
          animation: 'fadeIn 0.15s ease-out',
        }}>
          {task.description && (
            <p style={{
              margin: '0 0 8px',
              fontSize: '11px',
              color: '#8090a8',
              lineHeight: 1.55,
              whiteSpace: 'pre-wrap',
            }}>
              {task.description}
            </p>
          )}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
            {task.estimated_minutes && (
              <Detail label="Est." value={`${task.estimated_minutes}m`} />
            )}
            {task.model_tier && (
              <Detail label="Model" value={task.model_tier} />
            )}
            {task.review_count > 0 && (
              <Detail label="Reviews" value={String(task.review_count)} />
            )}
            {task.stall_count > 0 && (
              <Detail label="Stalls" value={String(task.stall_count)} color="#f0a500" />
            )}
          </div>
          {task.acceptance_criteria.length > 0 && (
            <div style={{ marginTop: '8px' }}>
              <div style={{ fontSize: '9px', color: '#4a5a70', fontFamily: 'monospace', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Criteria
              </div>
              <ul style={{ margin: 0, paddingLeft: '12px' }}>
                {task.acceptance_criteria.slice(0, 3).map((c, i) => (
                  <li key={i} style={{ fontSize: '10px', color: '#6b7a99', marginBottom: '2px' }}>{c}</li>
                ))}
                {task.acceptance_criteria.length > 3 && (
                  <li style={{ fontSize: '10px', color: '#3a4a5c' }}>+{task.acceptance_criteria.length - 3} more</li>
                )}
              </ul>
            </div>
          )}
          {task.depends_on.length > 0 && (
            <div style={{ marginTop: '8px', fontSize: '10px', color: '#4a5a70', fontFamily: 'monospace' }}>
              Depends: {task.depends_on.slice(0, 2).join(', ')}{task.depends_on.length > 2 ? '…' : ''}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Detail({ label, value, color = '#6b7a99' }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div style={{ fontSize: '9px', color: '#3a4a5c', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      <div style={{ fontSize: '11px', color, fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>{value}</div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────

interface BacklogPanelProps {
  tasks: BacklogTask[]
  loading?: boolean
  error?: string | null
  onRetry?: () => void
}

export function BacklogPanel({ tasks, loading = false, error = null, onRetry }: BacklogPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [filterStatus, setFilterStatus] = useState<BacklogTaskStatus | 'all'>('all')
  const [searchQuery, setSearchQuery] = useState('')

  const stats = useMemo(() => ({
    total: tasks.length,
    done: tasks.filter(t => t.status === 'done' || t.status === 'completed').length,
    active: tasks.filter(t => t.status === 'in_progress' || t.status === 'claimed').length,
    blocked: tasks.filter(t => t.status === 'blocked').length,
  }), [tasks])

  const filteredTasks = useMemo(() => {
    let result = tasks
    if (filterStatus !== 'all') {
      result = result.filter(t => t.status === filterStatus)
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter(t =>
        t.title.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q) ||
        (t.assigned_to ?? '').toLowerCase().includes(q)
      )
    }
    // Sort: active first, then by computed_priority desc
    return [...result].sort((a, b) => {
      const order: BacklogTaskStatus[] = ['in_progress', 'claimed', 'blocked', 'open', 'proposed', 'specifying', 'in_review', 'revision_needed', 'done', 'completed', 'cancelled']
      const ai = order.indexOf(a.status)
      const bi = order.indexOf(b.status)
      if (ai !== bi) return ai - bi
      return (b.computed_priority ?? 0) - (a.computed_priority ?? 0)
    })
  }, [tasks, filterStatus, searchQuery])

  const grouped = useMemo(() => {
    if (filterStatus !== 'all' || searchQuery) return null
    return STATUS_GROUPS.map(g => ({
      ...g,
      tasks: tasks.filter(t => g.statuses.includes(t.status))
        .sort((a, b) => (b.computed_priority ?? 0) - (a.computed_priority ?? 0)),
    })).filter(g => g.tasks.length > 0)
  }, [tasks, filterStatus, searchQuery])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0f1117', overflow: 'hidden' }}>
      <style>{`@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }`}</style>

      {/* Header */}
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid #2a3347',
        background: '#0f1117',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '10px' }}>
          <span style={{
            fontSize: '13px',
            fontWeight: 700,
            color: '#e8edf5',
            fontFamily: "'Syne', sans-serif",
            letterSpacing: '0.02em',
            flex: 1,
          }}>
            Backlog
          </span>
          <div style={{ display: 'flex', gap: '8px', fontSize: '10px', fontFamily: 'monospace' }}>
            <Chip value={stats.active} color="#f0a500" label="active" />
            <Chip value={stats.blocked} color="#ff4f6d" label="blocked" />
            <Chip value={`${stats.done}/${stats.total}`} color="#4db68c" label="done" />
          </div>
        </div>

        {/* Search */}
        <input
          type="text"
          placeholder="Search tasks…"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          style={{
            width: '100%',
            background: '#161b27',
            border: '1px solid #2a3347',
            borderRadius: '5px',
            color: '#c0ccde',
            fontSize: '11px',
            padding: '6px 10px',
            fontFamily: "'JetBrains Mono', monospace",
            outline: 'none',
            boxSizing: 'border-box',
          }}
        />
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px', scrollbarWidth: 'thin', scrollbarColor: '#2a3347 transparent' }}>
        {loading && (
          [...Array(6)].map((_, i) => <TaskSkeleton key={i} />)
        )}

        {error && !loading && (
          <div style={{ textAlign: 'center', padding: '32px 16px' }}>
            <div style={{ fontSize: '11px', color: '#ff4f6d', marginBottom: '12px' }}>{error}</div>
            {onRetry && (
              <button onClick={onRetry} style={retryBtnStyle}>Retry</button>
            )}
          </div>
        )}

        {!loading && !error && grouped && grouped.map(group => (
          <div key={group.label} style={{ marginBottom: '16px' }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginBottom: '6px',
              padding: '0 4px',
            }}>
              <div style={{ height: '1px', width: '10px', background: group.accent, opacity: 0.6 }} />
              <span style={{
                fontSize: '9px',
                color: group.accent,
                fontFamily: "'JetBrains Mono', monospace",
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                fontWeight: 700,
              }}>
                {group.label}
              </span>
              <span style={{ fontSize: '9px', color: '#3a4a5c', fontFamily: 'monospace' }}>
                ({group.tasks.length})
              </span>
              <div style={{ flex: 1, height: '1px', background: '#1e2535' }} />
            </div>
            {group.tasks.map(task => (
              <TaskCard
                key={task.task_id}
                task={task}
                expanded={expandedId === task.task_id}
                onToggle={() => setExpandedId(expandedId === task.task_id ? null : task.task_id)}
              />
            ))}
          </div>
        ))}

        {!loading && !error && !grouped && (
          filteredTasks.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '32px 16px', color: '#3a4a5c', fontSize: '12px' }}>
              No tasks match your filter
            </div>
          ) : (
            filteredTasks.map(task => (
              <TaskCard
                key={task.task_id}
                task={task}
                expanded={expandedId === task.task_id}
                onToggle={() => setExpandedId(expandedId === task.task_id ? null : task.task_id)}
              />
            ))
          )
        )}
      </div>
    </div>
  )
}

function Chip({ value, color, label }: { value: number | string; color: string; label: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <span style={{ color, fontWeight: 700, fontSize: '11px' }}>{value}</span>
      <span style={{ color: '#3a4a5c', fontSize: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
    </div>
  )
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
