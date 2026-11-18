# IPAM module: plan and status

Source: the IPAM app of NetBox (`sampark_netbox/netbox/ipam`, Django). NetBox is not copied: its rules are re-implemented here in the stack of this repository (FastAPI, SQLAlchemy, Alembic, Vue).
Branch: `feature/applications` (the current branch). Database: schema `assets_applications` (`DB_SCHEMA`), the same schema as every other table; the migration only adds tables to it.

## Approach

- **Additive only.** New tables, routes, pages and one permission section (`ipam`). No existing table, column or screen changes meaning.
- **Same conventions as the other modules.** UUID ids, `tenant_id` on every row, audit log on every change, paged lists (`{total, skip, limit, has_more, items}`), pure rules in a service module with no database access, English and Italian text.
- **Portable address storage.** Addresses are stored as text for display plus fixed 16-byte big-endian keys for comparison (`net_start`, `net_end`, `host`). Containment, overlap and range queries are plain byte comparisons, so they run the same on PostgreSQL and in the SQLite test database. The rules use the Python standard library `ipaddress` (no new dependency).
- **No NetBox-only concepts.** NetBox tags, custom fields, contacts, change-log, scope generic relations and its own "tenant" (customer) are left out. The tenant here is the organisation, as everywhere in this application.
- **Optional link to assets.** An IP address may point at an existing asset interface (`asset_interface_id`, nullable, `ON DELETE SET NULL`). The free-text IP, mask and VLAN fields of the interface are not changed.
- **Gate = permission.** The `ipam` section is the switch: read 1, write 2, delete 3. The migration grants administrator roles (level 3 or more on `roles`) full access, roles named "editor" Write and roles named "viewer" Read.

## NetBox model to table

| NetBox | Table | Phase |
|---|---|---|
| VRF | `ipam_vrfs` | 1 |
| Role | `ipam_roles` | 1 |
| VLANGroup | `ipam_vlan_groups` | 1 |
| VLAN | `ipam_vlans` | 1 |
| Prefix | `ipam_prefixes` | 1 |
| IPRange | `ipam_ip_ranges` | 1 |
| IPAddress | `ipam_ip_addresses` | 1 |
| RIR, Aggregate | `ipam_rirs`, `ipam_aggregates` | later |
| ASN, ASNRange | `ipam_asns`, `ipam_asn_ranges` | later |
| RouteTarget (VRF import/export) | `ipam_route_targets` | later |
| FHRPGroup and assignment | | later |
| Service, ServiceTemplate | | later |
| VLANTranslationPolicy and rule | | later |

## Phase 1 (core): rules carried over from NetBox

- **Prefix.** IPv4 or IPv6 network, no /0. Host bits are cleared (`10.0.0.5/24` is stored as `10.0.0.0/24`). Status container, active, reserved or deprecated. Optional VRF, VLAN, role, site, "is a pool" and "mark utilized". Duplicates are refused inside a VRF (or the global table) when that VRF enforces unique space; the global table enforces it too. Depth and child count are cached per prefix and recalculated for the VRF after every change.
- **Utilization.** A container prefix is measured by its child prefixes; any other prefix by the child IP addresses and the ranges marked utilized. IPv4 prefixes shorter than /31 that are not pools exclude the network and broadcast addresses.
- **Available space.** Free child prefixes of a prefix and the next free IP address, honouring usable bounds (pools and /31, /32, /127, /128 are fully usable) and ranges marked populated.
- **IP range.** Start and end of the same family and mask, end not before start, no overlap with another range in the same VRF, at most 2^32 - 1 addresses, size stored. Marked populated: no IP address may be created inside it. Marked utilized: counts as fully used.
- **IP address.** Address with mask, no /0. Status active, reserved, deprecated, DHCP or SLAAC (IPv6 only). Role loopback, secondary, anycast, VIP, VRRP, HSRP, GLBP or CARP; the last six may repeat. A network ID or broadcast address cannot be assigned to an interface (except /31, /32, /127, /128). DNS name is lower-cased. NAT inside points at another address of the same tenant. Duplicates are refused as for prefixes unless every address involved has a repeating role.
- **VLAN group.** Name unique per tenant, VLAN ID ranges inside 1-4094 that do not overlap, optional site scope. Available and next free VLAN ID.
- **VLAN.** VID 1-4094, name, status, role, optional site and group. Unique VID and name inside a group; the VID must fall in the group's ranges; a group scoped to a site only takes VLANs of that site.
- **VRF.** Name, optional route distinguisher (unique per tenant), "enforce unique space".
- **Role.** Name unique per tenant, weight.

