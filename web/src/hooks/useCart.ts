/**
 * `useCart` - the one place cart networking lives (Step 15), the same
 * role web/src/hooks/useScoutChat.ts plays for chat. Every cart
 * component (CartButton, CartDrawer) only ever reads what this hook
 * returns and calls its actions; none of them import cartClient
 * directly, and none of them compute a quantity, a line total, or a
 * subtotal - every `CartView` this hook stores came straight from the
 * backend, already fully revalidated.
 */
import { useCallback, useEffect, useState } from "react";
import {
  addCartItem,
  CartRequestError,
  clearCart,
  getCart,
  listStores,
  removeCartItem,
  setFulfillment,
  updateCartItemQuantity,
} from "../api/cartClient";
import type { CartView, StoreSummary } from "../types/cart";

const GENERIC_CART_ERROR = "Scout could not update your cart. Please try again.";

export interface UseCartResult {
  cart: CartView | null;
  itemCount: number;
  isLoading: boolean;
  errorMessage: string | null;
  stores: StoreSummary[];
  storesErrorMessage: string | null;
  addItem: (productId: string, quantity?: number) => Promise<void>;
  updateQuantity: (cartItemId: string, quantity: number) => Promise<void>;
  removeItem: (cartItemId: string) => Promise<void>;
  clear: () => Promise<void>;
  choosePickup: (storeId: string) => Promise<void>;
  chooseDelivery: () => Promise<void>;
  dismissError: () => void;
  refresh: () => Promise<void>;
  refreshStores: () => Promise<void>;
}

/**
 * @param sessionId The same session_id the chat hook is using (Step
 *   15's cart command resolution depends on both sharing one session)
 *   - passing an empty string is valid (nothing has a session yet) and
 *   simply skips fetching until a real one is set.
 */
export function useCart(sessionId: string): UseCartResult {
  const [cart, setCart] = useState<CartView | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [storesErrorMessage, setStoresErrorMessage] = useState<string | null>(null);

  const runMutation = useCallback(
    async (mutation: () => Promise<CartView>) => {
      setIsLoading(true);
      setErrorMessage(null);
      try {
        const updated = await mutation();
        setCart(updated);
      } catch (error) {
        setErrorMessage(error instanceof CartRequestError ? error.message : GENERIC_CART_ERROR);
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    getCart(sessionId)
      .then((result) => {
        if (!cancelled) {
          setCart(result);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setErrorMessage(error instanceof CartRequestError ? error.message : GENERIC_CART_ERROR);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const refreshStores = useCallback(async () => {
    setStoresErrorMessage(null);
    try {
      setStores(await listStores());
    } catch {
      setStores([]);
      setStoresErrorMessage("Scout could not load pickup locations. Check that the Step 17 backend is running, then try again.");
    }
  }, []);

  useEffect(() => {
    void refreshStores();
  }, [refreshStores]);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    setIsLoading(true);
    setErrorMessage(null);
    try {
      setCart(await getCart(sessionId));
    } catch (error) {
      setErrorMessage(error instanceof CartRequestError ? error.message : GENERIC_CART_ERROR);
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  const addItem = useCallback(
    (productId: string, quantity = 1) => runMutation(() => addCartItem(sessionId, productId, quantity)),
    [sessionId, runMutation]
  );

  const updateQuantity = useCallback(
    (cartItemId: string, quantity: number) =>
      runMutation(() => updateCartItemQuantity(sessionId, cartItemId, quantity)),
    [sessionId, runMutation]
  );

  const removeItem = useCallback(
    (cartItemId: string) => runMutation(() => removeCartItem(sessionId, cartItemId)),
    [sessionId, runMutation]
  );

  const clear = useCallback(() => runMutation(() => clearCart(sessionId)), [sessionId, runMutation]);

  const choosePickup = useCallback(
    (storeId: string) => runMutation(() => setFulfillment(sessionId, "pickup", storeId)),
    [sessionId, runMutation]
  );

  const chooseDelivery = useCallback(
    () => runMutation(() => setFulfillment(sessionId, "delivery", null)),
    [sessionId, runMutation]
  );

  const dismissError = useCallback(() => setErrorMessage(null), []);

  const itemCount = cart ? cart.items.reduce((total, item) => total + item.quantity, 0) : 0;

  return {
    cart,
    itemCount,
    isLoading,
    errorMessage,
    stores,
    storesErrorMessage,
    addItem,
    updateQuantity,
    removeItem,
    clear,
    choosePickup,
    chooseDelivery,
    dismissError,
    refresh,
    refreshStores,
  };
}
