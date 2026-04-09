<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import LocaleSwitch from '../ui/LocaleSwitch.vue'
import PluginDropdown from '../ui/PluginDropdown.vue'
import { resolveNodePreviewUrl } from '../../lib/nodePreview'
import { useSessionStore } from '../../stores/session'

const props = defineProps({
  pageMode: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['connected'])

const { t } = useI18n()
const session = useSessionStore()

const baudrateOptions = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
const brandLogoUrl = '/icons/Meshcorium3.png'

const selectedConnectionLabel = computed(() => {
  if (session.selectedTransportType === 'wifi') {
    return t('connect.status.wifiUnavailable')
  }
  if (session.selectedTransportType === 'ble') {
    const match = session.bleConnections.find((entry) => String(entry?.transport_id || entry?.address || '') === String(session.selectedBleDevice || ''))
    if (match) {
      return `${match.display_label || match.name || match.address} | RSSI ${match.rssi ?? 'n/a'}`
    }
    return session.selectedBleDevice ? session.selectedBleDevice : t('connect.status.bleNotSelected')
  }
  const match = session.ports.find((entry) => String(entry?.transport_id || entry?.device || '') === String(session.selectedPort || ''))
  return match
    ? `${match.transport_id || match.device} | ${match.description || t('common.unknown')}`
    : t('connect.status.portNotSelected')
})

const portOptions = computed(() => {
  return session.ports.map((entry) => ({
    value: String(entry?.transport_id || entry?.device || ''),
    label: String(entry?.transport_id || entry?.device || ''),
    meta: String(entry?.description || t('common.unknown')),
    triggerLabel: `${entry?.transport_id || entry?.device || ''} | ${entry?.description || t('common.unknown')}`,
  }))
})

const baudrateDropdownOptions = computed(() => {
  return baudrateOptions.map((baudrate) => ({
    value: baudrate,
    label: String(baudrate),
  }))
})

const bleDeviceOptions = computed(() => {
  return session.bleConnections.map((entry) => ({
    value: String(entry?.transport_id || entry?.address || ''),
    label: String(entry?.display_label || entry?.name || entry?.transport_id || entry?.address || ''),
    meta: entry?.rssi == null ? String(entry?.address || '') : `RSSI ${entry.rssi} | ${entry?.address || ''}`,
    triggerLabel: `${entry?.display_label || entry?.name || entry?.address || ''} | ${entry?.address || ''}`,
  }))
})

const bleSelectedDeviceLive = computed(() => Boolean(session.selectedBleDeviceInfo))

const bleSelectedAddress = computed(() => {
  return String(
    session.selectedBleDeviceInfo?.address
    || session.selectedBleDeviceInfo?.transport_id
    || session.selectedBleDevice
    || ''
  ).trim()
})

const bleDiagnosticMessage = computed(() => {
  return String(session.bleDiagnostics?.message || '').trim()
})

const bleDiagnosticHints = computed(() => {
  const hints = Array.isArray(session.bleDiagnostics?.hints) ? session.bleDiagnostics.hints : []
  if (hints.length) {
    return hints.filter(Boolean)
  }
  if (session.selectedBleDevice && !session.selectedBleDeviceInfo) {
    return [
      t('connect.ble.hints.cachedDevice'),
      t('connect.ble.hints.powerCycle'),
      t('connect.ble.hints.keepAgentOpen'),
    ]
  }
  return [
    t('connect.ble.hints.ensureAdvertising'),
    t('connect.ble.hints.keepAgentOpen'),
  ]
})

const bleScanSummary = computed(() => {
  const count = Number(session.bleConnections.length || 0)
  const lastScanAt = Number(session.bleLastScanAt || 0)
  const timeLabel = lastScanAt ? new Date(lastScanAt).toLocaleTimeString() : t('common.unknown')
  if (count > 0) {
    return t('connect.ble.scanSummaryFound', { count, time: timeLabel })
  }
  if (lastScanAt) {
    return t('connect.ble.scanSummaryEmpty', { time: timeLabel })
  }
  return t('connect.ble.scanSummaryIdle')
})

const bleStateLabel = computed(() => {
  if (session.selectedBleDeviceInfo) {
    return t('connect.ble.stateVisible')
  }
  if (session.selectedBleDevice) {
    return t('connect.ble.stateCached')
  }
  return t('connect.ble.stateNotSelected')
})

const bleDetailRows = computed(() => {
  const info = session.selectedBleDeviceInfo || {}
  const rows = []
  if (bleSelectedAddress.value) {
    rows.push({ label: t('connect.ble.address'), value: bleSelectedAddress.value })
  }
  if (info?.rssi != null) {
    rows.push({ label: t('connect.ble.rssi'), value: `RSSI ${info.rssi}` })
  }
  const adapterId = String(info?.adapter_id || '').trim()
  if (adapterId) {
    rows.push({ label: t('connect.ble.adapter'), value: adapterId })
  }
  const serviceUuids = Array.isArray(info?.service_uuids) ? info.service_uuids : []
  if (serviceUuids.length) {
    rows.push({ label: t('connect.ble.services'), value: serviceUuids.join(', ') })
  }
  return rows
})

const filteredSavedConnections = computed(() => {
  const activeTransportType = ['ble', 'wifi'].includes(session.selectedTransportType) ? session.selectedTransportType : 'serial'
  return session.savedConnections.filter((profile) => resolveSavedConnectionTransportType(profile) === activeTransportType)
})

const historyTitle = computed(() => {
  if (session.selectedTransportType === 'wifi') {
    return t('connect.history.wifiTitle')
  }
  return session.selectedTransportType === 'ble' ? t('connect.history.bleTitle') : t('connect.history.usbTitle')
})

const historySubtitle = computed(() => {
  if (session.selectedTransportType === 'wifi') {
    return t('connect.history.wifiSubtitle')
  }
  return session.selectedTransportType === 'ble' ? t('connect.history.bleSubtitle') : t('connect.history.usbSubtitle')
})

const historyEmptyText = computed(() => {
  if (session.selectedTransportType === 'wifi') {
    return t('connect.history.wifiEmpty')
  }
  return session.selectedTransportType === 'ble' ? t('connect.history.bleEmpty') : t('connect.history.usbEmpty')
})

function resolveSavedConnectionDisplayName(profile) {
  const nodeName = String(profile?.node_name || '').trim()
  if (nodeName) {
    return nodeName
  }
  const manufacturerModel = String(profile?.manufacturer_model || '').trim()
  if (manufacturerModel) {
    return manufacturerModel
  }
  return resolveSavedConnectionPort(profile)
}

function resolveSavedConnectionModelName(profile) {
  const manufacturerModel = String(profile?.manufacturer_model || '').trim()
  if (manufacturerModel) {
    return manufacturerModel
  }
  const nodeName = String(profile?.node_name || '').trim()
  if (nodeName) {
    return nodeName
  }
  return t('common.unknownNode')
}

function resolveSavedConnectionPreviewLabel(profile) {
  return String(
    profile?.manufacturer_model
    || profile?.node_name
    || profile?.port
    || ''
  ).trim()
}

function resolveSavedConnectionPort(profile) {
  return String(profile?.connection?.transport_id || profile?.transport_id || profile?.port || '').trim()
}

function resolveSavedConnectionTransportType(profile) {
  const transportType = String(profile?.connection?.transport_type || profile?.transport_type || profile?.connection_type || 'serial').trim().toLowerCase()
  return ['ble', 'wifi'].includes(transportType) ? transportType : 'serial'
}

function resolveSavedConnectionKind(profile) {
  const transportType = resolveSavedConnectionTransportType(profile)
  if (transportType === 'wifi') {
    return t('connect.transport.wifi')
  }
  return transportType === 'ble' ? t('connect.transport.ble') : t('connect.transport.usb')
}

function resolveSavedConnectionBaudrate(profile) {
  return Number(profile?.connection?.baudrate || profile?.baudrate || session.DEFAULT_BAUDRATE) || session.DEFAULT_BAUDRATE
}

async function connectNode() {
  try {
    const payload = await session.connectNode({ light: true })
    emit('connected', payload)
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('connect.status.connectFailed')), true)
  }
}

