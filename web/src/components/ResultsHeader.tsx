import { InfoIcon } from "./Icons";

export interface ResultsHeaderProps {
  count: number;
  explanationExpanded: boolean;
  onToggleExplanation: () => void;
}

export function ResultsHeader({ count, explanationExpanded, onToggleExplanation }: ResultsHeaderProps): JSX.Element {
  return (
    <div className="results-header">
      <div className="results-header__title-row">
        <h2>Top picks for you</h2>
        <span>{count} result{count === 1 ? "" : "s"}</span>
      </div>
      <button type="button" aria-expanded={explanationExpanded} onClick={onToggleExplanation}>
        <InfoIcon /> Why these?
      </button>
    </div>
  );
}
