/* Layout — top nav shell used by all workspace routes */

import React, { createContext, useContext, useState, type ReactNode } from 'react'
import { Link, useLocation, useMatch } from 'react-router-dom'

/* ── Breadcrumb context ─────────────────────────────────────────── */

interface BreadcrumbCtx {
  title: string | null
  setTitle: (t: string | null) => void
}

const BreadcrumbContext = createContext<BreadcrumbCtx>({
  title: null,
  setTitle: () => {},
})

export const useBreadcrumbTitle = () => useContext(BreadcrumbContext)

/* ── Layout ─────────────────────────────────────────────────────── */

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const workspaceMatch = useMatch('/workspaces/:workspace_id')
  const [breadcrumbTitle, setBreadcrumbTitle] = useState<string | null>(null)

  const isWorkspaceDetail = !!workspaceMatch

  return (
    <BreadcrumbContext.Provider value={{ title: breadcrumbTitle, setTitle: setBreadcrumbTitle }}>
      <div style={styles.shell}>
        {/* ── Top Nav ─────────────────────────────────────────── */}
        <header style={styles.nav}>
          {/* Logo */}
          <Link to="/workspaces" style={styles.logo}>
            <span style={styles.logoMark}>A</span>
            <span style={styles.logoText}>AgentOS</span>
          </Link>

          <div style={styles.sep} />

          {/* Breadcrumb or nav links */}
          {isWorkspaceDetail ? (
            <nav style={styles.breadcrumb}>
              <Link to="/workspaces" style={styles.breadcrumbLink}>
                Workspaces
              </Link>
              <span style={styles.breadcrumbSep}>/</span>
              <span style={styles.breadcrumbCurrent}>
                {breadcrumbTitle ||
                  workspaceMatch.params.workspace_id?.slice(0, 14) ||
                  'Workspace'}
              </span>
            </nav>
          ) : (
            <nav style={styles.navLinks}>
              <NavLink
                to="/workspaces"
                active={location.pathname.startsWith('/workspaces')}
              >
                Workspaces
              </NavLink>
            </nav>
          )}

          {/* Right controls */}
          <div style={styles.navRight}>
            <span style={styles.kbd} title="Command palette">⌘K</span>
            <button style={styles.settingsBtn} title="Settings">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
            </button>
          </div>
        </header>

        {/* ── Main content ─────────────────────────────────────── */}
        <main style={styles.main}>
          {children}
        </main>
      </div>
    </BreadcrumbContext.Provider>
  )
}

/* ── NavLink helper ─────────────────────────────────────────────── */

function NavLink({ to, active, children }: { to: string; active: boolean; children: ReactNode }) {
  return (
    <Link
      to={to}
      style={{
        ...styles.navLink,
        ...(active ? styles.navLinkActive : {}),
      }}
    >
      {children}
      {active && <span style={styles.navLinkDot} />}
    </Link>
  )
}

/* ── Styles ─────────────────────────────────────────────────────── */

const styles = {
  shell: {
    display: 'flex',
    flexDirection: 'column' as const,
    height: '100vh',
    overflow: 'hidden',
    background: '#08090e',
    fontFamily: "'Instrument Sans', -apple-system, BlinkMacSystemFont, sans-serif",
  },
  nav: {
    height: 52,
    borderBottom: '1px solid #1e2030',
    display: 'flex',
    alignItems: 'center',
    padding: '0 20px',
    gap: 16,
    flexShrink: 0,
    background: '#0e1017',
    position: 'relative' as const,
    zIndex: 10,
  },
  logo: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    textDecoration: 'none',
    flexShrink: 0,
  },
  logoMark: {
    width: 26,
    height: 26,
    background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
    borderRadius: 6,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 13,
    fontWeight: 700,
    color: '#08090e',
    letterSpacing: '-0.02em',
    boxShadow: '0 0 12px rgba(16,185,129,0.25)',
  } as React.CSSProperties,
  logoText: {
    fontSize: 14,
    fontWeight: 600,
    color: '#e2e4ed',
    letterSpacing: '-0.01em',
  },
  sep: {
    width: 1,
    height: 20,
    background: '#1e2030',
    flexShrink: 0,
  },
  navLinks: {
    display: 'flex',
    alignItems: 'center',
    gap: 2,
  },
  navLink: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    position: 'relative' as const,
    padding: '5px 10px',
    borderRadius: 6,
    fontSize: 13,
    fontWeight: 500,
    color: '#8b8fa8',
    textDecoration: 'none',
    transition: 'color 120ms, background 120ms',
    letterSpacing: '0.005em',
  },
  navLinkActive: {
    color: '#e2e4ed',
    background: 'rgba(30, 32, 48, 0.6)',
  },
  navLinkDot: {
    position: 'absolute' as const,
    bottom: -1,
    left: '50%',
    transform: 'translateX(-50%)',
    width: 3,
    height: 3,
    borderRadius: '50%',
    background: '#10b981',
  },
  breadcrumb: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  breadcrumbLink: {
    fontSize: 13,
    color: '#8b8fa8',
    textDecoration: 'none',
    transition: 'color 120ms',
  },
  breadcrumbSep: {
    fontSize: 13,
    color: '#555873',
  },
  breadcrumbCurrent: {
    fontSize: 13,
    fontWeight: 500,
    color: '#e2e4ed',
    maxWidth: 240,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  navRight: {
    marginLeft: 'auto',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  kbd: {
    fontSize: 11,
    fontWeight: 500,
    color: '#555873',
    padding: '2px 6px',
    border: '1px solid #1e2030',
    borderRadius: 4,
    background: '#0a0b10',
    fontFamily: 'monospace',
    cursor: 'default',
    userSelect: 'none' as const,
  },
  settingsBtn: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 28,
    height: 28,
    borderRadius: 6,
    border: '1px solid #1e2030',
    background: 'transparent',
    color: '#8b8fa8',
    cursor: 'pointer',
    transition: 'color 120ms, border-color 120ms, background 120ms',
  },
  main: {
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column' as const,
  },
}
