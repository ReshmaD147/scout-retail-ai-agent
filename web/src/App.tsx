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
import { MemoryPanel } from "./components/MemoryPanel";
import { OrderStatusCard } from "./components/OrderStatusCard";
import { OrderSupportPanel } from "./components/OrderSupportPanel";
import { ProductFilters } from "./components/ProductFilters";
import { ProtectedActionCard } from "./components/ProtectedActionCard";
import { ProductGrid } from "./components/ProductGrid";
import { RefineSearchCard } from "./components/RefineSearchCard";
import { ResultsHeader } from "./components/ResultsHeader";
import { SearchBar } from "./components/SearchBar";
import { SavedProductsView } from "./components/SavedProductsView";
import { Sidebar } from "./components/Sidebar";
import { SuggestionChips } from "./components/SuggestionChips";
import { TopActions } from "./components/TopActions";
import { VerifiedFacts } from "./components/VerifiedFacts";
import { SparklesIcon } from "./components/Icons";
import { useCart } from "./hooks/useCart";
import { useMemorySettings } from "./hooks/useMemorySettings";
import { useSavedProducts } from "./hooks/useSavedProducts";
import { useScoutChat } from "./hooks/useScoutChat";
import type { ConversationMessage, RecommendationFilters } from "./types/chat";
import type { ProductSummary } from "./types/chat";

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

