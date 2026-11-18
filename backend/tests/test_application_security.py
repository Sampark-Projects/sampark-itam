"""Application security: VAPT assessments and findings, pure rules and API."""
import uuid
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import ApplicationFinding, Asset, Vulnerability
from app.routers import application_hosting, application_security, applications
from app.services import application_security_logic as sl
from app.services.auth import get_current_user
from app.services.local_time import local_today
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)

TODAY = date(2026, 11, 17)


# --- pure rules -------------------------------------------------------------------------------

def test_numbers():
    assert sl.format_vapt(19) == "VAPT-0019" and sl.format_finding(8841) == "VULN-8841"


def test_assessment_cleaning_and_rules():
    out = sl.clean_assessment({"assessor": "  CERT-In   auditor ", "methodology": "grey_box", "test_date": date(2026, 10, 20),
                               "next_due_date": date(2027, 4, 20), "report_url": "https://reports.example/vapt.pdf"})
    assert out["assessor"] == "CERT-In auditor" and out["assessment_type"] == "web_app" and out["status"] == "scheduled"
    for bad in ({"assessment_type": "x"}, {"methodology": "pink_box"}, {"status": "done"}, {"overall_posture": "meh"},
                {"report_url": "ftp://x"}, {"test_date": date(2026, 5, 1), "next_due_date": date(2026, 4, 1)},
                {"status": "closed"}, {"scope": "x" * 5001}):
        with pytest.raises(sl.SecurityInputError):
            sl.clean_assessment(bad)


def test_finding_defaults_the_deadline_from_the_severity():
    assert sl.default_sla_due("critical", TODAY) == TODAY + timedelta(days=7)
    out = sl.clean_finding({"title": " Outdated  OpenSSL ", "severity": "high", "cvss_score": 8.24}, TODAY)
    assert out["title"] == "Outdated OpenSSL" and out["cvss_score"] == 8.2 and out["discovered_on"] == TODAY
    assert out["sla_due_date"] == TODAY + timedelta(days=30) and out["remediation_status"] == "open" and out["exploitability"] == "none_known"
    given = sl.clean_finding({"title": "x", "severity": "low", "discovered_on": TODAY, "sla_due_date": TODAY + timedelta(days=3)}, TODAY)
    assert given["sla_due_date"] == TODAY + timedelta(days=3)


@pytest.mark.parametrize("bad", [
    {"title": " ", "severity": "low"}, {"title": "x"}, {"title": "x", "severity": "scary"}, {"title": "x", "severity": "low", "cvss_score": 11},
    {"title": "x", "severity": "low", "cvss_score": True}, {"title": "x", "severity": "low", "exploitability": "meh"},
    {"title": "x", "severity": "low", "discovered_on": TODAY, "sla_due_date": TODAY - timedelta(days=1)},
    {"title": "x", "severity": "low", "retest_result": "passed"},  # a result needs a date
    {"title": "x", "severity": "low", "remediation_status": "verified_fixed"},
    {"title": "x", "severity": "low", "remediation_status": "verified_fixed", "retest_date": TODAY, "retest_result": "failed"},
    {"title": "x", "severity": "low", "remediation_status": "risk_accepted"},
])
def test_invalid_findings_are_refused(bad):
    with pytest.raises(sl.SecurityInputError):
        sl.clean_finding(bad, TODAY)


def test_fixed_and_accepted_findings_need_their_evidence():
    fixed = sl.clean_finding({"title": "x", "severity": "low", "remediation_status": "verified_fixed", "retest_date": TODAY, "retest_result": "passed"}, TODAY)
    accepted = sl.clean_finding({"title": "x", "severity": "low", "remediation_status": "risk_accepted", "exception_id": "EXC-2026-14"}, TODAY)
    assert fixed["remediation_status"] == "verified_fixed" and accepted["exception_id"] == "EXC-2026-14"


def test_flags_and_posture():
    past, future = TODAY - timedelta(days=1), TODAY + timedelta(days=1)
    assert sl.finding_flags("open", past, None, TODAY) == {"open": True, "overdue": True, "exception_expired": False}
    assert sl.finding_flags("patch_assigned", future, None, TODAY)["overdue"] is False
    assert sl.finding_flags("verified_fixed", past, None, TODAY) == {"open": False, "overdue": False, "exception_expired": False}
    assert sl.finding_flags("risk_accepted", past, past, TODAY)["exception_expired"] is True
    assert sl.posture_suggestion({"high": 1}) == "fail" and sl.posture_suggestion({"medium": 2}) == "conditional_pass"
    assert sl.posture_suggestion({}) == "pass" and sl.posture_suggestion({"info": 3}) == "pass"


