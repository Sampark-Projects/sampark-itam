"""API tests for the OT lifecycle modules: RBAC sections, tenant isolation, audit trail,
the workflow status gate, database tag uniqueness and the webhook address rules.

Runs on SQLite in memory with every model table, like test_api_rbac.py.
"""
import uuid
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import JSON, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers every table)
from app.crud import assets as crud_assets
from app.database import Base, get_db
from app.errors.exceptions import ErrorCodeException
from app.models import (
    Asset, AssetLifecycleRun, AssetStatus, AssetType, AuditLog, ChangeRequest, MaintenanceRecord, Role, Site,
    Tenant, User,
)
from app.routers import asset_tag_rules, changes, config_management, integrations, lifecycle, maintenance, workflows
from app.schemas import AssetCreate, AssetUpdate
from app.services import tag_rules
from app.services import webhook_service
from app.services.auth import get_current_user
from app.services.rbac_permissions import (
    ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS,
)

NEW_SECTIONS = ("lifecycle", "changes", "maintenance", "configurations", "reports")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _functions(dbapi_conn, _record):
        # PostgreSQL functions used by the code under test
        dbapi_conn.create_function("btrim", 1, lambda s: s.strip() if isinstance(s, str) else s)

    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        # same rule as the PostgreSQL index in migration asset_tag_unique (trim instead of btrim)
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_assets_tenant_tag ON assets (tenant_id, lower(trim(tag))) "
            "WHERE tag IS NOT NULL AND trim(tag) <> '' AND NOT tag_legacy_duplicate"
        )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


class World:
    """A tenant with a site, a type, statuses and one asset; users are added per test."""

    def __init__(self, db, name="T"):
        self.db = db
        self.tenant = Tenant(id=uuid.uuid4(), name=f"Tenant {name}", slug=f"t-{uuid.uuid4().hex[:8]}")
        db.add(self.tenant)
        db.flush()
        self.site = Site(id=uuid.uuid4(), tenant_id=self.tenant.id, name=f"Plant {name}", code=f"P{name}")
        self.type = AssetType(id=uuid.uuid4(), tenant_id=self.tenant.id, name="PLC")
        self.active = AssetStatus(id=uuid.uuid4(), tenant_id=self.tenant.id, name="Active")
        self.retired = AssetStatus(id=uuid.uuid4(), tenant_id=self.tenant.id, name="Retired")
        self.faulty = AssetStatus(id=uuid.uuid4(), tenant_id=self.tenant.id, name="Faulty")
        db.add_all([self.site, self.type, self.active, self.retired, self.faulty])
        db.flush()
        self.asset = Asset(id=uuid.uuid4(), tenant_id=self.tenant.id, name=f"PLC-{name}", site_id=self.site.id,
                           asset_type_id=self.type.id, status_id=self.active.id)
        db.add(self.asset)
        db.commit()

    def user(self, permissions, label="u"):
        role = Role(id=uuid.uuid4(), tenant_id=self.tenant.id, name=f"role-{label}-{uuid.uuid4().hex[:4]}",
                    permissions=dict(permissions))
        user = User(id=uuid.uuid4(), tenant_id=self.tenant.id, email=f"{label}-{uuid.uuid4().hex[:6]}@test.local",
                    password_hash="x", name=label, role_id=role.id, is_active=True)
        self.db.add_all([role, user])
        self.db.commit()
        self.db.refresh(user)
        return user


def client_for(db, user) -> TestClient:
    api = FastAPI()
    for module in (changes, maintenance, config_management, lifecycle, workflows, asset_tag_rules):
        api.include_router(module.router)
    api.include_router(integrations.webhooks)
    api.include_router(integrations.reports)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def with_levels(base, **levels):
    perms = dict(base)
    perms.update(levels)
    return perms


def new_change(client, asset_id, title="Firmware update"):
    return client.post("/changes", json={"title": title, "asset_ids": [str(asset_id)], "change_type": "firmware"})


# --- RBAC sections ----------------------------------------------------------------------------

def test_default_roles_cover_the_new_sections():
    for perms in (ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS):
        assert all(section in perms for section in NEW_SECTIONS)


@pytest.mark.parametrize("path", ["/changes", "/maintenance/parts", "/config/overview", "/lifecycle/expiring",
                                  "/workflows/tasks", "/reports/dashboard"])
def test_no_section_no_access(db, path):
    w = World(db)
    user = w.user(with_levels(ADMIN_DEFAULT_PERMISSIONS, **{s: 0 for s in NEW_SECTIONS}))
    # asset rights alone no longer open these modules
    assert client_for(db, user).get(path).status_code == 403


def test_viewer_reads_but_cannot_write(db):
    w = World(db)
    viewer = client_for(db, w.user(VIEWER_DEFAULT_PERMISSIONS))
    assert viewer.get("/changes").status_code == 200
    assert new_change(viewer, w.asset.id).status_code == 403
    assert viewer.post("/maintenance/parts", json={"name": "Fuse"}).status_code == 403
    assert viewer.get("/reports/audit-pack").status_code == 403  # exporting the register needs level 2