## Phase 1 build order

1. Pure rules (`services/ipam_logic.py`) with tests.
2. Models, migration `ipam_core`, `ipam` permission section.
3. Routers for VRF, role, VLAN group, VLAN, prefix, IP range, IP address, overview; tests (isolation, permissions, validation, hierarchy, available space).
4. Vue: IPAM menu group, prefixes (hierarchy list and detail), IP addresses, IP ranges, VLANs and groups, VRFs, roles; forms; English and Italian text.

## Phase 1 API (all under `/ipam`, read 1, write 2, delete 3)

- `GET /overview`, `GET /options`
- `GET/POST /vrfs`, `GET/PUT/DELETE /vrfs/{id}`; `GET/POST /roles`, `PUT/DELETE /roles/{id}`
- `GET/POST /vlan-groups`, `GET/PUT/DELETE /vlan-groups/{id}`, `GET /vlan-groups/{id}/available-vids`; `GET/POST /vlans`, `GET/PUT/DELETE /vlans/{id}`
- `GET/POST /prefixes` (filters: search, contains, within, vrf, status, family, role, site, VLAN, mask length), `GET/PUT/DELETE /prefixes/{id}`
- `GET /prefixes/{id}/prefixes` (child prefixes with the free blocks), `POST /prefixes/{id}/available-prefixes` (take the lowest free block of a mask length)
- `GET /prefixes/{id}/ip-addresses`, `GET /prefixes/{id}/ip-ranges`, `GET /prefixes/{id}/available-ips`, `POST /prefixes/{id}/available-ips` (take the next free address)
- `GET/POST /ip-ranges`, `GET/PUT/DELETE /ip-ranges/{id}`, `GET /ip-ranges/{id}/ip-addresses`, `GET /ip-ranges/{id}/available-ips`
- `GET/POST /ip-addresses` (filters: search, within, vrf, status, role, family, asset, interface, assigned), `GET/PUT/DELETE /ip-addresses/{id}`
- `GET /asset-interfaces?q=` to find the interface an address is assigned to

## Differences from NetBox

- No `scope` generic relation: a prefix and a VLAN group take an optional site; locations and regions are not used.
- VLAN group scope is the site only. Q-in-Q, VLAN translation and L2VPN are not carried over.
- No custom fields, tags, contacts or change log; the audit log records every change.
- A VRF has no route targets yet (later phase). Services, FHRP groups, ASNs, RIRs and aggregates are later phases.
- Prefix depth and child count are recalculated by the application after each change (NetBox does it in a signal), per routing table.
- The range label writes the shared leading part of two addresses once and stops at the first part that differs (NetBox keeps matching later parts too).

## Status

| Step | Status |
|---|---|
| 1 Pure rules (`services/ipam_logic.py`, 50 tests) | done, not committed |
| 2 Models and migration `ipam_core` (applied to schema `assets_applications` by the backend start-up) | done, not committed |
| 3 Routers and tests (`ipam_basics`, `ipam_prefixes`, `ipam_addresses`, 40+ API tests; also run on PostgreSQL inside a rolled-back transaction) | done, not committed |
| 4 Vue pages (prefixes, prefix detail, IP addresses, IP ranges, VLANs and groups, VRFs and roles), English and Italian | done, not committed; not checked on screen (login needed) |

