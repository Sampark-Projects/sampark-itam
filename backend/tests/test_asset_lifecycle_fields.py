"""Unit tests for the OT lifecycle asset fields and the OT seed data (no database needed)."""
import datetime as dt
import uuid

import pytest
from pydantic import ValidationError

from app.init_ot_lifecycle import (
    LIFECYCLE_STATUSES,
    OT_ASSET_TYPES,
    _missing,
)
from app.schemas.asset import AssetCreate, AssetUpdate


def _create(**extra):
    return AssetCreate(name="PLC-1", site_id=uuid.uuid4(), **extra)


def test_lifecycle_fields_are_all_optional():
    asset = _create()
    assert asset.safety_relevance is None
    assert asset.purchase_cost is None
    assert asset.warranty_expiry_date is None
    assert AssetUpdate().model_dump(exclude_unset=True) == {}


def test_full_lifecycle_payload_is_accepted():
    asset = _create(
        safety_relevance="safety_critical",
        requisition_number="REQ-1",
        purchase_order_number="PO-9",
        purchase_date=dt.date(2026, 1, 15),
        purchase_cost=1250.75,
        cost_currency="INR",
        warranty_expiry_date=dt.date(2028, 1, 1),
        amc_expiry_date=dt.date(2027, 1, 1),
        plant_owner="Dewas",
        amc_partner="Vendor Ltd",
    )
    assert asset.safety_relevance == "safety_critical"
    assert asset.purchase_cost == 1250.75
    assert asset.amc_expiry_date == dt.date(2027, 1, 1)


@pytest.mark.parametrize("value", ["none", "safety_related", "safety_critical"])
def test_safety_relevance_accepts_known_values(value):
    assert _create(safety_relevance=value).safety_relevance == value


@pytest.mark.parametrize("bad", [{"safety_relevance": "critical"}, {"purchase_cost": -1}, {"cost_currency": "12$"}, {"cost_currency": "RS"}])
def test_invalid_values_are_rejected(bad):
    with pytest.raises(ValidationError):
        AssetUpdate(**bad)


def test_currency_is_uppercased_and_blank_text_becomes_none():
    update = AssetUpdate(cost_currency=" inr ", purchase_order_number="   ", plant_owner="  Dewas  ")
    assert update.cost_currency == "INR"
    assert update.purchase_order_number is None
    assert update.plant_owner == "Dewas"


def test_update_only_reports_fields_that_were_sent():
    update = AssetUpdate(purchase_cost=10.0)
    assert update.model_dump(exclude_unset=True) == {"purchase_cost": 10.0}


# ---- seed data ----

def test_ot_asset_types_are_unique_and_in_purdue_range():
    names = [t["name"].lower() for t in OT_ASSET_TYPES]
    assert len(names) == len(set(names))
    assert all(0 <= t["purdue_level"] <= 3.5 for t in OT_ASSET_TYPES)
    assert all(len(t["name"]) <= 100 for t in OT_ASSET_TYPES)


def test_lifecycle_statuses_are_unique_and_fit_the_columns():
    names = [s["name"].lower() for s in LIFECYCLE_STATUSES]
    assert len(names) == len(set(names))
    assert all(len(s["name"]) <= 50 and len(s["description"]) <= 200 for s in LIFECYCLE_STATUSES)
    assert all(len(s["color"]) == 7 and s["color"].startswith("#") for s in LIFECYCLE_STATUSES)
    # no clash with the statuses every tenant already has
    assert not ({s["name"].lower() for s in LIFECYCLE_STATUSES} & {"active", "disposed", "in stock", "faulty", "in maintenance"})


def test_seed_skips_existing_names_and_aliases():
    existing = {"cnc", "drive", "switch"}
    missing = {d["name"] for d in _missing(OT_ASSET_TYPES, existing)}
    assert "CNC Controller" not in missing  # "CNC" is an alias
    assert "Drive" not in missing           # exact name exists
    assert "Managed Switch" in missing      # "Switch" is NOT an alias of it
    assert "Safety PLC" in missing
