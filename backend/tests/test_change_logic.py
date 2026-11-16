"""Pure tests for the change request rules and unapproved-change detection."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services import change_logic as cl


def test_transitions():
    assert cl.can_transition("draft", "submitted")
    assert cl.can_transition("submitted", "approved") and cl.can_transition("submitted", "rejected")
    assert cl.can_transition("approved", "implemented") and cl.can_transition("implemented", "closed")
    assert cl.can_transition("rejected", "draft")
    assert not cl.can_transition("draft", "approved")        # cannot skip the approval
    assert not cl.can_transition("approved", "draft")
    assert not cl.can_transition("closed", "draft") and not cl.can_transition("cancelled", "draft")
    assert not cl.can_transition("nonsense", "draft")


def test_every_status_has_a_transition_entry():
    assert set(cl.TRANSITIONS) == set(cl.STATUSES)


def test_number_format():
    assert cl.format_number(7) == "CR-0007"
    assert cl.format_number(12345) == "CR-12345"


def test_controlled_fields_are_validated():
    assert cl.clean_controlled_fields(["model", "model", "firmware_version"]) == ["model", "firmware_version"]
    for bad in (None, [], "model", ["nope"]):
        with pytest.raises(cl.ChangeInputError):
            cl.clean_controlled_fields(bad)
    assert set(cl.DEFAULT_CONTROLLED_FIELDS) <= set(cl.CONTROLLED_FIELD_CHOICES)


def test_who_can_decide():
    role, other = uuid.uuid4(), uuid.uuid4()
    assert cl.can_decide(role, role, False)
    assert not cl.can_decide(other, role, False)
    assert cl.can_decide(other, role, True)           # administrator
    assert not cl.can_decide(other, None, False)      # no approver role: administrators only
    assert cl.can_decide(other, None, True)
    assert not cl.can_decide(None, role, False)


def test_self_decision():
    me, you = uuid.uuid4(), uuid.uuid4()
    assert cl.self_decision_blocked(me, me, False)
    assert not cl.self_decision_blocked(me, you, False)
    assert not cl.self_decision_blocked(me, me, True)
    assert not cl.self_decision_blocked(None, me, False)


def test_audit_json_may_be_double_encoded():
    data = {"model": "S7"}
    assert cl.load_json(data) == data
    assert cl.load_json(json.dumps(data)) == data
    assert cl.load_json(json.dumps(json.dumps(data))) == data
    assert cl.load_json("not json") == {} and cl.load_json(None) == {} and cl.load_json("[1]") == {}


def test_changed_fields_only_reports_controlled_differences():
    old = {"model": "S7-1200", "firmware_version": "1.0", "name": "A", "location_id": None, "protocols": []}
    new = {"model": "S7-1500", "firmware_version": "1.0", "name": "B", "location_id": "", "protocols": None}
    assert cl.changed_fields(old, new, cl.DEFAULT_CONTROLLED_FIELDS + ("protocols",)) == ["model"]  # name not controlled; blanks equal
    assert cl.changed_fields(json.dumps(old), json.dumps(new), ["model", "firmware_version"]) == ["model"]


def test_field_missing_from_a_snapshot_is_not_counted():
    assert cl.changed_fields({"model": "A"}, {}, ["model"]) == []
    assert cl.changed_fields({}, {"model": "A"}, ["model"]) == []


def test_utc_conversion():
    aware = datetime(2026, 3, 1, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert cl.to_naive_utc(aware) == datetime(2026, 3, 1, 6, 30)
    naive = datetime(2026, 3, 1, 6, 30)
    assert cl.to_naive_utc(naive) == naive


def test_coverage_windows():
    approved = datetime(2026, 3, 1, 9, 0)
    done = datetime(2026, 3, 1, 17, 0)
    open_window = cl.coverage_window(approved, None)
    closed_window = cl.coverage_window(approved, done)
    assert cl.coverage_window(None, None) is None
    assert cl.is_covered(datetime(2026, 3, 1, 10, 0), [open_window])
    assert cl.is_covered(datetime(2026, 4, 1), [open_window])                 # still open
    assert not cl.is_covered(datetime(2026, 3, 1, 8, 59), [open_window])      # before approval
    assert cl.is_covered(datetime(2026, 3, 1, 17, 0), [closed_window])
    assert not cl.is_covered(datetime(2026, 3, 1, 17, 1), [closed_window])    # after implementation
    assert not cl.is_covered(datetime(2026, 3, 1, 10, 0), [None, (datetime(2026, 5, 1), None)])
    assert cl.is_covered(datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc), [open_window])
