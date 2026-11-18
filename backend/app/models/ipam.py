"""IPAM: VRFs, roles, VLAN groups, VLANs, prefixes, IP ranges and IP addresses.

Addresses are kept as text for display and as fixed 16-byte big-endian keys (`app.services.ipam_logic.to_key`) for
comparison, so containment, overlap and range queries are plain byte comparisons on any database."""
import uuid

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, SmallInteger, String, Text,
    UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


def _tenant():
    return Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)


class IpamVrf(Base):
    """A routing table. Prefixes and addresses without a VRF are in the global table."""
    __tablename__ = "ipam_vrfs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "rd", name="uq_ipam_vrf_rd"),
        Index("ix_ipam_vrfs_tenant_name", "tenant_id", "name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    name = Column(String(100), nullable=False)
    rd = Column(String(21), nullable=True)  # route distinguisher, RFC 4364
    enforce_unique = Column(Boolean, nullable=False, default=True, server_default="true")
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamRole(Base):
    """The function of a prefix, range or VLAN (for example Servers, Management)."""
    __tablename__ = "ipam_roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_ipam_role_name"), UniqueConstraint("tenant_id", "slug", name="uq_ipam_roles_slug"))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False)
    weight = Column(SmallInteger, nullable=False, default=1000, server_default="1000")
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamVlanGroup(Base):
    """A set of VLANs inside which VLAN IDs and names are unique. vid_ranges is a list of inclusive [low, high] pairs."""
    __tablename__ = "ipam_vlan_groups"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_ipam_vlan_groups_name"), UniqueConstraint("tenant_id", "slug", name="uq_ipam_vlan_groups_slug"))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL"), nullable=True, index=True)  # scope: a site, or a location of it
    vid_ranges = Column(JSONB, nullable=False, default=lambda: [[1, 4094]])
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamVlan(Base):
    __tablename__ = "ipam_vlans"
    __table_args__ = (
        UniqueConstraint("group_id", "vid", name="uq_ipam_vlans_group_vid"),
        UniqueConstraint("group_id", "name", name="uq_ipam_vlans_group_name"),
        UniqueConstraint("qinq_svlan_id", "vid", name="uq_ipam_vlans_qinq_vid"),
        UniqueConstraint("qinq_svlan_id", "name", name="uq_ipam_vlans_qinq_name"),
        Index("ix_ipam_vlans_tenant_vid", "tenant_id", "vid"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    vid = Column(SmallInteger, nullable=False)
    name = Column(String(64), nullable=False)
    status = Column(String(15), nullable=False, default="active", server_default="active")
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    group_id = Column(UUID(as_uuid=True), ForeignKey("ipam_vlan_groups.id", ondelete="RESTRICT"), nullable=True, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("ipam_roles.id", ondelete="SET NULL"), nullable=True)
    qinq_role = Column(String(5), nullable=True)  # svlan (service, outer) or cvlan (customer, inner)
    qinq_svlan_id = Column(UUID(as_uuid=True), ForeignKey("ipam_vlans.id", ondelete="RESTRICT"), nullable=True, index=True)
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamPrefix(Base):
    """An IPv4 or IPv6 network. depth and children are cached and recalculated for the routing table after every change."""
    __tablename__ = "ipam_prefixes"
    __table_args__ = (
        Index("ix_ipam_prefixes_space", "tenant_id", "vrf_id", "family", "net_start"),
        Index("ix_ipam_prefixes_range", "tenant_id", "family", "net_start", "net_end"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    prefix = Column(String(50), nullable=False)  # canonical text, for example 10.0.0.0/24
    family = Column(SmallInteger, nullable=False)  # 4 or 6
    mask_length = Column(SmallInteger, nullable=False)
    net_start = Column(LargeBinary(16), nullable=False)
    net_end = Column(LargeBinary(16), nullable=False)
    vrf_id = Column(UUID(as_uuid=True), ForeignKey("ipam_vrfs.id", ondelete="RESTRICT"), nullable=True, index=True)
    vlan_id = Column(UUID(as_uuid=True), ForeignKey("ipam_vlans.id", ondelete="SET NULL"), nullable=True, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("ipam_roles.id", ondelete="SET NULL"), nullable=True)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL"), nullable=True, index=True)  # scope: a site, or a location of it
    status = Column(String(15), nullable=False, default="active", server_default="active")
    is_pool = Column(Boolean, nullable=False, default=False, server_default="false")
    mark_utilized = Column(Boolean, nullable=False, default=False, server_default="false")
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    depth = Column(SmallInteger, nullable=False, default=0, server_default="0")
    children = Column(BigInteger, nullable=False, default=0, server_default="0")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamIpRange(Base):
    """A run of addresses from start to end (same family and mask)."""
    __tablename__ = "ipam_ip_ranges"
    __table_args__ = (Index("ix_ipam_ip_ranges_span", "tenant_id", "vrf_id", "family", "start_host", "end_host"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    start_address = Column(String(50), nullable=False)  # with mask, for example 10.0.0.10/24
    end_address = Column(String(50), nullable=False)
    family = Column(SmallInteger, nullable=False)
    mask_length = Column(SmallInteger, nullable=False)
    start_host = Column(LargeBinary(16), nullable=False)
    end_host = Column(LargeBinary(16), nullable=False)
    size = Column(BigInteger, nullable=False)
    vrf_id = Column(UUID(as_uuid=True), ForeignKey("ipam_vrfs.id", ondelete="RESTRICT"), nullable=True, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("ipam_roles.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(15), nullable=False, default="active", server_default="active")
    mark_populated = Column(Boolean, nullable=False, default=False, server_default="false")  # no addresses may be created inside
    mark_utilized = Column(Boolean, nullable=False, default=False, server_default="false")  # counts as fully used
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamIpAddress(Base):
    """One address with its mask. May be tied to an asset interface of the register (optional)."""
    __tablename__ = "ipam_ip_addresses"
    __table_args__ = (Index("ix_ipam_ip_addresses_host", "tenant_id", "vrf_id", "family", "host"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    address = Column(String(50), nullable=False)  # with mask, for example 10.0.0.5/24
    family = Column(SmallInteger, nullable=False)
    mask_length = Column(SmallInteger, nullable=False)
    host = Column(LargeBinary(16), nullable=False)
    vrf_id = Column(UUID(as_uuid=True), ForeignKey("ipam_vrfs.id", ondelete="RESTRICT"), nullable=True, index=True)
    status = Column(String(15), nullable=False, default="active", server_default="active")
    role = Column(String(15), nullable=True)
    dns_name = Column(String(255), nullable=True)
    nat_inside_id = Column(UUID(as_uuid=True), ForeignKey("ipam_ip_addresses.id", ondelete="SET NULL"), nullable=True)
    asset_interface_id = Column(UUID(as_uuid=True), ForeignKey("asset_interfaces.id", ondelete="SET NULL"), nullable=True, index=True)
    fhrp_group_id = Column(UUID(as_uuid=True), ForeignKey("ipam_fhrp_groups.id", ondelete="SET NULL"), nullable=True, index=True)  # a virtual IP
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamRir(Base):
    """A registry that allocates address space or AS numbers (ARIN, RIPE ... or a standard such as RFC 1918)."""
    __tablename__ = "ipam_rirs"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_ipam_rirs_name"), UniqueConstraint("tenant_id", "slug", name="uq_ipam_rirs_slug"))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False)
    is_private = Column(Boolean, nullable=False, default=False, server_default="false")
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamAggregate(Base):
    """A top-level block of address space assigned by a registry. Aggregates of one tenant never overlap."""
    __tablename__ = "ipam_aggregates"
    __table_args__ = (Index("ix_ipam_aggregates_range", "tenant_id", "family", "net_start", "net_end"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    prefix = Column(String(50), nullable=False)
    family = Column(SmallInteger, nullable=False)
    mask_length = Column(SmallInteger, nullable=False)
    net_start = Column(LargeBinary(16), nullable=False)
    net_end = Column(LargeBinary(16), nullable=False)
    rir_id = Column(UUID(as_uuid=True), ForeignKey("ipam_rirs.id", ondelete="RESTRICT"), nullable=False, index=True)
    date_added = Column(Date, nullable=True)
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamAsn(Base):
    """An autonomous system number."""
    __tablename__ = "ipam_asns"
    __table_args__ = (UniqueConstraint("tenant_id", "asn", name="uq_ipam_asns_asn"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    asn = Column(BigInteger, nullable=False)
    rir_id = Column(UUID(as_uuid=True), ForeignKey("ipam_rirs.id", ondelete="RESTRICT"), nullable=False, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("ipam_roles.id", ondelete="SET NULL"), nullable=True)
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamAsnRange(Base):
    """A block of AS numbers handed out by a registry; the ASNs inside it are the ones in the ASN table."""
    __tablename__ = "ipam_asn_ranges"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_ipam_asn_ranges_name"), UniqueConstraint("tenant_id", "slug", name="uq_ipam_asn_ranges_slug"))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False)
    rir_id = Column(UUID(as_uuid=True), ForeignKey("ipam_rirs.id", ondelete="RESTRICT"), nullable=False, index=True)
    start = Column(BigInteger, nullable=False)
    end = Column(BigInteger, nullable=False)
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamRouteTarget(Base):
    """A BGP extended community that controls how routes move between VRFs (RFC 4364), written like 65000:100."""
    __tablename__ = "ipam_route_targets"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_ipam_route_targets_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    name = Column(String(21), nullable=False)
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamVrfRouteTarget(Base):
    """A route target a VRF imports or exports (direction is 'import' or 'export')."""
    __tablename__ = "ipam_vrf_route_targets"
    __table_args__ = (UniqueConstraint("vrf_id", "route_target_id", "direction", name="uq_ipam_vrf_route_targets_link"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    vrf_id = Column(UUID(as_uuid=True), ForeignKey("ipam_vrfs.id", ondelete="CASCADE"), nullable=False, index=True)
    route_target_id = Column(UUID(as_uuid=True), ForeignKey("ipam_route_targets.id", ondelete="CASCADE"), nullable=False, index=True)
    direction = Column(String(6), nullable=False)


class IpamServiceTemplate(Base):
    """A reusable set of protocol/port pairs, for example Web = tcp/80, tcp/443. port_mappings is a list of 'tcp/80' strings."""
    __tablename__ = "ipam_service_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_ipam_service_templates_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    name = Column(String(100), nullable=False)
    port_mappings = Column(JSONB, nullable=False, default=list)
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamFhrpGroup(Base):
    """A first-hop redundancy group (VRRP, HSRP ...). Its virtual IP addresses are IPAM addresses assigned to the group."""
    __tablename__ = "ipam_fhrp_groups"
    __table_args__ = (Index("ix_ipam_fhrp_groups_order", "tenant_id", "protocol", "group_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    group_id = Column(Integer, nullable=False)
    name = Column(String(100), nullable=True)
    protocol = Column(String(20), nullable=False)
    auth_type = Column(String(20), nullable=True)
    auth_key_encrypted = Column(Text, nullable=True)  # never returned by the API
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamFhrpAssignment(Base):
    """An asset interface that takes part in a group, with its priority."""
    __tablename__ = "ipam_fhrp_assignments"
    __table_args__ = (UniqueConstraint("group_id", "asset_interface_id", name="uq_ipam_fhrp_assignments_link"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    group_id = Column(UUID(as_uuid=True), ForeignKey("ipam_fhrp_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_interface_id = Column(UUID(as_uuid=True), ForeignKey("asset_interfaces.id", ondelete="CASCADE"), nullable=False, index=True)
    priority = Column(SmallInteger, nullable=False)
    created_at = Column(DateTime, default=func.now())


class IpamService(Base):
    """A layer-four service (HTTP, SSH ...) running on an asset or offered by an FHRP group, optionally bound to addresses."""
    __tablename__ = "ipam_services"
    __table_args__ = (
        CheckConstraint("(asset_id IS NOT NULL) <> (fhrp_group_id IS NOT NULL)", name="ck_ipam_services_parent"),
        Index("ix_ipam_services_tenant_name", "tenant_id", "name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    name = Column(String(100), nullable=False)
    port_mappings = Column(JSONB, nullable=False, default=list)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=True, index=True)
    fhrp_group_id = Column(UUID(as_uuid=True), ForeignKey("ipam_fhrp_groups.id", ondelete="CASCADE"), nullable=True, index=True)
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamServiceAddress(Base):
    """An IP address a service is bound to."""
    __tablename__ = "ipam_service_addresses"
    __table_args__ = (UniqueConstraint("service_id", "ip_address_id", name="uq_ipam_service_addresses_link"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    service_id = Column(UUID(as_uuid=True), ForeignKey("ipam_services.id", ondelete="CASCADE"), nullable=False, index=True)
    ip_address_id = Column(UUID(as_uuid=True), ForeignKey("ipam_ip_addresses.id", ondelete="CASCADE"), nullable=False, index=True)


class IpamVlanTranslationPolicy(Base):
    """A named set of VLAN ID translation rules that can be applied to interfaces (NetBox: VLAN translation policy)."""
    __tablename__ = "ipam_vlan_translation_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_ipam_vlan_policies_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    name = Column(String(100), nullable=False)
    description = Column(String(200), nullable=True)
    comments = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamVlanTranslationRule(Base):
    """One translation of a local VLAN ID to a remote one inside a policy."""
    __tablename__ = "ipam_vlan_translation_rules"
    __table_args__ = (
        UniqueConstraint("policy_id", "local_vid", name="uq_ipam_vlan_rules_local"),
        UniqueConstraint("policy_id", "remote_vid", name="uq_ipam_vlan_rules_remote"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    policy_id = Column(UUID(as_uuid=True), ForeignKey("ipam_vlan_translation_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    local_vid = Column(SmallInteger, nullable=False)
    remote_vid = Column(SmallInteger, nullable=False)
    description = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class IpamInterfaceVlan(Base):
    """A VLAN carried by an asset interface: the untagged one (at most one per interface) or one of the tagged ones."""
    __tablename__ = "ipam_interface_vlans"
    __table_args__ = (
        UniqueConstraint("interface_id", "vlan_id", name="uq_ipam_interface_vlans_link"),
        Index("ux_ipam_interface_untagged", "interface_id", unique=True, postgresql_where=text("tagged = false"), sqlite_where=text("tagged = 0")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    interface_id = Column(UUID(as_uuid=True), ForeignKey("asset_interfaces.id", ondelete="CASCADE"), nullable=False, index=True)
    vlan_id = Column(UUID(as_uuid=True), ForeignKey("ipam_vlans.id", ondelete="CASCADE"), nullable=False, index=True)
    tagged = Column(Boolean, nullable=False, default=True, server_default="true")


class IpamSiteAsn(Base):
    """An AS number operated at a site (NetBox: Site.asns)."""
    __tablename__ = "ipam_site_asns"
    __table_args__ = (UniqueConstraint("site_id", "asn_id", name="uq_ipam_site_asns_link"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = _tenant()
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    asn_id = Column(UUID(as_uuid=True), ForeignKey("ipam_asns.id", ondelete="CASCADE"), nullable=False, index=True)
