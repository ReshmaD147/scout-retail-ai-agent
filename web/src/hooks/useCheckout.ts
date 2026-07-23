import { useCallback, useRef, useState } from "react";
import {
  CheckoutRequestError,
  confirmCheckout as confirmCheckoutRequest,
  createPaymentIntent,
  createCheckoutSession,
  getCheckoutPaymentStatus,
} from "../api/checkoutClient";
import type { CheckoutPaymentIntent, CheckoutPaymentStatus, CheckoutReview, OrderConfirmation, ShippingAddress } from "../types/checkout";

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
  paymentIntent: CheckoutPaymentIntent | null;
  paymentStatus: CheckoutPaymentStatus | null;
  isLoading: boolean;
  errorMessage: string | null;
  createReview: (shippingAddress: ShippingAddress | null) => Promise<void>;
  confirm: (confirmPayment: boolean) => Promise<void>;
  createStripeIntent: () => Promise<CheckoutPaymentIntent | null>;
  refreshPaymentStatus: () => Promise<CheckoutPaymentStatus | null>;
  reset: () => void;
  dismissError: () => void;
}

export function useCheckout(
  sessionId: string,
  onOrderCompleted?: () => void
): UseCheckoutResult {
  const [review, setReview] = useState<CheckoutReview | null>(null);
  const [confirmation, setConfirmation] = useState<OrderConfirmation | null>(null);
  const [paymentIntent, setPaymentIntent] = useState<CheckoutPaymentIntent | null>(null);
  const [paymentStatus, setPaymentStatus] = useState<CheckoutPaymentStatus | null>(null);
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
        setPaymentIntent(null);
        setPaymentStatus(null);
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

  const createStripeIntent = useCallback(async (): Promise<CheckoutPaymentIntent | null> => {
    if (!review || !sessionId) return null;
    const idempotencyKey = idempotencyKeyRef.current ?? createIdempotencyKey();
    idempotencyKeyRef.current = idempotencyKey;
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const intent = await createPaymentIntent(review.checkout_id, sessionId, idempotencyKey);
      setPaymentIntent(intent);
      setPaymentStatus({ checkout_id: intent.checkout_id, status: intent.status, order_id: null });
      return intent;
    } catch (error) {
      setErrorMessage(error instanceof CheckoutRequestError ? error.message : GENERIC_CHECKOUT_ERROR);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, [review, sessionId]);

  const refreshPaymentStatus = useCallback(async (): Promise<CheckoutPaymentStatus | null> => {
    if (!review || !sessionId) return null;
    try {
      const status = await getCheckoutPaymentStatus(review.checkout_id, sessionId);
      setPaymentStatus(status);
      if (status.status === "order_created") {
        onOrderCompleted?.();
      }
      return status;
    } catch (error) {
      setErrorMessage(error instanceof CheckoutRequestError ? error.message : GENERIC_CHECKOUT_ERROR);
      return null;
    }
  }, [onOrderCompleted, review, sessionId]);

  const reset = useCallback(() => {
    setReview(null);
    setConfirmation(null);
    setPaymentIntent(null);
    setPaymentStatus(null);
    setErrorMessage(null);
    idempotencyKeyRef.current = null;
  }, []);

  const dismissError = useCallback(() => setErrorMessage(null), []);

  return {
    review,
    confirmation,
    paymentIntent,
    paymentStatus,
    isLoading,
    errorMessage,
    createReview,
    confirm,
    createStripeIntent,
    refreshPaymentStatus,
    reset,
    dismissError,
  };
}