def test_last_and_next_vapt():
    a = [{"test_date": date(2026, 4, 1), "next_due_date": date(2026, 10, 1), "number": 1},
         {"test_date": date(2026, 10, 20), "next_due_date": date(2027, 4, 20), "number": 2}]
    assert sl.last_and_next(a) == (date(2026, 10, 20), date(2027, 4, 20))  # the newer test replaces the older due date
    scheduled = a + [{"test_date": None, "next_due_date": date(2026, 12, 1), "number": 3}]
    assert sl.last_and_next(scheduled) == (date(2026, 10, 20), date(2026, 12, 1))
    assert sl.last_and_next([]) == (None, None)


# --- API --------------------------------------------------------------------------------------

def _client(db, user) -> TestClient:
    api = FastAPI()
    for module in (applications, application_hosting, application_security):
        api.include_router(module.router)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def _setup(db, label="A"):
    w = World(db, label)
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "admin"))
    app = c.post("/applications", json={"name": "Billing"}).json()
    return w, c, app, f"/applications/{app['id']}"


def test_vapt_lifecycle_with_scorecard_and_audit(db):
    w, c, app, base = _setup(db)
    made = c.post(f"{base}/vapt", json={"assessment_type": "api", "methodology": "grey_box", "assessor": "Internal Red Team",
                                        "scope": "https://company.com*", "status": "remediation", "test_date": "2026-10-20",
                                        "next_due_date": "2027-04-20", "overall_posture": "conditional_pass",
                                        "sign_off_by": "Vikram Mehta", "sign_off_date": "2026-10-25"})
    assert made.status_code == 200 and made.json()["code"] == "VAPT-0001" and made.json()["open_total"] == 0
    vapt = made.json()
    for severity, status in (("high", "open"), ("medium", "open"), ("medium", "patch_assigned"), ("low", "open")):
        assert c.post(f"{base}/findings", json={"title": f"{severity} issue", "severity": severity, "vapt_id": vapt["id"], "remediation_status": status}).status_code == 200
    c.post(f"{base}/findings", json={"title": "fixed", "severity": "critical", "vapt_id": vapt["id"], "remediation_status": "verified_fixed",
                                     "retest_date": "2026-11-01", "retest_result": "passed"})
    got = c.get(f"{base}/vapt").json()[0]
    assert got["open_findings"] == {"critical": 0, "high": 1, "medium": 2, "low": 1, "info": 0} and got["finding_total"] == 5
    assert got["suggested_posture"] == "fail" and got["overall_posture"] == "conditional_pass"  # the signer decides

    upd = c.put(f"{base}/vapt/{vapt['id']}", json={"assessment_type": "api", "status": "closed", "test_date": "2026-10-20"})
    assert upd.status_code == 200 and upd.json()["status"] == "closed" and upd.json()["sign_off_by"] is None
    assert c.put(f"{base}/vapt/{vapt['id']}", json={"status": "closed"}).status_code == 400
    assert c.put(f"{base}/vapt/{uuid.uuid4()}", json={}).status_code == 404
    second = c.post(f"{base}/vapt", json={}).json()
    assert second["code"] == "VAPT-0002"
    assert c.delete(f"{base}/vapt/{vapt['id']}").status_code == 204
    still = c.get(f"{base}/findings").json()
    assert still["total"] == 5 and all(f["vapt_code"] is None for f in still["items"])  # findings stay
    assert [a.action for a in _audit(db, "ApplicationVapt")] == ["create", "update", "create", "delete"]


