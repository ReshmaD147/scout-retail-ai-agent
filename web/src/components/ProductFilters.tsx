import { useEffect, useMemo, useState } from "react";
import type { ChangeEvent } from "react";
import { useCatalogFilters } from "../hooks/useCatalogFilters";
import type { RecommendationFilters } from "../types/chat";

export interface ProductFiltersProps {
  value: RecommendationFilters;
  disabled?: boolean;
  onApply: (filters: RecommendationFilters) => void;
}

const EMPTY_FILTERS: RecommendationFilters = { in_stock_only: true };

export function ProductFilters({ value, disabled = false, onApply }: ProductFiltersProps): JSX.Element {
  const { options, isLoading, errorMessage, retry } = useCatalogFilters();
  const [draft, setDraft] = useState<RecommendationFilters>({ ...EMPTY_FILTERS, ...value });

  useEffect(() => {
    setDraft({ ...EMPTY_FILTERS, ...value });
  }, [value]);

  const productTypes = draft.category && options ? options.product_types[draft.category] ?? [] : [];
  const attributeOptions = useMemo(() => {
    if (!options) return [];
    return options.attributes
      .filter((option) => !draft.category || option.categories.includes(draft.category))
      .filter((option) => !draft.product_type || option.product_types.includes(draft.product_type))
      .slice(0, 10);
  }, [options, draft.category, draft.product_type]);

  const resolvedMax = options?.max_price ?? 500;
  const selectedMax = Math.min(draft.max_price ?? resolvedMax, resolvedMax);
  const selectedAttributes = new Set(draft.attributes ?? []);
  const hasChanges = JSON.stringify({ ...EMPTY_FILTERS, ...value }) !== JSON.stringify(draft);

  const updateCategory = (category: string): void => {
    setDraft((current) => ({
      ...current,
      category: category || undefined,
      product_type: undefined,
      attributes: [],
    }));
  };

  const toggleAttribute = (token: string): void => {
    setDraft((current) => {
      const existing = current.attributes ?? [];
      const attributes = existing.includes(token)
        ? existing.filter((item) => item !== token)
        : [...existing, token];
      return { ...current, attributes };
    });
  };

  const clear = (): void => {
    setDraft(EMPTY_FILTERS);
    onApply(EMPTY_FILTERS);
  };

  return (
    <section className="filters-card" aria-labelledby="filters-title">
      <div className="filters-card__header">
        <h2 id="filters-title">Filters</h2>
        <button type="button" onClick={clear} disabled={disabled}>Clear all</button>
      </div>
      <p className="filters-card__note">Filters re-run Scout&apos;s verified backend search; they do not hide cards only in the browser.</p>

      {isLoading && <p className="filters-card__status">Loading catalog filters…</p>}
      {errorMessage && (
        <div className="filters-card__status filters-card__status--error" role="alert">
          <p>{errorMessage}</p>
          <button type="button" onClick={retry} disabled={isLoading}>Retry</button>
        </div>
      )}

      <label>
        <span>Max price <strong>${selectedMax.toFixed(0)}</strong></span>
        <input
          type="range"
          min="0"
          max={resolvedMax}
          step="5"
          value={selectedMax}
          disabled={disabled || !options}
          onChange={(event: ChangeEvent<HTMLInputElement>) => setDraft((current) => ({ ...current, max_price: Number(event.target.value) }))}
          aria-label="Maximum product price"
        />
      </label>

      <label>
        <span>Category</span>
        <select
          value={draft.category ?? ""}
          disabled={disabled || !options}
          onChange={(event: ChangeEvent<HTMLSelectElement>) => updateCategory(event.target.value)}
        >
          <option value="">Any category</option>
          {options?.categories.map((category) => <option key={category} value={category}>{category}</option>)}
        </select>
      </label>

      <label>
        <span>Product type</span>
        <select
          value={draft.product_type ?? ""}
          disabled={disabled || !draft.category}
          onChange={(event: ChangeEvent<HTMLSelectElement>) => setDraft((current) => ({ ...current, product_type: event.target.value || undefined, attributes: [] }))}
        >
          <option value="">Any product type</option>
          {productTypes.map((productType) => <option key={productType} value={productType}>{productType}</option>)}
        </select>
      </label>

      <label>
        <span>Fulfillment</span>
        <select
          value={draft.fulfillment ?? ""}
          disabled={disabled}
          onChange={(event: ChangeEvent<HTMLSelectElement>) => setDraft((current) => ({
            ...current,
            fulfillment: (event.target.value || undefined) as RecommendationFilters["fulfillment"],
          }))}
        >
          <option value="">Pickup or delivery</option>
          <option value="pickup">Pickup</option>
          <option value="delivery">Delivery</option>
        </select>
      </label>

      <div className="filters-card__availability">
        <input id="verified-stock-filter" type="checkbox" checked readOnly />
        <label htmlFor="verified-stock-filter">Verified in-stock results only</label>
      </div>

      <fieldset className="filters-card__features" disabled={disabled || attributeOptions.length === 0}>
        <legend>Verified product features</legend>
        {attributeOptions.length === 0 ? (
          <p>Choose a category or product type to see catalog-backed features.</p>
        ) : (
          attributeOptions.map((option) => (
            <label key={option.token}>
              <input
                type="checkbox"
                checked={selectedAttributes.has(option.token)}
                onChange={() => toggleAttribute(option.token)}
              />
              <span>{option.label}</span>
            </label>
          ))
        )}
      </fieldset>

      <button
        type="button"
        className="filters-card__apply"
        disabled={disabled || !options || !hasChanges}
        onClick={() => onApply({ ...draft, in_stock_only: true })}
      >
        Apply filters
      </button>
    </section>
  );
}