def test_settings_need_level_three(db):
    w = World(db)
    editor = client_for(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "editor"))
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "admin"))
    body = {"approver_role_id": None, "allow_self_approval": False, "controlled_fields": ["firmware_version"]}
    assert editor.put("/changes/settings", json=body).status_code == 403
    assert admin.put("/changes/settings", json=body).status_code == 200
    target = {"metric": "config_drift", "target_value": 0}
    assert editor.put("/reports/targets", json=target).status_code == 403
    assert admin.put("/reports/targets", json=target).status_code == 200


def test_webhooks_follow_api_keys_section(db):
    w = World(db)
    assert client_for(db, w.user(VIEWER_DEFAULT_PERMISSIONS)).get("/webhooks").status_code == 403
    assert client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS)).get("/webhooks").status_code == 200


# --- tenant isolation -------------------------------------------------------------------------

def test_other_tenant_records_are_not_found(db):
    a, b = World(db, "A"), World(db, "B")
    client_a = client_for(db, a.user(ADMIN_DEFAULT_PERMISSIONS))
    client_b = client_for(db, b.user(ADMIN_DEFAULT_PERMISSIONS))

    cr = new_change(client_b, b.asset.id).json()
    assert client_a.get(f"/changes/{cr['id']}").status_code == 404
    assert client_a.post(f"/changes/{cr['id']}/transition", json={"target": "submitted"}).status_code == 404
    # a change request cannot name another tenant's asset
    assert new_change(client_a, b.asset.id).status_code in (400, 404)

    rec = client_b.post(f"/maintenance/assets/{b.asset.id}", json={"kind": "corrective", "title": "Fix",
                                                                   "due_date": str(date.today())}).json()
    assert client_a.delete(f"/maintenance/records/{rec['id']}").status_code == 404
    assert client_a.get(f"/maintenance/assets/{b.asset.id}").status_code == 404

    art = client_b.post(f"/config/assets/{b.asset.id}/artifacts", json={"name": "Main program", "kind": "program"}).json()
    assert client_a.put(f"/config/artifacts/{art['id']}", json={"name": "x", "kind": "program"}).status_code == 404
    assert client_a.get(f"/workflows/assets/{b.asset.id}/runs").status_code == 404
    assert db.query(ChangeRequest).count() == 1 and db.query(MaintenanceRecord).count() == 1


# --- audit trail ------------------------------------------------------------------------------

def _audit(db, entity, action=None):
    q = db.query(AuditLog).filter(AuditLog.entity == entity)
    if action:
        q = q.filter(AuditLog.action == action)
    return q.all()


def test_change_request_actions_are_audited(db):
    w = World(db)
    requester = w.user(EDITOR_DEFAULT_PERMISSIONS, "req")
    approver = w.user(ADMIN_DEFAULT_PERMISSIONS, "appr")
    req, appr = client_for(db, requester), client_for(db, approver)

    cr = new_change(req, w.asset.id).json()
    assert req.post(f"/changes/{cr['id']}/transition", json={"target": "submitted"}).status_code == 200
    # separation of duties: the requester cannot approve their own request
    assert req.post(f"/changes/{cr['id']}/transition", json={"target": "approved"}).status_code == 403
    assert appr.post(f"/changes/{cr['id']}/transition", json={"target": "approved", "note": "ok"}).status_code == 200

    created = _audit(db, "ChangeRequest", "create")
    approved = _audit(db, "ChangeRequest", "approve")
    assert len(created) == 1 and created[0].user_id == requester.id
    assert len(approved) == 1 and approved[0].user_id == approver.id
    assert "approved" in approved[0].description


def test_maintenance_config_and_webhook_actions_are_audited(db, monkeypatch):
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    part = admin.post("/maintenance/parts", json={"name": "Relay", "quantity": 3}).json()
    assert admin.delete(f"/maintenance/parts/{part['id']}").status_code == 204
    art = admin.post(f"/config/assets/{w.asset.id}/artifacts", json={"name": "Drive params", "kind": "configuration"}).json()
    assert admin.delete(f"/config/artifacts/{art['id']}").status_code == 204
    assert admin.put("/reports/targets", json={"metric": "open_changes", "target_value": 5}).status_code == 200

    monkeypatch.setattr(webhook_service, "network_policy", lambda refresh=False: ([], frozenset()))
    hook = admin.post("/webhooks", json={"name": "CMDB", "url": "http://10.1.2.3/hook", "events": ["change.approved"]})
    assert hook.status_code == 200
    assert admin.post(f"/webhooks/{hook.json()['id']}/rotate-secret").status_code == 200

    assert [a.action for a in _audit(db, "SparePart")] == ["create", "delete"]
    assert [a.action for a in _audit(db, "ConfigItem")] == ["create", "delete"]
    assert len(_audit(db, "KpiTarget", "update")) == 1
    assert [a.action for a in _audit(db, "Webhook")] == ["create", "rotate_secret"]
    # the secret is never written to the audit trail
    for entry in _audit(db, "Webhook"):
        assert hook.json()["secret"] not in (entry.new_data or "")


