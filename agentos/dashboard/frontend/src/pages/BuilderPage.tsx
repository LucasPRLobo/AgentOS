import { useCallback, useState } from 'react'
import { Canvas } from '../components/builder/Canvas'
import type { CanvasNode, CanvasEdge } from '../components/builder/Canvas'
import { NodePalette } from '../components/builder/NodePalette'
import type { PaletteItem } from '../components/builder/NodePalette'
import { PropertyPanel } from '../components/builder/PropertyPanel'
import { ExportImport } from '../components/builder/ExportImport'

let nextId = 1

export function BuilderPage() {
  const [nodes, setNodes] = useState<CanvasNode[]>([])
  const [edges, setEdges] = useState<CanvasEdge[]>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string>()
  const [edgeMode, setEdgeMode] = useState<string | null>(null)

  const handleDrop = useCallback((_x: number, _y: number, item: PaletteItem) => {
    const id = `node-${nextId++}`
    const newNode: CanvasNode = {
      id,
      type: item.type,
      label: `${item.label} ${nextId - 1}`,
      x: _x,
      y: _y,
      config: { name: `${item.label} ${nextId - 1}` },
    }
    setNodes((prev) => [...prev, newNode])
    setSelectedNodeId(id)
  }, [])

  const handleNodeMove = useCallback((nodeId: string, x: number, y: number) => {
    setNodes((prev) =>
      prev.map((n) => (n.id === nodeId ? { ...n, x, y } : n))
    )
  }, [])

  const handleNodeSelect = useCallback(
    (nodeId: string | undefined) => {
      if (edgeMode && nodeId && nodeId !== edgeMode) {
        const edgeId = `edge-${edgeMode}-${nodeId}`
        setEdges((prev) => [...prev, { id: edgeId, from: edgeMode, to: nodeId }])
        setEdgeMode(null)
      }
      setSelectedNodeId(nodeId)
    },
    [edgeMode]
  )

  const handleNodeUpdate = useCallback((nodeId: string, config: Record<string, string>) => {
    setNodes((prev) =>
      prev.map((n) => (n.id === nodeId ? { ...n, config } : n))
    )
  }, [])

  const handleNodeDelete = useCallback(
    (nodeId: string) => {
      setNodes((prev) => prev.filter((n) => n.id !== nodeId))
      setEdges((prev) => prev.filter((e) => e.from !== nodeId && e.to !== nodeId))
      if (selectedNodeId === nodeId) setSelectedNodeId(undefined)
    },
    [selectedNodeId]
  )

  const selectedNode = nodes.find((n) => n.id === selectedNodeId)

  return (
    <div className="builder-page" data-testid="builder-page">
      <div className="builder-toolbar">
        <h2>Workflow Builder</h2>
        <button
          data-testid="add-edge-btn"
          onClick={() => setEdgeMode(selectedNodeId || null)}
          disabled={!selectedNodeId}
        >
          {edgeMode ? 'Click target node...' : 'Add Edge'}
        </button>
        <ExportImport nodes={nodes} edges={edges} />
      </div>
      <div className="builder-layout">
        <NodePalette />
        <Canvas
          nodes={nodes}
          edges={edges}
          selectedNodeId={selectedNodeId}
          onNodeMove={handleNodeMove}
          onNodeSelect={handleNodeSelect}
          onDrop={handleDrop}
        />
        <PropertyPanel
          node={selectedNode}
          onUpdate={handleNodeUpdate}
          onDelete={handleNodeDelete}
        />
      </div>
    </div>
  )
}
