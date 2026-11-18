"""IPAM: pure rules (parsing, hierarchy, utilization, available space, ranges, addresses, VLANs)."""
import ipaddress

import pytest

from app.services import ipam_logic as il

net = ipaddress.ip_network


def ip(text):
    return int(ipaddress.ip_address(text))


# --- parsing and keys -------------------------------------------------------------------------

def test_keys_sort_like_numbers_in_both_families():
    assert il.to_key(ip("10.0.0.2")) > il.to_key(ip("10.0.0.1"))
    assert il.to_key(ip("10.0.1.0")) > il.to_key(ip("10.0.0.255"))
    assert il.to_key(ip("2001:db8::2")) > il.to_key(ip("2001:db8::1"))
    assert il.from_key(il.to_key(ip("192.168.1.1"))) == ip("192.168.1.1") and len(il.to_key(1)) == 16


def test_prefix_host_bits_are_cleared_and_fields_filled():
    out = il.clean_prefix({"prefix": " 10.0.0.77/24 "})
    assert out["prefix"] == "10.0.0.0/24" and out["family"] == 4 and out["mask_length"] == 24
    assert il.from_key(out["net_start"]) == ip("10.0.0.0") and il.from_key(out["net_end"]) == ip("10.0.0.255")
    assert out["status"] == "active" and out["is_pool"] is False and out["mark_utilized"] is False
    assert il.clean_prefix({"prefix": "2001:db8::/32"})["family"] == 6
    assert il.clean_prefix({"prefix": "10.1.1.1"})["prefix"] == "10.1.1.1/32"


@pytest.mark.parametrize("bad", [
    {"prefix": ""}, {"prefix": None}, {"prefix": "10.0.0.0/33"}, {"prefix": "banana"}, {"prefix": "0.0.0.0/0"}, {"prefix": "::/0"},
    {"prefix": "10.0.0.0/24", "status": "gone"}, {"prefix": "10.0.0.0/24", "is_pool": "yes"}, {"prefix": "10.0.0.0/24", "description": "x" * 201},
])
def test_invalid_prefix_is_refused(bad):
    with pytest.raises(il.IpamInputError):
        il.clean_prefix(bad)


def test_contains():
    assert il.contains(net("10.0.0.0/8"), net("10.1.0.0/16")) and il.contains(net("10.0.0.0/8"), net("10.0.0.0/8"))
    assert not il.contains(net("10.1.0.0/16"), net("10.0.0.0/8")) and not il.contains(net("10.0.0.0/8"), net("11.0.0.0/8"))
    assert not il.contains(net("::/1"), net("10.0.0.0/8"))


# --- hierarchy --------------------------------------------------------------------------------

def test_hierarchy_depth_and_children():
    items = [("a", net("10.0.0.0/8")), ("b", net("10.1.0.0/16")), ("c", net("10.1.1.0/24")), ("d", net("10.1.2.0/24")),
             ("e", net("192.168.0.0/16")), ("f", net("2001:db8::/32")), ("g", net("2001:db8:1::/48"))]
    h = il.compute_hierarchy(items)
    assert h["a"] == (0, 3) and h["b"] == (1, 2) and h["c"] == (2, 0) and h["d"] == (2, 0)
    assert h["e"] == (0, 0) and h["f"] == (0, 1) and h["g"] == (1, 0)


def test_hierarchy_equal_networks_do_not_count_each_other():
    h = il.compute_hierarchy([("a", net("10.0.0.0/24")), ("b", net("10.0.0.0/24")), ("c", net("10.0.0.0/16")), ("d", net("10.0.0.0/25"))])
    assert h["c"] == (0, 3) and h["a"] == (1, 1) and h["b"] == (1, 1) and h["d"] == (2, 0)


def test_hierarchy_of_nothing():
    assert il.compute_hierarchy([]) == {}


def test_hierarchy_accepts_a_generator_with_both_families():
    items = (p for p in [("a", net("10.0.0.0/8")), ("b", net("10.1.0.0/16")), ("c", net("2001:db8::/32")), ("d", net("2001:db8::/48"))])
    assert il.compute_hierarchy(items) == {"a": (0, 1), "b": (1, 0), "c": (0, 1), "d": (1, 0)}


# --- usable space and utilization -------------------------------------------------------------

