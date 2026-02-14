import { Route, Routes } from 'react-router-dom';
import DomainPicker from './pages/DomainPicker';
import TeamBuilder from './pages/TeamBuilder';
import SessionDashboard from './pages/SessionDashboard';
import SessionHistory from './pages/SessionHistory';

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-gray-800 px-6 py-4">
        <h1 className="text-xl font-bold text-white">
          AgentOS Platform
        </h1>
      </header>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<DomainPicker />} />
          <Route path="/sessions/new" element={<TeamBuilder />} />
          <Route path="/sessions/:id" element={<SessionDashboard />} />
          <Route path="/sessions" element={<SessionHistory />} />
        </Routes>
      </main>
    </div>
  );
}
