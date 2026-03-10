import type {} from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { DashboardPage } from './pages/DashboardPage'
import { WorkflowPage } from './pages/WorkflowPage'
import { BuilderPage } from './pages/BuilderPage'
import { MarketplacePage } from './pages/MarketplacePage'

export function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/workflows/:id" element={<WorkflowPage />} />
          <Route path="/builder" element={<BuilderPage />} />
          <Route path="/marketplace" element={<MarketplacePage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
