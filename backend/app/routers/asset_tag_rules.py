import uuid
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import AssetTagRule, AssetType, Site, User
from app.schemas.asset_tag_rule import AssetTagRule as AssetTagRuleSchema
from app.schemas.asset_tag_rule import AssetTagRuleCreate, AssetTagRuleUpdate
from app.services import tag_standard
from app.services.auth import get_current_user
from app.services.audit_trail import AuditContext, snapshot
from app.services.rbac import require_section_access

router = APIRouter(
    prefix="/asset-tag-rules",
    tags=["asset_tag_rules"],
    dependencies=[Depends(require_section_access("asset_types"))],
)


def _out(db: Session, rule: AssetTagRule) -> AssetTagRuleSchema:
    # a rule that is not tied to a site shows a placeholder where {SITE} will go
    code = "SITE"
    if rule.site_id:
        code = db.query(Site.code).filter(Site.id == rule.site_id).scalar() or code
    item = AssetTagRuleSchema.model_validate(rule)
    item.example = tag_standard.render(rule.pattern, rule.next_seq or 1, code)
    return item


def _get_rule(db: Session, tenant_id, rule_id) -> AssetTagRule:
    rule = db.query(AssetTagRule).filter(AssetTagRule.id == rule_id, AssetTagRule.tenant_id == tenant_id).first()
    if not rule:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.TAG_RULE_NOT_FOUND)
    return rule


def _check_scope(db: Session, tenant_id, data, exclude_rule_id=None) -> None:
    """The type and site must belong to the tenant; one active rule per scope."""
    if data.asset_type_id:
        found = db.query(AssetType.id).filter(
            AssetType.id == data.asset_type_id,
            (AssetType.tenant_id == tenant_id) | (AssetType.tenant_id.is_(None)),
        ).first()
        if not found:
            raise ErrorCodeException(status_code=400, error_code=ErrorCode.INVALID_TAG_RULE, detail="Unknown asset type")
    if data.site_id:
        if not db.query(Site.id).filter(Site.id == data.site_id, Site.tenant_id == tenant_id).first():
            raise ErrorCodeException(status_code=400, error_code=ErrorCode.INVALID_TAG_RULE, detail="Unknown site")
    if data.is_active:
        clash = db.query(AssetTagRule).filter(
            AssetTagRule.tenant_id == tenant_id,
            AssetTagRule.is_active.is_(True),
            AssetTagRule.asset_type_id == data.asset_type_id,
            AssetTagRule.site_id == data.site_id,
        )
        if data.asset_type_id is None:
            clash = clash.filter(AssetTagRule.asset_type_id.is_(None))
        if data.site_id is None:
            clash = clash.filter(AssetTagRule.site_id.is_(None))
        if exclude_rule_id:
            clash = clash.filter(AssetTagRule.id != exclude_rule_id)
        if clash.first():
            raise ErrorCodeException(
                status_code=409, error_code=ErrorCode.INVALID_TAG_RULE,
                detail="An active rule already exists for this asset type and site",
            )


@router.get("", response_model=List[AssetTagRuleSchema])
def list_rules(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rules = (
        db.query(AssetTagRule)
        .filter(AssetTagRule.tenant_id == current_user.tenant_id)
        .order_by(AssetTagRule.created_at)
        .all()
    )
    return [_out(db, r) for r in rules]


@router.post("", response_model=AssetTagRuleSchema)
def create_rule(data: AssetTagRuleCreate, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_scope(db, current_user.tenant_id, data)
    rule = AssetTagRule(tenant_id=current_user.tenant_id, **data.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    audit.log("create", "AssetTagRule", rule.id, f"Created tag rule '{rule.pattern}'", None, snapshot(rule, ("asset_type_id", "site_id", "pattern", "next_seq", "is_active")))
    return _out(db, rule)


@router.put("/{rule_id}", response_model=AssetTagRuleSchema)
def update_rule(
    rule_id: uuid.UUID, data: AssetTagRuleUpdate, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    rule = _get_rule(db, current_user.tenant_id, rule_id)
    old = snapshot(rule, ("asset_type_id", "site_id", "pattern", "next_seq", "is_active"))
    _check_scope(db, current_user.tenant_id, data, exclude_rule_id=rule.id)
    for key, value in data.model_dump(exclude_unset=True).items():
        if key == "next_seq" and value is None:
            continue
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    audit.log("update", "AssetTagRule", rule.id, f"Updated tag rule '{rule.pattern}'", old, snapshot(rule, ("asset_type_id", "site_id", "pattern", "next_seq", "is_active")))
    return _out(db, rule)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # tags already handed out stay on their assets; only the rule goes
    rule = _get_rule(db, current_user.tenant_id, rule_id)
    old = snapshot(rule, ("asset_type_id", "site_id", "pattern", "next_seq", "is_active"))
    db.delete(rule)
    db.commit()
    audit.log("delete", "AssetTagRule", rule_id, f"Deleted tag rule '{old['pattern']}'", old, None)
