"""DCIM rules with no database: form checks, fitting and clashing in a rack, the elevation and the utilization."""
import uuid
from decimal import Decimal

import pytest

from app.services import dcim_logic as dl

D = Decimal


def placed(key, position, height, face="front", full_depth=True, name=None):
    return dl.Placed(key=key, name=name or key, position=D(str(position)), face=face, height=D(str(height)), full_depth=full_depth)


# --- form checks ------------------------------------------------------------------------------

def test_rack_defaults_and_limits():
    rack = dl.clean_rack({"name": "  R1 "})
    assert rack["name"] == "R1" and rack["status"] == "active" and rack["u_height"] == 42 and rack["width"] == 19
    assert rack["starting_unit"] == 1 and rack["desc_units"] is False and rack["airflow"] is None
    for bad in ({"name": ""}, {"name": "R", "status": "gone"}, {"name": "R", "u_height": 0}, {"name": "R", "u_height": 101},
                {"name": "R", "width": 20}, {"name": "R", "airflow": "sideways"}, {"name": "R" * 101}):
        with pytest.raises(dl.DcimInputError):
            dl.clean_rack(bad)
    assert dl.clean_rack({"name": "R", "status": "PLANNED", "width": "23", "desc_units": True})["width"] == 23


def test_device_type_height_is_in_half_units():
    assert dl.clean_device_type({"model": "S7-1500"})["u_height"] is None            # not known yet
    assert dl.clean_device_type({"model": "X", "u_height": "1,5"})["u_height"] == D("1.5")
    assert dl.clean_device_type({"model": "PDU", "u_height": 0})["u_height"] == D("0")
    assert dl.clean_device_type({"model": "X", "is_full_depth": False})["is_full_depth"] is False
    for bad in ({"model": ""}, {"model": "X", "u_height": "0.3"}, {"model": "X", "u_height": "abc"}, {"model": "X", "u_height": 101}):
        with pytest.raises(dl.DcimInputError):
            dl.clean_device_type(bad)


def test_role_slug_and_colour():
    role = dl.clean_role({"name": "Network Racks!", "color": "#ABCDEF"})
    assert role["slug"] == "network-racks" and role["color"] == "#abcdef"
    with pytest.raises(dl.DcimInputError):
        dl.clean_role({"name": "x", "color": "red"})


def test_a_place_in_a_rack_needs_rack_face_and_position_together():
    rack = object()
    assert dl.clean_placement(None, None, None) == {"rack_id": None, "rack_position": None, "rack_face": None}
    assert dl.clean_placement(rack, None, None)["rack_position"] is None                       # in the rack, no position (0U)
    assert dl.clean_placement(rack, "10", "FRONT") == {"rack_id": rack, "rack_position": D("10"), "rack_face": "front"}
    for args in ((None, "10", "front"), (None, None, "front"), (rack, "10", None), (rack, None, "front"), (rack, "10", "left"), (rack, "10.2", "front")):
        with pytest.raises(dl.DcimInputError):
            dl.clean_placement(*args)


# --- space ------------------------------------------------------------------------------------

def test_fit_inside_the_rack():
    assert dl.fits(D("1"), D("42"), 1, 42)
    assert not dl.fits(D("2"), D("42"), 1, 42)
    assert not dl.fits(D("0"), D("1"), 1, 42)
    assert dl.fits(D("5"), D("2"), 5, 10) and not dl.fits(D("14"), D("2"), 5, 10)       # units 5 to 14
    assert dl.fits(D("14"), D("1"), 5, 10)


def test_full_depth_devices_block_both_faces_and_half_depth_only_their_own():
    a = placed("a", 10, 2)                                         # full depth, front
    assert dl.clashes(a, placed("b", 11, 1, face="rear"))          # a full-depth device shows on the rear too
    assert not dl.clashes(a, placed("c", 12, 1))                   # the unit above is free
    h1 = placed("h1", 20, 1, "front", full_depth=False)
    assert not dl.clashes(h1, placed("h2", 20, 1, "rear", full_depth=False))   # two half-depth devices back to back
    assert dl.clashes(h1, placed("h3", 20, 1, "front", full_depth=False))
    assert dl.clashes(h1, placed("h4", 20, 1, "rear", full_depth=True))
    assert not dl.clashes(placed("z", 10, 0), placed("y", 10, 2))                              # 0U uses no space


def test_half_units_and_neighbours():
    assert not dl.clashes(placed("a", 10, 0.5), placed("b", 10.5, 0.5))
    assert dl.clashes(placed("a", 10, 1), placed("b", 10.5, 1))


