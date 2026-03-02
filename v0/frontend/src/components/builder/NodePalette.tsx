/** Node palette — draggable role templates for the workflow canvas. */

import { useState, type DragEvent } from 'react';
import type { RoleTemplate, ToolManifestEntry } from '../../api/types';

interface NodePaletteProps {
  roles: RoleTemplate[];
  tools: ToolManifestEntry[];
}

const SIDE_EFFECT_COLORS: Record<string, string> = {
  PURE: 'bg-green-900 text-green-300',
  READ: 'bg-blue-900 text-blue-300',
  WRITE: 'bg-yellow-900 text-yellow-300',
  DESTRUCTIVE: 'bg-red-900 text-red-300',
};

export default function NodePalette({ roles, tools }: NodePaletteProps) {
  const [filter, setFilter] = useState('');

  const toolMap = new Map(tools.map((t) => [t.name, t]));

  const filtered = roles.filter(
    (r) =>
      r.display_name.toLowerCase().includes(filter.toLowerCase()) ||
      r.name.toLowerCase().includes(filter.toLowerCase()),
  );

  function onDragStart(e: DragEvent, role: RoleTemplate) {
    e.dataTransfer.setData('application/agentos-role', JSON.stringify(role));
    e.dataTransfer.effectAllowed = 'move';
  }

  return (
    <div className="flex flex-col gap-3 h-full">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
        Agent Roles
      </h3>

      <input
        type="text"
        placeholder="Filter roles..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="w-full px-3 py-1.5 text-sm bg-gray-800 border border-gray-700
                   rounded text-gray-200 placeholder-gray-500
                   focus:outline-none focus:border-blue-500"
      />

      <div className="flex flex-col gap-2 overflow-y-auto flex-1">
        {filtered.map((role) => (
          <div
            key={role.name}
            draggable
            onDragStart={(e) => onDragStart(e, role)}
            className="p-3 bg-gray-800 border border-gray-700 rounded-lg
                       cursor-grab hover:border-blue-500 hover:bg-gray-750
                       transition-colors active:cursor-grabbing"
          >
            <div className="font-medium text-sm text-gray-200">
              {role.display_name}
            </div>
            <div className="text-xs text-gray-500 mt-1 line-clamp-2">
              {role.description}
            </div>
            <div className="flex flex-wrap gap-1 mt-2">
              {role.tool_names.slice(0, 4).map((tn) => {
                const tool = toolMap.get(tn);
                const color = tool
                  ? SIDE_EFFECT_COLORS[tool.side_effect] ?? 'bg-gray-700 text-gray-300'
                  : 'bg-gray-700 text-gray-300';
                return (
                  <span
                    key={tn}
                    className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${color}`}
                  >
                    {tn}
                  </span>
                );
              })}
              {role.tool_names.length > 4 && (
                <span className="px-1.5 py-0.5 rounded text-[10px] text-gray-500">
                  +{role.tool_names.length - 4}
                </span>
              )}
            </div>
          </div>
        ))}

        {/* Custom agent drop item */}
        <div
          draggable
          onDragStart={(e) =>
            onDragStart(e, {
              name: 'custom',
              display_name: 'Custom Agent',
              description: 'A blank agent you can fully configure',
              system_prompt: '',
              tool_names: [],
              suggested_model: '',
              budget_profile: {
                max_tokens: 20000,
                max_tool_calls: 20,
                max_time_seconds: 120,
                max_recursion_depth: 1,
              },
              max_steps: 50,
              max_instances: 1,
            })
          }
          className="p-3 bg-gray-800 border border-dashed border-gray-600 rounded-lg
                     cursor-grab hover:border-blue-500 transition-colors
                     active:cursor-grabbing"
        >
          <div className="font-medium text-sm text-gray-400">
            + Custom Agent
          </div>
          <div className="text-xs text-gray-600 mt-1">
            Drag to add a blank agent node
          </div>
        </div>
      </div>
    </div>
  );
}
