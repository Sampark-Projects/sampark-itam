"""The plant calendar day comes from APP_TIMEZONE."""
from datetime import datetime, timezone

from app.services import local_time


def _with_zone(monkeypatch, name):
    monkeypatch.setenv("APP_TIMEZONE", name)
    local_time.plant_zone.cache_clear()


def test_plant_day_differs_from_utc_near_midnight(monkeypatch):
    # 20:46 UTC on 14 Nov is already 15 Nov in India
    fixed = datetime(2026, 11, 14, 20, 46, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed

    monkeypatch.setattr(local_time, "datetime", Clock)
    _with_zone(monkeypatch, "Asia/Kolkata")
    assert str(local_time.local_today()) == "2026-11-15"
    _with_zone(monkeypatch, "UTC")
    assert str(local_time.local_today()) == "2026-11-14"
    local_time.plant_zone.cache_clear()


def test_unknown_zone_falls_back_to_utc(monkeypatch):
    _with_zone(monkeypatch, "Mars/Olympus")
    assert local_time.plant_zone().key == "UTC"
    monkeypatch.delenv("APP_TIMEZONE")
    local_time.plant_zone.cache_clear()
    assert local_time.plant_zone().key == "UTC"
    local_time.plant_zone.cache_clear()
