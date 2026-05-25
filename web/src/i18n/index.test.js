import { describe, expect, it } from 'vitest'

import { getSupportedLocales, i18n, setLocale } from './index'

describe('i18n bootstrap', () => {
  it('exposes the supported locale list', () => {
    expect(getSupportedLocales()).toEqual(['ru', 'en'])
  })

  it('switches locale and falls back on unsupported values', () => {
    setLocale('en-US')
    expect(i18n.global.locale.value).toBe('en')

    setLocale('de')
    expect(i18n.global.locale.value).toBe('ru')
  })
})
