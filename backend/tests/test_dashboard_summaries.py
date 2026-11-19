"""The dashboard summaries: the batched dependency check gives the same answer as the per-connection analyzer, the review
summary is computed in SQL, and the per-tenant cache keeps and clears results."""
import uuid
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.database import get_db
from app.models import Asset
from app.models.asset_connection import AssetConnection
from app.models.asset_dependency import AssetDependency
from app.routers import dashboards
from app.services.asset_review_service import AssetReviewService
from app.services.auth import get_current_user
from app.services.connection_dependency_analyzer import ConnectionDependencyAnalyzer as Analyzer
from app.services.dashboard_cache import dashboard_cache, invalidate_dashboard_cache
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)


def _asset(w, name, **extra):
    a = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, site_id=w.site.id, asset_type_id=w.type.id, status_id=w.active.id, **extra)
    w.db.add(a)
    w.db.flush()
    return a


def _client(db, user):
    api = FastAPI()
    api.include_router(dashboards.router)
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def _count_queries(db):
    counter = {"n": 0}

    def bump(*args):
        counter["n"] += 1

    event.listen(db.get_bind(), "before_cursor_execute", bump)
    return counter, lambda: event.remove(db.get_bind(), "before_cursor_execute", bump)


def test_dependency_gaps_match_the_per_connection_analyzer(db):
    w = World(db)
    a, b, c, d, e = (_asset(w, n) for n in "abcde")
    other = World(db, "O")
    db.add_all([
        AssetConnection(tenant_id=w.tenant.id, parent_asset_id=a.id, child_asset_id=b.id, connection_type="control"),   # covered
        AssetConnection(tenant_id=w.tenant.id, parent_asset_id=c.id, child_asset_id=d.id, connection_type="safety"),    # covered, reversed
        AssetConnection(tenant_id=w.tenant.id, parent_asset_id=a.id, child_asset_id=c.id, connection_type="control"),   # missing
        AssetConnection(tenant_id=w.tenant.id, parent_asset_id=b.id, child_asset_id=e.id, connection_type="Ethernet"),  # not critical
        AssetConnection(tenant_id=w.tenant.id, parent_asset_id=d.id, child_asset_id=e.id, connection_type="critical"),  # missing
        AssetConnection(tenant_id=other.tenant.id, parent_asset_id=other.asset.id, child_asset_id=other.asset.id, connection_type="control"),
        AssetDependency(tenant_id=w.tenant.id, dependent_asset_id=a.id, dependency_asset_id=b.id),
        AssetDependency(tenant_id=w.tenant.id, dependent_asset_id=d.id, dependency_asset_id=c.id),
    ])
    db.commit()

    mine = db.query(AssetConnection).filter(AssetConnection.tenant_id == w.tenant.id).all()
    old = [Analyzer.get_connection_dependency_status(db, c_) for c_ in mine]
    expected = sum(1 for s in old if s["status"] == "missing")
    assert expected == 2

    counter, stop = _count_queries(db)
    got = Analyzer.dependency_gap_counts(db, w.tenant.id)
    stop()
    assert got == {"total_connections": 5, "missing": expected, "critical_missing": expected}
    assert counter["n"] == 2  # not one query per connection


def test_review_summary_counts_overdue_and_due_assets_in_sql(db):
    w = World(db)
    now = datetime.utcnow()
    overdue = _asset(w, "late", next_review_date=now - timedelta(days=3), review_status="pending")
    reviewed_late = _asset(w, "late-reviewed", next_review_date=now - timedelta(days=1), review_status="reviewed")
    skipped = _asset(w, "skipped", next_review_date=now - timedelta(days=9), review_status="skipped")
    soon = _asset(w, "soon", next_review_date=now + timedelta(days=5), review_status="pending")
    far = _asset(w, "far", next_review_date=now + timedelta(days=400), review_status="pending")
    stale = _asset(w, "stale", next_review_date=now + timedelta(days=400), review_status="overdue")
    unset = _asset(w, "unset")  # no date yet: calculated from its creation date and the default interval
    db.commit()

    out = AssetReviewService.dashboard_summary(db, w.tenant.id)
    db.expire_all()

    # the same assets the per-asset service reports as overdue (the unset one is calculated, so it counts as well when old enough)
    assert {a["name"] for a in out["overdue_assets"]} == {"late", "late-reviewed"}
    assert out["overdue_count"] == 2
    assert {a["name"] for a in out["due_assets"]} >= {"soon"} and out["due_count"] >= 1
    assert db.get(Asset, skipped.id).review_status == "skipped"
    assert db.get(Asset, overdue.id).review_status == "overdue"
    assert db.get(Asset, reviewed_late.id).review_status == "overdue"
    assert db.get(Asset, stale.id).review_status == "pending"          # its date is far in the future
    assert db.get(Asset, unset.id).next_review_date is not None        # calculated and saved
    assert far.id and soon.id