async function refreshTransport() {
  if (session.selectedTransportType === 'ble') {
    await session.refreshBleConnections()
    return
  }
  if (session.selectedTransportType === 'wifi') {
    session.setStatus(t('connect.status.wifiUnavailable'), true)
    return
  }
  await session.refreshPorts()
}

function pickSavedConnection(profile) {
  const transportType = resolveSavedConnectionTransportType(profile)
  session.selectedTransportType = transportType
  if (transportType === 'ble') {
    session.selectedBleDevice = resolveSavedConnectionPort(profile)
    session.selectedBlePin = ''
    return
  }
  if (transportType === 'wifi') {
    session.setStatus(t('connect.status.wifiUnavailable'), true)
    return
  }
  session.selectedPort = resolveSavedConnectionPort(profile)
  session.selectedBaudrate = resolveSavedConnectionBaudrate(profile)
}

async function forgetSavedConnection(profile) {
  await session.forgetSavedConnection(profile)
}
</script>

<template>
  <section class="mc-connect-float" :class="{ 'mc-connect-float--page': pageMode }">
    <div class="mc-connect-float-hero">
      <img :src="brandLogoUrl" alt="Meshcorium" />
      <div>
        <p class="mc-overline">{{ t('connect.welcome.title') }}</p>
        <h2>{{ t('connect.workspace.title') }}</h2>
        <p>{{ t('connect.float.subtitle') }}</p>
      </div>
      <div class="mc-connect-float-locale">
        <LocaleSwitch compact vertical />
      </div>
    </div>

    <div v-if="session.connectNotice" class="mc-connect-alert" :class="{ 'is-error': session.connectNotice.isError }">
      {{ session.connectNotice.message }}
    </div>

    <div class="mc-connect-float-layout">
      <div class="mc-connect-float-stack">
        <div class="mc-connect-float-card">
          <div class="mc-connect-float-primary">
            <button class="mc-button mc-button--primary mc-button--wide" type="button" :disabled="session.connecting || session.selectedTransportType === 'wifi'" @click="connectNode">
              {{ session.connecting ? t('connect.actions.connecting') : t('connect.actions.connect') }}
            </button>
            <button
              v-tooltip="{ content: session.selectedTransportType === 'wifi' ? t('connect.wifi.unavailableTitle') : (session.selectedTransportType === 'ble' ? t('connect.ble.scan') : t('common.refreshPorts')), theme: 'meshcorium-tooltip' }"
              class="mc-icon-button"
              type="button"
              :aria-label="session.selectedTransportType === 'wifi' ? t('connect.wifi.unavailableTitle') : (session.selectedTransportType === 'ble' ? t('connect.ble.scan') : t('common.refreshPorts'))"
              :disabled="session.loadingPorts || session.loadingBleConnections || session.selectedTransportType === 'wifi'"
              @click="refreshTransport"
            >
              ↻
            </button>
          </div>

          <div class="mc-connect-transport-toggle" role="group" :aria-label="t('connect.transport.title')">
            <button
              class="mc-connect-transport-option"
              :class="{ 'is-active': session.selectedTransportType === 'serial' || !['serial', 'ble', 'wifi'].includes(session.selectedTransportType) }"
              type="button"
              @click="session.selectedTransportType = 'serial'"
            >
              {{ t('connect.transport.usb') }}
            </button>
            <button
              class="mc-connect-transport-option"
              :class="{ 'is-active': session.selectedTransportType === 'ble' }"
              type="button"
              @click="session.selectedTransportType = 'ble'; session.refreshBleConnections()"
            >
              {{ t('connect.transport.ble') }}
            </button>
            <button
              class="mc-connect-transport-option"
              :class="{ 'is-active': session.selectedTransportType === 'wifi' }"
              type="button"
              @click="session.selectedTransportType = 'wifi'; session.setStatus(t('connect.status.wifiUnavailable'), true)"
            >
              {{ t('connect.transport.wifi') }}
            </button>
          </div>

          <template v-if="session.selectedTransportType === 'wifi'">
            <div class="mc-connect-wifi-placeholder">
              <p class="mc-overline">{{ t('connect.wifi.overline') }}</p>
              <h3>{{ t('connect.wifi.title') }}</h3>
              <p>{{ t('connect.wifi.body') }}</p>
            </div>
          </template>

          <template v-else-if="session.selectedTransportType === 'ble'">
            <label class="mc-field">
              <span>{{ t('connect.ble.device') }}</span>
              <PluginDropdown
                v-model="session.selectedBleDevice"
                :options="bleDeviceOptions"
                :placeholder="t('connect.ble.selectDevice')"
                :disabled="!bleDeviceOptions.length"
                :min-width="280"
              />
            </label>

            <label class="mc-field">
              <span>{{ t('connect.ble.pin') }}</span>
              <input
                v-model="session.selectedBlePin"
                class="mc-input"
                type="password"
                inputmode="numeric"
                autocomplete="new-password"
                data-lpignore="true"
                data-1p-ignore="true"
                :placeholder="t('connect.ble.pinPlaceholder')"
              />
            </label>

            <p class="mc-connect-ble-hint">{{ t('connect.ble.pinHint') }}</p>

            <section class="mc-connect-ble-panel">
              <div class="mc-connect-ble-panel-header">
                <div>
                  <p class="mc-overline">{{ t('connect.ble.panelOverline') }}</p>
                  <h3>{{ t('connect.ble.panelTitle') }}</h3>
                </div>
                <span class="mc-connect-ble-state" :class="{ 'is-live': bleSelectedDeviceLive, 'is-cached': session.selectedBleDevice && !bleSelectedDeviceLive }">
                  {{ bleStateLabel }}
                </span>
              </div>

              <p class="mc-connect-ble-summary">{{ bleScanSummary }}</p>

              <div v-if="bleDetailRows.length" class="mc-connect-ble-grid">
                <div v-for="row in bleDetailRows" :key="row.label" class="mc-connect-ble-metric">
                  <span>{{ row.label }}</span>
                  <strong>{{ row.value }}</strong>
                </div>
              </div>

              <div class="mc-connect-ble-diagnostics" :class="{ 'is-error': Boolean(bleDiagnosticMessage) || (session.selectedBleDevice && !bleSelectedDeviceLive) }">
                <p v-if="bleDiagnosticMessage">{{ bleDiagnosticMessage }}</p>
                <p v-else-if="session.selectedBleDevice && !bleSelectedDeviceLive">{{ t('connect.ble.cachedWarning') }}</p>
                <p v-else>{{ t('connect.ble.liveReadyHint') }}</p>
                <ul class="mc-connect-ble-hints">
                  <li v-for="hint in bleDiagnosticHints" :key="hint">{{ hint }}</li>
                </ul>
              </div>
            </section>
          </template>

          <template v-else>
            <label class="mc-field">
              <span>{{ t('connect.fields.port') }}</span>
              <PluginDropdown
                v-model="session.selectedPort"
                :options="portOptions"
                :placeholder="t('connect.fields.selectPort')"
                :disabled="!portOptions.length"
                :min-width="280"
              />
            </label>

            <label class="mc-field">
              <span>{{ t('connect.fields.baudrate') }}</span>
              <PluginDropdown
                v-model="session.selectedBaudrate"
                :options="baudrateDropdownOptions"
                :min-width="180"
              />
            </label>
          </template>

          <div class="mc-connect-meta">
            <p>{{ selectedConnectionLabel }}</p>
          </div>
        </div>

        <div class="mc-connect-float-note" :class="{ 'is-error': session.statusError }">{{ session.statusText }}</div>
      </div>

      <aside class="mc-connect-history-shell">
        <div class="mc-connect-history-header">
          <p class="mc-overline">{{ t('connect.history.overline') }}</p>
          <h3>{{ historyTitle }}</h3>
          <p>{{ historySubtitle }}</p>
        </div>
        <div class="mc-connect-history-list">
          <article
            v-for="profile in filteredSavedConnections"
            :key="profile.key || `${resolveSavedConnectionPort(profile)}-${profile.baudrate}-${profile.public_key || profile.node_name}`"
            class="mc-connect-history-card"
            role="button"
            tabindex="0"
            @click="pickSavedConnection(profile)"
            @keydown.enter.prevent="pickSavedConnection(profile)"
          >
            <div class="mc-connect-history-preview">
              <img
                v-if="resolveNodePreviewUrl(resolveSavedConnectionPreviewLabel(profile))"
                :src="resolveNodePreviewUrl(resolveSavedConnectionPreviewLabel(profile))"
                alt=""
              />
              <span v-else>◈</span>
            </div>
            <div class="mc-connect-history-main">
              <div class="mc-connect-history-top">
                <strong>{{ resolveSavedConnectionDisplayName(profile) }}</strong>
                <span class="mc-connect-history-kind">{{ resolveSavedConnectionKind(profile) }}</span>
              </div>
              <div class="mc-connect-history-bottom">
                <span>{{ resolveSavedConnectionModelName(profile) }}</span>
                <span>{{ resolveSavedConnectionPort(profile) }}</span>
                <span v-if="resolveSavedConnectionTransportType(profile) === 'serial'">{{ resolveSavedConnectionBaudrate(profile) }}</span>
                <button class="mc-connect-history-forget" type="button" @click.stop="forgetSavedConnection(profile)">
                  {{ t('connect.history.forget') }}
                </button>
              </div>
            </div>
          </article>
          <div v-if="!filteredSavedConnections.length" class="mc-connect-history-empty">{{ historyEmptyText }}</div>
        </div>
      </aside>
    </div>
  </section>
</template>
