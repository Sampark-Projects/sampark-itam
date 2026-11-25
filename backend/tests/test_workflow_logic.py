"""Pure tests for the lifecycle workflow rules (no database)."""
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.services import workflow_logic as wl


def step(**kw):
    base = dict(position=1, state="pending", required_fields=[], requires_document=False,
                requires_comment=False, confirm_statement=None, step_type="task", role_id=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_definition_is_cleaned_and_numbered():
    role = uuid.uuid4()
    out = wl.clean_definition([
        {"name": "  Receive   and verify ", "required_fields": ["serial_number", "serial_number", "model"]},
        {"name": "Sign off", "step_type": "approval", "role_id": role, "confirm_statement": " I accept ",
         "requires_comment": 1, "description": ""},
    ])
    assert [s["position"] for s in out] == [1, 2]
    assert out[0]["name"] == "Receive and verify"
    assert out[0]["required_fields"] == ["serial_number", "model"]
    assert out[0]["step_type"] == "task"
    assert out[1]["role_id"] == role and out[1]["confirm_statement"] == "I accept"
    assert out[1]["requires_comment"] is True and out[1]["description"] is None


@pytest.mark.parametrize("bad", [
    None, [], "x", [1], [{"name": ""}], [{"name": "a", "step_type": "magic"}],
    [{"name": "a", "required_fields": ["nope"]}], [{"name": "a", "required_fields": "tag"}],
    [{"name": "x" * 101}], [{"name": "a", "confirm_statement": "x" * 256}],
    [{"name": f"s{i}"} for i in range(16)],
])
def test_bad_definitions_are_rejected(bad):
    with pytest.raises(wl.WorkflowInputError):
        wl.clean_definition(bad)


def test_blank_values():
    assert wl.is_blank(None) and wl.is_blank("  ")
    assert not wl.is_blank(0) and not wl.is_blank(False) and not wl.is_blank(date(2026, 1, 1)) and not wl.is_blank("x")


def test_blockers_list_missing_fields_and_documents():
    s = step(required_fields=["serial_number", "purchase_cost", "model"], requires_document=True)
    values = {"serial_number": "SN1", "purchase_cost": 0, "model": " "}
    assert wl.step_blockers(s, values, 0) == ["field:model", "document"]
    assert wl.step_blockers(s, {**values, "model": "S7"}, 1) == []


def test_input_problems():
    s = step(requires_comment=True, confirm_statement="Data wiped")
    assert wl.input_problems(s, None, False) == ["comment", "confirm"]
    assert wl.input_problems(s, "NIST 800-88", True) == []
    assert wl.input_problems(step(), None, False) == []


def test_who_can_act():
    role, other = uuid.uuid4(), uuid.uuid4()
    assert wl.can_act(other, None, False) == (True, False)       # no role: anyone
    assert wl.can_act(role, role, False) == (True, False)
    assert wl.can_act(other, role, False) == (False, False)
    assert wl.can_act(other, role, True) == (True, True)         # administrator override
    assert wl.can_act(None, role, False) == (False, False)


def test_self_approval():
    me, you = uuid.uuid4(), uuid.uuid4()
    assert wl.self_approval_blocked("approval", me, me, False)
    assert not wl.self_approval_blocked("approval", me, you, False)
    assert not wl.self_approval_blocked("approval", me, me, True)
    assert not wl.self_approval_blocked("task", me, me, False)
    assert not wl.self_approval_blocked("approval", None, me, False)


def test_current_step_is_the_first_pending_by_position():
    steps = [step(position=3), step(position=1, state="done"), step(position=2)]
    assert wl.current_step(steps).position == 2
    assert wl.current_step([step(position=1, state="done")]) is None


def test_a_step_can_require_a_document_of_one_category():
    s = step(requires_document=True, document_category="disposal")
    assert wl.step_blockers(s, {}, {}) == ["document:disposal"]
    assert wl.step_blockers(s, {}, {"manual": 2}) == ["document:disposal"]  # other categories do not count
    assert wl.step_blockers(s, {}, {"disposal": 1}) == []
    any_doc = step(requires_document=True)
    assert wl.step_blockers(any_doc, {}, {None: 1}) == []
    assert wl.step_blockers(any_doc, {}, {}) == ["document"]


def test_document_category_is_validated_and_dropped_without_a_document():
    out = wl.clean_definition([{"name": "Dispose", "requires_document": True, "document_category": "disposal"},
                               {"name": "Note", "document_category": "disposal"}])
    assert out[0]["document_category"] == "disposal" and out[1]["document_category"] is None
    with pytest.raises(wl.WorkflowInputError):
        wl.clean_definition([{"name": "x", "requires_document": True, "document_category": "nope"}])
    assert "network_settings" in wl.REQUIRED_FIELD_CHOICES and "config_baseline" in wl.REQUIRED_FIELD_CHOICES
