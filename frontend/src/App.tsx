import { Link, Route, Routes, useLocation } from 'react-router-dom';
import Home from './pages/Home';
import DomainPicker from './pages/DomainPicker';
import TeamBuilder from './pages/TeamBuilder';
import SessionDashboard from './pages/SessionDashboard';
import SessionHistory from './pages/SessionHistory';
import WorkflowBuilder from './pages/WorkflowBuilder';
import NLCreator from './pages/NLCreator';
import Settings from './pages/Settings';

function NavLink({ to, label }: { to: string; label: string }) {
  const { pathname } = useLocation();
  const active = pathname === to || (to !== '/' && pathname.startsWith(to));
  return (
    <Link
      to={to}
      className={`text-sm transition-colors ${
        active
          ? 'text-blue-400'
          : 'text-gray-500 hover:text-gray-300'
      }`}
    >
      {label}
    </Link>
  );
}

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-gray-800 px-6 py-4 flex items-center gap-8">
        <Link to="/" className="text-xl font-bold text-white hover:text-blue-400 transition-colors">
          AgentOS Platform
        </Link>
        <nav className="flex items-center gap-6">
          <NavLink to="/" label="Home" />
          <NavLink to="/sessions" label="Sessions" />
          <NavLink to="/settings" label="Settings" />
        </nav>
      </header>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/packs" element={<DomainPicker />} />
          <Route path="/nl-creator" element={<NLCreator />} />
          <Route path="/sessions/new" element={<TeamBuilder />} />
          <Route path="/sessions/:id" element={<SessionDashboard />} />
          <Route path="/sessions" element={<SessionHistory />} />
          <Route path="/workflows/new" element={<WorkflowBuilder />} />
          <Route path="/workflows/:id/edit" element={<WorkflowBuilder />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
