/**
 * `useScoutChat` - the one place networking and workflow-state
 * handling live for Scout's frontend (Step 14). Every visual component
 * (SearchBar, AgentActivity, ProductGrid, ...) only ever reads what
 * this hook returns and calls its actions; none of them import
 * `chatClient`/`streamClient` directly, and none of them decide what
 * a backend result *means* - they only render it.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import { ChatRequestError, sendChatRequest } from "../api/chatClient";
import { StreamUnavailableError, streamChat } from "../api/streamClient";
import type {
  ActivityEvent,
  ChatError,
  ChatRequest,
  ChatResponse,
  StreamEvent,
  StreamEventType,
} from "../types/chat";

/** UI-level phase - distinct from (and layered on top of) the
 * backend's own `WorkflowStatus`: "result" covers every business
 * outcome the backend returned (completed/clarification_required/
 * no_results/confirmation_required/failed) - see `response.status`
 * for which one. "error" is reserved for a genuine service failure
 * (network unreachable, both /chat/stream and the /chat fallback
 * failed); "canceled" is a deliberate user action, never treated as
 * an error. */
export type ChatPhase = "idle" | "loading" | "result" | "canceled" | "error";

const GENERIC_ERROR_MESSAGE = "Scout could not process this request. Please try again.";

const ACTIVITY_EVENT_TYPES: ReadonlySet<StreamEventType> = new Set([
  "workflow_started",
  "plan_created",
  "agent_selected",
  "tool_started",
  "tool_completed",
  "workflow_replanned",
  "verification_started",
  "verification_completed",
  "clarification_required",
  "confirmation_required",
  "workflow_failed",
]);

function isChatResponse(value: unknown): value is ChatResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.workflow_id === "string" &&
    typeof candidate.session_id === "string" &&
    typeof candidate.status === "string" &&
    Array.isArray(candidate.products) &&
    Array.isArray(candidate.fulfillment_options) &&
    Array.isArray(candidate.activity_events) &&
    Array.isArray(candidate.errors)
  );
}

function isChatErrorPayload(value: unknown): value is ChatError {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return typeof candidate.code === "string" && typeof candidate.message === "string";
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function generateSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `session-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export interface UseScoutChatResult {
  query: string;
  setQuery: (value: string) => void;
  phase: ChatPhase;
  isLoading: boolean;
  activities: ActivityEvent[];
  response: ChatResponse | null;
  errorMessage: string | null;
  usedFallback: boolean;
  sessionId: string;
  /** Stable for the lifetime of this hook instance (Step 15) - shared
   * with useCart so "add the first product" resolves against the same
   * session's verified recommendation list /chat just persisted (see
   * scout/api/routes/chat.py::save_recommendation_snapshot). */
  submit: (overrideQuery?: string) => void;
  cancel: () => void;
  reset: () => void;
}

export function useScoutChat(): UseScoutChatResult {
  const [query, setQuery] = useState("");
  const [phase, setPhase] = useState<ChatPhase>("idle");
  const [activities, setActivities] = useState<ActivityEvent[]>([]);
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [usedFallback, setUsedFallback] = useState(false);

  const controllerRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string>(generateSessionId());

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setQuery("");
    setPhase("idle");
    setActivities([]);
    setResponse(null);
    setErrorMessage(null);
    setUsedFallback(false);
  }, []);

  const runFallback = useCallback(async (request: ChatRequest, signal: AbortSignal) => {
    try {
      const fallbackResponse = await sendChatRequest(request, signal);
      setResponse(fallbackResponse);
      setUsedFallback(true);
      setPhase("result");
    } catch (error) {
      if (isAbortError(error)) {
        setPhase("canceled");
        return;
      }
      setErrorMessage(error instanceof ChatRequestError ? error.message : GENERIC_ERROR_MESSAGE);
      setPhase("error");
    }
  }, []);

  const submit = useCallback(
    (overrideQuery?: string) => {
      const text = (overrideQuery ?? query).trim();
      if (!text || phase === "loading") {
        return;
      }

      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;

      setQuery(text);
      setPhase("loading");
      setActivities([]);
      setResponse(null);
      setErrorMessage(null);
      setUsedFallback(false);

      const request: ChatRequest = { session_id: sessionIdRef.current, message: text };

      void (async () => {
        let sawFinalResponse = false;
        let sawFailureWithoutFinal = false;

        const handleStreamEvent = (event: StreamEvent): void => {
          if (event.event_type === "heartbeat") {
            return;
          }

          if (ACTIVITY_EVENT_TYPES.has(event.event_type)) {
            setActivities((previous) => [
              ...previous,
              { id: event.event_id, type: event.event_type, label: event.label },
            ]);
          }

          if (event.event_type === "final_response" && isChatResponse(event.data)) {
            sawFinalResponse = true;
            setResponse(event.data);
            setPhase("result");
            return;
          }

          if (event.event_type === "workflow_failed" && !sawFinalResponse) {
            sawFailureWithoutFinal = true;
            const payload = isChatErrorPayload(event.data) ? event.data : null;
            setErrorMessage(payload?.message ?? GENERIC_ERROR_MESSAGE);
            setPhase("error");
          }
        };

        try {
          for await (const event of streamChat(request, controller.signal)) {
            handleStreamEvent(event);
          }
          if (!sawFinalResponse && !sawFailureWithoutFinal) {
            // The stream closed without ever telling us how the
            // workflow ended - should not normally happen, but the UI
            // must never sit on "loading" forever if it does.
            setErrorMessage(GENERIC_ERROR_MESSAGE);
            setPhase("error");
          }
        } catch (error) {
          if (isAbortError(error)) {
            setPhase("canceled");
            return;
          }
          if (error instanceof StreamUnavailableError) {
            await runFallback(request, controller.signal);
            return;
          }
          setErrorMessage(GENERIC_ERROR_MESSAGE);
          setPhase("error");
        }
      })();
    },
    [query, phase, runFallback]
  );

  return useMemo(
    () => ({
      query,
      setQuery,
      phase,
      isLoading: phase === "loading",
      activities,
      response,
      errorMessage,
      usedFallback,
      sessionId: sessionIdRef.current,
      submit,
      cancel,
      reset,
    }),
    [query, phase, activities, response, errorMessage, usedFallback, submit, cancel, reset]
  );
}
