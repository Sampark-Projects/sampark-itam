"""DCIM interfaces and cables: port details, cables between interfaces (an asset connection), the one-cable-per-port rule, the trace,
the PoE of switches, and the cable fields reaching the older connection list."""
import uuid
from datetime import datetime

import pytest
from sqlalchemy import event

from app.models import Asset, AssetConnection, AssetInterface, Site
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)
from tests.test_dcim_racks import FULL, client_for, new_asset


@pytest.fixture
def env(db):
    w = World(db)
    return w, client_for(db, w.user(FULL, "admin"))


def port(w, asset, name, **extra):
    row = AssetInterface(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=asset.id, name=name, type="ethernet", **extra)
    w.db.add(row)
    w.db.commit()
    return row


def cable(c, a, b, **extra):
    r = c.post("/dcim/cables", json={"local_interface_id": str(a.id), "remote_interface_id": str(b.id), **extra})
    assert r.status_code == 200, r.text
    return r.json()


def pair(w):
    sw, cam = new_asset(w, "Switch 1"), new_asset(w, "Camera 1")
    return sw, cam, port(w, sw, "Gi1/0/1"), port(w, cam, "eth0")


# --- port details -----------------------------------------------------------------------------

def test_set_and_clear_the_port_details(env, db):
    w, c = env
    sw, cam, p1, p2 = pair(w)
    out = c.put(f"/dcim/interfaces/{p1.id}", json={"port_type": "rj45", "mtu": 9000, "speed_kbps": 1000000, "duplex": "full", "poe_mode": "pse", "poe_type": "type2-ieee802.3at"}).json()
    assert out["port_type"] == "rj45" and out["mtu"] == 9000 and out["poe_mode"] == "pse" and out["enabled"] is True
    db.refresh(p1)
    assert p1.name == "Gi1/0/1" and p1.type == "ethernet"                                   # the other fields of the interface are not touched
    assert c.put(f"/dcim/interfaces/{p1.id}", json={"port_type": "usb-c"}).status_code == 400
    assert c.put(f"/dcim/interfaces/{p1.id}", json={"poe_type": "type1-ieee802.3af"}).status_code == 400   # a PoE type needs a mode
    cleared = c.put(f"/dcim/interfaces/{p1.id}", json={}).json()
    assert cleared["port_type"] is None and cleared["mtu"] is None and cleared["poe_mode"] is None
    assert c.put(f"/dcim/interfaces/{uuid.uuid4()}", json={}).status_code == 404


def test_the_asset_edit_keeps_the_port_details(env, db):
    """The asset form updates interfaces in place and sends only its own fields."""
    from app.crud.asset_interface import update_interface
    from app.schemas.asset_interface import AssetInterfaceUpdate
    w, c = env
    sw, cam, p1, p2 = pair(w)
    c.put(f"/dcim/interfaces/{p1.id}", json={"port_type": "sfp", "poe_mode": "pse"})
    update_interface(db, p1.id, AssetInterfaceUpdate(**{"name": "Gi1/0/9", "ip_address": "10.0.0.5"}))
    db.refresh(p1)
    assert (p1.name, p1.port_type, p1.poe_mode) == ("Gi1/0/9", "sfp", "pse")


def test_interface_list_filters_and_far_ends(env):
    w, c = env
    sw, cam, p1, p2 = pair(w)
    port(w, sw, "Gi1/0/2")
    c.put(f"/dcim/interfaces/{p2.id}", json={"port_type": "rj45", "poe_mode": "pd", "poe_power_draw_w": 6.5})
    cable(c, p1, p2)
    everything = c.get("/dcim/interfaces").json()
    assert everything["total"] == 3
    linked = next(i for i in everything["items"] if i["id"] == str(p1.id))
    assert linked["cable"]["far_end"]["asset_name"] == "Camera 1" and linked["cable"]["far_end"]["interface_name"] == "eth0"
    assert c.get("/dcim/interfaces", params={"has_cable": False}).json()["total"] == 1
    assert c.get("/dcim/interfaces", params={"has_cable": True}).json()["total"] == 2
    assert c.get("/dcim/interfaces", params={"poe_mode": "pd"}).json()["items"][0]["poe_power_draw_w"] == 6.5
    assert c.get("/dcim/interfaces", params={"asset_id": str(sw.id), "search": "0/2"}).json()["total"] == 1
    mine = c.get(f"/dcim/assets/{sw.id}/interfaces").json()
    assert [i["name"] for i in mine] == ["Gi1/0/1", "Gi1/0/2"] and mine[0]["cable"]["far_end"]["asset_name"] == "Camera 1" and mine[1]["cable"] is None


