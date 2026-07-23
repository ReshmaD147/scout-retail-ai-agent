import { SlidersIcon, SparklesIcon } from "./Icons";

export interface RefineSearchCardProps {
  onRefine: () => void;
}

export function RefineSearchCard({ onRefine }: RefineSearchCardProps): JSX.Element {
  return (
    <section className="refine-card">
      <span className="refine-card__icon"><SparklesIcon /></span>
      <div>
        <h2>Not seeing what you want?</h2>
        <p>Refine your request, expand the budget, or ask Scout for another fulfillment option.</p>
      </div>
      <button type="button" onClick={onRefine}>Refine search <SlidersIcon /></button>
    </section>
  );
}
