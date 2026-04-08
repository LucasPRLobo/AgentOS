/* AgentOS — root application with routing */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { WorkspaceListPage } from './pages/WorkspaceListPage'
import { WorkspacePage } from './pages/WorkspacePage'

export function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          {/* Redirect root to workspace list */}
          <Route path="/" element={<Navigate to="/workspaces" replace />} />

          {/* Workspace routes */}
          <Route path="/workspaces" element={<WorkspaceListPage />} />
          <Route path="/workspaces/:workspace_id" element={<WorkspacePage />} />

          {/* Catch-all → workspace list */}
          <Route path="*" element={<Navigate to="/workspaces" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