def test_candidate_check_names_the_problem():
    others = [placed("x", 10, 2, name="Switch 1")]
    dl.check_candidate(placed("n", 12, 1), others, 1, 42)
    with pytest.raises(dl.DcimInputError, match="Switch 1"):
        dl.check_candidate(placed("n", 11, 1), others, 1, 42)
    with pytest.raises(dl.DcimInputError, match="does not fit"):
        dl.check_candidate(placed("n", 42, 2), others, 1, 42)
    dl.check_candidate(placed("x", 10, 3), others, 1, 42)           # the device itself is not its own neighbour


def test_layout_problems_lists_devices_outside_and_clashes():
    assert dl.layout_problems([placed("a", 1, 2), placed("b", 3, 1)], 1, 4) == []
    problems = dl.layout_problems([placed("a", 1, 2), placed("b", 2, 1), placed("c", 4, 2)], 1, 4)
    assert any("a and b" in p for p in problems) and any("c (2U at 4)" in p for p in problems)


def test_utilization_counts_each_unit_once_across_faces():
    devices = [placed("a", 1, 2), placed("b", 2, 2, face="rear"), placed("c", 10, 1)]    # a and b overlap on unit 2
    assert dl.occupied_units(devices) == D("4")
    assert dl.utilization(devices, 40) == 10.0
    assert dl.utilization([], 42) == 0.0 and dl.occupied_units([placed("z", 3, 0)]) == D("0")


def test_elevation_marks_where_each_device_starts_and_follows_the_numbering():
    devices = [placed("a", 2, 2), placed("h", 5, 1, "rear", full_depth=False)]
    front = dl.elevation(devices, "front", 1, 6)
    assert [r["unit"] for r in front] == [6, 5, 4, 3, 2, 1]                         # top of the picture first
    assert [(r["unit"], r["device"], r["start"]) for r in front if r["device"]] == [(3, "a", True), (2, "a", False)]
    rear = dl.elevation(devices, "rear", 1, 6)
    assert {r["unit"]: r["device"] for r in rear if r["device"]} == {2: "a", 3: "a", 5: "h"}   # the full-depth device shows on both faces
    top_down = dl.elevation(devices, "front", 1, 6, desc_units=True)
    assert [r["unit"] for r in top_down] == [1, 2, 3, 4, 5, 6]
    assert [(r["unit"], r["start"]) for r in top_down if r["device"]] == [(2, True), (3, False)]


# --- interfaces and cables --------------------------------------------------------------------

def test_interface_details_defaults_and_limits():
    empty = dl.clean_interface_details({})
    assert empty["enabled"] is True and empty["mgmt_only"] is False and empty["port_type"] is None and empty["mtu"] is None
    full = dl.clean_interface_details({"port_type": "SFP-PLUS", "mtu": "9000", "speed_kbps": 10_000_000, "duplex": "full", "poe_mode": "pd",
                                       "poe_type": "type1-ieee802.3af", "poe_power_draw_w": "7,5", "enabled": False})
    assert full["port_type"] == "sfp-plus" and full["mtu"] == 9000 and full["poe_power_draw_w"] == D("7.5") and full["enabled"] is False
    for bad in ({"port_type": "usb-c"}, {"mtu": 0}, {"mtu": 70000}, {"speed_kbps": -1}, {"duplex": "both"}, {"poe_mode": "source"},
                {"poe_type": "type1-ieee802.3af"}, {"poe_power_draw_w": 5}, {"poe_mode": "pd", "poe_power_draw_w": "abc"}, {"poe_mode": "pd", "poe_power_draw_w": 1000}):
        with pytest.raises(dl.DcimInputError):
            dl.clean_interface_details(bad)


def test_cable_attributes():
    cable = dl.clean_cable({})
    assert cable["cable_status"] == "connected" and cable["cable_type"] is None and cable["cable_length"] is None and cable["cable_length_unit"] is None
    c = dl.clean_cable({"cable_type": "Cat6A", "status": "planned", "label": " C-12 ", "color": "#AABBCC", "length": "12,5", "length_unit": "m"})
    assert (c["cable_type"], c["cable_status"], c["cable_label"], c["cable_color"]) == ("cat6a", "planned", "C-12", "#aabbcc")
    assert c["cable_length"] == D("12.5") and c["cable_length_unit"] == "m"
    assert dl.clean_cable({"cable_length": 3, "cable_length_unit": "ft"})["cable_length_unit"] == "ft"
    assert dl.clean_cable({"cable_length": 2, "cable_length_unit": "km"})["cable_length_unit"] == "km"   # NetBox units: km, m, cm, mi, ft, in
    assert dl.clean_cable({"cable_length": 2, "cable_length_unit": "mi"})["cable_length_unit"] == "mi"
    assert dl.clean_cable({"cable_length_unit": "ft"})["cable_length_unit"] is None              # a unit without a length means nothing
    for bad in ({"cable_type": "rope"}, {"cable_status": "lost"}, {"cable_color": "blue"}, {"cable_length": -1}, {"cable_length": 1, "cable_length_unit": "yd"},
                {"cable_length": 12}):                                                           # a length needs a unit, as in NetBox
        with pytest.raises(dl.DcimInputError):
            dl.clean_cable(bad)