def test_usable_bounds():
    assert il.usable_bounds(net("10.0.0.0/24")) == (ip("10.0.0.1"), ip("10.0.0.254"))
    assert il.usable_bounds(net("10.0.0.0/24"), is_pool=True) == (ip("10.0.0.0"), ip("10.0.0.255"))
    assert il.usable_bounds(net("10.0.0.0/31")) == (ip("10.0.0.0"), ip("10.0.0.1"))
    assert il.usable_bounds(net("10.0.0.1/32")) == (ip("10.0.0.1"), ip("10.0.0.1"))
    assert il.usable_bounds(net("2001:db8::/64")) == (ip("2001:db8::1"), ip("2001:db8::ffff:ffff:ffff:ffff"))
    assert il.usable_bounds(net("2001:db8::/127"))[0] == ip("2001:db8::")


def test_utilization_size():
    assert il.utilization_size(net("10.0.0.0/24")) == 254 and il.utilization_size(net("10.0.0.0/24"), True) == 256
    assert il.utilization_size(net("10.0.0.0/31")) == 2 and il.utilization_size(net("2001:db8::/64")) == 2 ** 64


def test_active_prefix_utilization_counts_distinct_hosts():
    p = net("10.0.0.0/24")
    hosts = [ip("10.0.0.5"), ip("10.0.0.5"), ip("10.0.0.6")]
    assert il.prefix_utilization(p, "active", False, False, hosts) == pytest.approx(2 / 254 * 100)
    assert il.prefix_utilization(p, "active", False, True, []) == 100.0
    assert il.prefix_utilization(p, "active", False, False, []) == 0.0


def test_utilized_range_counts_and_hosts_inside_it_are_not_doubled():
    p = net("10.0.0.0/24")
    utilized = [(ip("10.0.0.10"), ip("10.0.0.19"))]  # 10 addresses
    hosts = [ip("10.0.0.12"), ip("10.0.0.50")]  # one inside the range, one outside
    assert il.prefix_utilization(p, "active", False, False, hosts, utilized) == pytest.approx(11 / 254 * 100)
    assert il.prefix_utilization(p, "active", False, False, [], [(ip("10.0.0.0"), ip("10.0.0.255"))]) == 100.0


def test_container_utilization_comes_from_child_prefixes():
    parent = net("10.0.0.0/24")
    kids = [net("10.0.0.0/26"), net("10.0.0.64/26"), net("10.0.0.0/27"), net("172.16.0.0/12")]  # last is outside, third is nested
    assert il.prefix_utilization(parent, "container", False, False, [], child_networks=kids) == pytest.approx(50.0)


# --- available space --------------------------------------------------------------------------

def test_available_ips_skip_used_and_populated():
    p = net("10.0.0.0/29")  # usable .1 to .6
    free = list(il.iter_available_ips(p, False, [ip("10.0.0.1"), ip("10.0.0.3")], [(ip("10.0.0.5"), ip("10.0.0.5"))]))
    assert free == [ip("10.0.0.2"), ip("10.0.0.4"), ip("10.0.0.6")]
    assert il.available_ip_count(p, False, [ip("10.0.0.1"), ip("10.0.0.3")], [(ip("10.0.0.5"), ip("10.0.0.5"))]) == 3
    assert il.available_ip_count(p, False, [ip("10.0.0.1"), ip("10.0.0.1")]) == 5  # duplicates count once
    assert il.available_ip_count(p, False, [], [(ip("10.0.0.0"), ip("10.0.0.255"))]) == 0


def test_available_ips_are_lazy_for_huge_prefixes():
    first = next(il.iter_available_ips(net("2001:db8::/32"), False, [ip("2001:db8::1")]))
    assert first == ip("2001:db8::2")


def test_available_prefixes():
    parent = net("10.0.0.0/24")
    free = il.available_prefixes(parent, [net("10.0.0.0/26"), net("10.0.0.128/26"), net("172.16.0.0/16")])
    assert [str(n) for n in free] == ["10.0.0.64/26", "10.0.0.192/26"]
    assert [str(n) for n in il.available_prefixes(parent, [])] == ["10.0.0.0/24"]
    assert il.available_prefixes(parent, [net("10.0.0.0/24")]) == []
    assert [str(n) for n in il.available_prefixes(parent, [net("10.0.0.64/26")])] == ["10.0.0.0/26", "10.0.0.128/25"]


