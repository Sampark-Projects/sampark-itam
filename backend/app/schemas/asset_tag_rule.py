import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services import tag_standard


class AssetTagRuleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    pattern: str = Field(..., description="e.g. DEW-{SITE}-PLC-{SEQ:4}")
    asset_type_id: Optional[uuid.UUID] = Field(None, description="Empty = every asset type")
    site_id: Optional[uuid.UUID] = Field(None, description="Empty = every site")
    is_active: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("pattern", mode="before")
    @classmethod
    def _check_pattern(cls, v):
        try:
            return tag_standard.check_pattern(v)
        except tag_standard.PatternError as exc:
            raise ValueError(str(exc))


class AssetTagRuleCreate(AssetTagRuleBase):
    # first number to hand out (e.g. continue an existing series)
    next_seq: int = Field(1, ge=1, le=999999999)


class AssetTagRuleUpdate(AssetTagRuleBase):
    next_seq: Optional[int] = Field(None, ge=1, le=999999999)


class AssetTagRule(AssetTagRuleBase):
    id: uuid.UUID
    next_seq: int
    created_at: Optional[datetime] = None
    example: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
