"""API tests for requirement gaps batch 2: purchase requests and receiving, maintenance plans and
overdue alerts, firmware upgrades, software inventory, end of life in the risk score."""
import uuid
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import (
    Asset, AssetSoftware, Manufacturer, MaintenancePlan, MaintenanceRecord, VendorLifecycleEntry,
)
from app.routers import asset_software, maintenance, procurement
from app.services import maintenance_service as ms
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS
from app.services.risk_scoring import CompositeRiskScoringEngine

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)


def client(db, user) -> TestClient:
    api = FastAPI()
    for module in (procurement, maintenance, asset_software):
        api.include_router(module.router)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def _maker(db, w, name="Siemens"):
    m = Manufacturer(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name)
    db.add(m)
    db.commit()
    return m


def _order(c, w, maker, quantity=1):
    return c.post("/procurement/orders", json={
        "title": "Spare PLC CPUs", "justification": "Line 3 has no spare CPU", "specification": "S7-1500, 2 MB",
        "currency": "INR", "lines": [{"asset_type_id": str(w.type.id), "manufacturer_id": str(maker.id),
                                      "model": "S7-1500", "quantity": quantity, "unit_cost": 120000}],
    }).json()


# --- plan and procure -------------------------------------------------------------------------

def test_purchase_request_flow_with_separation_of_duties(db):
    w = World(db)
    maker = _maker(db, w)
    req = client(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "engineer"))
    boss = client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "manager"))
    order = _order(req, w, maker, quantity=2)
    assert order["code"] == "PR-0001" and order["status"] == "draft" and order["total"] == 240000.0
    oid = order["id"]
    move = lambda c, target, **kw: c.post(f"/procurement/orders/{oid}/transition", json={"target": target, **kw})

    assert move(req, "submitted").status_code == 200
    assert move(req, "approved").status_code == 409            # an editor cannot approve
    assert move(boss, "rejected").status_code == 409            # a rejection needs a reason
    assert move(boss, "approved", note="ok").status_code == 200
    assert move(req, "ordered").status_code == 409              # needs the PO number
    assert move(req, "ordered", po_number="4500012345").json()["po_number"] == "4500012345"
    assert [a.action for a in _audit(db, "PurchaseOrder")] == ["create", "update", "approve", "update"]


def test_requester_cannot_approve_even_as_admin(db):
    w = World(db)
    boss = client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "manager"))
    order = _order(boss, w, _maker(db, w))
    boss.post(f"/procurement/orders/{order['id']}/transition", json={"target": "submitted"})
    r = boss.post(f"/procurement/orders/{order['id']}/transition", json={"target": "approved"})
    assert r.status_code == 409 and "own request" in r.json()["detail"]


def test_viewer_cannot_raise_a_request(db):
    w = World(db)
    viewer = client(db, w.user(VIEWER_DEFAULT_PERMISSIONS))
    assert viewer.get("/procurement/orders").status_code == 200
    assert viewer.post("/procurement/orders", json={"title": "x", "lines": []}).status_code == 403


def _approved_order(db, w, maker, quantity=1):
    req = client(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "engineer"))
    boss = client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "manager"))
    order = _order(req, w, maker, quantity)
    req.post(f"/procurement/orders/{order['id']}/transition", json={"target": "submitted"})
    boss.post(f"/procurement/orders/{order['id']}/transition", json={"target": "approved"})
    req.post(f"/procurement/orders/{order['id']}/transition", json={"target": "ordered", "po_number": "4500000001"})
    return req, order


def test_delivery_is_validated_against_the_order(db):
    w = World(db)
    maker = _maker(db, w)
    req, order = _approved_order(db, w, maker, quantity=1)
    line = order["lines"][0]["id"]

    w.asset.manufacturer_id, w.asset.model = maker.id, "S7-1200"  # the wrong model arrived
    db.commit()
    assert req.get(f"/procurement/lines/{line}/check", params={"asset_id": str(w.asset.id)}).json()["mismatches"] == ["model"]
    refused = req.post(f"/procurement/lines/{line}/receive", json={"asset_id": str(w.asset.id)})
    assert refused.status_code == 409 and "mismatch:model" in refused.json()["detail"]
    # accepted on purpose, with the reason recorded
    ok = req.post(f"/procurement/lines/{line}/receive",
                  json={"asset_id": str(w.asset.id), "accept_mismatch": True, "note": "Vendor shipped the newer model"})
    assert ok.status_code == 200 and ok.json()["mismatches"] == ["model"]
    db.refresh(w.asset)
    assert w.asset.purchase_order_line_id is not None
    assert w.asset.purchase_order_number == "4500000001" and w.asset.requisition_number == "PR-0001"
    assert float(w.asset.purchase_cost) == 120000 and w.asset.received_date == date.today()

    # the line was for one unit: a second asset is refused for quantity
    second = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name="PLC 2", site_id=w.site.id, asset_type_id=w.type.id,
                   status_id=w.active.id, manufacturer_id=maker.id, model="S7-1500")
    db.add(second)
    db.commit()
    assert "mismatch:quantity" in req.post(f"/procurement/lines/{line}/receive", json={"asset_id": str(second.id)}).json()["detail"]
    assert len(_audit(db, "Asset", "receive")) == 1

    from app.services import workflow_service as wsvc
    assert wsvc.asset_values(w.asset, db)["order_match"] is True
    assert wsvc.asset_values(second, db)["order_match"] is None


