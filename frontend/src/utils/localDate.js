// Date helpers for date-only fields ("YYYY-MM-DD").
//
// Why not toISOString()? It converts to UTC first, so a date picked at local midnight in a
// timezone ahead of UTC (e.g. India, UTC+5:30) comes out one day early. These helpers only
// use the local calendar parts, so the day the user picked is the day that is saved.

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/

/** "YYYY-MM-DD" (or a Date) -> Date at local midnight; null for empty / invalid input. */
export function parseLocalDate(value) {
  if (!value) return null
  if (value instanceof Date) return isNaN(value) ? null : value
  const match = DATE_ONLY.exec(String(value).slice(0, 10))
  if (!match) {
    const parsed = new Date(value)
    return isNaN(parsed) ? null : parsed
  }
  const [, y, m, d] = match
  return new Date(Number(y), Number(m) - 1, Number(d))
}

/** Date (or "YYYY-MM-DD") -> "YYYY-MM-DD" from the local calendar day; null for empty / invalid. */
export function formatLocalDate(value) {
  if (!value) return null
  if (typeof value === 'string' && DATE_ONLY.test(value)) return value
  const date = value instanceof Date ? value : new Date(value)
  if (isNaN(date)) return null
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/**
 * Expiry state of a date-only value, relative to `today`:
 *  'expired' (before today), 'soon' (within `soonDays`), 'ok', or null when there is no date.
 */
export function expiryState(value, soonDays = 90, today = new Date()) {
  const date = parseLocalDate(value)
  if (!date) return null
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const days = Math.round((date - start) / 86400000)
  if (days < 0) return 'expired'
  if (days <= soonDays) return 'soon'
  return 'ok'
}

/** The date-only fields added for the OT lifecycle data. */
export const LIFECYCLE_DATE_FIELDS = [
  'purchase_date',
  'expected_delivery_date',
  'received_date',
  'commissioned_date',
  'acceptance_date',
  'warranty_expiry_date',
  'amc_expiry_date',
  'support_expiry_date',
  'licence_expiry_date',
  'disposal_date'
]
