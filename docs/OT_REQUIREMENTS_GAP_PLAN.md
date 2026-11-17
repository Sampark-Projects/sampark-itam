# OT Asset Management — Requirements Gap Plan

Source: *OT Asset Management Solution for Complete Lifecycle Management of Operational Technology Assets* (VECV, Dewas pilot).
Scope read: sections 1–5.4 (Annexure B and later sections were not in the file).

## 1. Working agreement

| Item | Value |
|---|---|
| Git branch | `feature/ot-lifecycle` (from `release/qa`) |
| Database schema for this work | `assets_lifecycle` (copy of `assets`, taken 2026-11-14, 60 tables, 6,132 rows) |
| Original schema | `assets` stays untouched and keeps serving the current server |
| Local switch | `DB_SCHEMA=assets_lifecycle` in the git-ignored `.env.db` (set `DB_SCHEMA=assets` to go back) |
| Local app port | Frontend on http://localhost:5174 (Vite still listens on 5173 inside the container); backend on 8000 |
| Migrations | Alembic, applied to `assets_lifecycle` first; must stay compatible with `assets` |

Rules: new fields are additive and nullable; no existing column is changed or dropped; every new module gets an RBAC section; every user-visible string goes into the English and Italian locale files.

## 2. Gap summary (section 5, 22 requirements)

**2 met, 8 partly, 12 not met.**

| # | Requirement | Today | Phase |
|---|---|---|---|
| 5.1 | Configurable data model, custom fields | Partial: per-asset custom fields; `asset_types.fields_schema` exists but has no UI | 1 |
| 5.1 | Company / Plant / Unit / Track / Cell hierarchy | Partial: nested Sites, Areas, Locations | 0 |
| 5.1 | Classify by type, Purdue, zone, criticality, safety | Partial: no safety relevance field | 1 |
| 5.1 | Ownership (plant owner, contact, vendor/AMC) | Partial: contacts and suppliers linked, no AMC data | 1 |
| 5.1 | Audit trail and history | Met | — |
| 5.1 | Unique IDs, naming / tagging standard | Partial: free-text tag only | 1 |
| 5.1 | Parent-child components | Partial: dependencies only | 1 |
| 5.1 | Documents against the asset | Met | — |
| 5.2 | Configurable lifecycle workflow, approvals, tasks | Not met | 3 |
| 5.2 | Procurement details | Not met | 1 |
| 5.2 | Receive and onboard, validation, auto ID | Not met | 3 |
| 5.2 | Commissioning and acceptance sign-off | Partial | 1 |
| 5.2 | Warranty / AMC / support / licence expiry alerts | Not met | 2 |
| 5.2 | Vendor end-of-sale / support / life database | Not met | 2 |
| 5.2 | Replacement and obsolescence plan | Not met | 2 |
| 5.2 | Retirement workflow, wipe, disposal evidence | Not met | 3 |
| 5.2 | Total cost of ownership | Not met | 2 |
| 5.2 | Spare parts tracking | Not met | 5 |
| 5.3 | Versioned programs, configurations, firmware | Partial: one firmware field | 4 |
| 5.3 | Golden baselines and change detection | Not met | 4 |
| 5.4 | Change requests, unapproved-change flags | Not met | 5 |
| 5.4 | Maintenance history, integration | Not met | 5 |

## 3. Reusable building blocks

- Background scheduler (`background_tasks.py`) with email, review and probe loops
- Notification service (templates, queue, preferences, email)
- Audit log decorator and asset timeline
- Vulnerability feed service, a pattern for a vendor end-of-life feed
- Configurable asset statuses and types per tenant; `asset_types.fields_schema`
- Alembic migrations, RBAC section list, asset documents, CSV / Excel import and export

## 4. Phases

Sizes are rough: S = days, M = 1–2 weeks, L = several weeks.

### Phase 0 — Decisions and no-code setup (S)
- Decide: one tenant for all plants or one per plant
- Decide: Annexure B attribute list and the naming / tagging standard
- Decide: CMDB / ITSM and maintenance systems to integrate; approvers for lifecycle, retirement and change
- Set up: hierarchy convention (Site = company / plant / unit, Area = line or track, Location = cell or station)
- Set up: asset types for the missing OT classes and lifecycle statuses (seeded, not hand-edited)

