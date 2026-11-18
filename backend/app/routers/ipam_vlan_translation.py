"""IPAM VLAN translation policies and their rules (NetBox: VLAN translation policy / rule). A policy is a named set of
local-to-remote VLAN ID translations that can be applied to asset interfaces. Uses the `ipam` RBAC section."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AssetInterface, IpamVlanTranslationPolicy, IpamVlanTranslationRule, User
from app.services import api_paging
from app.services import ipam_logic as il
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.ipam_service import bad, get_owned, not_found
from app.services.rbac import require_section_access

router = APIRouter(prefix="/ipam", tags=["ipam"], dependencies=[Depends(require_section_access("ipam"))])

POLICY_FIELDS = ("name", "description", "comments")
RULE_FIELDS = ("policy_id", "local_vid", "remote_vid", "description")


class PolicyIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    comments: Optional[str] = None


class RuleIn(BaseModel):
    local_vid: int
    remote_vid: int
    description: Optional[str] = None


def _clean(fn, data: BaseModel) -> dict:
    try:
        return fn(data.model_dump())
    except il.IpamInputError as exc:
        raise bad(str(exc))


def _rule_out(r: IpamVlanTranslationRule) -> dict:
    return {"id": r.id, "policy_id": r.policy_id, "local_vid": r.local_vid, "remote_vid": r.remote_vid, "description": r.description,
            "created_at": r.created_at, "updated_at": r.updated_at}


def _policy_items(db: Session, rows) -> list:
    ids = [r.id for r in rows]
    rules: dict = {i: 0 for i in ids}
    used: dict = {i: 0 for i in ids}
    if ids:
        rules.update(dict(db.query(IpamVlanTranslationRule.policy_id, func.count(IpamVlanTranslationRule.id)).filter(
            IpamVlanTranslationRule.policy_id.in_(ids)).group_by(IpamVlanTranslationRule.policy_id).all()))
        used.update(dict(db.query(AssetInterface.vlan_translation_policy_id, func.count(AssetInterface.id)).filter(
            AssetInterface.vlan_translation_policy_id.in_(ids)).group_by(AssetInterface.vlan_translation_policy_id).all()))
    return [{"id": r.id, **snapshot(r, POLICY_FIELDS), "rule_count": rules[r.id], "interface_count": used[r.id],
             "created_at": r.created_at, "updated_at": r.updated_at} for r in rows]


def _name_taken(db: Session, tenant_id, name: str, exclude_id=None) -> bool:
    query = db.query(IpamVlanTranslationPolicy.id).filter(IpamVlanTranslationPolicy.tenant_id == tenant_id,
                                                          func.lower(IpamVlanTranslationPolicy.name) == name.lower())
    if exclude_id:
        query = query.filter(IpamVlanTranslationPolicy.id != exclude_id)
    return query.first() is not None


@router.get("/vlan-translation-policies")
def list_policies(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every policy of the tenant (a short list, so not paged), by name."""
    rows = db.query(IpamVlanTranslationPolicy).filter(IpamVlanTranslationPolicy.tenant_id == current_user.tenant_id).order_by(
        func.lower(IpamVlanTranslationPolicy.name)).all()
    return _policy_items(db, rows)


