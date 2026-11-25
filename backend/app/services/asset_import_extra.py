"""The columns of the asset import file that come after the first fourteen: OT lifecycle data, the controller, the place in a
rack and the custom fields of the asset type.

The preview and the confirm step of the import both go through `parse_row`, so a row that the preview accepts is read the same way
when it is written. A blank cell never clears a value that is already stored: it only means "not given".

Columns
  lifecycle     safety_relevance, plant_owner, amc_partner, requisition_number, purchase_order_number, purchase_date, purchase_cost,
                cost_currency, expected_delivery_date, received_date, commissioned_date, acceptance_date, acceptance_signed_by,
                warranty_expiry_date, amc_expiry_date, support_expiry_date, licence_expiry_date, disposal_method, disposal_date,
                disposal_reference (the same names and rules as the asset form and the asset export)
  DCIM          controller (asset tag, or name at the same site, of a PLC or controller), rack (name, at the site of the asset),
                rack_position, rack_face, airflow
  custom        cf_<key> for a field of the asset type, for example cf_voltage (a "url" field must be a web link)
MAC addresses, ports and cables have their own DCIM files."""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.errors.exceptions import ErrorCodeException
from app.models import Asset, DcimDeviceType, DcimRack
from app.schemas.asset import AssetLifecycleFields
from app.services import dcim_logic as dl
from app.services import dcim_service as ds

LIFECYCLE_COLUMNS = [
    "safety_relevance", "plant_owner", "amc_partner", "requisition_number", "purchase_order_number", "purchase_date", "purchase_cost",
    "cost_currency", "expected_delivery_date", "received_date", "commissioned_date", "acceptance_date", "acceptance_signed_by",
    "warranty_expiry_date", "amc_expiry_date", "support_expiry_date", "licence_expiry_date",
    "disposal_method", "disposal_date", "disposal_reference",
]
DCIM_COLUMNS = ["controller", "rack", "rack_position", "rack_face", "airflow"]
CUSTOM_PREFIX = "cf_"
_TRUE = {"true", "yes", "y", "1", "si", "sì"}
_FALSE = {"false", "no", "n", "0"}


@dataclass
class Extra:
    """What the extra columns of one row say. `errors` is empty when the row can be used."""
    errors: List[str] = field(default_factory=list)
    lifecycle: Dict = field(default_factory=dict)        # attribute -> value
    custom_fields: Dict = field(default_factory=dict)    # key -> value
    controller: Optional[Asset] = None                   # found in the database
    controller_pending: Optional[str] = None             # a controller that an earlier row of the same file creates
    rack: Optional[DcimRack] = None
    position: Optional[Decimal] = None
    face: Optional[str] = None
    airflow: Optional[str] = None
    shown: Dict = field(default_factory=dict)            # column -> text, for the preview

    @property
    def has_rack(self) -> bool:
        return self.rack is not None


def cell(row, key: str) -> Optional[str]:
    """The text of a cell: trimmed, None when the column is missing or blank. A spreadsheet date or a whole number comes as text."""
    try:
        value = row.get(key)
    except AttributeError:
        value = None
    if value is None:
        return None
    try:
        if pd.isna(value):  # NaN, and the empty date of a spreadsheet (NaT)
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        return str(int(value)) if value == int(value) else str(value)
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value).strip()
    if text.lower() in ("", "nan", "nat", "none", "[null]", "null"):
        return None
    return text


def _lifecycle(row, extra: Extra) -> None:
    given = {key: cell(row, key) for key in LIFECYCLE_COLUMNS if cell(row, key) is not None}
    if not given:
        return
    try:
        values = AssetLifecycleFields(**given).model_dump(exclude_unset=True)
    except ValidationError as exc:
        for err in exc.errors():
            name = str(err["loc"][0]) if err.get("loc") else "value"
            extra.errors.append(f"{name}: {err.get('msg', 'invalid value')}")
        return
    extra.lifecycle = {k: v for k, v in values.items() if k in given}
    extra.shown.update({k: given[k] for k in extra.lifecycle})


