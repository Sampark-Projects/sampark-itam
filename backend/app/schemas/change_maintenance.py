import uuid
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services import change_logic as cl


def _blank_to_none(v):
    if isinstance(v, str):
        return v.strip() or None
    return v


class ChangeSettingsIn(BaseModel):
    approver_role_id: Optional[uuid.UUID] = None
    allow_self_approval: bool = False
    controlled_fields: List[str] = Field(default_factory=lambda: list(cl.DEFAULT_CONTROLLED_FIELDS))
    required_approvals: int = Field(1, ge=1, le=cl.MAX_REQUIRED_APPROVALS)  # change board quorum

    @field_validator("controlled_fields", mode="before")
    @classmethod
    def _check_fields(cls, v):
        try:
            return cl.clean_controlled_fields(v)
        except cl.ChangeInputError as exc:
            raise ValueError(str(exc))


class ChangeRequestIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=5000)
    reason: Optional[str] = Field(None, max_length=5000)
    change_type: Literal["configuration", "firmware", "program", "hardware", "network", "other"] = "configuration"
    risk: Literal["low", "medium", "high"] = "low"
    urgency: Literal["normal", "emergency"] = "normal"
    planned_start: Optional[date] = None
    planned_end: Optional[date] = None
    asset_ids: List[uuid.UUID] = Field(..., min_length=1, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def _trim_title(cls, v):
        return " ".join(v.split()) if isinstance(v, str) else v

    @field_validator("description", "reason", mode="before")
    @classmethod
    def _blank(cls, v):
        return _blank_to_none(v)

    @model_validator(mode="after")
    def _dates(self):
        if self.planned_start and self.planned_end and self.planned_end < self.planned_start:
            raise ValueError("planned end is before planned start")
        return self


class ChangeTransitionIn(BaseModel):
    target: Literal["submitted", "approved", "rejected", "draft", "implemented", "closed", "cancelled"]
    note: Optional[str] = Field(None, max_length=5000)
    review_outcome: Optional[Literal["successful", "partial", "failed", "rolled_back"]] = None  # needed to close

    @field_validator("note", mode="before")
    @classmethod
    def _blank(cls, v):
        return _blank_to_none(v)


class RetroDecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: Optional[str] = Field(None, max_length=5000)

    @field_validator("note", mode="before")
    @classmethod
    def _blank(cls, v):
        return _blank_to_none(v)


class FlagReviewIn(BaseModel):
    note: str = Field(..., min_length=3, max_length=2000)

    @field_validator("note", mode="before")
    @classmethod
    def _trim(cls, v):
        return v.strip() if isinstance(v, str) else v


class PartUse(BaseModel):
    spare_part_id: uuid.UUID
    quantity: int = Field(..., ge=1, le=100000)


class MaintenanceIn(BaseModel):
    # upgrade = firmware upgrade, patch = software / security patch: both need an approved change request
    kind: Literal["preventive", "corrective", "inspection", "upgrade", "patch"]
    title: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=5000)
    due_date: Optional[date] = None
    change_request_id: Optional[uuid.UUID] = None
    from_version: Optional[str] = Field(None, max_length=100)
    to_version: Optional[str] = Field(None, max_length=100)

    @field_validator("from_version", "to_version", mode="before")
    @classmethod
    def _versions(cls, v):
        return _blank_to_none(v.strip() if isinstance(v, str) else v)

    @field_validator("title", mode="before")
    @classmethod
    def _trim_title(cls, v):
        return " ".join(v.split()) if isinstance(v, str) else v

    @field_validator("description", mode="before")
    @classmethod
    def _blank(cls, v):
        return _blank_to_none(v)


class MaintenanceCompleteIn(BaseModel):
    performed_on: date
    performed_by: Optional[str] = Field(None, max_length=255)
    vendor: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = Field(None, max_length=5000)
    cost_amount: Optional[float] = Field(None, ge=0, le=1e12)
    cost_currency: Optional[str] = Field(None, pattern=r"^[A-Z]{3}$")
    parts: List[PartUse] = Field(default_factory=list, max_length=50)
    next_due_date: Optional[date] = None  # a preventive task schedules its next occurrence
    to_version: Optional[str] = Field(None, max_length=100)  # upgrade / patch: the version actually installed

    @field_validator("performed_by", "vendor", "notes", mode="before")
    @classmethod
    def _blank(cls, v):
        return _blank_to_none(v)

    @field_validator("cost_currency", mode="before")
    @classmethod
    def _currency(cls, v):
        if isinstance(v, str):
            v = v.strip().upper()
            return v or None
        return v

    @model_validator(mode="after")
    def _cost_needs_currency(self):
        if self.cost_amount and not self.cost_currency:
            raise ValueError("a cost needs a currency")
        return self


class MaintenancePlanIn(BaseModel):
    kind: Literal["preventive", "inspection"] = "preventive"
    title: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=5000)
    interval_days: int = Field(..., ge=1, le=3650)
    lead_days: int = Field(14, ge=0, le=365)
    next_due_date: date
    is_active: bool = True

    @field_validator("title", mode="before")
    @classmethod
    def _trim_title(cls, v):
        return " ".join(v.split()) if isinstance(v, str) else v

    @field_validator("description", mode="before")
    @classmethod
    def _blank(cls, v):
        return _blank_to_none(v)


class SparePartIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    part_number: Optional[str] = Field(None, max_length=100)
    manufacturer_name: Optional[str] = Field(None, max_length=255)
    quantity: int = Field(0, ge=0, le=10000000)
    min_quantity: int = Field(0, ge=0, le=10000000)
    storage_location: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = Field(None, max_length=2000)
    asset_ids: List[uuid.UUID] = Field(default_factory=list, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, v):
        return " ".join(v.split()) if isinstance(v, str) else v

    @field_validator("part_number", "manufacturer_name", "storage_location", "notes", mode="before")
    @classmethod
    def _blank(cls, v):
        return _blank_to_none(v)
