export interface EmptyStateProps {
  title: string;
  message?: string;
  examples?: EmptyStateExample[];
  onExampleSelect?: (example: string) => void;
}

export interface EmptyStateExample {
  label: string;
  query: string;
  description: string;
}

export function EmptyState({ title, message, examples, onExampleSelect }: EmptyStateProps): JSX.Element {
  return (
    <div className="empty-state">
      <h2 className="empty-state__title">{title}</h2>
      {message && <p className="empty-state__message">{message}</p>}
      {examples && examples.length > 0 && (
        <ul className="empty-state__examples">
          {examples.map((example) => (
            <li key={example.label}>
              <button
                type="button"
                className="empty-state__example-button"
                onClick={() => onExampleSelect?.(example.query)}
              >
                <span>{example.label}</span>
                <strong>{example.query}</strong>
                <small>{example.description}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
