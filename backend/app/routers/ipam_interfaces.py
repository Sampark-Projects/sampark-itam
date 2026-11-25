"""IPAM settings of assets: what an interface carries (routing table, VLAN mode, untagged and tagged VLANs, VLAN translation
policy) and the primary IPv4, IPv6 and out-of-band addresses of an asset (NetBox: Interface VRF/VLANs and Device primary IPs).
Uses the `ipam` RBAC section (1 read, 2 write). The IP, subnet mask and VLAN text typed on the interface are not touched."""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Asset, AssetInterface, IpamInterfaceVlan, IpamIpAddress, IpamVlan, IpamVlanTranslationPolicy, IpamVrf, User,
)
from app.services import ipam_logic as il
from app.services.audit_trail import AuditContext
from app.services.auth import get_current_user
from app.services.ipam_service import bad, check_owned, get_owned, not_found
from app.services.rbac import require_section_access

router = APIRouter(prefix="/ipam", tags=["ipam"], dependencies=[Depends(require_section_access("ipam"))])


class InterfaceIpamIn(BaseModel):
    vrf_id: Optional[uuid.UUID] = None
    vlan_mode: Optional[str] = None  # access, tagged, tagged-all or q-in-q
    vlan_translation_policy_id: Optional[uuid.UUID] = None
    untagged_vlan_id: Optional[uuid.UUID] = None
    tagged_vlan_ids: Optional[List[uuid.UUID]] = None


class PrimaryIpsIn(BaseModel):
    primary_ip4_id: Optional[uuid.UUID] = None
    primary_ip6_id: Optional[uuid.UUID] = None
    oob_ip_id: Optional[uuid.UUID] = None


