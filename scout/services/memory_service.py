"""Step 18 memory service with strict boundaries and validation."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scout.config import get_settings
from scout.orchestration.state import RetailGraphState
from scout.repositories.memory_repository import MemoryRepository
from scout.repositories.models import DurablePreferenceRecord, SessionMemoryRecord, WorkflowMemoryRecord
from scout.repositories.product_repository import ProductRepository

PreferenceType = Literal[
    "preferred_store",
    "preferred_brand",
    "disliked_brand",
    "size",
    "width",
    "typical_budget",
    "fulfillment_preference",
    "preferred_category",
]
PreferenceSource = Literal["explicit", "customer_confirmed", "inferred"]

_SENSITIVE_PATTERN = re.compile(
    r"(password|token|verification code|ssn|social security|card|bank|cvc|cvv|\b(?:\d[ -]*?){13,16}\b)",
    re.IGNORECASE,
)


class MemoryServiceError(Exception):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


class PreferenceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(min_length=1, max_length=200)
    type: PreferenceType
    value: str = Field(min_length=1, max_length=200)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: PreferenceSource = "explicit"
    status: Literal["active"] = "active"
    expires_at: Optional[str] = None

    @field_validator("customer_id", "value")
    @classmethod
    def _trim_and_reject_sensitive(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        if _SENSITIVE_PATTERN.search(stripped):
            raise ValueError("sensitive values cannot be stored in memory")
        return stripped


class MemoryControls(BaseModel):
    customer_id: str
    memory_enabled: bool


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _session_expires_at() -> str:
    return _iso(datetime.now(timezone.utc) + timedelta(hours=get_settings().session_memory_ttl_hours))


def _preference_expires_at() -> str:
    return _iso(datetime.now(timezone.utc) + timedelta(days=get_settings().durable_preference_ttl_days))


def is_memory_enabled(customer_id: Optional[str], db_path: Optional[str] = None) -> bool:
    settings = get_settings()
    try:
        return MemoryRepository(db_path).memory_enabled(customer_id, settings.memory_enabled_default)
    except Exception:
        return False


def save_working_memory_from_state(state: RetailGraphState, db_path: Optional[str] = None) -> Optional[WorkflowMemoryRecord]:
    try:
        verification_status = None
        if state.verification_result:
            verification_status = "verified" if state.verification_result.get("verified") else "failed"
        return MemoryRepository(db_path).save_workflow_memory(
            workflow_id=state.workflow_id or f"workflow-{state.session_id}",
            session_id=state.session_id,
            customer_id=state.user_id,
            current_query=state.customer_query,
            structured_intent=state.structured_intent.model_dump(mode="json") if state.structured_intent else None,
            current_plan=[step.model_dump(mode="json") for step in state.plan],
            completed_steps=list(state.completed_steps),
            remaining_steps=list(state.pending_steps),
            tool_result_refs=[trace.tool_name for trace in state.tool_results],
            evidence_ids=[entry.data.get("evidence_id") or entry.source for entry in state.evidence],
            selected_products=[product.product_id for product in state.selected_products or state.product_candidates],
            errors=[error.model_dump(mode="json") for error in state.errors],
            retry_state={
                "retry_count": state.retry_count,
                "step_count": state.step_count,
                "correction_count": state.correction_count,
                "repeated_call_counts": state.repeated_call_counts,
            },
            verification_status=verification_status,
            status="active" if state.workflow_status == "in_progress" else "completed",
            expires_at=None if state.workflow_status == "in_progress" else _iso(datetime.now(timezone.utc) + timedelta(hours=1)),
        )
    except Exception:
        return None


def complete_working_memory(workflow_id: str, db_path: Optional[str] = None) -> None:
    try:
        MemoryRepository(db_path).complete_workflow_memory(workflow_id, _iso(datetime.now(timezone.utc) + timedelta(hours=1)))
    except Exception:
        return


def update_session_from_state(state: RetailGraphState, db_path: Optional[str] = None) -> Optional[SessionMemoryRecord]:
    if state.user_id and not is_memory_enabled(state.user_id, db_path):
        return None
    try:
        intent = state.intent or {}
        recommended = [product.product_id for product in state.product_candidates]
        updates: Dict[str, Any] = {
            "recommended_products": recommended,
            "viewed_products": recommended,
            "current_budget": intent.get("max_price") or intent.get("budget_max"),
            "selected_store_id": intent.get("selected_store_id"),
            "fulfillment_preference": intent.get("fulfillment_preference") or ("pickup" if intent.get("pickup_requested") else None),
            "comparison_set": intent.get("comparison_product_ids") or [],
            "current_policy_topic": intent.get("policy_category") or intent.get("policy_query"),
            "authorized_order_ref": (state.order_context or {}).get("order_id") if state.order_context else None,
        }
        return MemoryRepository(db_path).upsert_session_memory(state.session_id, state.user_id, updates, _session_expires_at())
    except Exception:
        return None


def record_viewed_product(session_id: str, product_id: str, customer_id: Optional[str] = None, db_path: Optional[str] = None) -> SessionMemoryRecord:
    repo = MemoryRepository(db_path)
    existing = repo.get_session_memory(session_id, include_expired=True)
    viewed = list(existing.viewed_products if existing else [])
    if product_id not in viewed:
        viewed.append(product_id)
    return repo.upsert_session_memory(session_id, customer_id, {"viewed_products": viewed}, _session_expires_at())


def record_rejected_product(session_id: str, product_id: str, customer_id: Optional[str] = None, db_path: Optional[str] = None) -> SessionMemoryRecord:
    repo = MemoryRepository(db_path)
    existing = repo.get_session_memory(session_id, include_expired=True)
    rejected = list(existing.rejected_products if existing else [])
    if product_id not in rejected:
        rejected.append(product_id)
    return repo.upsert_session_memory(session_id, customer_id, {"rejected_products": rejected}, _session_expires_at())


def clear_session_context(session_id: str, db_path: Optional[str] = None) -> None:
    MemoryRepository(db_path).clear_session_memory(session_id)


def set_memory_enabled(customer_id: str, enabled: bool, db_path: Optional[str] = None) -> MemoryControls:
    if not customer_id.strip():
        raise MemoryServiceError("validation_error", "customer_id is required")
    MemoryRepository(db_path).set_memory_enabled(customer_id.strip(), enabled)
    return MemoryControls(customer_id=customer_id.strip(), memory_enabled=enabled)


def create_or_update_preference(write: PreferenceWrite, db_path: Optional[str] = None) -> DurablePreferenceRecord:
    if not is_memory_enabled(write.customer_id, db_path):
        raise MemoryServiceError("memory_disabled", "Memory is disabled for this customer.")
    expires_at = write.expires_at or _preference_expires_at()
    return MemoryRepository(db_path).upsert_preference(
        customer_id=write.customer_id,
        preference_type=write.type,
        value=write.value,
        confidence=write.confidence,
        source=write.source,
        status=write.status,
        expires_at=expires_at,
    )


def list_preferences(customer_id: str, db_path: Optional[str] = None) -> List[DurablePreferenceRecord]:
    if not is_memory_enabled(customer_id, db_path):
        return []
    return MemoryRepository(db_path).list_preferences(customer_id)


def delete_preference(customer_id: str, preference_id: str, db_path: Optional[str] = None) -> None:
    if not MemoryRepository(db_path).delete_preference(customer_id, preference_id):
        raise MemoryServiceError("not_found", "Preference was not found for this customer.")


def clear_preferences(customer_id: str, db_path: Optional[str] = None) -> int:
    return MemoryRepository(db_path).clear_preferences(customer_id)


def bounded_preference_score(product_id: str, customer_id: Optional[str], db_path: Optional[str] = None) -> float:
    if not customer_id or not is_memory_enabled(customer_id, db_path):
        return 0.0
    product = ProductRepository(db_path).get_by_id(product_id)
    if product is None:
        return 0.0
    score = 0.0
    for preference in list_preferences(customer_id, db_path):
        value = preference.value.casefold()
        bounded = min(preference.confidence, 1.0) * 0.05
        if preference.type == "preferred_brand" and product.brand.casefold() == value:
            score += bounded
        elif preference.type == "disliked_brand" and product.brand.casefold() == value:
            score -= bounded
        elif preference.type == "preferred_category" and product.category.casefold() == value:
            score += bounded
    return max(min(score, 0.1), -0.1)