def test_a_draft_cannot_receive_deliveries(db):
    w = World(db)
    maker = _maker(db, w)
    c = client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    order = _order(c, w, maker)
    r = c.post(f"/procurement/lines/{order['lines'][0]['id']}/receive", json={"asset_id": str(w.asset.id)})
    assert r.status_code == 409


# --- maintenance plans ------------------------------------------------------------------------

def test_plan_creates_tasks_and_moves_on_after_completion(db):
    w = World(db)
    c = client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    due = date.today() + timedelta(days=10)
    plan = c.post(f"/maintenance/assets/{w.asset.id}/plans", json={
        "title": "Quarterly PLC check", "interval_days": 90, "lead_days": 14, "next_due_date": str(due)}).json()
    assert plan["open_task_id"] is not None  # due within the lead time: the first task exists at once
    assert c.post("/maintenance/plans/run").json()["tasks_created"] == 0  # no second task while one is open

    task = db.query(MaintenanceRecord).filter(MaintenanceRecord.plan_id == uuid.UUID(plan["id"])).one()
    done = c.post(f"/maintenance/records/{task.id}/complete", json={"performed_on": str(date.today())})
    assert done.status_code == 200
    db.expire_all()
    assert db.query(MaintenancePlan).one().next_due_date == date.today() + timedelta(days=90)
    assert len(_audit(db, "MaintenancePlan", "create")) == 1


def test_overdue_tasks_alert_once(db, monkeypatch):
    w = World(db)
    db.add(MaintenanceRecord(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=w.asset.id, kind="preventive",
                             status="planned", title="Grease the robot", due_date=date.today() - timedelta(days=3)))
    db.commit()
    from app.services import lifecycle_service
    recipient = w.user(VIEWER_DEFAULT_PERMISSIONS, "owner")
    monkeypatch.setattr(lifecycle_service, "alert_recipients", lambda db, asset: [recipient])
    sent = []
    from app.services import notification_service
    monkeypatch.setattr(notification_service.NotificationService, "send_notification",
                        staticmethod(lambda db, user_id, code, ctx: sent.append((code, ctx["days_overdue"])) or True))
    first = ms.run_maintenance_plans(db, w.tenant.id)
    assert first["overdue"] == 1 and first["sent"] == 1 and sent == [("maintenance_overdue", 3)]
    assert ms.run_maintenance_plans(db, w.tenant.id)["overdue"] == 0  # not sent twice


# --- firmware upgrades ------------------------------------------------------------------------

def test_firmware_upgrade_updates_the_asset(db):
    w = World(db)
    w.asset.firmware_version = "V2.8"
    db.commit()
    eng = client(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "engineer"))
    task = eng.post(f"/maintenance/assets/{w.asset.id}", json={
        "kind": "upgrade", "title": "Firmware V2.9", "due_date": str(date.today()), "to_version": "V2.9"}).json()
    assert task["from_version"] == "V2.8"
    assert eng.post(f"/maintenance/records/{task['id']}/complete", json={"performed_on": str(date.today())}).status_code == 200
    db.refresh(w.asset)
    assert w.asset.firmware_version == "V2.9"
    entry = [a for a in _audit(db, "Asset", "update") if "Firmware upgraded" in (a.description or "")]
    assert len(entry) == 1


# --- software inventory -----------------------------------------------------------------------

