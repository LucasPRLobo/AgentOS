/** Toolbar — workflow builder actions: save, run, validate, delete. */

import { useState } from 'react';
import type { WorkflowValidationResult } from '../../api/types';

interface ToolbarProps {
  workflowName: string;
  nodeCount: number;
  edgeCount: number;
  isSaved: boolean;
  isNew: boolean;
  validationResult: WorkflowValidationResult | null;
  onNameChange: (name: string) => void;
  onSave: () => Promise<void>;
  onRun: () => Promise<void>;
  onValidate: () => Promise<void>;
  onDelete: () => Promise<void>;
}

export default function Toolbar({
  workflowName,
  nodeCount,
  edgeCount,
  isSaved,
  isNew,
  validationResult,
  onNameChange,
  onSave,
  onRun,
  onValidate,
  onDelete,
}: ToolbarProps) {
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await onSave();
    } finally {
      setSaving(false);
    }
  }

  async function handleRun() {
    setRunning(true);
    try {
      await onRun();
    } finally {
      setRunning(false);
    }
  }

  async function handleDelete() {
    setShowDeleteConfirm(false);
    await onDelete();
  }

  const validColor = validationResult
    ? validationResult.valid
      ? 'text-green-400'
      : 'text-red-400'
    : 'text-gray-500';

  const validLabel = validationResult
    ? validationResult.valid
      ? 'Valid'
      : `${validationResult.issues.length} issue${validationResult.issues.length !== 1 ? 's' : ''}`
    : 'Not validated';

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-gray-900 border-b border-gray-800">
      {/* Workflow name */}
      <input
        type="text"
        value={workflowName}
        onChange={(e) => onNameChange(e.target.value)}
        className="px-2 py-1 text-sm font-medium bg-transparent border border-transparent
                   rounded text-gray-200 hover:border-gray-700
                   focus:outline-none focus:border-blue-500 min-w-[200px]"
        placeholder="Untitled Workflow"
      />

      <div className="flex-1" />

      {/* Status indicators */}
      <div className="flex items-center gap-4 text-xs text-gray-500 mr-2">
        <span>{nodeCount} node{nodeCount !== 1 ? 's' : ''}</span>
        <span>{edgeCount} edge{edgeCount !== 1 ? 's' : ''}</span>
        <span className={validColor}>{validLabel}</span>
        {!isSaved && <span className="text-yellow-500">Unsaved</span>}
      </div>

      {/* Actions */}
      <button
        onClick={onValidate}
        className="px-3 py-1.5 text-xs rounded bg-gray-800 text-gray-300
                   border border-gray-700 hover:border-gray-600 hover:text-gray-200
                   transition-colors"
      >
        Validate
      </button>

      <button
        onClick={handleSave}
        disabled={saving}
        className="px-3 py-1.5 text-xs rounded bg-gray-800 text-gray-300
                   border border-gray-700 hover:border-blue-500 hover:text-blue-300
                   transition-colors disabled:opacity-50"
      >
        {saving ? 'Saving...' : 'Save'}
      </button>

      <button
        onClick={handleRun}
        disabled={running || nodeCount === 0}
        className="px-4 py-1.5 text-xs rounded bg-blue-600 text-white font-medium
                   hover:bg-blue-500 transition-colors
                   disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {running ? 'Starting...' : 'Run'}
      </button>

      {!isNew && (
        <>
          <button
            onClick={() => setShowDeleteConfirm(true)}
            className="px-3 py-1.5 text-xs rounded bg-gray-800 text-red-400
                       border border-gray-700 hover:border-red-500
                       transition-colors"
          >
            Delete
          </button>

          {showDeleteConfirm && (
            <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
              <div className="bg-gray-900 border border-gray-700 rounded-lg p-6 max-w-sm">
                <h3 className="text-sm font-semibold text-gray-200 mb-2">
                  Delete Workflow?
                </h3>
                <p className="text-xs text-gray-400 mb-4">
                  This will permanently delete &ldquo;{workflowName}&rdquo;.
                  This action cannot be undone.
                </p>
                <div className="flex gap-2 justify-end">
                  <button
                    onClick={() => setShowDeleteConfirm(false)}
                    className="px-3 py-1.5 text-xs rounded bg-gray-800 text-gray-300
                               border border-gray-700 hover:border-gray-600"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleDelete}
                    className="px-3 py-1.5 text-xs rounded bg-red-600 text-white
                               hover:bg-red-500"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
