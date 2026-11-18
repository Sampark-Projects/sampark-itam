# Applications module: plan and status

Source: "Application Fields" and "How to configure Application in Industrace and Create connection (topology)".
Branch: `feature/applications` (from `feature/ot-lifecycle`). Database: schema `assets_applications`, a full copy of `assets_lifecycle`.

## Approach

- **Additive only.** New tables, routes, pages and one permission section. No existing table, column, route or screen changes meaning.
- **Read from existing modules, do not copy.** Server details come from linked assets, middleware from the software inventory, the topology from the existing connections.
- **Isolated risk.** Application vulnerabilities live in their own table, so the CVE feed, matching and risk score work as before.
- **Gate = permission.** The `applications` section is the switch. The migration grants full access to administrator roles (level 3 or more on `roles`), Write (2) to roles named "editor" and Read (1) to roles named "viewer". Any other role (for example "reviewer") has no access until an administrator grants it on the Role page.
- **Fast by design.** Server-side paging and filters, indexes on tenant, name and SSL expiry, no per-row queries, lazy tabs, a topology limited to one application.

## Phases

| Phase | Content | Status |
|---|---|---|
| 1 | Application record: Overview (identity, ownership, URLs, SSL expiry) and Security, compliance and backup (classification, firewall rule IDs, backup policy, RPO/RTO, last scan). List page with paging, search and filters. Permission section, migration `applications_core`, English and Italian text. | Done locally, not committed |
| 2 | Link assets to an application with a role (web, app, database, load balancer ...). Infrastructure tab (compute and servers, network and IP addressing) and Software tab read from the linked assets. Integrations (upstream and downstream systems). DNS records. Migration `applications_hosting`. | Done locally, not committed |
| 3 | Topology view for one application from the linked assets' connections plus the integration nodes, drawn with the same library as the Network map. | Done locally, not committed |
| 4 | VAPT assessments (signed report uploaded) and application findings with remediation, SLA, retest and risk acceptance. Migration `applications_security`. | Done locally, not committed |
| 5 | Alerts (SSL expiry, next VAPT, fix deadlines, risk-acceptance exceptions), overview numbers on the Applications page, audit-pack sheets. Migration `applications_alerts`. | Done locally, not committed |

## Phase 1 details

- API: `GET/POST /applications`, `GET/PUT/DELETE /applications/{id}`, `GET /applications/options`. Read needs level 1, write 2, delete 3.
- List: `GET /applications?search=&tier=&lifecycle_status=&site_id=&skip=&limit=` returns `{total, skip, limit, has_more, items}`.
- Numbering APP-0001 per tenant (unique key plus retry). Names are unique per tenant, ignoring case.
- Validation: URLs must be http or https; tier, lifecycle status and data classification come from fixed lists; RPO and RTO are whole hours.
- Every create, update and delete is written to the audit log.
- Files: `backend/app/models/application.py`, `services/application_logic.py`, `routers/applications.py`, `alembic/versions/applications_core.py`, `tests/test_applications.py`; `frontend/src/pages/Applications.vue`, `ApplicationDetail.vue`, `components/forms/ApplicationForm.vue`, `locales/{en,it}/applications.json`.
- Existing files touched only to register the new pieces: `main.py`, `models/__init__.py`, `error_codes.py`, `rbac_permissions.py`, `init_roles.py`, `api.js`, `router.js`, `SidebarMenu.vue`, `usePermissions.js`, `RoleDetails.vue`, `RoleForm.vue`, locale files for menu, roles, core errors and the locale loader.

## Phase 2 details

- Tables: `application_assets` (application, asset, role, environment, listening ports, notes; unique per pair), `application_integrations` (name, direction, protocol, port, optional linked asset, notes). Column `applications.dns_records`.
- Existing table extended (nullable, additive): `asset_software.install_path` and `license_type`, also editable on the asset page software card.
- API (under `/applications/{id}`): `GET infrastructure`, `GET asset-search?q=&include_linked=`, `POST/PUT/DELETE assets`, `GET software`, `GET/POST/PUT/DELETE integrations`. The list adds `asset_count` and `integration_count` from two grouped queries.
- Nothing is copied from the assets: hostname, type, status, site, interfaces (IP, VLAN, subnet, gateway, protocols) and the operating system (first OS entry of the software list) are read at view time, in a fixed number of queries. At most 200 linked assets and 200 integrations per application.
- Linking needs level 2, unlinking and deleting level 3. Only assets of the same tenant can be linked. Unlinking or deleting an application never deletes the asset.
- Files: `backend/app/routers/application_hosting.py`, `tests/test_application_hosting.py`, `frontend/src/components/features/applications/*`.

## Phase 3 details

