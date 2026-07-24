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
  ConversationMessage,
  ConversationMessageType,
  RecommendationFilters,
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
    Array.isArray(candidate.external_offers) &&
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

function generateMessageId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function messageTypeForResponse(response: ChatResponse): ConversationMessageType {
  if (response.message_type) return response.message_type;
  if (response.order) return "order_status";
  if (response.products.length > 0) return "recommendation";
  if (response.status === "clarification_required") return "clarification";
  if (response.status === "failed") return "safe_failure";
  return "text";
}

export interface UseScoutChatResult {
  query: string;
  setQuery: (value: string) => void;
  phase: ChatPhase;
  isLoading: boolean;
  activities: ActivityEvent[];
  response: ChatResponse | null;
  messages: ConversationMessage[];
  activeRequestId: string | null;
  errorMessage: string | null;
  usedFallback: boolean;
  sessionId: string;
  /** Stable for the lifetime of this hook instance (Step 15) - shared
   * with useCart so "add the first product" resolves against the same
   * session's verified recommendation list /chat just persisted (see
   * scout/api/routes/chat.py::save_recommendation_snapshot). */
  submit: (overrideQuery?: string, filters?: RecommendationFilters) => void;
  cancel: () => void;
  reset: () => void;
  clearConversation: () => void;
  retryMessage: (messageId: string) => void;
  setFeedback: (messageId: string, value: "helpful" | "not_helpful") => void;
}

function applyWorkflowEvent(previous: ActivityEvent[], event: StreamEvent): ActivityEvent[] {
  if (event.event_type === "workflow_failed") {
    const failedActivity: ActivityEvent = {
      id: event.event_id,
      type: event.event_type,
      label: event.label,
      status: "failed",
    };
    return [
      ...previous.map((activity) => activity.status === "active" ? { ...activity, status: "failed" as const } : activity),
      failedActivity,
    ];
  }

  if (event.event_type === "final_response") {
    return previous.map((activity) => activity.status === "active" ? { ...activity, status: "completed" as const } : activity);
  }

  if (event.event_type === "clarification_required" || event.event_type === "confirmation_required") {
    return previous.map((activity) => activity.status === "active" ? { ...activity, status: "completed" as const } : activity);
  }

  if (
    !event.event_type.endsWith("_completed") &&
    previous.some((activity) => activity.type === event.event_type && activity.label === event.label)
  ) {
    return previous;
  }

  const completionType = event.event_type.replace("_completed", "_started");
  const matchingStartedIndex = event.event_type.endsWith("_completed")
    ? previous.findIndex((activity) => activity.type === completionType)
    : -1;

  if (matchingStartedIndex >= 0) {
    return previous.map((activity, index) => (
      index === matchingStartedIndex ? { ...activity, status: "completed" as const } : activity
    ));
  }

  const activity: ActivityEvent = {
    id: event.event_id,
    type: event.event_type,
    label: event.label,
    status: event.event_type.endsWith("_completed")
      ? "completed"
      : "active",
  };
  return [
    ...previous.map((entry) => entry.status === "active" ? { ...entry, status: "completed" as const } : entry),
    activity,
  ];
}

