<script setup>
import { computed, onMounted, ref, watch } from 'vue'
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
const refreshAnimating = ref(false)
const refreshBusy = computed(() => (
  session.selectedTransportType === 'ble'
    ? (refreshAnimating.value || session.loadingBleConnections)
    : (refreshAnimating.value || session.loadingPorts)
))
const refreshButtonLabel = computed(() => {
  if (session.selectedTransportType === 'ble') {
    return t('connect.ble.scan')
  }
  if (session.selectedTransportType === 'wifi') {
    return t('connect.wifi.unavailableTitle')
  }
  return t('common.refreshPorts')
})
const serialOnlyStatusMessages = computed(() => new Set([
  t('connect.status.noVisiblePorts'),
  t('connect.status.portNotSelected'),
  t('connect.status.portRequired'),
]))
const visibleConnectNotice = computed(() => {
  const notice = session.connectNotice
  if (!notice) {
    return null
  }
  if (
    session.selectedTransportType === 'ble'
    && serialOnlyStatusMessages.value.has(String(notice.message || ''))
  ) {
    return null
  }
  return notice
})
const visibleStatusText = computed(() => {
  const message = String(session.statusText || '')
  if (!message) {
    return ''
  }
  if (
    session.selectedTransportType === 'ble'
    && serialOnlyStatusMessages.value.has(message)
  ) {
    return ''
  }
  return message
})

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
  const seen = new Set()
  const options = []
  for (const entry of session.bleConnections) {
    const value = String(entry?.transport_id || entry?.address || '')
    if (!value || seen.has(value)) {
      continue
    }
    seen.add(value)
    options.push({
      value,
      label: String(entry?.display_label || entry?.name || entry?.transport_id || entry?.address || ''),
      meta: entry?.rssi == null
        ? `${entry?.cached ? t('connect.ble.availability.cached') + ' | ' : ''}${entry?.address || ''}`
        : `RSSI ${entry.rssi} | ${entry?.address || ''}`,
      triggerLabel: `${entry?.display_label || entry?.name || entry?.address || ''} | ${entry?.address || ''}`,
    })
  }
  for (const profile of filteredSavedConnections.value) {
    const value = String(profile?.connection?.transport_id || profile?.transport_id || profile?.port || '')
    if (!value || seen.has(value)) {
      continue
    }
    seen.add(value)
    const label = String(profile?.node_name || profile?.manufacturer_model || value)
    options.push({
      value,
      label,
      meta: t('connect.ble.savedDeviceMeta', { address: value }),
      triggerLabel: `${label} | ${value}`,
    })
  }
  return options
})

const selectedBleDeviceInfo = computed(() => {
  const selectedId = String(session.selectedBleDevice || '')
  const liveMatch = session.bleConnections.find(
    (entry) => String(entry?.transport_id || entry?.address || '') === selectedId,
  )
  if (liveMatch) {
    return liveMatch
  }
  const savedMatch = filteredSavedConnections.value.find(
    (profile) => String(profile?.connection?.transport_id || profile?.transport_id || profile?.port || '') === selectedId,
  )
  if (!savedMatch) {
    return null
  }
  return {
    address: selectedId,
    transport_id: selectedId,
    display_label: String(savedMatch?.node_name || savedMatch?.manufacturer_model || selectedId),
    name: String(savedMatch?.node_name || ''),
    rssi: null,
    paired: false,
    bonded: false,
    trusted: false,
    connected: false,
    cached: false,
    savedOnly: true,
  }
})

const filteredSavedConnections = computed(() => {
  const activeTransportType = ['ble', 'wifi'].includes(session.selectedTransportType) ? session.selectedTransportType : 'serial'
  return session.savedConnections.filter((profile) => resolveSavedConnectionTransportType(profile) === activeTransportType)
})