def test_first_free_prefix_of_a_length():
    parent = net("10.0.0.0/24")
    kids = [net("10.0.0.0/26"), net("10.0.0.128/26")]
    assert str(il.first_free_prefix(parent, kids, 26)) == "10.0.0.64/26"
    assert str(il.first_free_prefix(parent, kids, 28)) == "10.0.0.64/28"
    assert il.first_free_prefix(parent, kids, 25) is None  # no free /25 left
    assert il.first_free_prefix(parent, kids, 24) is None and il.first_free_prefix(parent, kids, 33) is None


# --- IP range ---------------------------------------------------------------------------------

def test_range_cleaning_and_size():
    out = il.clean_ip_range({"start_address": "10.0.0.10/24", "end_address": "10.0.0.20/24", "mark_populated": True})
    assert out["size"] == 11 and out["family"] == 4 and out["mask_length"] == 24 and out["mark_populated"] is True
    assert il.from_key(out["start_host"]) == ip("10.0.0.10") and il.from_key(out["end_host"]) == ip("10.0.0.20")
    assert il.clean_ip_range({"start_address": "10.0.0.5/24", "end_address": "10.0.0.5/24"})["size"] == 1


@pytest.mark.parametrize("bad", [
    {"start_address": "10.0.0.10/24", "end_address": "10.0.0.9/24"},
    {"start_address": "10.0.0.10/24", "end_address": "10.0.0.20/25"},
    {"start_address": "10.0.0.10/24", "end_address": "2001:db8::1/24"},
    {"start_address": "10.0.0.10/24"}, {"start_address": "x", "end_address": "y"},
    {"start_address": "2001:db8::/64", "end_address": "2001:db9::/64"},  # larger than 2^32 - 1
    {"start_address": "10.0.0.10/24", "end_address": "10.0.0.20/24", "status": "dhcp"},
])
def test_invalid_range_is_refused(bad):
    with pytest.raises(il.IpamInputError):
        il.clean_ip_range(bad)


def test_range_label():
    assert il.range_label("10.0.0.10/24", "10.0.0.20/24") == "10.0.0.10-20/24"
    assert il.range_label("10.0.0.10/16", "10.0.5.20/16") == "10.0.0.10-5.20/16"
    assert il.range_label("10.0.0.5/24", "10.0.0.5/24") == "10.0.0.5-10.0.0.5/24"
    assert il.range_label("2001:db8::1/64", "2001:db8::9/64") == "2001:db8::1-9/64"


def test_range_utilization():
    assert il.range_utilization(10, 5, False) == 50.0 and il.range_utilization(10, 0, True) == 100.0 and il.range_utilization(10, 12, False) == 100.0


# --- IP address -------------------------------------------------------------------------------

def test_address_cleaning():
    out = il.clean_ip_address({"address": "10.0.0.5/24", "dns_name": " Host.Example.COM ", "role": "vip", "status": "dhcp"})
    assert out["address"] == "10.0.0.5/24" and out["family"] == 4 and out["mask_length"] == 24
    assert il.from_key(out["host"]) == ip("10.0.0.5") and out["dns_name"] == "host.example.com" and out["role"] == "vip"
    assert il.clean_ip_address({"address": "10.0.0.5"})["address"] == "10.0.0.5/32"
    assert il.clean_ip_address({"address": "2001:db8::1/64", "status": "slaac"})["status"] == "slaac"
    assert il.clean_ip_address({"address": "10.0.0.5/24", "dns_name": "*.corp.local"})["dns_name"] == "*.corp.local"


@pytest.mark.parametrize("bad", [
    {"address": "10.0.0.5/24", "status": "slaac"}, {"address": "10.0.0.5/0"}, {"address": "nope"}, {"address": ""},
    {"address": "10.0.0.5/24", "role": "boss"}, {"address": "10.0.0.5/24", "dns_name": "bad name"}, {"address": "10.0.0.5/24", "dns_name": "a_b!.com"},
])
def test_invalid_address_is_refused(bad):
    with pytest.raises(il.IpamInputError):
        il.clean_ip_address(bad)