### Phase 1 — Richer asset data (M)
- Expose `fields_schema` in Asset Types and render those fields in the asset form
- Structured fields: safety relevance; procurement (requisition, PO, vendor, cost, delivery date); warranty, AMC and support contract with dates; commissioning and acceptance sign-off; plant owner and AMC partner
- Naming / tag standard: pattern per type or site, auto-generation, validation, uniqueness
- "Component of" parent-child link
- Done when the fields appear in form, list, detail, export and API

### Phase 2 — Alerts, end-of-life, cost (M–L)
- Expiry-alert loop with configurable lead times, on the notification system
- Vendor lifecycle table (end-of-sale / support / life by manufacturer and model), loaded by CSV import, matched to assets
- Obsolescence report by year, plant and criticality
- Cost per asset from purchase, maintenance and upgrade records

### Phase 3 — Lifecycle and retirement workflow (L)
- Configurable stage workflow with role-based tasks and approvals
- Onboarding validation against the order, automatic ID / tag
- Retirement: decommission approval, data-wipe confirmation, disposal evidence, archive

### Phase 4 — Configuration management (L)
- Versioned configurations, programs and firmware per asset, with files
- Golden baselines, before / after comparison, change alerts, backup status
- Start with uploaded and imported versions; direct device connectors are a later step

### Phase 5 — Change and maintenance (M–L)
- Change requests linked to assets; flag audit-log changes with no approved request
- Maintenance records (preventive, corrective)
- Spare parts linked to installed assets
- Maintenance-system integration once named in Phase 0

### Phase 6 — Integrations and reporting (M–L)
- Read / write external API, CMDB or ITSM connectors, webhooks
- Plant / unit / track dashboards with targets; audit-ready reports

## 5. Order

1. Phase 0, then 1, then 2 (Dewas pilot)
2. Phases 3 and 5
3. Phases 4 and 6 (depend on external systems and data)

## 6. Open questions

1. What is in Annexure B, and what is VECV's naming standard?
2. One tenant or one per plant?
3. Which CMDB / ITSM and maintenance systems must integrate?
4. Where does the vendor end-of-life data come from?
5. Who approves lifecycle stages, retirement and changes?

Until answered, Phase 1 and 2 use the assumptions listed in the commit messages and in this section's tracker below.

## 6a. Phase 1 behaviour worth knowing

- A tag is checked only when it is new or changed, so existing assets can still be edited. XLSX import does not go through the naming check yet.
- Uniqueness is case-insensitive per tenant and counts trashed assets, so restoring one cannot create a duplicate.
- Naming rules reuse the `asset_types` RBAC section. Type-specific fields are not enforced on the server: required fields are checked in the asset form.
- Deleting a parent asset keeps its components (parent link is cleared).

## 6b. Phase 2 behaviour worth knowing

- Alerts go to the owner and point-of-contact contacts of an asset whose e-mail matches a user. An asset with no such user is counted as "no recipients" and retried on the next run; nothing is recorded until someone is notified.
- A step fires once per asset, date field and expiry date. An expiry first seen late sends one alert at the step it has reached (20 days out with steps 90/30/7 sends the 30 alert). Expired dates alert once, up to a year back.
- Vendor entries match on manufacturer name (case-insensitive) and model; `*` and `?` are wildcards and the most specific entry wins. Obsolescence is end of support, else end of life; end of sale alone does not count.
- Cost is never converted between currencies. Maintenance and upgrade records from Phase 5 will feed the same cost entries.
- The Lifecycle page and its endpoints use the `lifecycle` RBAC section (read to view; write to import, add costs and run alerts; level 3 to change alert settings). See 6g.
- Alert e-mails need a working mail setup (the existing notification queue); the vendor data itself still has to be loaded (open question 4).

## 6c. Phase 3 behaviour worth knowing

