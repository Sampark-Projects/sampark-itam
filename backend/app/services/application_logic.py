"""Pure rules for the Application register (no database)."""
from datetime import date
from typing import Dict, Optional
from urllib.parse import urlparse

TIERS = ("tier1", "tier2", "tier3", "tier4")  # tier1 = mission critical
LIFECYCLE_STATUSES = ("planned", "development", "staging", "uat", "production", "dr", "deprecated", "retired")
DATA_CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
MAX_URL = 500
ASSET_ROLES = ("web", "application", "database", "load_balancer", "cache", "queue", "storage", "other")
ENVIRONMENTS = ("production", "dr", "uat", "staging", "development")
DIRECTIONS = ("outbound", "inbound", "bidirectional")
MAX_LINKED_ASSETS = 200
MAX_INTEGRATIONS = 200
MAX_HOURS = 24 * 365

TEXT_FIELDS = {  # field -> maximum length
    "name": 150, "business_owner": 255, "technical_owner": 255, "authentication_method": 255,
    "firewall_rule_ids": 2000, "backup_policy": 2000, "last_scan_result": 255, "description": 5000,
    "dns_records": 2000,
}


class ApplicationInputError(ValueError):
    pass


def format_number(number: int) -> str:
    return f"APP-{number:04d}"


def clean_text(value, field: str) -> Optional[str]:
    """Trim; an empty value becomes None. Single-line fields have their inner spaces collapsed."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApplicationInputError(f"{field} must be text")
    text = value.strip() if field in ("firewall_rule_ids", "backup_policy", "description", "dns_records") else " ".join(value.split())
    if len(text) > TEXT_FIELDS[field]:
        raise ApplicationInputError(f"{field} is too long (at most {TEXT_FIELDS[field]} characters)")
    return text or None


def clean_url(value, field: str) -> Optional[str]:
    """A web address: http or https with a host. Empty is allowed."""
    if value is None or not str(value).strip():
        return None
    url = str(value).strip()
    if len(url) > MAX_URL:
        raise ApplicationInputError(f"{field} is too long")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ApplicationInputError(f"{field} must be a http or https address")
    return url


def clean_choice(value, allowed, field: str) -> Optional[str]:
    if value is None or value == "":
        return None
    if value not in allowed:
        raise ApplicationInputError(f"{field} must be one of: {', '.join(allowed)}")
    return value


def clean_hours(value, field: str) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_HOURS:
        raise ApplicationInputError(f"{field} must be a whole number of hours from 0 to {MAX_HOURS}")
    return value


def ssl_state(expiry: Optional[date], today: date, warn_days: int = 30) -> Optional[str]:
    """expired / expiring (within warn_days) / valid; None when no date is recorded."""
    if expiry is None:
        return None
    if expiry < today:
        return "expired"
    return "expiring" if (expiry - today).days <= warn_days else "valid"


def clean_application(raw: Dict) -> Dict:
    """Validate and normalise the editable fields of an application."""
    out = {f: clean_text(raw.get(f), f) for f in TEXT_FIELDS}
    if not out["name"]:
        raise ApplicationInputError("the application needs a name")
    out["primary_url"] = clean_url(raw.get("primary_url"), "primary_url")
    out["secondary_url"] = clean_url(raw.get("secondary_url"), "secondary_url")
    out["tier"] = clean_choice(raw.get("tier"), TIERS, "tier")
    out["lifecycle_status"] = clean_choice(raw.get("lifecycle_status"), LIFECYCLE_STATUSES, "lifecycle_status") or "production"
    out["data_classification"] = clean_choice(raw.get("data_classification"), DATA_CLASSIFICATIONS, "data_classification")
    out["rpo_hours"] = clean_hours(raw.get("rpo_hours"), "rpo_hours")
    out["rto_hours"] = clean_hours(raw.get("rto_hours"), "rto_hours")
    out["ssl_expiry_date"] = raw.get("ssl_expiry_date")
    out["last_scan_date"] = raw.get("last_scan_date")
    out["site_id"] = raw.get("site_id")
    return out


# --- hosting: assets linked to an application, and connected systems -------------------------------

def clean_link(raw: Dict) -> Dict:
    """The application-specific facts about a linked asset."""
    ports = " ".join(str(raw.get("listening_ports") or "").split())
    if len(ports) > 255:
        raise ApplicationInputError("listening_ports is too long (at most 255 characters)")
    notes = (raw.get("notes") or "").strip() if isinstance(raw.get("notes"), str) or raw.get("notes") is None else None
    if notes is None and raw.get("notes") is not None:
        raise ApplicationInputError("notes must be text")
    if notes and len(notes) > 2000:
        raise ApplicationInputError("notes is too long (at most 2000 characters)")
    return {
        "role": clean_choice(raw.get("role"), ASSET_ROLES, "role") or "other",
        "environment": clean_choice(raw.get("environment"), ENVIRONMENTS, "environment"),
        "listening_ports": ports or None,
        "notes": notes or None,
    }


def clean_integration(raw: Dict) -> Dict:
    """A system the application exchanges data with."""
    name = " ".join(str(raw.get("name") or "").split())
    if not name:
        raise ApplicationInputError("the connected system needs a name")
    if len(name) > 150:
        raise ApplicationInputError("name is too long (at most 150 characters)")
    out = {"name": name, "direction": clean_choice(raw.get("direction"), DIRECTIONS, "direction") or "outbound"}
    for field, limit in (("protocol", 100), ("port", 50)):
        value = " ".join(str(raw.get(field) or "").split())
        if len(value) > limit:
            raise ApplicationInputError(f"{field} is too long (at most {limit} characters)")
        out[field] = value or None
    notes = raw.get("notes")
    notes = notes.strip() if isinstance(notes, str) else None
    if notes and len(notes) > 2000:
        raise ApplicationInputError("notes is too long (at most 2000 characters)")
    out["notes"] = notes or None
    out["peer_asset_id"] = raw.get("peer_asset_id")
    return out


def pick_os(software) -> Optional[str]:
    """'Ubuntu 22.04' from the first operating-system entry of an asset's software list, or None."""
    for item in software:
        if item.get("kind") == "os":
            return " ".join(x for x in (item.get("name"), item.get("version")) if x) or None
    return None
