import { describe, it, expect } from 'vitest'
import { slugifyKey, missingRequired, emptyValue } from '../../src/utils/customFieldDefs'

describe('customFieldDefs helpers', () => {
  it('turns a label into a valid key', () => {
    expect(slugifyKey('I/O points (digital)')).toBe('i_o_points_digital')
    expect(slugifyKey('Tensione di alimentazione')).toBe('tensione_di_alimentazione')
    expect(slugifyKey('Qualità')).toBe('qualita')
  })

  it('always returns a key that starts with a letter', () => {
    expect(slugifyKey('24V supply')).toBe('f_24v_supply')
    expect(slugifyKey('???')).toBe('field')
    expect(slugifyKey('')).toBe('field')
  })

  it('keeps keys unique and within 50 characters', () => {
    expect(slugifyKey('Voltage', ['voltage'])).toBe('voltage_2')
    expect(slugifyKey('Voltage', ['voltage', 'voltage_2'])).toBe('voltage_3')
    const long = slugifyKey('x'.repeat(200), [])
    expect(long.length).toBeLessThanOrEqual(50)
    expect(/^[a-z][a-z0-9_]{0,49}$/.test(slugifyKey('x'.repeat(200), [long]))).toBe(true)
  })

  it('lists required fields without a value', () => {
    const defs = [
      { key: 'a', label: 'A', type: 'text', required: true },
      { key: 'b', label: 'B', type: 'number', required: true },
      { key: 'c', label: 'C', type: 'boolean', required: true },
      { key: 'd', label: 'D', type: 'text', required: false }
    ]
    expect(missingRequired(defs, { a: ' ', b: 0, c: false })).toEqual(['A'])
    expect(missingRequired(defs, {})).toEqual(['A', 'B', 'C'])
    expect(missingRequired(null, {})).toEqual([])
  })

  it('gives booleans a false default and everything else null', () => {
    expect(emptyValue({ type: 'boolean' })).toBe(false)
    expect(emptyValue({ type: 'text' })).toBeNull()
  })
})