export function useScoutChat(): UseScoutChatResult {
  const [query, setQuery] = useState("");
  const [phase, setPhase] = useState<ChatPhase>("idle");
  const [activities, setActivities] = useState<ActivityEvent[]>([]);
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [activeRequestId, setActiveRequestId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [usedFallback, setUsedFallback] = useState(false);

  const controllerRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string>(generateSessionId());
  const activeAssistantMessageIdRef = useRef<string | null>(null);

  const attachActivities = useCallback((requestId: string, nextActivities: ActivityEvent[]) => {
    setMessages((previous) => previous.map((message) => (
      message.request_id === requestId && message.role === "assistant"
        ? { ...message, activities: nextActivities }
        : message
    )));
  }, []);

  const completeAssistantMessage = useCallback((requestId: string, chatResponse: ChatResponse, status: "completed" | "failed" = "completed") => {
    setMessages((previous) => previous.map((message) => (
      message.request_id === requestId && message.role === "assistant"
        ? {
            ...message,
            message_id: chatResponse.assistant_message_id ?? message.message_id,
            message_type: messageTypeForResponse(chatResponse),
            content: chatResponse.answer ?? (chatResponse.products.length > 0 ? "I found verified results." : ""),
            status,
            product_ids: chatResponse.product_ids ?? chatResponse.products.map((product) => product.product_id),
            order_id: chatResponse.order?.order_id ?? null,
            approved_claims: chatResponse.approved_claims ?? [],
            suggested_actions: chatResponse.suggested_actions ?? [],
            response: chatResponse,
          }
        : message
    )));
  }, [activeRequestId]);

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    const requestId = activeRequestId;
    if (requestId) {
      setMessages((previous) => previous.map((message) => (
        message.request_id === requestId && message.role === "assistant"
          ? { ...message, status: "canceled" }
          : message
      )));
    }
  }, [activeRequestId]);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setQuery("");
    setPhase("idle");
    setActivities([]);
    setResponse(null);
    setMessages([]);
    setActiveRequestId(null);
    setErrorMessage(null);
    setUsedFallback(false);
  }, []);

  const clearConversation = useCallback(() => {
    controllerRef.current?.abort();
    setMessages([]);
    setActivities([]);
    setResponse(null);
    setActiveRequestId(null);
    setPhase("idle");
    setErrorMessage(null);
  }, []);

  const stageRetryMessage = useCallback((messageId: string) => {
    const message = messages.find((entry) => entry.message_id === messageId && entry.role === "user");
    if (message) {
      setQuery(message.content);
    }
  }, [messages]);

  const setFeedback = useCallback((messageId: string, value: "helpful" | "not_helpful") => {
    setMessages((previous) => previous.map((message) => (
      message.message_id === messageId && message.role === "assistant"
        ? { ...message, feedback: value }
        : message
    )));
  }, []);

  const runFallback = useCallback(async (request: ChatRequest, signal: AbortSignal, requestId: string) => {
    try {
      const fallbackResponse = await sendChatRequest(request, signal);
      setResponse(fallbackResponse);
      completeAssistantMessage(requestId, fallbackResponse);
      setUsedFallback(true);
      setPhase("result");
    } catch (error) {
      if (isAbortError(error)) {
        setMessages((previous) => previous.map((message) => (
          message.request_id === requestId && message.role === "assistant"
            ? { ...message, content: "Canceled by customer.", status: "canceled" }
            : message
        )));
        setPhase("canceled");
        return;
      }
      setErrorMessage(error instanceof ChatRequestError ? error.message : GENERIC_ERROR_MESSAGE);
      setMessages((previous) => previous.map((message) => (
        message.request_id === requestId && message.role === "assistant"
          ? { ...message, content: error instanceof ChatRequestError ? error.message : GENERIC_ERROR_MESSAGE, status: "failed" }
          : message
      )));
      setPhase("error");
    }
  }, [completeAssistantMessage]);

  const submit = useCallback(
    (overrideQuery?: string, filters?: RecommendationFilters) => {
      const text = (overrideQuery ?? query).trim();
      if (!text || phase === "loading") {
        return;
      }

      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      const requestId = generateMessageId("request");
      const userMessageId = generateMessageId("user");
      const assistantMessageId = generateMessageId("assistant");
      activeAssistantMessageIdRef.current = assistantMessageId;
      setActiveRequestId(requestId);
      const createdAt = new Date().toISOString();

      setQuery(text);
      setPhase("loading");
      setActivities([]);
      setResponse(null);
      setErrorMessage(null);
      setUsedFallback(false);
      setMessages((previous) => [
        ...previous,
        {
          message_id: userMessageId,
          session_id: sessionIdRef.current,
          request_id: requestId,
          role: "user",
          message_type: "text",
          content: text,
          status: "completed",
          created_at: createdAt,
          product_ids: [],
          order_id: null,
          approved_claims: [],
          suggested_actions: [],
        },
        {
          message_id: assistantMessageId,
          session_id: sessionIdRef.current,
          request_id: requestId,
          role: "assistant",
          message_type: "text",
          content: "Scout is working on it…",
          status: "streaming",
          created_at: createdAt,
          product_ids: [],
          order_id: null,
          approved_claims: [],
          suggested_actions: [],
          activities: [],
        },
      ]);

      const request: ChatRequest = {
        session_id: sessionIdRef.current,
        message: text,
        ...(filters ? { filters } : {}),
      };

      void (async () => {
        let sawFinalResponse = false;
        let sawFailureWithoutFinal = false;

        const handleStreamEvent = (event: StreamEvent): void => {
          if (event.event_type === "heartbeat") {
            return;
          }
          if (activeAssistantMessageIdRef.current !== assistantMessageId) {
            return;
          }

          if (ACTIVITY_EVENT_TYPES.has(event.event_type)) {
            setActivities((previous) => {
              const next = applyWorkflowEvent(previous, event);
              attachActivities(requestId, next);
              return next;
            });
          }

          if (event.event_type === "final_response" && isChatResponse(event.data)) {
            sawFinalResponse = true;
            setActivities((previous) => {
              const next = applyWorkflowEvent(previous, event);
              attachActivities(requestId, next);
              return next;
            });
            setResponse(event.data);
            completeAssistantMessage(requestId, event.data);
            setPhase("result");
            return;
          }

          if (event.event_type === "workflow_failed" && !sawFinalResponse) {
            sawFailureWithoutFinal = true;
            const payload = isChatErrorPayload(event.data) ? event.data : null;
            setErrorMessage(payload?.message ?? GENERIC_ERROR_MESSAGE);
            setMessages((previous) => previous.map((message) => (
              message.request_id === requestId && message.role === "assistant"
                ? { ...message, content: payload?.message ?? GENERIC_ERROR_MESSAGE, status: "failed" }
                : message
            )));
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
            setMessages((previous) => previous.map((message) => (
              message.request_id === requestId && message.role === "assistant"
                ? { ...message, content: GENERIC_ERROR_MESSAGE, status: "failed" }
                : message
            )));
            setPhase("error");
          }
        } catch (error) {
          if (isAbortError(error)) {
            setMessages((previous) => previous.map((message) => (
              message.request_id === requestId && message.role === "assistant"
                ? { ...message, content: "Canceled by customer.", status: "canceled" }
                : message
            )));
            setPhase("canceled");
            return;
          }
          if (error instanceof StreamUnavailableError) {
            await runFallback(request, controller.signal, requestId);
            return;
          }
          setErrorMessage(GENERIC_ERROR_MESSAGE);
          setMessages((previous) => previous.map((message) => (
            message.request_id === requestId && message.role === "assistant"
              ? { ...message, content: GENERIC_ERROR_MESSAGE, status: "failed" }
              : message
          )));
          setPhase("error");
        }
      })();
    },
    [query, phase, runFallback, attachActivities, completeAssistantMessage]
  );

  const retryMessage = useCallback((messageId: string) => {
    const message = messages.find((entry) => entry.message_id === messageId && entry.role === "user");
    if (message) {
      submit(message.content);
      return;
    }
    stageRetryMessage(messageId);
  }, [messages, stageRetryMessage, submit]);

  return useMemo(
    () => ({
      query,
      setQuery,
      phase,
      isLoading: phase === "loading",
      activities,
      response,
      messages,
      activeRequestId,
      errorMessage,
      usedFallback,
      sessionId: sessionIdRef.current,
      submit,
      cancel,
      reset,
      clearConversation,
      retryMessage,
      setFeedback,
    }),
    [query, phase, activities, response, messages, activeRequestId, errorMessage, usedFallback, submit, cancel, reset, clearConversation, retryMessage, setFeedback]
  );
}
