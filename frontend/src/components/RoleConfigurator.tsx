/** RoleConfigurator — configure model, count, and budget for a role. */

import type { AgentSlotConfig, RoleTemplate } from '../api/types';
import ToolBadge from './ToolBadge';

interface Props {
  role: RoleTemplate;
  slot: AgentSlotConfig;
  toolSideEffects: Record<string, string>;
  availableModels: string[];
  onUpdate: (slot: AgentSlotConfig) => void;
  onRemove: () => void;
}

export default function RoleConfigurator({
  role,
  slot,
  toolSideEffects,
  availableModels,
  onUpdate,
  onRemove,
}: Props) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-white">{role.display_name}</h3>
          <p className="text-xs text-gray-500">{role.description}</p>
        </div>
        <button
          onClick={onRemove}
          className="text-gray-500 hover:text-red-400 text-sm"
        >
          Remove
        </button>
      </div>

      <div className="flex flex-wrap gap-1">
        {role.tool_names.map((t) => (
          <ToolBadge key={t} name={t} sideEffect={toolSideEffects[t] ?? 'PURE'} />
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-400 mb-1">LLM Model</label>
          <select
            value={slot.model}
            onChange={(e) => onUpdate({ ...slot, model: e.target.value })}
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
          >
            {availableModels.length > 0 ? (
              availableModels.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))
            ) : (
              <option value={slot.model}>{slot.model}</option>
            )}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Instances</label>
          <input
            type="number"
            min={1}
            max={5}
            value={slot.count}
            onChange={(e) =>
              onUpdate({ ...slot, count: Math.max(1, parseInt(e.target.value) || 1) })
            }
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>
    </div>
  );
}