def test_network_id_and_broadcast_cannot_go_on_an_interface():
    il.check_assignable(ipaddress.ip_interface("10.0.0.5/24"))
    il.check_assignable(ipaddress.ip_interface("10.0.0.0/31"))  # point to point
    il.check_assignable(ipaddress.ip_interface("10.0.0.7/32"))
    il.check_assignable(ipaddress.ip_interface("2001:db8::/128"))
    with pytest.raises(il.IpamInputError, match="network ID"):
        il.check_assignable(ipaddress.ip_interface("10.0.0.0/24"))
    with pytest.raises(il.IpamInputError, match="broadcast"):
        il.check_assignable(ipaddress.ip_interface("10.0.0.255/24"))
    with pytest.raises(il.IpamInputError, match="network ID"):
        il.check_assignable(ipaddress.ip_interface("2001:db8::/64"))


def test_duplicate_rule_allows_repeating_roles_only_when_all_repeat():
    assert il.duplicate_blocks(None, []) is False
    assert il.duplicate_blocks(None, [None]) is True and il.duplicate_blocks("loopback", ["vip"]) is True
    assert il.duplicate_blocks("vrrp", ["vrrp", "hsrp"]) is False
    assert il.duplicate_blocks("vrrp", ["vrrp", None]) is True and il.duplicate_blocks("vip", [None]) is True


# --- VLANs, groups, VRF, role -----------------------------------------------------------------

def test_vid_ranges():
    assert il.clean_vid_ranges(None) == [[1, 4094]] and il.clean_vid_ranges([]) == [[1, 4094]]
    assert il.clean_vid_ranges([[200, 299], [1, 99]]) == [[1, 99], [200, 299]]
    assert il.parse_vid_ranges("1-99, 200-299 500") == [[1, 99], [200, 299], [500, 500]]
    assert il.format_vid_ranges([[1, 99], [500, 500]]) == "1-99, 500"
    for bad in ([[0, 5]], [[1, 4095]], [[10, 5]], [[1, 10], [10, 20]], [[1]], [["a", 2]], "1-5", [[True, 5]]):
        with pytest.raises(il.IpamInputError):
            il.clean_vid_ranges(bad)
    with pytest.raises(il.IpamInputError):
        il.parse_vid_ranges("1-x")


def test_available_vids():
    assert il.available_vids([[1, 5], [10, 11]], [2, 4, 10]) == [1, 3, 5, 11]
    assert il.vid_in_ranges(10, [[1, 5], [10, 11]]) and not il.vid_in_ranges(6, [[1, 5], [10, 11]])


def test_vlan_cleaning():
    out = il.clean_vlan({"vid": 100, "name": "  Plant   floor "})
    assert out["vid"] == 100 and out["name"] == "Plant floor" and out["status"] == "active"
    for bad in ({"vid": 0, "name": "x"}, {"vid": 4095, "name": "x"}, {"vid": "5", "name": "x"}, {"vid": True, "name": "x"},
                {"vid": 5, "name": " "}, {"vid": 5, "name": "x" * 65}, {"vid": 5, "name": "x", "status": "up"}):
        with pytest.raises(il.IpamInputError):
            il.clean_vlan(bad)


def test_vlan_group_cleaning():
    out = il.clean_vlan_group({"name": "Plant", "vid_ranges": [[100, 199]]})
    assert out["vid_ranges"] == [[100, 199]] and il.clean_vlan_group({"name": "All"})["vid_ranges"] == [[1, 4094]]
    with pytest.raises(il.IpamInputError):
        il.clean_vlan_group({"name": ""})


def test_vrf_and_role_cleaning():
    out = il.clean_vrf({"name": " Corp ", "rd": "65000:100"})
    assert out == {"name": "Corp", "rd": "65000:100", "enforce_unique": True, "description": None, "comments": None}
    assert il.clean_vrf({"name": "x", "rd": "10.0.0.1:5", "enforce_unique": False})["enforce_unique"] is False
    for bad in ({"name": ""}, {"name": "x", "rd": "banana"}, {"name": "x", "enforce_unique": "no"}):
        with pytest.raises(il.IpamInputError):
            il.clean_vrf(bad)
    assert il.clean_role({"name": "Servers"})["weight"] == 1000 and il.clean_role({"name": "x", "weight": 5})["weight"] == 5
    for bad in ({"name": ""}, {"name": "x", "weight": -1}, {"name": "x", "weight": True}, {"name": "x", "weight": 40000}):
        with pytest.raises(il.IpamInputError):
            il.clean_role(bad)


