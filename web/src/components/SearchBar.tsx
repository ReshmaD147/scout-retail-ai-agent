import { useCallback } from "react";
import type { ChangeEvent, FormEvent, KeyboardEvent } from "react";
import { SendIcon } from "./Icons";

export interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  isLoading: boolean;
}

export function SearchBar({ value, onChange, onSubmit, onCancel, isLoading }: SearchBarProps): JSX.Element {
  const canSubmit = value.trim().length > 0 && !isLoading;

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        if (canSubmit) onSubmit();
      }
    },
    [canSubmit, onSubmit]
  );

  const handleFormSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (canSubmit) onSubmit();
    },
    [canSubmit, onSubmit]
  );

  return (
    <div className="search-area">
      <form className="search-bar" onSubmit={handleFormSubmit}>
        <label htmlFor="scout-query" className="visually-hidden">What are you looking for?</label>
        <textarea
          id="scout-query"
          className="search-bar__input"
          value={value}
          onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Find comfortable work shoes under $100 that I can pick up today near Maple Grove."
          rows={1}
          aria-label="Search"
          aria-describedby="scout-query-hint"
          disabled={isLoading}
        />
        <button
          type="submit"
          className="search-bar__submit"
          disabled={!canSubmit}
          aria-label={isLoading ? "Searching..." : "Search"}
          title={isLoading ? "Searching…" : "Search"}
        >
          <SendIcon />
        </button>
      </form>
      <p id="scout-query-hint" className="visually-hidden">Press Enter to search, Shift+Enter for a new line.</p>
      {isLoading && (
        <button type="button" className="search-bar__cancel" onClick={onCancel}>Cancel</button>
      )}
    </div>
  );
}
