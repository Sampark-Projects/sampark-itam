"""Pure rules for the plant dashboard KPIs (no database)."""
from typing import Dict, Optional

# metric -> "max" (lower is better, the target is a ceiling), "min" (higher is better, a floor) or None (informational)
METRICS: Dict[str, Optional[str]] = {
    "assets_total": None,
    "expired_support": "max",        # assets with an expired warranty, AMC, support or licence date
    "obsolete_assets": "max",        # assets past the vendor end of support
    "baseline_coverage": "min",      # percent of configuration items that have a golden baseline
    "config_drift": "max",           # configuration items that differ from their baseline
    "overdue_maintenance": "max",    # planned maintenance past its due date
    "workflows_in_progress": None,
}
TARGETABLE = tuple(m for m, d in METRICS.items() if d)
MAX_TARGET = 1_000_000


class KpiInputError(ValueError):
    pass


def check_target(metric: str, value) -> float:
    if metric not in TARGETABLE:
        raise KpiInputError("this metric has no target")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KpiInputError("the target must be a number")
    value = float(value)
    if value < 0 or value > MAX_TARGET:
        raise KpiInputError("the target is out of range")
    if metric == "baseline_coverage" and value > 100:
        raise KpiInputError("a percentage cannot be above 100")
    return value


def percent(part: int, whole: int) -> Optional[float]:
    """None when there is nothing to measure (no configuration items at all)."""
    if not whole:
        return None
    return round(100.0 * part / whole, 1)


def status(metric: str, value: Optional[float], target: Optional[float]) -> str:
    """met / missed / no_target / no_data."""
    direction = METRICS.get(metric)
    if direction is None or target is None:
        return "no_target"
    if value is None:
        return "no_data"
    return "met" if (value <= target if direction == "max" else value >= target) else "missed"


def pick_target(site_targets: Dict[str, float], default_targets: Dict[str, float], metric: str) -> Optional[float]:
    """A site's own target wins over the tenant-wide one."""
    if metric in site_targets:
        return site_targets[metric]
    return default_targets.get(metric)