# --- workflow status gate (H3) ----------------------------------------------------------------

def test_retired_status_only_through_the_retirement_workflow(db):
    w = World(db)
    with pytest.raises(ErrorCodeException) as exc:
        crud_assets.update_asset(db, w.asset.id, AssetUpdate(status_id=w.retired.id), w.tenant.id)
    assert exc.value.error_code == "WORKFLOW_STATUS_LOCKED"
    # an ordinary status change still works
    crud_assets.update_asset(db, w.asset.id, AssetUpdate(status_id=w.faulty.id), w.tenant.id)
    db.refresh(w.asset)
    assert w.asset.status_id == w.faulty.id


def test_status_is_locked_while_a_workflow_runs(db):
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    assert admin.post(f"/workflows/assets/{w.asset.id}/runs", json={"kind": "retirement"}).status_code == 200
    assert db.query(AssetLifecycleRun).filter(AssetLifecycleRun.status == "in_progress").count() == 1
    with pytest.raises(ErrorCodeException) as exc:
        crud_assets.update_asset(db, w.asset.id, AssetUpdate(status_id=w.faulty.id), w.tenant.id)
    assert exc.value.error_code == "WORKFLOW_STATUS_LOCKED"
    assert len(_audit(db, "LifecycleRun", "start")) == 1


def test_cannot_create_an_asset_directly_as_retired(db):
    w = World(db)
    data = AssetCreate(name="New PLC", site_id=w.site.id, asset_type_id=w.type.id, status_id=w.retired.id)
    with pytest.raises(ErrorCodeException):
        crud_assets.create_asset(db, data, w.tenant.id)


# --- tag uniqueness in the database (H4) ------------------------------------------------------

def test_database_rejects_a_duplicate_tag_the_app_check_missed(db, monkeypatch):
    w = World(db)
    crud_assets.create_asset(db, AssetCreate(name="A", tag="PLC-001", site_id=w.site.id, asset_type_id=w.type.id,
                                             status_id=w.active.id), w.tenant.id)
    # simulate two saves at the same moment: the second one's app-level check sees nothing yet
    monkeypatch.setattr(tag_rules, "tag_in_use", lambda *a, **k: False)
    with pytest.raises(ErrorCodeException) as exc:
        crud_assets.create_asset(db, AssetCreate(name="B", tag="plc-001 ", site_id=w.site.id,
                                                 asset_type_id=w.type.id, status_id=w.active.id), w.tenant.id)
    assert exc.value.status_code == 409 and exc.value.error_code == "DUPLICATE_ASSET_TAG"


def test_legacy_duplicates_keep_working_until_their_tag_changes(db):
    w = World(db)
    for name in ("L1", "L2"):
        db.add(Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, tag="WIP", site_id=w.site.id,
                     asset_type_id=w.type.id, status_id=w.active.id, tag_legacy_duplicate=True))
    db.commit()
    legacy = db.query(Asset).filter(Asset.name == "L1").one()
    crud_assets.update_asset(db, legacy.id, AssetUpdate(description="still editable"), w.tenant.id)
    crud_assets.update_asset(db, legacy.id, AssetUpdate(tag="PLC-777"), w.tenant.id)
    db.refresh(legacy)
    assert legacy.tag == "PLC-777" and legacy.tag_legacy_duplicate is False


def test_same_tag_is_allowed_in_another_tenant(db):
    a, b = World(db, "A"), World(db, "B")
    for w in (a, b):
        crud_assets.create_asset(db, AssetCreate(name="X", tag="PLC-9", site_id=w.site.id, asset_type_id=w.type.id,
                                                 status_id=w.active.id), w.tenant.id)
    assert db.query(Asset).filter(Asset.tag == "PLC-9").count() == 2


# --- webhook address rules through the API (H6) -----------------------------------------------

def test_webhook_to_internal_service_is_refused(db, monkeypatch):
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    monkeypatch.setattr(webhook_service, "network_policy", lambda refresh=False: ([], frozenset({"10.9.9.9"})))
    body = {"name": "x", "events": ["change.approved"]}
    assert admin.post("/webhooks", json={**body, "url": "http://127.0.0.1/hook"}).status_code == 400
    assert admin.post("/webhooks", json={**body, "url": "http://169.254.169.254/latest"}).status_code == 400
    assert admin.post("/webhooks", json={**body, "url": "http://10.9.9.9:5432/"}).status_code == 400
    assert admin.post("/webhooks", json={**body, "url": "http://10.1.1.1/ok"}).status_code == 200
