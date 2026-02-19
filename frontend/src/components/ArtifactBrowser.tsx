/** ArtifactBrowser v2 — tree view, agent badges, enhanced preview. */

import { useCallback, useEffect, useMemo, useState } from 'react';
import Markdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import {
  getSessionFiles,
  getSessionFileContent,
  getSessionFileUrl,
  getSessionFilesZipUrl,
} from '../api/client';
import type { EventResponse, FileEntry } from '../api/types';

// ── Helpers ────────────────────────────────────────────────────────

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const TYPE_ICONS: Record<string, string> = {
  text: 'text-blue-400',
  code: 'text-yellow-400',
  image: 'text-purple-400',
  data: 'text-cyan-400',
  binary: 'text-gray-500',
};

const TYPE_LABELS: Record<string, string> = {
  text: '\u25A0',
  code: '\u25C6',
  image: '\u25CF',
  data: '\u25B2',
  binary: '\u25CB',
};

const CODE_EXTENSIONS: Record<string, string> = {
  py: 'python',
  js: 'javascript',
  ts: 'typescript',
  tsx: 'tsx',
  jsx: 'jsx',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  css: 'css',
  html: 'html',
  sh: 'bash',
  bash: 'bash',
  sql: 'sql',
  rs: 'rust',
  go: 'go',
  java: 'java',
  rb: 'ruby',
  toml: 'toml',
  xml: 'xml',
};

const AGENT_COLORS = [
  'bg-blue-600',
  'bg-emerald-600',
  'bg-purple-600',
  'bg-amber-600',
  'bg-rose-600',
  'bg-cyan-600',
  'bg-indigo-600',
];

function agentColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) | 0;
  }
  return AGENT_COLORS[Math.abs(hash) % AGENT_COLORS.length];
}

function getExtension(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
}

function getLanguage(name: string): string | null {
  return CODE_EXTENSIONS[getExtension(name)] ?? null;
}

// ── Tree structure ─────────────────────────────────────────────────

interface TreeNode {
  name: string;
  path: string;
  file?: FileEntry;
  children: Map<string, TreeNode>;
}

function buildTree(files: FileEntry[]): TreeNode {
  const root: TreeNode = { name: '', path: '', children: new Map() };
  for (const file of files) {
    const parts = file.path.split('/').filter(Boolean);
    let node = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      if (!node.children.has(part)) {
        const childPath = parts.slice(0, i + 1).join('/');
        node.children.set(part, { name: part, path: childPath, children: new Map() });
      }
      node = node.children.get(part)!;
    }
    node.file = file;
  }
  return root;
}

function sortedChildren(node: TreeNode): TreeNode[] {
  return Array.from(node.children.values()).sort((a, b) => {
    // Directories first
    const aIsDir = !a.file && a.children.size > 0;
    const bIsDir = !b.file && b.children.size > 0;
    if (aIsDir && !bIsDir) return -1;
    if (!aIsDir && bIsDir) return 1;
    return a.name.localeCompare(b.name);
  });
}

// ── File history from events ───────────────────────────────────────

interface FileHistoryEntry {
  action: string;
  agent: string;
  time: string;
}

function buildFileHistory(events: EventResponse[]): Map<string, FileHistoryEntry[]> {
  const history = new Map<string, FileHistoryEntry[]>();
  for (const ev of events) {
    if (ev.event_type !== 'FileCreated' && ev.event_type !== 'FileModified') continue;
    const filePath = ev.payload.file_path as string;
    if (!filePath) continue;
    const entries = history.get(filePath) ?? [];
    entries.push({
      action: ev.event_type === 'FileCreated' ? 'Created' : 'Modified',
      agent: (ev.payload.created_by_agent as string) ?? '',
      time: new Date(ev.timestamp).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      }),
    });
    history.set(filePath, entries);
  }
  return history;
}

// ── CSV parser ─────────────────────────────────────────────────────

function parseCSV(text: string): string[][] {
  const lines = text.trim().split('\n');
  return lines.map((line) => {
    const cells: string[] = [];
    let current = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (inQuotes) {
        if (ch === '"' && line[i + 1] === '"') {
          current += '"';
          i++;
        } else if (ch === '"') {
          inQuotes = false;
        } else {
          current += ch;
        }
      } else if (ch === '"') {
        inQuotes = true;
      } else if (ch === ',') {
        cells.push(current);
        current = '';
      } else {
        current += ch;
      }
    }
    cells.push(current);
    return cells;
  });
}

