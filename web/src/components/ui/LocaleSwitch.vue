<script setup>
import { useI18n } from 'vue-i18n'

import { useLocale } from '../../composables/useLocale'

defineProps({
  compact: {
    type: Boolean,
    default: false,
  },
  vertical: {
    type: Boolean,
    default: false,
  },
})

const { t } = useI18n()
const { locale, supportedLocales, changeLocale } = useLocale()
</script>

<template>
  <div class="mc-locale-switch" :class="{ compact, 'is-vertical': vertical }" role="group" :aria-label="t('common.language')">
    <button
      v-for="entry in supportedLocales"
      :key="entry.code"
      v-tooltip="{ content: t('common.languageSwitch', { language: entry.label }), theme: 'meshcorium-tooltip', placement: 'bottom' }"
      class="mc-locale-switch-button"
      :class="{ active: locale === entry.code }"
      type="button"
      @click="changeLocale(entry.code)"
    >
      {{ entry.label }}
    </button>
  </div>
</template>
