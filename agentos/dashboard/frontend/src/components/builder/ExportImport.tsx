import { useCallback, useRef } from 'react'
import type { CanvasNode, CanvasEdge } from './Canvas'

interface ExportImportProps {
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  onImport?: (yaml: string) => void
}

function nodesToYaml(nodes: CanvasNode[], edges: CanvasEdge[]): string {
  const tasks: Record<string, Record<string, unknown>> = {}
  for (const node of nodes) {
    const taskDef: Record<string, unknown> = {
      name: node.config.name || node.label,
      description: node.config.description || '',
    }
    if (node.type === 'task' && node.config.agent) {
      taskDef.agent = node.config.agent
    }
    if (node.type === 'gate') {
      taskDef.type = node.config.gate_type || 'approval'
    }
    if (node.type === 'adversarial') {
      taskDef.type = 'adversarial'
    }
    const deps = edges.filter((e) => e.to === node.id).map((e) => {
      const fromNode = nodes.find((n) => n.id === e.from)
      return fromNode?.config.name || fromNode?.label || e.from
    })
    if (deps.length > 0) {
      taskDef.depends_on = deps
    }
    const key = (node.config.name || node.label).toLowerCase().replace(/\s+/g, '_')
    tasks[key] = taskDef
  }

  const workflow = {
    name: 'untitled-workflow',
    version: '1.0',
    agents: {} as Record<string, unknown>,
    tasks,
  }

  // Simple YAML serialization (no dependency needed)
  return toYamlString(workflow)
}

function toYamlString(obj: unknown, indent = 0): string {
  const prefix = '  '.repeat(indent)
  if (obj === null || obj === undefined) return 'null'
  if (typeof obj === 'string') return obj.includes(':') || obj.includes('#') ? `"${obj}"` : obj
  if (typeof obj === 'number' || typeof obj === 'boolean') return String(obj)
  if (Array.isArray(obj)) {
    if (obj.length === 0) return '[]'
    return obj.map((item) => `${prefix}- ${toYamlString(item, indent + 1).trimStart()}`).join('\n')
  }
  if (typeof obj === 'object') {
    const entries = Object.entries(obj as Record<string, unknown>)
    if (entries.length === 0) return '{}'
    return entries
      .map(([key, val]) => {
        if (typeof val === 'object' && val !== null && !Array.isArray(val) && Object.keys(val).length > 0) {
          return `${prefix}${key}:\n${toYamlString(val, indent + 1)}`
        }
        if (Array.isArray(val) && val.length > 0) {
          return `${prefix}${key}:\n${toYamlString(val, indent + 1)}`
        }
        return `${prefix}${key}: ${toYamlString(val, indent)}`
      })
      .join('\n')
  }
  return String(obj)
}

export function ExportImport({ nodes, edges, onImport }: ExportImportProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleExport = useCallback(() => {
    const yaml = nodesToYaml(nodes, edges)
    const blob = new Blob([yaml], { type: 'text/yaml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'workflow.yaml'
    a.click()
    URL.revokeObjectURL(url)
  }, [nodes, edges])

  const handleImportClick = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = () => {
        onImport?.(reader.result as string)
      }
      reader.readAsText(file)
    },
    [onImport]
  )

  return (
    <div className="export-import" data-testid="export-import">
      <button data-testid="export-btn" onClick={handleExport}>
        Export YAML
      </button>
      <button data-testid="import-btn" onClick={handleImportClick}>
        Import YAML
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".yaml,.yml"
        style={{ display: 'none' }}
        onChange={handleFileChange}
        data-testid="import-file-input"
      />
    </div>
  )
}

export { nodesToYaml }