def test_review_summary_is_scoped_to_the_tenant_and_ignores_deleted_assets(db):
    w, other = World(db), World(db, "O")
    now = datetime.utcnow()
    _asset(other, "theirs", next_review_date=now - timedelta(days=2), review_status="pending")
    _asset(w, "gone", next_review_date=now - timedelta(days=2), review_status="pending", deleted_at=now)
    db.commit()
    out = AssetReviewService.dashboard_summary(db, w.tenant.id)
    assert out["overdue_count"] == 0 and out["overdue_assets"] == []


def test_review_summary_uses_a_fixed_number_of_queries(db):
    w = World(db)
    tenant_id = w.tenant.id

    def run():
        counter, stop = _count_queries(db)
        AssetReviewService.dashboard_summary(db, tenant_id)
        stop()
        return counter["n"]

    for i in range(3):
        _asset(w, f"a{i}", next_review_date=datetime.utcnow() + timedelta(days=100), review_status="pending")
    db.commit()
    run()  # the first call loads the tenant row once
    few = run()
    for i in range(40):
        _asset(w, f"b{i}", next_review_date=datetime.utcnow() + timedelta(days=100), review_status="pending")
    db.commit()
    assert run() == few  # the number of queries does not grow with the number of assets


def test_endpoints_are_cached_per_tenant_and_cleared_on_invalidate(db):
    dashboard_cache.clear_all_cache()
    w = World(db)
    client = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "admin"))
    first = client.get("/dashboard/reviews-summary")
    assert first.status_code == 200 and first.json()["overdue_count"] == 0

    _asset(w, "late", next_review_date=datetime.utcnow() - timedelta(days=2), review_status="pending")
    db.commit()
    assert client.get("/dashboard/reviews-summary").json()["overdue_count"] == 0     # served from the cache
    invalidate_dashboard_cache(str(w.tenant.id))
    assert client.get("/dashboard/reviews-summary").json()["overdue_count"] == 1     # recomputed

    for path in ("exposure", "dependencies-summary", "vulnerabilities-summary", "risky-assets"):
        assert client.get(f"/dashboard/{path}").status_code == 200, path
    other = World(db, "O")
    assert _client(db, other.user(ADMIN_DEFAULT_PERMISSIONS, "o")).get("/dashboard/reviews-summary").json()["overdue_count"] == 0


def test_a_failing_summary_is_not_cached():
    dashboard_cache.clear_all_cache()
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"ok": True}

    try:
        dashboard_cache.get_or_compute("t", "x", compute)
    except RuntimeError:
        pass
    assert dashboard_cache.get_or_compute("t", "x", compute) == {"ok": True}
    assert dashboard_cache.get_or_compute("t", "x", compute) == {"ok": True} and calls["n"] == 2


def test_batched_zone_status_equals_the_per_zone_calculation(db):
    from app.models import SecurityRequirement, SecurityRequirementCompliance, SecurityZone, SRAssessment
    from app.services.isa62443_compliance_engine import ISA62443ComplianceEngine as Engine

    w = World(db)
    reqs = [SecurityRequirement(id=uuid.uuid4(), requirement_id=f"SR {i}.1", title=f"R{i}", applies_to_zones=True,
                                min_security_level=1, max_security_level=4) for i in range(1, 4)]
    db.add_all(reqs)

    def zone(name, target):
        z = SecurityZone(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, security_level_target=target)
        db.add(z)
        return z

    no_target, untouched = zone("no target", None), zone("untouched", 2)
    legacy_ok, legacy_bad, legacy_part = zone("legacy ok", 1), zone("legacy bad", 1), zone("legacy partial", 1)
    assessed_ok, assessed_bad = zone("assessed ok", 1), zone("assessed bad", 1)
    db.flush()
    for z, statuses in ((legacy_ok, ["compliant"] * 3), (legacy_bad, ["non_compliant"] * 3), (legacy_part, ["compliant", "non_compliant", "partial"])):
        for r, st in zip(reqs, statuses):
            db.add(SecurityRequirementCompliance(tenant_id=w.tenant.id, requirement_id=r.id, zone_id=z.id, compliance_status=st))
    for z, st in ((assessed_ok, "compliant"), (assessed_bad, "non_compliant")):
        for r in reqs:
            db.add(SRAssessment(tenant_id=w.tenant.id, sr_id=r.id, object_type="zone", object_id=z.id, status=st))
    db.commit()

    zones = db.query(SecurityZone).filter(SecurityZone.tenant_id == w.tenant.id).all()
    one_by_one = {z.id: Engine.calculate_zone_compliance_status(db, z) for z in zones}
    counter, stop = _count_queries(db)
    batched = Engine.calculate_zone_compliance_statuses(db, zones)
    stop()
    assert batched == one_by_one
    assert one_by_one[no_target.id] == one_by_one[untouched.id] == "not_assessed"
    assert len(set(one_by_one.values())) >= 2          # the comparison covers more than the trivial case
    assert counter["n"] <= 4                           # requirements, assessments, legacy records
