import { useMemo, useState } from "react";
import { AgentActivity } from "./components/AgentActivity";
import { CartDrawer } from "./components/CartDrawer";
import { EmptyState } from "./components/EmptyState";
import { ErrorState } from "./components/ErrorState";
import { ExternalOfferGrid } from "./components/ExternalOfferGrid";
import { FulfillmentSummary } from "./components/FulfillmentSummary";
import { Header } from "./components/Header";
import { LoadingState } from "./components/LoadingState";
import { MobileHeader } from "./components/MobileHeader";
import { OrderStatusCard } from "./components/OrderStatusCard";
import { OrderSupportPanel } from "./components/OrderSupportPanel";
import { ProductFilters } from "./components/ProductFilters";
import { ProductGrid } from "./components/ProductGrid";
import { RefineSearchCard } from "./components/RefineSearchCard";
import { ResultsHeader } from "./components/ResultsHeader";
import { SearchBar } from "./components/SearchBar";
import { Sidebar } from "./components/Sidebar";
import { SuggestionChips } from "./components/SuggestionChips";
import { TopActions } from "./components/TopActions";
import { VerifiedFacts } from "./components/VerifiedFacts";
import { SparklesIcon } from "./components/Icons";
import { useCart } from "./hooks/useCart";
import { useScoutChat } from "./hooks/useScoutChat";
import type { RecommendationFilters } from "./types/chat";

const SUGGESTED_QUERIES = [
  "Work shoes under $100",
  "Backpack for travel",
  "Wireless earbuds",
  "Coffee maker deals",
];

const STARTER_QUERIES = [
  "Work shoes under $100",
  "Can I pick this up today near Maple Grove?",
  "Where is my order?",
];

const EMPTY_STATE_EXAMPLES = [
  {
    label: "Shop",
    query: "Work shoes under $100",
    description: "Find catalog products that match a budget.",
  },
  {
    label: "Fulfillment",
    query: "Can I pick this up today near Maple Grove?",
    description: "Check verified pickup and delivery options.",
  },
  {
    label: "Order help",
    query: "Where is my order?",
    description: "Retrieve order status from existing order data.",
  },
];

const DEFAULT_FILTERS: RecommendationFilters = { in_stock_only: true };

