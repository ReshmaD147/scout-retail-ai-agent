import { API_BASE_URL } from "./config";
import type { DurablePreference, PreferenceWrite } from "../types/memory";

export class MemoryRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MemoryRequestError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new MemoryRequestError("Scout could not reach memory settings.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as Record<string, unknown>;
    const message = typeof body.message === "string" ? body.message : "Scout could not update memory settings.";
    throw new MemoryRequestError(message);
  }
  return (await response.json()) as T;
}

export function listPreferences(customerId: string): Promise<DurablePreference[]> {
  return request<DurablePreference[]>(`/memory/preferences?customer_id=${encodeURIComponent(customerId)}`);
}

export function savePreference(write: PreferenceWrite): Promise<DurablePreference> {
  return request<DurablePreference>("/memory/preferences", {
    method: "POST",
    body: JSON.stringify({ confidence: 1, source: "explicit", ...write }),
  });
}

export function deletePreference(customerId: string, preferenceId: string): Promise<void> {
  return request<void>(`/memory/preferences/${encodeURIComponent(preferenceId)}?customer_id=${encodeURIComponent(customerId)}`, {
    method: "DELETE",
  });
}

export function clearPreferences(customerId: string): Promise<void> {
  return request<void>(`/memory/preferences?customer_id=${encodeURIComponent(customerId)}`, { method: "DELETE" });
}

export function setMemoryEnabled(customerId: string, memoryEnabled: boolean): Promise<{ customer_id: string; memory_enabled: boolean }> {
  return request<{ customer_id: string; memory_enabled: boolean }>("/memory/controls", {
    method: "POST",
    body: JSON.stringify({ customer_id: customerId, memory_enabled: memoryEnabled }),
  });
}

export function clearSessionMemory(sessionId: string): Promise<void> {
  return request<void>(`/memory/session/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
}
