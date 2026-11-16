# backend/schemas/asset.py

from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime, date
import uuid
from app.schemas.schema_mixins import AssetRiskFieldsMixin

from .site import Site
from .asset_type import AssetType
from .location import LocationRead
from .asset_document import AssetDocument
from .asset_photo import AssetPhoto
from .manufacturer import Manufacturer as ManufacturerSchema
from .asset_status import AssetStatus as AssetStatusSchema
from .contact import Contact
from .asset_interface import AssetInterface, AssetInterfaceUpdate, AssetInterfaceCreate


class AssetContact(BaseModel):
    """Asset contact with role information"""
    contact: Contact
    role: str = Field(..., description="Contact role: owner, point_of_contact, other, technical, administrative")
    
    model_config = ConfigDict(from_attributes=True)


class AssetContactCreate(BaseModel):
    """Create asset contact with role"""
    contact_id: uuid.UUID
    role: str = Field(..., description="Contact role: owner, point_of_contact, other, technical, administrative")
    
    model_config = ConfigDict(from_attributes=True)


class AssetCustomFieldUpdate(BaseModel):
    custom_fields: Dict[str, Optional[Any]]


class AssetSummary(BaseModel):
    id: uuid.UUID
    name: str

    model_config = ConfigDict(from_attributes=True)


class AssetLifecycleFields(BaseModel):
    """OT lifecycle data (requirements gap plan, phase 1). Every field is optional."""

    # Classification
    safety_relevance: Optional[Literal["none", "safety_related", "safety_critical"]] = Field(
        None, description="Safety relevance: none, safety_related or safety_critical"
    )
    # Procurement
    requisition_number: Optional[str] = Field(None, max_length=100, description="Purchase requisition number")
    purchase_order_number: Optional[str] = Field(None, max_length=100, description="Purchase order (PO) number")
    purchase_date: Optional[date] = None
    purchase_cost: Optional[float] = Field(None, ge=0, description="Purchase cost")
    cost_currency: Optional[str] = Field(None, pattern=r"^[A-Z]{3}$", description="ISO 4217 currency code, e.g. INR")
    expected_delivery_date: Optional[date] = None
    received_date: Optional[date] = None
    # Commissioning and acceptance
    commissioned_date: Optional[date] = None
    acceptance_date: Optional[date] = None
    acceptance_signed_by: Optional[str] = Field(None, max_length=255, description="Who signed the acceptance")
    # Warranty, AMC, support and licence
    warranty_expiry_date: Optional[date] = None
    amc_expiry_date: Optional[date] = None
    support_expiry_date: Optional[date] = None
    licence_expiry_date: Optional[date] = None
    # Ownership
    plant_owner: Optional[str] = Field(None, max_length=255, description="Plant owner")
    amc_partner: Optional[str] = Field(None, max_length=255, description="Vendor / AMC partner")
    # Disposal or return
    disposal_method: Optional[Literal["scrapped", "recycled", "returned_to_vendor", "sold", "transferred", "donated"]] = Field(
        None, description="How the asset left: scrapped, recycled, returned_to_vendor, sold, transferred or donated"
    )
    disposal_date: Optional[date] = None
    disposal_reference: Optional[str] = Field(None, max_length=100, description="Certificate, RMA or transfer number")
    # Parent-child
    parent_asset_id: Optional[uuid.UUID] = Field(None, description="Asset this one is a component of")

    @field_validator("cost_currency", mode="before")
    @classmethod
    def _currency_upper(cls, v):
        # clean first (trim, upper-case, blank = not set); the 3-letter pattern is then enforced
        if isinstance(v, str):
            v = v.strip().upper()
            return v or None
        return v

    @field_validator(
        "requisition_number", "purchase_order_number", "acceptance_signed_by",
        "plant_owner", "amc_partner", "disposal_reference", "disposal_method", mode="before",
    )
    @classmethod
    def _blank_to_none(cls, v):
        # an empty form field means "not set"
        if isinstance(v, str) and not v.strip():
            return None
        return v.strip() if isinstance(v, str) else v