export function App(): JSX.Element {
  const {
    query,
    setQuery,
    phase,
    isLoading,
    activities,
    response,
    errorMessage,
    usedFallback,
    sessionId,
    submit,
    cancel,
    reset,
  } = useScoutChat();
  const cartState = useCart(sessionId);
  const [isCartOpen, setIsCartOpen] = useState(false);
  const [isNavOpen, setIsNavOpen] = useState(false);
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [activeDialog, setActiveDialog] = useState<"categories" | "saved" | null>(null);
  const [explanationExpanded, setExplanationExpanded] = useState(false);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const [activeFilters, setActiveFilters] = useState<RecommendationFilters>(DEFAULT_FILTERS);
  const [lastSubmittedQuery, setLastSubmittedQuery] = useState("");

  const cartSubtotal = cartState.cart?.subtotal ?? 0;
  const currentFulfillment = response?.fulfillment_options ?? [];
  const currentOrder = response?.order ?? null;

  const recordSearch = (text: string): void => {
    setRecentSearches((previous) => [text, ...previous.filter((item) => item !== text)].slice(0, 5));
  };

  const runSearch = (override?: string, filtersOverride?: RecommendationFilters): void => {
    const text = (override ?? query).trim();
    if (!text || isLoading) return;
    const isNewQuery = text !== lastSubmittedQuery;
    const filters = filtersOverride ?? (isNewQuery ? DEFAULT_FILTERS : activeFilters);
    if (isNewQuery && filtersOverride === undefined) setActiveFilters(DEFAULT_FILTERS);
    if (filtersOverride !== undefined) setActiveFilters(filtersOverride);
    setLastSubmittedQuery(text);
    setExplanationExpanded(false);
    setIsHelpOpen(false);
    setActiveDialog(null);
    recordSearch(text);
    setIsNavOpen(false);
    submit(text, filters);
  };

  const startNewSearch = (): void => {
    reset();
    setExplanationExpanded(false);
    setIsNavOpen(false);
    setIsHelpOpen(false);
    setActiveDialog(null);
    setActiveFilters(DEFAULT_FILTERS);
    setLastSubmittedQuery("");
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    window.setTimeout(() => document.getElementById("scout-query")?.focus(), 0);
  };

  const handleAddToCart = (productId: string): void => {
    void cartState.addItem(productId);
    setIsCartOpen(true);
  };

  const focusSearch = (): void => {
    setIsHelpOpen(false);
    setActiveDialog(null);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    window.setTimeout(() => document.getElementById("scout-query")?.focus(), 0);
  };


  const startOrderHelp = (): void => {
    setIsHelpOpen(false);
    setActiveDialog(null);
    setQuery("I need help with my order");
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    window.setTimeout(() => document.getElementById("scout-query")?.focus(), 0);
  };

  const sidebarSearches = useMemo(
    () => recentSearches.length > 0 ? recentSearches : STARTER_QUERIES,
    [recentSearches]
  );

  return (
    <div className={`app-shell${currentOrder ? " app-shell--order" : ""}`}>
      <div className={`app-shell__overlay${isNavOpen ? " app-shell__overlay--visible" : ""}`} onClick={() => setIsNavOpen(false)} aria-hidden="true" />
      <Sidebar
        itemCount={cartState.itemCount}
        recentSearches={sidebarSearches}
        isOpen={isNavOpen}
        onClose={() => setIsNavOpen(false)}
        onNewSearch={startNewSearch}
        onDeals={() => runSearch("Show me products with active deals")}
        onCategories={() => { setIsHelpOpen(false); setActiveDialog("categories"); setIsNavOpen(false); }}
        onSaved={() => { setIsHelpOpen(false); setActiveDialog("saved"); setIsNavOpen(false); }}
        onCartClick={() => setIsCartOpen(true)}
        onRecentSearch={runSearch}
      />

      <div className="app-shell__center">
        <MobileHeader
          itemCount={cartState.itemCount}
          onMenuClick={() => setIsNavOpen(true)}
          onCartClick={() => setIsCartOpen(true)}
        />

        <main className="main-content">
          <Header />
          <SearchBar
            value={query}
            onChange={setQuery}
            onSubmit={() => runSearch()}
            onCancel={cancel}
            isLoading={isLoading}
          />
          <SuggestionChips suggestions={SUGGESTED_QUERIES} disabled={isLoading} onSelect={runSearch} />

          <section className="main-content__results" aria-live="polite">
            {phase === "idle" && (
              <EmptyState
                title="Describe what you need"
                message="Scout will search the catalog, verify inventory, and show grounded options."
                examples={EMPTY_STATE_EXAMPLES}
                onExampleSelect={runSearch}
              />
            )}

            {phase === "loading" && (
              <>
                <AgentActivity activities={activities} showWhenEmpty />
                <LoadingState />
              </>
            )}

            {phase === "canceled" && (
              <div className="app__notice" role="status">
                <p>Search canceled.</p>
                <button type="button" onClick={startNewSearch}>Start a new search</button>
              </div>
            )}

            {phase === "error" && errorMessage && <ErrorState message={errorMessage} onRetry={() => runSearch()} />}

            {phase === "result" && response && (
              <ResultView
                activities={activities}
                response={response}
                usedFallback={usedFallback}
                sessionId={sessionId}
                explanationExpanded={explanationExpanded}
                onToggleExplanation={() => setExplanationExpanded((value) => !value)}
                onAddToCart={handleAddToCart}
                onRefine={focusSearch}
                onNeedHelp={response.order ? startOrderHelp : () => { setActiveDialog(null); setIsHelpOpen(true); }}
                onContinueShopping={startNewSearch}
              />
            )}
          </section>
        </main>
      </div>

      <aside className="right-panel" aria-label="Shopping context">
        <TopActions
          itemCount={cartState.itemCount}
          subtotal={cartSubtotal}
          showHelp={!currentOrder}
          onCartClick={() => setIsCartOpen(true)}
          onNeedHelp={() => { setActiveDialog(null); setIsHelpOpen(true); }}
          onSaved={() => { setIsHelpOpen(false); setActiveDialog("saved"); }}
        />
        {currentOrder ? (
          <OrderSupportPanel order={currentOrder} onNeedHelp={startOrderHelp} onContinueShopping={startNewSearch} />
        ) : (
          <>
            <FulfillmentSummary
              options={currentFulfillment}
              stores={cartState.stores}
              requestedLocation={response?.requested_location ?? null}
            />
            <ProductFilters
              value={activeFilters}
              disabled={isLoading || !lastSubmittedQuery}
              onApply={(filters) => runSearch(lastSubmittedQuery || query, filters)}
            />
          </>
        )}
        {!currentOrder && (
          <button type="button" className="floating-scout" aria-label="Ask Scout" onClick={focusSearch}>
            <SparklesIcon />
          </button>
        )}
      </aside>

      {activeDialog === "categories" && (
        <section className="navigation-dialog" role="dialog" aria-modal="true" aria-labelledby="category-dialog-title">
          <button type="button" className="navigation-dialog__close" aria-label="Close categories" onClick={() => setActiveDialog(null)}>×</button>
          <h2 id="category-dialog-title">Browse categories</h2>
          <p>Choose a real Scout catalog category. Scout will run a normal verified search.</p>
          <div className="navigation-dialog__choices">
            <button type="button" onClick={() => runSearch("Show me footwear")}>Footwear</button>
            <button type="button" onClick={() => runSearch("Show me bags")}>Bags</button>
            <button type="button" onClick={() => runSearch("Show me electronics")}>Electronics</button>
            <button type="button" onClick={() => runSearch("Show me home and kitchen products")}>Home &amp; Kitchen</button>
          </div>
        </section>
      )}

      {activeDialog === "saved" && (
        <section className="navigation-dialog" role="dialog" aria-modal="true" aria-labelledby="saved-dialog-title">
          <button type="button" className="navigation-dialog__close" aria-label="Close saved products" onClick={() => setActiveDialog(null)}>×</button>
          <h2 id="saved-dialog-title">Saved products</h2>
          <p>Saved products are not part of the current backend yet. Nothing is being hidden or invented.</p>
          <button type="button" className="navigation-dialog__primary" onClick={() => { setActiveDialog(null); focusSearch(); }}>Continue shopping</button>
        </section>
      )}

      {isHelpOpen && (
        <section className="help-popover" role="dialog" aria-modal="false" aria-labelledby="help-popover-title">
          <button type="button" className="help-popover__close" aria-label="Close help" onClick={() => setIsHelpOpen(false)}>×</button>
          <SparklesIcon />
          <h2 id="help-popover-title">{currentOrder ? "Order help" : "How Scout can help"}</h2>
          <p>{currentOrder ? "Ask about payment, pickup, delivery, tracking, or eligibility for this order." : "Ask for products, store availability, delivery options, cart help, checkout, or an existing order status."}</p>
          <button type="button" onClick={focusSearch}>Ask Scout</button>
        </section>
      )}
      <div
        className={`cart-drawer__backdrop${isCartOpen ? " cart-drawer__backdrop--visible" : ""}`}
        onClick={() => setIsCartOpen(false)}
        aria-hidden="true"
      />
      <CartDrawer
        isOpen={isCartOpen}
        onClose={() => setIsCartOpen(false)}
        cart={cartState.cart}
        isLoading={cartState.isLoading}
        errorMessage={cartState.errorMessage}
        stores={cartState.stores}
        storesErrorMessage={cartState.storesErrorMessage}
        onUpdateQuantity={(cartItemId, quantity) => void cartState.updateQuantity(cartItemId, quantity)}
        onRemoveItem={(cartItemId) => void cartState.removeItem(cartItemId)}
        onClear={() => void cartState.clear()}
        onChoosePickup={(storeId) => void cartState.choosePickup(storeId)}
        onChooseDelivery={() => void cartState.chooseDelivery()}
        onDismissError={cartState.dismissError}
        onRefreshStores={() => void cartState.refreshStores()}
        sessionId={sessionId}
        onOrderCompleted={() => void cartState.refresh()}
      />
    </div>
  );
}

