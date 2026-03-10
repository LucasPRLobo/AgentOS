import { useState } from 'react'

export interface PaletteItem {
  type: 'task' | 'gate' | 'adversarial'
  label: string
  description: string
}

const PALETTE_ITEMS: PaletteItem[] = [
  { type: 'task', label: 'Task', description: 'An agent task node' },
  { type: 'gate', label: 'Gate', description: 'Approval gate node' },
  { type: 'adversarial', label: 'Adversarial', description: 'Adversarial validation node' },
]

interface NodePaletteProps {
  onDragStart?: (item: PaletteItem) => void
}

export function NodePalette({ onDragStart }: NodePaletteProps) {
  const [filter, setFilter] = useState('')

  const filtered = PALETTE_ITEMS.filter(
    (item) =>
      item.label.toLowerCase().includes(filter.toLowerCase()) ||
      item.description.toLowerCase().includes(filter.toLowerCase())
  )

  return (
    <div className="node-palette" data-testid="node-palette">
      <h3>Nodes</h3>
      <input
        type="text"
        placeholder="Filter nodes..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        data-testid="palette-filter"
      />
      <div className="palette-items">
        {filtered.map((item) => (
          <div
            key={item.type}
            className="palette-item"
            draggable
            data-testid={`palette-item-${item.type}`}
            onDragStart={() => onDragStart?.(item)}
          >
            <span className="palette-item-label">{item.label}</span>
            <span className="palette-item-desc">{item.description}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
