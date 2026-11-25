"""Pure lifecycle rules (no database): alert thresholds, vendor end-of-life matching, CSV parsing.

Kept separate from the database code so the date maths is easy to test.
"""
from app.services.local_time import local_today
import csv
import io
from datetime import date, datetime
from fnmatch import fnmatchcase
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_LEAD_DAYS = [90, 30, 7]
MAX_LEAD_DAYS = 3650
MAX_LEAD_VALUES = 12
# an expiry older than this is history, not something to alert about on the first run
EXPIRED_ALERT_WINDOW_DAYS = 365

EXPIRY_FIELDS = {
    "warranty_expiry_date": "warranty",
    "amc_expiry_date": "amc",
    "support_expiry_date": "support",
    "licence_expiry_date": "licence",
}

COST_TYPES = ("maintenance", "upgrade", "licence", "other")


class LifecycleInputError(ValueError):
    pass


def normalize_lead_days(values) -> List[int]:
    """Cleaned, de-duplicated, largest first. 0 (the expiry day) is always handled separately."""
    if not isinstance(values, (list, tuple)) or not values:
        raise LifecycleInputError("at least one lead time is required")
    out = set()
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
            raise LifecycleInputError("lead times must be whole numbers of days")
        v = int(v)
        if v < 1 or v > MAX_LEAD_DAYS:
            raise LifecycleInputError(f"lead times must be between 1 and {MAX_LEAD_DAYS} days")
        out.add(v)
    if len(out) > MAX_LEAD_VALUES:
        raise LifecycleInputError(f"at most {MAX_LEAD_VALUES} lead times")
    return sorted(out, reverse=True)


def threshold_for(days_left: int, lead_days: Iterable[int]) -> Optional[int]:
    """The alert step an expiry has reached, or None when nothing is due yet.

    Steps are the lead times plus 0 (expired). The step is the smallest one that days_left has
    reached, so an expiry first seen 20 days out with steps 90/30/7 is at step 30 and is alerted once.
    """
    if days_left < -EXPIRED_ALERT_WINDOW_DAYS:
        return None
    if days_left < 0:
        return 0
    reached = [t for t in lead_days if days_left <= t]
    return min(reached) if reached else None


def days_until(expiry: date, today: Optional[date] = None) -> int:
    return (expiry - (today or local_today())).days


# --- vendor end-of-life ---------------------------------------------------------------------

def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").split()).lower()


def model_matches(pattern: str, model: Optional[str]) -> bool:
    """Case-insensitive; * and ? are wildcards; blank pattern or blank model never match."""
    pattern, model = _norm(pattern), _norm(model)
    if not pattern or not model:
        return False
    return fnmatchcase(model, pattern)


def _specificity(pattern: str) -> Tuple[int, int]:
    # exact patterns beat wildcard ones; among wildcards the one with more literal characters wins
    p = _norm(pattern)
    literal = len(p.replace("*", "").replace("?", ""))
    return (0 if ("*" in p or "?" in p) else 1, literal)


def match_vendor_entry(entries, manufacturer_name: Optional[str], model: Optional[str]):
    """Best entry for an asset: same manufacturer, matching model, most specific pattern."""
    maker = _norm(manufacturer_name)
    if not maker:
        return None
    fitting = [
        e for e in entries
        if _norm(e.manufacturer_name) == maker and model_matches(e.model_pattern, model)
    ]
    if not fitting:
        return None
    return max(fitting, key=lambda e: _specificity(e.model_pattern))


def obsolescence_date(entry) -> Optional[date]:
    """When the asset stops being supported: end of support, else end of life, else None.

    End of sale alone is not obsolescence: the vendor still supports the product.
    """
    if entry is None:
        return None
    dates = [d for d in (entry.end_of_support_date, entry.end_of_life_date) if d]
    return min(dates) if dates else None


def obsolescence_state(when: Optional[date], today: Optional[date] = None, horizon_days: int = 365) -> str:
    """obsolete / soon (within the horizon) / later / unknown."""
    if when is None:
        return "unknown"
    left = days_until(when, today)
    if left < 0:
        return "obsolete"
    return "soon" if left <= horizon_days else "later"