const pairedBleDevices = computed(() => {
  if (session.selectedTransportType !== 'ble') {
    return []
  }
  const byId = new Map()
  for (const entry of session.bleConnections) {
    const id = String(entry?.transport_id || entry?.address || '').trim()
    if (!id) {
      continue
    }
    if (!(entry?.paired || entry?.bonded || entry?.trusted || entry?.connected)) {
      continue
    }
    const savedProfile = filteredSavedConnections.value.find(
      (profile) => resolveSavedConnectionPort(profile) === id,
    )
    byId.set(id, {
      key: `paired-${id}`,
      address: id,
      displayName: String(
        entry?.display_label
        || entry?.name
        || savedProfile?.node_name
        || savedProfile?.manufacturer_model
        || id,
      ).trim(),
      modelName: String(
        savedProfile?.manufacturer_model
        || entry?.display_label
        || entry?.name
        || id,
      ).trim(),
      previewLabel: String(
        savedProfile?.manufacturer_model
        || savedProfile?.node_name
        || entry?.display_label
        || entry?.name
        || id,
      ).trim(),
      pairState: entry?.connected
        ? t('connect.ble.pairStates.connected')
        : (entry?.paired || entry?.bonded)
            ? t('connect.ble.pairStates.paired')
            : entry?.trusted
              ? t('connect.ble.pairStates.trusted')
              : t('connect.ble.pairStates.unpaired'),
    })
  }
  return Array.from(byId.values())
})

const nonPairedSavedConnections = computed(() => {
  if (session.selectedTransportType !== 'ble') {
    return filteredSavedConnections.value
  }
  const pairedIds = new Set(pairedBleDevices.value.map((entry) => entry.address))
  return filteredSavedConnections.value.filter((profile) => !pairedIds.has(resolveSavedConnectionPort(profile)))
})

const bleScanDisabledByPairing = computed(() => (
  session.selectedTransportType === 'ble' && pairedBleDevices.value.length > 0
))

const refreshDisabled = computed(() => {
  if (session.selectedTransportType === 'wifi') {
    return true
  }
  if (session.selectedTransportType === 'ble') {
    return session.loadingBleConnections || bleScanDisabledByPairing.value
  }
  return session.loadingPorts
})

