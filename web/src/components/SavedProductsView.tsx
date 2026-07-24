import type { SavedProductsView as SavedProductsState } from "../types/saved";
import { ProductCard } from "./ProductCard";

export interface SavedProductsViewProps {
  saved: SavedProductsState | null;
  isLoading: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  onAddToCart: (productId: string) => void;
  onToggleSaved: (productId: string) => void;
}

export function SavedProductsView({
  saved,
  isLoading,
  errorMessage,
  onRetry,
  onAddToCart,
  onToggleSaved,
}: SavedProductsViewProps): JSX.Element {
  return (
    <section className="saved-products-view" aria-labelledby="saved-products-title">
      <div className="saved-products-view__header">
        <div>
          <p className="saved-products-view__eyebrow">Saved</p>
          <h2 id="saved-products-title">Saved products</h2>
        </div>
        <button type="button" onClick={onRetry}>Refresh</button>
      </div>

      {isLoading && <p role="status">Loading your saved products…</p>}
      {errorMessage && (
        <div className="saved-products-view__error" role="alert">
          <p>{errorMessage}</p>
          <button type="button" onClick={onRetry}>Retry</button>
        </div>
      )}
      {!isLoading && !errorMessage && (!saved || saved.products.length === 0) && (
        <p className="saved-products-view__empty">You have not saved any products yet.</p>
      )}
      {saved && saved.products.length > 0 && (
        <div className="product-grid" role="list" aria-label="Saved product results">
          {saved.products.map((item) => (
            <div role="listitem" key={item.saved_id}>
              <ProductCard
                product={item.product}
                fulfillmentOptions={[]}
                onAddToCart={item.can_add_to_cart ? onAddToCart : undefined}
                isSaved
                onToggleSaved={onToggleSaved}
              />
              <p className={`saved-products-view__availability${item.can_add_to_cart ? "" : " saved-products-view__availability--unavailable"}`}>
                {item.availability_label}
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
