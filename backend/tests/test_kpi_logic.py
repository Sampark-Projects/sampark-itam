"""Pure tests for dashboard KPI rules."""
import pytest

from app.services import kpi_logic as kl


def test_targetable_metrics_have_a_direction():
    assert "assets_total" not in kl.TARGETABLE and "workflows_in_progress" not in kl.TARGETABLE
    assert kl.METRICS["baseline_coverage"] == "min" and kl.METRICS["overdue_maintenance"] == "max"


def test_percent():
    assert kl.percent(3, 4) == 75.0
    assert kl.percent(1, 3) == 33.3
    assert kl.percent(0, 5) == 0.0
    assert kl.percent(0, 0) is None


def test_status_for_ceilings_and_floors():
    assert kl.status("overdue_maintenance", 0, 0) == "met"
    assert kl.status("overdue_maintenance", 1, 0) == "missed"
    assert kl.status("expired_support", 5, 10) == "met"
    assert kl.status("baseline_coverage", 90, 90) == "met"
    assert kl.status("baseline_coverage", 89.9, 90) == "missed"
    assert kl.status("baseline_coverage", None, 90) == "no_data"
    assert kl.status("config_drift", 2, None) == "no_target"
    assert kl.status("assets_total", 10, 5) == "no_target"       # informational metrics never have a verdict


def test_site_target_wins_over_the_default():
    assert kl.pick_target({"config_drift": 2}, {"config_drift": 0}, "config_drift") == 2
    assert kl.pick_target({}, {"config_drift": 0}, "config_drift") == 0
    assert kl.pick_target({}, {}, "config_drift") is None


@pytest.mark.parametrize("metric,value", [
    ("assets_total", 1), ("nope", 1), ("config_drift", -1), ("config_drift", "5"), ("config_drift", True),
    ("config_drift", 2_000_000), ("baseline_coverage", 101),
])
def test_bad_targets(metric, value):
    with pytest.raises(kl.KpiInputError):
        kl.check_target(metric, value)


def test_good_targets():
    assert kl.check_target("config_drift", 0) == 0.0
    assert kl.check_target("baseline_coverage", 95) == 95.0
