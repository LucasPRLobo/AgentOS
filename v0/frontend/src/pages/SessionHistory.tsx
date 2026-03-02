/** SessionHistory — list of past sessions. */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listSessions } from '../api/client';
import type { SessionSummary } from '../api/types';
import Spinner from '../components/Spinner';
import ErrorBanner from '../components/ErrorBanner';
import EmptyState from '../components/EmptyState';

const STATE_COLORS: Record<string, string> = {
  CREATED: 'text-gray-400',
  RUNNING: 'text-blue-400',
  SUCCEEDED: 'text-green-400',
  FAILED: 'text-red-400',
  STOPPED: 'text-yellow-400',
};

export default function SessionHistory() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  function loadSessions() {
    setLoading(true);
    setError('');
    listSessions()
      .then(setSessions)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load sessions'))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadSessions(); }, []);

  if (loading) return <Spinner message="Loading sessions..." />;

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-white">Session History</h2>
        <button
          onClick={() => navigate('/')}
          className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          New Session
        </button>
      </div>

      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} onDismiss={() => setError('')} onRetry={loadSessions} />
        </div>
      )}

      {sessions.length === 0 && !error ? (
        <EmptyState
          title="No sessions yet"
          description="Launch a workflow to see your session history here."
          actionLabel="Create New Session"
          onAction={() => navigate('/')}
        />
      ) : sessions.length > 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase">
                <th className="text-left px-4 py-3">Session ID</th>
                <th className="text-left px-4 py-3">Domain</th>
                <th className="text-left px-4 py-3">Workflow</th>
                <th className="text-left px-4 py-3">State</th>
                <th className="text-right px-4 py-3">Agents</th>
                <th className="text-left px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr
                  key={s.session_id}
                  onClick={() => navigate(`/sessions/${s.session_id}`)}
                  className="border-b border-gray-800/50 hover:bg-gray-800/50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3 font-mono text-gray-300">
                    {s.session_id.slice(0, 8)}...
                  </td>
                  <td className="px-4 py-3 text-gray-300">{s.domain_pack}</td>
                  <td className="px-4 py-3 text-gray-300">{s.workflow}</td>
                  <td className={`px-4 py-3 font-medium ${STATE_COLORS[s.state] ?? 'text-gray-400'}`}>
                    {s.state}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-300">
                    {s.agent_count}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {new Date(s.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
