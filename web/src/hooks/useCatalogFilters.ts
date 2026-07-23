import { useEffect, useState } from "react";
import { getCatalogFilterOptions } from "../api/catalogClient";
import type { CatalogFilterOptions } from "../types/catalog";

export interface UseCatalogFiltersResult {
  options: CatalogFilterOptions | null;
  isLoading: boolean;
  errorMessage: string | null;
}

export function useCatalogFilters(): UseCatalogFiltersResult {
  const [options, setOptions] = useState<CatalogFilterOptions | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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
        setErrorMessage("Scout could not load catalog filters. Please try again.");
      })
      .finally(() => setIsLoading(false));
    return () => controller.abort();
  }, []);

  return { options, isLoading, errorMessage };
}
