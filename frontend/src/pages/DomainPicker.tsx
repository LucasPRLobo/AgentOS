/** DomainPicker — landing page to select a domain pack. */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listPacks } from '../api/client';
import type { DomainPackSummary } from '../api/types';

export default function DomainPicker() {
  const [packs, setPacks] = useState<DomainPackSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    listPacks()
      .then(setPacks)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="text-gray-400">Loading domain packs...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto">
      <h2 className="text-2xl font-bold text-white mb-2">Choose a Domain</h2>
      <p className="text-gray-400 mb-8">
        Select a domain pack to configure your agent team.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {packs.map((pack) => (
          <div
            key={pack.name}
            className="bg-gray-900 border border-gray-800 rounded-xl p-6 hover:border-blue-600 hover:bg-gray-900/80 transition-colors group"
          >
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 bg-blue-900 rounded-lg flex items-center justify-center text-blue-400 text-lg font-bold">
                {pack.name[0].toUpperCase()}
              </div>
              <div>
                <h3 className="text-lg font-semibold text-white group-hover:text-blue-400 transition-colors">
                  {pack.display_name}
                </h3>
                <span className="text-xs text-gray-500">v{pack.version}</span>
              </div>
            </div>
            <p className="text-sm text-gray-400 mb-4">{pack.description}</p>
            <div className="flex gap-4 text-xs text-gray-500 mb-4">
              <span>{pack.tool_count} tools</span>
              <span>{pack.role_count} roles</span>
              <span>{pack.workflow_count} workflows</span>
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => navigate(`/workflows/new?pack=${pack.name}`)}
                className="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white
                           hover:bg-blue-500 transition-colors"
              >
                Build Workflow
              </button>
              <button
                onClick={() => navigate(`/sessions/new?pack=${pack.name}`)}
                className="px-4 py-2 text-sm rounded-lg bg-gray-800 text-gray-300
                           border border-gray-700 hover:border-gray-600 transition-colors"
              >
                Quick Launch
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