interface ResultViewProps {
  activities: ReturnType<typeof useScoutChat>["activities"];
  response: NonNullable<ReturnType<typeof useScoutChat>["response"]>;
  usedFallback: boolean;
  sessionId: string;
  explanationExpanded: boolean;
  onToggleExplanation: () => void;
  onAddToCart: (productId: string) => void;
  onRefine: () => void;
  onNeedHelp: () => void;
  onContinueShopping: () => void;
}

function ResultView({
  activities,
  response,
  usedFallback,
  sessionId,
  explanationExpanded,
  onToggleExplanation,
  onAddToCart,
  onRefine,
  onNeedHelp,
  onContinueShopping,
}: ResultViewProps): JSX.Element {
  const hasProducts = response.products.length > 0;

  return (
    <div className="result-view">
      {!response.order && <AgentActivity activities={activities} isComplete />}

      {usedFallback && <p className="result-view__fallback-note">Live updates weren&apos;t available for this search, so Scout ran it directly.</p>}

      {response.status === "no_results" && <EmptyState title="No matching products found" message={response.answer ?? undefined} />}

      {response.status === "clarification_required" && (
        <div className="result-view__clarification" role="status">
          <h2>Scout needs a bit more information</h2>
          <p>{response.answer}</p>
        </div>
      )}

      {response.status === "confirmation_required" && (
        <div className="result-view__confirmation" role="status">
          <h2>Confirmation needed</h2>
          <p>{response.answer}</p>
        </div>
      )}

      {response.status === "failed" && <ErrorState message={response.answer ?? "Scout could not verify a safe answer."} />}

      {response.status === "completed" && (
        <>
          {hasProducts ? (
            <>
              <ResultsHeader count={Math.min(response.products.length, 3)} explanationExpanded={explanationExpanded} onToggleExplanation={onToggleExplanation} />
              <VerifiedFacts response={response} />
              {explanationExpanded && response.answer && (
                <div className="result-view__answer" role="status">
                  <h2>Why Scout selected these</h2>
                  <p>{response.answer}</p>
                </div>
              )}
              <ProductGrid products={response.products} fulfillmentOptions={response.fulfillment_options} onAddToCart={onAddToCart} />
              <RefineSearchCard onRefine={onRefine} />
            </>
          ) : response.answer && !response.order && response.external_offers.length === 0 ? (
            <div className="result-view__answer"><h2>Scout&apos;s answer</h2><p>{response.answer}</p></div>
          ) : null}

          <ExternalOfferGrid offers={response.external_offers} sessionId={sessionId} workflowId={response.workflow_id} />
          {response.order && <OrderStatusCard order={response.order} onNeedHelp={onNeedHelp} onContinueShopping={onContinueShopping} />}
        </>
      )}

      {response.errors.length > 0 && (
        <ul className="result-view__errors">
          {response.errors.map((error, index) => <li key={`${error.code}-${index}`}>{error.message}</li>)}
        </ul>
      )}
    </div>
  );
}