def _interface(db: Session, tenant_id, interface_id):
    row = db.query(AssetInterface, Asset).join(Asset, Asset.id == AssetInterface.asset_id).filter(
        AssetInterface.id == interface_id, AssetInterface.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first()
    if row is None:
        raise not_found("Interface not found")
    return row


def _vlan_label(v) -> dict:
    return {"id": v.id, "vid": v.vid, "name": v.name, "label": f"{v.name} ({v.vid})", "site_id": v.site_id}


def _interface_items(db: Session, tenant_id, ifaces: list, asset: Asset) -> list:
    """The IPAM settings of the interfaces of ONE asset, in a fixed number of queries."""
    ids = [i.id for i in ifaces]
    links: dict = {i: [] for i in ids}
    addresses: dict = {i: [] for i in ids}
    if ids:
        for iface_id, tagged, v in db.query(IpamInterfaceVlan.interface_id, IpamInterfaceVlan.tagged, IpamVlan).join(
                IpamVlan, IpamVlan.id == IpamInterfaceVlan.vlan_id).filter(IpamInterfaceVlan.interface_id.in_(ids)).order_by(IpamVlan.vid).all():
            links[iface_id].append((tagged, v))
        for a in db.query(IpamIpAddress.id, IpamIpAddress.asset_interface_id, IpamIpAddress.address).filter(
                IpamIpAddress.tenant_id == tenant_id, IpamIpAddress.asset_interface_id.in_(ids)).order_by(IpamIpAddress.family, IpamIpAddress.host).all():
            addresses[a.asset_interface_id].append({"id": a.id, "address": a.address})
    vrf_ids = {i.vrf_id for i in ifaces if i.vrf_id}
    vrfs = {v.id: v.name for v in db.query(IpamVrf.id, IpamVrf.name).filter(IpamVrf.id.in_(vrf_ids))} if vrf_ids else {}
    policy_ids = {i.vlan_translation_policy_id for i in ifaces if i.vlan_translation_policy_id}
    policies = {p.id: p.name for p in db.query(IpamVlanTranslationPolicy.id, IpamVlanTranslationPolicy.name).filter(
        IpamVlanTranslationPolicy.id.in_(policy_ids))} if policy_ids else {}
    return [{
        "interface_id": i.id, "interface_name": i.name, "asset_id": asset.id, "asset_name": asset.name, "site_id": asset.site_id,
        "vrf_id": i.vrf_id, "vrf_name": vrfs.get(i.vrf_id), "vlan_mode": i.vlan_mode,
        "vlan_translation_policy_id": i.vlan_translation_policy_id, "vlan_translation_policy_name": policies.get(i.vlan_translation_policy_id),
        "untagged_vlan": next((_vlan_label(v) for tagged, v in links[i.id] if not tagged), None),
        "tagged_vlans": [_vlan_label(v) for tagged, v in links[i.id] if tagged],
        "ip_addresses": addresses[i.id],
    } for i in ifaces]


def _interface_out(db: Session, tenant_id, iface: AssetInterface, asset: Asset) -> dict:
    return _interface_items(db, tenant_id, [iface], asset)[0]


@router.get("/assets/{asset_id}/interfaces")
def asset_interfaces(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The IPAM settings (routing table, VLAN mode, VLANs, translation policy) of every interface of an asset, in one call."""
    asset = _asset(db, current_user.tenant_id, asset_id)
    ifaces = db.query(AssetInterface).filter(AssetInterface.asset_id == asset.id, AssetInterface.tenant_id == current_user.tenant_id).order_by(AssetInterface.name).all()
    return _interface_items(db, current_user.tenant_id, ifaces, asset)


@router.get("/interfaces/{interface_id}")
def get_interface(interface_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    iface, asset = _interface(db, current_user.tenant_id, interface_id)
    return _interface_out(db, current_user.tenant_id, iface, asset)


def _check_vlan(db: Session, tenant_id, vlan_id, asset: Asset, label: str) -> IpamVlan:
    vlan = db.query(IpamVlan).filter(IpamVlan.id == vlan_id, IpamVlan.tenant_id == tenant_id).first()
    if vlan is None:
        raise bad(f"Unknown {label}")
    if vlan.site_id not in (None, asset.site_id):  # NetBox: the VLAN must belong to the site of the device, or be global
        raise bad(f"The VLAN {vlan.name} ({vlan.vid}) must belong to the same site as the asset, or it must be global.")
    return vlan


@router.put("/interfaces/{interface_id}")
def update_interface(interface_id: uuid.UUID, data: InterfaceIpamIn, audit: AuditContext = Depends(),
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Replace the routing table, VLAN mode, translation policy, untagged VLAN and tagged VLANs of an interface."""
    tenant_id = current_user.tenant_id
    iface, asset = _interface(db, tenant_id, interface_id)
    try:
        values = il.clean_interface_ipam(data.model_dump())
    except il.IpamInputError as exc:
        raise bad(str(exc))
    check_owned(db, IpamVrf, tenant_id, values["vrf_id"], "VRF")
    check_owned(db, IpamVlanTranslationPolicy, tenant_id, values["vlan_translation_policy_id"], "VLAN translation policy")
    wanted = ([(values["untagged_vlan_id"], False)] if values["untagged_vlan_id"] else []) + [(v, True) for v in values["tagged_vlan_ids"]]
    for vlan_id, _ in wanted:
        _check_vlan(db, tenant_id, vlan_id, asset, "VLAN")
    old = _interface_out(db, tenant_id, iface, asset)
    iface.vrf_id, iface.vlan_mode, iface.vlan_translation_policy_id = values["vrf_id"], values["vlan_mode"], values["vlan_translation_policy_id"]
    db.query(IpamInterfaceVlan).filter(IpamInterfaceVlan.interface_id == iface.id).delete(synchronize_session=False)
    for vlan_id, tagged in wanted:
        db.add(IpamInterfaceVlan(tenant_id=tenant_id, interface_id=iface.id, vlan_id=vlan_id, tagged=tagged))
    db.commit()
    db.refresh(iface)
    out = _interface_out(db, tenant_id, iface, asset)
    keys = ("vrf_id", "vlan_mode", "vlan_translation_policy_id")
    audit.log("update", "IpamInterface", iface.id, f"Updated the IPAM settings of {asset.name} / {iface.name}",
              {**{k: old[k] for k in keys}, "untagged_vlan": old["untagged_vlan"] and old["untagged_vlan"]["label"], "tagged_vlans": [v["label"] for v in old["tagged_vlans"]]},
              {**{k: out[k] for k in keys}, "untagged_vlan": out["untagged_vlan"] and out["untagged_vlan"]["label"], "tagged_vlans": [v["label"] for v in out["tagged_vlans"]]})
    return out


@router.get("/vlans/{vlan_id}/interfaces")
def vlan_interfaces(vlan_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The asset interfaces that carry a VLAN, untagged or tagged (NetBox: VLAN interfaces tab)."""
    vlan = get_owned(db, IpamVlan, current_user.tenant_id, vlan_id, "VLAN")
    rows = db.query(IpamInterfaceVlan.tagged, AssetInterface.id, AssetInterface.name, Asset.id, Asset.name).join(
        AssetInterface, AssetInterface.id == IpamInterfaceVlan.interface_id).join(Asset, Asset.id == AssetInterface.asset_id).filter(
        IpamInterfaceVlan.vlan_id == vlan.id, Asset.deleted_at.is_(None)).order_by(Asset.name, AssetInterface.name).all()
    return [{"interface_id": i, "interface_name": n, "asset_id": a, "asset_name": an, "tagged": bool(t)} for t, i, n, a, an in rows]


# --- primary addresses of an asset ------------------------------------------------------------

def _asset(db: Session, tenant_id, asset_id) -> Asset:
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first()
    if asset is None:
        raise not_found("Asset not found")
    return asset


def _own_addresses(db: Session, tenant_id, asset: Asset) -> list:
    """The addresses assigned to an interface of the asset, or NAT-outside of one (these may be designated primary)."""
    iface_ids = [i for (i,) in db.query(AssetInterface.id).filter(AssetInterface.asset_id == asset.id, AssetInterface.tenant_id == tenant_id)]
    if not iface_ids:
        return []
    direct = db.query(IpamIpAddress).filter(IpamIpAddress.tenant_id == tenant_id, IpamIpAddress.asset_interface_id.in_(iface_ids)).all()
    inside_ids = [a.id for a in direct]
    outside = db.query(IpamIpAddress).filter(IpamIpAddress.tenant_id == tenant_id, IpamIpAddress.nat_inside_id.in_(inside_ids)).all() if inside_ids else []
    names = {i: n for i, n in db.query(AssetInterface.id, AssetInterface.name).filter(AssetInterface.id.in_(iface_ids))}
    seen, out = set(), []
    for a in direct + outside:
        if a.id in seen:
            continue
        seen.add(a.id)
        out.append({"id": a.id, "address": a.address, "family": a.family, "interface_name": names.get(a.asset_interface_id), "nat_outside": a.asset_interface_id is None,
                    "_host": a.host})
    out.sort(key=lambda x: (x["family"], bytes(x["_host"])))
    for x in out:
        x.pop("_host")
    return out


def _primary_out(db: Session, tenant_id, asset: Asset) -> dict:
    ids = [i for i in (asset.primary_ip4_id, asset.primary_ip6_id, asset.oob_ip_id) if i]
    labels = {i: a for i, a in db.query(IpamIpAddress.id, IpamIpAddress.address).filter(IpamIpAddress.id.in_(ids))} if ids else {}
    pick = lambda i: {"id": i, "address": labels.get(i)} if i else None
    return {"asset_id": asset.id, "asset_name": asset.name, "primary_ip4": pick(asset.primary_ip4_id), "primary_ip6": pick(asset.primary_ip6_id),
            "oob_ip": pick(asset.oob_ip_id), "candidates": _own_addresses(db, tenant_id, asset)}


@router.get("/assets/{asset_id}/primary-ips")
def get_primary_ips(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The primary IPv4, IPv6 and out-of-band addresses of an asset, with the addresses that may be chosen."""
    return _primary_out(db, current_user.tenant_id, _asset(db, current_user.tenant_id, asset_id))


@router.put("/assets/{asset_id}/primary-ips")
def set_primary_ips(asset_id: uuid.UUID, data: PrimaryIpsIn, audit: AuditContext = Depends(),
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Set (or clear) the three addresses. Each must be assigned to an interface of this asset (or be the NAT outside of such an
    address), the IPv4 and IPv6 ones must be of the right family, and an address can be primary for one asset only."""
    tenant_id = current_user.tenant_id
    asset = _asset(db, tenant_id, asset_id)
    allowed = {a["id"]: a for a in _own_addresses(db, tenant_id, asset)}
    chosen = (("primary_ip4_id", data.primary_ip4_id, 4, "Primary IPv4"), ("primary_ip6_id", data.primary_ip6_id, 6, "Primary IPv6"), ("oob_ip_id", data.oob_ip_id, None, "Out-of-band IP"))
    for field, value, family, label in chosen:
        if value is None:
            continue
        if db.query(IpamIpAddress.id).filter(IpamIpAddress.id == value, IpamIpAddress.tenant_id == tenant_id).first() is None:
            raise bad(f"Unknown IP address for {label}")
        if value not in allowed:
            raise bad(f"{label} address must belong to an interface on the asset.")
        if family:
            try:
                il.check_primary_family(allowed[value]["family"], family, label)
            except il.IpamInputError as exc:
                raise bad(str(exc))
        taken = db.query(Asset.id).filter(Asset.id != asset.id, Asset.tenant_id == tenant_id).filter(
            (Asset.primary_ip4_id == value) | (Asset.primary_ip6_id == value) | (Asset.oob_ip_id == value)).first()
        if taken:
            raise bad(f"{label}: the address is already designated for another asset", 409)
    old = {"primary_ip4_id": asset.primary_ip4_id, "primary_ip6_id": asset.primary_ip6_id, "oob_ip_id": asset.oob_ip_id}
    asset.primary_ip4_id, asset.primary_ip6_id, asset.oob_ip_id = data.primary_ip4_id, data.primary_ip6_id, data.oob_ip_id
    db.commit()
    db.refresh(asset)
    audit.log("update", "IpamAssetAddresses", asset.id, f"Set the primary addresses of {asset.name}", old,
              {"primary_ip4_id": asset.primary_ip4_id, "primary_ip6_id": asset.primary_ip6_id, "oob_ip_id": asset.oob_ip_id})
    return _primary_out(db, tenant_id, asset)
