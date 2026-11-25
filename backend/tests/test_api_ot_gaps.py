"""API tests for the requirement gaps: site hierarchy, document categories, commissioning checks,
retirement archive, spare assets, and the cross-tenant asset update fix."""
import uuid
from datetime import date

import pytest

from app.crud import assets as crud_assets
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, AssetDocument, AssetInterface, AssetTagRule, ConfigArtifact, ConfigVersion, Site
from app.schemas import AssetCreate, AssetCustomFieldUpdate, AssetUpdate
from app.services import workflow_service as wsvc
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, _audit, client_for, db  # noqa: F401  (db is the fixture)


def _unit(db, w, name="Engine unit", code="ENG"):
    unit = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, code=code, parent_id=w.site.id)
    db.add(unit)
    db.commit()
    return unit


def _asset_in(db, w, site, name="Robot"):
    asset = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, site_id=site.id,
                  asset_type_id=w.type.id, status_id=w.active.id)
    db.add(asset)
    db.commit()
    return asset


# --- site hierarchy ---------------------------------------------------------------------------

def test_a_plant_filter_includes_its_units(db):
    w = World(db, "D")
    _asset_in(db, w, _unit(db, w))
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    by_plant = admin.get("/reports/dashboard", params={"site_id": str(w.site.id)}).json()
    assert by_plant["totals"]["metrics"]["assets_total"] == 2  # the plant asset and the unit asset
    assert admin.get("/reports/dashboard", params={"group_by": "plant"}).status_code == 422  # only site or area
    by_site = admin.get("/reports/dashboard", params={"group_by": "site"}).json()
    assert sorted(r["name"] for r in by_site["rows"]) == ["Engine unit", "Plant D"]


def test_a_unit_inherits_the_plant_target(db):
    w = World(db, "D")
    _asset_in(db, w, _unit(db, w))
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    admin.put("/reports/targets", json={"metric": "overdue_maintenance", "target_value": 9})
    admin.put("/reports/targets", json={"metric": "overdue_maintenance", "target_value": 3, "site_id": str(w.site.id)})
    rows = {r["name"]: r for r in admin.get("/reports/dashboard").json()["rows"]}
    assert rows["Engine unit"]["targets"]["overdue_maintenance"] == 3  # the plant target, not the tenant default


def test_a_plant_naming_rule_applies_to_its_units(db):
    w = World(db, "D")
    unit = _unit(db, w)
    db.add(AssetTagRule(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Plant rule", pattern="DW-{SEQ:3}",
                        site_id=w.site.id, next_seq=1, is_active=True))
    db.commit()
    asset = crud_assets.create_asset(db, AssetCreate(name="New", site_id=unit.id, asset_type_id=w.type.id,
                                                     status_id=w.active.id), w.tenant.id)
    assert asset.tag == "DW-001"
    # a rule on the unit itself is closer and wins
    db.add(AssetTagRule(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Unit rule", pattern="ENG-{SEQ:2}",
                        site_id=unit.id, next_seq=1, is_active=True))
    db.commit()
    asset = crud_assets.create_asset(db, AssetCreate(name="New 2", site_id=unit.id, asset_type_id=w.type.id,
                                                     status_id=w.active.id), w.tenant.id)
    assert asset.tag == "ENG-01"


# --- retirement: disposal details, category evidence, archive ---------------------------------

