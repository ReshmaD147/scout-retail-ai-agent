import { useEffect, useState } from "react";
import { getCatalogFilterOptions } from "../api/catalogClient";
import type { CatalogFilterOptions } from "../types/catalog";

export interface UseCatalogFiltersResult {
  options: CatalogFilterOptions | null;
  isLoading: boolean;
  errorMessage: string | null;
  retry: () => void;
}

export function useCatalogFilters(): UseCatalogFiltersResult {
  const [options, setOptions] = useState<CatalogFilterOptions | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    getCatalogFilterOptions(controller.signal)
      .then((result) => {
        setOptions(result);
        setErrorMessage(null);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setErrorMessage("Filters are temporarily unavailable. You can still search normally.");
      })
      .finally(() => setIsLoading(false));
    return () => controller.abort();
  }, [attempt]);

  return { options, isLoading, errorMessage, retry: () => setAttempt((value) => value + 1) };
}
