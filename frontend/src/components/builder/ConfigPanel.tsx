/** Config panel — persona studio for agent node configuration. */

import { useState } from 'react';
import type {
  AdvancedModelConfig,
  ModelInfo,
  ToolManifestEntry,
  WorkflowNode,
  WorkflowNodeConfig,
} from '../../api/types';

interface ConfigPanelProps {
  node: WorkflowNode;
  availableTools: ToolManifestEntry[];
  availableModels: ModelInfo[];
  onChange: (nodeId: string, config: WorkflowNodeConfig) => void;
  onDisplayNameChange: (nodeId: string, name: string) => void;
}

const PERSONA_PRESETS = [
  { value: 'analytical', label: 'Analytical', desc: 'Precise, data-driven, systematic' },
  { value: 'creative', label: 'Creative', desc: 'Inventive, exploratory, generative' },
  { value: 'formal', label: 'Formal', desc: 'Professional, structured, detailed' },
  { value: 'concise', label: 'Concise', desc: 'Brief, to-the-point, efficient' },
  { value: 'friendly', label: 'Friendly', desc: 'Conversational, helpful, approachable' },
];

const SIDE_EFFECT_COLORS: Record<string, string> = {
  PURE: 'border-green-700 text-green-400',
  READ: 'border-blue-700 text-blue-400',
  WRITE: 'border-yellow-700 text-yellow-400',
  DESTRUCTIVE: 'border-red-700 text-red-400',
};

