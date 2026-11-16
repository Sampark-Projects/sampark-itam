"""Database side of the asset tag standard: pick the rule, generate the next tag, validate a tag."""
import uuid
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, AssetTagRule, Site
from app.services import site_tree, tag_standard

MAX_SKIPS = 10000  # safety stop when the counter keeps hitting tags that already exist


def clean_tag(tag: Optional[str]) -> Optional[str]:
    tag = (tag or "").strip()
    return tag or None


def _specificity(rule: AssetTagRule, chain) -> tuple:
    """Type match first; then the closest site (the asset's own site, then its plant, ...); a rule
    without a site comes last."""
    distance = chain.index(rule.site_id) if rule.site_id in chain else len(chain)
    return (1 if rule.asset_type_id else 0, -distance)


def find_rule(db: Session, tenant_id: uuid.UUID, asset_type_id, site_id) -> Optional[AssetTagRule]:
    """Most specific active rule: type+site, then type, then site, then the catch-all."""
    rules = (
        db.query(AssetTagRule)
        .filter(AssetTagRule.tenant_id == tenant_id, AssetTagRule.is_active.is_(True))
        .all()
    )
    chain = site_tree.ancestors(site_tree.parent_map(db, tenant_id), site_id) if site_id else []
    fitting = [
        r for r in rules
        if (r.asset_type_id is None or r.asset_type_id == asset_type_id)
        and (r.site_id is None or r.site_id in chain)
    ]
    if not fitting:
        return None
    # equal specificity: the oldest rule wins, so the choice is stable
    return sorted(fitting, key=lambda r: tuple(-x for x in _specificity(r, chain)) + (r.created_at.timestamp() if r.created_at else 0.0,))[0]


def site_code(db: Session, tenant_id: uuid.UUID, site_id) -> Optional[str]:
    if not site_id:
        return None
    return db.query(Site.code).filter(Site.id == site_id, Site.tenant_id == tenant_id).scalar()


def tag_in_use(db: Session, tenant_id: uuid.UUID, tag: str, exclude_asset_id=None) -> bool:
    """Case-insensitive, and trashed assets count too (restoring one must not create a duplicate)."""
    query = db.query(Asset.id).filter(Asset.tenant_id == tenant_id, func.lower(func.btrim(Asset.tag)) == tag.strip().lower())
    if exclude_asset_id is not None:
        query = query.filter(Asset.id != exclude_asset_id)
    return db.query(query.exists()).scalar()


def _next_free(db: Session, tenant_id: uuid.UUID, rule: AssetTagRule, code: Optional[str]):
    """Walk the counter until the rendered tag is free. Returns (tag, counter value to store)."""
    seq = rule.next_seq or 1
    for _ in range(MAX_SKIPS):
        tag = tag_standard.render(rule.pattern, seq, code)
        seq += 1
        if not tag_in_use(db, tenant_id, tag):
            return tag, seq
    raise ErrorCodeException(status_code=409, error_code=ErrorCode.INVALID_TAG_RULE)


def preview_tag(db: Session, tenant_id: uuid.UUID, asset_type_id, site_id) -> Optional[dict]:
    """What the next tag would be, without using it up."""
    rule = find_rule(db, tenant_id, asset_type_id, site_id)
    if not rule:
        return None
    # no site picked yet: show a placeholder where {SITE} will go
    tag, _ = _next_free(db, tenant_id, rule, site_code(db, tenant_id, site_id) or "SITE")
    return {"rule_id": rule.id, "rule_name": rule.name, "pattern": rule.pattern, "next_tag": tag}


def generate_tag(db: Session, tenant_id: uuid.UUID, asset_type_id, site_id) -> Optional[str]:
    """Next tag for a new asset, or None when no rule applies. The counter is stored in the
    caller transaction: it is committed together with the asset."""
    found = find_rule(db, tenant_id, asset_type_id, site_id)
    if not found:
        return None
    # lock the rule row so two simultaneous creations cannot take the same number
    rule = db.query(AssetTagRule).filter(AssetTagRule.id == found.id).with_for_update().first()
    tag, new_seq = _next_free(db, tenant_id, rule, site_code(db, tenant_id, site_id))
    rule.next_seq = new_seq
    return tag


def validate_tag(db: Session, tenant_id: uuid.UUID, tag: str, asset_type_id, site_id, exclude_asset_id=None) -> None:
    """A typed tag must be unique and, when a rule applies, follow its pattern."""
    if tag_in_use(db, tenant_id, tag, exclude_asset_id):
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.DUPLICATE_ASSET_TAG)
    rule = find_rule(db, tenant_id, asset_type_id, site_id)
    if rule and not tag_standard.matches(rule.pattern, tag, site_code(db, tenant_id, site_id)):
        raise ErrorCodeException(
            status_code=400,
            error_code=ErrorCode.INVALID_ASSET_TAG,
            detail=f"Expected pattern {rule.pattern} (for example {tag_standard.example(rule.pattern, site_code(db, tenant_id, site_id))})",
        )
