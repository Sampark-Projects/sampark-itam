import { describe, it, expect } from 'vitest'
import { parseLocalDate, formatLocalDate, expiryState, LIFECYCLE_DATE_FIELDS } from '../../src/utils/localDate'

describe('localDate helpers', () => {
  it('parses a date-only string as a local calendar day', () => {
    const d = parseLocalDate('2026-02-20')
    expect([d.getFullYear(), d.getMonth(), d.getDate()]).toEqual([2026, 1, 20])
    expect(d.getHours()).toBe(0)
  })

  it('returns null for empty or invalid input', () => {
    expect(parseLocalDate(null)).toBeNull()
    expect(parseLocalDate('')).toBeNull()
    expect(parseLocalDate('not a date')).toBeNull()
    expect(formatLocalDate(null)).toBeNull()
    expect(formatLocalDate('nope')).toBeNull()
  })

  it('formats a local Date without shifting the day (no UTC conversion)', () => {
    // local midnight is exactly the case where toISOString() goes one day back east of UTC
    const picked = new Date(2026, 0, 15, 0, 0, 0)
    expect(formatLocalDate(picked)).toBe('2026-01-15')
  })

  it('round-trips a date-only string', () => {
    expect(formatLocalDate(parseLocalDate('2027-12-31'))).toBe('2027-12-31')
    expect(formatLocalDate('2027-12-31')).toBe('2027-12-31')
  })

  it('classifies expiry dates', () => {
    const today = new Date(2026, 5, 10) // 10 Jun 2026
    expect(expiryState('2026-06-09', 90, today)).toBe('expired')
    expect(expiryState('2026-06-10', 90, today)).toBe('soon') // today is not expired
    expect(expiryState('2026-09-08', 90, today)).toBe('soon') // 90 days ahead
    expect(expiryState('2026-09-09', 90, today)).toBe('ok')
    expect(expiryState(null, 90, today)).toBeNull()
  })

  it('lists the ten lifecycle date fields once each', () => {
    expect(LIFECYCLE_DATE_FIELDS).toHaveLength(10)
    expect(LIFECYCLE_DATE_FIELDS).toContain('disposal_date')
    expect(new Set(LIFECYCLE_DATE_FIELDS).size).toBe(10)
  })
})
