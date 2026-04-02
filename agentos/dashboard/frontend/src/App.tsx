import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { WorkspaceListPage } from './pages/WorkspaceListPage'
import { WorkspacePage } from './pages/WorkspacePage'
import { BuilderPage } from './pages/BuilderPage'
import { SettingsPage } from './pages/SettingsPage'
import { MonitorPage } from './pages/MonitorPage'
import { NotificationContext, useNotificationProvider } from './hooks/useNotifications'
import { ErrorBoundary } from './components/ErrorBoundary'
import './styles/workspace.css'

export function App() {
  const notifications = useNotificationProvider()

  return (
    <NotificationContext.Provider value={notifications}>
      <BrowserRouter>
        <ErrorBoundary>
          <Routes>
            {/* Workspace routes (new) */}
            <Route path="/" element={<WorkspaceListPage />} />
            <Route path="/workspace/:id" element={<WorkspacePage />} />

            {/* Legacy routes (kept for backward compatibility) */}
            <Route path="/workflows/:id" element={<MonitorPage />} />
            <Route path="/builder" element={<BuilderPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </ErrorBoundary>
      </BrowserRouter>
    </NotificationContext.Provider>
  )
}