## Phase 2: asset link (done, not committed)

- **Asset page.** The Network Interfaces card shows the IPAM addresses assigned to each interface (cards and table), for users who can read `ipam`. Each address links to the IP address list.
- **Import from asset interfaces.** `POST /ipam/import/asset-interfaces` (full administration of `ipam`, because the path is an import) reads the IP field of every interface of a live asset in this tenant and creates an IPAM address assigned to that interface.
  - The field may hold several addresses (comma, semicolon or space). The mask comes from `address/mask`, else from the interface's subnet mask (length or dotted), else the address is a single host (/32, /128).
  - `dry_run` (the default) reports what would happen: create, link, already imported, duplicate, invalid. Invalid covers text that is not an address, a bad mask, a network ID or broadcast address, and an address inside a range marked populated.
  - An address already in IPAM and not assigned is linked to the interface. Running again skips interfaces already linked.
  - `vrf_id` picks the routing table; `per_site` gives each site its own VRF named after the site (created when missing, reused when the name exists), because plants often reuse private addresses; `create_prefixes` also creates the network of each address once and recalculates the hierarchy.
  - A fixed number of queries whatever the number of interfaces; one transaction; one audit entry for the run.
- The IP, mask and VLAN text on the interface is never changed.
- Dry run on the real data (read-only): 633 addresses on 633 interfaces in one tenant; imported into one table 308 are created and 325 skipped as duplicates, with one VRF per site 359 are created and 274 skipped.
- Files: `services/ipam_import.py`, `routers/ipam_import.py`, `tests/test_ipam_import.py`; `components/features/ipam/IpamInterfaceImport.vue`; `AssetDetailInterfaces.vue`, `IpamAddresses.vue`.

## Phase 3: registry (done, not committed)

- **Tables** (migration `ipam_registry`, after `ipam_core`): `ipam_rirs`, `ipam_aggregates`, `ipam_asns`, `ipam_asn_ranges`, all tenant-scoped, in the same schema. The `ipam` permission covers them.
- **RIR.** Name unique per tenant, "private" flag (the space it manages is private, for example RFC 1918). Cannot be deleted while an aggregate, ASN or ASN range uses it.
- **Aggregate.** An IPv4 or IPv6 block assigned by a RIR; host bits are cleared, no /0. Aggregates of a tenant never overlap: a block covered by one, or covering one, is refused (NetBox rule). Utilization is the share of the block covered by prefixes of every routing table (nested prefixes count once). The aggregate page lists the prefixes inside it with the free blocks between them, and can create the lowest free prefix of a mask length. The prefix page shows its aggregate. Deleting an aggregate keeps the prefixes.
- **ASN.** A 16- or 32-bit number, entered as `65000`, `AS65000` or ASDOT `1.10`; shown as `AS65546 (1.10)` above 16 bits. Unique per tenant (NetBox: unique across the whole install). Optional role from the IPAM roles.
- **ASN range.** Name, RIR, first and last number (the last must be higher); shows how many ASNs are used and free, lists the ASNs inside it and the first free numbers. Deleting a range keeps the ASNs.
- **API** (under `/ipam`): `GET/POST /rirs`, `PUT/DELETE /rirs/{id}`; `GET/POST /aggregates`, `GET/PUT/DELETE /aggregates/{id}`, `GET /aggregates/{id}/prefixes`, `POST /aggregates/{id}/available-prefixes`; `GET/POST /asns`, `GET/PUT/DELETE /asns/{id}`; `GET/POST /asn-ranges`, `GET/PUT/DELETE /asn-ranges/{id}`, `GET /asn-ranges/{id}/asns`, `GET /asn-ranges/{id}/available-asns`. The overview counts the four new kinds.
- **UI:** menu entries "Aggregates and RIRs" and "ASNs"; aggregate list and detail page, RIR tab, ASN and ASN range tabs, English and Italian.
- Files: `routers/ipam_registry.py`, `tests/test_ipam_registry.py`, `alembic/versions/ipam_registry.py`; `pages/IpamAggregates.vue`, `IpamAggregateDetail.vue`, `IpamAsns.vue`, `components/forms/IpamAggregateForm.vue`. The prefix output moved to `ipam_service.prefix_items` so aggregates and prefixes share it.
- Not carried over: contacts, tags, and the NetBox link from a site to its ASNs (sites here have no ASN field).

