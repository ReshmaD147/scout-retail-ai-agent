export interface DurablePreference {
  preference_id: string;
  customer_id: string;
  type: string;
  value: string;
  confidence: number;
  source: string;
  status: string;
  created_at: string;
  updated_at: string;
  last_confirmed_at: string | null;
  expires_at: string | null;
}

export interface PreferenceWrite {
  customer_id: string;
  type: string;
  value: string;
  confidence?: number;
  source?: "explicit" | "customer_confirmed" | "inferred";
}
