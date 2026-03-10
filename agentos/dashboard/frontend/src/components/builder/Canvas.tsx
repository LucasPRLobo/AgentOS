import { useCallback, useRef, useState } from 'react'
import type { PaletteItem } from './NodePalette'

export interface CanvasNode {
  id: string
  type: PaletteItem['type']
  label: string
  x: number
  y: number
  config: Record<string, string>
}

export interface CanvasEdge {
  id: string
  from: string
  to: string
}

interface CanvasProps {
  nodes: CanvasNode[]
  edges: CanvasEdge[]
  selectedNodeId?: string
  onNodeAdd?: (node: CanvasNode) => void
  onNodeMove?: (nodeId: string, x: number, y: number) => void
  onNodeSelect?: (nodeId: string | undefined) => void
  onEdgeAdd?: (edge: CanvasEdge) => void
  onDrop?: (x: number, y: number, item: PaletteItem) => void
}

export function Canvas({
  nodes,
  edges,
  selectedNodeId,
  onNodeMove,
  onNodeSelect,
  onDrop,
}: CanvasProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [dragging, setDragging] = useState<string | null>(null)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      const rect = svgRef.current?.getBoundingClientRect()
      if (!rect) return
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      const itemData = e.dataTransfer.getData('application/json')
      if (itemData) {
        const item = JSON.parse(itemData) as PaletteItem
        onDrop?.(x, y, item)
      }
    },
    [onDrop]
  )

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
  }, [])

  const handleMouseDown = useCallback(
    (nodeId: string) => {
      setDragging(nodeId)
      onNodeSelect?.(nodeId)
    },
    [onNodeSelect]
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!dragging || !svgRef.current) return
      const rect = svgRef.current.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      onNodeMove?.(dragging, x, y)
    },
    [dragging, onNodeMove]
  )

  const handleMouseUp = useCallback(() => {
    setDragging(null)
  }, [])

  const handleCanvasClick = useCallback(() => {
    onNodeSelect?.(undefined)
  }, [onNodeSelect])

  return (
    <svg
      ref={svgRef}
      className="builder-canvas"
      data-testid="builder-canvas"
      width="100%"
      height="600"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onClick={handleCanvasClick}
    >
      {/* Render edges */}
      {edges.map((edge) => {
        const fromNode = nodes.find((n) => n.id === edge.from)
        const toNode = nodes.find((n) => n.id === edge.to)
        if (!fromNode || !toNode) return null
        return (
          <line
            key={edge.id}
            data-testid={`edge-${edge.id}`}
            x1={fromNode.x + 60}
            y1={fromNode.y + 20}
            x2={toNode.x + 60}
            y2={toNode.y + 20}
            stroke="#666"
            strokeWidth={2}
            markerEnd="url(#arrowhead)"
          />
        )
      })}

      {/* Render nodes */}
      {nodes.map((node) => (
        <g
          key={node.id}
          data-testid={`canvas-node-${node.id}`}
          transform={`translate(${node.x}, ${node.y})`}
          onMouseDown={(e) => {
            e.stopPropagation()
            handleMouseDown(node.id)
          }}
          style={{ cursor: 'grab' }}
        >
          <rect
            width={120}
            height={40}
            rx={6}
            fill={selectedNodeId === node.id ? '#4a90d9' : '#2a2a2a'}
            stroke={selectedNodeId === node.id ? '#6ab0ff' : '#555'}
            strokeWidth={selectedNodeId === node.id ? 2 : 1}
          />
          <text
            x={60}
            y={25}
            textAnchor="middle"
            fill="white"
            fontSize={12}
          >
            {node.label}
          </text>
        </g>
      ))}

      <defs>
        <marker
          id="arrowhead"
          markerWidth="10"
          markerHeight="7"
          refX="10"
          refY="3.5"
          orient="auto"
        >
          <polygon points="0 0, 10 3.5, 0 7" fill="#666" />
        </marker>
      </defs>
    </svg>
  )
}