def test_report_with_a_non_latin_file_name_downloads(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    w, c, app, base = _setup(db)
    vapt = c.post(f"{base}/vapt", json={}).json()
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    name = "VAPT – Q3 रिपोर्ट.pdf"  # en dash and Devanagari: outside Latin-1
    assert c.post(f"{base}/vapt/{vapt['id']}/report", files={"file": (name, pdf, "application/pdf")}).status_code == 200
    res = c.get(f"{base}/vapt/{vapt['id']}/report")
    assert res.status_code == 200 and res.content == pdf
    assert res.headers["content-disposition"].startswith("attachment; filename*=utf-8''")


def test_report_upload_download_replace_and_remove(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    w, c, app, base = _setup(db)
    vapt = c.post(f"{base}/vapt", json={}).json()
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    send = lambda name, data=pdf, mime="application/pdf": c.post(f"{base}/vapt/{vapt['id']}/report", files={"file": (name, data, mime)})
    assert send("x.exe", b"MZ\x90\x00", "application/x-msdownload").status_code == 400
    assert send("fake.pdf", b"not a pdf").status_code == 400
    up = send("../../VAPT_Billing_Oct2026_Final.pdf")
    assert up.status_code == 200 and up.json()["report_file"]["name"] == "VAPT_Billing_Oct2026_Final.pdf"
    stored = list((tmp_path / "uploads").rglob("*.pdf"))
    assert len(stored) == 1 and str(w.tenant.id) in str(stored[0])
    assert c.get(f"{base}/vapt/{vapt['id']}/report").content == pdf
    assert send("v2.pdf").json()["report_file"]["name"] == "v2.pdf" and len(list((tmp_path / "uploads").rglob("*.pdf"))) == 1
    assert c.delete(f"{base}/vapt/{vapt['id']}/report").json()["report_file"] is None
    assert list((tmp_path / "uploads").rglob("*.pdf")) == [] and c.get(f"{base}/vapt/{vapt['id']}/report").status_code == 404
    other = World(db, "B")
    assert _client(db, other.user(ADMIN_DEFAULT_PERMISSIONS)).get(f"{base}/vapt/{vapt['id']}/report").status_code == 404


def test_finding_rules_links_and_flags(db):
    w, c, app, base = _setup(db)
    web = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name="PROD-WEB-APP01", site_id=w.site.id, asset_type_id=w.type.id, status_id=w.active.id)
    stray = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name="NOT-LINKED", site_id=w.site.id, asset_type_id=w.type.id, status_id=w.active.id)
    db.add_all([web, stray, Vulnerability(id=uuid.uuid4(), title="OpenSSL", cve_id="CVE-2025-49112", severity="high", source="nvd")])
    db.commit()
    c.post(f"{base}/assets", json={"asset_id": str(web.id), "role": "web"})
    body = {"title": "Outdated OpenSSL Version on Web Server", "severity": "high", "cve_id": " cve-2025-49112 ", "cvss_score": 8.2,
            "discovery_source": "Qualys VMDR", "affected_asset_id": str(web.id), "affected_target": "10.24.112.45:443",
            "affected_component": "OpenSSL 3.0.11", "exploitability": "poc_available", "recommended_fix": "Upgrade OpenSSL to 3.0.15",
            "assigned_owner": "Linux Infra Team"}
    made = c.post(f"{base}/findings", json=body)
    assert made.status_code == 200
    f = made.json()
    assert f["code"] == "VULN-0001" and f["cve_id"] == "CVE-2025-49112" and f["vulnerability_id"] is not None  # linked to the catalogue
    assert f["affected_asset_name"] == "PROD-WEB-APP01" and f["open"] and not f["overdue"]
    assert f["sla_due_date"] == str(local_today() + timedelta(days=30))
    assert c.post(f"{base}/findings", json={**body, "affected_asset_id": str(stray.id)}).status_code == 400  # asset must be linked
    assert c.post(f"{base}/findings", json={**body, "vapt_id": str(uuid.uuid4())}).status_code == 400
    assert c.post(f"{base}/findings", json={"title": "CWE one", "severity": "low", "cve_id": "CWE-79"}).json()["vulnerability_id"] is None

    assert c.put(f"{base}/findings/{f['id']}", json={**body, "remediation_status": "verified_fixed"}).status_code == 400  # no retest
    fixed = c.put(f"{base}/findings/{f['id']}", json={**body, "remediation_status": "verified_fixed", "retest_date": "2026-11-22", "retest_result": "passed"})
    assert fixed.status_code == 200 and fixed.json()["open"] is False
    exc = c.post(f"{base}/findings", json={"title": "waived", "severity": "medium", "remediation_status": "risk_accepted",
                                           "exception_id": "EXC-2026-14", "exception_valid_until": "2020-01-31"}).json()
    assert exc["exception_expired"] is True and exc["open"] is False