## Phase 4: route targets, services, FHRP groups (done, not committed)

- **Tables** (migration `ipam_services`, after `ipam_registry`): `ipam_route_targets`, `ipam_vrf_route_targets` (VRF to route target, direction import or export), `ipam_service_templates`, `ipam_services`, `ipam_service_addresses`, `ipam_fhrp_groups`, `ipam_fhrp_assignments`; plus one nullable column `ipam_ip_addresses.fhrp_group_id`. Same schema, tenant-scoped, covered by the `ipam` permission.
- **Route targets.** Value `ASN:number` or `IPv4:number` (RFC 4364), unique per tenant. A VRF has import and export lists; on update, lists that are not sent stay unchanged. Deleting a route target removes it from the VRFs (they stay).
- **Service templates.** Name (unique per tenant) and ports. Ports are written `tcp/80, udp/53, tcp/8000-8010` (TCP, UDP, SCTP; 1-65535), stored one `protocol/port` per entry, shown compressed.
- **Services.** A name, ports and exactly one owner: an asset of the tenant or an FHRP group (NetBox uses a device, VM or FHRP group; here assets), optionally tied to some IP addresses. `POST /services/from-template` copies the name, ports and description of a template; the copy is independent. The UI fills the form from a template instead.
- **FHRP groups.** Protocol (VRRPv2, VRRPv3, HSRP, GLBP, CARP, ClusterXL, other), group ID 0-32767, optional name, optional authentication (plain text or MD5) with the key kept encrypted and never returned (`has_auth_key`; an unsent key is kept, an empty one clears it). Interfaces of assets take part with a priority 0-255. An IP address can be assigned to a group instead of an interface (a virtual address); its role follows the protocol (vrrp, hsrp, glbp, carp, vip) unless set, and a virtual address may repeat across peers. Deleting a group deletes its services and interface assignments and keeps the addresses, now unassigned.
- **API** (under `/ipam`): `GET/POST /route-targets`, `PUT/DELETE /route-targets/{id}`; `GET/POST /service-templates`, `PUT/DELETE /service-templates/{id}`; `GET/POST /services`, `POST /services/from-template`, `GET/PUT/DELETE /services/{id}`; `GET/POST /fhrp-groups`, `GET/PUT/DELETE /fhrp-groups/{id}`, `POST /fhrp-groups/{id}/assignments`, `PUT/DELETE /fhrp-groups/{id}/assignments/{assignment_id}`; the IP address list filters by `fhrp_group_id`. The overview counts the four new kinds.
- **UI:** menu entries "FHRP groups" and "Services"; FHRP group list and detail page (virtual addresses, interfaces with priority, services); services page with a templates tab; a Route targets tab on the VRFs page and import/export pickers on the VRF form; an FHRP group picker on the IP address form.
- Files: `routers/ipam_routing.py`, `tests/test_ipam_routing.py` (12 API tests, also run on PostgreSQL in a rolled-back transaction), `alembic/versions/ipam_services.py`; `pages/IpamServices.vue`, `IpamFhrpGroups.vue`, `IpamFhrpGroupDetail.vue`, `components/forms/IpamServiceForm.vue`, `IpamFhrpGroupForm.vue`.
- Not carried over: tags, contacts, the NetBox owners "device" and "virtual machine" for a service (use the asset).

## Phase 5: CSV import and export, audit-pack sheets (done, not committed)

