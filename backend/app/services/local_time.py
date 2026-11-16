"""The plant's calendar day.

Expiry alerts, due and overdue maintenance, received dates and similar day-based rules use the date
where the plant is, not the server's UTC date (a UTC server in India would roll the day over at
05:30 local time). Set APP_TIMEZONE to an IANA name such as Asia/Kolkata; the default is UTC.
"""
import logging
import os
from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def plant_zone() -> ZoneInfo:
    name = (os.getenv("APP_TIMEZONE") or "UTC").strip()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.error("APP_TIMEZONE %r is not a known time zone; using UTC", name)
        return ZoneInfo("UTC")


def local_now() -> datetime:
    return datetime.now(plant_zone())


def local_today() -> date:
    """Today's date at the plant."""
    return local_now().date()