# --- cables -----------------------------------------------------------------------------------

def test_create_update_and_delete_a_cable(env, db):
    w, c = env
    sw, cam, p1, p2 = pair(w)
    made = cable(c, p1, p2, cable_type="cat6", cable_label="C-1", cable_length=12.5, cable_length_unit="m", cable_status="planned")
    assert made["local"]["asset_name"] == "Switch 1" and made["remote"]["interface_name"] == "eth0" and made["complete"] and not made["conflict"]
    assert (made["cable_type"], made["cable_status"], made["cable_length"], made["cable_length_unit"]) == ("cat6", "planned", 12.5, "m")
    row = db.get(AssetConnection, uuid.UUID(made["id"]))
    assert row.parent_asset_id == sw.id and row.child_asset_id == cam.id and row.connection_type == "ethernet"
    done = c.put(f"/dcim/cables/{made['id']}", json={"cable_status": "connected", "cable_type": "cat6a"}).json()
    assert done["cable_status"] == "connected" and done["cable_type"] == "cat6a" and done["cable_label"] is None   # a full replace of the attributes
    assert done["local"]["interface_name"] == "Gi1/0/1"
    assert c.delete(f"/dcim/cables/{made['id']}").status_code == 204
    assert c.delete(f"/dcim/cables/{made['id']}").status_code == 404


def test_one_cable_per_port_and_other_end_rules(env, db):
    w, c = env
    sw, cam, p1, p2 = pair(w)
    third = port(w, new_asset(w, "PLC 1"), "X1")
    cable(c, p1, p2)
    again = c.post("/dcim/cables", json={"local_interface_id": str(p1.id), "remote_interface_id": str(third.id)})
    assert again.status_code == 409 and "Camera 1" in again.text                                  # the message names the far end
    assert c.post("/dcim/cables", json={"local_interface_id": str(third.id), "remote_interface_id": str(p2.id)}).status_code == 409
    assert c.post("/dcim/cables", json={"local_interface_id": str(third.id), "remote_interface_id": str(third.id)}).status_code == 400
    same_asset = port(w, sw, "Gi1/0/2")
    assert c.post("/dcim/cables", json={"local_interface_id": str(same_asset.id), "remote_interface_id": str(p1.id)}).status_code in (400, 409)
    assert c.post("/dcim/cables", json={"local_interface_id": str(uuid.uuid4()), "remote_interface_id": str(third.id)}).status_code == 400
    assert c.post("/dcim/cables", json={"local_interface_id": str(same_asset.id), "remote_interface_id": str(third.id), "cable_type": "rope"}).status_code == 400
    # an interface of another tenant is unknown
    other = World(db, "O")
    foreign = port(other, other.asset, "Z1")
    assert c.post("/dcim/cables", json={"local_interface_id": str(same_asset.id), "remote_interface_id": str(foreign.id)}).status_code == 400
    # a cable may be saved again and moved to a free port, but not onto a port that is in use
    made = c.get("/dcim/cables").json()["items"][0]
    assert c.put(f"/dcim/cables/{made['id']}", json={"local_interface_id": str(p1.id), "remote_interface_id": str(p2.id), "cable_label": "same"}).status_code == 200
    cable_two = cable(c, same_asset, third)
    assert c.put(f"/dcim/cables/{cable_two['id']}", json={"local_interface_id": str(p1.id), "remote_interface_id": str(third.id)}).status_code == 409
    assert c.put(f"/dcim/cables/{cable_two['id']}", json={}).status_code == 200


def test_trashed_assets_cannot_be_cabled(env, db):
    w, c = env
    sw, cam, p1, p2 = pair(w)
    cam.deleted_at = datetime.utcnow()
    db.commit()
    assert c.post("/dcim/cables", json={"local_interface_id": str(p1.id), "remote_interface_id": str(p2.id)}).status_code in (400, 409)


