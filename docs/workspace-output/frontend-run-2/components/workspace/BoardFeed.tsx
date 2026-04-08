/* BoardFeed — center panel, live board posts with speech-act labels and WebSocket updates */

import { useState, useEffect, useRef, useCallback } from 'react'
import type { BoardState, BoardPost, SpeechAct, BoardSection } from '../../types/workspace'

// ── Utilities ────────────────────────────────────────────────────

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

// ── Color maps ────────────────────────────────────────────────────

const SPEECH_ACT_COLORS: Record<SpeechAct, { bg: string; text: string; border: string }> = {
  inform:    { bg: '#1a2535', text: '#7eb3e8', border: '#2a4060' },
  request:   { bg: '#1e2418', text: '#a3c97a', border: '#3a5228' },
  propose:   { bg: '#1e1a2e', text: '#b39ddb', border: '#3d3060' },
  accept:    { bg: '#152520', text: '#4db68c', border: '#1f5040' },
  reject:    { bg: '#271520', text: '#e57373', border: '#5c2030' },
  confirm:   { bg: '#122020', text: '#4ecdc4', border: '#1a4040' },
  alert:     { bg: '#271a10', text: '#f0a500', border: '#5c3800' },
  directive: { bg: '#201815', text: '#e8956d', border: '#5c3828' },
  status:    { bg: '#161b27', text: '#6b7a99', border: '#2a3347' },
}

const SECTION_ICONS: Record<BoardSection, string> = {
  announcement: '📢',
  status:       '◉',
  post:         '▸',
  decision:     '◆',
  question:     '?',
  alert:        '⚑',
}

const SECTION_ACCENT: Record<BoardSection, string> = {
  announcement: '#f0a500',
  status:       '#6b7a99',
  post:         '#4a5568',
  decision:     '#b39ddb',
  question:     '#7eb3e8',
  alert:        '#ff4f6d',
}

// ── Sub-components ────────────────────────────────────────────────

function SpeechActBadge({ act }: { act: SpeechAct }) {
  const c = SPEECH_ACT_COLORS[act] ?? SPEECH_ACT_COLORS.inform
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '1px 7px',
      borderRadius: '3px',
      fontSize: '10px',
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      fontWeight: 600,
      letterSpacing: '0.05em',
      textTransform: 'uppercase',
      background: c.bg,
      color: c.text,
      border: `1px solid ${c.border}`,
    }}>
      {act}
    </span>
  )
}

function AuthorAvatar({ authorId, authorType }: { authorId: string; authorType: string }) {
  const initials = authorId.slice(0, 2).toUpperCase()
  const colors: Record<string, string> = {
    agent: '#1e3a5f',
    human: '#2d3748',
    system: '#1a2a1a',
  }
  const textColors: Record<string, string> = {
    agent: '#7eb3e8',
    human: '#a0b4c8',
    system: '#4db68c',
  }
  return (
    <div style={{
      width: '28px',
      height: '28px',
      borderRadius: '6px',
      background: colors[authorType] ?? colors.agent,
      color: textColors[authorType] ?? textColors.agent,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: '10px',
      fontFamily: "'JetBrains Mono', monospace",
      fontWeight: 700,
      flexShrink: 0,
      border: `1px solid rgba(255,255,255,0.06)`,
    }}>
      {initials}
    </div>
  )
}

