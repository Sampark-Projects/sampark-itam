"""Paging and optimistic concurrency for the external API (no database)."""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def clamp(skip: int, limit: int):
    limit = DEFAULT_LIMIT if limit is None else int(limit)
    return max(0, int(skip or 0)), max(1, min(limit, MAX_LIMIT))


def page(items: List, total: int, skip: int, limit: int) -> Dict:
    """The response shape of every paged list: total, the window asked for, and whether more follow."""
    return {"total": total, "skip": skip, "limit": limit, "has_more": skip + len(items) < total, "items": items}


def page_list(items: List, skip: int, limit: int) -> Dict:
    skip, limit = clamp(skip, limit)
    return page(items[skip:skip + limit], len(items), skip, limit)


def _plain(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, float):
        return repr(value)
    return value


def etag(values: Dict) -> str:
    """A weak ETag over the given values: it changes whenever one of them changes."""
    body = json.dumps({k: _plain(v) for k, v in sorted(values.items())}, sort_keys=True, default=str)
    return 'W/"' + hashlib.sha256(body.encode("utf-8")).hexdigest()[:24] + '"'


def if_match_ok(header: Optional[str], current: str) -> bool:
    """No If-Match header, '*', or one of the listed tags equal to the current one (weak comparison)."""
    if header is None or not header.strip():
        return True
    tags = [t.strip() for t in header.split(",")]
    if "*" in tags:
        return True
    strip = lambda t: t[2:] if t.startswith("W/") else t
    return any(strip(t) == strip(current) for t in tags)
