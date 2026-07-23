import { API_BASE_URL } from "./config";
import type { CatalogFilterOptions } from "../types/catalog";

export async function getCatalogFilterOptions(signal?: AbortSignal): Promise<CatalogFilterOptions> {
  const response = await fetch(`${API_BASE_URL}/catalog/filter-options`, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    throw new Error("Scout could not load catalog filters.");
  }
  return (await response.json()) as CatalogFilterOptions;
}
