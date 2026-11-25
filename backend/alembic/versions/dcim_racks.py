"""DCIM (phase 2): racks, rack roles, device types, the place of an asset in a rack, and the `dcim` permission.

New tables: `dcim_rack_roles`, `dcim_racks` and `dcim_device_types`. New nullable columns on `assets`: `device_type_id`, `rack_id`,
`rack_position`, `rack_face` and `airflow`. Nothing is removed or changed.

Data: one device type is made for every manufacturer + model pair found on the assets (the model text is compared without
case or surrounding spaces) and the assets are linked to it. The height is left empty, because the assets do not say it.
Racks and positions are not in the current data and are entered or imported from a CSV file.

Permission: administrator roles (level 3 or more on `roles`) get level 4 on the new `dcim` section, roles named "editor" get 2 and
roles named "viewer" get 1; other roles are not changed.

Revision ID: dcim_racks
Revises: dcim_machine_profile
"""
import json
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "dcim_racks"
down_revision: Union[str, None] = "dcim_machine_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _load(value):
    if value is None:
        return {}
    return dict(value) if isinstance(value, dict) else json.loads(value)


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def _created_by():
    return sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _stamps():
    return [sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now())]


def upgrade() -> None:
    op.create_table(
        "dcim_rack_roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True), _tenant(),
        sa.Column("name", sa.String(100), nullable=False), sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("color", sa.String(7), nullable=True), sa.Column("description", sa.String(200), nullable=True),
        _created_by(), *_stamps(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_dcim_rack_roles_name"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_dcim_rack_roles_slug"),
    )
    op.create_index("ix_dcim_rack_roles_tenant_id", "dcim_rack_roles", ["tenant_id"])

    op.create_table(
        "dcim_device_types",
        sa.Column("id", UUID(as_uuid=True), primary_key=True), _tenant(),
        sa.Column("manufacturer_id", UUID(as_uuid=True), sa.ForeignKey("manufacturers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("u_height", sa.Numeric(4, 1), nullable=True),
        sa.Column("is_full_depth", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("airflow", sa.String(20), nullable=True), sa.Column("part_number", sa.String(100), nullable=True),
        sa.Column("description", sa.String(200), nullable=True), sa.Column("comments", sa.Text(), nullable=True),
        _created_by(), *_stamps(),
        sa.UniqueConstraint("tenant_id", "manufacturer_id", "model", name="uq_dcim_device_types_model"),
    )
    op.create_index("ix_dcim_device_types_tenant_id", "dcim_device_types", ["tenant_id"])
    op.create_index("ix_dcim_device_types_manufacturer_id", "dcim_device_types", ["manufacturer_id"])
    op.create_index("ix_dcim_device_types_tenant_model", "dcim_device_types", ["tenant_id", "model"])

    op.create_table(
        "dcim_racks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True), _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("location_id", UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("dcim_rack_roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(15), nullable=False, server_default="active"),
        sa.Column("facility_id", sa.String(50), nullable=True), sa.Column("serial", sa.String(100), nullable=True),
        sa.Column("asset_tag", sa.String(100), nullable=True),
        sa.Column("width", sa.SmallInteger(), nullable=False, server_default="19"),
        sa.Column("u_height", sa.SmallInteger(), nullable=False, server_default="42"),
        sa.Column("starting_unit", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("desc_units", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("airflow", sa.String(20), nullable=True), sa.Column("description", sa.String(200), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        _created_by(), *_stamps(),
        sa.UniqueConstraint("tenant_id", "site_id", "name", name="uq_dcim_racks_name"),
    )
    op.create_index("ix_dcim_racks_tenant_id", "dcim_racks", ["tenant_id"])
    op.create_index("ix_dcim_racks_site_id", "dcim_racks", ["site_id"])
    op.create_index("ix_dcim_racks_location_id", "dcim_racks", ["location_id"])
    op.create_index("ix_dcim_racks_tenant_asset_tag", "dcim_racks", ["tenant_id", "asset_tag"])

    op.add_column("assets", sa.Column("device_type_id", UUID(as_uuid=True), sa.ForeignKey("dcim_device_types.id", ondelete="SET NULL"), nullable=True))
    op.add_column("assets", sa.Column("rack_id", UUID(as_uuid=True), sa.ForeignKey("dcim_racks.id", ondelete="SET NULL"), nullable=True))
    op.add_column("assets", sa.Column("rack_position", sa.Numeric(5, 1), nullable=True))
    op.add_column("assets", sa.Column("rack_face", sa.String(5), nullable=True))
    op.add_column("assets", sa.Column("airflow", sa.String(20), nullable=True))
    op.create_index("ix_assets_device_type_id", "assets", ["device_type_id"])
    op.create_index("ix_assets_rack_id", "assets", ["rack_id"])

    conn = op.get_bind()
    # device types from the manufacturer + model pairs of the assets (one spelling of each is kept)
    pairs = conn.execute(sa.text(
        "SELECT a.tenant_id, a.manufacturer_id, MIN(TRIM(a.model)) FROM assets a "
        "JOIN manufacturers m ON m.id = a.manufacturer_id AND m.tenant_id = a.tenant_id "
        "WHERE a.manufacturer_id IS NOT NULL AND TRIM(COALESCE(a.model, '')) <> '' "
        "GROUP BY a.tenant_id, a.manufacturer_id, LOWER(TRIM(a.model))")).fetchall()
    types = sa.table("dcim_device_types", sa.column("id", UUID(as_uuid=True)), sa.column("tenant_id", UUID(as_uuid=True)),
                     sa.column("manufacturer_id", UUID(as_uuid=True)), sa.column("model", sa.String), sa.column("is_full_depth", sa.Boolean))
    if pairs:
        op.bulk_insert(types, [{"id": uuid.uuid4(), "tenant_id": t, "manufacturer_id": m, "model": model[:100], "is_full_depth": True} for t, m, model in pairs])
    conn.execute(sa.text(
        "UPDATE assets SET device_type_id = t.id FROM dcim_device_types t "
        "WHERE t.tenant_id = assets.tenant_id AND t.manufacturer_id = assets.manufacturer_id "
        "AND LOWER(t.model) = LOWER(TRIM(assets.model)) AND assets.device_type_id IS NULL"))

    for role_id, name, permissions in conn.execute(sa.text("SELECT id, name, permissions FROM roles")).fetchall():
        perms = _load(permissions)
        if "dcim" in perms:
            continue
        level = 4 if int(perms.get("roles", 0) or 0) >= 3 else {"editor": 2, "viewer": 1}.get((name or "").strip().lower())
        if level:
            perms["dcim"] = level
            conn.execute(sa.text("UPDATE roles SET permissions = CAST(:p AS json) WHERE id = :id"), {"p": json.dumps(perms), "id": role_id})


def downgrade() -> None:
    conn = op.get_bind()
    for role_id, permissions in conn.execute(sa.text("SELECT id, permissions FROM roles")).fetchall():
        perms = _load(permissions)
        if "dcim" in perms:
            perms.pop("dcim")
            conn.execute(sa.text("UPDATE roles SET permissions = CAST(:p AS json) WHERE id = :id"), {"p": json.dumps(perms), "id": role_id})
    op.drop_index("ix_assets_rack_id", table_name="assets")
    op.drop_index("ix_assets_device_type_id", table_name="assets")
    for column in ("airflow", "rack_face", "rack_position", "rack_id", "device_type_id"):
        op.drop_column("assets", column)
    op.drop_table("dcim_racks")
    op.drop_table("dcim_device_types")
    op.drop_table("dcim_rack_roles")
