import { describe, expect, it } from 'vitest'

import { matchNodePreviewFile, resolveNodePreviewUrl } from './nodePreview'

describe('nodePreview catalog matching', () => {
  it('matches known aliases for Heltec T114', () => {
    expect(matchNodePreviewFile('Heltec T114')).toBe('heltec_t114.svg')
    expect(matchNodePreviewFile('PEG7 T114 node')).toBe('heltec_t114.svg')
  })

  it('returns a public URL for matching devices', () => {
    expect(resolveNodePreviewUrl('LilyGo T-Echo')).toBe('/icons/nodes/lilygo_techo.svg')
  })

  it('returns an empty string for unknown labels', () => {
    expect(matchNodePreviewFile('Unknown custom prototype')).toBe('')
    expect(resolveNodePreviewUrl('Unknown custom prototype')).toBe('')
  })
})