function PostCard({ post, isNew }: { post: BoardPost; isNew: boolean }) {
  const sectionAccent = SECTION_ACCENT[post.section] ?? '#4a5568'
  return (
    <div
      style={{
        position: 'relative',
        background: '#161b27',
        border: '1px solid #2a3347',
        borderLeft: `3px solid ${sectionAccent}`,
        borderRadius: '6px',
        padding: '12px 14px',
        marginBottom: '8px',
        animation: isNew ? 'slideInPost 0.3s ease-out' : 'none',
        transition: 'border-color 0.2s',
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
        <AuthorAvatar authorId={post.author_id} authorType={post.author_type} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
            <span style={{
              fontSize: '12px',
              fontWeight: 600,
              color: '#c8d8ee',
              fontFamily: "'JetBrains Mono', monospace",
            }}>
              {post.author_id}
            </span>
            <span style={{ fontSize: '10px', color: '#3a4a5c', userSelect: 'none' }}>·</span>
            <span style={{
              fontSize: '10px',
              color: '#4a5a70',
              fontFamily: "'JetBrains Mono', monospace",
            }}>
              {relativeTime(post.timestamp)}
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
          <SpeechActBadge act={post.speech_act} />
          {post.pinned && (
            <span style={{ fontSize: '11px', color: '#f0a500' }} title="Pinned">📌</span>
          )}
          {post.resolved && (
            <span style={{ fontSize: '11px', color: '#4db68c' }} title="Resolved">✓</span>
          )}
        </div>
      </div>

      {/* Section label */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
        marginBottom: '6px',
      }}>
        <span style={{ fontSize: '10px', color: sectionAccent }}>
          {SECTION_ICONS[post.section]}
        </span>
        <span style={{
          fontSize: '10px',
          color: sectionAccent,
          fontFamily: "'JetBrains Mono', monospace",
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          opacity: 0.8,
        }}>
          {post.section}
        </span>
      </div>

      {/* Content */}
      <p style={{
        margin: 0,
        fontSize: '13px',
        lineHeight: '1.55',
        color: '#c0ccde',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        {post.content}
      </p>
    </div>
  )
}

// ── Skeleton ──────────────────────────────────────────────────────

function PostSkeleton() {
  return (
    <div style={{
      background: '#161b27',
      border: '1px solid #2a3347',
      borderLeft: '3px solid #2a3347',
      borderRadius: '6px',
      padding: '12px 14px',
      marginBottom: '8px',
    }}>
      <div style={{ display: 'flex', gap: '8px', marginBottom: '10px' }}>
        <div style={{ width: 28, height: 28, borderRadius: 6, background: '#1e2535' }} />
        <div style={{ flex: 1 }}>
          <div style={{ height: 10, width: '30%', background: '#1e2535', borderRadius: 3, marginBottom: 6 }} />
          <div style={{ height: 8, width: '15%', background: '#1a2030', borderRadius: 3 }} />
        </div>
      </div>
      <div style={{ height: 8, background: '#1e2535', borderRadius: 3, marginBottom: 5 }} />
      <div style={{ height: 8, width: '80%', background: '#1a2030', borderRadius: 3, marginBottom: 5 }} />
      <div style={{ height: 8, width: '60%', background: '#161d2e', borderRadius: 3 }} />
    </div>
  )
}

// ── Compose bar ───────────────────────────────────────────────────

interface ComposeBarProps {
  onPost: (content: string, section?: string) => Promise<void>
}

function ComposeBar({ onPost }: ComposeBarProps) {
  const [text, setText] = useState('')
  const [section, setSection] = useState<BoardSection>('post')
  const [posting, setPosting] = useState(false)
  const [focused, setFocused] = useState(false)

  const handlePost = async () => {
    const trimmed = text.trim()
    if (!trimmed || posting) return
    setPosting(true)
    try {
      await onPost(trimmed, section)
      setText('')
    } finally {
      setPosting(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleKeyDown
      handlePost()
    }
  }

  return (
    <div style={{
      borderTop: '1px solid #2a3347',
      padding: '12px 16px',
      background: '#0f1117',
    }}>
      <div style={{
        border: `1px solid ${focused ? '#3a5070' : '#2a3347'}`,
        borderRadius: '8px',
        background: '#161b27',
        transition: 'border-color 0.15s',
        overflow: 'hidden',
      }}>
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="Post to board… (⌘+Enter to send)"
          rows={2}
          style={{
            width: '100%',
            background: 'transparent',
            border: 'none',
            outline: 'none',
            resize: 'none',
            padding: '10px 12px',
            fontSize: '13px',
            color: '#c0ccde',
            fontFamily: "'Syne', sans-serif",
            boxSizing: 'border-box',
            lineHeight: 1.5,
          }}
        />
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '6px 10px',
          borderTop: '1px solid #1e2535',
        }}>
          <select
            value={section}
            onChange={e => setSection(e.target.value as BoardSection)}
            style={{
              background: '#1e2535',
              border: '1px solid #2a3347',
              borderRadius: '4px',
              color: '#6b7a99',
              fontSize: '11px',
              padding: '3px 6px',
              fontFamily: "'JetBrains Mono', monospace",
              cursor: 'pointer',
              outline: 'none',
            }}
          >
            {(['post', 'status', 'question', 'decision', 'announcement', 'alert'] as BoardSection[]).map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: '11px', color: '#3a4a5c', fontFamily: 'monospace' }}>
            ⌘↵ to send
          </span>
          <button
            onClick={handlePost}
            disabled={!text.trim() || posting}
            style={{
              background: posting || !text.trim() ? '#1e2535' : '#1a3a5c',
              border: `1px solid ${posting || !text.trim() ? '#2a3347' : '#2a5080'}`,
              borderRadius: '4px',
              color: posting || !text.trim() ? '#3a4a5c' : '#7eb3e8',
              fontSize: '11px',
              fontWeight: 600,
              padding: '4px 12px',
              cursor: posting || !text.trim() ? 'not-allowed' : 'pointer',
              transition: 'all 0.15s',
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            {posting ? 'Posting…' : 'Post'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Section filter tabs ───────────────────────────────────────────

type FilterSection = 'all' | BoardSection

const SECTION_FILTERS: { key: FilterSection; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'alert', label: '⚑ Alerts' },
  { key: 'announcement', label: '📢 Ann.' },
  { key: 'decision', label: '◆ Decisions' },
  { key: 'question', label: '? Questions' },
  { key: 'post', label: '▸ Posts' },
  { key: 'status', label: '◉ Status' },
]

// ── Main BoardFeed ────────────────────────────────────────────────

interface BoardFeedProps {
  board: BoardState | null
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  onPost?: (content: string, section?: string) => Promise<void>
}

export function BoardFeed({ board, loading = false, error = null, onRetry, onPost }: BoardFeedProps) {
  const [filter, setFilter] = useState<FilterSection>('all')
  const [newPostIds, setNewPostIds] = useState<Set<string>>(new Set())
  const prevPostsRef = useRef<string[]>([])
  const feedRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  // Track new posts for animation
  useEffect(() => {
    if (!board) return
    const allPosts = getAllPosts(board)
    const allIds = allPosts.map(p => p.post_id)
    const prevIds = new Set(prevPostsRef.current)
    const newIds = allIds.filter(id => !prevIds.has(id))
    if (newIds.length > 0) {
      setNewPostIds(prev => {
        const next = new Set(prev)
        newIds.forEach(id => next.add(id))
        return next
      })
      // Clear "new" flag after animation
      setTimeout(() => {
        setNewPostIds(prev => {
          const next = new Set(prev)
          newIds.forEach(id => next.delete(id))
          return next
        })
      }, 1000)
    }
    prevPostsRef.current = allIds
  }, [board])

  // Auto-scroll to bottom on new posts
  useEffect(() => {
    if (autoScroll && feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight
    }
  }, [board, autoScroll])

  const handleScroll = useCallback(() => {
    const el = feedRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60
    setAutoScroll(atBottom)
  }, [])

  if (loading) {
    return (
      <div style={containerStyle}>
        <FeedHeader title="Board Feed" connected={false} postCount={0} />
        <div style={scrollAreaStyle}>
          {[...Array(5)].map((_, i) => <PostSkeleton key={i} />)}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div style={containerStyle}>
        <FeedHeader title="Board Feed" connected={false} postCount={0} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ textAlign: 'center', padding: '24px' }}>
            <div style={{ fontSize: '28px', marginBottom: '12px', opacity: 0.5 }}>⚠</div>
            <div style={{ fontSize: '13px', color: '#ff4f6d', marginBottom: '16px' }}>{error}</div>
            {onRetry && (
              <button onClick={onRetry} style={retryButtonStyle}>
                Retry
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (!board) {
    return (
      <div style={containerStyle}>
        <FeedHeader title="Board Feed" connected={false} postCount={0} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <span style={{ color: '#3a4a5c', fontSize: '13px' }}>No board data</span>
        </div>
      </div>
    )
  }

  const allPosts = getAllPosts(board)
  const filteredPosts = filter === 'all'
    ? allPosts
    : allPosts.filter(p => p.section === filter)

  const alertCount = board.alerts.filter(a => !a.resolved).length

  return (
    <div style={containerStyle}>
      <style>{`
        @keyframes slideInPost {
          from { opacity: 0; transform: translateY(-8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulseGlow {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>

      <FeedHeader
        title="Board Feed"
        connected={true}
        postCount={allPosts.length}
        alertCount={alertCount}
        version={board.version}
      />

      {/* Section filter tabs */}
      <div style={{
        display: 'flex',
        gap: '2px',
        padding: '6px 16px',
        borderBottom: '1px solid #1e2535',
        overflowX: 'auto',
        scrollbarWidth: 'none',
      }}>
        {SECTION_FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            style={{
              padding: '4px 10px',
              borderRadius: '4px',
              border: `1px solid ${filter === f.key ? '#2a5080' : 'transparent'}`,
              background: filter === f.key ? '#1a3a5c' : 'transparent',
              color: filter === f.key ? '#7eb3e8' : '#4a5a70',
              fontSize: '11px',
              fontFamily: "'JetBrains Mono', monospace",
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              transition: 'all 0.15s',
            }}
          >
            {f.label}
            {f.key === 'alert' && alertCount > 0 && (
              <span style={{
                marginLeft: '4px',
                background: '#ff4f6d',
                color: '#fff',
                borderRadius: '9px',
                padding: '0 5px',
                fontSize: '9px',
                fontWeight: 700,
              }}>
                {alertCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Feed */}
      <div
        ref={feedRef}
        onScroll={handleScroll}
        style={scrollAreaStyle}
      >
        {filteredPosts.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '48px 24px', color: '#3a4a5c', fontSize: '13px' }}>
            No {filter === 'all' ? '' : filter} posts yet
          </div>
        ) : (
          [...filteredPosts].reverse().map(post => (
            <PostCard
              key={post.post_id}
              post={post}
              isNew={newPostIds.has(post.post_id)}
            />
          ))
        )}
      </div>

      {/* Scroll-to-bottom hint */}
      {!autoScroll && (
        <button
          onClick={() => {
            if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight
            setAutoScroll(true)
          }}
          style={{
            position: 'absolute',
            bottom: onPost ? '90px' : '12px',
            right: '20px',
            background: '#1a3a5c',
            border: '1px solid #2a5080',
            borderRadius: '20px',
            color: '#7eb3e8',
            fontSize: '11px',
            padding: '5px 12px',
            cursor: 'pointer',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          ↓ New posts
        </button>
      )}

      {/* Compose bar */}
      {onPost && <ComposeBar onPost={onPost} />}
    </div>
  )
}

// ── FeedHeader ────────────────────────────────────────────────────

function FeedHeader({ title, connected, postCount, alertCount = 0, version }: {
  title: string
  connected: boolean
  postCount: number
  alertCount?: number
  version?: number
}) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '10px',
      padding: '12px 16px',
      borderBottom: '1px solid #2a3347',
      background: '#0f1117',
      flexShrink: 0,
    }}>
      <span style={{
        fontSize: '13px',
        fontWeight: 700,
        color: '#e8edf5',
        fontFamily: "'Syne', sans-serif",
        letterSpacing: '0.02em',
      }}>
        {title}
      </span>
      <div style={{
        width: '7px',
        height: '7px',
        borderRadius: '50%',
        background: connected ? '#4db68c' : '#3a4a5c',
        boxShadow: connected ? '0 0 6px #4db68c88' : 'none',
        animation: connected ? 'pulseGlow 2s ease-in-out infinite' : 'none',
        flexShrink: 0,
      }} />
      <span style={{ fontSize: '10px', color: '#3a4a5c', fontFamily: 'monospace' }}>
        {connected ? 'live' : 'offline'}
      </span>
      <div style={{ flex: 1 }} />
      {alertCount > 0 && (
        <span style={{
          background: '#ff4f6d22',
          border: '1px solid #ff4f6d44',
          color: '#ff4f6d',
          borderRadius: '4px',
          padding: '2px 8px',
          fontSize: '10px',
          fontFamily: 'monospace',
          fontWeight: 600,
        }}>
          {alertCount} alert{alertCount !== 1 ? 's' : ''}
        </span>
      )}
      <span style={{ fontSize: '10px', color: '#3a4a5c', fontFamily: 'monospace' }}>
        {postCount} posts
      </span>
      {version !== undefined && (
        <span style={{ fontSize: '10px', color: '#2a3a4c', fontFamily: 'monospace' }}>
          v{version}
        </span>
      )}
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────────────

function getAllPosts(board: BoardState): BoardPost[] {
  const seen = new Set<string>()
  const posts: BoardPost[] = []
  const sources = [
    ...board.recent_posts,
    ...board.announcements,
    ...board.alerts,
    ...board.decisions,
    ...board.open_questions,
  ]
  for (const p of sources) {
    if (!seen.has(p.post_id)) {
      seen.add(p.post_id)
      posts.push(p)
    }
  }
  return posts.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
}

// ── Shared styles ─────────────────────────────────────────────────

const containerStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  height: '100%',
  background: '#0f1117',
  position: 'relative',
  overflow: 'hidden',
}

const scrollAreaStyle: React.CSSProperties = {
  flex: 1,
  overflowY: 'auto',
  padding: '12px 16px',
  scrollbarWidth: 'thin',
  scrollbarColor: '#2a3347 transparent',
}

const retryButtonStyle: React.CSSProperties = {
  background: '#1a3a5c',
  border: '1px solid #2a5080',
  borderRadius: '5px',
  color: '#7eb3e8',
  padding: '7px 18px',
  fontSize: '12px',
  cursor: 'pointer',
  fontFamily: "'JetBrains Mono', monospace",
}