// ── Sub-components ─────────────────────────────────────────────────

interface TreeItemProps {
  node: TreeNode;
  depth: number;
  selectedPath: string | null;
  collapsed: Set<string>;
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
  sessionId: string;
}

function TreeItem({
  node,
  depth,
  selectedPath,
  collapsed,
  onSelect,
  onToggle,
  sessionId,
}: TreeItemProps) {
  const isDir = !node.file && node.children.size > 0;
  const isCollapsed = collapsed.has(node.path);
  const children = sortedChildren(node);

  if (isDir) {
    return (
      <div>
        <div
          className="flex items-center gap-1 px-2 py-1 text-xs cursor-pointer hover:bg-gray-800 rounded"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
          onClick={() => onToggle(node.path)}
        >
          <span className="text-gray-500 w-4 text-center">
            {isCollapsed ? '\u25B6' : '\u25BC'}
          </span>
          <span className="text-gray-400">{node.name}/</span>
        </div>
        {!isCollapsed &&
          children.map((child) => (
            <TreeItem
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              collapsed={collapsed}
              onSelect={onSelect}
              onToggle={onToggle}
              sessionId={sessionId}
            />
          ))}
      </div>
    );
  }

  const file = node.file;
  if (!file) return null;

  return (
    <div
      className={`flex items-center gap-2 px-2 py-1.5 text-xs cursor-pointer transition-colors rounded ${
        selectedPath === file.path
          ? 'bg-gray-700 border border-gray-600'
          : 'hover:bg-gray-800'
      }`}
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
      onClick={() => onSelect(file.path)}
    >
      <span className={TYPE_ICONS[file.type] ?? 'text-gray-500'}>
        {TYPE_LABELS[file.type] ?? '\u25CB'}
      </span>
      <span className="text-gray-200 truncate flex-1">{node.name}</span>
      {file.created_by_agent && (
        <span
          className={`${agentColor(file.created_by_agent)} text-white text-[10px] px-1.5 py-0.5 rounded-full whitespace-nowrap`}
        >
          {file.created_by_agent}
        </span>
      )}
      <span className="text-gray-600 whitespace-nowrap">{formatSize(file.size)}</span>
      <a
        href={getSessionFileUrl(sessionId, file.path)}
        download={file.name}
        onClick={(e) => e.stopPropagation()}
        className="text-gray-600 hover:text-blue-400 transition-colors"
        title="Download"
      >
        {'\u2193'}
      </a>
    </div>
  );
}

function FileHistoryTimeline({ entries }: { entries: FileHistoryEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <div className="flex items-center gap-2 text-[10px] text-gray-500 px-1 py-1 border-b border-gray-800 mb-2 overflow-x-auto">
      {entries.map((entry, i) => (
        <span key={i} className="flex items-center gap-1 whitespace-nowrap">
          {i > 0 && <span className="text-gray-700">{'\u2192'}</span>}
          <span>
            {entry.action} by{' '}
            <span className="text-gray-400">{entry.agent || 'unknown'}</span> at{' '}
            {entry.time}
          </span>
        </span>
      ))}
    </div>
  );
}