class AssetBase(AssetRiskFieldsMixin, AssetLifecycleFields):
    id: Optional[uuid.UUID]
    tenant_id: Optional[uuid.UUID]
    site_id: Optional[uuid.UUID]
    asset_type_id: Optional[uuid.UUID]
    location_id: Optional[uuid.UUID]
    area_id: Optional[uuid.UUID]
    name: str = Field(..., max_length=255, description="Asset name")
    tag: Optional[str] = Field(None, max_length=100, description="Asset tag")
    serial_number: Optional[str] = Field(None, max_length=100, description="Serial number")
    model: Optional[str] = Field(None, max_length=100, description="Model")
    manufacturer_id: Optional[uuid.UUID]
    firmware_version: Optional[str] = Field(None, max_length=50, description="Firmware version")
    description: Optional[str] = Field(None, max_length=10000, description="Asset description")
    custom_fields: Dict[str, Any]
    map_x: Optional[float] = None
    map_y: Optional[float] = None
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    status_id: Optional[uuid.UUID] = None
    security_zone_id: Optional[uuid.UUID] = None
    installation_date: Optional[date] = None
    business_criticality: Optional[str] = Field(None, max_length=50, description="Business criticality")
    protocols: Optional[List[str]] = []
    interfaces: Optional[List[AssetInterface]] = None
    manufacturer: Optional[ManufacturerSchema] = None
    site: Optional[Site] = None
    asset_type: Optional[AssetType] = None
    location: Optional[LocationRead] = None
    area_name: Optional[str] = None
    area_code: Optional[str] = None
    status: Optional[AssetStatusSchema] = None

    # Risk Scoring fields
    impact_value: Optional[int] = 1
    purdue_level: Optional[float] = 0.0
    exposure_level: Optional[str] = Field(None, max_length=50, description="Exposure level")
    update_status: Optional[str] = Field(None, max_length=50, description="Update status")
    risk_score: Optional[float] = 0.0

    last_risk_assessment: Optional[datetime] = None
    remote_access: Optional[bool] = False
    remote_access_type: Optional[str] = Field(None, max_length=20, description="Remote access type")
    last_update_date: Optional[datetime] = None
    physical_access_ease: Optional[str] = Field(None, max_length=50, description="Physical access ease")

    # Asset review fields
    last_review_date: Optional[datetime] = None
    next_review_date: Optional[datetime] = None
    review_status: Optional[str] = None
    review_notes: Optional[str] = None
    review_interval_months: Optional[int] = None

    documents: List[AssetDocument] = []
    photos: List[AssetPhoto] = []
    contacts: List[Contact] = []

    # set when a retirement workflow completed; the record is then read-only
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AssetUpdate(AssetRiskFieldsMixin, AssetLifecycleFields):
    name: Optional[str] = Field(None, max_length=255, description="Asset name")
    tag: Optional[str] = Field(None, max_length=100, description="Asset tag")
    serial_number: Optional[str] = Field(None, max_length=100, description="Serial number")
    model: Optional[str] = Field(None, max_length=100, description="Model")
    manufacturer_id: Optional[uuid.UUID] = None
    firmware_version: Optional[str] = Field(None, max_length=50, description="Firmware version")
    description: Optional[str] = Field(None, max_length=10000, description="Asset description")
    custom_fields: Optional[Dict[str, Any]] = None
    map_x: Optional[float] = None
    map_y: Optional[float] = None
    remote_access: Optional[bool] = None
    remote_access_type: Optional[str] = Field(None, max_length=20, description="Remote access type")
    last_update_date: Optional[datetime] = None
    physical_access_ease: Optional[str] = Field(None, max_length=50, description="Physical access ease")
    installation_date: Optional[date] = None
    business_criticality: Optional[str] = Field(None, max_length=50, description="Business criticality")
    protocols: Optional[List[str]] = None
    interfaces: Optional[List[AssetInterfaceUpdate]] = None

    site_id: Optional[uuid.UUID] = None
    asset_type_id: Optional[uuid.UUID] = None
    location_id: Optional[uuid.UUID] = None
    area_id: Optional[uuid.UUID] = None
    status_id: Optional[uuid.UUID] = None
    security_zone_id: Optional[uuid.UUID] = None

    # Risk Scoring fields
    impact_value: Optional[int] = None
    purdue_level: Optional[float] = None
    exposure_level: Optional[str] = Field(None, max_length=50, description="Exposure level")
    update_status: Optional[str] = Field(None, max_length=50, description="Update status")
    risk_score: Optional[float] = None

    # Asset review fields
    review_interval_months: Optional[int] = None


class AssetCreate(AssetRiskFieldsMixin, AssetLifecycleFields):
    name: str = Field(..., max_length=255, description="Asset name")
    tag: Optional[str] = Field(None, max_length=100, description="Asset tag")
    serial_number: Optional[str] = Field(None, max_length=100, description="Serial number")
    model: Optional[str] = Field(None, max_length=100, description="Model")
    manufacturer_id: Optional[uuid.UUID] = None
    firmware_version: Optional[str] = Field(None, max_length=50, description="Firmware version")
    description: Optional[str] = Field(None, max_length=10000, description="Asset description")
    custom_fields: Dict[str, Any] = {}
    remote_access: Optional[bool] = False
    remote_access_type: Optional[str] = Field(None, max_length=20, description="Remote access type")
    last_update_date: Optional[datetime] = None
    physical_access_ease: Optional[str] = Field(None, max_length=50, description="Physical access ease")
    installation_date: Optional[date] = None
    business_criticality: Optional[str] = Field(None, max_length=50, description="Business criticality")
    protocols: Optional[List[str]] = []
    interfaces: Optional[List[AssetInterfaceCreate]] = None
    site_id: uuid.UUID
    asset_type_id: Optional[uuid.UUID] = None
    location_id: Optional[uuid.UUID] = None
    area_id: Optional[uuid.UUID] = None
    map_x: Optional[float] = None
    map_y: Optional[float] = None
    status_id: Optional[uuid.UUID] = None
    security_zone_id: Optional[uuid.UUID] = None

    # Risk Scoring fields
    impact_value: Optional[int] = 1
    purdue_level: Optional[float] = 0.0
    exposure_level: Optional[str] = Field(None, max_length=50, description="Exposure level")
    update_status: Optional[str] = Field(None, max_length=50, description="Update status")
    risk_score: Optional[float] = 0.0


class AssetRead(AssetBase):
    location_id: Optional[uuid.UUID]
    parent: Optional[AssetSummary] = None
    contacts: List[Contact] = []
    protocols: Optional[List[str]] = []

    model_config = ConfigDict(from_attributes=True)


class AssetBulkUpdateRequest(BaseModel):
    ids: List[uuid.UUID]
    fields: Dict[str, Any]


class AssetBulkSoftDeleteRequest(BaseModel):
    ids: List[uuid.UUID]


class RiskScoreRequest(BaseModel):
    asset_id: uuid.UUID


class RiskScoreResponse(BaseModel):
    asset_id: uuid.UUID
    risk_score: Optional[float]
    risk_level: str
    risk_severity: str
    breakdown: Dict[str, Any]


class RiskOverviewResponse(BaseModel):
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    total_assets: int
    average_risk_score: float
    top_risk_assets: List[Dict[str, Any]]
