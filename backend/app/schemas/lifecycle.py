import uuid
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services import lifecycle_logic as ll


class LifecycleSettingsIn(BaseModel):
    enabled: bool = True
    lead_days: List[int] = Field(default_factory=lambda: list(ll.DEFAULT_LEAD_DAYS))

    @field_validator("lead_days", mode="before")
    @classmethod
    def _check_lead_days(cls, v):
        try:
            return ll.normalize_lead_days(v)
        except ll.LifecycleInputError as exc:
            raise ValueError(str(exc))


class LifecycleSettingsOut(LifecycleSettingsIn):
    model_config = ConfigDict(from_attributes=True)


class VendorEntryBase(BaseModel):
    manufacturer_name: str = Field(..., min_length=1, max_length=255)
    model_pattern: str = Field(..., min_length=1, max_length=100, description="Exact model, or with * and ? wildcards")
    end_of_sale_date: Optional[date] = None
    end_of_support_date: Optional[date] = None
    end_of_life_date: Optional[date] = None
    source: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator("manufacturer_name", "model_pattern", mode="before")
    @classmethod
    def _trim(cls, v):
        return " ".join(v.split()) if isinstance(v, str) else v

    @field_validator("source", "notes", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @model_validator(mode="after")
    def _needs_a_date(self):
        if not (self.end_of_sale_date or self.end_of_support_date or self.end_of_life_date):
            raise ValueError("at least one date is required")
        return self


class VendorEntryRead(VendorEntryBase):
    id: uuid.UUID
    model_config = ConfigDict(from_attributes=True)


class CostEntryIn(BaseModel):
    entry_type: Literal["maintenance", "upgrade", "licence", "other"]
    amount: float = Field(..., gt=0, le=1e12)
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    incurred_on: date
    description: Optional[str] = Field(None, max_length=255)

    @field_validator("currency", mode="before")
    @classmethod
    def _currency_upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("description", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v


class CostEntryRead(CostEntryIn):
    id: uuid.UUID
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)
