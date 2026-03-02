/** NLCreator — generate a workflow from a natural language description. */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { generateWorkflow, saveWorkflow, listModels } from '../api/client';
import { useEffect } from 'react';
import type { ModelInfo, WorkflowDefinition } from '../api/types';

export default function NLCreator() {
  const navigate = useNavigate();
  const [description, setDescription] = useState('');
  const [model, setModel] = useState('gpt-4o-mini');
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<{
    workflow: WorkflowDefinition;
    explanation: string;
  } | null>(null);

  useEffect(() => {
    listModels().then(setModels).catch(console.error);
  }, []);

  async function handleGenerate() {
    if (!description.trim()) return;
    setGenerating(true);
    setError('');
    setResult(null);
    try {
      const resp = await generateWorkflow(description, model);
      setResult(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  async function handleOpenInBuilder() {
    if (!result) return;
    try {
      const saved = await saveWorkflow(result.workflow);
      navigate(
        `/workflows/${saved.id}/edit?pack=${result.workflow.domain_pack || 'codeos'}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="max-w-3xl mx-auto">
      <h2 className="text-2xl font-bold text-white mb-2">
        Describe Your Agent Team
      </h2>
      <p className="text-gray-400 mb-6">
        Tell us what you want your agents to do and we'll generate a workflow you
        can customize in the visual builder.
      </p>

      {/* Input */}
      <div className="mb-4">
        <label className="block text-sm text-gray-400 mb-1">
          What do you want your agents to do?
        </label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={5}
          placeholder="e.g., I need a team that researches a topic online, writes a detailed report with citations, and has a reviewer check everything before delivering the final document."
          className="w-full px-4 py-3 text-sm bg-gray-900 border border-gray-700 rounded-lg
                     text-gray-200 placeholder-gray-600 resize-none
                     focus:outline-none focus:border-blue-500"
        />
      </div>

      {/* Model selector + Generate button */}
      <div className="flex items-center gap-4 mb-6">
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-400">Model:</label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="px-3 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded
                       text-gray-200 focus:outline-none focus:border-blue-500"
          >
            {models.length > 0 ? (
              models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.display_name}
                </option>
              ))
            ) : (
              <option value="gpt-4o-mini">GPT-4o Mini</option>
            )}
          </select>
        </div>

        <button
          onClick={handleGenerate}
          disabled={generating || !description.trim()}
          className="px-5 py-2 text-sm rounded-lg bg-blue-600 text-white font-medium
                     hover:bg-blue-500 transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {generating ? 'Generating...' : 'Generate Workflow'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-6 px-4 py-3 rounded-lg bg-red-900/30 border border-red-500/40 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-4 py-3 bg-gray-900 border-b border-gray-800">
            <h3 className="text-sm font-semibold text-white">
              Generated Workflow Preview
            </h3>
            {result.explanation && (
              <p className="text-xs text-gray-400 mt-1">{result.explanation}</p>
            )}
          </div>

          <div className="p-4 space-y-3">
            {/* Workflow name and description */}
            <div>
              <div className="text-sm font-medium text-gray-200">
                {result.workflow.name}
              </div>
              <div className="text-xs text-gray-400">
                {result.workflow.description}
              </div>
            </div>

            {/* Nodes */}
            <div className="flex flex-wrap gap-2">
              {result.workflow.nodes.map((node, i) => (
                <div
                  key={node.id}
                  className="flex items-center gap-2 px-3 py-2 bg-gray-800 rounded-lg border border-gray-700"
                >
                  <span className="text-xs text-gray-500">{i + 1}.</span>
                  <span className="text-sm text-gray-200">
                    {node.display_name}
                  </span>
                  <span className="text-[10px] text-gray-500">
                    {node.config.model}
                  </span>
                  <span className="text-[10px] text-gray-600">
                    {node.config.tools.length} tool
                    {node.config.tools.length !== 1 ? 's' : ''}
                  </span>
                </div>
              ))}
            </div>

            {/* Stats */}
            <div className="flex gap-4 text-xs text-gray-500">
              <span>
                {result.workflow.nodes.length} agent
                {result.workflow.nodes.length !== 1 ? 's' : ''}
              </span>
              <span>
                {result.workflow.edges.length} connection
                {result.workflow.edges.length !== 1 ? 's' : ''}
              </span>
            </div>

            {/* Actions */}
            <div className="flex gap-3 pt-2">
              <button
                onClick={handleOpenInBuilder}
                className="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white
                           hover:bg-blue-500 transition-colors"
              >
                Open in Builder
              </button>
              <button
                onClick={handleGenerate}
                disabled={generating}
                className="px-4 py-2 text-sm rounded-lg bg-gray-800 text-gray-300
                           border border-gray-700 hover:border-gray-600 transition-colors
                           disabled:opacity-50"
              >
                Regenerate
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
