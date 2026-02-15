/** DagGraph — simple DAG visualization for agent phases. */

interface DagNode {
  id: string;
  label: string;
  state: 'pending' | 'running' | 'succeeded' | 'failed';
}

const STATE_STYLES: Record<string, string> = {
  pending: 'bg-gray-800 border-gray-600 text-gray-400',
  running: 'bg-blue-900 border-blue-500 text-blue-300 animate-pulse',
  succeeded: 'bg-green-900 border-green-600 text-green-300',
  failed: 'bg-red-900 border-red-600 text-red-300',
};

interface Props {
  nodes: DagNode[];
}

export default function DagGraph({ nodes }: Props) {
  return (
    <div className="flex items-center gap-2 overflow-x-auto py-4">
      {nodes.map((node, i) => (
        <div key={node.id} className="flex items-center gap-2">
          <div
            className={`px-4 py-2 rounded-lg border-2 text-sm font-medium ${STATE_STYLES[node.state] ?? STATE_STYLES.pending}`}
          >
            {node.label}
          </div>
          {i < nodes.length - 1 && (
            <svg width="24" height="24" viewBox="0 0 24 24" className="text-gray-600 shrink-0">
              <path d="M5 12h14m-4-4 4 4-4 4" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </div>
      ))}
    </div>
  );
}