# --- routing and services ---------------------------------------------------------------------

def test_port_mappings_parse_expand_and_normalize():
    assert il.parse_port_mappings(["tcp/80", "UDP/53", "tcp/080"][:2]) == ["tcp/80", "udp/53"]
    assert il.parse_port_mappings("tcp/80, udp/53;tcp/8000-8002\ntcp/443") == ["tcp/80", "udp/53", "tcp/8000", "tcp/8001", "tcp/8002", "tcp/443"]
    assert il.parse_port_mappings(None) == [] and il.parse_port_mappings("") == [] and il.parse_port_mappings([" "]) == []
    assert il.parse_port_mappings(["sctp/1", "tcp/65535"]) == ["sctp/1", "tcp/65535"]
    for bad in ("tcp", "tcp/", "80", "icmp/80", "tcp/0", "tcp/65536", "tcp/90-80", "tcp/80,tcp/80", "tcp/80-82, tcp/81", "tcp/ab", [80], 5,
                "tcp/1-6000"):
        with pytest.raises(il.IpamInputError):
            il.parse_port_mappings(bad)


def test_port_mappings_format_collapses_ranges():
    assert il.format_port_mappings(["tcp/80", "tcp/81", "tcp/82", "tcp/443", "udp/53"]) == "TCP/80-82, TCP/443, UDP/53"
    assert il.format_port_mappings(["udp/53", "tcp/8000", "tcp/8001"]) == "TCP/8000-8001, UDP/53"
    assert il.format_port_mappings([]) == "" and il.format_port_mappings(["tcp/9"]) == "TCP/9"


def test_route_target_template_service_cleaning():
    assert il.clean_route_target({"name": "65000:100"}) == {"name": "65000:100", "description": None, "comments": None}
    assert il.clean_route_target({"name": "10.0.0.1:5", "description": " x "})["description"] == "x"
    for bad in ({"name": ""}, {"name": "banana"}, {"name": "65000:100:1"}, {"name": "1" * 30 + ":1"}):
        with pytest.raises(il.IpamInputError):
            il.clean_route_target(bad)
    tpl = il.clean_service_template({"name": " Web ", "port_mappings": "tcp/80, tcp/443"})
    assert tpl["name"] == "Web" and tpl["port_mappings"] == ["tcp/80", "tcp/443"]
    for bad in ({"name": "x"}, {"name": "x", "port_mappings": []}, {"name": "", "port_mappings": "tcp/80"}):
        with pytest.raises(il.IpamInputError):
            il.clean_service_template(bad)
    svc = il.clean_service({"name": "HTTPS", "port_mappings": ["tcp/443"], "asset_id": "a", "ip_address_ids": ["i", "i", "j"]})
    assert svc["ip_address_ids"] == ["i", "j"] and svc["fhrp_group_id"] is None
    for bad in ({"name": "x", "port_mappings": ["tcp/1"]}, {"name": "x", "port_mappings": ["tcp/1"], "asset_id": "a", "fhrp_group_id": "g"},
                {"name": "", "port_mappings": ["tcp/1"], "asset_id": "a"}, {"name": "x", "port_mappings": [], "asset_id": "a"}):
        with pytest.raises(il.IpamInputError):
            il.clean_service(bad)


def test_fhrp_cleaning_roles_and_labels():
    g = il.clean_fhrp_group({"group_id": 10, "name": " Core ", "protocol": "vrrp3", "auth_type": "md5", "auth_key": "s3cret"})
    assert g["group_id"] == 10 and g["name"] == "Core" and g["auth_key"] == "s3cret"
    assert il.clean_fhrp_group({"group_id": 0, "protocol": "other"})["auth_key"] is None
    for bad in ({"group_id": -1, "protocol": "hsrp"}, {"group_id": 40000, "protocol": "hsrp"}, {"group_id": True, "protocol": "hsrp"},
                {"group_id": 1}, {"group_id": 1, "protocol": "bogus"}, {"group_id": 1, "protocol": "hsrp", "auth_type": "rot13"},
                {"group_id": 1, "protocol": "hsrp", "auth_key": "x" * 256}, {"group_id": 1, "protocol": "hsrp", "auth_key": 5}):
        with pytest.raises(il.IpamInputError):
            il.clean_fhrp_group(bad)
    assert il.clean_fhrp_assignment({"priority": 255}) == {"priority": 255}
    for bad in ({"priority": 256}, {"priority": -1}, {"priority": "1"}, {}):
        with pytest.raises(il.IpamInputError):
            il.clean_fhrp_assignment(bad)
    assert il.FHRP_ADDRESS_ROLES["vrrp3"] == "vrrp" and "clusterxl" not in il.FHRP_ADDRESS_ROLES
    assert il.fhrp_group_label("vrrp3", 10, "Core", "10.0.0.1/24") == "Core VRRPv3: 10 (10.0.0.1/24)"
    assert il.fhrp_group_label("hsrp", 1, None) == "HSRP: 1"


