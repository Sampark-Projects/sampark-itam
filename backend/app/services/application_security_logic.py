"""Pure rules for VAPT assessments and application findings (no database)."""
from datetime import date, timedelta
from typing import Dict, Iterable, Optional

ASSESSMENT_TYPES = ("web_app", "api", "network", "mobile", "infrastructure", "cloud", "code_review", "other")
METHODOLOGIES = ("black_box", "grey_box", "white_box")
ASSESSMENT_STATUSES = ("scheduled", "in_progress", "remediation", "closed")
POSTURES = ("pass", "conditional_pass", "fail")

SEVERITIES = ("critical", "high", "medium", "low", "info")
EXPLOITABILITY = ("none_known", "poc_available", "actively_exploited")
REMEDIATION_STATUSES = ("open", "patch_assigned", "retest_pending", "verified_fixed", "risk_accepted")
CLOSED_STATUSES = ("verified_fixed", "risk_accepted")
RETEST_RESULTS = ("passed", "failed")

# default fix deadline in days from discovery when none is given
SLA_DAYS = {"critical": 7, "high": 30, "medium": 90, "low": 180, "info": 365}
MAX_CVSS = 10.0

ASSESSMENT_TEXT = {"reference": 100, "scope": 5000, "assessor": 255, "report_url": 500, "sign_off_by": 255, "notes": 5000}
FINDING_TEXT = {
    "title": 300, "cve_id": 100, "discovery_source": 150, "affected_target": 255, "affected_component": 255,
    "recommended_fix": 5000, "assigned_owner": 255, "exception_id": 100, "ticket_ref": 100, "notes": 5000,
}
MULTILINE = ("scope", "recommended_fix", "notes")


class SecurityInputError(ValueError):
    pass


def format_vapt(number: int) -> str:
    return f"VAPT-{number:04d}"


def format_finding(number: int) -> str:
    return f"VULN-{number:04d}"


def _text(value, field: str, limits: Dict[str, int]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SecurityInputError(f"{field} must be text")
    text = value.strip() if field in MULTILINE else " ".join(value.split())
    if len(text) > limits[field]:
        raise SecurityInputError(f"{field} is too long (at most {limits[field]} characters)")
    return text or None


def _choice(value, allowed: Iterable[str], field: str) -> Optional[str]:
    if value is None or value == "":
        return None
    if value not in allowed:
        raise SecurityInputError(f"{field} must be one of: {', '.join(allowed)}")
    return value


def _url(value, field: str) -> Optional[str]:
    text = _text(value, field, ASSESSMENT_TEXT)
    if text is None:
        return None
    if not (text.lower().startswith("http://") or text.lower().startswith("https://")):
        raise SecurityInputError(f"{field} must be a http or https address")
    return text


def clean_assessment(raw: Dict) -> Dict:
    out = {f: _text(raw.get(f), f, ASSESSMENT_TEXT) for f in ASSESSMENT_TEXT if f != "report_url"}
    out["report_url"] = _url(raw.get("report_url"), "report_url")
    out["assessment_type"] = _choice(raw.get("assessment_type"), ASSESSMENT_TYPES, "assessment_type") or "web_app"
    out["methodology"] = _choice(raw.get("methodology"), METHODOLOGIES, "methodology")
    out["status"] = _choice(raw.get("status"), ASSESSMENT_STATUSES, "status") or "scheduled"
    out["overall_posture"] = _choice(raw.get("overall_posture"), POSTURES, "overall_posture")
    for field in ("test_date", "next_due_date", "sign_off_date"):
        out[field] = raw.get(field)
    if out["test_date"] and out["next_due_date"] and out["next_due_date"] < out["test_date"]:
        raise SecurityInputError("the next VAPT must be after the test date")
    if out["status"] == "closed" and not out["test_date"]:
        raise SecurityInputError("a closed assessment needs the date the test was completed")
    return out


def default_sla_due(severity: str, discovered_on: date) -> date:
    return discovered_on + timedelta(days=SLA_DAYS[severity])


def clean_finding(raw: Dict, today: date) -> Dict:
    out = {f: _text(raw.get(f), f, FINDING_TEXT) for f in FINDING_TEXT}
    if not out["title"]:
        raise SecurityInputError("the finding needs a title")
    out["severity"] = _choice(raw.get("severity"), SEVERITIES, "severity")
    if out["severity"] is None:
        raise SecurityInputError("choose a severity")
    score = raw.get("cvss_score")
    if score is not None and score != "":
        if isinstance(score, bool) or not isinstance(score, (int, float)) or score < 0 or score > MAX_CVSS:
            raise SecurityInputError(f"the CVSS score must be a number from 0 to {MAX_CVSS:g}")
        score = round(float(score), 1)
    else:
        score = None
    out["cvss_score"] = score
    out["exploitability"] = _choice(raw.get("exploitability"), EXPLOITABILITY, "exploitability") or "none_known"
    out["remediation_status"] = _choice(raw.get("remediation_status"), REMEDIATION_STATUSES, "remediation_status") or "open"
    out["retest_result"] = _choice(raw.get("retest_result"), RETEST_RESULTS, "retest_result")
    out["vapt_id"] = raw.get("vapt_id")
    out["affected_asset_id"] = raw.get("affected_asset_id")
    out["discovered_on"] = raw.get("discovered_on") or today
    out["sla_due_date"] = raw.get("sla_due_date") or default_sla_due(out["severity"], out["discovered_on"])
    for field in ("retest_date", "exception_valid_until"):
        out[field] = raw.get(field)
    if out["sla_due_date"] < out["discovered_on"]:
        raise SecurityInputError("the fix deadline cannot be before the discovery date")
    status = out["remediation_status"]
    if out["retest_result"] and not out["retest_date"]:
        raise SecurityInputError("give the date of the retest")
    if status == "verified_fixed" and not (out["retest_date"] and out["retest_result"] == "passed"):
        raise SecurityInputError("a finding is verified fixed only after a retest that passed")
    if status == "risk_accepted" and not out["exception_id"]:
        raise SecurityInputError("give the exception or risk-acceptance ID to accept the risk")
    return out


def is_open(status: str) -> bool:
    return status not in CLOSED_STATUSES


def finding_flags(status: str, sla_due: Optional[date], exception_valid_until: Optional[date], today: date) -> Dict:
    """overdue: still open past its deadline. exception_expired: accepted, but the waiver has run out."""
    return {
        "open": is_open(status),
        "overdue": bool(is_open(status) and sla_due and sla_due < today),
        "exception_expired": bool(status == "risk_accepted" and exception_valid_until and exception_valid_until < today),
    }


def posture_suggestion(open_counts: Dict[str, int]) -> str:
    """A hint for the scorecard from the open findings: fail with any critical or high, conditional with
    medium or low, pass with none. The person signing off still chooses."""
    if open_counts.get("critical") or open_counts.get("high"):
        return "fail"
    if open_counts.get("medium") or open_counts.get("low"):
        return "conditional_pass"
    return "pass"


def last_and_next(assessments) -> tuple:
    """(date of the last completed test, date the next test is due) from a list of
    {test_date, next_due_date, number}. A new completed test replaces the older ones' due dates; a scheduled
    test (no completion date yet) counts with its own due date."""
    done = [a for a in assessments if a.get("test_date")]
    last = max(done, key=lambda a: (a["test_date"], a.get("number") or 0)) if done else None
    candidates = [a["next_due_date"] for a in assessments if not a.get("test_date") and a.get("next_due_date")]
    if last and last.get("next_due_date"):
        candidates.append(last["next_due_date"])
    return (last["test_date"] if last else None), (min(candidates) if candidates else None)