def test_software_inventory(db):
    a, b = World(db, "A"), World(db, "B")
    c = client(db, a.user(ADMIN_DEFAULT_PERMISSIONS))
    item = c.post(f"/assets/{a.asset.id}/software", json={"kind": "os", "name": "Windows 10 IoT", "version": "21H2"}).json()
    assert c.get(f"/assets/{a.asset.id}/software").json()[0]["name"] == "Windows 10 IoT"
    assert c.put(f"/assets/{a.asset.id}/software/{item['id']}", json={"kind": "os", "name": "Windows 10 IoT",
                                                                      "version": "22H2"}).json()["version"] == "22H2"
    assert c.get(f"/assets/{b.asset.id}/software").status_code == 404  # another tenant
    assert client(db, a.user(VIEWER_DEFAULT_PERMISSIONS)).post(f"/assets/{a.asset.id}/software", json={"name": "x"}).status_code == 403
    assert c.delete(f"/assets/{a.asset.id}/software/{item['id']}").status_code == 204
    assert db.query(AssetSoftware).count() == 0
    assert [x.action for x in _audit(db, "AssetSoftware")] == ["create", "update", "delete"]


# --- end of life in the risk score ------------------------------------------------------------

def test_end_of_life_raises_the_risk_score(db):
    w = World(db)
    maker = _maker(db, w)
    w.asset.business_criticality, w.asset.manufacturer_id, w.asset.model = "high", maker.id, "S7-300"
    db.commit()
    engine = CompositeRiskScoringEngine()
    engine._vendor_cache.clear()
    before = engine.calculate(w.asset, db=db)
    db.add(VendorLifecycleEntry(id=uuid.uuid4(), tenant_id=w.tenant.id, manufacturer_name="Siemens",
                                model_pattern="S7-300", end_of_support_date=date(2023, 10, 1)))
    w.asset.support_expiry_date = date.today() - timedelta(days=1)
    db.commit()
    engine._vendor_cache.clear()
    after = engine.calculate(w.asset, db=db)
    assert after["vulnerability"]["score"] == before["vulnerability"]["score"] + 3
    assert after["final_score"] > before["final_score"]
    assert any("end of support" in line for line in after["vulnerability"]["breakdown"])


def test_purchase_order_document_upload_download_replace_remove(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # files are stored under ./uploads
    w, other = World(db), World(db, "B")
    maker = _maker(db, w)
    req = client(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "engineer"))
    boss = client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "manager"))
    order = _order(req, w, maker)
    oid, pdf = order["id"], b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    files = lambda name, data=pdf, mime="application/pdf": {"file": (name, data, mime)}

    # a draft cannot take the document yet
    assert req.post(f"/procurement/orders/{oid}/po-file", files=files("po.pdf")).status_code == 409
    req.post(f"/procurement/orders/{oid}/transition", json={"target": "submitted"})
    boss.post(f"/procurement/orders/{oid}/transition", json={"target": "approved"})
    detail = req.get(f"/procurement/orders/{oid}").json()
    assert detail["po_file"] is None and detail["can_attach_po"] is True

    # wrong type is refused
    assert req.post(f"/procurement/orders/{oid}/po-file", files=files("x.exe", b"MZ\x90\x00", "application/x-msdownload")).status_code == 400
    assert req.post(f"/procurement/orders/{oid}/po-file", files=files("fake.pdf", b"not a pdf at all")).status_code == 400

    up = req.post(f"/procurement/orders/{oid}/po-file", files=files("../../evil/PO 4500.pdf"))
    assert up.status_code == 200 and up.json()["po_file"]["name"] == "PO 4500.pdf" and up.json()["po_file"]["size"] == len(pdf)
    stored = list((tmp_path / "uploads").rglob("*.pdf"))
    assert len(stored) == 1 and str(w.tenant.id) in str(stored[0])
    assert req.get(f"/procurement/orders/{oid}/po-file").content == pdf

    # ordering keeps the document; replacing removes the old file from disk
    req.post(f"/procurement/orders/{oid}/transition", json={"target": "ordered", "po_number": "4500000001"})
    again = req.post(f"/procurement/orders/{oid}/po-file", files=files("PO v2.pdf"))
    assert again.json()["po_file"]["name"] == "PO v2.pdf"
    assert len(list((tmp_path / "uploads").rglob("*.pdf"))) == 1

    # another tenant cannot see it
    stranger = client(db, other.user(EDITOR_DEFAULT_PERMISSIONS, "outsider"))
    assert stranger.get(f"/procurement/orders/{oid}/po-file").status_code in (403, 404)

    assert req.delete(f"/procurement/orders/{oid}/po-file").status_code == 403  # removing needs level 3
    gone = boss.delete(f"/procurement/orders/{oid}/po-file")
    assert gone.status_code == 200 and gone.json()["po_file"] is None
    assert list((tmp_path / "uploads").rglob("*.pdf")) == []
    assert req.get(f"/procurement/orders/{oid}/po-file").status_code == 404


