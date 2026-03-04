import type { CanvasNode } from './Canvas'

interface PropertyPanelProps {
  node: CanvasNode | undefined
  onUpdate?: (nodeId: string, config: Record<string, string>) => void
  onDelete?: (nodeId: string) => void
}

export function PropertyPanel({ node, onUpdate, onDelete }: PropertyPanelProps) {
  if (!node) {
    return (
      <div className="property-panel" data-testid="property-panel-empty">
        <p>Select a node to edit its properties</p>
      </div>
    )
  }

  const handleChange = (key: string, value: string) => {
    onUpdate?.(node.id, { ...node.config, [key]: value })
  }

  return (
    <div className="property-panel" data-testid="property-panel">
      <h3>{node.label}</h3>
      <div className="property-fields">
        <label>
          Name
          <input
            type="text"
            value={node.config.name || node.label}
            onChange={(e) => handleChange('name', e.target.value)}
            data-testid="prop-name"
          />
        </label>
        <label>
          Description
          <textarea
            value={node.config.description || ''}
            onChange={(e) => handleChange('description', e.target.value)}
            data-testid="prop-description"
          />
        </label>
        {node.type === 'task' && (
          <label>
            Agent
            <input
              type="text"
              value={node.config.agent || ''}
              onChange={(e) => handleChange('agent', e.target.value)}
              data-testid="prop-agent"
            />
          </label>
        )}
        {node.type === 'gate' && (
          <label>
            Gate Type
            <select
              value={node.config.gate_type || 'approval'}
              onChange={(e) => handleChange('gate_type', e.target.value)}
              data-testid="prop-gate-type"
            >
              <option value="approval">Approval</option>
              <option value="input">Input</option>
            </select>
          </label>
        )}
      </div>
      <button
        className="delete-btn"
        data-testid="delete-node"
        onClick={() => onDelete?.(node.id)}
      >
        Delete Node
      </button>
    </div>
  )
}
