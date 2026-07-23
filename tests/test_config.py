"""Tests for centralized configuration validation.

Settings() is a plain Pydantic model construction, so these tests
build it directly (never through the cached get_settings()) to check
that a bad delivery-window configuration fails fast - at startup,
not the first time a request happens to hit get_delivery_estimate.
"""

import pytest
from pydantic import ValidationError

from scout.config import Settings


def test_settings_default_supervisor_policy_is_ollama_with_low_temperature(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_POLICY", raising=False)
    settings = Settings()

    assert settings.supervisor_policy == "ollama"
    assert settings.ollama_chat_temperature == 0.1


def test_settings_accepts_a_valid_delivery_window():
    settings = Settings(standard_delivery_min_days=3, standard_delivery_max_days=5)

    assert settings.standard_delivery_min_days == 3
    assert settings.standard_delivery_max_days == 5


def test_settings_accepts_equal_min_and_max_days():
    settings = Settings(standard_delivery_min_days=3, standard_delivery_max_days=3)

    assert settings.standard_delivery_max_days == 3


def test_settings_rejects_negative_minimum_days():
    with pytest.raises(ValidationError):
        Settings(standard_delivery_min_days=-1, standard_delivery_max_days=5)


def test_settings_rejects_maximum_days_below_minimum_days():
    with pytest.raises(ValidationError):
        Settings(standard_delivery_min_days=5, standard_delivery_max_days=3)


def test_settings_accepts_valid_step_and_retry_limits():
    settings = Settings(
        max_workflow_steps=10,
        max_retries=2,
        max_agent_iterations=8,
        max_tool_calls=10,
        max_identical_tool_call_count=1,
        max_correction_attempts=1,
    )

    assert settings.max_workflow_steps == 10
    assert settings.max_retries == 2
    assert settings.max_agent_iterations == 8
    assert settings.max_tool_calls == 10
    assert settings.max_identical_tool_call_count == 1
    assert settings.max_correction_attempts == 1


def test_settings_rejects_a_max_workflow_steps_below_one():
    with pytest.raises(ValidationError):
        Settings(max_workflow_steps=0)


def test_settings_rejects_a_max_retries_below_one():
    with pytest.raises(ValidationError):
        Settings(max_retries=0)


def test_settings_rejects_invalid_agent_loop_limits():
    with pytest.raises(ValidationError):
        Settings(max_agent_iterations=0)
    with pytest.raises(ValidationError):
        Settings(max_tool_calls=0)
    with pytest.raises(ValidationError):
        Settings(max_identical_tool_call_count=0)
    with pytest.raises(ValidationError):
        Settings(max_correction_attempts=-1)


def test_settings_accepts_valid_checkout_rules():
    settings = Settings(
        checkout_tax_rate=0.075,
        flat_shipping_fee=6.49,
        free_shipping_threshold=75.0,
        checkout_currency="USD",
    )

    assert settings.checkout_tax_rate == 0.075
    assert settings.flat_shipping_fee == 6.49
    assert settings.free_shipping_threshold == 75.0
    assert settings.checkout_currency == "USD"


def test_settings_rejects_invalid_checkout_rules():
    with pytest.raises(ValidationError):
        Settings(checkout_tax_rate=1.01)
    with pytest.raises(ValidationError):
        Settings(flat_shipping_fee=-0.01)
    with pytest.raises(ValidationError):
        Settings(free_shipping_threshold=-1)
    with pytest.raises(ValidationError):
        Settings(checkout_currency="usd")


def test_stripe_provider_requires_test_keys(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_PUBLISHABLE_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(payment_provider="stripe_test", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(
            payment_provider="stripe_test",
            stripe_secret_key="sk_live_not_allowed",
            stripe_publishable_key="pk_test_ok",
            _env_file=None,
        )
    with pytest.raises(ValidationError):
        Settings(
            payment_provider="stripe_test",
            stripe_secret_key="sk_test_ok",
            stripe_publishable_key="pk_live_not_allowed",
            _env_file=None,
        )


def test_stripe_provider_accepts_test_keys():
    settings = Settings(
        payment_provider="stripe_test",
        stripe_secret_key="sk_test_ok",
        stripe_publishable_key="pk_test_ok",
        stripe_webhook_secret="whsec_ok",
    )

    assert settings.payment_provider == "stripe_test"


def test_settings_bounds_external_offer_limit():
    assert Settings(max_external_offers=3).max_external_offers == 3
    with pytest.raises(ValidationError):
        Settings(max_external_offers=0)
    with pytest.raises(ValidationError):
        Settings(max_external_offers=11)


def test_settings_bounds_ollama_chat_temperature():
    assert Settings(ollama_chat_temperature=0.0).ollama_chat_temperature == 0.0
    assert Settings(ollama_chat_temperature=0.2).ollama_chat_temperature == 0.2
    with pytest.raises(ValidationError):
        Settings(ollama_chat_temperature=-0.01)
    with pytest.raises(ValidationError):
        Settings(ollama_chat_temperature=0.21)