def test_old_cables_with_a_missing_end_or_a_shared_port_are_listed_and_can_be_put_right(env, db):
    w, c = env
    sw, cam, p1, p2 = pair(w)
    plc = new_asset(w, "PLC 1")
    p3 = port(w, plc, "X1")
    legacy_half = AssetConnection(id=uuid.uuid4(), tenant_id=w.tenant.id, parent_asset_id=sw.id, child_asset_id=cam.id, connection_type="Ethernet", local_interface_id=p1.id)
    shared_a = AssetConnection(id=uuid.uuid4(), tenant_id=w.tenant.id, parent_asset_id=plc.id, child_asset_id=sw.id, connection_type="Ethernet", local_interface_id=p3.id, remote_interface_id=port(w, sw, "Gi1/0/5").id)
    shared_b = AssetConnection(id=uuid.uuid4(), tenant_id=w.tenant.id, parent_asset_id=plc.id, child_asset_id=cam.id, connection_type="Ethernet", local_interface_id=p3.id, remote_interface_id=p2.id)
    db.add_all([legacy_half, shared_a, shared_b])
    db.commit()
    overview = c.get("/dcim/cables/overview").json()
    assert overview["cables"] == 3 and overview["incomplete"] == 1 and overview["interfaces_with_several_cables"] == 1
    assert [x["id"] for x in c.get("/dcim/cables", params={"incomplete": True}).json()["items"]] == [str(legacy_half.id)]
    listed = c.get("/dcim/cables", params={"conflict": True}).json()["items"]
    assert {x["id"] for x in listed} == {str(shared_a.id), str(shared_b.id)} and all(x["conflict"] for x in listed)
    # complete the half cable: its missing end must be a free port
    assert c.put(f"/dcim/cables/{legacy_half.id}", json={"remote_interface_id": str(p2.id)}).status_code == 409        # p2 is on shared_b
    free = port(w, cam, "eth1")
    done = c.put(f"/dcim/cables/{legacy_half.id}", json={"remote_interface_id": str(free.id)}).json()
    assert done["complete"] is True and done["remote"]["interface_name"] == "eth1"


def test_cable_list_filters_and_search(env, db):
    w, c = env
    sw, cam, p1, p2 = pair(w)
    other_site = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Plant B", code="PB")
    db.add(other_site)
    db.commit()
    far_asset = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Far", site_id=other_site.id, asset_type_id=w.type.id, status_id=w.active.id)
    db.add(far_asset)
    db.commit()
    p5 = port(w, far_asset, "f1")
    cable(c, p1, p2, cable_label="Uplink", cable_type="cat6")
    cable(c, p5, port(w, sw, "Gi1/0/9"), cable_status="planned", cable_type="smf")
    assert c.get("/dcim/cables").json()["total"] == 2
    assert c.get("/dcim/cables", params={"search": "uplink"}).json()["total"] == 1
    assert c.get("/dcim/cables", params={"search": "camera"}).json()["total"] == 1
    assert c.get("/dcim/cables", params={"cable_status": "planned"}).json()["total"] == 1
    assert c.get("/dcim/cables", params={"cable_type": "cat6"}).json()["total"] == 1
    assert c.get("/dcim/cables", params={"asset_id": str(sw.id)}).json()["total"] == 2
    assert c.get("/dcim/cables", params={"site_id": str(other_site.id)}).json()["total"] == 1


def test_trace_follows_the_cable_to_the_far_end(env):
    w, c = env
    sw, cam, p1, p2 = pair(w)
    free = port(w, sw, "Gi1/0/2")
    cable(c, p1, p2, cable_type="cat6")
    out = c.get(f"/dcim/interfaces/{p1.id}/trace").json()
    assert out["near"]["asset_name"] == "Switch 1" and out["far_ends"][0]["asset_name"] == "Camera 1" and out["far_ends"][0]["interface_name"] == "eth0"
    assert out["cables"][0]["cable_type"] == "cat6" and len(out["path"]) == 3
    back = c.get(f"/dcim/interfaces/{p2.id}/trace").json()
    assert back["far_ends"][0]["asset_name"] == "Switch 1"
    assert c.get(f"/dcim/interfaces/{free.id}/trace").json()["cables"] == []
    assert c.get(f"/dcim/interfaces/{uuid.uuid4()}/trace").status_code == 404


