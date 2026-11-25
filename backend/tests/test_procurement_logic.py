"""Pure tests for purchase request rules, delivery checks, maintenance plan scheduling and end-of-life risk."""
from datetime import date

import pytest

from app.services import lifecycle_logic as ll
from app.services import procurement_logic as pl


def test_number_format():
    assert pl.format_number(7) == "PR-0007"


def test_requester_cannot_decide():
    assert pl.allowed_targets("submitted", is_requester=True, can_decide=True) == ["draft", "cancelled"]
    assert pl.allowed_targets("submitted", is_requester=False, can_decide=True) == ["approved", "rejected", "draft", "cancelled"]
    assert pl.allowed_targets("submitted", is_requester=False, can_decide=False) == ["draft", "cancelled"]
    with pytest.raises(pl.ProcurementInputError):
        pl.check_transition("submitted", "approved", True, True, None, 1, None)


@pytest.mark.parametrize("status,target,po,lines,note", [
    ("draft", "approved", None, 1, None),      # must be submitted first
    ("draft", "submitted", None, 0, None),     # nothing to order
    ("submitted", "rejected", None, 1, " "),   # rejection needs a reason
    ("approved", "ordered", "", 1, None),      # ordering needs the PO number
    ("closed", "draft", None, 1, None),
])
def test_bad_transitions(status, target, po, lines, note):
    with pytest.raises(pl.ProcurementInputError):
        pl.check_transition(status, target, False, True, po, lines, note)


def test_good_transitions():
    pl.check_transition("draft", "submitted", True, False, None, 2, None)
    pl.check_transition("submitted", "approved", False, True, None, 2, None)
    pl.check_transition("approved", "ordered", True, False, "4500012345", 2, None)
    pl.check_transition("ordered", "received", True, False, "4500012345", 2, None)


def test_lines_are_validated():
    out = pl.clean_lines([{"model": " S7-1500  CPU ", "quantity": 2, "unit_cost": 1500}])
    assert out[0]["model"] == "S7-1500 CPU" and out[0]["position"] == 1
    for bad in ([{"model": "x", "quantity": 0}], [{"quantity": 1}], [{"model": "x", "quantity": True}],
                [{"model": "x", "quantity": 1, "unit_cost": -1}], "x"):
        with pytest.raises(pl.ProcurementInputError):
            pl.clean_lines(bad)


def test_delivery_is_checked_against_the_line():
    line = {"asset_type_id": "plc", "manufacturer_id": "siemens", "model": "S7-1500", "quantity": 2}
    good = {"asset_type_id": "plc", "manufacturer_id": "siemens", "model": "s7-1500 "}
    assert pl.order_mismatches(line, good, 0) == []
    assert pl.order_mismatches(line, {**good, "model": "S7-1200"}, 0) == ["model"]
    assert pl.order_mismatches(line, {**good, "manufacturer_id": "abb", "asset_type_id": "hmi"}, 0) == ["type", "manufacturer"]
    assert pl.order_mismatches(line, good, 2) == ["quantity"]  # both ordered units already received
    assert pl.order_mismatches({"description": "spares", "quantity": 1}, {}, 0) == []  # empty fields are not checked


def test_total():
    assert pl.total([{"unit_cost": 10, "quantity": 3}, {"unit_cost": 2.5, "quantity": 2}]) == 35.0
    assert pl.total([{"unit_cost": None, "quantity": 1}]) is None


def test_plan_scheduling():
    assert pl.plan_task_due(date(2026, 12, 31), 14, date(2026, 12, 17), False)
    assert not pl.plan_task_due(date(2026, 12, 31), 14, date(2026, 12, 16), False)
    assert not pl.plan_task_due(date(2026, 12, 31), 14, date(2027, 1, 5), True)  # one is still open
    assert pl.next_due_after(date(2027, 1, 5), 90) == date(2027, 4, 5)


def test_end_of_life_risk_points():
    assert ll.eol_risk("obsolete", True) == (3, ["eol_obsolete", "eol_contract_expired"])
    assert ll.eol_risk("soon", False) == (1, ["eol_soon"])
    assert ll.eol_risk("later", False) == (0, [])
    assert ll.eol_risk("unknown", True) == (1, ["eol_contract_expired"])

    class A:
        support_expiry_date = date(2020, 1, 1)
        amc_expiry_date = None
        warranty_expiry_date = date(2020, 1, 1)
    assert ll.support_expired(A(), date(2026, 1, 1))
    A.support_expiry_date = date(2030, 1, 1)
    assert not ll.support_expired(A(), date(2026, 1, 1))  # an expired warranty alone does not count


# --- multi-level approval ---------------------------------------------------------------------

def test_chain_is_cleaned_and_limited():
    out = pl.clean_chain([{"name": "  Plant   head ", "role_id": "r1"}, {"name": "Finance"}])
    assert out == [{"level": 1, "name": "Plant head", "role_id": "r1"}, {"level": 2, "name": "Finance", "role_id": None}]
    assert pl.clean_chain([]) == [] and pl.clean_chain(None) == []
    assert pl.chain_or_default([])[0]["level"] == 1  # nothing configured: one level
    for bad in ([{"name": " "}], [{"name": "x"}] * (pl.MAX_LEVELS + 1), [{"name": "x" * 81}], "levels"):
        with pytest.raises(pl.ProcurementInputError):
            pl.clean_chain(bad)


def test_levels_decide_in_order():
    chain = pl.clean_chain([{"name": "A"}, {"name": "B"}, {"name": "C"}])
    assert pl.next_level(chain, set())["level"] == 1
    assert pl.next_level(chain, {1})["level"] == 2
    assert pl.next_level(chain, {1, 2})["level"] == 3
    assert pl.next_level(chain, {1, 2, 3}) is None


def test_who_may_decide_a_level():
    with_role = {"level": 2, "name": "Plant head", "role_id": "role-b"}
    no_role = {"level": 1, "name": "Approval", "role_id": None}
    ok = lambda level, **kw: pl.may_decide_level(level, kw.get("user", "u"), kw.get("role", "x"), kw.get("admin", False),
                                                 kw.get("requester", "r"), kw.get("earlier", set()))
    assert ok(with_role, role="role-b") and not ok(with_role, role="role-a", admin=True)  # the role, not just rights
    assert ok(no_role, admin=True) and not ok(no_role, admin=False)  # no role: any approver
    assert not ok(with_role, role="role-b", user="r")  # never the requester
    assert not ok(with_role, role="role-b", earlier={"u"})  # never twice on one request
    assert not ok(None, admin=True)  # nothing left to decide
