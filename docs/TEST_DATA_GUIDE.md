# Test data in the Sampark tenant (assets_lifecycle schema)

Created on 2026-11-16 in the **Sampark Empty Tenant**, schema `assets_lifecycle` only (the production `assets` schema is untouched). Everything is labelled **TEST** so it is easy to spot. `docs/demo/test_data_manifest.json` lists every created record id and the original values of the real asset fields that were edited, so all of it can be removed or reverted later.

## Users

| User | Role | Use it as |
|---|---|---|
| testuser01@gmail.com (`Test@123`) | editor (lifecycle 2) | requester / workflow starter. Cannot approve |
| dummyuser01@gmail.com (`Test@123`) | reviewer (lifecycle 3) | approver |
| manvendra.s@samparksoftwares.com | admin | your own account |

In this tenant the **onboarding** steps are assigned to the **admin** role, so the editor cannot act on them. The reviewer can (lifecycle level 3 acts as an override, recorded on the step). The retirement steps have no role, so the editor can act on them.

## What exists, and what to test with it

**Real assets that were given lifecycle data** (their original values are in the manifest):

| Asset | Type / model | What was set | Test |
|---|---|---|---|
| COUNTER SHAFT PRESS | PLC S7-1500 | serial, firmware V2.9.2, warranty +20d, support +180d, AMC +45d, 2 software items, config file (v1 baseline, v2 differs), maintenance plan (quarterly), costs, spare parts | Lifecycle → Expiring; asset page cards; configuration drift; maintenance |
| HD LINE MAIN PANEL PLC | PLC CPU 1515-2 PN | warranty +75d, HMI project config (matches baseline), spare CPU linked | Spares on both assets; baseline "matches" |
| ACE DESIGNER HARD TURNING 02 | FANUC CNC | warranty expired, AMC expired, config with no baseline, overdue corrective task, completed inspection with cost and a part used | Overdue maintenance, expired support, parts stock |
| CLUTCH HSG OIL SEAL PRESS / TILTER 1&2 | HMI TP700 | licence +25d, support +200d, runtime software | Licence expiry |
| CLEAVELAND HOBBING MACHINE-666 | SIEMENS SMART 200 | warranty and support already expired, firmware edited | Obsolescence "obsolete"; unapproved-change flag |

**New TEST assets:** TEST-NEW-PLC-01 (onboarding in progress), TEST-NEW-HMI-01 (spare for a purchase flow), TEST-SPARE-CPU-01 (a spare linked to HD LINE MAIN PANEL PLC), TEST-RETIRE-01 (retirement waiting for approval), TEST-RETIRE-02 (retired and archived).

**Vendor end-of-life table:** 5 entries marked "TEST data (illustrative)". The dates are made up. They match many real assets (for example 85 TP700 panels and 35 SMART 200 PLCs), so the obsolescence report now shows real-looking numbers that are not vendor facts.

## Scenarios, with who does what

1. **Purchase requests (Lifecycle → Purchase requests).** PR-0001 draft, PR-0002 submitted (waiting for the reviewer: approve it, or reject with a reason), PR-0003 rejected, PR-0004 ordered with PO TEST-PO-0002 and not yet received (book TEST-NEW-HMI-01 against it, and try a mismatching asset first), PR-0005 ordered and received for TEST-NEW-PLC-01. Sign in as the editor and check there is no Approve button on your own request.
2. **Workflows (Lifecycle → My tasks).** The reviewer has two tasks: acceptance sign-off for TEST-NEW-PLC-01 (fill acceptance date and signed-by on the asset first, otherwise it is blocked) and decommission approval for TEST-RETIRE-01 (needs a comment). The editor started both, so the editor is refused if they try to approve. Continue TEST-RETIRE-01 as the editor after approval (wipe, disposal evidence with a real PDF, archive). TEST-RETIRE-02 shows an archived asset; the reviewer can reopen it with a reason.
3. **Change requests and unapproved-change tracking were removed.** The CR-0002 to CR-0006 test records and their flags were deleted with the tables. The FANUC firmware-upgrade task now completes without a change request.
4. **Multi-level purchase approval.** Lifecycle > Purchase requests > Approval levels (needs lifecycle level 3). Set levels such as Manager (role reviewer) and Plant head (role admin), then submit a request as the editor and approve level by level with different users.
5. **Configuration (asset page, Maintenance & configuration → Configuration).** Differs from baseline (COUNTER SHAFT PRESS), matches baseline (HD LINE MAIN PANEL PLC), no baseline (FANUC). Upload a new version, compare two versions, set a new baseline.
6. **Maintenance and spares.** Maintenance tab: overdue FANUC task, upcoming quarterly task, the upgrade task. Spare parts tab: "TEST backup battery" is below its minimum stock.
7. **Reports.** Dashboard by site and by area (obsolete, expired support, baseline coverage, drift, overdue maintenance, workflows in progress). The trend shows only today until snapshots build up over several days. Audit pack download.

## Not set up

- **Dashboard targets:** the reviewer has Reports level 2, and setting targets needs level 3. Set them with your admin account (Reports → Targets).
- **E-mails:** this tenant has no contacts, so alert e-mails to asset owners report "no recipients". Approver e-mails depend on your mail setup.
- **Webhooks and tag naming rules:** not created, because they affect real integrations or real asset numbering. Add them when you want to test them.

## Notes

- The data sits in the same tenant as your real assets, so the dashboard counts (1,369 assets, 35 obsolete, and so on) include the TEST records.
- Nothing here has been committed. Say the word and I'll remove all of it and put the five real assets back to their original values using the manifest.
