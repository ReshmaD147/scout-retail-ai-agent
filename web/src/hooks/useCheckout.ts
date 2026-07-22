import { useCallback, useRef, useState } from "react";
import {
  CheckoutRequestError,
  confirmCheckout as confirmCheckoutRequest,
  createCheckoutSession,
} from "../api/checkoutClient";
import type { CheckoutReview, OrderConfirmation, ShippingAddress } from "../types/checkout";

const GENERIC_CHECKOUT_ERROR = "Scout could not complete checkout. Please try again.";

function createIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `checkout-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export interface UseCheckoutResult {
  review: CheckoutReview | null;
  confirmation: OrderConfirmation | null;
  isLoading: boolean;
  errorMessage: string | null;
  createReview: (shippingAddress: ShippingAddress | null) => Promise<void>;
  confirm: (confirmPayment: boolean) => Promise<void>;
  reset: () => void;
  dismissError: () => void;
}

export function useCheckout(
  sessionId: string,
  onOrderCompleted?: () => void
): UseCheckoutResult {
  const [review, setReview] = useState<CheckoutReview | null>(null);
  const [confirmation, setConfirmation] = useState<OrderConfirmation | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const idempotencyKeyRef = useRef<string | null>(null);

  const createReview = useCallback(
    async (shippingAddress: ShippingAddress | null) => {
      if (!sessionId) return;
      setIsLoading(true);
      setErrorMessage(null);
      setConfirmation(null);
      try {
        const created = await createCheckoutSession(sessionId, shippingAddress);
        setReview(created);
        idempotencyKeyRef.current = createIdempotencyKey();
      } catch (error) {
        setErrorMessage(
          error instanceof CheckoutRequestError ? error.message : GENERIC_CHECKOUT_ERROR
        );
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId]
  );

  const confirm = useCallback(
    async (confirmPayment: boolean) => {
      if (!review || !sessionId) return;
      const idempotencyKey = idempotencyKeyRef.current ?? createIdempotencyKey();
      idempotencyKeyRef.current = idempotencyKey;
      setIsLoading(true);
      setErrorMessage(null);
      try {
        const order = await confirmCheckoutRequest(
          review.checkout_id,
          sessionId,
          idempotencyKey,
          confirmPayment
        );
        setConfirmation(order);
        onOrderCompleted?.();
      } catch (error) {
        setErrorMessage(
          error instanceof CheckoutRequestError ? error.message : GENERIC_CHECKOUT_ERROR
        );
      } finally {
        setIsLoading(false);
      }
    },
    [onOrderCompleted, review, sessionId]
  );

  const reset = useCallback(() => {
    setReview(null);
    setConfirmation(null);
    setErrorMessage(null);
    idempotencyKeyRef.current = null;
  }, []);

  const dismissError = useCallback(() => setErrorMessage(null), []);

  return {
    review,
    confirmation,
    isLoading,
    errorMessage,
    createReview,
    confirm,
    reset,
    dismissError,
  };
}
