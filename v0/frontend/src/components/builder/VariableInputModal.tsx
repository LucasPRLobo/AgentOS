/** VariableInputModal — prompts user for workflow variable values before run. */

import { useState } from 'react';
import type { WorkflowVariable } from '../../api/types';

interface Props {
  variables: WorkflowVariable[];
  onRun: (values: Record<string, string>) => void;
  onCancel: () => void;
}

export default function VariableInputModal({
  variables,
  onRun,
  onCancel,
}: Props) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const v of variables) {
      initial[v.name] = v.default_value ?? '';
    }
    return initial;
  });

  function handleChange(name: string, value: string) {
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onRun(values);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-gray-900 border border-gray-700 rounded-lg shadow-xl w-full max-w-md mx-4">
        <form onSubmit={handleSubmit}>
          {/* Header */}
          <div className="px-6 py-4 border-b border-gray-800">
            <h3 className="text-lg font-semibold text-white">
              Configure Variables
            </h3>
            <p className="text-xs text-gray-500 mt-1">
              Set values for this workflow run
            </p>
          </div>

          {/* Variables */}
          <div className="px-6 py-4 space-y-4 max-h-80 overflow-y-auto">
            {variables.map((v) => (
              <div key={v.name}>
                <label className="block text-xs font-medium text-gray-300 mb-1">
                  {v.name}
                  {v.description && (
                    <span className="ml-2 text-gray-600 font-normal">
                      {v.description}
                    </span>
                  )}
                </label>
                <input
                  type="text"
                  value={values[v.name] ?? ''}
                  onChange={(e) => handleChange(v.name, e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500"
                  placeholder={v.default_value || `Enter ${v.name}...`}
                />
              </div>
            ))}
          </div>

          {/* Actions */}
          <div className="px-6 py-4 border-t border-gray-800 flex justify-end gap-3">
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition-colors"
            >
              Run
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
