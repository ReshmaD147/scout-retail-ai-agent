"""Explicit confirmation endpoints for protected customer actions."""

from fastapi import APIRouter

from scout.api.exceptions import ScoutAppError
from scout.services.protected_action_service import (
    ProtectedActionDecisionRequest,
    ProtectedActionError,
    ProtectedActionProposal,
    ProtectedActionProposalRequest,
    ProtectedActionResult,
    decide_confirmation,
    propose_action,
)

router = APIRouter(prefix="/protected-actions", tags=["protected-actions"])

_ERROR_STATUS = {
    "validation_error": 400,
    "order_not_found": 404,
    "checkout_not_found": 404,
    "confirmation_not_found": 404,
    "authorization_failed": 403,
    "ineligible_action": 409,
    "confirmation_consumed": 409,
    "payload_hash_mismatch": 409,
    "checkout_not_confirmable": 409,
    "payment_provider_unavailable": 400,
    "stripe_configuration_error": 500,
    "stripe_unavailable": 500,
    "payment_intent_failed": 502,
    "execution_failed": 500,
}


def _as_app_error(exc: ProtectedActionError) -> ScoutAppError:
    return ScoutAppError(
        exc.message,
        status_code=_ERROR_STATUS.get(exc.error_type, 400),
        code=exc.error_type.upper(),
    )


@router.post("/proposals", response_model=ProtectedActionProposal)
def create_protected_action_proposal(request: ProtectedActionProposalRequest) -> ProtectedActionProposal:
    try:
        return propose_action(request)
    except ProtectedActionError as exc:
        raise _as_app_error(exc) from exc


@router.post("/confirm", response_model=ProtectedActionResult)
def confirm_protected_action(request: ProtectedActionDecisionRequest) -> ProtectedActionResult:
    try:
        return decide_confirmation(request)
    except ProtectedActionError as exc:
        raise _as_app_error(exc) from exc
