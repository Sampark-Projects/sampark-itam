# Lifecycle module: how it works and a client demo script

For the VECV OT asset-management requirement (see `OT_REQUIREMENTS_GAP_PLAN.md` for the full build log).
Screen names below are the English ones. Demo dates assume today is mid-November 2026.

## 1. The idea in one minute

An asset moves through five stages. Sampark covers each one and keeps a full audit trail.

| Stage | What the client sees | Where |
|---|---|---|
| 1. Plan and procure | A purchase request with lines, approved by a different person, then ordered with the ERP PO number | Lifecycle → Purchase requests |
| 2. Receive and onboard | The delivery is booked against the order, checked (model, quantity), a tag is generated, then commissioning and acceptance sign-off | Asset page → Lifecycle workflow; Lifecycle → My tasks / Workflows |
| 3. Operate and maintain | Expiry alerts, maintenance plans, software and spares, versioned configurations with a golden baseline | Lifecycle, Maintenance & configuration, asset page |
| 4. Plan replacement | Vendor end-of-life table matched to assets, obsolescence report, cost of ownership | Lifecycle → Expiring, Obsolescence, Vendor, Cost |
| 5. Retire | Decommission approval, data-wipe confirmation, disposal evidence, then the record is archived | Asset page → Start retirement |

Reports (plant dashboard, audit pack, webhooks) sit on top of all of this.

## 2. Building blocks you should understand before demoing

- **Workflow.** Each tenant has one Onboarding and one Retirement workflow: an ordered list of steps. A step is a task or an approval, can belong to a role, and can demand evidence before it can be completed (asset fields, an uploaded document of a given category, a comment, a confirmation). A step can also set the asset status. Edit them in **Lifecycle → Workflow setup**; changes apply only to runs started afterwards.
- **Run.** One workflow in progress on one asset (only one open run per asset). Every step records who did it and when.
- **Separation of duties.** The person who started a run cannot approve its approval steps, and the requester of a purchase request cannot approve it. A purchase request can have several approval levels (Lifecycle → Purchase requests → Approval levels), each decided by a different person. Plan for **two users**, or more if you set up levels, in the demo.
- **Status lock.** While a run is in progress, and for the statuses the retirement workflow sets (Retired), the asset status cannot be edited by hand. Retired assets are archived (read-only) until someone with lifecycle level 3 reopens them with a reason.
- **Alerts.** A daily job e-mails the asset owner and point-of-contact users at the configured steps (default 90 / 30 / 7 days) before warranty, AMC or support dates, and when a configuration drifts or maintenance is overdue. E-mails need the mail setup to be working.
- **Vendor end-of-life table.** Entries per manufacturer and model (`*` and `?` wildcards, most specific wins), loaded by CSV. Obsolescence is end of support, else end of life.
- **Permissions.** Sections `lifecycle`, `maintenance`, `configurations`, `reports`: level 1 reads, 2 writes, 3 deletes and changes settings. Webhooks use `api_keys`.

## 3. Before the demo

1. Open http://localhost:5174 and sign in as an administrator. Have a **second person** ready: the seeded **Editor** user works well as the requester or starter (it can request and start, but cannot approve), while the administrator approves. Use another browser profile or a private window for the second sign-in.
2. In **Lifecycle → Workflow setup**, leave the defaults. Optionally give the approval steps a role so you can show role checks.
3. **Lifecycle → Vendor**: import `docs/demo/vendor_lifecycle_demo.csv` (three rows: obsolete, soon, later).
4. Create **demo assets** (do not demo on the copied production data):
   - **DEMO-PLC-01**: type PLC, manufacturer Siemens, model "SIMATIC S7-300 CPU 315", status Planned, with a **warranty expiry** about 20 days away, support expiry about 6 months away, criticality high, safety relevance safety-related. Add a contact (as owner or point of contact) whose e-mail matches a Sampark user, otherwise the expiry alert reports "no recipients" and sends nothing.
   - **DEMO-PLC-02**: manufacturer Rockwell Automation, model "ControlLogix 1756-L71", site as a unit under a plant.
   - **DEMO-SPARE-01**: a spare CPU of the same model, status In stock.
   - **DEMO-OLD-01**: any asset you will retire at the end.
5. Optional: in **Asset Types → naming rules**, add a rule for the PLC type (for example `PLC-{SEQ:4}`) so the onboarding start shows a generated tag. Without a rule the tag stays empty.
6. Make sure at least one site has a unit site under it (Sites → parent) so the hierarchy shows.
7. Check the numbers on **Reports → Plant dashboard** so you know the starting point.

## 4. Demo script (about 40 minutes)

Each step: what to do, what to say, what to expect.

**A. Plan and procure (5 min).** *Lifecycle → Purchase requests → New.*
- Enter demand, specification, one line (type PLC, manufacturer Siemens, model S7-300 CPU 315, quantity 1, unit cost). Submit.
- Say: "The requester cannot approve their own request." Show the Approve button is absent. Switch to the second user and approve. The requester gets an e-mail.
- Mark it **Ordered** and enter a PO number. Try the same PO number on another request: it is refused (unique per tenant).

