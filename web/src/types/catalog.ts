export interface CatalogAttributeOption {
  token: string;
  label: string;
  key: string;
  value: string;
  categories: string[];
  product_types: string[];
}

export interface CatalogFilterOptions {
  max_price: number;
  categories: string[];
  product_types: Record<string, string[]>;
  attributes: CatalogAttributeOption[];
}
