import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import WorkspaceListPage from './pages/WorkspaceListPage';

// Lazy-load WorkspacePage (owned by workspace-page-builder agent)
const WorkspacePage = lazy(() => import('./pages/WorkspacePage'));

// ── Fallback for lazy-loaded routes ──────────────────────────────────────────

function PageFallback() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '60vh',
        gap: '12px',
        color: 'var(--text-muted)',
        fontSize: '13px',
        fontFamily: 'var(--font-mono)',
      }}
    >
      <Spinner />
      Loading…
    </div>
  );
}

function Spinner() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
      style={{ animation: 'spin 0.8s linear infinite' }}
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" strokeDasharray="25" strokeDashoffset="10" />
    </svg>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          {/* Root redirect */}
          <Route path="/" element={<Navigate to="/workspaces" replace />} />

          {/* Workspace list */}
          <Route path="/workspaces" element={<WorkspaceListPage />} />

          {/* Single workspace (lazy) */}
          <Route path="/workspaces/:workspace_id" element={<WorkspacePage />} />

          {/* Catch-all */}
          <Route path="*" element={<Navigate to="/workspaces" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