- `GET /applications/{id}/topology?include_inferred=true` returns `{nodes, edges, summary}`. No new tables.
- Nodes: end users, the primary (and secondary) URL, the linked assets, and the connected systems. Layers top to bottom: users, URL, load balancer, web, application, data tier (database, cache, queue, storage), then outbound systems; inbound systems sit above the application.
- Edges: users to URL with the protocol from the address (HTTPS / 443); URL to the first layer present; **recorded asset connections** between linked assets (solid, labelled protocol / port); **role-based links** where nothing is recorded (dashed, optional with the "Show links based on roles" switch); connected systems from the application tier, with direction.
- Badge: a node with open critical or high vulnerabilities from the Vulnerabilities module (status unreviewed or acknowledged) gets a coloured border and a "[!] n high" line. Application findings from phase 4 will add to it.
- Pure builder: `backend/app/services/application_topology.py`; endpoint in `routers/application_hosting.py`; tab `ApplicationTopologyTab.vue` (vis-network, hierarchical layout, zoom, fit, PNG export, double-click opens the asset).
- Only linked assets are drawn; a connection to an asset that is not linked is ignored.

## Phase 4 details

- Tables `application_vapt_assessments` (VAPT-0001 per tenant) and `application_findings` (VULN-0001 per tenant). A finding may point at an assessment, an asset of the application and, by its CVE, at the existing vulnerability catalogue; it keeps its row if those go away.
- Assessment: type, methodology, scope, assessor, status (scheduled, in progress, remediation, closed), test date, next due date, report (file upload up to 10 MB or a link), overall posture, sign-off name and date. The scorecard counts open findings by severity from the findings; the posture is chosen by the person signing off, with a suggestion (fail with any open critical or high, conditional with medium or low, pass otherwise).
- Finding: severity, CVSS, source, affected asset (must be linked to the application), target and component, exploitability, remediation status (open, patch assigned, retest pending, verified fixed, risk accepted), recommended fix, owner, discovery date, fix deadline (default from severity: critical 7 days, high 30, medium 90, low 180, info 365), retest date and result, exception ID and validity.
- Rules: verified fixed needs a retest that passed; risk accepted needs an exception ID; a retest result needs a date; an expired exception is flagged; an open finding past its deadline is overdue.
- API under `/applications/{id}`: `GET security-summary`, `GET/POST/PUT/DELETE vapt`, `POST/GET/DELETE vapt/{id}/report`, `GET/POST/PUT/DELETE findings` (paged; filters state, remediation_status, severity, overdue, vapt_id, asset_id, search). Read level 1, write 2, delete 3.
- The topology badge now also counts the application's own open critical and high findings per affected asset.
- Sign-off is a name and a date (no approval workflow yet). Files: `routers/application_security.py`, `services/application_security_logic.py`, `services/upload_check.py`, `tests/test_application_security.py`, `frontend/.../ApplicationSecurityTab.vue`, `ApplicationVaptAssessments.vue`, `ApplicationFindings.vue`.

## Phase 5 details

- **Alerts.** Tenant settings (on or off, lead days default 90, 30, 7, warning before a fix deadline default 3 days) in `application_alert_settings`; sent steps are recorded in `application_alerts_sent` so nothing goes twice. The daily background job (the one that runs the other expiry alerts) and a "Send due alerts now" button run the same check. One e-mail per application and run lists everything that reached a step: SSL expiry, next VAPT (from the latest completed test, or a scheduled one), open findings close to or past their deadline, and risk-acceptance exceptions that run out. Retired applications are skipped. Template `application_alert` (created at start-up). Finding titles are escaped in the HTML.
- **Recipients (default used).** The users who administer the Applications section (level 3). Owners are free text on the application, so they are not matched to users. If nobody administers the section, nothing is recorded and the alert goes out later.
- **Overview.** `GET /applications/overview`: totals, tiers, SSL expired and expiring in 30 days, VAPT overdue or never tested, open critical and high findings, overdue fixes, expired exceptions, applications with no assets. Eleven grouped queries, shown as a strip on the Applications page.
- **Audit pack.** Five sheets are added when the tenant has applications: Applications, Application assets, Application integrations, VAPT, Application findings (filtered by the site when one is chosen; applications with no site are kept). Tenants without applications get the same workbook as before.
- **Settings and send-now** need Applications level 3 (`/application-alerts/settings`, `/application-alerts/run`).
- **VAPT sign-off** stays a name and a date. A real approval step (reusing the multi-level purchase approval) is not built.
- Not built, can follow: webhook events and an external API for applications, matching owners to users for alerts, dashboard KPIs per site.

## Working schema

`assets_applications` was cloned from `assets_lifecycle` with all 88 tables, data, 193 foreign keys, 284 indexes, the enum type and the sequence. The local `.env.db` now has `DB_SCHEMA=assets_applications`. **Set it back before deploying** (it is the same file used on the server). The backend applies migrations on start-up, so any database that runs this code gets `applications_core`.
`assets_lifecycle` stays as it was (migration `remove_change_requests`, no applications table), and the production `assets` schema is untouched.

## Open decisions (defaults used)

Application is its own table; servers are linked, not retyped; URL and downstream systems are lightweight nodes owned by the application; application vulnerabilities are a separate table with an optional CVE link. Still to confirm: whether the VAPT sign-off is a real approval step and which alerts are wanted.
