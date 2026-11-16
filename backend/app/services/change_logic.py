"""Pure rules for change requests and unapproved-change detection (no database)."""
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

CHANGE_TYPES = ("configuration", "firmware", "program", "hardware", "network", "other")
RISK_LEVELS = ("low", "medium", "high")
URGENCIES = ("normal", "emergency")
REVIEW_OUTCOMES = ("successful", "partial", "failed", "rolled_back")
MAX_REQUIRED_APPROVALS = 5
STATUSES = ("draft", "submitted", "approved", "rejected", "implemented", "closed", "cancelled")

# status -> statuses it can move to
TRANSITIONS = {
    "draft": ("submitted", "cancelled"),
    "submitted": ("approved", "rejected", "draft", "cancelled"),
    "approved": ("implemented", "cancelled"),
    "rejected": ("draft",),
    "implemented": ("closed",),
    "closed": (),
    "cancelled": (),
}
# a change request in one of these statuses can cover asset changes
COVERING_STATUSES = ("approved", "implemented", "closed")

# asset fields whose change must be covered by an approved change request (administrators can adjust)
DEFAULT_CONTROLLED_FIELDS = (
    "firmware_version", "model", "manufacturer_id", "site_id", "location_id", "security_zone_id",
    "remote_access", "remote_access_type", "physical_access_ease",
)
CONTROLLED_FIELD_CHOICES = DEFAULT_CONTROLLED_FIELDS + (
    "serial_number", "ip_address", "protocols", "asset_type_id", "status_id", "business_criticality",
)


class ChangeInputError(ValueError):
    pass


def targets(current: str, urgency: str = "normal") -> Tuple[str, ...]:
    """Where a request can go from `current`. An emergency change may be implemented straight from
    'submitted' (approval follows afterwards, see the retro decision)."""
    out = TRANSITIONS.get(current, ())
    if urgency == "emergency" and current == "submitted":
        out = out + ("implemented",)
    return out


def can_transition(current: str, target: str, urgency: str = "normal") -> bool:
    return target in targets(current, urgency)


def clean_required_approvals(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ChangeInputError("the number of approvals must be a whole number")
    if not 1 <= n <= MAX_REQUIRED_APPROVALS:
        raise ChangeInputError(f"the number of approvals must be between 1 and {MAX_REQUIRED_APPROVALS}")
    return n


def quorum_reached(approvals: int, required: int) -> bool:
    return approvals >= max(1, required)


def check_close(urgency: str, review_outcome: Optional[str], retro_decision: Optional[str]) -> None:
    """Closing needs the post-implementation review, and an emergency change also needs its late approval decision."""
    if review_outcome not in REVIEW_OUTCOMES:
        raise ChangeInputError("a post-implementation review outcome is required to close: " + ", ".join(REVIEW_OUTCOMES))
    if urgency == "emergency" and retro_decision not in ("approved", "rejected"):
        raise ChangeInputError("an emergency change must be approved or rejected afterwards before it can be closed")


def format_number(number: int) -> str:
    return f"CR-{number:04d}"


def clean_controlled_fields(values) -> List[str]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ChangeInputError("at least one controlled field is required")
    bad = [v for v in values if v not in CONTROLLED_FIELD_CHOICES]
    if bad:
        raise ChangeInputError("unknown field(s): " + ", ".join(map(str, bad)))
    return list(dict.fromkeys(values))


def can_decide(user_role_id, approver_role_id, is_admin: bool) -> bool:
    """Approve or reject: the configured approver role, or an administrator."""
    if approver_role_id is not None and user_role_id is not None and user_role_id == approver_role_id:
        return True
    return bool(is_admin)


def self_decision_blocked(requested_by, user_id, allow_self_approval: bool) -> bool:
    return (not allow_self_approval) and requested_by is not None and requested_by == user_id


# --- unapproved change detection ---------------------------------------------------------------

def load_json(value: Any) -> Dict:
    """Audit data is stored as JSON that may itself be a JSON string."""
    for _ in range(2):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return {}
    return value if isinstance(value, dict) else {}


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, (list, tuple)):
        return list(value) or None
    return value


def changed_fields(old: Any, new: Any, fields: Iterable[str]) -> List[str]:
    """Controlled fields whose value differs between two audit snapshots. A field missing from
    either snapshot is not counted: the snapshot did not record it."""
    old, new = load_json(old), load_json(new)
    out = []
    for field in fields:
        if field in old and field in new and _norm(old[field]) != _norm(new[field]):
            out.append(field)
    return out


def to_naive_utc(ts: datetime) -> datetime:
    if ts.tzinfo is not None:
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def coverage_window(approved_at: Optional[datetime], implemented_at: Optional[datetime],
                    urgency: str = "normal", submitted_at: Optional[datetime] = None,
                    retro_decision: Optional[str] = None) -> Optional[Tuple[datetime, Optional[datetime]]]:
    """From approval until the change is marked implemented (open-ended before that). An emergency change
    covers from the moment it was submitted, since its approval comes afterwards."""
    if urgency == "emergency" and retro_decision == "rejected":
        return None  # the emergency change was not justified: its edits are not covered
    start = approved_at
    if urgency == "emergency" and submitted_at is not None:
        # the late approval must not shorten the cover: it starts at submission
        start = submitted_at if start is None else min(start, submitted_at)
    if start is None:
        return None
    return (start, implemented_at)


def is_covered(ts: datetime, windows: Sequence[Optional[Tuple[datetime, Optional[datetime]]]]) -> bool:
    ts = to_naive_utc(ts)
    for window in windows:
        if window is None:
            continue
        start, end = window
        if start <= ts and (end is None or ts <= end):
            return True
    return False