def test_retirement_needs_disposal_details_and_then_archives_the_record(db):
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "admin"))
    approver = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "approver"))
    run = admin.post(f"/workflows/assets/{w.asset.id}/runs", json={"kind": "retirement"}).json()
    steps = sorted(run["steps"], key=lambda s: s["position"])
    act = lambda client, i, body: client.post(f"/workflows/runs/{run['id']}/steps/{steps[i]['id']}/complete", json=body)
    assert act(approver, 0, {"comment": "approved"}).status_code == 200  # someone other than the starter
    assert act(admin, 1, {"comment": "wiped", "confirmed": True}).status_code == 200

    blocked = act(admin, 2, {"comment": "gone"})
    assert blocked.status_code == 400
    assert "field:disposal_method" in blocked.json()["detail"] and "document:disposal" in blocked.json()["detail"]

    w.asset.disposal_method, w.asset.disposal_date = "returned_to_vendor", date.today()
    db.add(AssetDocument(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=w.asset.id, name="manual.pdf",
                         file_path="x", category="manual"))
    db.commit()
    assert "document:disposal" in act(admin, 2, {"comment": "gone"}).json()["detail"]  # a manual is not evidence
    db.add(AssetDocument(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=w.asset.id, name="rma.pdf",
                         file_path="y", category="disposal"))
    db.commit()
    assert act(admin, 2, {"comment": "gone"}).status_code == 200
    assert act(admin, 3, {}).status_code == 200

    db.refresh(w.asset)
    assert w.asset.status_id == w.retired.id and w.asset.archived_at is not None
    with pytest.raises(ErrorCodeException) as exc:
        crud_assets.update_asset(db, w.asset.id, AssetUpdate(description="edit"), w.tenant.id)
    assert exc.value.error_code == "ASSET_ARCHIVED"
    assert admin.post(f"/workflows/assets/{w.asset.id}/runs", json={"kind": "onboarding"}).status_code == 409

    # an administrator can reopen the record with a reason; it is audited
    assert admin.post(f"/workflows/assets/{w.asset.id}/reopen", json={"reason": ""}).status_code == 400
    assert admin.post(f"/workflows/assets/{w.asset.id}/reopen", json={"reason": "Wrong asset retired"}).status_code == 200
    db.refresh(w.asset)
    assert w.asset.archived_at is None and len(_audit(db, "Asset", "reopen")) == 1


def test_only_level_three_can_reopen(db):
    from app.services.rbac_permissions import EDITOR_DEFAULT_PERMISSIONS
    w = World(db)
    editor = client_for(db, w.user(EDITOR_DEFAULT_PERMISSIONS))
    assert editor.post(f"/workflows/assets/{w.asset.id}/reopen", json={"reason": "please reopen"}).status_code == 403


# --- commissioning ----------------------------------------------------------------------------

def test_commissioning_checks_network_settings_and_baseline(db):
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    run = admin.post(f"/workflows/assets/{w.asset.id}/runs", json={"kind": "onboarding"}).json()
    install = sorted(run["steps"], key=lambda s: s["position"])[1]
    assert {"network_settings", "config_baseline"} <= set(install["required_fields"])

    values = wsvc.asset_values(w.asset, db)
    assert values["network_settings"] is None and values["config_baseline"] is None
    db.add(AssetInterface(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=w.asset.id, name="eth0", ip_address="10.1.1.5"))
    art = ConfigArtifact(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=w.asset.id, name="Program", kind="program")
    db.add(art)
    db.flush()
    ver = ConfigVersion(id=uuid.uuid4(), tenant_id=w.tenant.id, artifact_id=art.id, version_number=1, file_name="p.zip", file_path="p",
                        size_bytes=1, sha256="0" * 64)
    db.add(ver)
    db.flush()
    art.baseline_version_id = ver.id
    db.commit()
    values = wsvc.asset_values(w.asset, db)
    assert values["network_settings"] is True and values["config_baseline"] is True


# --- spare assets -----------------------------------------------------------------------------

def test_spare_assets_link_both_ways(db):
    a, b = World(db, "A"), World(db, "B")
    spare = _asset_in(db, a, a.site, "Spare CPU")
    admin = client_for(db, a.user(ADMIN_DEFAULT_PERMISSIONS))
    out = admin.put(f"/lifecycle/assets/{a.asset.id}/spares", json={"spare_asset_ids": [str(spare.id)]}).json()
    assert [s["name"] for s in out["spares"]] == ["Spare CPU"]
    assert [s["name"] for s in admin.get(f"/lifecycle/assets/{spare.id}/spares").json()["spare_for"]] == [a.asset.name]
    assert admin.put(f"/lifecycle/assets/{a.asset.id}/spares", json={"spare_asset_ids": [str(a.asset.id)]}).status_code == 400
    # another tenant's asset cannot be named as a spare
    assert admin.put(f"/lifecycle/assets/{a.asset.id}/spares", json={"spare_asset_ids": [str(b.asset.id)]}).status_code == 400
    assert len(_audit(db, "AssetSpares", "update")) == 1


# --- cross-tenant asset update ------------------------------------------------------------------

def test_asset_update_cannot_reach_another_tenant(db):
    a, b = World(db, "A"), World(db, "B")
    assert crud_assets.update_asset(db, b.asset.id, AssetUpdate(description="x"), a.tenant.id) is None
    assert crud_assets.update_asset_custom_fields(
        db, b.asset.id, AssetCustomFieldUpdate(custom_fields={"k": "v"}), a.tenant.id) is None
    db.refresh(b.asset)
    assert b.asset.description is None