def _custom_fields(db: Session, row, asset_type_id, extra: Extra) -> None:
    from app.crud.assets import clean_url_value
    from app.models.asset_type import AssetType
    columns = [c for c in getattr(row, "index", []) if isinstance(c, str) and c.lower().startswith(CUSTOM_PREFIX)]
    given = {c: cell(row, c) for c in columns if cell(row, c) is not None}
    if not given:
        return
    schema = (db.query(AssetType.fields_schema).filter(AssetType.id == asset_type_id).scalar() or []) if asset_type_id else []
    defs = {f.get("key"): f for f in schema if isinstance(f, dict) and f.get("key")}
    for column, text in given.items():
        key = column[len(CUSTOM_PREFIX):].lower()
        definition = defs.get(key)
        if definition is None:
            extra.errors.append(f"{column}: the asset type has no custom field '{key}'")
            continue
        label, kind = definition.get("label") or key, definition.get("type", "text")
        try:
            if kind == "number":
                try:
                    value = float(text.replace(",", "."))
                except ValueError:
                    raise ValueError("must be a number")
                value = int(value) if value == int(value) else value
            elif kind == "boolean":
                if text.lower() in _TRUE:
                    value = True
                elif text.lower() in _FALSE:
                    value = False
                else:
                    raise ValueError("must be yes or no")
            elif kind == "date":
                try:
                    value = date.fromisoformat(text[:10]).isoformat()
                except ValueError:
                    raise ValueError("must be a date as YYYY-MM-DD")
            elif kind == "select":
                options = {str(o).lower(): o for o in definition.get("options") or []}
                if text.lower() not in options:
                    raise ValueError("must be one of: " + ", ".join(options.values()))
                value = options[text.lower()]
            elif kind == "url":
                value = clean_url_value(text)
            else:
                value = text
        except ValueError as exc:
            extra.errors.append(f"{label} ({column}): {exc}")
            continue
        if value is not None:
            extra.custom_fields[key] = value
            extra.shown[column] = str(value)


def find_controller(db: Session, tenant_id, site_id, text: str) -> Optional[Asset]:
    """The live asset that a controller cell names: its tag, or else its name (a site narrows several matches)."""
    low = text.strip().lower()
    base = db.query(Asset).filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None))
    found = base.filter(func.lower(Asset.tag) == low).all()
    if not found:
        found = base.filter(func.lower(Asset.name) == low).all()
        if len(found) > 1 and site_id is not None:
            found = [a for a in found if a.site_id == site_id]
    if len(found) > 1:
        raise ValueError(f"'{text}' matches {len(found)} assets; use the asset tag")
    return found[0] if found else None


def _controller(db: Session, tenant_id, site_id, row, asset: Optional[Asset], pending: Dict[str, str], extra: Extra) -> None:
    from app.crud import assets as crud_assets
    text = cell(row, "controller")
    if text is None:
        # a machine that moves to another site must not keep a controller of the old site
        if asset is not None and asset.controller_asset_id and site_id is not None and asset.site_id != site_id:
            try:
                crud_assets.validate_controller_asset(db, tenant_id, asset.controller_asset_id, site_id, asset_id=asset.id)
            except ErrorCodeException:
                extra.errors.append("controller: the asset moves to another site than its controller; fill the controller column or change the controller first")
        return
    try:
        controller = find_controller(db, tenant_id, site_id, text)
    except ValueError as exc:
        extra.errors.append(f"controller: {exc}")
        return
    if controller is None:
        pending_type = pending.get(text.lower())
        if pending_type is not None and crud_assets.is_controller_type_name(pending_type):
            extra.controller_pending = text
            extra.shown["controller"] = f"{text} (created earlier in this file)"
            return
        extra.errors.append(f"controller: no asset with the tag or name '{text}'")
        return
    try:
        crud_assets.validate_controller_asset(db, tenant_id, controller.id, site_id, asset_id=asset.id if asset is not None else None)
    except ErrorCodeException:
        extra.errors.append(f"controller: '{text}' must be another asset of a PLC or controller type at the same site")
        return
    extra.controller = controller
    extra.shown["controller"] = controller.name


def _rack(db: Session, tenant_id, site_id, row, asset: Optional[Asset], extra: Extra) -> None:
    rack_name, position, face, airflow = cell(row, "rack"), cell(row, "rack_position"), cell(row, "rack_face"), cell(row, "airflow")
    try:
        extra.airflow = dl._choice(airflow, "Airflow", dl.AIRFLOWS)
    except dl.DcimInputError as exc:
        extra.errors.append(f"airflow: {exc}")
    if extra.airflow:
        extra.shown["airflow"] = extra.airflow
    if rack_name is None:
        if position is not None or face is not None:
            extra.errors.append("rack: choose a rack for the position and face")
        elif asset is not None and asset.rack_id and site_id is not None and asset.site_id != site_id:
            extra.errors.append("rack: the asset is in a rack; remove it from the rack before moving it to another site")
        return
    rack = (db.query(DcimRack).filter(DcimRack.tenant_id == tenant_id, DcimRack.site_id == site_id, func.lower(DcimRack.name) == rack_name.lower()).first()
            if site_id is not None else None)
    if rack is None:
        elsewhere = db.query(DcimRack.id).filter(DcimRack.tenant_id == tenant_id, func.lower(DcimRack.name) == rack_name.lower()).first()
        extra.errors.append(f"rack: the rack '{rack_name}' is at another site than the asset" if elsewhere else f"rack: unknown rack '{rack_name}'")
        return
    try:
        place = dl.clean_placement(rack.id, position, face)
    except dl.DcimInputError as exc:
        extra.errors.append(f"rack: {exc}")
        return
    extra.rack, extra.position, extra.face = rack, place["rack_position"], place["rack_face"]
    extra.shown["rack"] = rack.name
    if extra.position is not None:
        extra.shown["rack_position"] = f"{extra.position} {extra.face}"