@router.post("/vlan-translation-policies")
def create_policy(data: PolicyIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _clean(il.clean_vlan_policy, data)
    if _name_taken(db, current_user.tenant_id, values["name"]):
        raise bad("A VLAN translation policy with this name already exists", 409)
    row = IpamVlanTranslationPolicy(tenant_id=current_user.tenant_id, created_by=current_user.id, **values)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log("create", "IpamVlanTranslationPolicy", row.id, f"Created VLAN translation policy '{row.name}'", None, snapshot(row, POLICY_FIELDS))
    return _policy_items(db, [row])[0]


@router.get("/vlan-translation-policies/{policy_id}")
def get_policy(policy_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One policy with its rules, by local VLAN ID."""
    row = get_owned(db, IpamVlanTranslationPolicy, current_user.tenant_id, policy_id, "VLAN translation policy")
    item = _policy_items(db, [row])[0]
    item["rules"] = [_rule_out(r) for r in db.query(IpamVlanTranslationRule).filter(IpamVlanTranslationRule.policy_id == row.id).order_by(
        IpamVlanTranslationRule.local_vid).all()]
    return item


@router.put("/vlan-translation-policies/{policy_id}")
def update_policy(policy_id: uuid.UUID, data: PolicyIn, audit: AuditContext = Depends(),
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVlanTranslationPolicy, current_user.tenant_id, policy_id, "VLAN translation policy")
    values = _clean(il.clean_vlan_policy, data)
    if _name_taken(db, current_user.tenant_id, values["name"], row.id):
        raise bad("A VLAN translation policy with this name already exists", 409)
    old = snapshot(row, POLICY_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "IpamVlanTranslationPolicy", row.id, f"Updated VLAN translation policy '{row.name}'", old, snapshot(row, POLICY_FIELDS))
    return _policy_items(db, [row])[0]


@router.delete("/vlan-translation-policies/{policy_id}", status_code=204)
def delete_policy(policy_id: uuid.UUID, audit: AuditContext = Depends(),
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVlanTranslationPolicy, current_user.tenant_id, policy_id, "VLAN translation policy")
    if db.query(AssetInterface.id).filter(AssetInterface.vlan_translation_policy_id == row.id).first():
        raise bad("Interfaces still use this policy; remove it from them first", 409)
    old = snapshot(row, POLICY_FIELDS)
    db.query(IpamVlanTranslationRule).filter(IpamVlanTranslationRule.policy_id == row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    audit.log("delete", "IpamVlanTranslationPolicy", policy_id, f"Deleted VLAN translation policy '{old['name']}'", old, None)


# --- rules ------------------------------------------------------------------------------------

def _rule_clash(db: Session, policy_id, values: dict, exclude_id=None) -> None:
    query = db.query(IpamVlanTranslationRule).filter(IpamVlanTranslationRule.policy_id == policy_id)
    if exclude_id:
        query = query.filter(IpamVlanTranslationRule.id != exclude_id)
    for other in query.all():
        if other.local_vid == values["local_vid"]:
            raise bad(f"The policy already translates local VLAN {values['local_vid']}", 409)
        if other.remote_vid == values["remote_vid"]:
            raise bad(f"The policy already translates to remote VLAN {values['remote_vid']}", 409)


@router.get("/vlan-translation-rules")
def list_rules(policy_id: Optional[uuid.UUID] = None, local_vid: Optional[int] = Query(None, ge=1, le=4094),
               remote_vid: Optional[int] = Query(None, ge=1, le=4094), skip: int = Query(0, ge=0),
               limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    R = IpamVlanTranslationRule
    query = db.query(R).filter(R.tenant_id == current_user.tenant_id)
    for column, value in ((R.policy_id, policy_id), (R.local_vid, local_vid), (R.remote_vid, remote_vid)):
        if value is not None:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(R.policy_id, R.local_vid).offset(skip).limit(limit).all()
    return api_paging.page([_rule_out(r) for r in rows], total, skip, limit)


@router.post("/vlan-translation-policies/{policy_id}/rules")
def create_rule(policy_id: uuid.UUID, data: RuleIn, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    policy = get_owned(db, IpamVlanTranslationPolicy, current_user.tenant_id, policy_id, "VLAN translation policy")
    values = _clean(il.clean_vlan_rule, data)
    _rule_clash(db, policy.id, values)
    row = IpamVlanTranslationRule(tenant_id=current_user.tenant_id, policy_id=policy.id, **values)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise bad("The policy already has a rule with this local or remote VLAN ID", 409)
    db.refresh(row)
    audit.log("create", "IpamVlanTranslationRule", row.id, f"Added rule {row.local_vid} -> {row.remote_vid} to policy '{policy.name}'", None, snapshot(row, RULE_FIELDS))
    return _rule_out(row)


def _get_rule(db: Session, tenant_id, policy_id, rule_id) -> IpamVlanTranslationRule:
    row = db.query(IpamVlanTranslationRule).filter(IpamVlanTranslationRule.id == rule_id, IpamVlanTranslationRule.policy_id == policy_id,
                                                   IpamVlanTranslationRule.tenant_id == tenant_id).first()
    if row is None:
        raise not_found("Rule not found")
    return row


@router.put("/vlan-translation-policies/{policy_id}/rules/{rule_id}")
def update_rule(policy_id: uuid.UUID, rule_id: uuid.UUID, data: RuleIn, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    policy = get_owned(db, IpamVlanTranslationPolicy, current_user.tenant_id, policy_id, "VLAN translation policy")
    row = _get_rule(db, current_user.tenant_id, policy.id, rule_id)
    values = _clean(il.clean_vlan_rule, data)
    _rule_clash(db, policy.id, values, row.id)
    old = snapshot(row, RULE_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "IpamVlanTranslationRule", row.id, f"Changed rule {row.local_vid} -> {row.remote_vid} of policy '{policy.name}'", old, snapshot(row, RULE_FIELDS))
    return _rule_out(row)


@router.delete("/vlan-translation-policies/{policy_id}/rules/{rule_id}", status_code=204)
def delete_rule(policy_id: uuid.UUID, rule_id: uuid.UUID, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    policy = get_owned(db, IpamVlanTranslationPolicy, current_user.tenant_id, policy_id, "VLAN translation policy")
    row = _get_rule(db, current_user.tenant_id, policy.id, rule_id)
    old = snapshot(row, RULE_FIELDS)
    db.delete(row)
    db.commit()
    audit.log("delete", "IpamVlanTranslationRule", rule_id, f"Removed rule {old['local_vid']} -> {old['remote_vid']} from policy '{policy.name}'", old, None)
