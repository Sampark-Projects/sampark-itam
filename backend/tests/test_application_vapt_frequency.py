"""VAPT frequency of an application: every <number> months (month is the only unit and the default). The rules, and the last / next VAPT it gives."""
from datetime import date, timedelta

import pytest

from app.services import application_logic as al
from app.services import application_security_logic as sl
from app.services.local_time import local_today

from tests.test_api_ot_modules import _audit, db  # noqa: F401  (db is the fixture)
from tests.test_application_security import _setup


def test_frequency_rules():
    assert sl.clean_frequency(None, None) == (None, None) and sl.clean_frequency("", " ") == (None, None)
    assert sl.clean_frequency(6, "month") == (6, "month") and sl.clean_frequency(6, None) == (6, "month")  # month is the default
    assert sl.clean_frequency(None, "month") == (None, None)  # a unit alone means no frequency
    assert sl.clean_frequency(12.0, "month") == (12, "month")
    for value, unit in ((0, "month"), (-1, "month"), (1.5, "month"), (True, "month"), ("6", "month"),
                        (6, "week"), (6, "Month"), (6, "year"), (121, "month")):  # year is no longer a unit
        with pytest.raises(sl.SecurityInputError):
            sl.clean_frequency(value, unit)
    assert sl.clean_frequency(120, "month") == (120, "month")


def test_application_cleaning_keeps_the_frequency_optional():
    assert al.clean_application({"name": "x"})["vapt_frequency_value"] is None
    out = al.clean_application({"name": "x", "vapt_frequency_value": 3, "vapt_frequency_unit": "month"})
    assert (out["vapt_frequency_value"], out["vapt_frequency_unit"]) == (3, "month")
    assert al.clean_application({"name": "x", "vapt_frequency_value": 3})["vapt_frequency_unit"] == "month"  # month is the default
    assert al.clean_application({"name": "x", "vapt_frequency_unit": "month"})["vapt_frequency_value"] is None
    for bad in ({"vapt_frequency_unit": "year", "vapt_frequency_value": 1}, {"vapt_frequency_value": 0, "vapt_frequency_unit": "month"},
                {"vapt_frequency_value": 2, "vapt_frequency_unit": "week"}):
        with pytest.raises(al.ApplicationInputError):
            al.clean_application({"name": "x", **bad})


def test_next_due_from_frequency():
    assert sl.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert sl.add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert sl.add_months(date(2026, 11, 20), 3) == date(2027, 2, 20)
    assert sl.next_due_from_frequency(date(2026, 10, 20), 6, "month") == date(2027, 4, 20)
    assert sl.next_due_from_frequency(date(2026, 10, 20), 24, "month") == date(2028, 10, 20)
    assert sl.next_due_from_frequency(None, 6, "month") is None and sl.next_due_from_frequency(date(2026, 10, 20), None, None) is None


def test_test_date_cannot_be_in_the_future(db):
    today = date(2026, 11, 25)
    assert sl.clean_assessment({"test_date": today}, today)["test_date"] == today
    with pytest.raises(sl.SecurityInputError):
        sl.clean_assessment({"test_date": date(2026, 11, 26)}, today)
    w, c, app, base = _setup(db)
    soon = (local_today() + timedelta(days=1)).isoformat()
    assert c.post(f"{base}/vapt", json={"test_date": soon}).status_code == 400
    assert c.post(f"{base}/vapt", json={"test_date": local_today().isoformat()}).status_code == 200
    made = c.post(f"{base}/vapt", json={}).json()
    assert c.put(f"{base}/vapt/{made['id']}", json={"test_date": soon}).status_code == 400


def test_application_frequency_api_and_next_vapt(db):
    w, c, app, base = _setup(db)
    # optional: an application without a frequency has a last VAPT but no next one
    assert app["vapt_frequency_value"] is None and app["next_vapt_due"] is None
    assert c.post(f"{base}/vapt", json={"test_date": "2026-10-20"}).status_code == 200
    summary = c.get(f"{base}/security-summary").json()
    assert summary["last_vapt_date"] == "2026-10-20" and summary["next_vapt_due"] is None

    # set the frequency on the application: the next VAPT is the last test date + 6 months
    body = {"name": "Billing", "vapt_frequency_value": 6, "vapt_frequency_unit": "month"}
    upd = c.put(base, json=body)
    assert upd.status_code == 200
    got = upd.json()
    assert (got["vapt_frequency_value"], got["vapt_frequency_unit"]) == (6, "month")
    assert got["last_vapt_date"] == "2026-10-20" and got["next_vapt_due"] == "2027-04-20"
    assert c.get(base).json()["next_vapt_due"] == "2027-04-20"
    summary = c.get(f"{base}/security-summary").json()
    assert summary["next_vapt_due"] == "2027-04-20" and summary["vapt_frequency_unit"] == "month" and summary["next_vapt_overdue"] is False

    # a newer test moves it; an older one does not; the list shows the same
    assert c.post(f"{base}/vapt", json={"test_date": "2026-11-01"}).status_code == 200
    assert c.post(f"{base}/vapt", json={"test_date": "2026-01-01"}).status_code == 200
    assert c.get(base).json()["next_vapt_due"] == "2027-05-01"
    listed = c.get("/applications").json()["items"][0]
    assert listed["last_vapt_date"] == "2026-11-01" and listed["next_vapt_due"] == "2027-05-01"

    # change the frequency: the next date follows; clear it: no next date
    assert c.put(base, json={**body, "vapt_frequency_value": 12}).json()["next_vapt_due"] == "2027-11-01"  # the unit is month by default
    cleared = c.put(base, json={"name": "Billing"}).json()
    assert cleared["vapt_frequency_value"] is None and cleared["next_vapt_due"] is None and cleared["last_vapt_date"] == "2026-11-01"

    # a positive whole number of months; month is the only unit
    for bad in ({"vapt_frequency_value": 1, "vapt_frequency_unit": "year"}, {"vapt_frequency_value": 0, "vapt_frequency_unit": "month"},
                {"vapt_frequency_value": -2, "vapt_frequency_unit": "month"}, {"vapt_frequency_value": 3, "vapt_frequency_unit": "week"},
                {"vapt_frequency_value": 121}):
        assert c.put(base, json={"name": "Billing", **bad}).status_code == 400, bad
    assert c.put(base, json={"name": "Billing", "vapt_frequency_value": 1.5, "vapt_frequency_unit": "month"}).status_code == 422
    # the assessments carry no frequency or next date of their own, and the audit trail carries the application's frequency
    vapt = c.get(f"{base}/vapt").json()[0]
    assert "frequency_value" not in vapt and "next_due_date" not in vapt
    assert any('"vapt_frequency_value": 12' in str(e.new_data) for e in _audit(db, "Application"))
