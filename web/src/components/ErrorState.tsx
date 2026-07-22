export interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

/**
 * A safe error panel. `message` must already be a customer-safe
 * sentence by the time it reaches this component - useScoutChat only
 * ever stores the backend's own safe `message` field or a fixed
 * generic sentence here, never a raw exception, stack trace, or
 * network error string (see web/src/hooks/useScoutChat.ts).
 */
export function ErrorState({ message, onRetry }: ErrorStateProps): JSX.Element {
  return (
    <div className="error-state" role="alert">
      <h2 className="error-state__title">Something went wrong</h2>
      <p className="error-state__message">{message}</p>
      {onRetry && (
        <button type="button" className="error-state__retry" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
