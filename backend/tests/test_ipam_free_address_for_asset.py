"""A new asset can take a free IPAM address: it gets an interface carrying it and the address becomes its primary IP."""
import uuid

import pytest

from app.crud import assets as crud_assets
from app.errors.exceptions import ErrorCodeException
from app.models import AssetInterface, IpamIpAddress
from app.schemas import AssetCreate
from app.services import ipam_logic as il
from app.services import ipam_service as svc

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)


def _address(db, w, text, **extra):
    import ipaddress
    iface = ipaddress.ip_interface(text)
    row = IpamIpAddress(id=uuid.uuid4(), tenant_id=w.tenant.id, address=str(iface), family=iface.version, mask_length=iface.network.prefixlen,
                        host=il.to_key(int(iface.ip)), status=extra.pop("status", "active"), **extra)
    db.add(row)
    db.commit()
    return row


def _new_asset(db, w, address_id=None):
    return crud_assets.create_asset(db, AssetCreate(name="New server", site_id=w.site.id, asset_type_id=w.type.id, status_id=w.active.id,
                                                    ipam_ip_address_id=address_id), w.tenant.id)


def test_the_asset_gets_an_interface_with_the_address_and_it_becomes_primary(db):
    w = World(db)
    free = _address(db, w, "10.20.30.15/24")
    asset = _new_asset(db, w, free.id)  # the field is not an Asset column: creating must ignore it
    svc.assign_free_address(db, w.tenant.id, asset, free.id)
    db.refresh(free)
    db.refresh(asset)
    iface = db.query(AssetInterface).filter(AssetInterface.asset_id == asset.id).one()
    assert (iface.name, iface.ip_address, iface.subnet_mask) == ("LAN", "10.20.30.15", "255.255.255.0")
    assert free.asset_interface_id == iface.id and asset.primary_ip4_id == free.id


def test_an_ipv6_address_becomes_the_primary_ipv6(db):
    w = World(db)
    free = _address(db, w, "2001:db8::10/64")
    asset = _new_asset(db, w)
    svc.assign_free_address(db, w.tenant.id, asset, free.id)
    db.refresh(asset)
    assert asset.primary_ip6_id == free.id and asset.primary_ip4_id is None
    assert db.query(AssetInterface).filter(AssetInterface.asset_id == asset.id).one().subnet_mask is None


def test_taken_deprecated_foreign_and_unassignable_addresses_are_refused(db):
    w, other = World(db), World(db, "O")
    taken = _address(db, w, "10.0.0.5/24")
    first = _new_asset(db, w)
    svc.assign_free_address(db, w.tenant.id, first, taken.id)
    cases = {
        "taken": (taken.id, 409),
        "deprecated": (_address(db, w, "10.0.0.6/24", status="deprecated").id, 400),
        "other tenant": (_address(db, other, "10.0.0.7/24").id, 404),
        "network id": (_address(db, w, "10.0.1.0/24").id, 400),
        "missing": (uuid.uuid4(), 404),
    }
    for label, (address_id, code) in cases.items():
        with pytest.raises(ErrorCodeException) as exc:
            svc.check_free_address(db, w.tenant.id, address_id)
        assert exc.value.status_code == code, label


def test_a_second_address_on_an_existing_asset_is_a_new_interface_and_keeps_the_primary(db):
    w = World(db)
    first, second = _address(db, w, "10.20.30.15/24"), _address(db, w, "10.20.40.15/24")
    asset = _new_asset(db, w)
    svc.assign_free_address(db, w.tenant.id, asset, first.id)
    svc.assign_free_address(db, w.tenant.id, asset, second.id)
    db.refresh(asset)
    names = sorted(i.name for i in db.query(AssetInterface).filter(AssetInterface.asset_id == asset.id))
    assert names == ["LAN", "LAN-2"]
    assert asset.primary_ip4_id == first.id  # an asset that already has a primary keeps it
    db.refresh(second)
    assert second.asset_interface_id is not None
