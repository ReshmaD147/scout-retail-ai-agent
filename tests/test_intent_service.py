import json

from scout.config import get_settings
from scout.services.intent_service import StructuredIntent, extract_intent_with_ollama


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses=None, exc=None):
        self._responses = list(responses or [])
        self._exc = exc
        self.requests = []
        self.closed = False

    def post(self, url, json):
        self.requests.append((url, json))
        if self._exc is not None:
            raise self._exc
        return _FakeResponse({"response": self._responses.pop(0)})

    def close(self):
        self.closed = True


def test_ollama_intent_request_uses_strict_json_and_low_temperature(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "scout-intent")
    monkeypatch.setenv("OLLAMA_CHAT_TEMPERATURE", "0.1")
    get_settings.cache_clear()
    client = _FakeClient(
        [
            json.dumps(
                {
                    "request_type": "product_search",
                    "product_type": "Work",
                    "category": "Footwear",
                    "use_case": None,
                    "attributes": [],
                    "budget_min": None,
                    "budget_max": None,
                    "location": None,
                    "fulfillment_preference": None,
                    "urgency": None,
                    "reference_product_id": None,
                    "comparison_product_ids": [],
                    "order_id": None,
                    "needs_clarification": False,
                    "clarification_question": None,
                    "confidence": 0.9,
                }
            )
        ]
    )

    try:
        result = extract_intent_with_ollama("Need work shoes", client=client)
    finally:
        get_settings.cache_clear()

    assert result.extraction_source == "llm"
    assert result.intent.product_type == "Work"
    request = client.requests[0][1]
    assert request["model"] == "scout-intent"
    assert request["stream"] is False
    assert request["format"] == "json"
    assert request["options"]["temperature"] == 0.1
    assert "Return strict JSON only" in request["prompt"]


def _intent_payload(**overrides):
    payload = {
        "request_type": "product_search",
        "product_type": None,
        "category": None,
        "use_case": None,
        "attributes": [],
        "budget_min": None,
        "budget_max": None,
        "location": None,
        "fulfillment_preference": None,
        "urgency": None,
        "reference_product_id": None,
        "comparison_product_ids": [],
        "order_id": None,
        "needs_clarification": False,
        "clarification_question": None,
        "confidence": 0.8,
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_intent_extracts_search():
    result = extract_intent_with_ollama(
        "find work shoes",
        client=_FakeClient([_intent_payload(request_type="product_search", product_type="work shoes")]),
    )

    assert result.intent.request_type == "product_search"
    assert result.intent.product_type == "work shoes"


def test_intent_extracts_comparison():
    result = extract_intent_with_ollama(
        "compare FTW-004 and FTW-002",
        client=_FakeClient([
            _intent_payload(request_type="compare", comparison_product_ids=["FTW-004", "FTW-002"])
        ]),
    )

    assert result.intent.request_type == "compare"
    assert result.intent.comparison_product_ids == ["FTW-004", "FTW-002"]


def test_intent_extracts_similar_products():
    result = extract_intent_with_ollama(
        "find products similar to FTW-004",
        client=_FakeClient([_intent_payload(request_type="find_similar", reference_product_id="FTW-004")]),
    )

    assert result.intent.request_type == "find_similar"
    assert result.intent.reference_product_id == "FTW-004"


def test_intent_extracts_fulfillment_location_and_budget():
    result = extract_intent_with_ollama(
        "pickup work shoes under $100 near Plymouth today",
        client=_FakeClient([
            _intent_payload(
                request_type="fulfillment",
                product_type="work shoes",
                budget_max=100,
                location="Plymouth",
                fulfillment_preference="pickup",
                urgency="today",
            )
        ]),
    )

    assert result.intent.request_type == "fulfillment"
    assert result.intent.location == "Plymouth"
    assert result.intent.budget_max == 100
    assert result.intent.fulfillment_preference == "pickup"


def test_intent_extracts_vague_request_clarification():
    result = extract_intent_with_ollama(
        "help me choose",
        client=_FakeClient([
            _intent_payload(
                request_type="clarification",
                needs_clarification=True,
                clarification_question="What kind of product are you looking for?",
            )
        ]),
    )

    assert result.intent.request_type == "clarification"
    assert result.intent.needs_clarification is True
    assert result.intent.clarification_question == "What kind of product are you looking for?"


def test_intent_extracts_out_of_scope():
    result = extract_intent_with_ollama(
        "write me a poem",
        client=_FakeClient([_intent_payload(request_type="out_of_scope", confidence=0.9)]),
    )

    assert result.intent.request_type == "out_of_scope"


def test_malformed_json_retries_once_and_records_retry_source():
    valid = json.dumps(
        {
            "request_type": "deals",
            "product_type": "Coffee Makers",
            "category": "Home and Kitchen",
            "use_case": None,
            "attributes": [],
            "budget_min": None,
            "budget_max": None,
            "location": None,
            "fulfillment_preference": None,
            "urgency": None,
            "reference_product_id": None,
            "comparison_product_ids": [],
            "order_id": None,
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.8,
        }
    )
    client = _FakeClient(["not-json", valid])

    result = extract_intent_with_ollama("Coffee maker deals", client=client)

    assert result.extraction_source == "retry"
    assert result.intent.request_type == "deals"
    assert len(client.requests) == 2


def test_ollama_failure_returns_deterministic_fallback_source():
    fallback = StructuredIntent(
        request_type="clarification",
        needs_clarification=True,
        clarification_question="What product are you looking for?",
    )
    client = _FakeClient(exc=RuntimeError("ollama unavailable"))

    result = extract_intent_with_ollama("hello", client=client, fallback_intent=fallback)

    assert result.extraction_source == "deterministic_fallback"
    assert result.intent is fallback


def test_llm_sanitization_drops_unmentioned_ids_prices_and_locations():
    raw = json.dumps(
        {
            "request_type": "find_similar",
            "product_type": None,
            "category": None,
            "use_case": None,
            "attributes": [],
            "budget_min": None,
            "budget_max": 999.0,
            "location": "Invented City",
            "fulfillment_preference": None,
            "urgency": None,
            "reference_product_id": "FTW-999",
            "comparison_product_ids": ["FTW-001", "BAG-777"],
            "order_id": "123e4567-e89b-42d3-a456-426614174000",
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.8,
        }
    )
    client = _FakeClient([raw])

    result = extract_intent_with_ollama("Find similar products to FTW-001", client=client)

    assert result.intent.budget_max is None
    assert result.intent.location is None
    assert result.intent.reference_product_id is None
    assert result.intent.comparison_product_ids == ["FTW-001"]
    assert result.intent.order_id is None
