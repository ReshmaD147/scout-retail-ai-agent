export function LoadingState(): JSX.Element {
  return (
    <section className="loading-state" role="status" aria-live="polite" aria-label="Scout is working on your request">
      <span className="visually-hidden">Scout is working on your request...</span>
      <div className="loading-state__heading skeleton" />
      <div className="loading-state__grid" aria-hidden="true">
        {[0, 1, 2].map((item) => (
          <div className="loading-card" key={item}>
            <div className="loading-card__image skeleton" />
            <div className="loading-card__line loading-card__line--title skeleton" />
            <div className="loading-card__line skeleton" />
            <div className="loading-card__line loading-card__line--short skeleton" />
            <div className="loading-card__button skeleton" />
          </div>
        ))}
      </div>
    </section>
  );
}
