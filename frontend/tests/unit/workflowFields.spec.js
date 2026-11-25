import { describe, it, expect } from 'vitest'
import { fieldLabel, blockerLabel, blockersFromDetail } from '../../src/utils/workflowFields'

const t = (key) => `<${key}>`

describe('workflowFields helpers', () => {
  it('labels known fields through their i18n key and falls back to the field name', () => {
    expect(fieldLabel('serial_number', t)).toBe('<assets.fields.serialNumber>')
    expect(fieldLabel('acceptance_date', t)).toBe('<assets.lifecycle.fields.acceptanceDate>')
    expect(fieldLabel('something_new', t)).toBe('something_new')
  })

  it('labels blockers', () => {
    expect(blockerLabel('field:model', t)).toBe('<assets.fields.model>')
    expect(blockerLabel('document', t)).toBe('<workflows.blockers.document>')
    expect(blockerLabel('comment', t)).toBe('<workflows.blockers.comment>')
    expect(blockerLabel('confirm', t)).toBe('<workflows.blockers.confirm>')
  })

  it('reads the blockers out of an error detail and ignores anything else', () => {
    expect(blockersFromDetail('comment, field:serial_number, document')).toEqual(['comment', 'field:serial_number', 'document'])
    expect(blockersFromDetail('Unknown role')).toEqual([])
    expect(blockersFromDetail(undefined)).toEqual([])
    expect(blockersFromDetail('field:disposal_method, document:disposal')).toEqual(['field:disposal_method', 'document:disposal'])
  })

  it('names the category a document must have', () => {
    const t = (key, params) => params ? `<${key}|${params.category}>` : `<${key}>`
    expect(blockerLabel('document:disposal', t)).toBe('<workflows.blockers.documentOf|<assets.documents.categories.disposal>>')
    expect(blockerLabel('field:network_settings', t)).toBe('<workflows.fields.networkSettings>')
  })
})
