import { useCallback, useEffect, useMemo, useState } from "react";
import {
  listSavedProducts,
  removeSavedProduct,
  SavedProductsRequestError,
  saveProduct,
} from "../api/savedProductsClient";
import type { SavedProductsView } from "../types/saved";

const GENERIC_SAVED_ERROR = "Scout could not load your saved products. Please try again.";

export interface UseSavedProductsResult {
  saved: SavedProductsView | null;
  savedIds: Set<string>;
  count: number;
  isLoading: boolean;
  errorMessage: string | null;
  refresh: () => Promise<void>;
  toggle: (productId: string) => Promise<void>;
  dismissError: () => void;
}

export function useSavedProducts(sessionId: string): UseSavedProductsResult {
  const [saved, setSaved] = useState<SavedProductsView | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    setIsLoading(true);
    setErrorMessage(null);
    try {
      setSaved(await listSavedProducts(sessionId));
    } catch (error) {
      setErrorMessage(error instanceof SavedProductsRequestError ? error.message : GENERIC_SAVED_ERROR);
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const savedIds = useMemo(() => new Set(saved?.saved_product_ids ?? []), [saved]);

  const toggle = useCallback(async (productId: string) => {
    if (!sessionId) return;
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const updated = savedIds.has(productId)
        ? await removeSavedProduct(sessionId, productId)
        : await saveProduct(sessionId, productId);
      setSaved(updated);
    } catch (error) {
      setErrorMessage(error instanceof SavedProductsRequestError ? error.message : "Scout could not update your saved products. Please try again.");
    } finally {
      setIsLoading(false);
    }
  }, [savedIds, sessionId]);

  return {
    saved,
    savedIds,
    count: saved?.count ?? 0,
    isLoading,
    errorMessage,
    refresh,
    toggle,
    dismissError: () => setErrorMessage(null),
  };
}