- Defaults are created per tenant on first use. Onboarding: receive and verify (PO, received date, serial, model, manufacturer, status Received), install and commission (status Commissioning), acceptance sign-off (approval, status Active). Retirement: decommission approval, data wipe confirmation (comment and tick-box), disposal evidence (uploaded document and comment), archive (status Retired). No step has a role until an administrator assigns one in Workflow setup; until then anyone with `lifecycle` write access can act.
- Open question 5 (who approves) is answered by this configuration rather than by code: pick the role per step. Anyone with `lifecycle` level 3 or more may act outside a step's role; that is recorded on the step as an override.
- The person who started a run cannot approve its approval steps unless the workflow setting allows it. Administrator override does not bypass this.
- A step is blocked until its required asset fields are filled and, when set, a document was uploaded after the run started. Evidence is checked against asset documents, not stored separately.
- One open run per asset (enforced in the database). Rejecting an approval ends the run; steps already done stay done and the asset status is not rolled back. Cancelling is for the starter or an administrator.
- Changing a definition affects only runs started afterwards; each run keeps a copy of its steps.
- Acting on a step needs `lifecycle` write access in addition to the step role. Every start, step action and cancel is written to the audit log, and a status set by a step gets its own asset entry. While a run is in progress, and for the statuses the retirement workflow sets (Retired by default), the asset status cannot be changed by editing, bulk update or creation (see 6g).
- Task and result e-mails use the notification queue (templates `lifecycle_task_assigned`, `lifecycle_run_finished`).

## 6d. Phase 5 behaviour worth knowing

- A change request covers its assets from the moment it is approved until it is marked implemented. An edit to a controlled asset field outside such a window is flagged. The default controlled fields are firmware version, model, manufacturer, site, location, security zone and the remote and physical access fields; administrators change the list in the Settings tab.
- Detection reads the audit log (asset updates only). Changes made through other routes (bulk update, import, interface or IP edits, workflow status changes) are not in that log as asset updates, so they are not flagged. A flag is cleared with a note, not deleted.
- Approving needs the approver role set in Settings, or administrator rights (asset delete level or more). Nobody can approve a change they requested unless the setting allows it. Approvals are not e-mailed yet.
- Completing a maintenance task takes the parts used out of stock (a shortfall stops the completion) and, when a cost is entered, adds a maintenance cost entry on the asset. Deleting a record returns the parts and removes that cost entry.
- A preventive task can schedule its next occurrence when completed. There is no recurring schedule or overdue e-mail yet; overdue tasks show on the Maintenance tab and the asset page.
- Change requests use the `changes` RBAC section (level 3 for the settings and for acting as administrator); maintenance and spare parts use `maintenance`. See 6g.

## 6e. Phase 4 behaviour worth knowing

- Versions are uploaded by hand (any file type, 50 MB by default, `CONFIG_MAX_BYTES` changes it). The server stores the file under the uploads folder with a generated name, records a SHA-256 checksum, and always serves it as a download, never inline. Nothing is executed.
- Small UTF-8 text files (up to 512 KB) also keep their text so two versions can be compared line by line. Other files are compared by checksum and size only.
- "Differs from baseline" compares the newest version with the baseline by checksum. Setting a new baseline or removing one changes the state immediately. The baseline version cannot be deleted until another is chosen.
- A drift alert is sent once per version, to the owner and point-of-contact users of the asset. An overdue-backup alert is sent once per stale period. As with expiry alerts, nothing is recorded when nobody can be notified, so it is retried on the next run.
- A version can reference a change request; the drift e-mail says which one (or that none was given). Drift is not yet checked against change-request approval windows automatically.
- Uses the `configurations` RBAC section; every download of a file is written to the audit log. Deleting an item or version needs delete rights; files are removed from disk with them. Hard-deleting a whole asset does not remove its files from disk yet.

## 6f. Phase 6 behaviour worth knowing

