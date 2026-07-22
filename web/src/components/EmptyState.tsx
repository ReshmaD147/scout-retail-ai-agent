export interface EmptyStateProps {
  title: string;
  message?: string;
  examples?: string[];
  onExampleSelect?: (example: string) => void;
}

/**
 * A reusable "nothing to show yet" panel - used both for the initial,
 * pre-search welcome screen (with example queries to try) and for a
 * verified no-results outcome (a message only, no examples). Which
 * one is showing is entirely App.tsx's decision based on
 * `useScoutChat`'s phase/response - this component only renders the
 * props it is given.
 */
export function EmptyState({ title, message, examples, onExampleSelect }: EmptyStateProps): JSX.Element {
  return (
    <div className="empty-state">
      <h2 className="empty-state__title">{title}</h2>
      {message && <p className="empty-state__message">{message}</p>}
      {examples && examples.length > 0 && (
        <ul className="empty-state__examples">
          {examples.map((example) => (
            <li key={example}>
              <button
                type="button"
                className="empty-state__example-button"
                onClick={() => onExampleSelect?.(example)}
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
