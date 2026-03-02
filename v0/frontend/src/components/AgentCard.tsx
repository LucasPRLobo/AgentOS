/** AgentCard — displays status for a single agent instance. */

import BudgetBar from './BudgetBar';

const STATE_COLORS: Record<string, string> = {
  idle: 'text-gray-400',
  running: 'text-blue-400',
  succeeded: 'text-green-400',
  failed: 'text-red-400',
};

interface Props {
  role: string;
  model: string;
  state: string;
  step: number;
  maxSteps: number;
  tokensUsed: number;
  maxTokens: number;
  toolCalls: number;
  maxToolCalls: number;
  lastTool?: string;
}

export default function AgentCard({
  role,
  model,
  state,
  step,
  maxSteps,
  tokensUsed,
  maxTokens,
  toolCalls,
  maxToolCalls,
  lastTool,
}: Props) {
  const stateColor = STATE_COLORS[state] ?? 'text-gray-400';

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-white">{role}</h3>
          <p className="text-xs text-gray-500">{model}</p>
        </div>
        <span className={`text-sm font-medium ${stateColor}`}>
          {state}
        </span>
      </div>

      <div className="text-xs text-gray-400">
        Step {step} / {maxSteps}
        {lastTool && <span className="ml-2 text-gray-500">last: {lastTool}</span>}
      </div>

      <div className="space-y-2">
        <BudgetBar label="Tokens" used={tokensUsed} max={maxTokens} />
        <BudgetBar label="Tool Calls" used={toolCalls} max={maxToolCalls} />
      </div>
    </div>
  );
}