def test_poe_budget_of_a_switch(env):
    w, c = env
    sw = new_asset(w, "Switch 1")
    cams = [new_asset(w, f"Camera {i}") for i in range(3)]
    for i, cam in enumerate(cams):
        s_port, c_port = port(w, sw, f"Gi1/0/{i + 1}"), port(w, cam, "eth0")
        c.put(f"/dcim/interfaces/{s_port.id}", json={"poe_mode": "pse"})
        c.put(f"/dcim/interfaces/{c_port.id}", json={"poe_mode": "pd", "poe_power_draw_w": [6.5, 12, None][i]})
        if i < 2:
            cable(c, s_port, c_port)
    port_unused = port(w, sw, "Gi1/0/9")
    c.put(f"/dcim/interfaces/{port_unused.id}", json={"poe_mode": "pse"})
    out = c.get("/dcim/poe").json()
    assert out["total"] == 1
    budget = out["items"][0]
    assert budget["asset_name"] == "Switch 1" and budget["pse_ports"] == 4 and budget["powered_ports"] == 2 and budget["draw_w"] == 18.5 and budget["unknown_draw"] == 0
    assert c.get("/dcim/poe", params={"search": "nothing"}).json()["total"] == 0


def test_the_older_connection_list_carries_the_cable_fields(env, db):
    from app.schemas.asset_connection import AssetConnection as Out
    w, c = env
    sw, cam, p1, p2 = pair(w)
    made = cable(c, p1, p2, cable_type="cat6", cable_length=3, cable_length_unit="m", cable_label="C-9")
    row = db.get(AssetConnection, uuid.UUID(made["id"]))
    data = Out.model_validate(row).model_dump()
    assert (data["cable_type"], data["cable_status"], data["cable_label"], data["cable_length"]) == ("cat6", "connected", "C-9", 3.0)


def test_lists_use_a_fixed_number_of_queries(env, db):
    w, c = env
    sw = new_asset(w, "Switch 1")
    for i in range(12):
        cam = new_asset(w, f"Camera {i}")
        cable(c, port(w, sw, f"p{i}"), port(w, cam, "eth0"))

    def queries(path, **params):
        counter = {"n": 0}
        bump = lambda *a: counter.__setitem__("n", counter["n"] + 1)
        event.listen(db.get_bind(), "before_cursor_execute", bump)
        out = c.get(path, params=params).json()
        event.remove(db.get_bind(), "before_cursor_execute", bump)
        return counter["n"], out

    few, _ = queries("/dcim/cables", limit=2)
    many, out = queries("/dcim/cables", limit=50)
    assert out["total"] == 12 and many <= few + 1
    few, _ = queries("/dcim/interfaces", limit=2)
    many, out = queries("/dcim/interfaces", limit=100)
    assert out["total"] == 24 and many <= few + 1


def test_cable_permissions(env, db):
    w, c = env
    sw, cam, p1, p2 = pair(w)
    viewer = client_for(db, w.user({**VIEWER_DEFAULT_PERMISSIONS, "dcim": 1}, "viewer"))
    editor = client_for(db, w.user({**ADMIN_DEFAULT_PERMISSIONS, "dcim": 2}, "editor"))
    made = cable(c, p1, p2)
    assert viewer.get("/dcim/cables").status_code == 200 and viewer.get(f"/dcim/interfaces/{p1.id}/trace").status_code == 200
    assert viewer.post("/dcim/cables", json={"local_interface_id": str(p1.id), "remote_interface_id": str(p2.id)}).status_code in (401, 403)
    assert viewer.put(f"/dcim/interfaces/{p1.id}", json={}).status_code in (401, 403)
    assert editor.put(f"/dcim/cables/{made['id']}", json={}).status_code == 200
    assert editor.delete(f"/dcim/cables/{made['id']}").status_code in (401, 403)


# --- topology ---------------------------------------------------------------------------------