- **Export.** `GET /ipam/export/{prefixes|ip-addresses|vlans}` (read level, like the lists; `vrf_id` or `global_table` limit prefixes and addresses to one routing table) returns a UTF-8 CSV with a byte order mark, so Excel reads accented text. Names stand in for IDs: VRF, role, site, VLAN group and VLAN ID, asset (tag, else name) and interface, FHRP protocol and group number. A text starting with `= + - @` is written with a leading apostrophe against spreadsheet formulas; the import removes it. Each export writes one audit entry.
- **Columns.** prefixes: `prefix, vrf, status, role, vlan_group, vlan_vid, site, is_pool, mark_utilized, description`. ip-addresses: `address, vrf, status, role, dns_name, asset, interface, fhrp_protocol, fhrp_group, description`. vlans: `vid, name, group, status, site, role, description`. The NAT inside link and the VLAN group definitions are not in the files.
- **Import.** `POST /ipam/import/csv/{kind}` (the path contains `/import/`, so full administration, level 4), multipart with `file`, `dry_run` (default true), `update_existing`, `skip_invalid`. Comma, semicolon or tab separated (taken from the header line), up to 5 MB and 20,000 rows, headers in any case.
  - Every row goes through the same rules as the forms: the `ipam_logic.clean_*` functions, then the rules that need the database, planned in memory from one read of each table and written in one transaction (a fixed number of queries). Unique space (also inside the file), populated ranges, VLAN group ID ranges and site, assignable addresses, names of the tenant only (a VRF, role, site or asset of another tenant is "unknown").
  - Each row is `create`, `update`, `skipped_duplicate` (already there, or twice in the file) or `skipped_invalid` with the reason and the line number. A file with invalid rows is refused with 422 unless `skip_invalid` is set. An existing object is replaced only with `update_existing`; an update replaces every column like the form does, a blank cell clears the value, and the NAT link of an address stays.
  - Prefix imports rebuild the hierarchy of each routing table touched. One audit entry for the run.
  - A file exported and imported back with `update_existing` changes nothing (tested).
- **Audit pack.** Extra sheets for a user who can read `ipam`, only for the kinds the tenant uses: IPAM prefixes (with utilization and free IPs), IPAM addresses (with the asset and interface), IPAM VLANs, IPAM aggregates (tenant-wide, left out of a single-site pack), IPAM services, IPAM FHRP groups. A site pack keeps rows of that site and rows with no site. The authentication key of a group is never written, only whether one is set.
- **UI:** "Export CSV" and "Import CSV" on the prefix, IP address and VLAN pages; the import dialog shows the columns, previews, lists problems first and imports; English and Italian.
- Files: `services/ipam_csv.py`, `services/ipam_report.py`, `routers/ipam_export.py`, `routers/ipam_import.py`, `services/report_service.py` (hook), `tests/test_ipam_csv.py` (15 tests, also on PostgreSQL in a rolled-back transaction); `components/features/ipam/IpamCsvTools.vue`.
- Not carried over: CSV for ranges, VRFs, roles, aggregates, ASNs, services and FHRP groups, and bulk edit by ID as in NetBox.

## Phase 6: NetBox parity (done, not committed)

A check of every NetBox IPAM model (`sampark_netbox/netbox/ipam/models`, 18 models) against what phases 1-5 built. All 18 existed except the two VLAN translation models; the columns below were missing. Approved by the user to change the existing IPAM tables, `assets`, `asset_interfaces`, the IPAM routers and the asset page.