export default function ConfigPanel({
  node,
  availableTools,
  availableModels,
  onChange,
  onDisplayNameChange,
}: ConfigPanelProps) {
  const [advancedMode, setAdvancedMode] = useState(false);
  const config = node.config;

  function update(patch: Partial<WorkflowNodeConfig>) {
    onChange(node.id, { ...config, ...patch });
  }

  function updateAdvanced(patch: Partial<AdvancedModelConfig>) {
    const adv = config.advanced ?? {};
    update({ advanced: { ...adv, ...patch } });
  }

  function toggleTool(toolName: string) {
    const current = new Set(config.tools);
    if (current.has(toolName)) {
      current.delete(toolName);
    } else {
      current.add(toolName);
    }
    update({ tools: [...current] });
  }

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
          Configure Agent
        </h3>
        <button
          onClick={() => setAdvancedMode(!advancedMode)}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          {advancedMode ? 'Simple' : 'Advanced'}
        </button>
      </div>

      {/* Display Name */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Display Name</label>
        <input
          type="text"
          value={node.display_name}
          onChange={(e) => onDisplayNameChange(node.id, e.target.value)}
          className="w-full px-3 py-1.5 text-sm bg-gray-800 border border-gray-700
                     rounded text-gray-200 focus:outline-none focus:border-blue-500"
        />
      </div>

      {/* Persona Preset */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Personality</label>
        <div className="grid grid-cols-1 gap-1">
          {PERSONA_PRESETS.map((p) => (
            <button
              key={p.value}
              onClick={() => update({ persona_preset: p.value })}
              className={`text-left px-3 py-1.5 rounded text-sm transition-colors ${
                config.persona_preset === p.value
                  ? 'bg-blue-600/20 border border-blue-500 text-blue-300'
                  : 'bg-gray-800 border border-gray-700 text-gray-400 hover:border-gray-600'
              }`}
            >
              <span className="font-medium">{p.label}</span>
              <span className="text-xs text-gray-500 ml-2">{p.desc}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Behavior / System Prompt (simple) */}
      {!advancedMode && (
        <div>
          <label className="block text-xs text-gray-500 mb-1">Behavior Instructions</label>
          <textarea
            value={config.system_prompt}
            onChange={(e) => update({ system_prompt: e.target.value })}
            rows={3}
            placeholder="Describe what this agent should do..."
            className="w-full px-3 py-2 text-sm bg-gray-800 border border-gray-700
                       rounded text-gray-200 placeholder-gray-600 resize-none
                       focus:outline-none focus:border-blue-500"
          />
        </div>
      )}

      {/* Model Selector */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Model</label>
        <select
          value={config.model}
          onChange={(e) => update({ model: e.target.value })}
          className="w-full px-3 py-1.5 text-sm bg-gray-800 border border-gray-700
                     rounded text-gray-200 focus:outline-none focus:border-blue-500"
        >
          <option value="">Select model...</option>
          {availableModels.map((m) => (
            <option key={m.name} value={m.name} disabled={!m.available}>
              {m.display_name} ({m.provider})
            </option>
          ))}
        </select>
      </div>

      {/* Tool Permissions */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">
          Tools ({config.tools.length} enabled)
        </label>
        <div className="max-h-48 overflow-y-auto flex flex-col gap-1">
          {availableTools.map((tool) => {
            const enabled = config.tools.includes(tool.name);
            const color = SIDE_EFFECT_COLORS[tool.side_effect] ?? 'border-gray-700 text-gray-400';
            return (
              <label
                key={tool.name}
                className={`flex items-center gap-2 px-2 py-1 rounded text-xs border
                  cursor-pointer transition-colors
                  ${enabled ? color + ' bg-gray-800/50' : 'border-gray-800 text-gray-600'}
                `}
              >
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={() => toggleTool(tool.name)}
                  className="accent-blue-500"
                />
                <span className="truncate flex-1">{tool.name}</span>
                <span className="text-[10px] text-gray-600">{tool.side_effect}</span>
              </label>
            );
          })}
        </div>
      </div>

      {/* Max Steps */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">
          Max Steps: {config.max_steps}
        </label>
        <input
          type="range"
          min={1}
          max={100}
          value={config.max_steps}
          onChange={(e) => update({ max_steps: parseInt(e.target.value) })}
          className="w-full accent-blue-500"
        />
      </div>

      {/* ── Advanced Mode ─────────────────────────────────────── */}
      {advancedMode && (
        <>
          <div className="border-t border-gray-800 pt-3">
            <h4 className="text-xs font-semibold text-gray-500 uppercase mb-3">
              Advanced
            </h4>
          </div>

          {/* System Prompt (full editor) */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">System Prompt</label>
            <textarea
              value={config.system_prompt}
              onChange={(e) => update({ system_prompt: e.target.value })}
              rows={6}
              className="w-full px-3 py-2 text-xs font-mono bg-gray-800 border border-gray-700
                         rounded text-gray-200 resize-y
                         focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* Temperature */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Temperature: {config.advanced?.temperature?.toFixed(2) ?? '0.70'}
            </label>
            <input
              type="range"
              min={0}
              max={200}
              value={Math.round((config.advanced?.temperature ?? 0.7) * 100)}
              onChange={(e) =>
                updateAdvanced({ temperature: parseInt(e.target.value) / 100 })
              }
              className="w-full accent-blue-500"
            />
          </div>

          {/* Max Output Tokens */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Max Output Tokens: {config.advanced?.max_output_tokens ?? 2048}
            </label>
            <input
              type="range"
              min={256}
              max={16384}
              step={256}
              value={config.advanced?.max_output_tokens ?? 2048}
              onChange={(e) =>
                updateAdvanced({ max_output_tokens: parseInt(e.target.value) })
              }
              className="w-full accent-blue-500"
            />
          </div>

          {/* Few-shot Examples */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Few-shot Examples
            </label>
            {(config.advanced?.few_shot_examples ?? []).map((ex, i) => (
              <div key={i} className="flex flex-col gap-1 mb-2 p-2 bg-gray-800 rounded border border-gray-700">
                <input
                  type="text"
                  value={ex.input}
                  placeholder="Input example..."
                  onChange={(e) => {
                    const examples = [...(config.advanced?.few_shot_examples ?? [])];
                    examples[i] = { ...examples[i], input: e.target.value };
                    updateAdvanced({ few_shot_examples: examples });
                  }}
                  className="w-full px-2 py-1 text-xs bg-gray-900 border border-gray-700
                             rounded text-gray-300 focus:outline-none focus:border-blue-500"
                />
                <input
                  type="text"
                  value={ex.output}
                  placeholder="Output example..."
                  onChange={(e) => {
                    const examples = [...(config.advanced?.few_shot_examples ?? [])];
                    examples[i] = { ...examples[i], output: e.target.value };
                    updateAdvanced({ few_shot_examples: examples });
                  }}
                  className="w-full px-2 py-1 text-xs bg-gray-900 border border-gray-700
                             rounded text-gray-300 focus:outline-none focus:border-blue-500"
                />
                <button
                  onClick={() => {
                    const examples = (config.advanced?.few_shot_examples ?? []).filter(
                      (_, j) => j !== i,
                    );
                    updateAdvanced({ few_shot_examples: examples });
                  }}
                  className="text-[10px] text-red-400 hover:text-red-300 self-end"
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              onClick={() => {
                const examples = [
                  ...(config.advanced?.few_shot_examples ?? []),
                  { input: '', output: '' },
                ];
                updateAdvanced({ few_shot_examples: examples });
              }}
              className="text-xs text-blue-400 hover:text-blue-300"
            >
              + Add example
            </button>
          </div>
        </>
      )}
    </div>
  );
}
