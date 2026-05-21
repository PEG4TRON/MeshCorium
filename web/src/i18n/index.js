import { computed } from 'vue'
import { createI18n } from 'vue-i18n'
import { usePreferredLanguages, useStorage } from '@vueuse/core'

import en from './messages/en'
import ru from './messages/ru'

const SUPPORTED_LOCALES = ['ru', 'en']
const FALLBACK_LOCALE = 'ru'

function normalizeLocale(value) {
  const raw = String(value || '').trim().toLowerCase()
  if (!raw) {
    return ''
  }
  const primary = raw.split('-')[0]
  return SUPPORTED_LOCALES.includes(primary) ? primary : ''
}

const preferredLanguages = usePreferredLanguages()
const storedLocale = useStorage('meshcorium_locale', '')
const initialLocale = computed(() => {
  const explicit = normalizeLocale(storedLocale.value)
  if (explicit) {
    return explicit
  }
  for (const entry of preferredLanguages.value || []) {
    const candidate = normalizeLocale(entry)
    if (candidate) {
      return candidate
    }
  }
  return FALLBACK_LOCALE
})

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale.value,
  fallbackLocale: FALLBACK_LOCALE,
  globalInjection: true,
  messages: {
    ru,
    en,
  },
})

export function setLocale(nextLocale) {
  const normalized = normalizeLocale(nextLocale) || FALLBACK_LOCALE
  i18n.global.locale.value = normalized
  storedLocale.value = normalized
}

export function getSupportedLocales() {
  return [...SUPPORTED_LOCALES]
}
