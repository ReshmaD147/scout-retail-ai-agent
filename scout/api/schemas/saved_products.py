"""Request schemas for deterministic Saved Products endpoints."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _optional_non_blank(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be whitespace-only")
    return stripped


class SaveProductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: Optional[str] = Field(default=None)
    customer_id: Optional[str] = Field(default=None)
    product_id: str = Field(min_length=1)

    @field_validator("session_id", "customer_id")
    @classmethod
    def _owner_not_blank(cls, value: Optional[str]) -> Optional[str]:
        return _optional_non_blank(value)

    @field_validator("product_id")
    @classmethod
    def _product_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty or whitespace-only")
        return stripped
