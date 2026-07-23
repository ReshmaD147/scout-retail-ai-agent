export interface SuggestionChipsProps {
  suggestions: string[];
  disabled?: boolean;
  onSelect: (query: string) => void;
}

export function SuggestionChips({ suggestions, disabled = false, onSelect }: SuggestionChipsProps): JSX.Element {
  return (
    <div className="suggestion-chips" aria-label="Suggested searches">
      {suggestions.map((suggestion) => (
        <button key={suggestion} type="button" disabled={disabled} onClick={() => onSelect(suggestion)}>
          {suggestion}
        </button>
      ))}
    </div>
  );
}
