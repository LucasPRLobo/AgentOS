/** Agent node — custom React Flow node for workflow agents. */

import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';

export interface AgentNodeData {
  label: string;
  role: string;
  model: string;
  toolCount: number;
  isValid: boolean;
  isSelected: boolean;
  persona_preset: string;
}

const PRESET_ICONS: Record<string, string> = {
  analytical: 'A',
  creative: 'C',
  formal: 'F',
  concise: 'X',
  friendly: 'H',
};

const PRESET_COLORS: Record<string, string> = {
  analytical: 'bg-blue-600',
  creative: 'bg-purple-600',
  formal: 'bg-gray-600',
  concise: 'bg-cyan-600',
  friendly: 'bg-green-600',
};

function AgentNodeComponent({ data }: NodeProps) {
  const d = data as unknown as AgentNodeData;
  const presetIcon = PRESET_ICONS[d.persona_preset] ?? '?';
  const presetColor = PRESET_COLORS[d.persona_preset] ?? 'bg-gray-600';

  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 bg-gray-900 min-w-[180px]
        transition-colors
        ${d.isSelected ? 'border-blue-500 shadow-lg shadow-blue-500/20' : 'border-gray-700'}
        ${!d.isValid ? 'border-red-500/50' : ''}
      `}
    >
      <Handle type="target" position={Position.Left} className="!bg-gray-500 !w-3 !h-3" />

      {/* Header row */}
      <div className="flex items-center gap-2">
        <div className={`w-7 h-7 rounded-full ${presetColor} flex items-center justify-center text-white text-xs font-bold`}>
          {presetIcon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm text-gray-100 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-gray-500 truncate">
            {d.role}
          </div>
        </div>
      </div>

      {/* Info row */}
      <div className="flex items-center gap-3 mt-2 text-[11px]">
        {d.model && (
          <span className="px-1.5 py-0.5 bg-gray-800 rounded text-gray-400 truncate max-w-[100px]">
            {d.model}
          </span>
        )}
        {d.toolCount > 0 && (
          <span className="text-gray-500">
            {d.toolCount} tool{d.toolCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Validation indicator */}
      {!d.isValid && (
        <div className="mt-1.5 text-[10px] text-red-400">
          Configuration incomplete
        </div>
      )}

      <Handle type="source" position={Position.Right} className="!bg-gray-500 !w-3 !h-3" />
    </div>
  );
}

export default memo(AgentNodeComponent);
