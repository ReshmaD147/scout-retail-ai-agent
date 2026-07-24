"""Deterministic customer memory controls."""

from typing import List

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from scout.api.exceptions import ScoutAppError
from scout.repositories.models import DurablePreferenceRecord, SessionMemoryRecord
from scout.services.memory_service import (
    MemoryControls,
    MemoryServiceError,
    PreferenceWrite,
    clear_preferences,
    clear_session_context,
    create_or_update_preference,
    delete_preference,
    list_preferences,
    record_rejected_product,
    record_viewed_product,
    set_memory_enabled,
)

router = APIRouter(prefix="/memory", tags=["memory"])


class ProductMemoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=200)
    product_id: str = Field(min_length=1, max_length=128)
    customer_id: str | None = Field(default=None, max_length=200)


class MemoryToggleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(min_length=1, max_length=200)
    memory_enabled: bool


def _as_app_error(exc: MemoryServiceError) -> ScoutAppError:
    status = 404 if exc.error_type == "not_found" else 409 if exc.error_type == "memory_disabled" else 400
    return ScoutAppError(exc.message, status_code=status, code=exc.error_type.upper())


@router.get("/preferences", response_model=List[DurablePreferenceRecord])
def get_preferences(customer_id: str = Query(min_length=1, max_length=200)) -> List[DurablePreferenceRecord]:
    return list_preferences(customer_id)


@router.post("/preferences", response_model=DurablePreferenceRecord)
def upsert_preference(request: PreferenceWrite) -> DurablePreferenceRecord:
    try:
        return create_or_update_preference(request)
    except (MemoryServiceError, ValueError) as exc:
        if isinstance(exc, MemoryServiceError):
            raise _as_app_error(exc) from exc
        raise ScoutAppError("Invalid memory preference.", status_code=400, code="VALIDATION_ERROR") from exc


@router.delete("/preferences/{preference_id}", response_model=dict)
def remove_preference(preference_id: str, customer_id: str = Query(min_length=1, max_length=200)) -> dict:
    try:
        delete_preference(customer_id, preference_id)
    except MemoryServiceError as exc:
        raise _as_app_error(exc) from exc
    return {"deleted": True}


@router.delete("/preferences", response_model=dict)
def clear_all_preferences(customer_id: str = Query(min_length=1, max_length=200)) -> dict:
    return {"deleted_count": clear_preferences(customer_id)}


@router.post("/controls", response_model=MemoryControls)
def update_memory_controls(request: MemoryToggleRequest) -> MemoryControls:
    try:
        return set_memory_enabled(request.customer_id, request.memory_enabled)
    except MemoryServiceError as exc:
        raise _as_app_error(exc) from exc


@router.post("/session/viewed", response_model=SessionMemoryRecord)
def viewed_product(request: ProductMemoryEvent) -> SessionMemoryRecord:
    return record_viewed_product(request.session_id, request.product_id, request.customer_id)


@router.post("/session/rejected", response_model=SessionMemoryRecord)
def rejected_product(request: ProductMemoryEvent) -> SessionMemoryRecord:
    return record_rejected_product(request.session_id, request.product_id, request.customer_id)


@router.delete("/session/{session_id}", response_model=dict)
def clear_session_memory(session_id: str) -> dict:
    clear_session_context(session_id)
    return {"cleared": True}
