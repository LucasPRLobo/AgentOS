/** Workflow builder — visual drag-and-drop workflow editor with React Flow. */

import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  ReactFlow,
  addEdge,
  useNodesState,
  useEdgesState,
  Background,
  Controls,
  MiniMap,
  type Connection,
  type Edge,
  type Node,
  type OnConnect,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import {
  getPack,
  getWorkflow,
  listModels,
  saveWorkflow,
  updateWorkflow,
  deleteWorkflow,
  validateWorkflow,
  runWorkflow,
} from '../api/client';
import type {
  DomainPackDetail,
  ModelInfo,
  RoleTemplate,
  WorkflowDefinition,
  WorkflowNode,
  WorkflowNodeConfig,
  WorkflowValidationResult,
} from '../api/types';

import AgentNode, { type AgentNodeData } from '../components/builder/AgentNode';
import ConfigPanel from '../components/builder/ConfigPanel';
import ErrorBanner from '../components/ErrorBanner';
import NodePalette from '../components/builder/NodePalette';
import Spinner from '../components/Spinner';
import Toolbar from '../components/builder/Toolbar';

const NODE_TYPES = { agentNode: AgentNode };

function newNodeId(): string {
  return `node_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

function newWorkflowId(): string {
  return `wf_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

function makeDefaultConfig(role?: RoleTemplate): WorkflowNodeConfig {
  return {
    model: role?.suggested_model ?? '',
    system_prompt: role?.system_prompt ?? '',
    persona_preset: 'analytical',
    tools: role?.tool_names ?? [],
    budget: role?.budget_profile ?? null,
    max_steps: role?.max_steps ?? 50,
    advanced: null,
  };
}

/** Convert our WorkflowNode[] to React Flow nodes. */
function toNodes(
  nodes: WorkflowNode[],
  selectedId: string | null,
): Node[] {
  return nodes.map((n) => ({
    id: n.id,
    type: 'agentNode',
    position: n.position,
    data: {
      label: n.display_name,
      role: n.role,
      model: n.config.model,
      toolCount: n.config.tools.length,
      isValid: Boolean(n.config.model && n.display_name),
      isSelected: n.id === selectedId,
      persona_preset: n.config.persona_preset,
    } satisfies AgentNodeData,
  }));
}

export default function WorkflowBuilder() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const isNew = !id || id === 'new';
  const packName = searchParams.get('pack') ?? 'labos';

  // Workflow state
  const [workflowId, setWorkflowId] = useState(isNew ? newWorkflowId() : id!);
  const [workflowName, setWorkflowName] = useState('Untitled Workflow');
  const [workflowDescription, setWorkflowDescription] = useState('');
  const [workflowNodes, setWorkflowNodes] = useState<WorkflowNode[]>([]);
  const [isSaved, setIsSaved] = useState(!isNew);
  const [validationResult, setValidationResult] = useState<WorkflowValidationResult | null>(null);

  // React Flow state
  const [rfNodes, setNodes, onNodesChange] = useNodesState<Node>([] as Node[]);
  const [rfEdges, setRFEdges, onEdgesChange] = useEdgesState<Edge>([] as Edge[]);

  // UI state
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [pack, setPack] = useState<DomainPackDetail | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [actionError, setActionError] = useState('');
  const [loadingWorkflow, setLoadingWorkflow] = useState(!isNew);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  // Load domain pack and models
  useEffect(() => {
    getPack(packName).then(setPack).catch(console.error);
    listModels().then(setModels).catch(console.error);
  }, [packName]);

  // Load existing workflow
  useEffect(() => {
    if (!isNew && id) {
      setLoadingWorkflow(true);
      getWorkflow(id)
        .then((wf) => {
          setWorkflowId(wf.id);
          setWorkflowName(wf.name);
          setWorkflowDescription(wf.description);
          setWorkflowNodes(wf.nodes);
          setNodes(toNodes(wf.nodes, null));
          setRFEdges(
            wf.edges.map((e) => ({
              id: `${e.source}-${e.target}`,
              source: e.source,
              target: e.target,
            })),
          );
          setIsSaved(true);
        })
        .catch((err) => setActionError(err instanceof Error ? err.message : 'Failed to load workflow'))
        .finally(() => setLoadingWorkflow(false));
    }
  }, [id, isNew, setNodes, setRFEdges]);

  // Sync RF nodes when workflowNodes change
  useEffect(() => {
    setNodes(toNodes(workflowNodes, selectedNodeId));
  }, [workflowNodes, selectedNodeId, setNodes]);

  // ── Node operations ────────────────────────────────────────

  function addNode(role: RoleTemplate, position: { x: number; y: number }) {
    const nodeId = newNodeId();
    const newNode: WorkflowNode = {
      id: nodeId,
      role: role.name,
      display_name: role.display_name,
      position,
      config: makeDefaultConfig(role),
    };
    setWorkflowNodes((prev) => [...prev, newNode]);
    setIsSaved(false);
    setSelectedNodeId(nodeId);
  }

  function updateNodeConfig(nodeId: string, config: WorkflowNodeConfig) {
    setWorkflowNodes((prev) =>
      prev.map((n) => (n.id === nodeId ? { ...n, config } : n)),
    );
    setIsSaved(false);
  }

  function updateNodeDisplayName(nodeId: string, name: string) {
    setWorkflowNodes((prev) =>
      prev.map((n) => (n.id === nodeId ? { ...n, display_name: name } : n)),
    );
    setIsSaved(false);
  }

  // ── React Flow callbacks ────────────────────────────────────

  const onConnect: OnConnect = useCallback(
    (params: Connection) => {
      setRFEdges((eds) => addEdge(params, eds));
      setIsSaved(false);
    },
    [setRFEdges],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNodeId(node.id);
    },
    [],
  );

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  // Sync position changes back to workflowNodes
  const onNodeDragStop = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setWorkflowNodes((prev) =>
        prev.map((n) =>
          n.id === node.id ? { ...n, position: node.position } : n,
        ),
      );
    },
    [],
  );

  const onNodesDelete = useCallback(
    (deleted: Node[]) => {
      const ids = new Set(deleted.map((n) => n.id));
      setWorkflowNodes((prev) => prev.filter((n) => !ids.has(n.id)));
      if (selectedNodeId && ids.has(selectedNodeId)) {
        setSelectedNodeId(null);
      }
      setIsSaved(false);
    },
    [selectedNodeId],
  );

  const onEdgesDelete = useCallback(() => {
    setIsSaved(false);
  }, []);

  // ── Keyboard shortcuts ────────────────────────────────────────

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Ctrl+S / Cmd+S → save
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  });

  // ── Drag & drop from palette ────────────────────────────────

  function onDragOver(e: DragEvent) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    const data = e.dataTransfer.getData('application/agentos-role');
    if (!data) return;

    const role = JSON.parse(data) as RoleTemplate;
    const bounds = reactFlowWrapper.current?.getBoundingClientRect();
    if (!bounds) return;

    const position = {
      x: e.clientX - bounds.left - 90,
      y: e.clientY - bounds.top - 30,
    };
    addNode(role, position);
  }

  // ── Toolbar actions ─────────────────────────────────────────

  async function handleSave() {
    const now = new Date().toISOString();
    const wf: WorkflowDefinition = {
      id: workflowId,
      name: workflowName,
      description: workflowDescription,
      domain_pack: packName,
      version: '1.0.0',
      nodes: workflowNodes,
      edges: rfEdges.map((e) => ({ source: e.source, target: e.target })),
      variables: [],
      created_at: now,
      updated_at: now,
      template_source: null,
    };

    try {
      setActionError('');
      if (isNew || !isSaved) {
        if (isNew) {
          await saveWorkflow(wf);
          navigate(`/workflows/${workflowId}/edit?pack=${packName}`, { replace: true });
        } else {
          await updateWorkflow(workflowId, wf);
        }
      }
      setIsSaved(true);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to save workflow');
    }
  }

  async function handleRun() {
    await handleSave();
    try {
      setActionError('');
      const result = await runWorkflow(workflowId);
      navigate(`/sessions/${result.session_id}`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to run workflow');
    }
  }

  async function handleValidate() {
    await handleSave();
    try {
      setActionError('');
      const result = await validateWorkflow(workflowId);
      setValidationResult(result);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Validation failed');
    }
  }

  async function handleDelete() {
    try {
      setActionError('');
      await deleteWorkflow(workflowId);
      navigate('/');
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete workflow');
    }
  }

  // ── Selected node ───────────────────────────────────────────

  const selectedNode = workflowNodes.find((n) => n.id === selectedNodeId);

  if (loadingWorkflow) {
    return <Spinner message="Loading workflow..." />;
  }

  return (
    <div className="flex flex-col h-[calc(100vh-73px)]">
      {actionError && (
        <div className="px-4 py-2">
          <ErrorBanner message={actionError} onDismiss={() => setActionError('')} />
        </div>
      )}
      <Toolbar
        workflowName={workflowName}
        nodeCount={workflowNodes.length}
        edgeCount={rfEdges.length}
        isSaved={isSaved}
        isNew={isNew}
        validationResult={validationResult}
        onNameChange={(name) => {
          setWorkflowName(name);
          setIsSaved(false);
        }}
        onSave={handleSave}
        onRun={handleRun}
        onValidate={handleValidate}
        onDelete={handleDelete}
      />

      <div className="flex flex-1 overflow-hidden">
        {/* Left: Node Palette */}
        <div className="hidden md:block w-56 border-r border-gray-800 p-3 overflow-y-auto bg-gray-950">
          {pack && (
            <NodePalette roles={pack.role_templates} tools={pack.tools} />
          )}
        </div>

        {/* Center: React Flow Canvas */}
        <div className="flex-1" ref={reactFlowWrapper}>
          <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            nodeTypes={NODE_TYPES}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            onNodeDragStop={onNodeDragStop}
            onNodesDelete={onNodesDelete}
            onEdgesDelete={onEdgesDelete}
            onDragOver={onDragOver}
            onDrop={onDrop}
            fitView
            className="bg-gray-950"
            defaultEdgeOptions={{ animated: true, style: { stroke: '#4b5563' } }}
          >
            <Background color="#374151" gap={20} />
            <Controls className="!bg-gray-800 !border-gray-700 [&>button]:!bg-gray-800 [&>button]:!border-gray-700 [&>button]:!text-gray-400" />
            <MiniMap
              nodeColor="#3b82f6"
              maskColor="rgba(0,0,0,0.7)"
              className="!bg-gray-900 !border-gray-700"
            />
          </ReactFlow>
        </div>

        {/* Right: Config Panel */}
        <div className="hidden lg:block w-72 border-l border-gray-800 p-3 overflow-y-auto bg-gray-950">
          {selectedNode ? (
            <ConfigPanel
              node={selectedNode}
              availableTools={pack?.tools ?? []}
              availableModels={models}
              onChange={updateNodeConfig}
              onDisplayNameChange={updateNodeDisplayName}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-gray-600 text-sm">
              <p>Select a node to configure</p>
              <p className="text-xs mt-1">or drag a role from the palette</p>
            </div>
          )}
        </div>
      </div>

      {/* Validation issues toast */}
      {validationResult && !validationResult.valid && (
        <div className="absolute bottom-4 right-4 max-w-sm bg-gray-900 border border-red-500/50
                        rounded-lg p-4 shadow-lg z-50">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-semibold text-red-400">Validation Issues</h4>
            <button
              onClick={() => setValidationResult(null)}
              className="text-gray-500 hover:text-gray-300 text-xs"
            >
              Dismiss
            </button>
          </div>
          <ul className="text-xs space-y-1">
            {validationResult.issues.map((issue, i) => (
              <li
                key={i}
                className={`${
                  issue.severity === 'error' ? 'text-red-400' : 'text-yellow-400'
                }`}
              >
                {issue.severity === 'error' ? 'ERR' : 'WARN'}: {issue.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
