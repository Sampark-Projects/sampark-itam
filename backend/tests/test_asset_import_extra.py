"""The asset import file: lifecycle, controller, rack and custom-field columns, and the template file that ships with the app."""
import csv
import io
import uuid
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import Asset, AssetStatus, AssetType, DcimRack, Manufacturer, Site
from app.routers import assets as assets_router
from app.services import asset_import_extra as extra
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)

FULL = {**ADMIN_DEFAULT_PERMISSIONS, "assets": 4}
ORIGINAL_COLUMNS = ["name", "tag", "site_code", "asset_type", "ip_address", "manufacturer", "serial_number", "model", "firmware_version",
                    "description", "business_criticality", "physical_access_ease", "purdue_level", "installation_date"]
TEMPLATE = Path(__file__).resolve().parents[2] / "frontend" / "public" / "template_import_asset.csv"


def client(db, w):
    api = FastAPI()
    api.include_router(assets_router.router)
    api.dependency_overrides[get_db] = lambda: db
    user = w.user(FULL)
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def file_of(rows):
    """A CSV file from a list of dicts (the columns are the keys of all the rows)."""
    columns = []
    for r in rows:
        columns += [k for k in r if k not in columns]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return {"file": ("assets.csv", buf.getvalue().encode("utf-8"), "text/csv")}


def row(w, name, tag, **cols):
    return {"name": name, "tag": tag, "site_code": w.site.code, "asset_type": "PLC", **cols}


def run(c, rows):
    preview = c.post("/assets/import/xlsx/preview", files=file_of(rows)).json()
    confirm = c.post("/assets/import/xlsx/confirm", files=file_of(rows)).json()
    return preview, confirm


def asset_of(db, w, tag):
    found = db.query(Asset).filter(Asset.tenant_id == w.tenant.id, Asset.tag == tag).first()
    if found is not None:
        db.refresh(found)
    return found


def add_type(w, name, fields=None):
    t = AssetType(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, fields_schema=fields or [])
    w.db.add(t)
    w.db.commit()
    return t


# --- lifecycle columns ------------------------------------------------------------------------------

def test_lifecycle_values_are_read_checked_and_saved(db):
    w = World(db)
    c = client(db, w)
    good = row(w, "Press PLC", "L1", safety_relevance="safety_related", plant_owner="Engineering", purchase_date="2023-05-01",
               purchase_cost="1850.50", cost_currency="inr", warranty_expiry_date="2026-05-01", disposal_method="")
    preview, confirm = run(c, [good])
    assert preview["errors"] == [] and confirm["errors"] == [] and confirm["created"] == ["L1"]
    a = asset_of(db, w, "L1")
    assert (a.safety_relevance, a.plant_owner, a.purchase_date, float(a.purchase_cost), a.cost_currency, a.warranty_expiry_date) == (
        "safety_related", "Engineering", date(2023, 5, 1), 1850.5, "INR", date(2026, 5, 1))
    assert a.disposal_method is None


@pytest.mark.parametrize("column,value", [("safety_relevance", "very"), ("purchase_date", "01/05/2023"), ("purchase_cost", "cheap"),
                                          ("purchase_cost", "-5"), ("cost_currency", "RUPEE"), ("disposal_method", "burned")])
def test_a_bad_lifecycle_value_is_an_error_naming_the_column(db, column, value):
    w = World(db)
    c = client(db, w)
    preview, confirm = run(c, [row(w, "Bad", "B1", **{column: value})])
    assert preview["errors"] and column in preview["errors"][0]["error"] and preview["errors"][0]["row"] == 2
    assert confirm["created"] == [] and asset_of(db, w, "B1") is None


def test_a_blank_cell_never_clears_a_stored_value(db):
    w = World(db)
    c = client(db, w)
    run(c, [row(w, "Press PLC", "L1", plant_owner="Engineering", purchase_date="2023-05-01")])
    preview, confirm = run(c, [row(w, "Press PLC", "L1", plant_owner="", purchase_date="", amc_partner="Vendor Ltd")])
    assert confirm["updated"] == ["L1"] and confirm["errors"] == []
    a = asset_of(db, w, "L1")
    assert (a.plant_owner, a.purchase_date, a.amc_partner) == ("Engineering", date(2023, 5, 1), "Vendor Ltd")
    assert preview["to_update"][0]["diff"].get("amc_partner", {}).get("new") == "Vendor Ltd"
    assert "plant_owner" not in preview["to_update"][0]["diff"]


# --- controller -------------------------------------------------------------------------------------