def test_list_filters_order_and_summary(db):
    w, c, app, base = _setup(db)
    past = str(local_today() - timedelta(days=40))
    rows = [("c-open", "critical", {}), ("h-open", "high", {"discovered_on": past}), ("m-open", "medium", {}), ("l-open", "low", {"remediation_status": "retest_pending"}),
            ("m-fixed", "medium", {"remediation_status": "verified_fixed", "retest_date": past, "retest_result": "passed"})]
    for title, severity, extra in rows:
        assert c.post(f"{base}/findings", json={"title": title, "severity": severity, **extra}).status_code == 200
    titles = lambda **p: [i["title"] for i in c.get(f"{base}/findings", params=p).json()["items"]]
    assert titles() == ["c-open", "h-open", "m-open", "l-open", "m-fixed"]  # open first, most severe first
    assert titles(state="open") == ["c-open", "h-open", "m-open", "l-open"] and titles(state="closed") == ["m-fixed"]
    assert titles(overdue=True) == ["h-open"]  # discovered 40 days ago, due after 30
    assert titles(severity="medium") == ["m-open", "m-fixed"] and titles(remediation_status="retest_pending") == ["l-open"]
    assert titles(search="C-OPEN") == ["c-open"] and c.get(f"{base}/findings", params={"limit": 2}).json()["has_more"] is True
    assert c.get(f"{base}/findings", params={"severity": "bad"}).status_code == 422

    c.post(f"{base}/vapt", json={"test_date": "2026-10-20", "next_due_date": "2027-04-20", "status": "closed"})
    summary = c.get(f"{base}/security-summary").json()
    assert summary["open"] == {"critical": 1, "high": 1, "medium": 1, "low": 1, "info": 0} and summary["open_total"] == 4
    assert summary["overdue"] == 1 and summary["assessments"] == 1 and summary["suggested_posture"] == "fail"
    assert summary["last_vapt_date"] == "2026-10-20" and summary["next_vapt_due"] == "2027-04-20" and summary["next_vapt_overdue"] is False


def test_other_tenants_and_permissions(db):
    w, c, app, base = _setup(db)
    finding = c.post(f"{base}/findings", json={"title": "x", "severity": "low"}).json()
    vapt = c.post(f"{base}/vapt", json={}).json()
    outsider = _client(db, World(db, "B").user(ADMIN_DEFAULT_PERMISSIONS))
    for method, path in (("get", "vapt"), ("get", "findings"), ("get", "security-summary")):
        assert getattr(outsider, method)(f"{base}/{path}").status_code == 404
    assert outsider.put(f"{base}/findings/{finding['id']}", json={"title": "y", "severity": "low"}).status_code == 404
    assert outsider.delete(f"{base}/vapt/{vapt['id']}").status_code == 404

    viewer = _client(db, w.user({**ADMIN_DEFAULT_PERMISSIONS, "applications": 1}, "viewer"))
    editor = _client(db, w.user({**EDITOR_DEFAULT_PERMISSIONS, "applications": 2}, "editor"))
    assert viewer.get(f"{base}/findings").status_code == 200 and viewer.post(f"{base}/findings", json={"title": "y", "severity": "low"}).status_code == 403
    assert viewer.post(f"{base}/vapt", json={}).status_code == 403
    assert editor.post(f"{base}/vapt", json={}).status_code == 200
    assert editor.delete(f"{base}/findings/{finding['id']}").status_code == 403  # deleting needs level 3
    assert c.delete(f"{base}/findings/{finding['id']}").status_code == 204
    assert db.query(ApplicationFinding).count() == 0


def test_deleting_an_application_removes_its_report_files(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    w, c, app, base = _setup(db)
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    for _ in range(2):
        vapt = c.post(f"{base}/vapt", json={}).json()
        assert c.post(f"{base}/vapt/{vapt['id']}/report", files={"file": ("r.pdf", pdf, "application/pdf")}).status_code == 200
    assert len(list((tmp_path / "uploads").rglob("*.pdf"))) == 2
    assert c.delete(base).status_code == 204
    assert list((tmp_path / "uploads").rglob("*.pdf")) == []