const SUPPORT_QUICK_ACTIONS = [
  { label: "Returns & refunds", query: "What is Scout's returns and refunds policy?" },
  { label: "Shipping help", query: "What happens when a package is marked delivered but is missing?" },
  { label: "Check an order", query: "Where is my order?" },
  { label: "Store policies", query: "What is Scout's store pickup policy?" },
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
    messages = [],
    activeRequestId = null,
    errorMessage,
    usedFallback,
    sessionId,
    submit,
    cancel,
    clearConversation,
    retryMessage,
    setFeedback,
  } = useScoutChat();
  const cartState = useCart(sessionId);
  const savedState = useSavedProducts(sessionId);
  const memoryState = useMemorySettings(sessionId, sessionId);
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
  const showingSaved = activeDialog === "saved";

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
    clearConversation();
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

  const clearConversationWithConfirm = (): void => {
    if (window.confirm("Clear this conversation? Your cart and saved products will stay unchanged.")) {
      clearConversation();
    }
  };

  const handleAddToCart = (productId: string): void => {
    void cartState.addItem(productId);
    setIsCartOpen(true);
  };

  const handleToggleSaved = (productId: string): void => {
    void savedState.toggle(productId);
  };

  const focusSearch = (): void => {
    setIsHelpOpen(false);
    setActiveDialog(null);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    window.setTimeout(() => document.getElementById("scout-query")?.focus(), 0);
  };


  const startOrderHelp = (): void => {
    runSearch("Where is my order?");
  };

  const runSupportQuickAction = (text: string): void => {
    runSearch(text);
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
        savedCount={savedState.count}
        recentSearches={sidebarSearches}
        isOpen={isNavOpen}
        onClose={() => setIsNavOpen(false)}
        onNewSearch={startNewSearch}
        onDeals={() => runSearch("Show me products with active deals")}
        onCategories={() => { setIsHelpOpen(false); setActiveDialog("categories"); setIsNavOpen(false); }}
        onSaved={() => { setIsHelpOpen(false); setActiveDialog("saved"); setIsNavOpen(false); void savedState.refresh(); }}
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
            {showingSaved ? (
              <SavedProductsView
                saved={savedState.saved}
                isLoading={savedState.isLoading}
                errorMessage={savedState.errorMessage}
                onRetry={() => void savedState.refresh()}
                onAddToCart={handleAddToCart}
                onToggleSaved={handleToggleSaved}
              />
            ) : (
              <>
                {messages.length > 0 ? (
                  <ConversationHistory
                    messages={messages}
                    activeRequestId={activeRequestId}
                    activeActivities={activities}
                    usedFallback={usedFallback}
                    sessionId={sessionId}
                    explanationExpanded={explanationExpanded}
                    onToggleExplanation={() => setExplanationExpanded((value) => !value)}
                    onAddToCart={handleAddToCart}
                    savedProductIds={savedState.savedIds}
                    onToggleSaved={handleToggleSaved}
                    onRefine={focusSearch}
                    onNeedHelp={() => { setActiveDialog(null); setIsHelpOpen(true); }}
                    onContinueShopping={startNewSearch}
                    onSuggestedAction={runSearch}
                    onStop={cancel}
                    onRetry={retryMessage}
                    onFeedback={setFeedback}
                    onClearConversation={clearConversationWithConfirm}
                  />
                ) : phase === "idle" && (
                <EmptyState
                  title="Describe what you need"
                  message="Scout will search the catalog, verify inventory, and show grounded options."
                  examples={EMPTY_STATE_EXAMPLES}
                  onExampleSelect={runSearch}
                />
                )}

                {messages.length === 0 && phase === "loading" && (
                  <>
                    <AgentActivity activities={activities} showWhenEmpty />
                    <LoadingState />
                  </>
                )}

                {messages.length === 0 && phase === "canceled" && (
                  <div className="app__notice" role="status">
                    <p>Search canceled.</p>
                    <button type="button" onClick={startNewSearch}>Start a new search</button>
                  </div>
                )}

                {messages.length === 0 && phase === "error" && errorMessage && <ErrorState message={errorMessage} onRetry={() => runSearch()} />}

                {messages.length === 0 && phase === "result" && response && (
                  <ResultView
                    activities={activities}
                    response={response}
                    usedFallback={usedFallback}
                    sessionId={sessionId}
                    explanationExpanded={explanationExpanded}
                    onToggleExplanation={() => setExplanationExpanded((value) => !value)}
                    onAddToCart={handleAddToCart}
                    savedProductIds={savedState.savedIds}
                    onToggleSaved={handleToggleSaved}
                    onRefine={focusSearch}
                    onNeedHelp={response.order ? startOrderHelp : () => { setActiveDialog(null); setIsHelpOpen(true); }}
                    onContinueShopping={startNewSearch}
                  />
                )}
              </>
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
              disabled={isLoading}
              canApply={Boolean(lastSubmittedQuery)}
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

      {isHelpOpen && (
        <section className="help-popover" role="dialog" aria-modal="false" aria-labelledby="help-popover-title">
          <button type="button" className="help-popover__close" aria-label="Close help" onClick={() => setIsHelpOpen(false)}>×</button>
          <SparklesIcon />
          <h2 id="help-popover-title">{currentOrder ? "Order help" : "How Scout can help"}</h2>
          <p>{currentOrder ? "Ask about payment, pickup, delivery, tracking, or eligibility for this order." : "Choose a support topic. Scout will send it through the backend Supervisor and verified policy/order flow."}</p>
          <div className="help-popover__actions" aria-label="Support quick actions">
            {SUPPORT_QUICK_ACTIONS.map((action) => (
              <button key={action.label} type="button" onClick={() => runSupportQuickAction(action.query)} disabled={isLoading}>
                {action.label}
              </button>
            ))}
          </div>
          <button type="button" className="help-popover__ask" onClick={focusSearch}>Ask something else</button>
          <MemoryPanel memory={memoryState} />
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
  savedProductIds: Set<string>;
  onToggleSaved: (productId: string) => void;
  onRefine: () => void;
  onNeedHelp: () => void;
  onContinueShopping: () => void;
  showRefineCard?: boolean;
}

interface ConversationHistoryProps {
  messages: ConversationMessage[];
  activeRequestId: string | null;
  activeActivities: ReturnType<typeof useScoutChat>["activities"];
  usedFallback: boolean;
  sessionId: string;
  explanationExpanded: boolean;
  onToggleExplanation: () => void;
  onAddToCart: (productId: string) => void;
  savedProductIds: Set<string>;
  onToggleSaved: (productId: string) => void;
  onRefine: () => void;
  onNeedHelp: () => void;
  onContinueShopping: () => void;
  onSuggestedAction: (query: string) => void;
  onStop: () => void;
  onRetry: (messageId: string) => void;
  onFeedback: (messageId: string, value: "helpful" | "not_helpful") => void;
  onClearConversation: () => void;
}

function ConversationHistory({
  messages,
  activeRequestId,
  activeActivities,
  usedFallback,
  sessionId,
  explanationExpanded,
  onToggleExplanation,
  onAddToCart,
  savedProductIds,
  onToggleSaved,
  onRefine,
  onNeedHelp,
  onContinueShopping,
  onSuggestedAction,
  onStop,
  onRetry,
  onFeedback,
  onClearConversation,
}: ConversationHistoryProps): JSX.Element {
  return (
    <section className="conversation" aria-label="Chat history">
      <div className="conversation__toolbar">
        <span>{messages.length} message{messages.length === 1 ? "" : "s"}</span>
        <button type="button" onClick={onClearConversation}>Clear conversation</button>
      </div>
      <ol className="conversation__list" aria-live="polite">
        {messages.map((message, index) => {
          const previousUser = [...messages.slice(0, index)].reverse().find((entry) => entry.role === "user");
          return (
            <li key={message.message_id} className={`conversation-message conversation-message--${message.role} conversation-message--${message.status}`}>
              <article>
                <header className="conversation-message__header">
                  <strong>{message.role === "user" ? "You" : "Scout"}</strong>
                  <time dateTime={message.created_at}>{formatMessageTime(message.created_at)}</time>
                  {statusLabel(message) && <span className="conversation-message__status">{statusLabel(message)}</span>}
                </header>
                {!(message.role === "assistant" && (message.response || message.status === "failed" || message.status === "streaming")) && (
                  <p className="conversation-message__content">{message.content}</p>
                )}
                {message.role === "assistant" && message.status === "streaming" && (
                  <>
                    <AgentActivity activities={message.request_id === activeRequestId ? activeActivities : message.activities ?? []} showWhenEmpty />
                    <LoadingState />
                    <button type="button" className="conversation-message__control" onClick={onStop}>Stop response</button>
                  </>
                )}
                {message.role === "assistant" && message.status === "canceled" && (
                  <div className="app__notice" role="status">
                    <p>Search canceled.</p>
                    <button type="button" onClick={onContinueShopping}>Start a new search</button>
                  </div>
                )}
                {message.role === "assistant" && message.status === "failed" && !message.response && (
                  <ErrorState message={message.content} onRetry={() => previousUser && onRetry(previousUser.message_id)} />
                )}
                {message.role === "assistant" && message.response && (
                  <>
                    <ResultView
                      activities={message.activities ?? []}
                      response={message.response}
                      usedFallback={usedFallback && message.request_id === activeRequestId}
                      sessionId={sessionId}
                      explanationExpanded={explanationExpanded}
                      onToggleExplanation={onToggleExplanation}
                      onAddToCart={onAddToCart}
                      savedProductIds={savedProductIds}
                      onToggleSaved={onToggleSaved}
                      onRefine={onRefine}
                      onNeedHelp={onNeedHelp}
                      onContinueShopping={onContinueShopping}
                      showRefineCard={false}
                    />
                    <MessageActions
                      message={message}
                      previousUserMessageId={previousUser?.message_id ?? null}
                      onSuggestedAction={onSuggestedAction}
                      onRetry={onRetry}
                      onFeedback={onFeedback}
                    />
                  </>
                )}
                {message.role === "assistant" && message.status === "failed" && message.response && (
                  <button type="button" onClick={() => previousUser && onRetry(previousUser.message_id)}>Retry failed request</button>
                )}
              </article>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function MessageActions({
  message,
  previousUserMessageId,
  onSuggestedAction,
  onRetry,
  onFeedback,
}: {
  message: ConversationMessage;
  previousUserMessageId: string | null;
  onSuggestedAction: (query: string) => void;
  onRetry: (messageId: string) => void;
  onFeedback: (messageId: string, value: "helpful" | "not_helpful") => void;
}): JSX.Element {
  const copyResponse = (): void => {
    void navigator.clipboard?.writeText(message.content);
  };
  const safeSuggestedActions = message.message_type === "clarification" || message.message_type === "safe_failure"
    ? []
    : message.suggested_actions ?? [];
  return (
    <div className="message-actions" aria-label="Scout response actions">
      {(message.response?.quick_replies?.length ?? 0) > 0 && (
        <div className="message-actions__group" aria-label="Quick replies">
          {(message.response?.quick_replies ?? []).map((action) => (
            <button type="button" key={action.action_id} onClick={() => onSuggestedAction(action.query)}>{action.label}</button>
          ))}
        </div>
      )}
      {safeSuggestedActions.length > 0 && (
        <div className="message-actions__group message-actions__group--shopping" aria-label="Shopping follow-up actions">
          {safeSuggestedActions.map((action) => (
            <button type="button" key={action.action_id} onClick={() => onSuggestedAction(action.query)}>{action.label}</button>
          ))}
        </div>
      )}
      <div className="message-actions__group message-actions__group--message" aria-label="Message actions">
        <button type="button" onClick={copyResponse}>Copy response</button>
        {previousUserMessageId && <button type="button" onClick={() => onRetry(previousUserMessageId)}>Retry</button>}
        <button type="button" aria-pressed={message.feedback === "helpful"} onClick={() => onFeedback(message.message_id, "helpful")}>Helpful</button>
        <button type="button" aria-pressed={message.feedback === "not_helpful"} onClick={() => onFeedback(message.message_id, "not_helpful")}>Not helpful</button>
      </div>
    </div>
  );
}

function formatMessageTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function statusLabel(message: ConversationMessage): string | null {
  if (message.status === "streaming") return "Processing";
  if (message.status === "canceled") return "Canceled";
  if (message.status === "failed") return "Failed";
  if (message.message_type === "clarification") return "Waiting for clarification";
  if (message.message_type === "partial_result") return "Partial result";
  if (message.message_type === "safe_failure") return "Stopped safely";
  return null;
}

function ResultView({
  activities,
  response,
  usedFallback,
  sessionId,
  explanationExpanded,
  onToggleExplanation,
  onAddToCart,
  savedProductIds,
  onToggleSaved,
  onRefine,
  onNeedHelp,
  onContinueShopping,
  showRefineCard = true,
}: ResultViewProps): JSX.Element {
  const hasProducts = response.products.length > 0;
  const visibleGroups = (response.product_groups ?? []).filter((group) => group.products.length > 0 || group.missing);
  const hasGroupedProducts = visibleGroups.length > 1;
  const hasPerProductExplanations = response.products.some((product) => Boolean(product.explanation));
  const visibleErrors = response.errors.filter((error) => error.message.trim() !== (response.answer ?? "").trim());

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
          {response.protected_action && (
            <ProtectedActionCard action={response.protected_action} sessionId={sessionId} />
          )}
        </div>
      )}

      {response.status === "failed" && <ErrorState message={response.answer ?? "Scout could not verify a safe answer."} />}

      {response.status === "completed" && (
        <>
          {hasProducts ? (
            <>
              <ResultsHeader count={Math.min(response.products.length, 3)} explanationExpanded={explanationExpanded} onToggleExplanation={onToggleExplanation} />
              <VerifiedFacts response={response} />
              {explanationExpanded && response.answer && !hasPerProductExplanations && (
                <div className="result-view__answer" role="status">
                  <h2>Why Scout selected these</h2>
                  <p>{response.answer}</p>
                </div>
              )}
              {hasGroupedProducts ? (
                <GroupedProductResults
                  groups={visibleGroups}
                  fulfillmentOptions={response.fulfillment_options}
                  onAddToCart={onAddToCart}
                  savedProductIds={savedProductIds}
                  onToggleSaved={onToggleSaved}
                />
              ) : (
                <ProductGrid
                  products={response.products}
                  fulfillmentOptions={response.fulfillment_options}
                  onAddToCart={onAddToCart}
                  savedProductIds={savedProductIds}
                  onToggleSaved={onToggleSaved}
                />
              )}
              {showRefineCard && <RefineSearchCard onRefine={onRefine} />}
            </>
          ) : response.answer && !response.order && response.external_offers.length === 0 ? (
            <div className="result-view__answer"><h2>Scout&apos;s answer</h2><p>{response.answer}</p></div>
          ) : null}

          <ExternalOfferGrid offers={response.external_offers} sessionId={sessionId} workflowId={response.workflow_id} />
          {response.order && <OrderStatusCard order={response.order} onNeedHelp={onNeedHelp} onContinueShopping={onContinueShopping} />}
        </>
      )}

      {visibleErrors.length > 0 && (
        <ul className="result-view__errors">
          {visibleErrors.map((error, index) => <li key={`${error.code}-${index}`}>{error.message}</li>)}
        </ul>
      )}
    </div>
  );
}

interface GroupedProductResultsProps {
  groups: NonNullable<NonNullable<ReturnType<typeof useScoutChat>["response"]>["product_groups"]>;
  fulfillmentOptions: NonNullable<ReturnType<typeof useScoutChat>["response"]>["fulfillment_options"];
  onAddToCart: (productId: string) => void;
  savedProductIds: Set<string>;
  onToggleSaved: (productId: string) => void;
}

function GroupedProductResults({
  groups,
  fulfillmentOptions,
  onAddToCart,
  savedProductIds,
  onToggleSaved,
}: GroupedProductResultsProps): JSX.Element {
  const products = groups.flatMap((group) => group.products);
  const productsById = new Map<string, ProductSummary>(products.map((product) => [product.product_id, product]));

  return (
    <div className="grouped-results" aria-label="Grouped product results">
      {groups.map((group) => (
        <section className="grouped-results__group" key={group.target_label}>
          <div className="grouped-results__heading">
            <h3>{titleCase(group.target_label)}</h3>
            {group.missing ? <span>Not verified</span> : <span>Matched</span>}
          </div>
          {group.products.length > 0 ? (
            <ProductGrid
              products={group.products.map((product) => productsById.get(product.product_id) ?? product)}
              fulfillmentOptions={fulfillmentOptions}
              onAddToCart={onAddToCart}
              savedProductIds={savedProductIds}
              onToggleSaved={onToggleSaved}
            />
          ) : (
            <p className="grouped-results__missing">
              {group.message ?? "Scout could not verify a matching product for this part of your request."}
            </p>
          )}
        </section>
      ))}
    </div>
  );
}

function titleCase(value: string): string {
  return value.replace(/\b\w/g, (character) => character.toUpperCase());
}