def test_the_controller_is_found_by_tag_or_name_and_must_be_a_plc_or_controller_type(db):
    w = World(db)                                              # World.type is "PLC"
    machine_type, switch_type = add_type(w, "Conventional Machine"), add_type(w, "Switch")
    c = client(db, w)
    run(c, [row(w, "Line PLC", "PLC1"), row(w, "Core Switch", "SW1", asset_type="Switch")])
    plc, switch = asset_of(db, w, "PLC1"), asset_of(db, w, "SW1")
    ok = row(w, "Press", "M1", asset_type="Conventional Machine", controller="plc1")
    by_name = row(w, "Lathe", "M2", asset_type="Conventional Machine", controller="Line PLC")
    preview, confirm = run(c, [ok, by_name])
    assert preview["errors"] == [] and confirm["created"] == ["M1", "M2"]
    assert asset_of(db, w, "M1").controller_asset_id == plc.id and asset_of(db, w, "M2").controller_asset_id == plc.id
    for bad, text in ((switch.tag, "PLC or controller"), ("NOPE", "no asset")):
        preview, confirm = run(c, [row(w, "Drill", "M3", asset_type="Conventional Machine", controller=bad)])
        assert text in preview["errors"][0]["error"] and "controller" in preview["errors"][0]["error"]
        assert asset_of(db, w, "M3") is None


def test_a_controller_named_before_it_is_created_in_the_same_file(db):
    w = World(db)
    machine_type = add_type(w, "Conventional Machine")
    c = client(db, w)
    rows = [row(w, "New PLC", "NP1"), row(w, "New Machine", "NM1", asset_type="Conventional Machine", controller="NP1")]
    preview, confirm = run(c, rows)
    assert preview["errors"] == [] and confirm["errors"] == [] and confirm["created"] == ["NP1", "NM1"]
    assert asset_of(db, w, "NM1").controller_asset_id == asset_of(db, w, "NP1").id
    # the controller after the machine is not known yet
    preview, _ = run(c, [row(w, "M", "NM2", asset_type="Conventional Machine", controller="NP2"), row(w, "P", "NP2")])
    assert preview["errors"] and "no asset" in preview["errors"][0]["error"]


def test_the_controller_must_be_at_the_same_site(db):
    w = World(db)
    other_site = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Second plant", code="SP2")
    db.add(other_site)
    db.commit()
    add_type(w, "Conventional Machine")
    c = client(db, w)
    run(c, [row(w, "Line PLC", "PLC1")])
    preview, _ = run(c, [row(w, "Far machine", "FM1", asset_type="Conventional Machine", site_code="SP2", controller="PLC1")])
    assert preview["errors"] and "same site" in preview["errors"][0]["error"]


# --- rack -------------------------------------------------------------------------------------------

def rack_world(db):
    w = World(db)
    rack = DcimRack(id=uuid.uuid4(), tenant_id=w.tenant.id, name="R1", site_id=w.site.id, u_height=42)
    other_site = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Second plant", code="SP2")
    db.add_all([rack, other_site])
    db.add(DcimRack(id=uuid.uuid4(), tenant_id=w.tenant.id, name="R2", site_id=other_site.id, u_height=42))
    db.commit()
    return w, rack


def test_an_asset_is_placed_in_a_rack_by_the_file(db):
    w, rack = rack_world(db)
    c = client(db, w)
    preview, confirm = run(c, [row(w, "Server 1", "S1", manufacturer="Siemens", model="S7-1500", rack="r1", rack_position="10", rack_face="Front",
                                   airflow="front-to-rear")])
    assert preview["errors"] == [] and confirm["errors"] == [] and confirm["created"] == ["S1"]
    a = asset_of(db, w, "S1")
    assert (a.rack_id, float(a.rack_position), a.rack_face, a.airflow) == (rack.id, 10.0, "front", "front-to-rear")
    assert a.device_type_id is not None
    assert preview["to_create"][0]["extra"]["rack"] == "R1"
    # moving it: the preview shows the change, a blank rack column leaves it where it is
    preview, confirm = run(c, [row(w, "Server 1", "S1", rack="R1", rack_position="20", rack_face="front")])
    assert preview["to_update"][0]["diff"]["rack"]["new"].startswith("R1 / 20")
    assert float(asset_of(db, w, "S1").rack_position) == 20.0
    run(c, [row(w, "Server 1", "S1")])
    assert float(asset_of(db, w, "S1").rack_position) == 20.0


