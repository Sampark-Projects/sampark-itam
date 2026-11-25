// Labels for the asset fields a workflow step can require, and the text for "what blocks this step".

// field name -> i18n key of its label
const FIELD_KEYS = {
  tag: 'assets.fields.tag',
  ip_address: 'assets.fields.ipAddress',
  protocols: 'assets.fields.protocols',
  asset_type_id: 'assets.fields.assetType',
  status_id: 'assets.fields.status',
  site_id: 'assets.fields.site',
  remote_access: 'assets.fields.remoteAccess',
  remote_access_type: 'assets.fields.remoteAccessType',
  physical_access_ease: 'assets.fields.physicalAccessEase',
  serial_number: 'assets.fields.serialNumber',
  model: 'assets.fields.model',
  firmware_version: 'assets.fields.firmwareVersion',
  manufacturer_id: 'assets.fields.manufacturer',
  location_id: 'assets.fields.location',
  area_id: 'assets.fields.area',
  security_zone_id: 'workflows.fields.securityZone',
  business_criticality: 'assets.fields.businessCriticality',
  safety_relevance: 'assets.lifecycle.fields.safetyRelevance',
  requisition_number: 'assets.lifecycle.fields.requisitionNumber',
  purchase_order_number: 'assets.lifecycle.fields.purchaseOrderNumber',
  purchase_date: 'assets.lifecycle.fields.purchaseDate',
  purchase_cost: 'assets.lifecycle.fields.purchaseCost',
  cost_currency: 'assets.lifecycle.fields.costCurrency',
  expected_delivery_date: 'assets.lifecycle.fields.expectedDeliveryDate',
  received_date: 'assets.lifecycle.fields.receivedDate',
  commissioned_date: 'assets.lifecycle.fields.commissionedDate',
  acceptance_date: 'assets.lifecycle.fields.acceptanceDate',
  acceptance_signed_by: 'assets.lifecycle.fields.acceptanceSignedBy',
  warranty_expiry_date: 'assets.lifecycle.fields.warrantyExpiryDate',
  amc_expiry_date: 'assets.lifecycle.fields.amcExpiryDate',
  support_expiry_date: 'assets.lifecycle.fields.supportExpiryDate',
  licence_expiry_date: 'assets.lifecycle.fields.licenceExpiryDate',
  plant_owner: 'assets.lifecycle.fields.plantOwner',
  amc_partner: 'assets.lifecycle.fields.amcPartner',
  disposal_method: 'assets.lifecycle.fields.disposalMethod',
  disposal_date: 'assets.lifecycle.fields.disposalDate',
  disposal_reference: 'assets.lifecycle.fields.disposalReference',
  network_settings: 'workflows.fields.networkSettings',
  config_baseline: 'workflows.fields.configBaseline',
  order_match: 'workflows.fields.orderMatch'
}

// document categories (same list as the server's workflow_logic.DOCUMENT_CATEGORIES)
export const DOCUMENT_CATEGORIES = [
  'manual', 'drawing', 'certificate', 'purchase_order', 'warranty', 'delivery_note', 'commissioning',
  'acceptance', 'test_report', 'wipe_certificate', 'disposal', 'other'
]

export function categoryLabel(category, t) {
  return category ? t(`assets.documents.categories.${category}`) : ''
}

export function fieldLabel(field, t) {
  const key = FIELD_KEYS[field]
  return key ? t(key) : field
}

// "field:serial_number" -> "Serial number", "document" -> "A document uploaded during this workflow"
export function blockerLabel(code, t) {
  if (code.startsWith('field:')) return fieldLabel(code.slice(6), t)
  if (code === 'document') return t('workflows.blockers.document')
  if (code.startsWith('document:')) return t('workflows.blockers.documentOf', { category: categoryLabel(code.slice(9), t) })
  if (code === 'comment') return t('workflows.blockers.comment')
  if (code === 'confirm') return t('workflows.blockers.confirm')
  return code
}

// the server sends "a, b, c" in the error detail of an incomplete step
export function blockersFromDetail(detail) {
  if (typeof detail !== 'string') return []
  return detail.split(',').map(s => s.trim()).filter(c => /^(field:\w+|document(:\w+)?|comment|confirm)$/.test(c))
}