- Webhooks send an event to any URL when a change request moves (submitted, approved, rejected, implemented, closed, cancelled), a workflow starts, completes or is rejected, a configuration drifts, a warranty or support date reaches an alert step, or maintenance is completed. Each endpoint picks its events. They are managed under the `api_keys` RBAC section (read to view, write to change).
- Each request is a POST with a JSON body and the headers `X-Sampark-Event`, `X-Sampark-Delivery`, `X-Sampark-Timestamp` and `X-Sampark-Signature: sha256=<hex>`. The signature is the HMAC-SHA256 of `<timestamp>.<body>` with the endpoint secret. The receiver should reject old timestamps. The secret is shown once (at creation or after rotating) and stored encrypted.
- A non-2xx answer or a network error is retried after 1 minute, 5 minutes, 30 minutes and 2 hours, then marked failed (5 attempts). A worker checks every 30 seconds; finished deliveries are deleted after 30 days. Redirects are not followed.
- Addresses are checked when a webhook is saved and again before every send: only http and https, no credentials in the URL, and loopback, link-local (cloud metadata), unspecified and multicast addresses are refused. Private ranges (10.x, 172.16.x, 192.168.x) are allowed because plant systems live there.
- Events are queued after the action has been saved. A failure in the integration never undoes or blocks the action.
- External API (API key): `GET /external/v1/lifecycle/expiring`, `/changes`, `/maintenance/due`, `/config/status` (read scope) and `PATCH /external/v1/assets/{id}/lifecycle` (write scope). The write route accepts only the lifecycle fields (not the parent link), rejects anything else, and writes an audit entry naming the API key. This is generic: no CMDB or ITSM product-specific connector exists because the system is still unnamed (open question 3).
- Plant dashboard: counts per site (plant or unit) or per area (line or track) for assets, expired support, obsolete assets, baseline coverage, configuration drift, overdue maintenance, open changes, unapproved changes (last 30 days) and workflows in progress. A target is a ceiling for counts and a floor for baseline coverage; a site's own target beats the one for all sites. The dashboard needs `reports` read, the audit pack `reports` level 2, targets `reports` level 3. Status is met, missed, no target or no data (baseline coverage with no configuration items).
- Audit pack: an Excel workbook (Summary, Assets, Vendor end of life, Change requests, Unapproved changes, Maintenance, Configuration, Workflows) for all sites or one, with a period in days (1 to 730). Cells that start with = + - or @ are written as text, and each sheet stops at 20000 rows with a note. Downloading needs `assets` read access.
- Migration `integrations_reporting`; new page Reports and integrations (Plant dashboard, Audit pack, Integrations tabs).

## 6g. Review fixes (H1–H6)

- **RBAC sections (H2).** Five new sections: `lifecycle` (Lifecycle page, workflows, costs), `changes`, `maintenance`, `configurations`, `reports`. Level 1 reads, 2 writes, 3 deletes and changes the module's settings. Migration `rbac_lifecycle_sections` gives every existing role the level it already had on `assets`, so nobody loses or gains access on upgrade; administrators can then narrow it in Roles. Webhooks stay under `api_keys`, tag rules under `asset_types`.
- **Audit trail (H1).** Every create, update, delete and state change in these modules is written to the audit log with user, time, IP and before/after values. This covers change requests (including approvals), flag reviews, maintenance, spare parts, configuration items, versions, baselines and downloads, workflow definitions, runs and steps, vendor entries and imports, costs, alert settings, tag rules, webhooks (secrets are never logged), KPI targets and audit-pack exports. An audit-pack export records the file's SHA-256, which is also sent as `X-Content-SHA256`.
- **Status gate (H3).** The retirement workflow is the only way to reach the statuses it sets, and a running workflow owns the asset status until it ends. Editing, bulk update and creating an asset are refused with `WORKFLOW_STATUS_LOCKED`. Bulk update can no longer set `id`, `tenant_id`, `tag`, `parent_asset_id` or the timestamps.
- **Tag uniqueness (H4).** Migration `asset_tag_unique` adds the unique index `uq_assets_tenant_tag` on (tenant, lower(trim(tag))). Rows that already shared a tag (216 in the copied data, for example 71 tagged "wip") are marked `tag_legacy_duplicate` and left out of the index; changing such a row's tag clears the mark. The duplicates should be cleaned up during the pilot.
- **API tests (H5).** `tests/test_api_ot_modules.py` runs the routers on SQLite and checks RBAC, tenant isolation, audit entries, the status gate, tag uniqueness and webhook address rules.
- **Webhook network rules (H6).** The host is resolved once, every address is checked, and the request goes to that IP with the original Host header and TLS name, so a second DNS answer cannot redirect it. The server's own addresses and those of its database and Redis are always refused. Optional settings: `WEBHOOK_ALLOWED_NETWORKS` (for example `10.20.0.0/16`; when set, only these networks are reachable) and `WEBHOOK_DENIED_HOSTS` (extra hosts to refuse). Webhooks ignore HTTP proxy settings.

