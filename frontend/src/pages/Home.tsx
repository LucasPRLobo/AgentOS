/** Home — landing page with template gallery and quick-start actions. */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listTemplates, instantiateTemplate } from '../api/client';
import type { TemplateSummary } from '../api/types';
import Spinner from '../components/Spinner';
import ErrorBanner from '../components/ErrorBanner';
import EmptyState from '../components/EmptyState';

const CATEGORY_COLORS: Record<string, string> = {
  research: 'bg-purple-900/50 text-purple-300',
  productivity: 'bg-green-900/50 text-green-300',
  content: 'bg-orange-900/50 text-orange-300',
  development: 'bg-blue-900/50 text-blue-300',
  data: 'bg-cyan-900/50 text-cyan-300',
};

export default function Home() {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [instantiating, setInstantiating] = useState<string | null>(null);
  const navigate = useNavigate();

  function loadTemplates() {
    setLoading(true);
    setError('');
    listTemplates()
      .then(setTemplates)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load templates'))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadTemplates(); }, []);

  async function handleUseTemplate(tpl: TemplateSummary) {
    setInstantiating(tpl.id);
    setError('');
    try {
      const wf = await instantiateTemplate(tpl.id);
      navigate(`/workflows/${wf.id}/edit?pack=${tpl.domain_pack}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create workflow from template');
    } finally {
      setInstantiating(null);
    }
  }

  return (
    <div className="max-w-5xl mx-auto">
      {/* Hero */}
      <div className="mb-10">
        <h1 className="text-3xl font-bold text-white mb-2">
          How would you like to start?
        </h1>
        <p className="text-gray-400">
          Build an agent team from scratch, describe what you need, or pick a template.
        </p>
      </div>

      {/* Quick-start cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-12">
        <button
          onClick={() => navigate('/nl-creator')}
          className="text-left p-6 bg-gray-900 border border-gray-800 rounded-xl
                     hover:border-blue-600 transition-colors group"
        >
          <h3 className="text-lg font-semibold text-white mb-1 group-hover:text-blue-400 transition-colors">
            Describe It
          </h3>
          <p className="text-sm text-gray-400">
            Tell us what you need in plain English and we'll generate a workflow for you.
          </p>
        </button>

        <button
          onClick={() => navigate('/workflows/new?pack=codeos')}
          className="text-left p-6 bg-gray-900 border border-gray-800 rounded-xl
                     hover:border-blue-600 transition-colors group"
        >
          <h3 className="text-lg font-semibold text-white mb-1 group-hover:text-blue-400 transition-colors">
            Build from Scratch
          </h3>
          <p className="text-sm text-gray-400">
            Open the visual builder and drag-and-drop your agent team.
          </p>
        </button>
      </div>

      {/* Divider */}
      <div className="flex items-center gap-4 mb-8">
        <div className="flex-1 border-t border-gray-800" />
        <span className="text-sm text-gray-500">Or start from a template</span>
        <div className="flex-1 border-t border-gray-800" />
      </div>

      {/* Error */}
      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} onDismiss={() => setError('')} onRetry={loadTemplates} />
        </div>
      )}

      {/* Template grid */}
      {loading ? (
        <Spinner message="Loading templates..." />
      ) : templates.length === 0 ? (
        <EmptyState
          title="No templates available"
          description="Templates will appear here once the server is running and has templates configured."
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {templates.map((tpl) => (
            <button
              key={tpl.id}
              onClick={() => handleUseTemplate(tpl)}
              disabled={instantiating === tpl.id}
              className="text-left p-4 bg-gray-900 border border-gray-800 rounded-xl
                         hover:border-blue-600 hover:bg-gray-900/80 transition-colors
                         disabled:opacity-50 disabled:cursor-wait group"
            >
              <div className="flex items-center gap-2 mb-2">
                <h4 className="text-sm font-semibold text-white group-hover:text-blue-400 transition-colors">
                  {tpl.name}
                </h4>
                {tpl.category && (
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                      CATEGORY_COLORS[tpl.category] ?? 'bg-gray-800 text-gray-400'
                    }`}
                  >
                    {tpl.category}
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-400 mb-3 line-clamp-2">
                {tpl.description}
              </p>
              <div className="flex items-center gap-3 text-[11px] text-gray-500">
                <span>
                  {tpl.agent_count} agent{tpl.agent_count !== 1 ? 's' : ''}
                </span>
                {tpl.estimated_cost && <span>{tpl.estimated_cost}</span>}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