# --- end of life in the risk score ------------------------------------------------------------

# fields whose expiry means no more vendor patches or service (warranty and licence do not)
SUPPORT_CONTRACT_FIELDS = ("support_expiry_date", "amc_expiry_date")
MAX_EOL_RISK = 3


def eol_risk(vendor_state: str, support_expired: bool) -> Tuple[int, List[str]]:
    """Points added to the vulnerability side of the risk score, with the reasons:
    past vendor end of support +2, reaching it within a year +1, support / AMC contract expired +1."""
    points, reasons = 0, []
    if vendor_state == "obsolete":
        points, reasons = 2, ["eol_obsolete"]
    elif vendor_state == "soon":
        points, reasons = 1, ["eol_soon"]
    if support_expired:
        points += 1
        reasons.append("eol_contract_expired")
    return min(points, MAX_EOL_RISK), reasons


def support_expired(asset, today: Optional[date] = None) -> bool:
    today = today or local_today()
    return any((getattr(asset, f, None) is not None and getattr(asset, f) < today) for f in SUPPORT_CONTRACT_FIELDS)


# --- CSV import -----------------------------------------------------------------------------

CSV_COLUMNS = ("manufacturer", "model", "end_of_sale", "end_of_support", "end_of_life", "source", "notes")
_ALIASES = {
    "vendor": "manufacturer", "manufacturer_name": "manufacturer",
    "model_pattern": "model",
    "end_of_sale_date": "end_of_sale", "eos": "end_of_sale",
    "end_of_support_date": "end_of_support", "eosl": "end_of_support", "last_support": "end_of_support",
    "end_of_life_date": "end_of_life", "eol": "end_of_life",
}
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")
MAX_CSV_ROWS = 5000


def parse_date_cell(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise LifecycleInputError(f"not a date: {value!r} (use YYYY-MM-DD or DD/MM/YYYY)")


def parse_vendor_csv(text: str) -> Tuple[List[Dict], List[Dict]]:
    """Returns (rows, errors). Row errors carry the CSV line number; good rows are still returned."""
    text = text.lstrip("﻿")
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise LifecycleInputError("the file is empty")
    mapping = {}
    for name in reader.fieldnames:
        key = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
        mapping[name] = _ALIASES.get(key, key)
    missing = [c for c in ("manufacturer", "model") if c not in mapping.values()]
    if missing:
        raise LifecycleInputError("missing column(s): " + ", ".join(missing))

    rows, errors = [], []
    for line_no, raw in enumerate(reader, start=2):
        if line_no - 1 > MAX_CSV_ROWS:
            raise LifecycleInputError(f"more than {MAX_CSV_ROWS} rows")
        cells = {mapping[k]: (v or "").strip() for k, v in raw.items() if k is not None}
        if not any(cells.values()):
            continue
        try:
            if not cells.get("manufacturer") or not cells.get("model"):
                raise LifecycleInputError("manufacturer and model are required")
            if len(cells["manufacturer"]) > 255 or len(cells["model"]) > 100:
                raise LifecycleInputError("manufacturer or model is too long")
            row = {
                "manufacturer_name": cells["manufacturer"],
                "model_pattern": cells["model"],
                "end_of_sale_date": parse_date_cell(cells.get("end_of_sale", "")),
                "end_of_support_date": parse_date_cell(cells.get("end_of_support", "")),
                "end_of_life_date": parse_date_cell(cells.get("end_of_life", "")),
                "source": (cells.get("source") or "")[:255] or None,
                "notes": cells.get("notes") or None,
            }
            if not (row["end_of_sale_date"] or row["end_of_support_date"] or row["end_of_life_date"]):
                raise LifecycleInputError("at least one date is required")
            rows.append(row)
        except LifecycleInputError as exc:
            errors.append({"line": line_no, "error": str(exc)})
    return rows, errors
