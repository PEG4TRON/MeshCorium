import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { getSupportedLocales, setLocale } from '../i18n'

export function useLocale() {
  const { locale, t } = useI18n({ useScope: 'global' })

  const supportedLocales = computed(() => {
    return getSupportedLocales().map((code) => ({
      code,
      label: t(`locales.${code}`),
    }))
  })

  function changeLocale(nextLocale) {
    setLocale(nextLocale)
  }

  return {
    locale,
    supportedLocales,
    changeLocale,
  }
}