def test_poe_budget_adds_up_the_draw_of_the_powered_ports():
    ports = [{"connected": True, "draw": 7.5}, {"connected": True, "draw": 12.0}, {"connected": True, "draw": None}, {"connected": False, "draw": None}]
    assert dl.poe_budget(ports) == {"pse_ports": 4, "powered_ports": 3, "draw_w": 19.5, "unknown_draw": 1}
    assert dl.poe_budget([]) == {"pse_ports": 0, "powered_ports": 0, "draw_w": 0, "unknown_draw": 0}


# --- the value lists and rules of NetBox ------------------------------------------------------

def test_the_value_lists_are_the_netbox_ones():
    assert "1000base-t" in dl.PORT_TYPES and "ieee802.11ax" in dl.PORT_TYPES and "extreme-summitstack-512" in dl.PORT_TYPES and "rj45" in dl.PORT_TYPES   # NetBox types and the plant's generic ones
    assert len(dl.PORT_TYPES) > 200 and len(dl.PORT_TYPES) == len(set(dl.PORT_TYPES))
    assert {"cat6a", "mmf-om4", "smf-os2", "dac-passive", "aoc", "mrj21-trunk", "usb", "profibus", "canbus"} <= set(dl.CABLE_TYPES)
    assert dl.POE_TYPES == ["type1-ieee802.3af", "type2-ieee802.3at", "type3-ieee802.3bt", "type4-ieee802.3bt", "passive-24v-2pair", "passive-24v-4pair",
                            "passive-48v-2pair", "passive-48v-4pair"]
    assert dl.LENGTH_UNITS == ["km", "m", "cm", "mi", "ft", "in"] and dl.RACK_AIRFLOWS == ["front-to-rear", "rear-to-front"] and len(dl.RACK_FORM_FACTORS) == 7
    assert dl.clean_rack({"name": "R", "airflow": "front-to-rear", "form_factor": "4-post-cabinet"})["form_factor"] == "4-post-cabinet"
    for bad in ({"airflow": "passive"}, {"form_factor": "shelf"}):                  # a rack has two airflows only; a device has ten
        with pytest.raises(dl.DcimInputError):
            dl.clean_rack({"name": "R", **bad})


def test_virtual_ports_take_no_poe_and_no_cable():
    assert {"virtual", "lag", "bridge"} <= dl.VIRTUAL_PORT_TYPES and "ieee802.11ac" in dl.WIRELESS_PORT_TYPES and "channel" in dl.NONCONNECTABLE_PORT_TYPES
    assert "1000base-t" not in dl.NONCONNECTABLE_PORT_TYPES and "rj45" not in dl.NONCONNECTABLE_PORT_TYPES
    for bad in ({"port_type": "lag", "poe_mode": "pse"}, {"port_type": "virtual", "poe_mode": "pd", "poe_type": "type1-ieee802.3af"}):
        with pytest.raises(dl.DcimInputError):
            dl.clean_interface_details(bad)
    assert dl.clean_interface_details({"port_type": "1000base-t", "poe_mode": "pse"})["poe_mode"] == "pse"


def test_placement_rules_of_netbox():
    a, b = uuid.uuid4(), uuid.uuid4()
    dl.check_placement_rules(None, b, 1, True)                       # the asset has no location: any rack
    dl.check_placement_rules(a, None, 1, True)                       # the rack has none: fine
    dl.check_placement_rules(a, a, 2, True)
    dl.check_placement_rules(a, a, 0, False)                         # a 0U device may be assigned to the rack without a position
    with pytest.raises(dl.DcimInputError):
        dl.check_placement_rules(a, b, 1, True)                      # two different locations
    with pytest.raises(dl.DcimInputError):
        dl.check_placement_rules(None, None, 0, True)                # a 0U device cannot have a position