@pytest.mark.parametrize("cols,text", [
    ({"rack": "NOPE", "rack_position": "5", "rack_face": "front"}, "unknown rack"),
    ({"rack": "R2", "rack_position": "5", "rack_face": "front"}, "another site"),
    ({"rack_position": "5", "rack_face": "front"}, "choose a rack"),
    ({"rack": "R1", "rack_position": "5"}, "face"),
    ({"rack": "R1", "rack_position": "50", "rack_face": "front"}, "rack"),
    ({"rack": "R1", "rack_position": "5", "rack_face": "side"}, "front"),
    ({"airflow": "sideways"}, "airflow"),
])
def test_a_bad_rack_cell_is_an_error(db, cols, text):
    w, rack = rack_world(db)
    c = client(db, w)
    preview, confirm = run(c, [row(w, "Server 1", "S1", **cols)])
    assert preview["errors"] and text in preview["errors"][0]["error"].lower()
    assert confirm["created"] == [] and asset_of(db, w, "S1") is None


def test_two_devices_cannot_take_the_same_unit(db):
    w, rack = rack_world(db)
    c = client(db, w)
    run(c, [row(w, "Server 1", "S1", rack="R1", rack_position="10", rack_face="front")])
    preview, confirm = run(c, [row(w, "Server 2", "S2", rack="R1", rack_position="10", rack_face="front")])
    assert preview["errors"] and confirm["created"] == [] and asset_of(db, w, "S2") is None


def test_a_site_change_is_refused_while_the_asset_is_in_a_rack(db):
    w, rack = rack_world(db)
    c = client(db, w)
    run(c, [row(w, "Server 1", "S1", rack="R1", rack_position="10", rack_face="front")])
    preview, confirm = run(c, [row(w, "Server 1", "S1", site_code="SP2")])
    assert preview["errors"] and "rack" in preview["errors"][0]["error"]
    assert confirm["updated"] == [] and asset_of(db, w, "S1").site_id == w.site.id


# --- custom fields ----------------------------------------------------------------------------------

def machine_type(w):
    return add_type(w, "Conventional Machine", [
        {"key": "voltage", "label": "Voltage (V)", "type": "number", "required": False, "options": []},
        {"key": "phase", "label": "Phase", "type": "select", "required": False, "options": ["Single", "Three"]},
        {"key": "ce_marked", "label": "CE marked", "type": "boolean", "required": False, "options": []},
        {"key": "plan_url", "label": "Plan", "type": "url", "required": False, "options": []},
        {"key": "note", "label": "Note", "type": "text", "required": False, "options": []}])


def test_custom_field_columns_are_checked_by_the_type_of_the_field(db):
    w = World(db)
    machine_type(w)
    c = client(db, w)
    good = row(w, "Press", "M1", asset_type="Conventional Machine", cf_voltage="415", cf_phase="three", cf_ce_marked="yes",
               cf_plan_url=" https://plans.example.com/m1.pdf ", cf_note="old press")
    preview, confirm = run(c, [good])
    assert preview["errors"] == [] and confirm["created"] == ["M1"]
    assert asset_of(db, w, "M1").custom_fields == {"voltage": 415, "phase": "Three", "ce_marked": True,
                                                   "plan_url": "https://plans.example.com/m1.pdf", "note": "old press"}
    # a change keeps the other values
    run(c, [row(w, "Press", "M1", asset_type="Conventional Machine", cf_voltage="400", cf_note="")])
    assert asset_of(db, w, "M1").custom_fields["voltage"] == 400 and asset_of(db, w, "M1").custom_fields["note"] == "old press"


@pytest.mark.parametrize("column,value,text", [("cf_voltage", "high", "number"), ("cf_phase", "Four", "one of"), ("cf_ce_marked", "maybe", "yes or no"),
                                               ("cf_plan_url", "plans.example.com", "web link"), ("cf_colour", "red", "no custom field")])
def test_a_bad_custom_field_cell_is_an_error(db, column, value, text):
    w = World(db)
    machine_type(w)
    c = client(db, w)
    preview, confirm = run(c, [row(w, "Press", "M1", asset_type="Conventional Machine", **{column: value})])
    assert preview["errors"] and text in preview["errors"][0]["error"].lower()
    assert confirm["created"] == [] and asset_of(db, w, "M1") is None


# --- archived assets and the cell reader ------------------------------------------------------------

