import { describe, expect, it } from 'vitest'

import { normalizeUpdateCheckPayload } from './useUpdateCheck'

describe('normalizeUpdateCheckPayload', () => {
  it('keeps update available only when a next version exists', () => {
    expect(normalizeUpdateCheckPayload({ update_available: true, next_version: 'v0.7.5' })).toEqual({
      update_available: true,
      next_version: 'v0.7.5',
    })
    expect(normalizeUpdateCheckPayload({ update_available: true, next_version: '' })).toEqual({
      update_available: false,
      next_version: '',
    })
  })

  it('tolerates missing or malformed backend payloads', () => {
    expect(normalizeUpdateCheckPayload(null)).toEqual({ update_available: false, next_version: '' })
    expect(normalizeUpdateCheckPayload({ update_available: 1, next_version: 123 })).toEqual({
      update_available: true,
      next_version: '123',
    })
  })
})
