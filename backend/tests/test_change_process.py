"""Fuller change process: emergency changes, change board quorum, post-implementation review, e-mails."""
import uuid
from datetime import datetime, timedelta

import pytest

from app.models import AuditLog, ChangeRequest
from app.services import approval_notify
from app.services import change_logic as cl
from app.services import change_service

from tests.test_api_ot_modules import (  # noqa: F401
    ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS, World, client_for, db, new_change,
)


def _move(c, cr, target, **kw):
    return c.post(f"/changes/{cr['id']}/transition", json={"target": target, **kw})


@pytest.fixture
def mails(monkeypatch):
    sent = {"requests": [], "decisions": []}
    monkeypatch.setattr(approval_notify, "request_approval", lambda db, users, *a, **k: sent["requests"].append(([u.id for u in users], a)) or len(users))
    monkeypatch.setattr(approval_notify, "report_decision", lambda db, requester, *a, **k: sent["decisions"].append((requester.id if requester else None, a)) or 1)
    return sent


# --- pure rules -------------------------------------------------------------------------------

def test_logic_emergency_and_close_rules():
    assert not cl.can_transition("submitted", "implemented")
    assert cl.can_transition("submitted", "implemented", "emergency")
    assert not cl.can_transition("draft", "implemented", "emergency")
    assert cl.clean_required_approvals("3") == 3
    for bad in (0, 6, "x", None):
        with pytest.raises(cl.ChangeInputError):
            cl.clean_required_approvals(bad)
    assert cl.quorum_reached(2, 2) and not cl.quorum_reached(1, 2)
    with pytest.raises(cl.ChangeInputError):
        cl.check_close("normal", None, None)
    cl.check_close("normal", "successful", None)
    with pytest.raises(cl.ChangeInputError):
        cl.check_close("emergency", "successful", None)  # late approval still missing
    cl.check_close("emergency", "failed", "rejected")


def test_emergency_coverage_starts_at_submission():
    sub, imp = datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 12)
    assert cl.coverage_window(None, None, "normal", sub) is None
    assert cl.coverage_window(None, imp, "emergency", sub) == (sub, imp)
    assert cl.is_covered(datetime(2026, 1, 1, 11), [cl.coverage_window(None, imp, "emergency", sub)])


def test_late_approval_does_not_shorten_emergency_cover():
    sub, imp, late = datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 12), datetime(2026, 1, 3, 9)
    window = cl.coverage_window(late, imp, "emergency", sub)
    assert window == (sub, imp)
    assert cl.is_covered(datetime(2026, 1, 1, 11), [window])
    assert cl.coverage_window(late, imp, "normal", sub) == (late, imp)


def test_rejected_late_decision_ends_emergency_cover():
    sub, imp = datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 12)
    assert cl.coverage_window(None, imp, "emergency", sub, "rejected") is None
    assert cl.coverage_window(None, imp, "emergency", sub, "approved") == (sub, imp)


def test_late_approval_needs_the_whole_change_board(db, mails):
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "boss"))
    second = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "second"))
    req = client_for(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "req"))
    admin.put("/changes/settings", json={"required_approvals": 2, "controlled_fields": ["model"]})
    cr = req.post("/changes", json={"title": "Down", "asset_ids": [str(w.asset.id)], "urgency": "emergency"}).json()
    _move(req, cr, "submitted")
    _move(req, cr, "implemented")
    first = admin.post(f"/changes/{cr['id']}/retro-decision", json={"decision": "approved"}).json()
    assert first["retro_decision"] is None and first["retro_approvals"] == {"required": 2, "given": 1}
    assert first["can_retro_decide"] is False  # the same person cannot count twice
    assert admin.post(f"/changes/{cr['id']}/retro-decision", json={"decision": "approved"}).status_code == 409
    last = second.post(f"/changes/{cr['id']}/retro-decision", json={"decision": "approved"}).json()
    assert last["retro_decision"] == "approved"


# --- change board quorum ----------------------------------------------------------------------

def test_change_board_needs_several_distinct_approvals(db, mails):
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "boss"))
    req = client_for(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "req"))
    second = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "second"))
    assert admin.put("/changes/settings", json={"required_approvals": 2, "controlled_fields": ["model"]}).json()["required_approvals"] == 2

    cr = new_change(req, w.asset.id).json()
    assert _move(req, cr, "submitted").status_code == 200
    assert mails["requests"], "approvers are e-mailed on submit"
    first = _move(admin, cr, "approved").json()
    assert first["status"] == "submitted" and first["approvals"] == {"required": 2, "given": 1, "by": first["approvals"]["by"]}
    assert first["decided_at"] is None
    again = _move(admin, cr, "approved")
    assert again.status_code in (403, 409)  # the same person cannot count twice
    done = _move(second, cr, "approved").json()
    assert done["status"] == "approved" and done["approvals"]["given"] == 2
    assert [d[1][3] for d in mails["decisions"]] == ["approved"]
    assert db.query(AuditLog).filter(AuditLog.entity == "ChangeRequest", AuditLog.action == "approve").count() == 2