| NetBox | Here |
|---|---|
| VLANTranslationPolicy, VLANTranslationRule | new tables `ipam_vlan_translation_policies`, `ipam_vlan_translation_rules`; policy and rule API, a "Translation policies" tab on the VLAN page; a policy can be applied to an interface and cannot be deleted while one uses it |
| VLAN `qinq_role`, `qinq_svlan` | `ipam_vlans.qinq_role` (svlan/cvlan), `qinq_svlan_id`; NetBox rules (only a customer VLAN has a service VLAN, a customer VLAN must have one, the service VLAN must be a service VLAN); unique (service VLAN, VID) and (service VLAN, name); a service VLAN with customer VLANs cannot be deleted |
| `slug` on RIR, role, VLAN group, ASN range | column on those 4 tables (filled from the name for existing rows, numbered when two names give the same slug), unique per tenant; typed or made from the name on create, kept on update |
| `comments` on every primary and organizational model | `comments` text (5000 characters) on the 15 tables that have a description; in every API output and form (`IpamComments.vue`) |
| Prefix and VLAN group scope (region, site group, site, location, rack, cluster) | `location_id` on prefixes and VLAN groups next to `site_id`: a site, or a location of it (a location brings its site; a location of another site, deleted or of another tenant is refused). Regions, site groups, racks and clusters do not exist in this app |
| Device `primary_ip4`, `primary_ip6`, `oob_ip` | `assets.primary_ip4_id`, `primary_ip6_id`, `oob_ip_id`: NetBox rules (right family, assigned to an interface of the asset or the NAT outside of one, one address for one asset), an address that is primary cannot be moved to another interface |
| Interface `vrf`, `mode`, `untagged_vlan`, `tagged_vlans`, `vlan_translation_policy` | `asset_interfaces.vrf_id`, `vlan_mode` (access, tagged, tagged-all, q-in-q), `vlan_translation_policy_id`, and table `ipam_interface_vlans` (one untagged per interface by a partial unique index); NetBox rules (an untagged VLAN needs a mode, tagged VLANs only in tagged mode, a VLAN must be of the asset's site or global). The text fields `vlan`, `ip_address`, `subnet_mask` on the interface are untouched |
| Site `asns` | table `ipam_site_asns`; sites on the ASN form and list, `site_id` filter |
| Filtersets | prefixes: `mask_length_gte/lte`, `depth`, `children`, `is_pool`, `mark_utilized`, `location_id`, `vlan_group_id`, `vlan_vid`, `present_in_vrf_id`; ranges: `parent`, `present_in_vrf_id`, `mark_populated`, `mark_utilized`, `global_table`; addresses: `parent`, `mask_length(+gte/lte)`, `present_in_vrf_id`, `service_id`, `nat_inside_id`, `dns_name`; VLANs: `qinq_role`, `qinq_svlan_id`, `available_at_site`; VLAN groups: `site_id`, `location_id`, `contains_vid`; VRFs: `import_target_id`, `export_target_id`; route targets: `importing_vrf_id`, `exporting_vrf_id`; FHRP groups: `auth_type`, `related_ip_id`; ASNs: `site_id` |

- **Migration** `ipam_parity` (after `ipam_services`). Tested on a throwaway PostgreSQL: schema built from the models, stepped back with the downgrade, rows added in the old shape (slug collisions, two tenants), upgraded, compared with the models (no difference but cosmetic server defaults), then downgrade and upgrade again.
- **API added:** `/ipam/vlan-translation-policies` (+ `/{id}/rules`), `/ipam/vlan-translation-rules`, `GET/PUT /ipam/interfaces/{id}`, `GET /ipam/assets/{id}/interfaces`, `GET/PUT /ipam/assets/{id}/primary-ips`, `GET /ipam/vlans/{id}/interfaces`.
- **UI:** the asset page interface card shows the primary addresses (with an edit dialog) and, per interface, the VRF, mode and VLANs (with an edit dialog); comments, slug, location, Q-in-Q and ASN sites in the existing forms; English and Italian.
- Tests: `tests/test_ipam_parity.py` (14), plus the existing IPAM tests updated for the new keys.
- **Not carried over (NetBox platform features this app does not have as shared subsystems):** customer "tenant" (the app tenant already isolates data), tags, custom fields, contacts on IPAM objects, journal entries, bookmarks, export templates, custom links, event rules, GraphQL, bulk edit by ID. L2VPN terminations (no L2VPN module here). The IPAM CSV files do not yet carry `comments`, `slug` or the interface settings.

## Next phases

None: the five planned phases and the NetBox parity pass are built.