## 6h. Requirement gaps, batch 1

Checked against the VECV document (sections 1–5.4). Migration `lifecycle_gaps`.

- **Hierarchy (5.1).** A site can sit under a plant (`Site.parent_id`). Filtering by a plant now includes its units everywhere: the asset list and export, the external API, obsolescence, cost summary, the dashboard and the audit pack. The dashboard has a "Plant (units rolled up)" grouping. A KPI target or naming rule set on a plant applies to its units unless a unit has its own (the closest site wins).
- **Document categories (5.1).** Asset documents have a category (manual, drawing, certificate, purchase order, warranty, delivery note, commissioning, acceptance, test report, data wipe certificate, disposal or return evidence, other). It is chosen at upload and can be changed later. A workflow step can require a document of one category.
- **Commissioning (5.2).** Two checks a step can require: "network settings" (an interface with an IP or MAC address) and "baseline configuration set" (a configuration item with a golden baseline). The default commissioning step requires both; the migration adds them to tenants whose step was still the default. Remove them from the step for non-network assets.
- **Retirement (5.2).** New asset fields: disposal method (scrapped, recycled, returned to vendor, sold, transferred, donated), disposal or return date, certificate / RMA / transfer number. The default "Disposal evidence" step requires the method, the date and a document of category "disposal or return evidence". When a retirement completes, the record is archived: it can no longer be edited, bulk-updated or put through another workflow. A person with `lifecycle` level 3 can reopen it with a reason, which is audited.
- **Spare assets (5.2).** Whole assets kept as spares (for example a spare CPU in stock) can be linked to the installed assets they back up. Both directions show on the asset page.
- **Security fix found on the way.** Updating an asset and its custom fields did not check the tenant, so a user who knew another tenant's asset id could change it. Both now return "not found".

Still open: product-specific CMDB / ITSM / maintenance connectors (systems unnamed), Annexure B attributes, collecting configurations from devices, comparing binary PLC programs, a purchase-order record to validate deliveries against, a plan-and-procure workflow, recurring preventive maintenance, patch and firmware-upgrade records, software inventory, vendor end-of-life feed, end-of-life in the risk score.

## 6i. Requirement gaps, batch 2

Migration `lifecycle_gaps_2`.

- **Plan and procure (4.2 stage 1, 5.2).** Purchase requests (Lifecycle page, "Purchase requests" tab): demand, specification, lines (type, manufacturer, model, quantity, unit cost). Flow: draft, submitted, approved or rejected, ordered (needs the ERP PO number, unique per tenant), received, closed. Approving needs `lifecycle` level 3, and the requester can never approve their own request. Webhook events `purchase.approved / rejected / ordered`.
- **Receive against the order (5.2).** A delivered asset is booked on an order line. Type, manufacturer, model and quantity are checked; a difference is refused unless accepted with a reason, which is kept on the asset and audited. Booking fills the empty PO, requisition, cost, currency, vendor and received-date fields. The workflow check "Delivery checked against a purchase request" (`order_match`) can be added to the receive step; it is not on by default because the requests may not be kept in Sampark.
- **Recurring maintenance (5.4).** Maintenance plans per asset (every N days): a task is created 14 days before each due date; completing it moves the next due date to the interval after the work. Overdue tasks are e-mailed once to the asset owner and point-of-contact users (template `maintenance_overdue`, webhook `maintenance.overdue`). This runs in the daily lifecycle loop.
- **Firmware upgrades and patches (4.2 stage 5).** Maintenance kinds `upgrade` and `patch` record the from and to versions. They can only be completed under an approved (or implemented) change request that covers the asset. Completing an upgrade sets the asset firmware version and writes an asset audit entry.
- **Software inventory (objective 3).** Per asset: kind (OS, application, runtime, firmware module, library, other), name, vendor, version, install date, licence expiry. Uses the `assets` section; audited.
- **End of life in the risk score (objective 4).** Vulnerability side: past the vendor end of support +2, within a year +1, support or AMC contract expired +1 (at most +3), shown in the risk breakdown with a "plan replacement" suggestion. The daily loop recalculates stored scores because these dates pass without edits.
- **Audit pack** gains "Software" and "Purchase requests" sheets, and the maintenance sheet shows versions, change request and plan.

