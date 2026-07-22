"""Public API contracts for Step 16.5 external merchant fallback."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scout.mcp.schemas import ExternalOfferSummary


class ExternalOfferSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_text: str = Field(min_length=1, max_length=2000)
    category: Optional[str] = None
    max_price: Optional[float] = Field(default=None, ge=0)
    limit: int = Field(default=3, ge=1, le=20)

    @field_validator("query_text")
    @classmethod
    def _query_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query_text must not be blank")
        return stripped


class ExternalOfferSearchResponse(BaseModel):
    offers: List[ExternalOfferSummary]
    count: int


class AffiliateClickResponse(BaseModel):
    click_id: str
    offer_id: str
    redirect_url: str
