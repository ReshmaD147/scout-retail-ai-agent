import json

from scout.services.product_explanation_service import (
    ProductExplanationEvidence,
    deterministic_fallback,
    generate_explanation,
    normalize_attribute_labels,
    verify_explanation,
)


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)

    def post(self, *args, **kwargs):
        return _Response({"response": self.responses.pop(0)})


def _evidence() -> ProductExplanationEvidence:
    return ProductExplanationEvidence(
        product_id="FTW-004",
        product_name="ComfortPro Shift Support",
        category="Footwear",
        product_type="Work",
        regular_price=89.99,
        promotional_price=80.99,
        budget_compliant=True,
        matched_attributes=["high cushioning", "slip resistant", "wide fit"],
        inventory={"quantity": 7, "scope": "store network"},
        promotion={"label": "Workwear Comfort Event", "verified": True, "savings": 9.0},
        rating=4.7,
        review_count=401,
    )


def test_ollama_explanation_uses_approved_evidence_only():
    explanation = (
        "ComfortPro Shift Support matches your work-shoe request with high cushioning "
        "and slip resistant features. Its verified $80.99 promotional price is within budget."
    )
    client = _Client([json.dumps({"product_id": "FTW-004", "explanation": explanation})])

    result = generate_explanation(_evidence(), "Work shoes under $100", client=client)

    assert result.source == "ollama"
    assert result.explanation == explanation


def test_malformed_ollama_json_retries_once():
    explanation = "ComfortPro Shift Support matches your request with high cushioning."
    client = _Client(["not-json", json.dumps({"product_id": "FTW-004", "explanation": explanation})])

    result = generate_explanation(_evidence(), "Work shoes under $100", client=client)

    assert result.source == "retry"
    assert result.explanation == explanation


def test_invalid_ollama_claim_uses_deterministic_fallback():
    client = _Client([
        json.dumps({"product_id": "FTW-004", "explanation": "This is the perfect waterproof steel toe shoe."}),
        json.dumps({"product_id": "FTW-004", "explanation": "This is the best premium shoe."}),
    ])

    result = generate_explanation(_evidence(), "Work shoes under $100", client=client)

    assert result.source == "deterministic_fallback"
    assert "verified price" in result.explanation


def test_unsupported_explanation_claim_is_rejected():
    assert verify_explanation("It is a waterproof steel toe shoe.", _evidence()) is False


def test_deterministic_fallback_uses_same_approved_evidence():
    result = deterministic_fallback(_evidence())

    assert "high cushioning" in result.explanation
    assert "$80.99" in result.explanation
    assert "Workwear Comfort Event" in result.explanation


def test_raw_attribute_tags_are_normalized_before_explanation():
    labels = normalize_attribute_labels(["high", "wide", "work shifts / standing all day"])

    assert labels == ["high cushioning", "wide fit", "designed for long work shifts"]
    fallback = deterministic_fallback(_evidence().model_copy(update={"matched_attributes": ["high", "wide"]}))
    assert "high, wide" not in fallback.explanation
    assert "high cushioning" in fallback.explanation
    assert "wide fit" in fallback.explanation
