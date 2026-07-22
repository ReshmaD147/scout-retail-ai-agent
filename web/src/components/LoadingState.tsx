/**
 * A small, accessible loading indicator. `role="status"` plus
 * `aria-live="polite"` means assistive technology announces this once
 * without repeating it on every re-render, and the visible spinner
 * gives sighted users the same information.
 */
export function LoadingState(): JSX.Element {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <span className="loading-state__spinner" aria-hidden="true" />
      <span>Scout is working on your request...</span>
    </div>
  );
}
