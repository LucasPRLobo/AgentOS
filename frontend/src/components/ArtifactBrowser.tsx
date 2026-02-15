/** ArtifactBrowser — displays files produced during a session. */

import { useState } from 'react';
import type { EventResponse } from '../api/types';

interface ArtifactEntry {
  name: string;
  type: 'file' | 'write';
  agent: string;
  timestamp: string;
}

function extractArtifacts(events: EventResponse[]): ArtifactEntry[] {
  const artifacts: ArtifactEntry[] = [];
  const seen = new Set<string>();

  for (const e of events) {
    if (e.event_type !== 'ToolCallFinished') continue;
    const toolName = e.payload.tool_name as string | undefined;
    if (!toolName) continue;

    // Detect file-writing tools
    if (
      toolName === 'file_write' ||
      toolName === 'google_docs_write' ||
      toolName === 'google_sheets_write'
    ) {
      const output = e.payload.output as string | undefined;
      const fileName =
        (e.payload.file_path as string) ||
        (e.payload.path as string) ||
        output?.match(/(?:saved?|wro?te?|created?)\s+(?:to\s+)?["']?([^\s"']+)/i)?.[1] ||
        `artifact_${artifacts.length + 1}`;

      if (!seen.has(fileName)) {
        seen.add(fileName);
        artifacts.push({
          name: fileName,
          type: 'file',
          agent: (e.payload.agent_role as string) || 'unknown',
          timestamp: e.timestamp,
        });
      }
    }
  }

  return artifacts;
}

const FILE_ICONS: Record<string, string> = {
  md: 'text-blue-400',
  txt: 'text-gray-400',
  py: 'text-yellow-400',
  json: 'text-green-400',
  csv: 'text-cyan-400',
  png: 'text-purple-400',
};

function getFileColor(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  return FILE_ICONS[ext] ?? 'text-gray-400';
}

interface Props {
  events: EventResponse[];
}

export default function ArtifactBrowser({ events }: Props) {
  const artifacts = extractArtifacts(events);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);

  if (artifacts.length === 0) {
    return (
      <div className="text-xs text-gray-600 text-center py-4">
        No artifacts produced yet.
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {artifacts.map((art, i) => (
        <button
          key={`${art.name}-${i}`}
          onClick={() => setSelectedIdx(selectedIdx === i ? null : i)}
          className={`w-full text-left px-3 py-2 rounded text-xs transition-colors ${
            selectedIdx === i
              ? 'bg-gray-700 border border-gray-600'
              : 'hover:bg-gray-800'
          }`}
        >
          <div className="flex items-center gap-2">
            <span className={getFileColor(art.name)}>
              {art.name.split('/').pop()}
            </span>
            <span className="text-gray-600 ml-auto">{art.agent}</span>
          </div>
          {selectedIdx === i && (
            <div className="mt-1 text-[10px] text-gray-500">
              Full path: {art.name}
            </div>
          )}
        </button>
      ))}
    </div>
  );
}
