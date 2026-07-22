"""Health check endpoint.

Used by operators, load balancers, and (later) the React frontend to
confirm the API process is running and can serve requests.
"""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from scout.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: str
    timestamp: str
    app_name: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Report that the service is up and identify itself."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
        app_name=settings.app_name,
        version="0.1.0",
    )
