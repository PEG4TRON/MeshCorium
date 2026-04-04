<script setup>
import { computed, ref } from 'vue'
import { useIntervalFn } from '@vueuse/core'
import { useI18n } from 'vue-i18n'

import { resolveNodePreviewUrl } from '../../lib/nodePreview'
import { useSessionStore } from '../../stores/session'
import PhonebarClock from './PhonebarClock.vue'

const session = useSessionStore()
const { t, locale } = useI18n()

const usbIconUrl = '/icons/icons8-usb-100.png'
const phonebarTick = ref(Date.now())

function formatLocalizedNumber(value, options = {}) {
  return new Intl.NumberFormat(locale.value === 'en' ? 'en-US' : 'ru-RU', options).format(Number(value || 0))
}

function formatLocalizedDecimal(value, options = {}) {
  return new Intl.NumberFormat(locale.value === 'en' ? 'en-US' : 'ru-RU', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
    ...options,
  }).format(Number(value || 0))
}

function getBatteryPercentage(millivolts) {
  if (millivolts == null || Number.isNaN(Number(millivolts))) {
    return null
  }
  const numeric = Number(millivolts)
  const minVoltage = 3400
  const maxVoltage = 4200
  if (numeric <= minVoltage) return 0
  if (numeric >= maxVoltage) return 100
  return Math.floor(((numeric - minVoltage) / (maxVoltage - minVoltage)) * 100)
}

const notificationSoundEnabled = computed(() => Boolean(session.settingsPayload?.settings?.notifications_sound_enabled))

const batteryPercent = computed(() => {
  const telemetry = session.selfTelemetry || {}
  const batteryInfo = session.batteryInfo || {}
  if (telemetry.battery_percent != null) {
    return Math.max(0, Math.min(100, Number(telemetry.battery_percent)))
  }
  if (batteryInfo.level != null) {
    return Math.max(0, Math.min(100, Number(batteryInfo.level)))
  }
  return getBatteryPercentage(telemetry.battery_mv)
})

const nodePreviewUrl = computed(() => {
  return resolveNodePreviewUrl(session.device?.manufacturer_model || session.self?.name || '')
})

const recentRepeaterCount = computed(() => {
  return Math.max(0, Number(session.recentRepeaterCount || 0))
})

const phoneSignalLevel = computed(() => {
  const snr = session.radioStats?.last_snr
  if (snr == null) {
    return 0
  }
  const normalized = Math.max(-11, Math.min(13, Number(snr)))
  if (normalized >= 8) return 4
  if (normalized >= 2) return 3
  if (normalized >= -5) return 2
  return 1
})

const contactCountSummary = computed(() => {
  const summary = session.sessionSnapshot?.contact_summary || {}
  return {
    nodeResident: Math.max(0, Number(summary?.node_resident || 0)),
    nodeLimit: Math.max(0, Number(summary?.node_limit || 0)),
    dbTotal: Math.max(0, Number(summary?.db_total || 0)),
  }
})

const channelCountSummary = computed(() => {
  const visibleCount = Math.max(0, Number(session.sessionSnapshot?.channels_count || 0))
  return {
    visibleCount,
    totalSlots: Math.max(0, Number(session.device?.max_channels || 0)),
  }
})

const nodeLinkStatus = computed(() => {
  if (!session.connected) {
    return 'disconnected'
  }
  return (phonebarTick.value - Number(session.radioTxObservedAt || 0)) <= 2400 ? 'tx' : 'connected'
})

const phoneBarNodeName = computed(() => {
  const selfName = String(session.self?.name || '').trim()
  if (selfName) {
    return selfName
  }
  const saved = (session.savedConnections || []).find((item) => (
    String(item?.port || '') === String(session.selectedPort || '')
    && Number(item?.baudrate || 0) === Number(session.selectedBaudrate || 0)
  ))
  return String(saved?.node_name || t('common.offline'))
})

async function toggleNotificationSoundEnabled() {
  try {
    await session.toggleNotificationSoundEnabled()
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('notifications.sound.off')), true)
  }
}

useIntervalFn(() => {
  phonebarTick.value = Date.now()
}, 1000, { immediate: true })
</script>

<template>
  <header class="mc-phonebar">
    <div class="mc-phonebar-row mc-phonebar-row--with-clock">
      <div class="mc-phonebar-left">
        <div class="mc-metric">R <strong>{{ recentRepeaterCount }}</strong></div>
        <div class="mc-signal" :class="`level-${phoneSignalLevel}`"><span></span><span></span><span></span><span></span></div>
        <div class="mc-metric">{{ t('messages.phonebar.snr') }} <strong>{{ session.radioStats?.last_snr == null ? t('common.na') : `${formatLocalizedDecimal(session.radioStats.last_snr)} dB` }}</strong></div>
        <div class="mc-metric">{{ t('messages.phonebar.noise') }} <strong>{{ session.radioStats?.noise_floor == null ? t('common.na') : `${formatLocalizedNumber(session.radioStats.noise_floor)} dBm` }}</strong></div>
      </div>
      <PhonebarClock />
      <div class="mc-phonebar-right">
        <div class="mc-battery">
          <button
            v-tooltip="{ content: notificationSoundEnabled ? t('notifications.sound.on') : t('notifications.sound.off'), theme: 'meshcorium-tooltip' }"
            class="mc-sound-toggle"
            type="button"
            :class="{ muted: !notificationSoundEnabled }"
            :aria-label="notificationSoundEnabled ? t('notifications.sound.on') : t('notifications.sound.off')"
            @click.stop.prevent="toggleNotificationSoundEnabled"
          >
            {{ notificationSoundEnabled ? '🔊' : '🔇' }}
          </button>
          <img v-if="session.connected" :src="usbIconUrl" class="mc-usb-icon" alt="USB companion connected" />
          <strong v-if="batteryPercent != null">{{ batteryPercent }}%</strong>
        </div>
      </div>
    </div>
    <div class="mc-phonebar-row">
      <div class="mc-phonebar-left">
        <div class="mc-metric">{{ t('messages.phonebar.channels') }} <strong>{{ channelCountSummary.visibleCount }}/{{ channelCountSummary.totalSlots }}</strong></div>
        <div class="mc-metric">{{ t('messages.phonebar.contacts') }} <strong>{{ contactCountSummary.nodeResident }}/{{ contactCountSummary.nodeLimit }}/{{ contactCountSummary.dbTotal }}</strong></div>
      </div>
      <div class="mc-phonebar-right">
        <div class="mc-node-model">
          <img v-if="nodePreviewUrl" :src="nodePreviewUrl" alt="" class="mc-node-model-preview" />
          <strong>{{ session.device?.manufacturer_model || t('common.offline') }}</strong>
        </div>
        <span class="mc-node-led" :class="`status-${nodeLinkStatus}`" aria-hidden="true"></span>
        <div class="mc-node-name"><strong>{{ phoneBarNodeName }}</strong></div>
      </div>
    </div>
  </header>
</template>
