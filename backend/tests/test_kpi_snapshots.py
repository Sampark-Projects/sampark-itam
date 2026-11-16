"""Daily KPI snapshots and the trend endpoint."""
from datetime import timedelta

from app.models import KpiSnapshot
from app.services import kpi_snapshot_service as ks
from app.services.local_time import local_today

from tests.test_api_ot_modules import ADMIN_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS, World, client_for, db  # noqa: F401


def test_snapshot_is_idempotent_per_day(db):
    w = World(db)
    n = ks.take_snapshot(db, w.tenant.id)
    assert n == 2  # the whole tenant and the one site
    ks.take_snapshot(db, w.tenant.id)
    assert db.query(KpiSnapshot).filter(KpiSnapshot.tenant_id == w.tenant.id).count() == 2
    whole = db.query(KpiSnapshot).filter(KpiSnapshot.tenant_id == w.tenant.id, KpiSnapshot.site_id.is_(None)).one()
    assert whole.metrics["assets_total"] == 1


def test_trend_has_gaps_and_todays_point(db):
    w = World(db)
    old = local_today() - timedelta(days=2)
    db.add(KpiSnapshot(tenant_id=w.tenant.id, site_id=None, day=old, metrics={"assets_total": 5, "open_changes": 2}))
    db.commit()
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    r = admin.get("/reports/trend", params={"days": 5}).json()
    assert len(r["days"]) == 5 and r["days"][-1] == local_today().isoformat()
    assets = r["series"]["assets_total"]
    assert assets[-3] == 5 and assets[-2] is None and assets[-1] == 1  # a missing day stays empty
    site = admin.get("/reports/trend", params={"days": 3, "site_id": str(w.site.id)}).json()
    assert site["series"]["assets_total"][-1] == 1


def test_todays_point_follows_the_live_numbers(db):
    from app.models import Asset
    import uuid
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    assert admin.get("/reports/trend", params={"days": 2}).json()["series"]["assets_total"][-1] == 1
    db.add(Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Another", site_id=w.site.id,
                 asset_type_id=w.type.id, status_id=w.active.id))
    db.commit()
    assert admin.get("/reports/trend", params={"days": 2}).json()["series"]["assets_total"][-1] == 2  # not a stale morning value


def test_trend_is_tenant_scoped_and_needs_reports_access(db):
    a, b = World(db, "A"), World(db, "B")
    ks.take_snapshot(db, b.tenant.id)
    admin_a = client_for(db, a.user(ADMIN_DEFAULT_PERMISSIONS))
    assert admin_a.get("/reports/trend", params={"site_id": str(b.site.id)}).json()["series"]["assets_total"][-1] is None
    assert client_for(db, a.user({})).get("/reports/trend").status_code == 403


def test_all_tenants_run_prunes_old(db):
    w = World(db)
    db.add(KpiSnapshot(tenant_id=w.tenant.id, site_id=None, day=local_today() - timedelta(days=ks.KEEP_DAYS + 5), metrics={}))
    db.commit()
    assert ks.take_snapshots_all_tenants(db)["failed"] == 0
    assert db.query(KpiSnapshot).filter(KpiSnapshot.day < local_today() - timedelta(days=ks.KEEP_DAYS)).count() == 0
