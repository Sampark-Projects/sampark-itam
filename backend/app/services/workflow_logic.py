"""Pure rules for lifecycle workflows (no database): step definitions, who may act, what blocks a step."""
from typing import Any, Dict, Iterable, List, Optional, Tuple

KINDS = ("onboarding", "retirement")
STEP_TYPES = ("task", "approval")
MAX_STEPS = 15

# asset fields a step may require to be filled in before it can be completed
REQUIRED_FIELD_CHOICES = (
    "tag", "serial_number", "model", "firmware_version", "manufacturer_id", "location_id", "area_id",
    "security_zone_id", "business_criticality", "safety_relevance", "requisition_number",
    "purchase_order_number", "purchase_date", "purchase_cost", "cost_currency", "expected_delivery_date",
    "received_date", "commissioned_date", "acceptance_date", "acceptance_signed_by",
    "warranty_expiry_date", "amc_expiry_date", "support_expiry_date", "licence_expiry_date",
    "plant_owner", "amc_partner", "disposal_method", "disposal_date", "disposal_reference",
    # checks rather than fields: an IP address or interface is recorded / a configuration baseline is set
    "network_settings", "config_baseline", "order_match",
)

# what a document is; a workflow step can require a document of one category
DOCUMENT_CATEGORIES = (
    "manual", "drawing", "certificate", "purchase_order", "warranty", "delivery_note", "commissioning",
    "acceptance", "test_report", "wipe_certificate", "disposal", "other",
)


class WorkflowInputError(ValueError):
    pass


def clean_definition(steps: Any) -> List[Dict]:
    """Validate and normalise the steps of a workflow definition; positions become 1..n in order."""
    if not isinstance(steps, (list, tuple)) or not steps:
        raise WorkflowInputError("a workflow needs at least one step")
    if len(steps) > MAX_STEPS:
        raise WorkflowInputError(f"at most {MAX_STEPS} steps")
    cleaned = []
    for index, raw in enumerate(steps, start=1):
        if not isinstance(raw, dict):
            raise WorkflowInputError("each step must be an object")
        name = " ".join(str(raw.get("name") or "").split())
        if not name or len(name) > 100:
            raise WorkflowInputError(f"step {index}: a name of 1-100 characters is required")
        step_type = raw.get("step_type") or "task"
        if step_type not in STEP_TYPES:
            raise WorkflowInputError(f"step {index}: type must be one of {', '.join(STEP_TYPES)}")
        fields = raw.get("required_fields") or []
        if not isinstance(fields, (list, tuple)):
            raise WorkflowInputError(f"step {index}: required_fields must be a list")
        bad = [f for f in fields if f not in REQUIRED_FIELD_CHOICES]
        if bad:
            raise WorkflowInputError(f"step {index}: unknown field(s): {', '.join(map(str, bad))}")
        statement = " ".join(str(raw.get("confirm_statement") or "").split()) or None
        if statement and len(statement) > 255:
            raise WorkflowInputError(f"step {index}: the confirmation statement is too long")
        category = raw.get("document_category") or None
        if category is not None and category not in DOCUMENT_CATEGORIES:
            raise WorkflowInputError(f"step {index}: unknown document category")
        description = " ".join(str(raw.get("description") or "").split()) or None
        if description and len(description) > 255:
            raise WorkflowInputError(f"step {index}: the description is too long")
        cleaned.append({
            "position": index,
            "name": name,
            "description": description,
            "step_type": step_type,
            "role_id": raw.get("role_id") or None,
            "required_fields": list(dict.fromkeys(fields)),
            "requires_document": bool(raw.get("requires_document")),
            "document_category": category if raw.get("requires_document") else None,
            "requires_comment": bool(raw.get("requires_comment")),
            "confirm_statement": statement,
            "sets_status_id": raw.get("sets_status_id") or None,
        })
    return cleaned


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False  # 0, False and dates are values


def missing_fields(required: Iterable[str], values: Dict[str, Any]) -> List[str]:
    return [f for f in required if is_blank(values.get(f))]


def step_blockers(step, values: Dict[str, Any], documents_since_start) -> List[str]:
    """What is still missing on the asset before the step can be completed.
    Codes: "field:<name>", "document" and "document:<category>".
    documents_since_start is a count, or {category: count} of documents uploaded since the run began."""
    blockers = [f"field:{f}" for f in missing_fields(step.required_fields or [], values)]
    if step.requires_document:
        category = getattr(step, "document_category", None)
        if isinstance(documents_since_start, dict):
            have = documents_since_start.get(category, 0) if category else sum(documents_since_start.values())
        else:
            have = documents_since_start
        if have < 1:
            blockers.append(f"document:{category}" if category else "document")
    return blockers


def input_problems(step, comment: Optional[str], confirmed: bool) -> List[str]:
    """What the person acting must supply: "comment" and "confirm"."""
    problems = []
    if step.requires_comment and is_blank(comment):
        problems.append("comment")
    if step.confirm_statement and not confirmed:
        problems.append("confirm")
    return problems


def can_act(user_role_id, step_role_id, is_admin: bool) -> Tuple[bool, bool]:
    """(allowed, override). A step with no role is open to anyone allowed to work on the asset.
    An administrator may act outside the role; that is recorded as an override."""
    if step_role_id is None:
        return True, False
    if user_role_id is not None and user_role_id == step_role_id:
        return True, False
    if is_admin:
        return True, True
    return False, False


def self_approval_blocked(step_type: str, started_by, acting_user_id, allow_self_approval: bool) -> bool:
    """Separation of duties: the person who started a run cannot approve its approval steps."""
    return (
        step_type == "approval"
        and not allow_self_approval
        and started_by is not None
        and started_by == acting_user_id
    )


def current_step(steps):
    """First step that is still pending, or None when none are left."""
    for step in sorted(steps, key=lambda s: s.position):
        if step.state == "pending":
            return step
    return None