def test_address_cannot_be_on_an_interface_and_a_group():
    with pytest.raises(il.IpamInputError):
        il.clean_ip_address({"address": "10.0.0.1/24", "asset_interface_id": "a", "fhrp_group_id": "g"})
    assert il.clean_ip_address({"address": "10.0.0.1/24", "fhrp_group_id": "g"})["fhrp_group_id"] == "g"


# --- registry ---------------------------------------------------------------------------------

def test_asn_parsing_and_labels():
    assert il.parse_asn(65000) == 65000 and il.parse_asn("65000") == 65000 and il.parse_asn(" as65000 ") == 65000
    assert il.parse_asn("1.10") == 65546 and il.parse_asn("AS0.5") == 5 and il.parse_asn(4294967295) == 4294967295
    assert il.asdot(65546) == "1.10" and il.asdot(65535) is None
    assert il.asn_label(65000) == "AS65000" and il.asn_label(65546) == "AS65546 (1.10)"
    for bad in (0, -5, 4294967296, "x", "1.2.3", "70000.1", "1.70000", None, "", True, 1.5, "AS"):
        with pytest.raises(il.IpamInputError):
            il.parse_asn(bad)


def test_rir_aggregate_asn_range_cleaning():
    assert il.clean_rir({"name": " RFC 1918 ", "is_private": True}) == {"name": "RFC 1918", "slug": None, "is_private": True, "description": None, "comments": None}
    rir = uuid_like = "11111111-1111-1111-1111-111111111111"
    agg = il.clean_aggregate({"prefix": "10.1.2.3/8", "rir_id": rir, "date_added": "2026-01-01"})
    assert agg["prefix"] == "10.0.0.0/8" and agg["family"] == 4 and agg["rir_id"] == rir
    assert il.from_key(agg["net_end"]) == ip("10.255.255.255")
    assert il.clean_asn({"asn": "1.10", "rir_id": rir})["asn"] == 65546
    rng = il.clean_asn_range({"name": "Private", "rir_id": rir, "start": 64512, "end": "65534"})
    assert (rng["start"], rng["end"]) == (64512, 65534)
    for fn, bad in ((il.clean_rir, {"name": " "}), (il.clean_rir, {"name": "x", "is_private": "yes"}),
                    (il.clean_aggregate, {"prefix": "10.0.0.0/8"}), (il.clean_aggregate, {"prefix": "0.0.0.0/0", "rir_id": rir}),
                    (il.clean_asn, {"asn": 65000}), (il.clean_asn_range, {"name": "x", "rir_id": rir, "start": 10, "end": 10}),
                    (il.clean_asn_range, {"name": "", "rir_id": rir, "start": 1, "end": 5}), (il.clean_asn_range, {"name": "x", "start": 1, "end": 5})):
        with pytest.raises(il.IpamInputError):
            fn(bad)


def test_aggregate_utilization_counts_prefixes_of_any_table_once():
    agg = net("10.0.0.0/16")
    kids = [net("10.0.0.0/18"), net("10.0.0.0/20"), net("10.0.64.0/18"), net("10.0.0.0/16"), net("192.168.0.0/16")]
    assert il.aggregate_utilization(agg, kids[:3]) == pytest.approx(50.0)
    assert il.aggregate_utilization(agg, kids) == 100.0  # an equal prefix fills it; the outside one is ignored
    assert il.aggregate_utilization(agg, []) == 0.0


def test_available_asns():
    assert il.available_asns(10, 20, [10, 12, 13], 3) == [11, 14, 15]
    assert il.available_asns(10, 12, [10, 11, 12], 5) == []
    assert il.available_asns(1, 4294967295, [], 2) == [1, 2]  # lazy over a huge range