**B. Receive and onboard (8 min).** *Asset page → Lifecycle workflow → Start onboarding.*
- **Receive first:** on the order line, book DEMO-PLC-01 against the order. Try DEMO-PLC-02 first (different manufacturer and model): it is refused until accepted with a reason. Booking the right asset fills PO, requisition, cost, vendor and received date. Show the order link on the asset.
- Start onboarding on DEMO-PLC-01 **as the Editor**. If a naming rule exists, the tag is generated.
- Step 1 "Receive and verify" is blocked, and the Current step card says what is missing: the **serial number** (the PO and received date are already filled by the booking). Fill it and complete the step.
- Step 2 "Install and commission" needs four things on the asset: a **commissioning date**, a **location**, **network settings** (an interface with an IP or MAC) and a **golden baseline** (see section E; do E1 before this step).
- Step 3 "Acceptance sign-off" is an approval. The Editor, who started the run, is refused (self-approval). Before the administrator can approve, the asset needs an **acceptance date** and **acceptance signed by**; fill those on the asset first. Status becomes Active.
- Show **Lifecycle → My tasks** (what is waiting for you) and **Workflows** (all runs).

**C. Operate: alerts and dates (4 min).** *Lifecycle → Expiring.*
- The warranty expiry 20 days away appears. Explain the alert steps (**Lifecycle → Alerts** tab), that each step is sent once, and that owner and contact users are e-mailed.
- Press the run-alerts button if you want to show the e-mail, if mail is configured.

**D. Software, spares, components (3 min).** *Asset page.*
- Software card: add an operating system with a licence expiry.
- Spares: link DEMO-SPARE-01 as a spare for DEMO-PLC-01; show it on both pages.
- "Component of": make a module a child of DEMO-PLC-01 and show the Components card.

**E. Configuration management (6 min).** *(Do the upload and baseline, E1, before commissioning in B.)* *Asset page → configuration card, or Changes & Maintenance → Configuration.*
- Add a configuration item "Main program", upload version 1 (any text file), set it as the **golden baseline**. Say that the file is encrypted at rest and its checksum is re-verified on every download.
- Upload version 2 with a small edit. The state changes to **Differs from baseline**; open the comparison to show the line diff. Say that a drift e-mail goes to the owner.
- Show the backup state (a backup interval makes it overdue if no new version arrives).

**F. Multi-level purchase approval (4 min).** *Lifecycle → Purchase requests → Approval levels.* (Change requests and unapproved-change tracking were removed from the product.)
- Set two levels, for example "Manager" (role reviewer) and "Plant head" (role admin). Raise a request as the requester and submit it.
- Open it: the Approval list shows level 1 waiting. The wrong role has no Approve button; the right one approves with a note and the request stays submitted with level 2 waiting.
- The same person cannot approve level 2. The second approver approves and the request becomes approved; show a rejection at level 2 ending another request.

**G. Maintenance (3 min).** *Changes & Maintenance → Maintenance.*
- Add a maintenance plan (every 90 days). The first task appears within 14 days of the due date. Complete a task with a cost: the cost appears under the asset's cost of ownership. An upgrade task can only be completed under an approved change request.

**H. End of life and cost (3 min).** *Lifecycle → Obsolescence, Vendor, Cost.*
- Show the vendor table, then the obsolescence report by year, site and criticality: DEMO-PLC-01 is obsolete, DEMO-PLC-02 is "soon". Show the cost summary per currency.
- Mention that the asset's risk score now reflects end of support.

**I. Retirement (4 min).** *DEMO-OLD-01 → Start retirement.*
- Decommission approval (a different person from the starter; an approval needs a **comment**), data-wipe confirmation (comment and the confirm tick-box), disposal evidence (disposal method, disposal date and an uploaded document of category "Disposal or return evidence"; use a real PDF, DOC, DOCX, XLS, XLSX, CSV or TXT file, a fake file is rejected), then archive (a comment).
- The asset becomes Retired and archived: try editing it and show it is refused. Lifecycle level 3 can reopen it with a reason.

**J. Reports (4 min).** *Reports.*
- Plant dashboard: group by Site or Area, targets (met / missed), trend cards (the sparkline needs at least two days of history; today's value always matches the dashboard).
- Audit pack: download the workbook and show the sheets (Summary, Assets, Vendor end of life, Maintenance, Configuration, Workflows, Software, Purchase requests).
- Webhooks: add an endpoint (use a test receiver), trigger an event, show the signed delivery and the retry/redeliver behaviour.
- Audit trail: open **Audit logs** and show every step above is recorded with user and before/after values.

## 5. Rehearsal results (2026-11-16)

Ran every part end to end on the local copy (API for the multi-user steps, browser for the screens): purchase request with self-approval refused and PO number required, receive against the order (mismatch refused), onboarding with every blocker and the self-approval rule, configuration baseline and drift, change request with quorum, review-to-close, emergency late approval and unapproved flag, maintenance plan with a completed task and its cost, vendor match, obsolescence and cost screens, retirement with the status lock and archive, dashboard, trend and audit pack. All behaved as described above. Things found and fixed during the rehearsal: the trend's "today" value could be stale; the guide now has the exact field names and prerequisites.

Not rehearsed: e-mail delivery (no mail setup), webhook delivery to a live receiver, the Escape key in the webhook form.

## 6. Known limits to be upfront about

- No product-specific CMDB, ITSM or maintenance-system connector yet (the systems are not named). The generic external API and webhooks are there.
- Configurations are uploaded by hand; there is no direct collection from devices, and binary PLC programs are compared by checksum only.
- The vendor end-of-life table is loaded by CSV; there is no automatic feed.
- XLSX import does not go through the tag naming check.
- Trend charts need several days of snapshots to be meaningful.
- Alert and approval e-mails need working mail setup.
- All of this runs on the local `assets_lifecycle` schema and is not yet committed or deployed.

## 7. Dry run checklist

- [ ] Two users can sign in at the same time
- [ ] Vendor CSV imported, DEMO assets created
- [ ] Mail setup works (or skip e-mail claims)
- [ ] Run through sections A to J once on your own, ideally the day before
- [ ] After the demo, delete the DEMO assets so they do not mix with real data
