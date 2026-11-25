# backend/schemas/asset_type.py

import re
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Any, Dict, List, Literal, Optional
from datetime import datetime
import uuid

FIELD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
MAX_FIELDS_PER_TYPE = 40
MAX_SELECT_OPTIONS = 50


class AssetFieldDef(BaseModel):
    """One type-specific field. Its value is stored in the asset custom_fields under `key`."""

    key: str = Field(..., description="Stable machine name: lower-case letters, digits, underscore")
    label: str = Field(..., min_length=1, max_length=100)
    type: Literal["text", "number", "date", "select", "boolean", "url"] = "text"
    required: bool = False
    options: List[str] = Field(default_factory=list, description="Choices for a select field")
    help: Optional[str] = Field(None, max_length=255)

    @field_validator("key", mode="before")
    @classmethod
    def _clean_key(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not isinstance(v, str) or not FIELD_KEY_PATTERN.match(v):
            raise ValueError("key must start with a letter and use only a-z, 0-9 and _ (max 50)")
        return v

    @field_validator("label", mode="before")
    @classmethod
    def _clean_label(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("help", mode="before")
    @classmethod
    def _blank_help(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @model_validator(mode="after")
    def _check_options(self):
        if self.type == "select":
            cleaned = []
            for o in self.options:
                o = o.strip()
                if o and o not in cleaned:
                    cleaned.append(o)
            if not cleaned:
                raise ValueError("a select field needs at least one option")
            if len(cleaned) > MAX_SELECT_OPTIONS:
                raise ValueError(f"a select field can have at most {MAX_SELECT_OPTIONS} options")
            self.options = cleaned
        else:
            self.options = []
        return self


def _validate_field_list(fields):
    if fields is None:
        return fields
    if len(fields) > MAX_FIELDS_PER_TYPE:
        raise ValueError(f"at most {MAX_FIELDS_PER_TYPE} type-specific fields")
    keys = [f.key for f in fields]
    if len(keys) != len(set(keys)):
        raise ValueError("field keys must be unique")
    return fields


class AssetTypeBase(BaseModel):
    name: str = Field(..., max_length=100, description="Asset type name")
    description: Optional[str] = Field(None, max_length=255, description="Asset type description")
    purdue_level: Optional[float] = Field(None, description="Purdue level (0-4)")  # valori 0-4, anche 1.5


class AssetTypeCreate(AssetTypeBase):
    purdue_level: Optional[float] = None
    fields_schema: Optional[List[AssetFieldDef]] = None

    _unique_keys = field_validator("fields_schema")(_validate_field_list)


class AssetTypeUpdate(AssetTypeBase):
    purdue_level: Optional[float] = None
    fields_schema: Optional[List[AssetFieldDef]] = None

    _unique_keys = field_validator("fields_schema")(_validate_field_list)


class AssetType(AssetTypeBase):
    id: uuid.UUID
    tenant_id: Optional[uuid.UUID] = None
    icon: Optional[str] = None
    color: str = "#6366f1"
    created_at: datetime
    asset_count: Optional[int] = None
    # read leniently: whatever is stored is returned as is (the write schemas above are strict)
    fields_schema: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("fields_schema", mode="before")
    @classmethod
    def _stored_schema(cls, v):
        return v if isinstance(v, list) else []

    model_config = ConfigDict(from_attributes=True)