# --- multi-level purchase approval ------------------------------------------------------------

def test_purchase_request_goes_through_every_approval_level(db):
    w = World(db)
    maker = _maker(db, w)
    editor = w.user(EDITOR_DEFAULT_PERMISSIONS, "engineer")
    manager, head = w.user(ADMIN_DEFAULT_PERMISSIONS, "manager"), w.user(ADMIN_DEFAULT_PERMISSIONS, "head")
    req, mgr, hd = client(db, editor), client(db, manager), client(db, head)

    assert req.put("/procurement/approval-levels", json={"levels": []}).status_code == 403  # level 3 only
    unknown = mgr.put("/procurement/approval-levels", json={"levels": [{"name": "Manager", "role_id": str(uuid.uuid4())}]})
    assert unknown.status_code == 400
    saved = mgr.put("/procurement/approval-levels", json={"levels": [
        {"name": "Manager", "role_id": str(manager.role_id)}, {"name": "Plant head", "role_id": str(head.role_id)}]})
    assert saved.status_code == 200 and [l["role_name"] is not None for l in saved.json()["levels"]] == [True, True]
    assert [l["name"] for l in req.get("/procurement/approval-levels").json()["levels"]] == ["Manager", "Plant head"]

    order = _order(req, w, maker)
    oid = order["id"]
    move = lambda c, target, **kw: c.post(f"/procurement/orders/{oid}/transition", json={"target": target, **kw})
    assert move(req, "submitted").status_code == 200
    state = req.get(f"/procurement/orders/{oid}").json()
    assert [l["state"] for l in state["approval"]["levels"]] == ["waiting", "pending"] and state["approval"]["current_level"] == 1
    assert state["allowed_targets"] == ["draft", "cancelled"]  # the requester decides nothing

    # level 2 cannot jump the queue, and level 1 cannot be decided by the wrong role
    assert move(hd, "approved").status_code == 409
    assert "approved" not in hd.get(f"/procurement/orders/{oid}").json()["allowed_targets"]
    first = move(mgr, "approved", note="Budget ok")
    assert first.status_code == 200 and first.json()["status"] == "submitted"
    assert [l["state"] for l in first.json()["approval"]["levels"]] == ["approved", "waiting"]
    assert first.json()["approval"]["levels"][0]["by"] and first.json()["approval"]["levels"][0]["note"] == "Budget ok"
    assert first.json()["decided_by"] is None  # not decided yet
    assert move(mgr, "approved").status_code == 409  # one person cannot approve two levels
    final = move(hd, "approved")
    assert final.status_code == 200 and final.json()["status"] == "approved" and final.json()["decided_by"]
    assert final.json()["approval"]["current_level"] is None
    assert req.post(f"/procurement/orders/{oid}/po-file", files={"file": ("po.pdf", b"%PDF-1.4\n", "application/pdf")}).status_code == 200

    # a rejection at any level ends the request
    other = _order(req, w, maker)["id"]
    send = lambda c, target, **kw: c.post(f"/procurement/orders/{other}/transition", json={"target": target, **kw})
    send(req, "submitted")
    send(mgr, "approved")
    assert send(hd, "rejected").status_code == 409  # a reason is needed
    rejected = send(hd, "rejected", note="Over budget")
    assert rejected.json()["status"] == "rejected"
    assert [l["state"] for l in rejected.json()["approval"]["levels"]] == ["approved", "rejected"]


def test_resubmitting_starts_the_approval_again_with_the_current_levels(db):
    w = World(db)
    maker = _maker(db, w)
    req = client(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "engineer"))
    boss = client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "manager"))
    oid = _order(req, w, maker)["id"]
    move = lambda c, target, **kw: c.post(f"/procurement/orders/{oid}/transition", json={"target": target, **kw})
    move(req, "submitted")  # no levels set: one level, any approver
    assert len(req.get(f"/procurement/orders/{oid}").json()["approval"]["levels"]) == 1
    boss.put("/procurement/approval-levels", json={"levels": [{"name": "A"}, {"name": "B"}]})
    move(req, "draft")
    assert req.get(f"/procurement/orders/{oid}").json()["approval"] is None
    move(req, "submitted")
    assert [l["name"] for l in req.get(f"/procurement/orders/{oid}").json()["approval"]["levels"]] == ["A", "B"]
    assert move(boss, "approved").json()["status"] == "submitted"  # level 1 of 2
