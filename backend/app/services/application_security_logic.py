"""Pure rules for VAPT assessments and application findings (no database)."""
import calendar
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

# how often a VAPT repeats: a whole number of months (at most 120)
FREQUENCY_UNITS = ("month",)
DEFAULT_FREQUENCY_UNIT = "month"
MAX_FREQUENCY_MONTHS = 120

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


def clean_frequency(value, unit) -> tuple:
    """(value, unit) of the VAPT frequency of an application: a positive whole number of months, or empty. The unit is month (the
    default, and the only one): it is filled in when only the number is given, and dropped when there is no number."""
    unit = None if unit is None or (isinstance(unit, str) and not unit.strip()) else unit
    if value == "":
        value = None
    if value is None:
        return None, None
    if unit is None:
        unit = DEFAULT_FREQUENCY_UNIT
    whole = isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if isinstance(value, bool) or not whole:
        raise SecurityInputError("the frequency must be a whole number")
    value = int(value)
    if value < 1:
        raise SecurityInputError("the frequency must be at least 1")
    if unit not in FREQUENCY_UNITS:
        raise SecurityInputError(f"the frequency unit must be one of: {', '.join(FREQUENCY_UNITS)}")
    if value > MAX_FREQUENCY_MONTHS:
        raise SecurityInputError(f"the frequency can be at most {MAX_FREQUENCY_MONTHS} months")
    return value, unit


def frequency_months(value: Optional[int], unit: Optional[str]) -> Optional[int]:
    if not value or unit not in FREQUENCY_UNITS:
        return None
    return value


def add_months(day: date, months: int) -> date:
    """The same day `months` later; a day that does not exist there (31 Jan + 1 month) becomes the last day of that month."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def next_due_from_frequency(test_date: Optional[date], value: Optional[int], unit: Optional[str]) -> Optional[date]:
    """The next VAPT: the date of the last completed test plus the frequency."""
    months = frequency_months(value, unit)
    if test_date is None or months is None:
        return None
    return add_months(test_date, months)


def clean_assessment(raw: Dict, today: Optional[date] = None) -> Dict:
    """`today`, when given, is the latest allowed test date: a test cannot be completed in the future."""
    out = {f: _text(raw.get(f), f, ASSESSMENT_TEXT) for f in ASSESSMENT_TEXT if f != "report_url"}
    out["report_url"] = _url(raw.get("report_url"), "report_url")
    out["assessment_type"] = _choice(raw.get("assessment_type"), ASSESSMENT_TYPES, "assessment_type") or "web_app"
    out["methodology"] = _choice(raw.get("methodology"), METHODOLOGIES, "methodology")
    out["status"] = _choice(raw.get("status"), ASSESSMENT_STATUSES, "status") or "scheduled"
    out["overall_posture"] = _choice(raw.get("overall_posture"), POSTURES, "overall_posture")
    for field in ("test_date", "sign_off_date"):
        out[field] = raw.get(field)
    if today and out["test_date"] and out["test_date"] > today:
        raise SecurityInputError("the test completion date cannot be in the future")
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


def last_and_next(test_dates, frequency_value: Optional[int] = None, frequency_unit: Optional[str] = None) -> tuple:
    """(date of the last completed test, date the next test is due). `test_dates` are the completion dates of the application's
    assessments (None for one not tested yet). The next date is the last test date plus the application's frequency; with no test
    or no frequency there is none."""
    done = [d for d in test_dates if d]
    last = max(done) if done else None
    return last, next_due_from_frequency(last, frequency_value, frequency_unit)