def test_an_archived_asset_is_not_updated_by_the_file(db):
    from datetime import datetime
    w = World(db)
    c = client(db, w)
    run(c, [row(w, "Old PLC", "A1")])
    a = asset_of(db, w, "A1")
    a.archived_at = datetime.utcnow()
    db.commit()
    preview, confirm = run(c, [row(w, "Renamed", "A1")])
    assert preview["errors"] and "archived" in preview["errors"][0]["error"]
    assert confirm["updated"] == [] and asset_of(db, w, "A1").name == "Old PLC"


@pytest.mark.parametrize("value,text", [("  x  ", "x"), ("", None), (None, None), (float("nan"), None), (12.0, "12"), (12.5, "12.5"),
                                        ("NULL", None), ("[NULL]", None), (date(2024, 1, 2), "2024-01-02")])
def test_cell_reader(value, text):
    assert extra.cell({"a": value}, "a") == text
    assert extra.cell({}, "a") is None


# --- the template file --------------------------------------------------------------------------------

def test_the_template_has_every_import_column():
    if not TEMPLATE.exists():
        pytest.skip("the frontend folder is not part of this environment")
    with TEMPLATE.open(newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    expected = ORIGINAL_COLUMNS + extra.DCIM_COLUMNS + extra.LIFECYCLE_COLUMNS
    assert header[:len(expected)] == expected
    assert all(h.startswith(extra.CUSTOM_PREFIX) for h in header[len(expected):]) and len(header) > len(expected)


def test_the_template_is_processed_on_upload(db):
    if not TEMPLATE.exists():
        pytest.skip("the frontend folder is not part of this environment")
    w = World(db)
    sites = {}
    for code in ("MPP", "RDC", "DW"):
        sites[code] = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name=f"Site {code}", code=code)
        db.add(sites[code])
    db.commit()
    with TEMPLATE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for name in sorted({r["asset_type"] for r in rows} - {"PLC"}):
        fields = [{"key": k.replace("cf_", ""), "label": k, "type": "url" if k.endswith("_url") else "number", "required": False, "options": []}
                  for k in rows[0] if k.startswith("cf_")] if name == "Conventional Machine" else []
        add_type(w, name, fields)
    c = client(db, w)
    raw = TEMPLATE.read_bytes()
    preview = c.post("/assets/import/xlsx/preview", files={"file": ("template.csv", raw, "text/csv")}).json()
    assert preview["errors"] == [] and len(preview["to_create"]) == len(rows)
    confirm = c.post("/assets/import/xlsx/confirm", files={"file": ("template.csv", raw, "text/csv")}).json()
    assert confirm["errors"] == [] and len(confirm["created"]) == len(rows)
    machine = asset_of(db, w, "MCH001")
    plc = asset_of(db, w, "PLC001")
    assert machine.controller_asset_id == plc.id and machine.custom_fields["voltage"] == 415
    assert machine.custom_fields["electrical_schematic_url"].startswith("https://")
    assert (plc.safety_relevance, plc.cost_currency, plc.purchase_date) == ("safety_related", "INR", date(2022, 11, 1))
    # the same file again changes nothing and fails nowhere
    again = c.post("/assets/import/xlsx/confirm", files={"file": ("template.csv", raw, "text/csv")}).json()
    assert again["errors"] == [] and again["created"] == []


# --- an Excel file: numbers and dates arrive as numbers and dates ---------------------------------------

def test_an_excel_file_with_numbers_and_dates(db):
    import openpyxl
    w, rack = rack_world(db)
    machine_type(w)
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["name", "tag", "site_code", "asset_type", "rack", "rack_position", "rack_face", "purchase_date", "purchase_cost", "cf_voltage"])
    sheet.append(["Excel PLC", "X1", w.site.code, "PLC", "R1", 12, "rear", date(2024, 3, 9), 1200.5, None])
    sheet.append(["Excel Machine", "X2", w.site.code, "Conventional Machine", None, None, None, None, None, 400])
    buf = io.BytesIO()
    book.save(buf)
    files = {"file": ("assets.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    c = client(db, w)
    preview = c.post("/assets/import/xlsx/preview", files=files).json()
    confirm = c.post("/assets/import/xlsx/confirm", files=files).json()
    assert preview.get("errors") == [] and confirm["errors"] == [] and confirm["created"] == ["X1", "X2"]
    a = asset_of(db, w, "X1")
    assert (a.rack_id, float(a.rack_position), a.rack_face, a.purchase_date, float(a.purchase_cost)) == (rack.id, 12.0, "rear", date(2024, 3, 9), 1200.5)
    assert asset_of(db, w, "X2").custom_fields == {"voltage": 400}
