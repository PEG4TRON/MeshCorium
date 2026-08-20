<script setup>
import { computed, ref } from 'vue'
import { useIntervalFn } from '@vueuse/core'
import { useI18n } from 'vue-i18n'

const { locale } = useI18n()
const clockTick = ref(Date.now())

const currentTimeText = computed(() => {
  const activeLocale = locale.value === 'en' ? 'en-US' : 'ru-RU'
  return new Intl.DateTimeFormat(activeLocale, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(clockTick.value))
})

useIntervalFn(() => {
  clockTick.value = Date.now()
}, 1000, { immediate: true })
</script>

<template>
  <div class="mc-phonebar-clock" aria-live="off">{{ currentTimeText }}</div>
</template>
