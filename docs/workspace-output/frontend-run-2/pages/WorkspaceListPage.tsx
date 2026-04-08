/* WorkspaceListPage — responsive workspace grid with search, filter, loading/error states */

import React, { useEffect, useState, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { WorkspaceSummary, WorkspaceStatus } from '../types/workspace'
import { listWorkspaces } from '../api/workspace'
import { WorkspaceCard, WorkspaceCardSkeleton } from '../components/layout/WorkspaceCard'

type FilterStatus = 'all' | WorkspaceStatus

/* ── WorkspaceListPage ───────────────────────────────────────────── */

export function WorkspaceListPage() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<FilterStatus>('all')
  const navigate = useNavigate()

  const fetchWorkspaces = useCallback(() => {
    setLoading(true)
    setError(null)
    listWorkspaces()
      .then(data => {
        setWorkspaces(data)
        setLoading(false)
      })
      .catch(err => {
        setError(err?.message ?? 'Failed to load workspaces')
        setLoading(false)
      })
  }, [])

  useEffect(() => { fetchWorkspaces() }, [fetchWorkspaces])

  const filtered = useMemo(() => {
    let list = workspaces
    if (statusFilter !== 'all') {
      list = list.filter(ws => ws.status === statusFilter)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(ws =>
        ws.name.toLowerCase().includes(q) ||
        ws.goal.toLowerCase().includes(q),
      )
    }
    return list
  }, [workspaces, search, statusFilter])

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { all: workspaces.length }
    for (const ws of workspaces) {
      counts[ws.status] = (counts[ws.status] ?? 0) + 1
    }
    return counts
  }, [workspaces])

  const showToolbar = !loading && !error && workspaces.length > 0

  return (
    <div style={styles.page}>
      {/* Page header */}
      <div style={styles.pageHeader}>
        <div style={styles.headerLeft}>
          <h1 style={styles.title}>Workspaces</h1>
          {!loading && workspaces.length > 0 && (
            <span style={styles.countBadge}>{workspaces.length}</span>
          )}
        </div>
      </div>

      {/* Search & filter toolbar */}
      {showToolbar && (
        <div style={styles.toolbar}>
          {/* Search */}
          <div style={styles.searchWrap}>
            <svg style={styles.searchIcon} width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              style={styles.searchInput}
              type="text"
              placeholder="Search workspaces…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            {search && (
              <button
                style={styles.clearBtn}
                onClick={() => setSearch('')}
                aria-label="Clear search"
              >
                ×
              </button>
            )}
          </div>

          {/* Status filter pills */}
          <div style={styles.filterRow}>
            {(['all', 'active', 'paused', 'completed'] as FilterStatus[]).map(s => (
              <FilterPill
                key={s}
                label={s === 'all' ? 'All' : s.charAt(0).toUpperCase() + s.slice(1)}
                count={statusCounts[s]}
                active={statusFilter === s}
                status={s}
                onClick={() => setStatusFilter(s)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Content area */}
      <div style={styles.content}>
        {loading ? (
          <SkeletonGrid />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchWorkspaces} />
        ) : filtered.length === 0 && workspaces.length > 0 ? (
          <EmptySearch onClear={() => { setSearch(''); setStatusFilter('all') }} />
        ) : workspaces.length === 0 ? (
          <EmptyWorkspaces />
        ) : (
          <div style={styles.grid}>
            {filtered.map((ws, i) => (
              <WorkspaceCard
                key={ws.workspace_id}
                ws={ws}
                index={i}
                onClick={() => navigate(`/workspaces/${ws.workspace_id}`)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Filter Pill ─────────────────────────────────────────────────── */

const PILL_ACTIVE_COLORS: Record<string, string> = {
  active: '#10b981',
  paused: '#f59e0b',
  completed: '#38bdf8',
  all: '#8b5cf6',
}

function FilterPill({
  label,
  count,
  active,
  status,
  onClick,
}: {
  label: string
  count?: number
  active: boolean
  status: FilterStatus
  onClick: () => void
}) {
  const accentColor = PILL_ACTIVE_COLORS[status] ?? '#8b5cf6'

  return (
    <button
      style={{
        ...styles.filterPill,
        ...(active
          ? {
              color: accentColor,
              background: `${accentColor}14`,
              borderColor: `${accentColor}40`,
            }
          : {}),
      }}
      onClick={onClick}
    >
      {label}
      {count != null && (
        <span
          style={{
            ...styles.pillCount,
            ...(active ? { color: accentColor } : {}),
          }}
        >
          {count}
        </span>
      )}
    </button>
  )
}

/* ── Skeleton Grid ───────────────────────────────────────────────── */

function SkeletonGrid() {
  return (
    <div style={styles.grid}>
      {Array.from({ length: 6 }).map((_, i) => (
        <WorkspaceCardSkeleton key={i} index={i} />
      ))}
    </div>
  )
}

/* ── Error State ─────────────────────────────────────────────────── */

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div style={styles.centerState}>
      <div style={styles.errorIcon}>
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#f43f5e" strokeWidth="1.5" strokeLinecap="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </div>
      <div style={styles.stateTitle}>Connection failed</div>
      <div style={styles.stateDesc}>{message}</div>
      <button style={styles.retryBtn} onClick={onRetry}>
        Try again
      </button>
    </div>
  )
}

/* ── Empty States ────────────────────────────────────────────────── */

function EmptySearch({ onClear }: { onClear: () => void }) {
  return (
    <div style={styles.centerState}>
      <div style={styles.emptyGlyph}>◇</div>
      <div style={styles.stateTitle}>No matches found</div>
      <div style={styles.stateDesc}>Try adjusting your search or filters.</div>
      <button style={styles.retryBtn} onClick={onClear}>
        Clear filters
      </button>
    </div>
  )
}

function EmptyWorkspaces() {
  return (
    <div style={styles.centerState}>
      <div style={styles.emptyGlyph}>⬡</div>
      <div style={styles.stateTitle}>No workspaces yet</div>
      <div style={styles.stateDesc}>
        Workspaces appear here once they are created via the CLI or API.
      </div>
    </div>
  )
}

/* ── Styles ─────────────────────────────────────────────────────── */

const styles: Record<string, React.CSSProperties> = {
  page: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
    background: '#08090e',
    fontFamily: "'Instrument Sans', -apple-system, BlinkMacSystemFont, sans-serif",
  },
  pageHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '24px 28px 0',
    flexShrink: 0,
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  title: {
    fontSize: 20,
    fontWeight: 600,
    color: '#e2e4ed',
    letterSpacing: '-0.02em',
    margin: 0,
  },
  countBadge: {
    fontSize: 12,
    fontWeight: 600,
    color: '#8b8fa8',
    background: '#1e2030',
    padding: '2px 8px',
    borderRadius: 9999,
    fontFamily: "'Commit Mono', monospace",
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '16px 28px 0',
    flexShrink: 0,
    flexWrap: 'wrap' as const,
  },
  searchWrap: {
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
    minWidth: 220,
  },
  searchIcon: {
    position: 'absolute',
    left: 10,
    color: '#555873',
    pointerEvents: 'none',
  },
  searchInput: {
    width: '100%',
    height: 32,
    background: '#0e1017',
    border: '1px solid #1e2030',
    borderRadius: 7,
    padding: '0 28px 0 30px',
    fontSize: 13,
    color: '#e2e4ed',
    outline: 'none',
    transition: 'border-color 120ms',
  },
  clearBtn: {
    position: 'absolute',
    right: 8,
    fontSize: 16,
    color: '#555873',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    lineHeight: 1,
    padding: 0,
  },
  filterRow: {
    display: 'flex',
    gap: 6,
    flexWrap: 'wrap' as const,
  },
  filterPill: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    padding: '4px 10px',
    borderRadius: 9999,
    fontSize: 12,
    fontWeight: 500,
    color: '#8b8fa8',
    background: 'transparent',
    border: '1px solid #1e2030',
    cursor: 'pointer',
    transition: 'color 120ms, background 120ms, border-color 120ms',
    letterSpacing: '0.01em',
  },
  pillCount: {
    fontSize: 11,
    fontWeight: 600,
    color: '#555873',
    fontFamily: "'Commit Mono', monospace",
  },
  content: {
    flex: 1,
    minHeight: 0,
    overflowY: 'auto',
    padding: '20px 28px 32px',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
    gap: 14,
  },
  centerState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '80px 20px',
    gap: 10,
    textAlign: 'center',
  },
  emptyGlyph: {
    fontSize: 36,
    color: '#2a2d40',
    marginBottom: 8,
  },
  errorIcon: {
    marginBottom: 8,
  },
  stateTitle: {
    fontSize: 15,
    fontWeight: 600,
    color: '#e2e4ed',
    letterSpacing: '-0.01em',
  },
  stateDesc: {
    fontSize: 13,
    color: '#8b8fa8',
    maxWidth: 320,
    lineHeight: 1.5,
  },
  retryBtn: {
    marginTop: 8,
    padding: '7px 16px',
    fontSize: 13,
    fontWeight: 500,
    color: '#e2e4ed',
    background: '#1e2030',
    border: '1px solid #2a2d40',
    borderRadius: 7,
    cursor: 'pointer',
    transition: 'background 120ms',
  },
}
