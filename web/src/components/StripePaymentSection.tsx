import { useMemo, useState } from "react";
import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe } from "@stripe/stripe-js";
import type { Stripe } from "@stripe/stripe-js";
import type { UseCheckoutResult } from "../hooks/useCheckout";

interface StripePaymentSectionProps {
  checkout: UseCheckoutResult;
}

function StripePaymentForm({ checkout }: StripePaymentSectionProps): JSX.Element {
  const stripe = useStripe();
  const elements = useElements();
  const [processing, setProcessing] = useState(false);

  const pay = async (): Promise<void> => {
    if (!stripe || !elements || !checkout.paymentIntent) return;
    setProcessing(true);
    try {
      const result = await stripe.confirmPayment({
        elements,
        clientSecret: checkout.paymentIntent.client_secret,
        confirmParams: { return_url: window.location.href },
        redirect: "if_required",
      });
      if (result.error) {
        checkout.dismissError();
        await checkout.refreshPaymentStatus();
        return;
      }
      await checkout.refreshPaymentStatus();
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div className="checkout-stripe">
      <PaymentElement />
      <button
        type="button"
        className="checkout-panel__primary"
        disabled={!stripe || !elements || processing || checkout.isLoading}
        onClick={() => void pay()}
      >
        {processing ? "Processing test payment..." : "Pay with Stripe test card"}
      </button>
    </div>
  );
}

export function StripePaymentSection({ checkout }: StripePaymentSectionProps): JSX.Element {
  const stripePromise = useMemo<Promise<Stripe | null> | null>(() => {
    if (!checkout.paymentIntent?.publishable_key) return null;
    return loadStripe(checkout.paymentIntent.publishable_key);
  }, [checkout.paymentIntent?.publishable_key]);

  if (!checkout.paymentIntent) {
    return (
      <button
        type="button"
        className="checkout-panel__primary"
        disabled={checkout.isLoading}
        onClick={() => void checkout.createStripeIntent()}
      >
        {checkout.isLoading ? "Preparing Stripe..." : `Prepare Stripe test payment · $${checkout.review?.total.toFixed(2)}`}
      </button>
    );
  }

  return (
    <>
      <p className="checkout-panel__test-note">
        Stripe test mode is enabled. Use Stripe test cards only; Scout never handles card numbers or CVC.
      </p>
      {checkout.paymentStatus && (
        <p className="checkout-panel__note">Payment state: {checkout.paymentStatus.status}</p>
      )}
      {stripePromise && checkout.paymentIntent.client_secret ? (
        <Elements stripe={stripePromise} options={{ clientSecret: checkout.paymentIntent.client_secret }}>
          <StripePaymentForm checkout={checkout} />
        </Elements>
      ) : (
        <p className="checkout-panel__error">Stripe test payment is not ready. Please try again.</p>
      )}
    </>
  );
}
