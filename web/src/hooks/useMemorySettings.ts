import { useCallback, useEffect, useMemo, useState } from "react";
import {
  clearPreferences,
  clearSessionMemory,
  deletePreference,
  listPreferences,
  savePreference,
  setMemoryEnabled,
} from "../api/memoryClient";
import type { DurablePreference } from "../types/memory";

export interface UseMemorySettingsResult {
  preferences: DurablePreference[];
  memoryEnabled: boolean;
  isLoading: boolean;
  errorMessage: string | null;
  refresh: () => Promise<void>;
  save: (type: string, value: string) => Promise<void>;
  remove: (preferenceId: string) => Promise<void>;
  clearAll: () => Promise<void>;
  setEnabled: (enabled: boolean) => Promise<void>;
  clearSession: () => Promise<void>;
}

export function useMemorySettings(customerId: string, sessionId: string): UseMemorySettingsResult {
  const [preferences, setPreferences] = useState<DurablePreference[]>([]);
  const [memoryEnabled, setMemoryEnabledState] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      setPreferences(await listPreferences(customerId));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Scout could not load memory settings.");
    } finally {
      setIsLoading(false);
    }
  }, [customerId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const save = useCallback(async (type: string, value: string) => {
    setErrorMessage(null);
    try {
      await savePreference({ customer_id: customerId, type, value });
      await refresh();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Scout could not save that preference.");
    }
  }, [customerId, refresh]);

  const remove = useCallback(async (preferenceId: string) => {
    setErrorMessage(null);
    try {
      await deletePreference(customerId, preferenceId);
      await refresh();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Scout could not remove that preference.");
    }
  }, [customerId, refresh]);

  const clearAll = useCallback(async () => {
    setErrorMessage(null);
    try {
      await clearPreferences(customerId);
      await refresh();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Scout could not clear remembered preferences.");
    }
  }, [customerId, refresh]);

  const setEnabled = useCallback(async (enabled: boolean) => {
    setErrorMessage(null);
    try {
      const result = await setMemoryEnabled(customerId, enabled);
      setMemoryEnabledState(result.memory_enabled);
      if (!result.memory_enabled) setPreferences([]);
      else await refresh();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Scout could not update memory controls.");
    }
  }, [customerId, refresh]);

  const clearSession = useCallback(async () => {
    setErrorMessage(null);
    try {
      await clearSessionMemory(sessionId);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Scout could not clear session context.");
    }
  }, [sessionId]);

  return useMemo(() => ({
    preferences,
    memoryEnabled,
    isLoading,
    errorMessage,
    refresh,
    save,
    remove,
    clearAll,
    setEnabled,
    clearSession,
  }), [preferences, memoryEnabled, isLoading, errorMessage, refresh, save, remove, clearAll, setEnabled, clearSession]);
}
