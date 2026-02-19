/** ArtifactBrowser — real file browser backed by workspace API. */

import { useCallback, useEffect, useState } from 'react';
import {
  getSessionFiles,
  getSessionFileContent,
  getSessionFileUrl,
} from '../api/client';
import type { EventResponse, FileEntry } from '../api/types';

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

interface Props {
  events: EventResponse[];
  sessionId: string;
}

export default function ArtifactBrowser({ events: _events, sessionId }: Props) {
  void _events; // kept for interface compatibility
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);

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
    if (!selectedFile) {
      setPreview(null);
      return;
    }

    const file = files.find((f) => f.path === selectedFile);
    if (!file) return;

    if (file.type === 'image') {
      // Images are shown via <img> tag, no need to fetch content
      setPreview(null);
      return;
    }

    if (file.type === 'binary') {
      setPreview(null);
      return;
    }

    // Fetch text content
    setLoadingPreview(true);
    getSessionFileContent(sessionId, file.path)
      .then(setPreview)
      .catch(() => setPreview('Failed to load file content.'))
      .finally(() => setLoadingPreview(false));
  }, [selectedFile, sessionId, files]);

  if (files.length === 0) {
    return (
      <div className="text-xs text-gray-600 text-center py-4">
        No files produced yet.
      </div>
    );
  }

  const selected = files.find((f) => f.path === selectedFile);

  return (
    <div className="flex h-full gap-3">
      {/* File list */}
      <div className="w-1/3 min-w-[180px] overflow-y-auto space-y-1">
        {files.map((file) => (
          <div
            key={file.path}
            className={`flex items-center gap-2 px-3 py-2 rounded text-xs cursor-pointer transition-colors ${
              selectedFile === file.path
                ? 'bg-gray-700 border border-gray-600'
                : 'hover:bg-gray-800'
            }`}
            onClick={() =>
              setSelectedFile(selectedFile === file.path ? null : file.path)
            }
          >
            <span className={TYPE_ICONS[file.type] ?? 'text-gray-500'}>
              {TYPE_LABELS[file.type] ?? '\u25CB'}
            </span>
            <span className="text-gray-200 truncate flex-1">{file.name}</span>
            <span className="text-gray-600 whitespace-nowrap">
              {formatSize(file.size)}
            </span>
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
        ))}
      </div>

      {/* Preview panel */}
      <div className="flex-1 overflow-y-auto border-l border-gray-800 pl-3">
        {!selected ? (
          <div className="text-xs text-gray-600 text-center py-8">
            Click a file to preview
          </div>
        ) : selected.type === 'image' ? (
          <div className="flex items-center justify-center h-full">
            <img
              src={getSessionFileUrl(sessionId, selected.path)}
              alt={selected.name}
              className="max-w-full max-h-full object-contain rounded"
            />
          </div>
        ) : selected.type === 'binary' ? (
          <div className="text-xs text-gray-500 text-center py-8">
            Binary file — download only
          </div>
        ) : loadingPreview ? (
          <div className="text-xs text-gray-500 text-center py-8">
            Loading...
          </div>
        ) : (
          <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-words">
            {preview}
          </pre>
        )}
      </div>
    </div>
  );
}