function CSVTable({ content }: { content: string }) {
  const rows = useMemo(() => parseCSV(content), [content]);
  if (rows.length === 0) return null;
  const [header, ...body] = rows;
  return (
    <div className="overflow-auto max-h-[500px]">
      <table className="w-full text-xs text-gray-300 border-collapse">
        <thead>
          <tr>
            {header.map((cell, i) => (
              <th
                key={i}
                className="text-left px-2 py-1 border-b border-gray-700 bg-gray-800 text-gray-200 font-medium sticky top-0"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri} className="hover:bg-gray-800/50">
              {row.map((cell, ci) => (
                <td key={ci} className="px-2 py-1 border-b border-gray-800/50">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Preview renderer ───────────────────────────────────────────────

function PreviewContent({
  file,
  content,
  sessionId,
}: {
  file: FileEntry;
  content: string | null;
  sessionId: string;
}) {
  if (file.type === 'image') {
    return (
      <div className="flex items-center justify-center h-full">
        <img
          src={getSessionFileUrl(sessionId, file.path)}
          alt={file.name}
          className="max-w-full max-h-full object-contain rounded"
        />
      </div>
    );
  }

  if (file.type === 'binary') {
    return (
      <div className="text-xs text-gray-500 text-center py-8">
        Binary file —{' '}
        <a
          href={getSessionFileUrl(sessionId, file.path)}
          download={file.name}
          className="text-blue-400 hover:underline"
        >
          download
        </a>
      </div>
    );
  }

  if (content === null) return null;

  const ext = getExtension(file.name);

  // CSV → table
  if (ext === 'csv') {
    return <CSVTable content={content} />;
  }

  // Markdown → rendered
  if (ext === 'md' || ext === 'markdown') {
    return (
      <div className="prose prose-invert prose-sm max-w-none px-2 py-1 text-gray-300">
        <Markdown>{content}</Markdown>
      </div>
    );
  }

  // Code → syntax highlighted
  const lang = getLanguage(file.name);
  if (lang) {
    return (
      <SyntaxHighlighter
        language={lang}
        style={vscDarkPlus}
        customStyle={{ margin: 0, fontSize: '12px', background: 'transparent' }}
        wrapLongLines
      >
        {content}
      </SyntaxHighlighter>
    );
  }

  // Fallback: plain text
  return (
    <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-words">
      {content}
    </pre>
  );
}

// ── Main component ─────────────────────────────────────────────────

interface Props {
  events: EventResponse[];
  sessionId: string;
}

export default function ArtifactBrowser({ events, sessionId }: Props) {
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const fileHistory = useMemo(() => buildFileHistory(events), [events]);
  const tree = useMemo(() => buildTree(files), [files]);
  const zipUrl = useMemo(() => getSessionFilesZipUrl(sessionId), [sessionId]);

  // Fetch file list on mount + poll every 3s
  const fetchFiles = useCallback(() => {
    if (!sessionId) return;
    getSessionFiles(sessionId)
      .then((resp) => setFiles(resp.files))
      .catch(() => {});
  }, [sessionId]);

  useEffect(() => {
    fetchFiles();
    const interval = setInterval(fetchFiles, 3000);
    return () => clearInterval(interval);
  }, [fetchFiles]);

  // Load file content on selection
  useEffect(() => {
    if (!selectedPath) {
      setPreview(null);
      return;
    }

    const file = files.find((f) => f.path === selectedPath);
    if (!file) return;

    if (file.type === 'image' || file.type === 'binary') {
      setPreview(null);
      return;
    }

    setLoadingPreview(true);
    getSessionFileContent(sessionId, file.path)
      .then(setPreview)
      .catch(() => setPreview('Failed to load file content.'))
      .finally(() => setLoadingPreview(false));
  }, [selectedPath, sessionId, files]);

  const handleSelect = useCallback(
    (path: string) => setSelectedPath((prev) => (prev === path ? null : path)),
    [],
  );

  const handleToggle = useCallback(
    (path: string) =>
      setCollapsed((prev) => {
        const next = new Set(prev);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        return next;
      }),
    [],
  );

  if (files.length === 0) {
    return (
      <div className="text-xs text-gray-600 text-center py-4">
        No files produced yet.
      </div>
    );
  }

  const selected = files.find((f) => f.path === selectedPath);
  const selectedHistory = selectedPath ? fileHistory.get(selectedPath) ?? [] : [];

  return (
    <div className="flex flex-col h-full">
      {/* Header bar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
        <span className="text-xs text-gray-400">
          {files.length} file{files.length !== 1 ? 's' : ''}
        </span>
        <a
          href={zipUrl}
          download
          className="text-xs text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1"
        >
          {'\u2913'} Download All
        </a>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Tree panel */}
        <div className="w-1/3 min-w-[180px] overflow-y-auto py-1">
          {sortedChildren(tree).map((child) => (
            <TreeItem
              key={child.path}
              node={child}
              depth={0}
              selectedPath={selectedPath}
              collapsed={collapsed}
              onSelect={handleSelect}
              onToggle={handleToggle}
              sessionId={sessionId}
            />
          ))}
        </div>

        {/* Preview panel */}
        <div className="flex-1 overflow-y-auto border-l border-gray-800 pl-3 flex flex-col">
          {!selected ? (
            <div className="text-xs text-gray-600 text-center py-8">
              Click a file to preview
            </div>
          ) : (
            <>
              <FileHistoryTimeline entries={selectedHistory} />
              {loadingPreview ? (
                <div className="text-xs text-gray-500 text-center py-8">
                  Loading...
                </div>
              ) : (
                <PreviewContent
                  file={selected}
                  content={preview}
                  sessionId={sessionId}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
