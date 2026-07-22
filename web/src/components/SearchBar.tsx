import { useCallback } from "react";
import type { KeyboardEvent } from "react";

export interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  isLoading: boolean;
}

/**
 * The natural-language search input, its Search button, and (while a
 * request is active) its Cancel button.
 *
 * Keyboard behavior: Enter submits, Shift+Enter inserts a new line -
 * a `<textarea>` is used specifically so Shift+Enter has somewhere
 * meaningful to put the new line (a plain `<input>` cannot). Submission
 * itself is rejected for an empty or whitespace-only query, and the
 * Search button is disabled the same way, so keyboard and mouse users
 * hit the identical rule.
 */
export function SearchBar({ value, onChange, onSubmit, onCancel, isLoading }: SearchBarProps): JSX.Element {
  const canSubmit = value.trim().length > 0 && !isLoading;

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        if (canSubmit) {
          onSubmit();
        }
      }
      // Shift+Enter is intentionally left alone - the textarea's own
      // default behavior (insert a newline) is exactly what we want.
    },
    [canSubmit, onSubmit]
  );

  const handleFormSubmit = useCallback(
    (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (canSubmit) {
        onSubmit();
      }
    },
    [canSubmit, onSubmit]
  );

  return (
    <form className="search-bar" onSubmit={handleFormSubmit}>
      <label htmlFor="scout-query" className="search-bar__label">
        What are you looking for?
      </label>
      <textarea
        id="scout-query"
        className="search-bar__input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Find comfortable work shoes under $100 that I can pick up today near Maple Grove."
        rows={2}
        aria-describedby="scout-query-hint"
        disabled={isLoading}
      />
      <p id="scout-query-hint" className="search-bar__hint">
        Press Enter to search, Shift+Enter for a new line.
      </p>
      <div className="search-bar__actions">
        <button type="submit" className="search-bar__submit" disabled={!canSubmit}>
          {isLoading ? "Searching..." : "Search"}
        </button>
        {isLoading && (
          <button type="button" className="search-bar__cancel" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
