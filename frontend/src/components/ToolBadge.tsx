/** ToolBadge — displays a tool name with color-coded side-effect. */

const SIDE_EFFECT_COLORS: Record<string, string> = {
  PURE: 'bg-green-900 text-green-300 border-green-700',
  READ: 'bg-blue-900 text-blue-300 border-blue-700',
  WRITE: 'bg-yellow-900 text-yellow-300 border-yellow-700',
  DESTRUCTIVE: 'bg-red-900 text-red-300 border-red-700',
};

interface Props {
  name: string;
  sideEffect: string;
}

export default function ToolBadge({ name, sideEffect }: Props) {
  const colors = SIDE_EFFECT_COLORS[sideEffect] ?? 'bg-gray-800 text-gray-300 border-gray-600';
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono border ${colors}`}>
      {name}
    </span>
  );
}