Checked in the browser on 2026-11-15: request form, submit (no Approve offered to the requester), status filter, receive with a model mismatch (refused until accepted) and with a match, the order link on the asset, software card, maintenance plan (first task created within the lead time) and the upgrade fields.

## 6j. Medium review items (M1–M8)

Migration `review_medium_fixes`. All additive; existing data keeps its behaviour.

- **M1 paging / concurrency (external API):** every list endpoint answers `{total, skip, limit, has_more, items}`; the lifecycle read returns an `ETag` and `PATCH` honours `If-Match` (412 `PRECONDITION_FAILED` when stale).
- **M2 webhooks:** rotating a secret keeps the old one signing for 24 h (header `X-Sampark-Signature-Previous`; `?immediate=true` drops it at once). An endpoint is switched off after 10 failed deliveries in a row (reason shown in the UI; switching it on again resets the counter). Failed deliveries can be sent again (`POST /webhooks/deliveries/{id}/redeliver`).
- **M3 configuration files:** stored encrypted at rest (Fernet, chunked; `CONFIG_ENCRYPT_AT_REST`, default on; older plain files still download). The SHA-256 recorded at upload is re-checked on every download; a mismatch returns 409 `CONFIG_INTEGRITY_FAILED` and is audited. Optional ClamAV scan (`CONFIG_SCAN_CLAMD=host:port`): infected files are refused, an unreachable scanner refuses uploads unless `CONFIG_SCAN_FAIL_OPEN=true`. The text kept for version diffs is still stored in the database in plain form.
- **M4 plant-local dates:** `APP_TIMEZONE` drives "today" everywhere (see `local_time.py`).
- **M5 KPI trends:** the daily loop stores one snapshot per tenant and site (`kpi_snapshots`, kept 800 days); `GET /reports/trend` returns daily series and the dashboard shows a card with a sparkline per metric. Today's point is created on demand.
- **M6 audit-pack integrity:** done with H1.
- **M7 change process:** `urgency` normal/emergency (an emergency change can be implemented straight after submitting, its edits are covered from submission, it must be approved or rejected afterwards via `POST /changes/{id}/retro-decision` before it can be closed); change board quorum (`required_approvals` 1–5, distinct approvers, one rejection stops the request, returning to draft resets the approvals); closing needs a post-implementation review outcome; approvers are e-mailed on submit and the requester on approval or rejection (change and purchase requests; templates `approval_requested`, `approval_decided`).
- **M8 recurring maintenance and overdue e-mails:** done in batch 2.

- **Follow-up fixes:** a rejected late decision removes the emergency cover; the late approval needs the full change board (`retro_approvals`); the text kept for diffs is encrypted too (`enc1:` prefix, older rows still readable); optional `CONFIG_ENCRYPTION_KEY` / `CONFIG_ENCRYPTION_KEY_PREVIOUS` for a dedicated or rotated key; Escape in the webhook events list closes only the list.

## 7. Progress tracker