const connectDisabled = computed(() => {
  if (session.connecting || session.selectedTransportType === 'wifi') {
    return true
  }
  if (session.selectedTransportType === 'ble') {
    return session.loadingBleConnections
  }
  return false
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

const pairedSectionTitle = computed(() => t('connect.ble.pairedSectionTitle'))
const pairedSectionSubtitle = computed(() => t('connect.ble.pairedSectionSubtitle'))

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

function pickPairedBleDevice(entry) {
  const address = String(entry?.address || '').trim()
  if (!address) {
    return
  }
  session.selectedTransportType = 'ble'
  session.selectedBleDevice = address
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
  if (bleScanDisabledByPairing.value) {
    return
  }
  refreshAnimating.value = true
  if (session.selectedTransportType === 'ble') {
    try {
      await session.refreshBleConnections()
      return
    } finally {
      refreshAnimating.value = false
    }
  }
  if (session.selectedTransportType === 'wifi') {
    try {
      session.setStatus(t('connect.status.wifiUnavailable'), true)
      return
    } finally {
      refreshAnimating.value = false
    }
  }
  try {
    await session.refreshPorts()
  } finally {
    refreshAnimating.value = false
  }
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

async function unpairSelectedBleDevice() {
  if (!selectedBleDeviceInfo.value) {
    return
  }
  try {
    await session.unpairBleDevice({
      address: String(selectedBleDeviceInfo.value?.address || selectedBleDeviceInfo.value?.transport_id || ''),
      adapterId: String(selectedBleDeviceInfo.value?.adapter_id || ''),
    })
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('connect.ble.unpairFailed')), true)
  }
}

async function ensureBleConnectionsLoaded() {
  if (session.loadingBleConnections) {
    return
  }
  if (session.bleConnections.length) {
    return
  }
  try {
    await session.refreshBleConnections()
  } catch {
    // Keep the connect window responsive even if background BLE discovery fails.
  }
}

onMounted(() => {
  void ensureBleConnectionsLoaded()
})

watch(
  () => session.selectedTransportType,
  (transportType) => {
    if (transportType === 'ble') {
      void ensureBleConnectionsLoaded()
    }
  },
)
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

    <div v-if="visibleConnectNotice" class="mc-connect-alert" :class="{ 'is-error': visibleConnectNotice.isError }">
      {{ visibleConnectNotice.message }}
    </div>

    <div class="mc-connect-float-layout">
      <div class="mc-connect-float-stack">
        <div class="mc-connect-float-card">
          <div class="mc-connect-float-primary">
            <button class="mc-button mc-button--primary mc-button--wide" type="button" :disabled="connectDisabled" @click="connectNode">
              {{ session.connecting ? t('connect.actions.connecting') : t('connect.actions.connect') }}
            </button>
            <button
              v-tooltip="{ content: refreshButtonLabel, theme: 'meshcorium-tooltip' }"
              class="mc-icon-button"
              :class="{ 'is-spinning': refreshBusy, 'mc-icon-button--with-label': session.selectedTransportType === 'ble' }"
              type="button"
              :aria-label="refreshButtonLabel"
              :disabled="refreshDisabled"
              @click="refreshTransport"
            >
              <svg class="mc-icon-button-glyph" :class="{ 'is-spinning': refreshBusy }" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M20 6v5h-5"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
                <path
                  d="M20 11a8 8 0 1 0 2 5.2"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
              <span v-if="session.selectedTransportType === 'ble'" class="mc-icon-button-label">{{ refreshButtonLabel }}</span>
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

            <div
              v-if="selectedBleDeviceInfo && (selectedBleDeviceInfo.paired || selectedBleDeviceInfo.bonded || selectedBleDeviceInfo.trusted || selectedBleDeviceInfo.connected)"
              class="mc-connect-ble-tools"
            >
              <button
                class="mc-connect-ble-unpair"
                type="button"
                :title="t('connect.ble.unpair')"
                :aria-label="t('connect.ble.unpair')"
                @click="unpairSelectedBleDevice"
              >
                ⛓
              </button>
            </div>
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

        <div v-if="visibleStatusText" class="mc-connect-float-note" :class="{ 'is-error': session.statusError }">{{ visibleStatusText }}</div>
      </div>

      <aside class="mc-connect-history-shell">
        <div class="mc-connect-history-header">
          <p class="mc-overline">{{ t('connect.history.overline') }}</p>
          <h3>{{ historyTitle }}</h3>
          <p>{{ historySubtitle }}</p>
        </div>
        <div v-if="session.selectedTransportType === 'ble' && pairedBleDevices.length" class="mc-connect-paired-shell">
          <div class="mc-connect-history-header mc-connect-history-header--subsection">
            <p class="mc-overline">{{ pairedSectionTitle }}</p>
            <p>{{ pairedSectionSubtitle }}</p>
          </div>
          <div class="mc-connect-history-list">
            <article
              v-for="entry in pairedBleDevices"
              :key="entry.key"
              class="mc-connect-history-card mc-connect-history-card--paired"
              role="button"
              tabindex="0"
              @click="pickPairedBleDevice(entry)"
              @keydown.enter.prevent="pickPairedBleDevice(entry)"
            >
              <div class="mc-connect-history-preview">
                <img
                  v-if="resolveNodePreviewUrl(entry.previewLabel)"
                  :src="resolveNodePreviewUrl(entry.previewLabel)"
                  alt=""
                />
                <span v-else>◈</span>
              </div>
              <div class="mc-connect-history-main">
                <div class="mc-connect-history-top">
                  <strong>{{ entry.displayName }}</strong>
                  <span class="mc-connect-history-kind mc-connect-history-kind--paired">{{ t('connect.ble.pairStates.paired') }}</span>
                </div>
                <div class="mc-connect-history-bottom">
                  <span class="mc-connect-history-icon">⌁</span>
                  <span>{{ entry.modelName }}</span>
                  <span>{{ entry.address }}</span>
                  <span>{{ entry.pairState }}</span>
                </div>
              </div>
            </article>
          </div>
        </div>
        <div class="mc-connect-history-list">
          <article
            v-for="profile in nonPairedSavedConnections"
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
                <span v-if="resolveSavedConnectionTransportType(profile) === 'ble'" class="mc-connect-history-icon">⌁</span>
                <span>{{ resolveSavedConnectionModelName(profile) }}</span>
                <span>{{ resolveSavedConnectionPort(profile) }}</span>
                <span v-if="resolveSavedConnectionTransportType(profile) === 'serial'">{{ resolveSavedConnectionBaudrate(profile) }}</span>
                <button class="mc-connect-history-forget" type="button" :title="t('connect.history.forget')" @click.stop="forgetSavedConnection(profile)">
                  🗑
                </button>
              </div>
            </div>
          </article>
          <div v-if="!nonPairedSavedConnections.length" class="mc-connect-history-empty">{{ historyEmptyText }}</div>
        </div>
      </aside>
    </div>
  </section>
</template>