def test_the_topology_is_drawn_from_the_cables(env, db):
    w, c = env
    sw, cam, p1, p2 = pair(w)
    port(w, sw, "Gi1/0/2")                                                    # a free port on the switch
    plc = new_asset(w, "PLC 1")
    p3, p4 = port(w, sw, "Gi1/0/3"), port(w, plc, "eth0")
    c.put(f"/dcim/interfaces/{p1.id}", json={"port_type": "rj45", "poe_mode": "pse"})
    c.put(f"/dcim/interfaces/{p2.id}", json={"port_type": "rj45", "poe_mode": "pd", "poe_power_draw_w": 6.5})
    cable(c, p1, p2, cable_type="cat6", cable_status="connected", cable_length=12, cable_length_unit="m")
    cable(c, p3, p4, cable_status="planned")
    half = c.post("/dcim/cables", json={"local_interface_id": str(port(w, plc, "eth1").id), "remote_interface_id": str(port(w, cam, "eth1").id)}).json()
    db.add(AssetConnection(id=uuid.uuid4(), tenant_id=w.tenant.id, parent_asset_id=sw.id, child_asset_id=cam.id, connection_type="Ethernet", local_interface_id=p1.id))  # incomplete: not drawn
    db.commit()
    out = c.get("/dcim/topology").json()
    assert {n["name"] for n in out["nodes"]} == {"Switch 1", "Camera 1", "PLC 1"} and len(out["edges"]) == 3 and out["truncated"] is False
    switch = next(n for n in out["nodes"] if n["name"] == "Switch 1")
    assert switch["ports"] == 3 and switch["free_ports"] == 1 and switch["free_port_names"] == ["Gi1/0/2"]        # Gi1/0/1 and Gi1/0/3 have cables
    poe_edge = next(e for e in out["edges"] if e["cable_type"] == "cat6")
    assert poe_edge["poe"] == {"source_interface_id": str(p1.id), "draw_w": 6.5} and poe_edge["cable_length"] == 12.0
    assert {poe_edge["a"]["interface_name"], poe_edge["b"]["interface_name"]} == {"Gi1/0/1", "eth0"}
    assert next(e for e in out["edges"] if e["cable_status"] == "planned")["poe"] is None
    assert out["summary"] == {"assets": 3, "cables": 3, "poe_cables": 1, "poe_draw_w": 6.5, "poe_unknown_draw": 0}


def test_the_topology_by_site_keeps_the_other_end_of_a_cable(env, db):
    w, c = env
    other_site = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Plant B", code="PB")
    db.add(other_site)
    db.commit()
    here, there, elsewhere = new_asset(w, "Here"), new_asset(w, "There"), new_asset(w, "Elsewhere")
    there.site_id = elsewhere.site_id = other_site.id
    db.commit()
    cable(c, port(w, here, "e0"), port(w, there, "e0"))
    cable(c, port(w, there, "e1"), port(w, elsewhere, "e0"))
    everything = c.get("/dcim/topology").json()
    assert len(everything["edges"]) == 2
    mine = c.get("/dcim/topology", params={"site_id": str(w.site.id)}).json()
    assert len(mine["edges"]) == 1 and {n["name"]: n["outside_site"] for n in mine["nodes"]} == {"Here": False, "There": True}
    other = World(db, "O")
    assert client_for(db, other.user(FULL)).get("/dcim/topology").json() == {"nodes": [], "edges": [], "truncated": False,
        "summary": {"assets": 0, "cables": 0, "poe_cables": 0, "poe_draw_w": 0, "poe_unknown_draw": 0}}


def test_a_cable_cannot_end_on_a_virtual_or_wireless_port(env, db):
    w, c = env
    sw, cam, p1, p2 = pair(w)
    wifi, bridge = port(w, cam, "wlan0"), port(w, cam, "br0")
    c.put(f"/dcim/interfaces/{wifi.id}", json={"port_type": "ieee802.11ac"})
    c.put(f"/dcim/interfaces/{bridge.id}", json={"port_type": "bridge"})
    for target in (wifi, bridge):
        refused = c.post("/dcim/cables", json={"local_interface_id": str(p1.id), "remote_interface_id": str(target.id)})
        assert refused.status_code == 400 and "cannot be terminated" in refused.json()["detail"]
    c.put(f"/dcim/interfaces/{p2.id}", json={"port_type": "1000base-t"})
    assert c.post("/dcim/cables", json={"local_interface_id": str(p1.id), "remote_interface_id": str(p2.id), "cable_type": "cat6a"}).status_code == 200
    assert c.put(f"/dcim/interfaces/{bridge.id}", json={"port_type": "bridge", "poe_mode": "pse"}).status_code == 400            # virtual: no PoE
    assert c.post("/dcim/cables", json={"local_interface_id": str(p1.id), "remote_interface_id": str(p2.id), "cable_length": 5}).status_code in (400, 409)   # a length needs a unit
