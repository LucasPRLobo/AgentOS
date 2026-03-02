/** ErrorBanner — inline dismissible error message. */

interface Props {
  message: string;
  onDismiss?: () => void;
  /** Optional retry callback shown as a button. */
  onRetry?: () => void;
}

export default function ErrorBanner({ message, onDismiss, onRetry }: Props) {
  return (
    <div className="flex items-start gap-3 px-4 py-3 rounded-lg bg-red-900/20 border border-red-800/50">
      <div className="flex-1">
        <p className="text-sm text-red-300">{message}</p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {onRetry && (
          <button
            onClick={onRetry}
            className="text-xs text-red-400 hover:text-red-300 underline"
          >
            Retry
          </button>
        )}
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="text-xs text-gray-500 hover:text-gray-300"
          >
            Dismiss
          </button>
        )}
      </div>
    </div>
  );
}
