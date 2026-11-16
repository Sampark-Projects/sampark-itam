"""Validation of the per-asset-type field definitions (asset_types.fields_schema)."""
import pytest
from pydantic import ValidationError

from app.schemas.asset_type import AssetFieldDef, AssetType, AssetTypeCreate, AssetTypeUpdate

import datetime
import uuid


def _type(fields):
    return AssetTypeCreate(name="PLC", fields_schema=fields)


def test_fields_schema_is_optional():
    assert AssetTypeCreate(name="PLC").fields_schema is None
    assert AssetTypeUpdate(name="PLC").model_dump(exclude_unset=True) == {"name": "PLC"}


def test_valid_definitions_are_accepted_and_cleaned():
    t = _type([
        {"key": "io_points", "label": " I/O points ", "type": "number", "required": True},
        {"key": "voltage", "label": "Voltage", "type": "select", "options": [" 24V ", "110V", "24V", ""]},
        {"key": "ex_rated", "label": "Ex rated", "type": "boolean", "options": ["ignored"], "help": "  "},
    ])
    first, second, third = t.fields_schema
    assert first.label == "I/O points" and first.required is True
    assert second.options == ["24V", "110V"]          # trimmed, de-duplicated, blanks dropped
    assert third.options == [] and third.help is None  # options only kept for select


@pytest.mark.parametrize("key", ["", "Io", "1abc", "a b", "a-b", "x" * 51])
def test_bad_keys_are_rejected(key):
    with pytest.raises(ValidationError):
        AssetFieldDef(key=key, label="Label")


def test_duplicate_keys_are_rejected():
    with pytest.raises(ValidationError):
        _type([{"key": "a", "label": "A"}, {"key": "a", "label": "B"}])


def test_select_needs_options():
    with pytest.raises(ValidationError):
        AssetFieldDef(key="a", label="A", type="select", options=[])


def test_unknown_type_is_rejected():
    with pytest.raises(ValidationError):
        AssetFieldDef(key="a", label="A", type="file")


def test_too_many_fields_are_rejected():
    with pytest.raises(ValidationError):
        _type([{"key": f"f{i}", "label": "F"} for i in range(41)])


def test_response_tolerates_legacy_stored_values():
    base = dict(id=uuid.uuid4(), name="PLC", created_at=datetime.datetime.utcnow())
    assert AssetType(**base, fields_schema=None).fields_schema == []
    assert AssetType(**base, fields_schema={"x": 1}).fields_schema == []
    assert AssetType(**base, fields_schema=[{"key": "a"}]).fields_schema == [{"key": "a"}]