def check_placement(db: Session, tenant_id, asset: Optional[Asset], location_id, name: str, dtype: Optional[DcimDeviceType], extra: Extra) -> None:
    """The place in the rack must suit the device type and be free (raises ValueError with the reason)."""
    if not extra.has_rack:
        return
    rack, has_position = extra.rack, extra.position is not None
    try:
        dl.check_placement_rules(location_id, rack.location_id, dtype.u_height if dtype else None, has_position)
        if has_position:
            ds.check_placement(db, tenant_id, rack, asset.id if asset is not None else None, extra.position, extra.face,
                               dl.height_of(dtype.u_height if dtype else None), True if dtype is None else bool(dtype.is_full_depth), name)
    except dl.DcimInputError as exc:
        raise ValueError(str(exc))
    except ErrorCodeException as exc:
        raise ValueError(str(exc.detail))


def parse_row(db: Session, tenant_id, row, *, site_id, asset_type_id, asset: Optional[Asset], manufacturer_id, model: Optional[str],
              location_id=None, name: str = "", pending: Optional[Dict[str, str]] = None) -> Extra:
    """Read and check the extra columns of one row. `asset` is the existing asset of the row (None for a new one); `pending` maps the
    tags of the rows read earlier in the same file to their asset type, so that a controller in the file can be named before it exists."""
    extra = Extra()
    if asset is not None:
        from app.crud import assets as crud_assets
        try:
            crud_assets.ensure_not_archived(asset)
        except ErrorCodeException:
            extra.errors.append("the asset is retired and archived; it can no longer be changed")
            return extra
    _lifecycle(row, extra)
    _custom_fields(db, row, asset_type_id, extra)
    _controller(db, tenant_id, site_id, row, asset, pending or {}, extra)
    _rack(db, tenant_id, site_id, row, asset, extra)
    if extra.has_rack and not extra.errors:
        dtype = ds.find_device_type(db, tenant_id, manufacturer_id, model) if (manufacturer_id and isinstance(model, str) and model.strip()) else (
            db.query(DcimDeviceType).filter(DcimDeviceType.id == asset.device_type_id).first() if asset is not None and asset.device_type_id else None)
        try:
            check_placement(db, tenant_id, asset, asset.location_id if asset is not None else location_id,
                            (asset.name if asset is not None else name) or name, dtype, extra)
        except ValueError as exc:
            extra.errors.append(f"rack: {exc}")
    return extra


def apply_fields(asset: Asset, extra: Extra) -> None:
    """Set the lifecycle values, the custom fields and the controller of the row (nothing is committed here)."""
    for key, value in extra.lifecycle.items():
        setattr(asset, key, value)
    if extra.custom_fields:
        merged = dict(asset.custom_fields or {})
        merged.update(extra.custom_fields)
        asset.custom_fields = merged
    if extra.controller is not None:
        asset.controller_asset_id = extra.controller.id


def apply_controller_pending(db: Session, tenant_id, asset: Asset, extra: Extra, pending_text: Optional[str]) -> None:
    """A controller named in the file is looked up again when the row is written: the row that creates it has been committed by then."""
    from app.crud import assets as crud_assets
    if not pending_text:
        return
    controller = find_controller(db, tenant_id, asset.site_id, pending_text)
    if controller is None:
        raise ValueError(f"controller: no asset with the tag or name '{pending_text}'")
    try:
        crud_assets.validate_controller_asset(db, tenant_id, controller.id, asset.site_id, asset_id=asset.id)
    except ErrorCodeException:
        raise ValueError(f"controller: '{pending_text}' must be another asset of a PLC or controller type at the same site")
    asset.controller_asset_id = controller.id


def apply_placement(db: Session, tenant_id, asset: Asset, extra: Extra) -> None:
    """Put the asset in its rack place (after its device type has been linked). Raises ValueError when the place is not free any more."""
    if extra.airflow:
        asset.airflow = extra.airflow
    if not extra.has_rack:
        return
    dtype = db.query(DcimDeviceType).filter(DcimDeviceType.id == asset.device_type_id).first() if asset.device_type_id else None
    check_placement(db, tenant_id, asset, asset.location_id, asset.name, dtype, extra)
    asset.rack_id, asset.rack_position, asset.rack_face = extra.rack.id, extra.position, extra.face
