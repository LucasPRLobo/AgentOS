/** TeamBuilder — configure agent team for a session. */

import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { createSession, getPack, startSession } from '../api/client';
import type { AgentSlotConfig, DomainPackDetail } from '../api/types';
import RoleConfigurator from '../components/RoleConfigurator';

export default function TeamBuilder() {
  const [searchParams] = useSearchParams();
  const packName = searchParams.get('pack') ?? 'labos';
  const navigate = useNavigate();

  const [pack, setPack] = useState<DomainPackDetail | null>(null);
  const [selectedWorkflow, setSelectedWorkflow] = useState('');
  const [slots, setSlots] = useState<AgentSlotConfig[]>([]);
  const [taskDescription, setTaskDescription] = useState('');
  const [workspaceRoot, setWorkspaceRoot] = useState('/tmp/agentos-session');
  const [launching, setLaunching] = useState(false);

  useEffect(() => {
    getPack(packName).then((p) => {
      setPack(p);
      if (p.workflows.length > 0) {
        const wf = p.workflows[0];
        setSelectedWorkflow(wf.name);
        // Pre-fill slots from workflow's default roles
        const roleMap = Object.fromEntries(p.role_templates.map((r) => [r.name, r]));
        const initialSlots = wf.default_roles
          .filter((name) => name in roleMap)
          .map((name) => ({
            role: name,
            model: roleMap[name].suggested_model,
            count: roleMap[name].max_instances,
          }));
        setSlots(initialSlots);
      }
    });
  }, [packName]);

  if (!pack) return <div className="text-gray-400">Loading...</div>;

  const roleMap = Object.fromEntries(pack.role_templates.map((r) => [r.name, r]));
  const toolSideEffects = Object.fromEntries(
    pack.tools.map((t) => [t.name, t.side_effect]),
  );

  const addRole = (roleName: string) => {
    const role = roleMap[roleName];
    if (!role) return;
    setSlots([...slots, { role: roleName, model: role.suggested_model, count: 1 }]);
  };

  const updateSlot = (index: number, slot: AgentSlotConfig) => {
    const next = [...slots];
    next[index] = slot;
    setSlots(next);
  };

  const removeSlot = (index: number) => {
    setSlots(slots.filter((_, i) => i !== index));
  };

  const handleLaunch = async () => {
    setLaunching(true);
    try {
      const session = await createSession({
        domain_pack: packName,
        workflow: selectedWorkflow,
        agents: slots,
        workspace_root: workspaceRoot,
        task_description: taskDescription,
      });
      await startSession(session.session_id);
      navigate(`/sessions/${session.session_id}`);
    } catch (err) {
      alert(`Failed to launch: ${err}`);
      setLaunching(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto">
      <h2 className="text-2xl font-bold text-white mb-6">
        Configure Team — {pack.display_name}
      </h2>

      <div className="grid grid-cols-12 gap-6">
        {/* Left: Available Roles */}
        <div className="col-span-3">
          <h3 className="text-sm font-semibold text-gray-400 uppercase mb-3">
            Available Roles
          </h3>
          <div className="space-y-2">
            {pack.role_templates.map((role) => (
              <button
                key={role.name}
                onClick={() => addRole(role.name)}
                className="w-full text-left bg-gray-900 border border-gray-800 rounded-lg p-3 hover:border-blue-600 transition-colors"
              >
                <div className="text-sm font-medium text-white">
                  {role.display_name}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {role.description}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Center: Team Configuration */}
        <div className="col-span-6 space-y-4">
          <h3 className="text-sm font-semibold text-gray-400 uppercase mb-3">
            Agent Team ({slots.length} roles)
          </h3>
          {slots.length === 0 ? (
            <div className="text-center text-gray-600 py-8">
              Add roles from the left panel
            </div>
          ) : (
            slots.map((slot, i) => {
              const role = roleMap[slot.role];
              return role ? (
                <RoleConfigurator
                  key={`${slot.role}-${i}`}
                  role={role}
                  slot={slot}
                  toolSideEffects={toolSideEffects}
                  onUpdate={(s) => updateSlot(i, s)}
                  onRemove={() => removeSlot(i)}
                />
              ) : null;
            })
          )}
        </div>

        {/* Right: Workflow + Launch */}
        <div className="col-span-3 space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-gray-400 uppercase mb-3">
              Workflow
            </h3>
            <select
              value={selectedWorkflow}
              onChange={(e) => setSelectedWorkflow(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200"
            >
              {pack.workflows.map((wf) => (
                <option key={wf.name} value={wf.name}>
                  {wf.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Workspace Directory
            </label>
            <input
              type="text"
              value={workspaceRoot}
              onChange={(e) => setWorkspaceRoot(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Task Description
            </label>
            <textarea
              value={taskDescription}
              onChange={(e) => setTaskDescription(e.target.value)}
              rows={4}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500 resize-none"
              placeholder="Describe what the agent team should accomplish..."
            />
          </div>

          <button
            onClick={handleLaunch}
            disabled={launching || slots.length === 0}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-semibold py-3 rounded-lg transition-colors"
          >
            {launching ? 'Launching...' : 'Launch Session'}
          </button>
        </div>
      </div>
    </div>
  );
}
