"""Pure rules for purchase requests / orders (no database).

draft -> submitted -> approved -> ordered -> received -> closed
                   -> rejected (end)       any open state -> cancelled
A submitted request goes back to draft to be changed. Approval needs an approver who is not the
requester. Ordering needs the ERP purchase order number.
"""
from datetime import date, timedelta
from typing import Dict, List, Optional

STATUSES = ("draft", "submitted", "approved", "rejected", "ordered", "received", "closed", "cancelled")
OPEN = ("draft", "submitted", "approved", "ordered")
EDITABLE = ("draft",)
RECEIVABLE = ("approved", "ordered", "received")  # deliveries can be booked against these

TRANSITIONS: Dict[str, tuple] = {
    "draft": ("submitted", "cancelled"),
    "submitted": ("approved", "rejected", "draft", "cancelled"),
    "approved": ("ordered", "cancelled"),
    "ordered": ("received", "cancelled"),
    "received": ("closed",),
    "rejected": (),
    "closed": (),
    "cancelled": (),
}
DECISIONS = ("approved", "rejected")
MAX_LINES = 50


class ProcurementInputError(ValueError):
    pass


def format_number(number: int) -> str:
    return f"PR-{number:04d}"


def allowed_targets(status: str, is_requester: bool, can_decide: bool) -> List[str]:
    """What this person may move the request to."""
    out = []
    for target in TRANSITIONS.get(status, ()):
        if target in DECISIONS and (not can_decide or is_requester):
            continue  # nobody approves their own request
        out.append(target)
    return out


def check_transition(status: str, target: str, is_requester: bool, can_decide: bool, po_number: Optional[str],
                     lines: int, note: Optional[str]) -> None:
    if target not in TRANSITIONS.get(status, ()):
        raise ProcurementInputError(f"cannot move from {status} to {target}")
    if target in DECISIONS:
        if not can_decide:
            raise ProcurementInputError("only an approver can decide")
        if is_requester:
            raise ProcurementInputError("the requester cannot approve or reject their own request")
    if target == "submitted" and lines < 1:
        raise ProcurementInputError("add at least one line before submitting")
    if target == "rejected" and not (note or "").strip():
        raise ProcurementInputError("give a reason for the rejection")
    if target == "ordered" and not (po_number or "").strip():
        raise ProcurementInputError("enter the purchase order number when ordering")


def clean_lines(lines) -> List[Dict]:
    if not isinstance(lines, (list, tuple)):
        raise ProcurementInputError("lines must be a list")
    if len(lines) > MAX_LINES:
        raise ProcurementInputError(f"at most {MAX_LINES} lines")
    out = []
    for index, raw in enumerate(lines, start=1):
        qty = raw.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1 or qty > 100000:
            raise ProcurementInputError(f"line {index}: the quantity must be a whole number from 1")
        model = " ".join(str(raw.get("model") or "").split()) or None
        description = " ".join(str(raw.get("description") or "").split()) or None
        if not (model or description or raw.get("asset_type_id")):
            raise ProcurementInputError(f"line {index}: give a model, a description or an asset type")
        cost = raw.get("unit_cost")
        if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0):
            raise ProcurementInputError(f"line {index}: the unit cost must be zero or more")
        out.append({
            "position": index, "asset_type_id": raw.get("asset_type_id") or None,
            "manufacturer_id": raw.get("manufacturer_id") or None, "model": model, "description": description,
            "quantity": qty, "unit_cost": cost,
        })
    return out


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


def order_mismatches(line: Dict, asset: Dict, already_received: int) -> List[str]:
    """How a delivered asset differs from the order line it is booked against. Codes:
    type, manufacturer, model, quantity. Fields the line leaves empty are not checked."""
    problems = []
    if line.get("asset_type_id") and asset.get("asset_type_id") != line["asset_type_id"]:
        problems.append("type")
    if line.get("manufacturer_id") and asset.get("manufacturer_id") != line["manufacturer_id"]:
        problems.append("manufacturer")
    if line.get("model") and _norm(asset.get("model")) != _norm(line["model"]):
        problems.append("model")
    if already_received >= int(line.get("quantity") or 0):
        problems.append("quantity")
    return problems


def total(lines) -> Optional[float]:
    costs = [(l.get("unit_cost"), l.get("quantity")) for l in lines]
    if not costs or any(c is None for c, _ in costs):
        return None
    return round(sum(float(c) * int(q) for c, q in costs), 2)


# --- maintenance plans (kept here with the other pure scheduling rules) -----------------------

MIN_INTERVAL, MAX_INTERVAL = 1, 3650


def plan_task_due(next_due: date, lead_days: int, today: date, has_open_task: bool) -> bool:
    """A plan creates its next task lead_days before the due date, unless one is still open."""
    return not has_open_task and today >= next_due - timedelta(days=max(0, lead_days))


def next_due_after(done_on: date, interval_days: int) -> date:
    """The next due date counts from the day the work was actually done."""
    return done_on + timedelta(days=interval_days)
