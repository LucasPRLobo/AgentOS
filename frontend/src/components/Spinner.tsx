/** Spinner — reusable loading indicator. */

interface Props {
  /** Optional message below the spinner. */
  message?: string;
  /** Size variant. */
  size?: 'sm' | 'md' | 'lg';
}

const SIZES = {
  sm: 'h-4 w-4 border-2',
  md: 'h-6 w-6 border-2',
  lg: 'h-10 w-10 border-3',
};

export default function Spinner({ message, size = 'md' }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-8">
      <div
        className={`${SIZES[size]} rounded-full border-gray-700 border-t-blue-500 animate-spin`}
      />
      {message && <p className="text-sm text-gray-500">{message}</p>}
    </div>
  );
}
