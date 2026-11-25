"""The site hierarchy: a company / plant site can hold unit sites (Site.parent_id).

Filtering by a plant includes its units, the dashboard can roll units up into their plant, and a
naming rule or KPI target set on a plant applies to its units unless a unit has its own.
The pure functions take a {site_id: parent_id} map so they can be tested without a database.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import Site

MAX_DEPTH = 20  # guards against a loop in bad data


def parent_map(db: Session, tenant_id) -> Dict:
    """{site_id: parent_id} for every site of the tenant (trashed ones too, so old assets still resolve)."""
    return {sid: pid for sid, pid in db.query(Site.id, Site.parent_id).filter(Site.tenant_id == tenant_id).all()}


def ancestors(parents: Dict, site_id) -> List:
    """[site, parent, grandparent, ...] starting with the site itself."""
    chain, current = [], site_id
    while current is not None and current not in chain and len(chain) < MAX_DEPTH:
        chain.append(current)
        current = parents.get(current)
    return chain


def descendants(parents: Dict, site_id) -> List:
    """The site and every site below it."""
    children: Dict = {}
    for sid, pid in parents.items():
        if pid is not None:
            children.setdefault(pid, []).append(sid)
    out, queue = [], [site_id]
    while queue and len(out) < 10000:
        current = queue.pop()
        if current in out:
            continue
        out.append(current)
        queue.extend(children.get(current, []))
    return out


def top(parents: Dict, site_id):
    """The top-level site (plant or company) a site belongs to."""
    chain = ancestors(parents, site_id)
    return chain[-1] if chain else None


def subtree_ids(db: Session, tenant_id, site_id) -> List:
    """For a filter: the site and all its units."""
    return descendants(parent_map(db, tenant_id), site_id)


def nearest(parents: Dict, site_id, values: Dict) -> Optional[object]:
    """The value set on the closest site up the chain (the site itself first)."""
    for sid in ancestors(parents, site_id):
        if sid in values:
            return values[sid]
    return None
