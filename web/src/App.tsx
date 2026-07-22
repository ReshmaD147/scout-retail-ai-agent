import { useState } from "react";
import { AgentActivity } from "./components/AgentActivity";
import { CartButton } from "./components/CartButton";
import { CartDrawer } from "./components/CartDrawer";
import { EmptyState } from "./components/EmptyState";
import { ErrorState } from "./components/ErrorState";
import { ExternalOfferGrid } from "./components/ExternalOfferGrid";
import { Header } from "./components/Header";
import { LoadingState } from "./components/LoadingState";
import { ProductGrid } from "./components/ProductGrid";
import { SearchBar } from "./components/SearchBar";
import { useCart } from "./hooks/useCart";
import { useScoutChat } from "./hooks/useScoutChat";

const EXAMPLE_QUERIES = [
  "Find comfortable work shoes under $100 that I can pick up today near Maple Grove.",
];

/**
 * Scout's main shopping interface (Step 14). Wires `useScoutChat` (all
 * networking and workflow-state handling) to the presentational
 * components - this file decides *which* state to show, never *what a
 * result means*: that classification already happened on the backend
 * (`ChatResponse.status`, scout/api/schemas/chat.py) and in the hook.
 */
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

  // Sharing one sessionId with useScoutChat (Step 15) is what lets the
  // cart's "add the first product" command resolve against the exact
  // ranked list this session's last /chat response returned.
  const cartState = useCart(sessionId);
  const [isCartOpen, setIsCartOpen] = useState(false);

  const handleExampleSelect = (example: string): void => {
    setQuery(example);
    submit(example);
  };

  const handleAddToCart = (productId: string): void => {
    void cartState.addItem(productId);
    setIsCartOpen(true);
  };

  return (
    <div className="app">
      <div className="app__header-row">
        <Header />
        <CartButton itemCount={cartState.itemCount} onClick={() => setIsCartOpen(true)} />
      </div>

      <main className="app__main">
        <SearchBar
          value={query}
          onChange={setQuery}
          onSubmit={() => submit()}
          onCancel={cancel}
          isLoading={isLoading}
        />

        <section className="app__results" aria-live="polite">
          {phase === "idle" && (
            <EmptyState
              title="Try an example"
              examples={EXAMPLE_QUERIES}
              onExampleSelect={handleExampleSelect}
            />
          )}

          {phase === "loading" && (
            <>
              <LoadingState />
              <AgentActivity activities={activities} />
            </>
          )}

          {phase === "canceled" && (
            <div className="app__notice" role="status">
              <p>Search canceled.</p>
              <button type="button" onClick={reset}>
                Start a new search
              </button>
            </div>
          )}

          {phase === "error" && errorMessage && <ErrorState message={errorMessage} onRetry={() => submit()} />}

          {phase === "result" && response && (
            <ResultView
              activities={activities}
              response={response}
              usedFallback={usedFallback}
              sessionId={sessionId}
              onAddToCart={handleAddToCart}
            />
          )}
        </section>
      </main>

      <CartDrawer
        isOpen={isCartOpen}
        onClose={() => setIsCartOpen(false)}
        cart={cartState.cart}
        isLoading={cartState.isLoading}
        errorMessage={cartState.errorMessage}
        stores={cartState.stores}
        onUpdateQuantity={(cartItemId, quantity) => void cartState.updateQuantity(cartItemId, quantity)}
        onRemoveItem={(cartItemId) => void cartState.removeItem(cartItemId)}
        onClear={() => void cartState.clear()}
        onChoosePickup={(storeId) => void cartState.choosePickup(storeId)}
        onChooseDelivery={() => void cartState.chooseDelivery()}
        onDismissError={cartState.dismissError}
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
  onAddToCart: (productId: string) => void;
}

/** Renders whichever of the five verified `ChatResponse.status`
 * outcomes the backend actually returned - each one is a normal,
 * successfully-handled business result, not an error. */
function ResultView({ activities, response, usedFallback, sessionId, onAddToCart }: ResultViewProps): JSX.Element {
  return (
    <div className="result-view">
      <AgentActivity activities={activities} />

      {usedFallback && (
        <p className="result-view__fallback-note">
          Live updates weren&apos;t available for this search, so Scout ran it directly.
        </p>
      )}

      {response.status === "no_results" && (
        <EmptyState title="No matching products found" message={response.answer ?? undefined} />
      )}

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
          <div className="result-view__answer">
            <h2>Scout&apos;s answer</h2>
            <p>{response.answer}</p>
          </div>
          {response.products.length > 0 && (
            <ProductGrid
              products={response.products}
              fulfillmentOptions={response.fulfillment_options}
              onAddToCart={onAddToCart}
            />
          )}
          <ExternalOfferGrid
            offers={response.external_offers}
            sessionId={sessionId}
            workflowId={response.workflow_id}
          />
        </>
      )}

      {response.errors.length > 0 && (
        <ul className="result-view__errors">
          {response.errors.map((error, index) => (
            <li key={`${error.code}-${index}`}>{error.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