def test_one_rejection_stops_the_request_and_returning_to_draft_resets_approvals(db, mails):
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "boss"))
    second = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "second"))
    req = client_for(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "req"))
    admin.put("/changes/settings", json={"required_approvals": 2, "controlled_fields": ["model"]})
    cr = new_change(req, w.asset.id).json()
    _move(req, cr, "submitted")
    _move(admin, cr, "approved")
    assert _move(second, cr, "rejected").status_code == 400  # a reason is needed
    assert _move(second, cr, "rejected", note="not now").json()["status"] == "rejected"
    assert _move(req, cr, "draft").status_code == 200
    _move(req, cr, "submitted")
    assert admin.get(f"/changes/{cr['id']}").json()["approvals"]["given"] == 0  # a new round


# --- emergency change -------------------------------------------------------------------------

def test_emergency_change_is_implemented_first_and_approved_afterwards(db, mails):
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "boss"))
    req = client_for(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "req"))
    cr = req.post("/changes", json={"title": "Line down", "asset_ids": [str(w.asset.id)], "change_type": "program",
                                    "urgency": "emergency"}).json()
    assert cr["urgency"] == "emergency"
    assert _move(req, cr, "implemented").status_code == 409  # still a draft
    _move(req, cr, "submitted")
    done = _move(req, cr, "implemented", note="patched on site")
    assert done.status_code == 200 and done.json()["status"] == "implemented"
    # a normal change cannot skip the approval
    normal = new_change(req, w.asset.id).json()
    _move(req, normal, "submitted")
    assert _move(req, normal, "implemented").status_code == 409

    body = admin.get(f"/changes/{cr['id']}").json()
    assert body["can_retro_decide"] is True
    # review and late approval are both needed to close
    assert _move(admin, cr, "closed", review_outcome="successful").status_code == 400
    assert req.post(f"/changes/{cr['id']}/retro-decision", json={"decision": "approved"}).status_code == 403  # not own change
    ok = admin.post(f"/changes/{cr['id']}/retro-decision", json={"decision": "approved", "note": "justified"})
    assert ok.status_code == 200 and ok.json()["retro_decision"] == "approved"
    assert admin.post(f"/changes/{cr['id']}/retro-decision", json={"decision": "approved"}).status_code == 409  # once
    assert _move(admin, cr, "closed").status_code == 400  # the review outcome is missing
    closed = _move(admin, cr, "closed", review_outcome="partial", note="one drive still to fix").json()
    assert closed["status"] == "closed" and closed["review_outcome"] == "partial"
    assert [d[1][3] for d in mails["decisions"]][-1].startswith("approved afterwards")


def test_normal_change_closing_needs_review_outcome(db, mails):
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "boss"))
    req = client_for(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "req"))
    cr = new_change(req, w.asset.id).json()
    _move(req, cr, "submitted")
    _move(admin, cr, "approved")
    _move(req, cr, "implemented")
    assert _move(req, cr, "closed").status_code == 400
    assert _move(req, cr, "closed", review_outcome="successful").json()["review_outcome"] == "successful"


def test_edits_during_onboarding_are_not_flagged_but_later_edits_are(db):
    from app.models import AssetLifecycleRun
    w = World(db)
    admin_user = w.user(ADMIN_DEFAULT_PERMISSIONS, "boss")
    now = datetime.utcnow()

    def edit_log(at):
        db.add(AuditLog(tenant_id=w.tenant.id, user_id=admin_user.id, action="update", entity="Asset", entity_id=w.asset.id,
                        timestamp=at, old_data={"location_id": None}, new_data={"location_id": "rack-1"}, description="edit"))

    run = AssetLifecycleRun(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=w.asset.id, kind="onboarding",
                            workflow_name="Onboarding", status="completed", started_by=admin_user.id,
                            started_at=now - timedelta(hours=5), finished_at=now - timedelta(hours=1))
    db.add(run)
    db.add(AuditLog(tenant_id=w.tenant.id, user_id=admin_user.id, action="start", entity="LifecycleRun", entity_id=run.id,
                    timestamp=now - timedelta(hours=5), description="start"))
    edit_log(now - timedelta(hours=3))   # while the onboarding ran
    edit_log(now - timedelta(minutes=10))  # after it finished
    edit_log(now - timedelta(hours=8))   # before it started
    db.commit()
    items = change_service.unapproved_changes(db, w.tenant.id, 30)["items"]
    assert len(items) == 2  # only the edit during onboarding is covered


def test_unapproved_report_treats_open_emergency_change_as_cover(db, mails):
    w = World(db)
    req = client_for(db, w.user(EDITOR_DEFAULT_PERMISSIONS, "req"))
    cr = req.post("/changes", json={"title": "Fix", "asset_ids": [str(w.asset.id)], "urgency": "emergency"}).json()
    _move(req, cr, "submitted")
    row = db.query(ChangeRequest).filter(ChangeRequest.id == uuid.UUID(cr["id"])).one()
    assert row.submitted_at is not None and row.decided_at is None
    windows = [cl.coverage_window(row.decided_at, row.implemented_at, row.urgency, row.submitted_at)]
    assert cl.is_covered(datetime.utcnow() + timedelta(minutes=1), windows)
