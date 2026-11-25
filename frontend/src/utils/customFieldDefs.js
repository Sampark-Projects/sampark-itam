// Helpers for the per-asset-type field definitions (asset_types.fields_schema).
// A definition is { key, label, type, required, options, help }; the value lives in asset.custom_fields[key].

export const FIELD_TYPES = ['text', 'number', 'date', 'select', 'boolean', 'url']

// "I/O points (digital)" -> "io_points_digital"; never empty, always starts with a letter, max 50 chars
export function slugifyKey(label, takenKeys = []) {
  let base = String(label || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  if (!base) base = 'field'
  if (!/^[a-z]/.test(base)) base = `f_${base}`
  base = base.slice(0, 44).replace(/_+$/, '')
  const taken = new Set(takenKeys)
  let key = base
  for (let n = 2; taken.has(key); n++) key = `${base}_${n}`
  return key
}

// What the form needs to start from: an empty value that matches the field type
export function emptyValue(def) {
  return def.type === 'boolean' ? false : null
}

// Labels of required fields that have no value (false is a valid answer for a boolean)
export function missingRequired(defs, values) {
  return (defs || [])
    .filter(d => d.required)
    .filter(d => {
      const v = (values || {})[d.key]
      if (d.type === 'boolean') return v === null || v === undefined
      return v === null || v === undefined || String(v).trim() === ''
    })
    .map(d => d.label)
}