| Phase | Status | Notes |
|---|---|---|
| Setup (branch, schema copy) | Done 2026-11-14 | `feature/ot-lifecycle`, `assets_lifecycle` |
| 0 | Done 2026-11-14 | OT asset types and lifecycle statuses seeded (`backend/app/init_ot_lifecycle.py`); hierarchy convention and decisions still need confirming |
| 1 | Done 2026-11-14 (local, not committed) | Migrations `asset_lifecycle_fields`, `asset_parent_link`, `asset_tag_rules`. 17 lifecycle fields (form, detail, list export, API). Parent-child link with loop checks (`GET /assets/{id}/components`, "Component of" picker, Components card). Type-specific fields: editor in Asset Types, rendered in the asset form, stored in `custom_fields`. Naming rules: pattern per type and/or site (`{SEQ:n}`, `{SITE}`, `{YYYY}`, `{YY}`), auto-generated tag, typed tag checked, case-insensitive uniqueness, `GET /assets/next-tag` preview |
| 2 | Done 2026-11-14 (local, not committed) | Migration `lifecycle_phase2`. Expiry alerts: lead times per tenant, daily scheduler loop, e-mail template `asset_expiry_alert`, each step sent once. Vendor end-of-life table with wildcard models and CSV import, matched to assets. Obsolescence report by year / site / criticality. Cost: purchase cost plus maintenance / upgrade / licence entries per asset, summary per currency. New Lifecycle page and asset-page cards |
| 3 | Done 2026-11-14 (local, not committed) | Migration `lifecycle_workflows`. One configurable onboarding and one retirement workflow per tenant (ordered steps, task or approval, role, required asset fields, document, comment, confirmation, status to set). Runs on an asset with a step checklist, role checks, approval separation, e-mail to the step role, tag generated at onboarding start. Retirement: decommission approval, wipe confirmation, disposal evidence, archive to Retired. Lifecycle page: My tasks, Workflows, Workflow setup |
| 4 | Done 2026-11-14 (local, not committed) | Migration `config_management`. Programs, device configurations and firmware kept as numbered versions per asset (file upload, checksum, optional change request). Golden baseline per item, drift flag when the newest version differs, e-mail to asset owners on drift and on an overdue backup (daily loop), line-by-line comparison of text files, backup status from an expected interval. Overview tab on the Changes and maintenance page. Direct device connectors and automatic collection are not done |
| 5 | Done 2026-11-14 (local, not committed) | Migration `change_maintenance`. Change requests (draft, submitted, approved or rejected, implemented, closed) linked to assets, with an approver role and separation of duties. Unapproved-change report: asset edits to controlled fields with no approved request covering them, cleared by a reviewer note. Maintenance records (planned then completed, preventive follow-up), spare parts with stock and fitted assets, maintenance cost feeds the cost entries. New Changes and maintenance page and an asset-page card. Maintenance-system integration not done (system not named) |
| Medium review items M1–M8 | Done 2026-11-15 (local, not committed) | Migration `review_medium_fixes`. See 6j |
| Requirement gaps, batch 2 | Done 2026-11-15 (local, not committed) | Migration `lifecycle_gaps_2`. See 6i |
| Requirement gaps, batch 1 | Done 2026-11-14 (local, not committed) | Migration `lifecycle_gaps`. See 6h |
| Review fixes H1–H6 | Done 2026-11-14 (local, not committed) | Migrations `rbac_lifecycle_sections`, `asset_tag_unique`. See 6g |
| 6 | Done 2026-11-14 (local, not committed) | Migration `integrations_reporting`. Signed outbound webhooks (12 events, retries, delivery log, SSRF guard, encrypted secret shown once) and an event worker. External API read routes for expiring dates, changes, due maintenance and configuration status, plus a write route for lifecycle fields. Plant / unit / line dashboard with per-site targets, and an Excel audit pack. New Reports and integrations page. Product-specific CMDB / ITSM / maintenance connectors not done (systems not named) |

## Change of scope (2026-11-16)

- **Change requests and unapproved-change tracking were removed** (requirement 5.4 is no longer in scope): the Change requests, Unapproved changes and Settings tabs, the `changes` RBAC section, the `change.*` webhook events, the `open_changes` and `unapproved_changes` dashboard measures, the audit-pack sheets, `GET /external/v1/changes`, and the rule that a firmware upgrade or patch needs an approved change request. Migration `remove_change_requests` drops the tables and columns. The page is now **Maintenance & configuration** (maintenance, spare parts, configuration). The older sections of this plan that describe change requests are kept as history only.
- **Multi-level approval of purchase requests.** A tenant sets up to 5 ordered approval levels (name, optional role) under Lifecycle > Purchase requests > Approval levels. A request copies the levels when it is submitted and is approved level by level. Each level is decided by a member of its role (any approver if none is set), never by the requester, and never by someone who approved an earlier level. One rejection ends the request. With no levels set, one approver is enough, as before. Migration `purchase_approval_levels`.
- **Purchase order document.** A PO file (PDF, Word, Excel, text or CSV, up to 10 MB) can be attached once a request is approved. Migration `purchase_order_file`.
