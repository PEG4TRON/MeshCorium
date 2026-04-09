<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useDebounceFn, useDocumentVisibility, useIntervalFn, useStorage } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import MessagesConfirmSheet from '../components/messages/MessagesConfirmSheet.vue'
import PluginDropdown from '../components/ui/PluginDropdown.vue'
import ShellPageFrame from '../components/layout/ShellPageFrame.vue'
import ShellPhonebar from '../components/layout/ShellPhonebar.vue'
import { useLocale } from '../composables/useLocale'
import { logFrontendDiagnostic } from '../lib/frontendDiagnostics'
import { resolveNodePreviewUrl } from '../lib/nodePreview'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()
const { t, tm } = useI18n()
const route = useRoute()
const router = useRouter()
const { locale: activeLocale, supportedLocales, changeLocale } = useLocale()
const visibility = useDocumentVisibility()

const refreshing = ref(false)
const activeSettingsSectionId = useStorage('meshcorium_settings_root_section', 'meshcorium')
const activeDebugSectionId = useStorage('meshcorium_settings_debug_section', 'debug')
const activeNodeCompanionSectionId = useStorage('meshcorium_settings_node_section', 'general')
const activeMeshcoreParamsSectionId = useStorage('meshcorium_settings_meshcore_params_section', 'radio')
const meshcoreParamsPayload = ref(null)
const meshcoreParamsLoading = ref(false)
const meshcoreParamsBusyMode = ref('')
const meshcoreParamsRadioDraft = ref({
  freq_mhz: '',
  bw_khz: '',
  sf: 7,
  cr: 5,
  tx_power_dbm: '',
  client_repeat: false,
})
const meshcoreParamsIdentityDraft = ref({
  name: '',
  lat: '',
  lon: '',
})
const meshcoreParamsRoutingDraft = ref({
  multi_acks: '',
  manual_add_only: false,
  telemetry_mode_base: 0,
  telemetry_mode_loc: 0,
  telemetry_mode_env: 0,
  rx_delay_base: '',
  airtime_factor: '',
  path_hash_mode: 0,
  autoadd_overwrite_oldest: false,
  autoadd_chat: false,
  autoadd_repeater: false,
  autoadd_room_server: false,
  autoadd_sensor: false,
  autoadd_max_hops: '',
})
const meshcoreParamsSecurityDraft = ref({
  ble_pin: '',
})
const meshcoreParamsRegionGpsDraft = ref({
  gps_enabled: false,
  gps_interval: '',
  advert_loc_policy: 0,
})
const settingsWorkspaceRef = ref(null)
const wallpaperFileInput = ref(null)
const uploadingWallpaper = ref(false)
const backgroundBlurDraftPx = ref(14)
const contactDebugPayload = ref(null)
const contactDebugLoading = ref(false)
const messageDebugSummary = ref(null)
const messageDebugSummaryLoading = ref(false)
const contactsAdminBusyMode = ref('')
const lastRootSettingsSectionId = ref('meshcorium')
const nodeCompanionNameDraft = ref('')
const nodeCompanionSaving = ref(false)
const nodeCompanionSyncingTime = ref(false)
const nodeCompanionRefreshingContacts = ref(false)
const nodeCompanionSendingAdvert = ref(false)
const nodeCompanionListenerSource = ref(null)
const signalMetricsPayload = ref(null)
const signalMetricsLoading = ref(false)
const signalMetricsHoverIndex = ref(-1)
const signalMetricsRangeSeconds = useStorage('meshcorium_signal_metrics_range_seconds', 86400)
const signalMetricsShowSnr = useStorage('meshcorium_signal_metrics_show_snr', true)
const signalMetricsShowNoise = useStorage('meshcorium_signal_metrics_show_noise', true)
const signalMetricsShowRepeaters = useStorage('meshcorium_signal_metrics_show_repeaters', false)
const signalMetricsLineWeight = useStorage('meshcorium_signal_metrics_line_weight', 50)
const signalMetricsRetentionDraft = ref(7)
const signalMetricsPollDraft = ref(15)
const nodeCompanionAuthEnabledDraft = ref(false)
const nodeCompanionAuthUsernameDraft = ref('')
const nodeCompanionAuthPasswordDraft = ref('')
const nodeCompanionSwitchTiming = ref({
  token: 0,
  startedAt: 0,
  settledLogged: false,
})
let signalMetricsLiveTimer = null
let clearMessageDbUnlockTimer = null
const confirmDialog = ref({
  open: false,
  title: '',
  message: '',
  note: '',
  confirmLabel: '',
  confirmDisabled: false,
  action: null,
})

const backgroundPresetOptions = [
  { value: 'default', labelKey: 'settings.meshcorium.background.options.default' },
  { value: 'aurora', labelKey: 'settings.meshcorium.background.options.aurora' },
  { value: 'grid', labelKey: 'settings.meshcorium.background.options.grid' },
]
const chatBackgroundPresetOptions = [
  { value: 'chat-backplane-blue', labelKey: 'settings.meshcorium.chatBackground.options.blue' },
]
const baudrateOptions = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
const meshcoriumBrandLogoUrl = '/icons/Meshcorium3.png'
const meshcoriumDisplayVersion = 'v0.5.2'

function getBatteryPercentage(millivolts) {
  const numeric = Number(millivolts)
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return null
  }
  const minVoltage = 3300
  const maxVoltage = 4150
  if (numeric <= minVoltage) {
    return 0
  }
  if (numeric >= maxVoltage) {
    return 100
  }
  return Math.floor(((numeric - minVoltage) / (maxVoltage - minVoltage)) * 100)
}

function formatJsonPayload(value) {
  return JSON.stringify(value ?? null, null, 2)
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function interpolateMessageTemplate(template, params = {}) {
  return String(template ?? '').replace(/\{(\w+)\}/g, (_, key) => {
    const value = params[key]
    return value == null ? '' : String(value)
  })
}

function readMessageTemplate(value, fallback = '') {
  return typeof value === 'string' ? value : String(fallback || '')
}

function formatDurationCompact(totalSeconds) {
  const secondsValue = Number(totalSeconds)
  if (!Number.isFinite(secondsValue) || secondsValue < 0) {
    return t('common.na')
  }
  let remaining = Math.floor(secondsValue)
  const days = Math.floor(remaining / 86400)
  remaining -= days * 86400
  const hours = Math.floor(remaining / 3600)
  remaining -= hours * 3600
  const minutes = Math.floor(remaining / 60)
  const seconds = remaining - minutes * 60
  const parts = []
  if (days) {
    parts.push(`${days}d`)
  }
  if (hours || parts.length) {
    parts.push(`${hours}h`)
  }
  if (minutes || parts.length) {
    parts.push(`${minutes}m`)
  }
  if (!parts.length || (!days && !hours)) {
    parts.push(`${seconds}s`)
  }
  return parts.join(' ')
}

function resolveSettingsOptionLabel(options, value) {
  const numericValue = Number(value)
  const match = Array.isArray(options)
    ? options.find((option) => Number(option?.value) === numericValue)
    : null
  return match?.label || String(value ?? t('common.na'))
}

function formatMeshcoreStateLabel(value) {
  return value
    ? t('settings.nodeCompanion.meshcoreParams.fields.stateOn')
    : t('settings.nodeCompanion.meshcoreParams.fields.stateOff')
}

async function refreshSettingsState({ includePorts = false, suppressStatus = false } = {}) {
  if (refreshing.value) {
    return
  }
  refreshing.value = true
  try {
    await session.loadClientSettings()
    if (includePorts) {
      await session.refreshPorts()
    }
    await session.syncSessionState({ light: true })
    if (!suppressStatus) {
      session.setStatus(t('settings.status.refreshed'))
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || t('settings.status.loadFailed'))
    if (!suppressStatus) {
      session.setStatus(message, true)
    }
  } finally {
    refreshing.value = false
  }
}

const selectedPortLabel = computed(() => {
  if (!session.selectedPort) {
    return t('settings.values.noData')
  }
  return `${session.selectedPort} @ ${session.selectedBaudrate}`
})

const serviceStatusCopy = computed(() => {
  const selfName = String(session.self?.name || '').trim()
  if (session.connected) {
    return t('settings.status.connectedTo', { target: selfName || t('common.offline') })
  }
  if (session.recoveringSessions.length) {
    return t('settings.status.recovering', { count: session.recoveringSessions.length })
  }
  return t('settings.status.disconnected')
})

const isDebugSettingsMode = computed(() => activeSettingsSectionId.value === 'debug')
const isNodeCompanionSettingsMode = computed(() => activeSettingsSectionId.value === 'node')
const isMeshcoreParamsSettingsMode = computed(() => (
  isNodeCompanionSettingsMode.value && activeNodeCompanionSectionId.value === 'meshcore-params'
))

const debugSettingsSections = computed(() => {
  return [
    {
      id: 'debug',
      title: t('settings.sections.debug.title'),
      subtitle: t('settings.sections.debug.subtitle'),
    },
    {
      id: 'messages',
      title: t('settings.debug.messagesTab'),
      subtitle: t('settings.debug.messagesSubtitle'),
    },
  ]
})

const nodeCompanionSections = computed(() => {
  return [
    {
      id: 'general',
      title: t('settings.nodeCompanion.sections.general.title'),
      subtitle: t('settings.nodeCompanion.sections.general.subtitle'),
    },
    {
      id: 'connection',
      title: t('settings.nodeCompanion.sections.connection.title'),
      subtitle: t('settings.nodeCompanion.sections.connection.subtitle'),
    },
    {
      id: 'meshcore-params',
      title: t('settings.nodeCompanion.sections.meshcoreParams.title'),
      subtitle: t('settings.nodeCompanion.sections.meshcoreParams.subtitle'),
    },
    {
      id: 'signal-metrics',
      title: t('settings.nodeCompanion.sections.signalMetrics.title'),
      subtitle: t('settings.nodeCompanion.sections.signalMetrics.subtitle'),
    },
  ]
})

const meshcoreParamsSections = computed(() => {
  return [
    {
      id: 'radio',
      title: t('settings.nodeCompanion.meshcoreParams.groups.radio.title'),
      subtitle: t('settings.nodeCompanion.meshcoreParams.groups.radio.subtitle'),
    },
    {
      id: 'identity',
      title: t('settings.nodeCompanion.meshcoreParams.groups.identity.title'),
      subtitle: t('settings.nodeCompanion.meshcoreParams.groups.identity.subtitle'),
    },
    {
      id: 'routing',
      title: t('settings.nodeCompanion.meshcoreParams.groups.routing.title'),
      subtitle: t('settings.nodeCompanion.meshcoreParams.groups.routing.subtitle'),
    },
    {
      id: 'security',
      title: t('settings.nodeCompanion.meshcoreParams.groups.security.title'),
      subtitle: t('settings.nodeCompanion.meshcoreParams.groups.security.subtitle'),
    },
    {
      id: 'region-gps',
      title: t('settings.nodeCompanion.meshcoreParams.groups.regionGps.title'),
      subtitle: t('settings.nodeCompanion.meshcoreParams.groups.regionGps.subtitle'),
    },
    {
      id: 'bridge-hardware',
      title: t('settings.nodeCompanion.meshcoreParams.groups.bridgeHardware.title'),
      subtitle: t('settings.nodeCompanion.meshcoreParams.groups.bridgeHardware.subtitle'),
    },
    {
      id: 'persisted-prefs',
      title: t('settings.nodeCompanion.meshcoreParams.groups.persistedPrefs.title'),
      subtitle: t('settings.nodeCompanion.meshcoreParams.groups.persistedPrefs.subtitle'),
    },
  ]
})

const activeMeshcoreParamsSection = computed(() => {
  const normalizedId = normalizeMeshcoreParamsSectionId(activeMeshcoreParamsSectionId.value)
  if (normalizedId !== activeMeshcoreParamsSectionId.value) {
    activeMeshcoreParamsSectionId.value = normalizedId
  }
  return meshcoreParamsSections.value.find((section) => section.id === normalizedId) || meshcoreParamsSections.value[0]
})
const meshcoreParamsGroupKey = computed(() => meshcoreParamsTranslationGroupId(activeMeshcoreParamsSection.value?.id))

const activeDebugSectionTitle = computed(() => {
  return activeDebugSectionId.value === 'messages'
    ? t('settings.debug.messagesTab')
    : t('settings.sections.debug.title')
})

const activeDebugSectionSubtitle = computed(() => {
  return activeDebugSectionId.value === 'messages'
    ? t('settings.debug.messagesSubtitle')
    : t('settings.sections.debug.subtitle')
})

const activeNodeCompanionSectionTitle = computed(() => {
  if (activeNodeCompanionSectionId.value === 'meshcore-params') {
    return activeMeshcoreParamsSection.value.title
  }
  if (activeNodeCompanionSectionId.value === 'connection') {
    return t('settings.nodeCompanion.sections.connection.title')
  }
  return activeNodeCompanionSectionId.value === 'signal-metrics'
    ? t('settings.nodeCompanion.sections.signalMetrics.title')
    : t('settings.nodeCompanion.sections.general.title')
})

const activeNodeCompanionSectionSubtitle = computed(() => {
  if (activeNodeCompanionSectionId.value === 'meshcore-params') {
    return activeMeshcoreParamsSection.value.subtitle
  }
  if (activeNodeCompanionSectionId.value === 'connection') {
    return t('settings.nodeCompanion.sections.connection.subtitle')
  }
  return activeNodeCompanionSectionId.value === 'signal-metrics'
    ? t('settings.nodeCompanion.sections.signalMetrics.subtitle')
    : t('settings.nodeCompanion.sections.general.subtitle')
})

function normalizeMeshcoreParamsSectionId(value) {
  const normalized = String(value || '').trim()
  return normalized === 'identity'
    ? 'identity'
    : (normalized === 'routing'
        ? 'routing'
        : (normalized === 'security'
            ? 'security'
            : (normalized === 'region-gps'
                ? 'region-gps'
                : (normalized === 'bridge-hardware'
                    ? 'bridge-hardware'
                    : (normalized === 'persisted-prefs' ? 'persisted-prefs' : 'radio')))))
}

function meshcoreParamsTranslationGroupId(sectionId) {
  const normalized = normalizeMeshcoreParamsSectionId(sectionId)
  return normalized === 'region-gps'
    ? 'regionGps'
    : (normalized === 'bridge-hardware'
        ? 'bridgeHardware'
        : (normalized === 'persisted-prefs' ? 'persistedPrefs' : normalized))
}

const batteryDebugPayload = computed(() => {
  const telemetry = session.selfTelemetry || {}
  const batteryInfo = session.batteryInfo || {}
  const batteryMv = telemetry?.battery_mv == null ? null : Number(telemetry.battery_mv)
  const voltage = telemetry?.voltage == null ? null : Number(telemetry.voltage)
  const telemetryPercent = telemetry?.battery_percent == null
    ? null
    : Math.max(0, Math.min(100, Number(telemetry.battery_percent)))
  const infoLevel = batteryInfo?.level == null
    ? null
    : Math.max(0, Math.min(100, Number(batteryInfo.level)))
  const fallbackPercent = batteryMv == null ? null : getBatteryPercentage(batteryMv)
  const displayedPercent = telemetryPercent == null
    ? (infoLevel == null ? fallbackPercent : infoLevel)
    : telemetryPercent
  const displayedVoltage = voltage == null ? null : Number(voltage.toFixed(3))
  return {
    connected: session.connected,
    telemetry: {
      battery_mv: batteryMv,
      voltage,
      battery_percent: telemetryPercent,
    },
    battery_info: {
      level: infoLevel,
      used_kb: batteryInfo?.used_kb ?? null,
      total_kb: batteryInfo?.total_kb ?? null,
    },
    ui_display: {
      displayed_percent: displayedPercent,
      displayed_voltage: displayedVoltage,
      fallback_percent_from_battery_mv: fallbackPercent,
    },
  }
})

const batteryDebugNote = computed(() => {
  return session.connected
    ? t('settings.debug.battery.connectedNote')
    : t('settings.debug.battery.disconnectedNote')
})

const contactDebugNote = computed(() => {
  if (contactDebugLoading.value) {
    return t('settings.debug.contacts.loading')
  }
  if (!session.connected || !session.selectedPort) {
    return t('settings.debug.contacts.disconnectedNote')
  }
  return t('settings.debug.contacts.connectedNote', { port: session.selectedPort })
})

const contactDebugOutput = computed(() => {
  return formatJsonPayload(contactDebugPayload.value || {
    policy: null,
    summary: null,
    selected_public_key: '',
    selected_cached_contact: null,
    live_contacts: [],
    recent_residency_events: [],
  })
})

const messageDebugSummaryCards = computed(() => {
  const summary = messageDebugSummary.value || {}
  return [
    {
      id: 'mentions',
      label: t('settings.debug.messages.summary.mentions'),
      value: Math.max(0, Number(summary.mention_messages || 0)),
    },
    {
      id: 'regular',
      label: t('settings.debug.messages.summary.regular'),
      value: Math.max(0, Number(summary.regular_messages || 0)),
    },
    {
      id: 'direct',
      label: t('settings.debug.messages.summary.direct'),
      value: Math.max(0, Number(summary.direct_messages || 0)),
    },
  ]
})

const nodeCompanionAvailable = computed(() => Boolean(String(session.selectedPort || '').trim()))
const meshcoreParamsAvailable = computed(() => Boolean(session.connected && session.selectedConnection?.transport_id))

const nodeCompanionListenerActive = computed(() => Boolean(nodeCompanionListenerSource.value))

const nodeCompanionPreviewUrl = computed(() => {
  const candidates = [
    session.device?.manufacturer_model,
    session.device?.name,
    session.device?.hardware_name,
    session.device?.board_name,
    session.device?.platform,
  ]
  for (const candidate of candidates) {
    const url = resolveNodePreviewUrl(candidate)
    if (url) {
      return url
    }
  }
  return ''
})

const nodeCompanionContactSummary = computed(() => {
  const summary = session.sessionSnapshot?.contact_summary || {}
  const nodeResident = Math.max(0, Number(summary?.node_resident || 0))
  const dbTotal = Math.max(0, Number(summary?.db_total || 0))
  const nodeLimit = Math.max(0, Number(summary?.node_limit || session.device?.max_contacts_base || session.device?.max_contacts || 0))
  return `${nodeResident}/${nodeLimit}/${dbTotal}`
})

const nodeCompanionChannelSummary = computed(() => {
  const visible = Math.max(0, Number(session.sessionSnapshot?.channels_count || 0))
  const total = Math.max(0, Number(session.device?.max_channels || 0))
  return `${visible}/${total}`
})

const nodeCompanionStatusSummary = computed(() => {
  const uptimeSecs = session.radioStats?.uptime_secs ?? session.selfTelemetry?.uptime_secs ?? null
  const uptimeLabel = formatDurationCompact(uptimeSecs)
  const batteryLevel = session.batteryInfo?.level == null
    ? (session.selfTelemetry?.battery_mv == null ? null : getBatteryPercentage(session.selfTelemetry.battery_mv))
    : Math.max(0, Math.min(100, Number(session.batteryInfo.level)))
  return batteryLevel == null ? `${uptimeLabel}; ${t('common.na')}` : `${uptimeLabel}; ${batteryLevel}%`
})

const nodeCompanionModelSummary = computed(() => {
  const nodeModel = String(session.device?.manufacturer_model || t('common.na')).trim() || t('common.na')
  const nodeName = String(session.self?.name || '').trim()
  return nodeName ? `${nodeModel}; ${nodeName}` : nodeModel
})

const nodeCompanionFirmwareSummary = computed(() => {
  return String(session.device?.semantic_version || session.device?.firmware_ver || t('common.na')).trim() || t('common.na')
})

const nodeCompanionPublicKeySummary = computed(() => {
  return String(session.self?.public_key || t('common.na')).trim() || t('common.na')
})

const nodeCompanionListenerLabel = computed(() => {
  return nodeCompanionListenerActive.value
    ? t('settings.nodeCompanion.actions.stopListener')
    : t('settings.nodeCompanion.actions.startListener')
})

const nodeCompanionPortOptions = computed(() => {
  return session.ports.map((entry) => ({
    value: String(entry?.transport_id || entry?.device || ''),
    label: String(entry?.transport_id || entry?.device || ''),
    meta: String(entry?.description || t('common.unknown')),
    triggerLabel: `${entry?.transport_id || entry?.device || ''} | ${entry?.description || t('common.unknown')}`,
  }))
})

const nodeCompanionBaudrateOptions = computed(() => {
  return baudrateOptions.map((baudrate) => ({
    value: baudrate,
    label: String(baudrate),
  }))
})

const nodeCompanionPortLabel = computed(() => {
  const match = session.ports.find((entry) => String(entry?.transport_id || entry?.device || '') === String(session.selectedPort || ''))
  return match
    ? `${match.transport_id || match.device} | ${match.description || t('common.unknown')}`
    : t('connect.status.portNotSelected')
})

const notificationSoundOptions = computed(() => {
  const files = Array.isArray(session.settingsPayload?.notification_sound_files) ? session.settingsPayload.notification_sound_files : []
  return files.map((fileName) => ({
    value: String(fileName || ''),
    label: String(fileName || ''),
  })).filter((entry) => entry.label)
})
const playSoundIconUrl = '/icons/PlaySound.svg'

const startupProfileOptions = computed(() => {
  return session.savedConnections.map((profile) => ({
    value: String(profile?.key || ''),
    label: String(profile?.label || `${profile?.port || ''} @ ${profile?.baudrate || ''}`),
  })).filter((entry) => entry.value)
})

const startupUseLastSuccessful = computed(() => Boolean(session.settingsPayload?.settings?.startup_use_last_successful))
const autoConnectOnServiceStart = computed(() => Boolean(session.settingsPayload?.settings?.auto_connect_on_service_start))
const accessAllMeshcoriumContacts = computed(() => Boolean(session.settingsPayload?.settings?.access_all_meshcorium_contacts !== false))
const selectedStartupConnectionKey = computed(() => String(session.settingsPayload?.settings?.startup_connection_key || ''))
const regularNotificationSoundFile = computed(() => String(session.settingsPayload?.settings?.notification_regular_sound_file || ''))
const mentionNotificationSoundFile = computed(() => String(session.settingsPayload?.settings?.notification_mention_sound_file || ''))
const directNotificationSoundFile = computed(() => String(session.settingsPayload?.settings?.notification_direct_sound_file || ''))
const regularNotificationSoundPreviewPlaying = ref(false)
const mentionNotificationSoundPreviewPlaying = ref(false)
const directNotificationSoundPreviewPlaying = ref(false)
const authPasswordConfigured = computed(() => Boolean(session.settingsPayload?.settings?.auth_password_configured))
const soundPreviewAudios = {
  regular: null,
  mention: null,
  direct: null,
}
function classifyContactKind(contact) {
  const advType = Number(contact?.adv_type || 0)
  if (advType === 2) {
    return 'repeater'
  }
  if (advType === 3) {
    return 'room'
  }
  if (advType === 4) {
    return 'sensor'
  }
  return 'contact'
}

function collectContactCategoryCounts(list) {
  const counts = {
    total: 0,
    contacts: 0,
    repeaters: 0,
    rooms: 0,
    sensors: 0,
  }
  for (const entry of Array.isArray(list) ? list : []) {
    counts.total += 1
    const kind = classifyContactKind(entry)
    if (kind === 'repeater') {
      counts.repeaters += 1
    } else if (kind === 'room') {
      counts.rooms += 1
    } else if (kind === 'sensor') {
      counts.sensors += 1
    } else {
      counts.contacts += 1
    }
  }
  return counts
}

function contactLegendCount(summary, scope, key) {
  const suffix = String(key || '')
  if (!suffix) {
    return 0
  }
  const property = `${scope}${suffix.charAt(0).toUpperCase()}${suffix.slice(1)}`
  return Math.max(0, Number(summary?.[property] || 0))
}

const contactsAdminSummary = computed(() => {
  const summary = session.sessionSnapshot?.contact_summary
  const contacts = Array.isArray(session.contacts) ? session.contacts : []
  const liveContacts = contacts.filter((contact) => Boolean(contact?.is_on_node))
  const dbCounts = collectContactCategoryCounts(contacts)
  const liveCounts = collectContactCategoryCounts(liveContacts)
  if (summary && typeof summary === 'object' && !Array.isArray(summary)) {
    return {
      nodeResident: Math.max(0, Number(summary.node_resident || 0)),
      nodeLimit: Math.max(0, Number(summary.node_limit || 0)),
      policyNonFavoriteLimit: Math.max(0, Number(summary.policy_non_favorite_limit || 0)),
      dbTotal: Math.max(0, Number(summary.db_total || 0)),
      dbOnly: Math.max(0, Number(summary.db_only || 0)),
      nodeFavorites: Math.max(0, Number(summary.node_favorites || 0)),
      nodeDirectHistory: Math.max(0, Number(summary.node_direct_history || 0)),
      nodeNonFavorites: Math.max(0, Number(summary.node_non_favorites || 0)),
      nodeRepeaters: Math.max(0, Number(summary.node_repeaters || 0)),
      nodeUsers: Math.max(0, Number(summary.node_users || liveCounts.contacts + liveCounts.rooms + liveCounts.sensors)),
      nodeFree: Math.max(0, Number(summary.node_free || 0)),
      nodeContacts: Math.max(0, Number(summary.node_contacts ?? liveCounts.contacts)),
      nodeRooms: Math.max(0, Number(summary.node_rooms ?? liveCounts.rooms)),
      nodeSensors: Math.max(0, Number(summary.node_sensors ?? liveCounts.sensors)),
      dbContacts: Math.max(0, Number(summary.db_contacts ?? dbCounts.contacts)),
      dbRepeaters: Math.max(0, Number(summary.db_repeaters ?? dbCounts.repeaters)),
      dbRooms: Math.max(0, Number(summary.db_rooms ?? dbCounts.rooms)),
      dbSensors: Math.max(0, Number(summary.db_sensors ?? dbCounts.sensors)),
    }
  }
  const dbOnly = Math.max(0, contacts.length - liveContacts.length)
  const nodeFavorites = liveContacts.filter((contact) => Boolean(contact?.flags?.favorite)).length
  const nodeDirectHistory = liveContacts.filter((contact) => Number(contact?.last_message_at || 0) > 0).length
  const nodeLimit = Math.max(0, Number(session.device?.max_contacts_base ?? session.device?.max_contacts ?? 0))
  return {
    nodeResident: liveContacts.length,
    nodeLimit,
    policyNonFavoriteLimit: Math.max(0, Number(session.device?.max_contacts_policy_non_favorite_limit || 50)),
    dbTotal: contacts.length,
    dbOnly,
    nodeFavorites,
    nodeDirectHistory,
    nodeNonFavorites: Math.max(0, liveContacts.length - nodeFavorites),
    nodeRepeaters: liveCounts.repeaters,
    nodeUsers: Math.max(0, liveContacts.length - liveCounts.repeaters),
    nodeFree: Math.max(0, nodeLimit - liveContacts.length),
    nodeContacts: liveCounts.contacts,
    nodeRooms: liveCounts.rooms,
    nodeSensors: liveCounts.sensors,
    dbContacts: dbCounts.contacts,
    dbRepeaters: dbCounts.repeaters,
    dbRooms: dbCounts.rooms,
    dbSensors: dbCounts.sensors,
  }
})
const contactsAdminUsagePercent = computed(() => {
  const summary = contactsAdminSummary.value
  if (!summary.nodeLimit) {
    return 0
  }
  return Math.max(0, Math.min(100, Math.round((summary.nodeResident / summary.nodeLimit) * 100)))
})
const contactsAdminLegendItems = computed(() => {
  return [
    {
      id: 'contacts',
      label: t('settings.contacts.legend.contacts'),
      className: 'mc-settings-contacts-legend-dot--contacts',
      countKey: 'contacts',
    },
    {
      id: 'repeaters',
      label: t('settings.contacts.legend.repeaters'),
      className: 'mc-settings-contacts-legend-dot--repeaters',
      countKey: 'repeaters',
    },
    {
      id: 'rooms',
      label: t('settings.contacts.legend.rooms'),
      className: 'mc-settings-contacts-legend-dot--rooms',
      countKey: 'rooms',
    },
    {
      id: 'sensors',
      label: t('settings.contacts.legend.sensors'),
      className: 'mc-settings-contacts-legend-dot--sensors',
      countKey: 'sensors',
    },
  ]
})
const contactsAdminNodeFillItems = computed(() => {
  const summary = contactsAdminSummary.value
  if (!summary.nodeLimit) {
    return []
  }
  return [
    { id: 'contacts', className: 'mc-settings-contacts-capacity-fill--contacts', width: (summary.nodeContacts / summary.nodeLimit) * 100 },
    { id: 'repeaters', className: 'mc-settings-contacts-capacity-fill--repeaters', width: (summary.nodeRepeaters / summary.nodeLimit) * 100 },
    { id: 'rooms', className: 'mc-settings-contacts-capacity-fill--rooms', width: (summary.nodeRooms / summary.nodeLimit) * 100 },
    { id: 'sensors', className: 'mc-settings-contacts-capacity-fill--sensors', width: (summary.nodeSensors / summary.nodeLimit) * 100 },
  ].map((item) => ({ ...item, width: Math.max(0, Math.min(100, item.width)) }))
})
const contactsMeshcoriumFillItems = computed(() => {
  const summary = contactsAdminSummary.value
  if (!summary.dbTotal) {
    return []
  }
  return [
    { id: 'contacts', className: 'mc-settings-contacts-capacity-fill--contacts', width: (summary.dbContacts / summary.dbTotal) * 100 },
    { id: 'repeaters', className: 'mc-settings-contacts-capacity-fill--repeaters', width: (summary.dbRepeaters / summary.dbTotal) * 100 },
    { id: 'rooms', className: 'mc-settings-contacts-capacity-fill--rooms', width: (summary.dbRooms / summary.dbTotal) * 100 },
    { id: 'sensors', className: 'mc-settings-contacts-capacity-fill--sensors', width: (summary.dbSensors / summary.dbTotal) * 100 },
  ].map((item) => ({ ...item, width: Math.max(0, Math.min(100, item.width)) }))
})
const nodeCompanionConnectionNoteTemplates = computed(() => {
  const raw = tm('settings.nodeCompanion.connection.note')
  if (!raw || typeof raw !== 'object') {
    return {
      activeSession: 'Service session: {name} ({port} @ {baudrate}).{queueSuffix}',
      recoveringSession: 'Background session recovery is already in progress for {port}. Current reconnect attempt: {attempts}.',
      default: 'After an unexpected disconnect, the service will try to reconnect using the last successful profile automatically.',
      queueInProgress: ' The session is currently draining the companion offline queue.',
      queueInProgressWithCycles: ' The session is currently draining the companion offline queue: cycle {cycles}.',
      queueRequested: ' A follow-up queue drain is already scheduled for this session.',
      queueOverflow: ' The last queue drain flushed {total} messages; the backlog was heavy.',
      queueOverflowWithCycles: ' The last queue drain flushed {total} messages across {cycles} cycle(s); the backlog was heavy.',
    }
  }
  return {
    activeSession: readMessageTemplate(raw.activeSession, 'Service session: {name} ({port} @ {baudrate}).{queueSuffix}'),
    recoveringSession: readMessageTemplate(raw.recoveringSession, 'Background session recovery is already in progress for {port}. Current reconnect attempt: {attempts}.'),
    default: readMessageTemplate(raw.default, 'After an unexpected disconnect, the service will try to reconnect using the last successful profile automatically.'),
    queueInProgress: readMessageTemplate(raw.queueInProgress, ' The session is currently draining the companion offline queue.'),
    queueInProgressWithCycles: readMessageTemplate(raw.queueInProgressWithCycles, ' The session is currently draining the companion offline queue: cycle {cycles}.'),
    queueRequested: readMessageTemplate(raw.queueRequested, ' A follow-up queue drain is already scheduled for this session.'),
    queueOverflow: readMessageTemplate(raw.queueOverflow, ' The last queue drain flushed {total} messages; the backlog was heavy.'),
    queueOverflowWithCycles: readMessageTemplate(raw.queueOverflowWithCycles, ' The last queue drain flushed {total} messages across {cycles} cycle(s); the backlog was heavy.'),
  }
})

const nodeCompanionConnectionNote = computed(() => {
  try {
    const templates = nodeCompanionConnectionNoteTemplates.value
  const selectedPort = String(session.selectedPort || session.resolvedStartupConnection?.port || '').trim()
  const activeSession = (session.activeSessions || []).find((entry) => String(entry?.port || '') === selectedPort)
    || session.activeSessions?.[0]
    || null
  if (activeSession) {
    const queueDrainInProgress = Boolean(activeSession.queue_drain_in_progress)
    const queueDrainRequested = Boolean(activeSession.queue_drain_requested)
    const queueOverflowRisk = Boolean(activeSession.queue_last_overflow_risk)
    const queueDrainMessages = Math.max(0, Number(activeSession.queue_last_drain_message_count || 0))
    const queueDrainCycles = Math.max(0, Number(activeSession.queue_last_drain_cycles || 0))
    let queueSuffix = ''
    if (queueDrainInProgress) {
      queueSuffix = queueDrainCycles > 0
        ? interpolateMessageTemplate(
          templates.queueInProgressWithCycles,
          { cycles: queueDrainCycles },
        )
        : templates.queueInProgress
    } else if (queueDrainRequested) {
      queueSuffix = templates.queueRequested
    } else if (queueOverflowRisk && queueDrainMessages > 0) {
      queueSuffix = queueDrainCycles > 1
        ? interpolateMessageTemplate(
          templates.queueOverflowWithCycles,
          { total: queueDrainMessages, cycles: queueDrainCycles },
        )
        : interpolateMessageTemplate(
          templates.queueOverflow,
          { total: queueDrainMessages },
        )
    }
    return interpolateMessageTemplate(templates.activeSession, {
      name: activeSession.self_name || activeSession.port || t('common.offline'),
      port: activeSession.port || t('common.offline'),
      baudrate: activeSession.baudrate || session.selectedBaudrate || 0,
      queueSuffix,
    })
  }
  if (session.recoveringSessions.length) {
    const recoveringSession = session.recoveringSessions[0] || {}
    return interpolateMessageTemplate(templates.recoveringSession, {
      port: recoveringSession.port || t('common.offline'),
      attempts: Math.max(0, Number(recoveringSession.reconnect_attempts || 0)),
    })
  }
    return templates.default
  } catch {
    return 'Companion service session status is temporarily unavailable.'
  }
})

const meshcoreParamsRadio = computed(() => meshcoreParamsPayload.value?.radio || {})
const meshcoreParamsIdentity = computed(() => meshcoreParamsPayload.value?.identity || {})
const meshcoreParamsRouting = computed(() => meshcoreParamsPayload.value?.routing || {})
const meshcoreParamsSecurity = computed(() => meshcoreParamsPayload.value?.security || {})
const meshcoreParamsRegionGps = computed(() => meshcoreParamsPayload.value?.region_gps || {})
const meshcoreParamsBridgeHardware = computed(() => meshcoreParamsPayload.value?.bridge_hardware || {})
const meshcoreParamsPersistedPrefs = computed(() => meshcoreParamsPayload.value?.persisted_prefs || {})
const meshcoreParamsRawCustomVars = computed(() => meshcoreParamsPayload.value?.raw_custom_vars || {})
const meshcoreParamsCapabilities = computed(() => meshcoreParamsPayload.value?.capabilities || {})
const meshcoreParamsCompanionCliRescueOnly = computed(() => Boolean(meshcoreParamsCapabilities.value?.companion_cli_rescue_physical_only))
const meshcoreParamsConstraints = computed(() => meshcoreParamsPayload.value?.constraints || {})
const meshcoreParamsRadioConstraints = computed(() => meshcoreParamsConstraints.value?.radio || {})
const meshcoreParamsIdentityConstraints = computed(() => meshcoreParamsConstraints.value?.identity || {})
const meshcoreParamsRoutingConstraints = computed(() => meshcoreParamsConstraints.value?.routing || {})
const meshcoreParamsSecurityConstraints = computed(() => meshcoreParamsConstraints.value?.security || {})
const meshcoreParamsRegionGpsConstraints = computed(() => meshcoreParamsConstraints.value?.region_gps || {})
const meshcoreTelemetryModeOptions = computed(() => [
  { value: 0, label: t('settings.nodeCompanion.meshcoreParams.fields.telemetryModeOptions.deny') },
  { value: 1, label: t('settings.nodeCompanion.meshcoreParams.fields.telemetryModeOptions.flags') },
  { value: 2, label: t('settings.nodeCompanion.meshcoreParams.fields.telemetryModeOptions.allowAll') },
])
const meshcoreAdvertLocPolicyOptions = computed(() => [
  { value: 0, label: t('settings.nodeCompanion.meshcoreParams.fields.advertPolicyOptions.none') },
  { value: 1, label: t('settings.nodeCompanion.meshcoreParams.fields.advertPolicyOptions.share') },
  { value: 2, label: t('settings.nodeCompanion.meshcoreParams.fields.advertPolicyOptions.prefs') },
])
const meshcorePathHashModeOptions = computed(() => [
  { value: 0, label: t('settings.nodeCompanion.meshcoreParams.fields.pathHashModeOptions.byte1') },
  { value: 1, label: t('settings.nodeCompanion.meshcoreParams.fields.pathHashModeOptions.byte2') },
  { value: 2, label: t('settings.nodeCompanion.meshcoreParams.fields.pathHashModeOptions.byte3') },
])
const meshcorePersistedAutoaddLabels = computed(() => {
  const prefs = meshcoreParamsPersistedPrefs.value || {}
  const labels = []
  if (prefs.autoadd_overwrite_oldest) {
    labels.push(t('settings.nodeCompanion.meshcoreParams.fields.autoaddOverwriteOldest'))
  }
  if (prefs.autoadd_chat) {
    labels.push(t('settings.nodeCompanion.meshcoreParams.fields.autoaddChat'))
  }
  if (prefs.autoadd_repeater) {
    labels.push(t('settings.nodeCompanion.meshcoreParams.fields.autoaddRepeater'))
  }
  if (prefs.autoadd_room_server) {
    labels.push(t('settings.nodeCompanion.meshcoreParams.fields.autoaddRoomServer'))
  }
  if (prefs.autoadd_sensor) {
    labels.push(t('settings.nodeCompanion.meshcoreParams.fields.autoaddSensor'))
  }
  return labels
})

function captureNodeConnectionRenderField(field, fallback, resolver) {
  try {
    return resolver()
  } catch (error) {
    logFrontendDiagnostic('settings-node-connection-render-error', {
      field,
      activeSettingsSectionId: activeSettingsSectionId.value,
      activeNodeCompanionSectionId: activeNodeCompanionSectionId.value,
      selectedPort: String(session.selectedPort || ''),
      message: error instanceof Error ? error.message : String(error || ''),
      stack: error instanceof Error ? String(error.stack || '') : '',
    })
    return typeof fallback === 'function' ? fallback() : fallback
  }
}

const nodeConnectionRenderModel = computed(() => {
  const historyProfiles = captureNodeConnectionRenderField('historyProfiles', [], () => {
    return session.savedConnections.map((profile) => {
      const previewLabel = resolveSavedConnectionPreviewLabel(profile)
      return {
        raw: profile,
        key: profile.key || `${resolveSavedConnectionPort(profile)}-${resolveSavedConnectionBaudrate(profile)}-${profile.public_key || profile.node_name}`,
        previewUrl: resolveNodePreviewUrl(previewLabel),
        displayName: resolveSavedConnectionDisplayName(profile),
        modelName: resolveSavedConnectionModelName(profile),
        port: resolveSavedConnectionPort(profile),
        baudrate: resolveSavedConnectionBaudrate(profile),
      }
    })
  })
  return {
    portOptions: captureNodeConnectionRenderField('portOptions', [], () => nodeCompanionPortOptions.value),
    selectedPort: captureNodeConnectionRenderField('selectedPort', '', () => String(session.selectedPort || '')),
    baudrateOptions: captureNodeConnectionRenderField('baudrateOptions', [], () => nodeCompanionBaudrateOptions.value),
    selectedBaudrate: captureNodeConnectionRenderField('selectedBaudrate', String(session.DEFAULT_BAUDRATE), () => String(session.selectedBaudrate || session.DEFAULT_BAUDRATE)),
    autoConnectOnServiceStart: captureNodeConnectionRenderField('autoConnectOnServiceStart', false, () => autoConnectOnServiceStart.value),
    startupUseLastSuccessful: captureNodeConnectionRenderField('startupUseLastSuccessful', false, () => startupUseLastSuccessful.value),
    startupProfileOptions: captureNodeConnectionRenderField('startupProfileOptions', [], () => startupProfileOptions.value),
    selectedStartupConnectionKey: captureNodeConnectionRenderField('selectedStartupConnectionKey', '', () => selectedStartupConnectionKey.value),
    accessAllMeshcoriumContacts: captureNodeConnectionRenderField('accessAllMeshcoriumContacts', true, () => accessAllMeshcoriumContacts.value),
    historyProfiles,
    connectionNote: captureNodeConnectionRenderField('connectionNote', t('settings.nodeCompanion.connection.note.default'), () => nodeCompanionConnectionNote.value),
  }
})

function buildNodeCompanionConfig(extra = {}) {
  const config = session.configBody(extra)
  const connection = session.selectedConnection
  const transportType = String(connection?.transport_type || config?.transport_type || '').trim().toLowerCase()
  const transportId = String(connection?.transport_id || config?.transport_id || config?.port || '').trim()
  if (!transportId || transportType === 'wifi') {
    session.setStatus(t('settings.nodeCompanion.status.connectionRequired'), true)
    return null
  }
  return config
}

function setOptionalNumberField(target, key, value, { integer = false } = {}) {
  if (value == null) {
    return
  }
  const normalized = typeof value === 'string' ? value.trim() : value
  if (normalized === '') {
    return
  }
  const parsed = integer ? Number.parseInt(normalized, 10) : Number(normalized)
  if (!Number.isFinite(parsed)) {
    return
  }
  target[key] = parsed
}

function resetMeshcoreParamsDrafts() {
  meshcoreParamsRadioDraft.value = {
    freq_mhz: '',
    bw_khz: '',
    sf: 7,
    cr: 5,
    tx_power_dbm: '',
    client_repeat: false,
  }
  meshcoreParamsIdentityDraft.value = {
    name: '',
    lat: '',
    lon: '',
  }
  meshcoreParamsRoutingDraft.value = {
    multi_acks: '',
    manual_add_only: false,
    telemetry_mode_base: 0,
    telemetry_mode_loc: 0,
    telemetry_mode_env: 0,
    rx_delay_base: '',
    airtime_factor: '',
    path_hash_mode: 0,
    autoadd_overwrite_oldest: false,
    autoadd_chat: false,
    autoadd_repeater: false,
    autoadd_room_server: false,
    autoadd_sensor: false,
    autoadd_max_hops: '',
  }
  meshcoreParamsSecurityDraft.value = {
    ble_pin: '',
  }
  meshcoreParamsRegionGpsDraft.value = {
    gps_enabled: false,
    gps_interval: '',
    advert_loc_policy: 0,
  }
}

function populateMeshcoreParamsDrafts(payload) {
  const radio = payload?.radio || {}
  const identity = payload?.identity || {}
  const routing = payload?.routing || {}
  const telemetryModes = routing?.telemetry_modes || {}
  const security = payload?.security || {}
  const regionGps = payload?.region_gps || {}
  meshcoreParamsRadioDraft.value = {
    freq_mhz: radio?.freq_mhz ?? '',
    bw_khz: radio?.bw_khz ?? '',
    sf: Number(radio?.sf || 7) || 7,
    cr: Number(radio?.cr || 5) || 5,
    tx_power_dbm: radio?.tx_power_dbm ?? '',
    client_repeat: Boolean(radio?.client_repeat),
  }
  meshcoreParamsIdentityDraft.value = {
    name: String(identity?.name || ''),
    lat: identity?.lat ?? '',
    lon: identity?.lon ?? '',
  }
  meshcoreParamsRoutingDraft.value = {
    multi_acks: routing?.multi_acks ?? '',
    manual_add_only: Boolean(routing?.manual_add_only),
    telemetry_mode_base: Number(telemetryModes?.base || 0),
    telemetry_mode_loc: Number(telemetryModes?.location || 0),
    telemetry_mode_env: Number(telemetryModes?.environment || 0),
    rx_delay_base: routing?.rx_delay_base ?? '',
    airtime_factor: routing?.airtime_factor ?? '',
    path_hash_mode: Number(routing?.path_hash_mode || 0),
    autoadd_overwrite_oldest: Boolean(routing?.autoadd_overwrite_oldest),
    autoadd_chat: Boolean(routing?.autoadd_chat),
    autoadd_repeater: Boolean(routing?.autoadd_repeater),
    autoadd_room_server: Boolean(routing?.autoadd_room_server),
    autoadd_sensor: Boolean(routing?.autoadd_sensor),
    autoadd_max_hops: routing?.autoadd_max_hops ?? '',
  }
  meshcoreParamsSecurityDraft.value = {
    ble_pin: security?.ble_pin ?? '',
  }
  meshcoreParamsRegionGpsDraft.value = {
    gps_enabled: Boolean(regionGps?.gps_enabled),
    gps_interval: regionGps?.gps_interval ?? '',
    advert_loc_policy: Number(regionGps?.advert_loc_policy || 0),
  }
}

async function loadMeshcoreParams({ silent = false } = {}) {
  const config = buildNodeCompanionConfig()
  if (!config) {
    meshcoreParamsPayload.value = null
    resetMeshcoreParamsDrafts()
    return null
  }
  if (session.connected && !session.collectionsReady) {
    if (!silent) {
      session.setStatus(t('settings.nodeCompanion.meshcoreParams.status.initializingCollections'))
    }
    return null
  }
  if (meshcoreParamsLoading.value) {
    return meshcoreParamsPayload.value
  }
  meshcoreParamsLoading.value = true
  try {
    const data = await session.api('/api/node/meshcore-params', {
      method: 'POST',
      body: JSON.stringify(config),
    })
    session.applySessionSnapshot(data || {})
    meshcoreParamsPayload.value = data?.meshcore_params || null
    populateMeshcoreParamsDrafts(meshcoreParamsPayload.value)
    if (!silent) {
      session.setStatus(t('settings.nodeCompanion.meshcoreParams.status.refreshed'))
    }
    return meshcoreParamsPayload.value
  } catch (error) {
    meshcoreParamsPayload.value = null
    resetMeshcoreParamsDrafts()
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.loadFailed')), true)
    return null
  } finally {
    meshcoreParamsLoading.value = false
  }
}

async function applyMeshcoreParamsGroup(group, patch) {
  const config = buildNodeCompanionConfig()
  if (!config || meshcoreParamsBusyMode.value) {
    return null
  }
  meshcoreParamsBusyMode.value = String(group || '')
  try {
    const data = await session.api('/api/node/meshcore-params/apply', {
      method: 'POST',
      body: JSON.stringify({
        ...config,
        group,
        patch,
      }),
    })
    session.applySessionSnapshot(data || {})
    meshcoreParamsPayload.value = data?.meshcore_params || null
    populateMeshcoreParamsDrafts(meshcoreParamsPayload.value)
    session.setStatus(t('settings.nodeCompanion.meshcoreParams.status.groupApplied', {
      group: activeMeshcoreParamsSection.value?.title || group,
    }))
    return data
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.saveFailed')), true)
    return null
  } finally {
    meshcoreParamsBusyMode.value = ''
  }
}

async function applyMeshcoreRadioParams() {
  const patch = {
    client_repeat: Boolean(meshcoreParamsRadioDraft.value.client_repeat),
    sf: Number(meshcoreParamsRadioDraft.value.sf),
    cr: Number(meshcoreParamsRadioDraft.value.cr),
  }
  setOptionalNumberField(patch, 'freq_mhz', meshcoreParamsRadioDraft.value.freq_mhz)
  setOptionalNumberField(patch, 'bw_khz', meshcoreParamsRadioDraft.value.bw_khz)
  setOptionalNumberField(patch, 'tx_power_dbm', meshcoreParamsRadioDraft.value.tx_power_dbm, { integer: true })
  await applyMeshcoreParamsGroup('radio', patch)
}

async function applyMeshcoreIdentityParams() {
  const patch = {
    name: String(meshcoreParamsIdentityDraft.value.name || '').trim(),
  }
  setOptionalNumberField(patch, 'lat', meshcoreParamsIdentityDraft.value.lat)
  setOptionalNumberField(patch, 'lon', meshcoreParamsIdentityDraft.value.lon)
  await applyMeshcoreParamsGroup('identity', patch)
}

async function applyMeshcoreRoutingParams() {
  const patch = {
    multi_acks: Number(meshcoreParamsRoutingDraft.value.multi_acks),
    manual_add_only: Boolean(meshcoreParamsRoutingDraft.value.manual_add_only),
    telemetry_mode_base: Number(meshcoreParamsRoutingDraft.value.telemetry_mode_base),
    telemetry_mode_loc: Number(meshcoreParamsRoutingDraft.value.telemetry_mode_loc),
    telemetry_mode_env: Number(meshcoreParamsRoutingDraft.value.telemetry_mode_env),
    path_hash_mode: Number(meshcoreParamsRoutingDraft.value.path_hash_mode),
    autoadd_overwrite_oldest: Boolean(meshcoreParamsRoutingDraft.value.autoadd_overwrite_oldest),
    autoadd_chat: Boolean(meshcoreParamsRoutingDraft.value.autoadd_chat),
    autoadd_repeater: Boolean(meshcoreParamsRoutingDraft.value.autoadd_repeater),
    autoadd_room_server: Boolean(meshcoreParamsRoutingDraft.value.autoadd_room_server),
    autoadd_sensor: Boolean(meshcoreParamsRoutingDraft.value.autoadd_sensor),
  }
  setOptionalNumberField(patch, 'rx_delay_base', meshcoreParamsRoutingDraft.value.rx_delay_base)
  setOptionalNumberField(patch, 'airtime_factor', meshcoreParamsRoutingDraft.value.airtime_factor)
  setOptionalNumberField(patch, 'autoadd_max_hops', meshcoreParamsRoutingDraft.value.autoadd_max_hops, { integer: true })
  await applyMeshcoreParamsGroup('routing', patch)
}

async function applyMeshcoreSecurityParams() {
  const patch = {}
  setOptionalNumberField(patch, 'ble_pin', meshcoreParamsSecurityDraft.value.ble_pin, { integer: true })
  await applyMeshcoreParamsGroup('security', patch)
}

async function applyMeshcoreRegionGpsParams() {
  const patch = {
    gps_enabled: Boolean(meshcoreParamsRegionGpsDraft.value.gps_enabled),
    advert_loc_policy: Number(meshcoreParamsRegionGpsDraft.value.advert_loc_policy || 0),
  }
  setOptionalNumberField(patch, 'gps_interval', meshcoreParamsRegionGpsDraft.value.gps_interval, { integer: true })
  await applyMeshcoreParamsGroup('region-gps', patch)
}

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
    || resolveSavedConnectionPort(profile)
    || ''
  ).trim()
}

function resolveSavedConnectionPort(profile) {
  return String(profile?.connection?.transport_id || profile?.transport_id || profile?.port || '').trim()
}

function resolveSavedConnectionBaudrate(profile) {
  return Number(profile?.connection?.baudrate || profile?.baudrate || session.DEFAULT_BAUDRATE) || session.DEFAULT_BAUDRATE
}

async function updateNodeCompanionClientSettings(patch = {}, successMessage = '') {
  try {
    await session.updateClientSettings(patch)
    if (successMessage) {
      session.setStatus(successMessage)
    }
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.saveFailed')), true)
  }
}

function updateSelectedPort(value) {
  session.selectedPort = String(value || '')
}

function updateSelectedBaudrate(value) {
  session.selectedBaudrate = Number(value || session.DEFAULT_BAUDRATE) || session.DEFAULT_BAUDRATE
}

function updateAutoConnectOnServiceStart(value) {
  void updateNodeCompanionClientSettings({
    auto_connect_on_service_start: Boolean(value),
  })
}

function updateStartupUseLastSuccessful(value) {
  const nextValue = Boolean(value)
  const patch = {
    startup_use_last_successful: nextValue,
  }
  if (nextValue) {
    patch.startup_connection_key = ''
  }
  void updateNodeCompanionClientSettings(patch)
}

function updateAccessAllMeshcoriumContacts(value) {
  void (async () => {
    try {
      await session.updateClientSettings({
        access_all_meshcorium_contacts: Boolean(value),
      })
      await session.loadContacts({ refresh: false }).catch(() => {})
      await session.loadUnreadSummary({
        port: String(session.selectedPort || ''),
        mentionName: String(session.selfName || ''),
      }).catch(() => {})
    } catch (error) {
      session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.saveFailed')), true)
    }
  })()
}

function updateStartupConnectionKey(value) {
  void updateNodeCompanionClientSettings({
    startup_use_last_successful: false,
    startup_connection_key: String(value || ''),
  })
}

function updateRegularNotificationSoundFile(value) {
  void updateNodeCompanionClientSettings({
    notification_regular_sound_file: String(value || ''),
  })
}

function updateMentionNotificationSoundFile(value) {
  void updateNodeCompanionClientSettings({
    notification_mention_sound_file: String(value || ''),
  })
}

function updateDirectNotificationSoundFile(value) {
  void updateNodeCompanionClientSettings({
    notification_direct_sound_file: String(value || ''),
  })
}

function setNotificationSoundPreviewPlaying(kind, playing) {
  if (kind === 'regular') {
    regularNotificationSoundPreviewPlaying.value = playing
    return
  }
  if (kind === 'mention') {
    mentionNotificationSoundPreviewPlaying.value = playing
    return
  }
  directNotificationSoundPreviewPlaying.value = playing
}

function getNotificationSoundPreviewFile(kind) {
  if (kind === 'regular') {
    return String(regularNotificationSoundFile.value || '')
  }
  if (kind === 'mention') {
    return String(mentionNotificationSoundFile.value || '')
  }
  return String(directNotificationSoundFile.value || '')
}

function stopNotificationSoundPreview(kind) {
  const audio = soundPreviewAudios[kind]
  soundPreviewAudios[kind] = null
  if (audio) {
    audio.pause()
    audio.currentTime = 0
  }
  setNotificationSoundPreviewPlaying(kind, false)
}

async function playNotificationSoundPreview(kind) {
  const fileName = getNotificationSoundPreviewFile(kind)
  if (!fileName) {
    return
  }
  stopNotificationSoundPreview(kind)
  const audio = new Audio(`/sounds/${encodeURIComponent(fileName)}`)
  soundPreviewAudios[kind] = audio
  setNotificationSoundPreviewPlaying(kind, true)
  const cleanup = () => {
    if (soundPreviewAudios[kind] === audio) {
      soundPreviewAudios[kind] = null
    }
    audio.onended = null
    audio.onerror = null
    audio.onpause = null
    setNotificationSoundPreviewPlaying(kind, false)
  }
  audio.onended = cleanup
  audio.onerror = cleanup
  audio.onpause = cleanup
  try {
    await audio.play()
  } catch {
    cleanup()
  }
}

function updateSignalMetricsRetention(value) {
  const nextValue = Math.max(1, Math.min(365, Number(value || signalMetricsRetentionDays.value) || signalMetricsRetentionDays.value))
  signalMetricsRetentionDraft.value = nextValue
  void updateNodeCompanionClientSettings({
    signal_metrics_retention_days: nextValue,
  })
}

async function refreshNodeCompanionPorts() {
  try {
    await session.refreshPorts()
    session.setStatus(t('settings.status.refreshed'))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.loadFailed')), true)
  }
}

async function saveNodeCompanionAuth() {
  try {
    await session.updateClientSettings({
      auth_enabled: Boolean(nodeCompanionAuthEnabledDraft.value),
      auth_username: String(nodeCompanionAuthUsernameDraft.value || '').trim(),
      auth_password: String(nodeCompanionAuthPasswordDraft.value || ''),
    })
    nodeCompanionAuthPasswordDraft.value = ''
    session.setStatus(t('settings.nodeCompanion.connection.auth.saved'))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.saveFailed')), true)
  }
}

async function logoutNodeCompanionAuthBrowser() {
  try {
    await session.api('/api/auth/logout', {
      method: 'POST',
      body: JSON.stringify({}),
    })
    window.location.href = '/login'
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.saveFailed')), true)
  }
}

function selectSavedConnectionStartupProfile(profile) {
  session.selectedPort = resolveSavedConnectionPort(profile)
  session.selectedBaudrate = resolveSavedConnectionBaudrate(profile)
  void updateNodeCompanionClientSettings({
    startup_use_last_successful: false,
    startup_connection_key: String(profile?.key || ''),
  }, t('settings.nodeCompanion.connection.history.selected', {
    label: resolveSavedConnectionDisplayName(profile),
  }))
}

function stopNodeCompanionListener({ silent = false } = {}) {
  if (nodeCompanionListenerSource.value) {
    nodeCompanionListenerSource.value.close()
    nodeCompanionListenerSource.value = null
  }
  if (!silent) {
    session.setStatus(t('settings.nodeCompanion.status.listenerStopped'))
  }
}

function startNodeCompanionListener() {
  const config = buildNodeCompanionConfig()
  if (!config) {
    return
  }
  stopNodeCompanionListener({ silent: true })
  const query = new URLSearchParams({
    port: String(config.port),
    baudrate: String(config.baudrate),
    timeout: String(config.timeout),
  })
  const source = new EventSource(`/api/events?${query.toString()}`)
  nodeCompanionListenerSource.value = source
  source.onopen = () => {
    session.setStatus(t('messages.status.listenerActive'))
  }
  source.onmessage = async (event) => {
    let payload = {}
    try {
      payload = JSON.parse(String(event.data || '{}'))
    } catch {
      return
    }
    if (payload.event === 'heartbeat') {
      return
    }
    if (payload.event === 'connected') {
      session.applySessionSnapshot({ ...payload, active: true })
      return
    }
    if (payload.event === 'contacts-sync') {
      session.patchSessionSnapshotFields({
        contacts: payload.contacts || [],
        contacts_count: Array.isArray(payload.contacts) ? payload.contacts.length : session.sessionSnapshot?.contacts_count,
        contact_summary: payload.contact_summary || null,
        recent_repeaters_count: payload.recent_repeaters_count,
      })
      return
    }
    if (payload.event === 'client-settings') {
      session.applyClientSettingsPayload({
        ...(session.settingsPayload || {}),
        settings: payload.settings || {},
      })
      return
    }
    if (payload.event === 'radio-stats') {
      session.patchSessionSnapshotFields({
        radio_stats: payload.radio_stats || null,
        recent_repeaters_count: payload.recent_repeaters_count,
      })
      return
    }
    if (payload.event === 'queue-state') {
      session.patchSessionSnapshotFields({
        queue_state: payload.queue_state || null,
      })
      return
    }
    if (payload.event === 'message') {
      if (payload.recent_repeaters_count != null) {
        session.patchSessionSnapshotFields({
          recent_repeaters_count: payload.recent_repeaters_count,
        })
      }
      return
    }
    if (payload.event === 'raw-advert') {
      if (payload.recent_repeaters_count != null) {
        session.patchSessionSnapshotFields({
          recent_repeaters_count: payload.recent_repeaters_count,
        })
      }
      return
    }
    if (payload.event === 'channel-relayed') {
      if (payload.recent_repeaters_count != null) {
        session.patchSessionSnapshotFields({
          recent_repeaters_count: payload.recent_repeaters_count,
        })
      }
      return
    }
    if (payload.event === 'disconnected') {
      session.patchSessionSnapshotFields({
        active: false,
        queue_state: payload.queue_state || null,
      })
      session.setStatus(t('messages.status.listenerUnavailable'), true)
      stopNodeCompanionListener({ silent: true })
      return
    }
    if (payload.event === 'error' && !payload.auto_reconnect) {
      session.setStatus(String(payload.message || t('messages.status.listenerUnavailable')), true)
    }
  }
  source.onerror = () => {
    if (session.connected) {
      session.setStatus(t('messages.status.listenerReconnecting'))
      return
    }
    session.setStatus(t('messages.status.listenerUnavailable'))
  }
}

function toggleNodeCompanionListener() {
  if (nodeCompanionListenerActive.value) {
    stopNodeCompanionListener()
    return
  }
  startNodeCompanionListener()
}

async function saveNodeCompanionName() {
  const config = buildNodeCompanionConfig()
  if (!config || nodeCompanionSaving.value) {
    return
  }
  if (session.connected && !session.collectionsReady) {
    session.setStatus(t('settings.nodeCompanion.meshcoreParams.status.initializingCollections'))
    return
  }
  const nextName = String(nodeCompanionNameDraft.value || '').trim()
  if (!nextName) {
    session.setStatus(t('settings.nodeCompanion.status.nameRequired'), true)
    return
  }
  if (new TextEncoder().encode(nextName).length > 32) {
    session.setStatus(t('settings.nodeCompanion.status.nameTooLong'), true)
    return
  }
  nodeCompanionSaving.value = true
  try {
    const data = await session.api('/api/node/name', {
      method: 'POST',
      body: JSON.stringify({
        ...config,
        name: nextName,
      }),
    })
    session.applySessionSnapshot(data || {})
    nodeCompanionNameDraft.value = String(data?.self?.name || nextName).trim()
    session.setStatus(t('settings.nodeCompanion.status.nameUpdated', {
      name: data?.self?.name || nextName,
    }))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.saveFailed')), true)
  } finally {
    nodeCompanionSaving.value = false
  }
}

async function syncNodeCompanionTime() {
  const config = buildNodeCompanionConfig()
  if (!config || nodeCompanionSyncingTime.value) {
    return
  }
  if (session.connected && !session.collectionsReady) {
    session.setStatus(t('settings.nodeCompanion.meshcoreParams.status.initializingCollections'))
    return
  }
  nodeCompanionSyncingTime.value = true
  try {
    const data = await session.api('/api/time/sync', {
      method: 'POST',
      body: JSON.stringify(config),
    })
    await session.syncSessionState({ light: true }).catch(() => {})
    const afterValue = String(data?.after_utc || data?.after || '').trim()
    session.setStatus(t('settings.nodeCompanion.status.timeSynced', {
      after: afterValue || t('common.na'),
    }))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.loadFailed')), true)
  } finally {
    nodeCompanionSyncingTime.value = false
  }
}

async function sendNodeCompanionAdvert() {
  return sendNodeCompanionAdvertWithMode(false)
}

async function sendNodeCompanionFloodAdvert() {
  return sendNodeCompanionAdvertWithMode(true)
}

async function sendNodeCompanionAdvertWithMode(flood = false) {
  const config = buildNodeCompanionConfig()
  if (!config || nodeCompanionSendingAdvert.value) {
    return
  }
  if (session.connected && !session.collectionsReady) {
    session.setStatus(t('settings.nodeCompanion.meshcoreParams.status.initializingCollections'))
    return
  }
  nodeCompanionSendingAdvert.value = true
  try {
    await session.api('/api/advert', {
      method: 'POST',
      body: JSON.stringify({
        ...config,
        flood: Boolean(flood),
      }),
    })
    session.setStatus(t(flood ? 'advert.status.floodSent' : 'advert.status.directSent'))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('advert.status.failed')), true)
  } finally {
    nodeCompanionSendingAdvert.value = false
  }
}

async function refreshNodeCompanionContacts() {
  const config = buildNodeCompanionConfig()
  if (!config || nodeCompanionRefreshingContacts.value) {
    return
  }
  if (session.connected && !session.collectionsReady) {
    session.setStatus(t('settings.nodeCompanion.meshcoreParams.status.initializingCollections'))
    return
  }
  nodeCompanionRefreshingContacts.value = true
  try {
    const contacts = await session.loadContacts({ refresh: true })
    session.setStatus(t('settings.nodeCompanion.status.contactsRefreshed', {
      total: Array.isArray(contacts) ? contacts.length : 0,
    }))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.loadFailed')), true)
  } finally {
    nodeCompanionRefreshingContacts.value = false
  }
}

const signalMetricsRetentionDays = computed(() => {
  return Math.max(1, Math.min(365, Number(session.settingsPayload?.settings?.signal_metrics_retention_days || 7) || 7))
})

const signalMetricsPollSeconds = computed(() => {
  return Math.max(5, Math.min(120, Number(session.settingsPayload?.settings?.signal_metrics_poll_seconds || 15) || 15))
})

const signalMetricsRangeOptions = computed(() => {
  return [60, 300, 600, 1800, 3600, 10800, 21600, 43200, 86400, 604800, 2592000].map((value) => ({
    value,
    label: formatSignalMetricsRangeLabel(value),
    disabled: value > (signalMetricsRetentionDays.value * 86400),
  }))
})

const signalMetricsHasVisibleSeries = computed(() => {
  return Boolean(signalMetricsShowSnr.value || signalMetricsShowNoise.value || signalMetricsShowRepeaters.value)
})

const signalMetricsNormalizedPayload = computed(() => {
  const source = signalMetricsPayload.value
  if (!source || typeof source !== 'object') {
    return null
  }
  const points = Array.isArray(source.points)
    ? source.points.map((point) => ({ ...point }))
    : []
  const repeaterValues = points
    .filter((point) => point?.repeaters != null && !Number.isNaN(Number(point.repeaters)))
    .map((point) => Number(point.repeaters))
  const hasRepeaterHistory = repeaterValues.some((value) => value > 0)
  const currentRecentRepeaterCount = Math.max(0, Number(session.recentRepeaterCount || 0))
  if (!hasRepeaterHistory && currentRecentRepeaterCount > 0) {
    if (points.length) {
      points[points.length - 1] = {
        ...points[points.length - 1],
        repeaters: currentRecentRepeaterCount,
      }
    } else {
      points.push({
        ts: Math.floor(Date.now() / 1000),
        snr: null,
        noise_floor: null,
        repeaters: currentRecentRepeaterCount,
      })
    }
  }
  const normalizedRepeaterValues = points
    .filter((point) => point?.repeaters != null && !Number.isNaN(Number(point.repeaters)))
    .map((point) => Number(point.repeaters))
  const latestRepeaterPoint = [...points].reverse().find((point) => point?.repeaters != null && !Number.isNaN(Number(point.repeaters)))
  return {
    ...source,
    points,
    repeaters_latest_value: latestRepeaterPoint?.repeaters ?? null,
    repeaters_min_value: normalizedRepeaterValues.length ? +Math.min(...normalizedRepeaterValues).toFixed(2) : null,
    repeaters_max_value: normalizedRepeaterValues.length ? +Math.max(...normalizedRepeaterValues).toFixed(2) : null,
    repeaters_avg_value: normalizedRepeaterValues.length
      ? +(normalizedRepeaterValues.reduce((sum, value) => sum + value, 0) / normalizedRepeaterValues.length).toFixed(2)
      : null,
  }
})

const signalMetricsPoints = computed(() => {
  return Array.isArray(signalMetricsNormalizedPayload.value?.points) ? signalMetricsNormalizedPayload.value.points : []
})

const signalMetricsSummary = computed(() => signalMetricsNormalizedPayload.value || {})

const signalMetricsHoverPoint = computed(() => {
  const points = signalMetricsPoints.value
  const index = Number(signalMetricsHoverIndex.value || -1)
  return index >= 0 && index < points.length ? points[index] : null
})

function signalMetricUnit(metric) {
  if (metric === 'noise_floor') {
    return 'dBm'
  }
  if (metric === 'repeaters') {
    return t('settings.nodeCompanion.signalMetrics.units.repeaters')
  }
  return 'dB'
}

function formatSignalMetricValue(metric, value) {
  if (value == null || Number.isNaN(Number(value))) {
    return t('common.na')
  }
  return `${Number(value).toFixed(2)} ${signalMetricUnit(metric)}`
}

function formatSignalMetricBucketLabel(epoch, bucketSecs) {
  const locale = String(activeLocale.value || 'en').toLowerCase().startsWith('ru') ? 'ru-RU' : 'en-US'
  const date = new Date(Number(epoch || 0) * 1000)
  if (Number(bucketSecs || 0) >= 86400) {
    return date.toLocaleDateString(locale, { day: '2-digit', month: '2-digit' })
  }
  return date.toLocaleTimeString(locale, {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatSignalMetricsRangeLabel(rangeSeconds) {
  const seconds = Math.max(60, Number(rangeSeconds || 0))
  if (seconds < 3600) {
    return t('settings.nodeCompanion.signalMetrics.range.minutes', { count: Math.round(seconds / 60) })
  }
  if (seconds < 86400) {
    return t('settings.nodeCompanion.signalMetrics.range.hours', { count: Math.round(seconds / 3600) })
  }
  if (seconds < 2592000) {
    const days = Math.round(seconds / 86400)
    if (days === 7) {
      return t('settings.nodeCompanion.signalMetrics.range.week')
    }
    return t('settings.nodeCompanion.signalMetrics.range.days', { count: days })
  }
  return t('settings.nodeCompanion.signalMetrics.range.month')
}

function getSignalMetricsStrokeWidths() {
  const normalized = Math.max(1, Math.min(100, Number(signalMetricsLineWeight.value || 50)))
  const ratio = (normalized - 1) / 99
  return {
    line: +(1.1 + (ratio * 2.3)).toFixed(2),
    grid: +(0.4 + (ratio * 0.8)).toFixed(2),
    dot: +(2.6 + (ratio * 2.4)).toFixed(2),
  }
}

function buildSignalMetricsSvg(points, options = {}) {
  const showSnr = options.showSnr !== false
  const showNoise = options.showNoise !== false
  const showRepeaters = options.showRepeaters === true
  const bucketSecs = Number(options.bucketSecs || 3600)
  const width = 720
  const height = 300
  const padLeft = 52
  const padRight = 52
  const padTop = 18
  const padBottom = 34
  const innerWidth = width - padLeft - padRight
  const innerHeight = height - padTop - padBottom
  const xStep = points.length > 1 ? innerWidth / (points.length - 1) : 0
  const stroke = getSignalMetricsStrokeWidths()
  const snrValues = points.filter((point) => point.snr != null).map((point) => Number(point.snr))
  const noiseValues = points.filter((point) => point.noise_floor != null).map((point) => Number(point.noise_floor))
  const repeaterValues = points.filter((point) => point.repeaters != null).map((point) => Number(point.repeaters))
  const snrMin = snrValues.length ? Math.min(...snrValues) : -1
  const snrMax = snrValues.length ? Math.max(...snrValues) : 1
  const noiseMin = noiseValues.length ? Math.min(...noiseValues) : -120
  const noiseMax = noiseValues.length ? Math.max(...noiseValues) : -80
  const repeatersMin = repeaterValues.length ? Math.min(...repeaterValues) : 0
  const repeatersMax = repeaterValues.length ? Math.max(...repeaterValues) : 1
  const snrDomainMin = snrMin === snrMax ? snrMin - 1 : snrMin
  const snrDomainMax = snrMin === snrMax ? snrMax + 1 : snrMax
  const noiseDomainMin = noiseMin === noiseMax ? noiseMin - 1 : noiseMin
  const noiseDomainMax = noiseMin === noiseMax ? noiseMax + 1 : noiseMax
  const repeatersDomainMin = repeatersMin === repeatersMax ? Math.max(0, repeatersMin - 1) : Math.max(0, repeatersMin)
  const repeatersDomainMax = repeatersMin === repeatersMax ? repeatersMax + 1 : repeatersMax
  const yFor = (value, min, max) => {
    const ratio = (Number(value) - min) / Math.max(0.0001, (max - min))
    return padTop + innerHeight - (ratio * innerHeight)
  }
  const buildSeriesPath = (seriesKey, min, max) => {
    let started = false
    return points.map((point, index) => {
      const value = point[seriesKey]
      if (value == null) {
        started = false
        return ''
      }
      const x = padLeft + (xStep * index)
      const y = yFor(value, min, max)
      const prefix = started ? 'L' : 'M'
      started = true
      return `${prefix} ${x.toFixed(2)} ${y.toFixed(2)}`
    }).filter(Boolean).join(' ')
  }
  const snrPath = buildSeriesPath('snr', snrDomainMin, snrDomainMax)
  const noisePath = buildSeriesPath('noise_floor', noiseDomainMin, noiseDomainMax)
  const repeatersPath = buildSeriesPath('repeaters', repeatersDomainMin, repeatersDomainMax)
  const leftAxisMode = showSnr ? 'snr' : (showRepeaters ? 'repeaters' : null)
  const rightAxisMode = showNoise ? 'noise_floor' : (!showSnr && showRepeaters ? 'repeaters' : null)
  const grid = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const y = padTop + (innerHeight * ratio)
    const snrLabel = snrDomainMax - ((snrDomainMax - snrDomainMin) * ratio)
    const noiseLabel = noiseDomainMax - ((noiseDomainMax - noiseDomainMin) * ratio)
    const repeatersLabel = repeatersDomainMax - ((repeatersDomainMax - repeatersDomainMin) * ratio)
    return `
      <line x1="${padLeft}" y1="${y.toFixed(2)}" x2="${width - padRight}" y2="${y.toFixed(2)}" stroke="rgba(255,255,255,0.07)" stroke-width="${stroke.grid}" stroke-dasharray="4 6" shape-rendering="crispEdges" />
      ${leftAxisMode === 'snr' ? `<text x="${padLeft - 8}" y="${(y + 4).toFixed(2)}" text-anchor="end" fill="rgba(240,203,114,0.82)" font-size="11">${escapeHtml(Number(snrLabel).toFixed(1))}</text>` : ''}
      ${leftAxisMode === 'repeaters' ? `<text x="${padLeft - 8}" y="${(y + 4).toFixed(2)}" text-anchor="end" fill="rgba(125,211,160,0.9)" font-size="11">${escapeHtml(Number(repeatersLabel).toFixed(1))}</text>` : ''}
      ${rightAxisMode === 'noise_floor' ? `<text x="${width - padRight + 8}" y="${(y + 4).toFixed(2)}" text-anchor="start" fill="rgba(240,113,120,0.82)" font-size="11">${escapeHtml(Number(noiseLabel).toFixed(1))}</text>` : ''}
      ${rightAxisMode === 'repeaters' ? `<text x="${width - padRight + 8}" y="${(y + 4).toFixed(2)}" text-anchor="start" fill="rgba(125,211,160,0.9)" font-size="11">${escapeHtml(Number(repeatersLabel).toFixed(1))}</text>` : ''}
    `
  }).join('')
  const labelIndexes = (() => {
    if (points.length <= 1) {
      return [0]
    }
    if (points.length <= 4) {
      return points.map((_, index) => index)
    }
    const targetCount = points.length >= 10 ? 3 : 4
    const step = (points.length - 1) / Math.max(1, targetCount - 1)
    const indexes = new Set([0, points.length - 1])
    for (let markerIndex = 1; markerIndex < targetCount - 1; markerIndex += 1) {
      indexes.add(Math.round(step * markerIndex))
    }
    return [...indexes].sort((left, right) => left - right)
  })()
  const labels = labelIndexes.map((pointIndex) => {
    const point = points[pointIndex]
    const x = padLeft + (xStep * pointIndex)
    return `<text x="${x.toFixed(2)}" y="${height - 11}" text-anchor="middle" fill="rgba(224,232,243,0.68)" font-size="10">${escapeHtml(formatSignalMetricBucketLabel(point.ts, bucketSecs))}</text>`
  }).join('')
  const dotSeries = (key, min, max, color) => points.map((point, index) => {
    const value = point[key]
    if (value == null) return ''
    const x = padLeft + (xStep * index)
    const y = yFor(value, min, max)
    return `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${stroke.dot}" fill="${color}"></circle>`
  }).join('')
  const hoverIndex = Number(signalMetricsHoverIndex.value || -1)
  const hoverPoint = hoverIndex >= 0 && hoverIndex < points.length ? points[hoverIndex] : null
  const hoverSvg = hoverPoint ? (() => {
    const x = padLeft + (xStep * hoverIndex)
    const hoverSnr = showSnr && hoverPoint.snr != null
      ? `<circle cx="${x.toFixed(2)}" cy="${yFor(hoverPoint.snr, snrDomainMin, snrDomainMax).toFixed(2)}" r="${(stroke.dot + 1.2).toFixed(2)}" fill="#f0cb72" stroke="rgba(10,16,24,0.84)" stroke-width="2" />`
      : ''
    const hoverNoise = showNoise && hoverPoint.noise_floor != null
      ? `<circle cx="${x.toFixed(2)}" cy="${yFor(hoverPoint.noise_floor, noiseDomainMin, noiseDomainMax).toFixed(2)}" r="${(stroke.dot + 1.2).toFixed(2)}" fill="#f07178" stroke="rgba(10,16,24,0.84)" stroke-width="2" />`
      : ''
    const hoverRepeaters = showRepeaters && hoverPoint.repeaters != null
      ? `<circle cx="${x.toFixed(2)}" cy="${yFor(hoverPoint.repeaters, repeatersDomainMin, repeatersDomainMax).toFixed(2)}" r="${(stroke.dot + 1.2).toFixed(2)}" fill="#7dd3a0" stroke="rgba(10,16,24,0.84)" stroke-width="2" />`
      : ''
    return `
      <line x1="${x.toFixed(2)}" y1="${padTop}" x2="${x.toFixed(2)}" y2="${height - padBottom}" stroke="rgba(255,255,255,0.22)" stroke-width="1" stroke-dasharray="3 5" />
      ${hoverSnr}
      ${hoverNoise}
      ${hoverRepeaters}
    `
  })() : ''
  return `
    <svg class="mc-settings-signal-metrics-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" aria-label="${escapeHtml(t('settings.nodeCompanion.sections.signalMetrics.title'))}">
      ${grid}
      ${showSnr && snrPath ? `<path d="${snrPath}" fill="none" stroke="#f0cb72" stroke-width="${stroke.line}" stroke-linejoin="round" stroke-linecap="round" />` : ''}
      ${showNoise && noisePath ? `<path d="${noisePath}" fill="none" stroke="#f07178" stroke-width="${stroke.line}" stroke-linejoin="round" stroke-linecap="round" />` : ''}
      ${showRepeaters && repeatersPath ? `<path d="${repeatersPath}" fill="none" stroke="#7dd3a0" stroke-width="${stroke.line}" stroke-linejoin="round" stroke-linecap="round" />` : ''}
      ${showSnr ? dotSeries('snr', snrDomainMin, snrDomainMax, '#f0cb72') : ''}
      ${showNoise ? dotSeries('noise_floor', noiseDomainMin, noiseDomainMax, '#f07178') : ''}
      ${showRepeaters ? dotSeries('repeaters', repeatersDomainMin, repeatersDomainMax, '#7dd3a0') : ''}
      ${hoverSvg}
      ${labels}
    </svg>
  `
}

const signalMetricsHoverText = computed(() => {
  const point = signalMetricsHoverPoint.value
  if (!point) {
    return ''
  }
  const summary = signalMetricsSummary.value
  const parts = []
  if (signalMetricsShowSnr.value && point?.snr != null) {
    parts.push(`${t('settings.nodeCompanion.signalMetrics.series.snr')} ${formatSignalMetricValue('snr', point.snr)}`)
  }
  if (signalMetricsShowNoise.value && point?.noise_floor != null) {
    parts.push(`${t('settings.nodeCompanion.signalMetrics.series.noise')} ${formatSignalMetricValue('noise_floor', point.noise_floor)}`)
  }
  if (signalMetricsShowRepeaters.value && point?.repeaters != null) {
    parts.push(`${t('settings.nodeCompanion.signalMetrics.series.repeaters')} ${formatSignalMetricValue('repeaters', point.repeaters)}`)
  }
  return `${formatSignalMetricBucketLabel(point.ts, Number(summary.bucket_secs || 3600))}: ${parts.join(' · ')}`
})

const signalMetricsChartMarkup = computed(() => {
  const points = signalMetricsPoints.value
  const summary = signalMetricsSummary.value
  const hasVisibleData = points.some((point) => (
    (signalMetricsShowSnr.value && point?.snr != null)
    || (signalMetricsShowNoise.value && point?.noise_floor != null)
    || (signalMetricsShowRepeaters.value && point?.repeaters != null)
  ))
  if (!signalMetricsHasVisibleSeries.value) {
    return ''
  }
  if (!points.length || !hasVisibleData) {
    return ''
  }
  return buildSignalMetricsSvg(points, {
    showSnr: signalMetricsShowSnr.value,
    showNoise: signalMetricsShowNoise.value,
    showRepeaters: signalMetricsShowRepeaters.value,
    bucketSecs: Number(summary.bucket_secs || 3600),
  })
})

const signalMetricsSummaryItems = computed(() => {
  const summary = signalMetricsSummary.value
  return [
    `${t('settings.nodeCompanion.signalMetrics.summary.period')}: ${formatSignalMetricsRangeLabel(signalMetricsRangeSeconds.value)}`,
    `${t('settings.nodeCompanion.signalMetrics.summary.points')}: ${signalMetricsPoints.value.length}`,
    signalMetricsShowSnr.value ? `${t('settings.nodeCompanion.signalMetrics.summary.snrLatest')}: ${formatSignalMetricValue('snr', summary.snr_latest_value)}` : '',
    signalMetricsShowSnr.value ? `${t('settings.nodeCompanion.signalMetrics.summary.snrAvg')}: ${formatSignalMetricValue('snr', summary.snr_avg_value)}` : '',
    signalMetricsShowSnr.value ? `${t('settings.nodeCompanion.signalMetrics.summary.snrMin')}: ${formatSignalMetricValue('snr', summary.snr_min_value)}` : '',
    signalMetricsShowSnr.value ? `${t('settings.nodeCompanion.signalMetrics.summary.snrMax')}: ${formatSignalMetricValue('snr', summary.snr_max_value)}` : '',
    signalMetricsShowNoise.value ? `${t('settings.nodeCompanion.signalMetrics.summary.noiseLatest')}: ${formatSignalMetricValue('noise_floor', summary.noise_latest_value)}` : '',
    signalMetricsShowNoise.value ? `${t('settings.nodeCompanion.signalMetrics.summary.noiseAvg')}: ${formatSignalMetricValue('noise_floor', summary.noise_avg_value)}` : '',
    signalMetricsShowNoise.value ? `${t('settings.nodeCompanion.signalMetrics.summary.noiseMin')}: ${formatSignalMetricValue('noise_floor', summary.noise_min_value)}` : '',
    signalMetricsShowNoise.value ? `${t('settings.nodeCompanion.signalMetrics.summary.noiseMax')}: ${formatSignalMetricValue('noise_floor', summary.noise_max_value)}` : '',
    signalMetricsShowRepeaters.value ? `${t('settings.nodeCompanion.signalMetrics.summary.repeatersLatest')}: ${formatSignalMetricValue('repeaters', summary.repeaters_latest_value)}` : '',
    signalMetricsShowRepeaters.value ? `${t('settings.nodeCompanion.signalMetrics.summary.repeatersAvg')}: ${formatSignalMetricValue('repeaters', summary.repeaters_avg_value)}` : '',
    signalMetricsShowRepeaters.value ? `${t('settings.nodeCompanion.signalMetrics.summary.repeatersMin')}: ${formatSignalMetricValue('repeaters', summary.repeaters_min_value)}` : '',
    signalMetricsShowRepeaters.value ? `${t('settings.nodeCompanion.signalMetrics.summary.repeatersMax')}: ${formatSignalMetricValue('repeaters', summary.repeaters_max_value)}` : '',
  ].filter(Boolean)
})

async function loadSignalMetricsPayload(options = {}) {
  const showLoadingState = options.quiet !== true || !signalMetricsPayload.value
  if (showLoadingState) {
    signalMetricsLoading.value = true
  }
  try {
    const params = new URLSearchParams({
      range_seconds: String(Math.min(
        Math.max(60, Number(signalMetricsRangeSeconds.value || 86400) || 86400),
        signalMetricsRetentionDays.value * 86400,
      )),
    })
    if (session.selectedPort) {
      params.set('port', String(session.selectedPort))
    }
    const data = await session.api(`/api/signal-metrics?${params.toString()}`)
    signalMetricsPayload.value = data || null
    signalMetricsRangeSeconds.value = Number(data?.range_seconds || signalMetricsRangeSeconds.value || 86400)
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.loadFailed')), true)
  } finally {
    if (showLoadingState) {
      signalMetricsLoading.value = false
    }
  }
}

async function applySignalMetricsSettings() {
  try {
    await session.updateClientSettings({
      signal_metrics_poll_seconds: Math.max(5, Math.min(120, Number(signalMetricsPollDraft.value || signalMetricsPollSeconds.value) || signalMetricsPollSeconds.value)),
      signal_metrics_retention_days: Math.max(1, Math.min(365, Number(signalMetricsRetentionDraft.value || signalMetricsRetentionDays.value) || signalMetricsRetentionDays.value)),
    })
    await loadSignalMetricsPayload()
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.saveFailed')), true)
  }
}

function clearSignalMetricsLiveTimer() {
  if (signalMetricsLiveTimer != null) {
    window.clearInterval(signalMetricsLiveTimer)
    signalMetricsLiveTimer = null
  }
}

function ensureSignalMetricsLiveTimer() {
  clearSignalMetricsLiveTimer()
  if (
    visibility.value !== 'visible'
    || !isNodeCompanionSettingsMode.value
    || activeNodeCompanionSectionId.value !== 'signal-metrics'
  ) {
    return
  }
  const intervalMs = Math.max(3000, signalMetricsPollSeconds.value * 1000)
  signalMetricsLiveTimer = window.setInterval(() => {
    if (!signalMetricsLoading.value) {
      loadSignalMetricsPayload({ quiet: true }).catch(() => {})
    }
  }, intervalMs)
}

function syncSignalMetricsHoverFromEvent(event) {
  const chart = event?.currentTarget
  const points = signalMetricsPoints.value
  if (!chart || !points.length) {
    return
  }
  const rect = chart.getBoundingClientRect()
  if (!rect.width) {
    return
  }
  const relativeX = Math.max(0, Math.min(rect.width, Number(event.clientX || 0) - rect.left))
  const index = points.length <= 1
    ? 0
    : Math.max(0, Math.min(points.length - 1, Math.round((relativeX / rect.width) * (points.length - 1))))
  signalMetricsHoverIndex.value = index
}

function clearSignalMetricsHover() {
  signalMetricsHoverIndex.value = -1
}

function updateSignalMetricsRange(value) {
  signalMetricsRangeSeconds.value = Number(value || 86400)
  signalMetricsHoverIndex.value = -1
  void loadSignalMetricsPayload()
}

function updateSignalMetricsPollDraft(value) {
  signalMetricsPollDraft.value = Number(value || 15)
}

async function loadContactDebugPayload() {
  if (!session.connected || !session.selectedPort) {
    contactDebugPayload.value = null
    return null
  }
  contactDebugLoading.value = true
  try {
    const params = new URLSearchParams({
      port: String(session.selectedPort || ''),
    })
    const data = await session.api(`/api/contact-debug?${params.toString()}`)
    contactDebugPayload.value = data || null
    return data
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || t('settings.status.loadFailed'))
    session.setStatus(message, true)
    throw error
  } finally {
    contactDebugLoading.value = false
  }
}

async function loadMessageDebugSummary() {
  if (!session.connected || !session.selectedPort) {
    messageDebugSummary.value = null
    return null
  }
  messageDebugSummaryLoading.value = true
  try {
    const data = await session.api('/api/messages/debug-summary', {
      method: 'POST',
      body: JSON.stringify({
        port: String(session.selectedPort || ''),
        mention_name: String(session.selfName || ''),
      }),
    })
    messageDebugSummary.value = data || null
    return data
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || t('settings.status.loadFailed'))
    session.setStatus(message, true)
    throw error
  } finally {
    messageDebugSummaryLoading.value = false
  }
}

async function setAllMessagesReadState(isRead, scope = 'regular') {
  if (!session.connected || !session.selectedPort) {
    session.setStatus(t('settings.debug.messages.connectionRequired'), true)
    return
  }
  const normalizedScope = String(scope || 'regular')
  const mentionName = String(session.selfName || '')
  const data = await session.api('/api/messages/read-state', {
    method: 'POST',
    body: JSON.stringify({
      port: String(session.selectedPort || ''),
      is_read: Boolean(isRead),
      scope: normalizedScope,
      mention_name: mentionName,
      source: 'settings/debug/messages',
    }),
  })
  await session.loadUnreadSummary({
    port: String(session.selectedPort || ''),
    mentionName,
  })
  await loadMessageDebugSummary().catch(() => {})
  const total = normalizedScope === 'mention'
    ? Number(data.mention_messages || 0) + Number(data.mention_contact_messages || 0)
    : (normalizedScope === 'direct'
        ? Number(data.contact_messages || 0)
        : Number(data.messages || 0) + Number(data.contact_messages || 0))
  const statusKey = normalizedScope === 'mention'
    ? (isRead ? 'notifications.status.markedMentionsRead' : 'notifications.status.markedMentionsUnread')
    : (normalizedScope === 'direct'
        ? (isRead ? 'notifications.status.markedDirectMessagesRead' : 'notifications.status.markedDirectMessagesUnread')
        : (isRead ? 'notifications.status.markedMessagesRead' : 'notifications.status.markedMessagesUnread'))
  session.setStatus(t(statusKey, { total }))
}

function requestSetAllMessagesReadState(isRead, scope = 'regular') {
  const normalizedScope = String(scope || 'regular')
  const actionKey = isRead
    ? 'notifications.actions.markRead'
    : 'notifications.actions.markUnread'
  const confirmKey = normalizedScope === 'mention'
    ? (isRead ? 'notifications.confirm.markMentionsRead' : 'notifications.confirm.markMentionsUnread')
    : (normalizedScope === 'direct'
        ? (isRead ? 'notifications.confirm.markDirectRead' : 'notifications.confirm.markDirectUnread')
        : (isRead ? 'notifications.confirm.markRegularRead' : 'notifications.confirm.markRegularUnread'))
  confirmDialog.value = {
    open: true,
    title: t('common.confirmation'),
    message: t(confirmKey),
    note: '',
    confirmLabel: t(actionKey),
    confirmDisabled: false,
    action: async () => setAllMessagesReadState(isRead, normalizedScope),
  }
}

function closeConfirmDialog() {
  if (clearMessageDbUnlockTimer != null) {
    window.clearInterval(clearMessageDbUnlockTimer)
    clearMessageDbUnlockTimer = null
  }
  confirmDialog.value = {
    open: false,
    title: '',
    message: '',
    note: '',
    confirmLabel: '',
    confirmDisabled: false,
    action: null,
  }
}

async function submitConfirmDialog() {
  if (confirmDialog.value.confirmDisabled) {
    return
  }
  const action = confirmDialog.value.action
  closeConfirmDialog()
  if (typeof action === 'function') {
    await action()
  }
}

const confirmSheetModel = computed(() => {
  return {
    open: confirmDialog.value.open,
    title: confirmDialog.value.title,
    message: confirmDialog.value.message,
    note: confirmDialog.value.note,
    confirmLabel: confirmDialog.value.confirmLabel,
    confirmDisabled: confirmDialog.value.confirmDisabled,
  }
})

function openClearMessageDbDialog() {
  if (!session.selectedPort) {
    session.setStatus(t('settings.meshcorium.clearMessages.portRequired'), true)
    return
  }
  let remaining = 10
  const buildLabel = () => remaining > 0
    ? t('settings.meshcorium.clearMessages.confirmCountdown', { seconds: remaining })
    : t('settings.meshcorium.clearMessages.confirm')
  confirmDialog.value = {
    open: true,
    title: t('settings.meshcorium.clearMessages.dialogTitle'),
    message: t('settings.meshcorium.clearMessages.warning'),
    note: t('settings.meshcorium.clearMessages.note'),
    confirmLabel: buildLabel(),
    confirmDisabled: true,
    action: clearMessageDatabase,
  }
  if (clearMessageDbUnlockTimer != null) {
    window.clearInterval(clearMessageDbUnlockTimer)
  }
  clearMessageDbUnlockTimer = window.setInterval(() => {
    remaining -= 1
    if (remaining <= 0) {
      if (clearMessageDbUnlockTimer != null) {
        window.clearInterval(clearMessageDbUnlockTimer)
        clearMessageDbUnlockTimer = null
      }
      confirmDialog.value = {
        ...confirmDialog.value,
        confirmLabel: t('settings.meshcorium.clearMessages.confirm'),
        confirmDisabled: false,
      }
      return
    }
    confirmDialog.value = {
      ...confirmDialog.value,
      confirmLabel: buildLabel(),
      confirmDisabled: true,
    }
  }, 1000)
}

async function clearMessageDatabase() {
  if (!session.selectedPort) {
    session.setStatus(t('settings.meshcorium.clearMessages.portRequired'), true)
    return
  }
  try {
    const data = await session.api('/api/messages/clear', {
      method: 'POST',
      body: JSON.stringify({
        port: String(session.selectedPort || ''),
      }),
    })
    session.clearUnreadSummary()
    await session.loadUnreadSummary({
      port: String(session.selectedPort || ''),
      mentionName: String(session.selfName || ''),
    }).catch(() => {})
    session.setStatus(t('settings.meshcorium.clearMessages.cleared', {
      total: Number(data?.deleted || 0),
    }))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.meshcorium.clearMessages.failed')), true)
  }
}

function handleSettingsEscape(event) {
  if (event.defaultPrevented || event.key !== 'Escape') {
    return
  }
  if (confirmDialog.value.open) {
    event.preventDefault()
    closeConfirmDialog()
  }
}

const localeDropdownOptions = computed(() => {
  return supportedLocales.value.map((entry) => ({
    value: entry.code,
    label: entry.label,
  }))
})

const wallpaperEntries = computed(() => {
  return Array.isArray(session.settingsPayload?.wallpaper_files) ? session.settingsPayload.wallpaper_files : []
})

const backgroundDropdownOptions = computed(() => {
  const presetOptions = backgroundPresetOptions.map((entry) => ({
    value: entry.value,
    label: t(entry.labelKey),
  }))
  const wallpaperOptions = wallpaperEntries.value.map((entry) => ({
    value: `wallpaper:${String(entry?.name || '').trim()}`,
    label: String(entry?.name || '').trim(),
  })).filter((entry) => entry.label)
  return [...presetOptions, ...wallpaperOptions]
})

const chatBackgroundDropdownOptions = computed(() => {
  const presetOptions = chatBackgroundPresetOptions.map((entry) => ({
    value: entry.value,
    label: t(entry.labelKey),
  }))
  const wallpaperOptions = wallpaperEntries.value.map((entry) => ({
    value: `wallpaper:${String(entry?.name || '').trim()}`,
    label: String(entry?.name || '').trim(),
  })).filter((entry) => entry.label)
  return [...presetOptions, ...wallpaperOptions]
})

const pageBackgroundId = computed(() => {
  return String(session.settingsPayload?.settings?.page_background_id || 'default').trim() || 'default'
})

const chatBackgroundId = computed(() => {
  return String(session.settingsPayload?.settings?.chat_background_id || 'chat-backplane-blue').trim() || 'chat-backplane-blue'
})

const pageBackgroundBlurEnabled = computed(() => {
  return Boolean(session.settingsPayload?.settings?.page_background_blur_enabled)
})

const pageBackgroundBlurPx = computed(() => {
  return Math.max(0, Math.min(32, Number(session.settingsPayload?.settings?.page_background_blur_px || 0) || 0))
})

watch(pageBackgroundBlurPx, (value) => {
  backgroundBlurDraftPx.value = value
}, { immediate: true })

async function updateMeshcoriumSettings(patch) {
  try {
    await session.updateClientSettings(patch)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || t('settings.status.saveFailed'))
    session.setStatus(message, true)
  }
}

const persistBackgroundBlurPx = useDebounceFn((value) => {
  return updateMeshcoriumSettings({
    page_background_blur_px: Number(value),
  })
}, 160)

function updatePageBackgroundId(value) {
  void updateMeshcoriumSettings({
    page_background_id: String(value || 'default'),
  })
}

function updateChatBackgroundId(value) {
  void updateMeshcoriumSettings({
    chat_background_id: String(value || 'chat-backplane-blue'),
  })
}

function updatePageBackgroundBlurEnabled(value) {
  if (typeof document !== 'undefined') {
    document.documentElement.style.setProperty(
      '--mc-page-backdrop-filter',
      value ? `blur(${backgroundBlurDraftPx.value}px)` : 'none',
    )
  }
  void updateMeshcoriumSettings({
    page_background_blur_enabled: Boolean(value),
  })
}

function handleBackgroundBlurInput(event) {
  const value = Math.max(0, Math.min(32, Number(event?.target?.value || 0) || 0))
  backgroundBlurDraftPx.value = value
  if (typeof document !== 'undefined' && pageBackgroundBlurEnabled.value) {
    document.documentElement.style.setProperty('--mc-page-backdrop-filter', `blur(${value}px)`)
  }
  void persistBackgroundBlurPx(value)
}

function openWallpaperPicker() {
  wallpaperFileInput.value?.click?.()
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error || new Error('read failed'))
    reader.onload = () => resolve(String(reader.result || ''))
    reader.readAsDataURL(file)
  })
}

async function handleWallpaperUpload(event) {
  const input = event?.target
  const file = input?.files?.[0]
  if (!file || uploadingWallpaper.value) {
    return
  }
  uploadingWallpaper.value = true
  try {
    const contentBase64 = await readFileAsDataUrl(file)
    const data = await session.api('/api/wallpapers/upload', {
      method: 'POST',
      body: JSON.stringify({
        filename: file.name,
        content_base64: contentBase64,
      }),
    })
    session.applyClientSettingsPayload(data)
    session.setStatus(t('settings.status.wallpaperUploaded', {
      name: data?.uploaded_wallpaper?.name || file.name,
    }))
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || t('settings.status.wallpaperUploadFailed'))
    session.setStatus(message, true)
  } finally {
    uploadingWallpaper.value = false
    if (input) {
      input.value = ''
    }
  }
}

const aboutLinkGroups = computed(() => {
  return [
    {
      id: 'references',
      title: t('settings.about.groups.references.title'),
      subtitle: t('settings.about.groups.references.subtitle'),
      entries: [
        {
          name: 'MeshCore',
          version: 'firmware upstream',
          packageUrl: 'https://github.com/ripplebiz/MeshCore',
          packageLabel: t('settings.about.actions.home'),
          repoUrl: 'https://github.com/ripplebiz/MeshCore',
        },
        {
          name: 'meshcore-web',
          version: 'reference client',
          packageUrl: 'https://github.com/liamcottle/meshcore-web',
          packageLabel: t('settings.about.actions.home'),
          repoUrl: 'https://github.com/liamcottle/meshcore-web',
        },
        {
          name: 'meshcore_py',
          version: '2.3.1',
          packageUrl: 'https://pypi.org/project/meshcore/',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/fdlamotte/meshcore_py',
        },
      ],
    },
    {
      id: 'python',
      title: t('settings.about.groups.python.title'),
      subtitle: t('settings.about.groups.python.subtitle'),
      entries: [
        {
          name: 'pyserial',
          version: '3.5',
          packageUrl: 'https://pypi.org/project/pyserial/',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/pyserial/pyserial',
        },
        {
          name: 'cryptography',
          version: '46.0.5',
          packageUrl: 'https://pypi.org/project/cryptography/',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/pyca/cryptography',
        },
      ],
    },
    {
      id: 'vue-runtime',
      title: t('settings.about.groups.vueRuntime.title'),
      subtitle: t('settings.about.groups.vueRuntime.subtitle'),
      entries: [
        {
          name: 'vue',
          version: '^3.5.13',
          packageUrl: 'https://www.npmjs.com/package/vue',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/vuejs/core',
        },
        {
          name: 'vue-router',
          version: '^5.0.4',
          packageUrl: 'https://www.npmjs.com/package/vue-router',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/vuejs/router',
        },
        {
          name: 'pinia',
          version: '^3.0.4',
          packageUrl: 'https://www.npmjs.com/package/pinia',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/vuejs/pinia',
        },
        {
          name: 'vue-i18n',
          version: '^11.3.0',
          packageUrl: 'https://www.npmjs.com/package/vue-i18n',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/intlify/vue-i18n',
        },
        {
          name: '@vueuse/core',
          version: '^12.8.2',
          packageUrl: 'https://www.npmjs.com/package/@vueuse/core',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/vueuse/vueuse',
        },
        {
          name: 'floating-vue',
          version: '^5.2.2',
          packageUrl: 'https://www.npmjs.com/package/floating-vue',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/Akryum/floating-vue',
        },
        {
          name: 'vue3-emoji-picker',
          version: '^1.1.8',
          packageUrl: 'https://www.npmjs.com/package/vue3-emoji-picker',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/delowardev/vue3-emoji-picker',
        },
      ],
    },
    {
      id: 'vue-tooling',
      title: t('settings.about.groups.vueTooling.title'),
      subtitle: t('settings.about.groups.vueTooling.subtitle'),
      entries: [
        {
          name: 'vite',
          version: '^6.1.0',
          packageUrl: 'https://www.npmjs.com/package/vite',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/vitejs/vite',
        },
        {
          name: '@vitejs/plugin-vue',
          version: '^5.2.1',
          packageUrl: 'https://www.npmjs.com/package/@vitejs/plugin-vue',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/vitejs/vite/tree/main/packages/plugin-vue',
        },
        {
          name: 'vite-plugin-vue-devtools',
          version: '^7.7.6',
          packageUrl: 'https://www.npmjs.com/package/vite-plugin-vue-devtools',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/vuejs/devtools',
        },
        {
          name: 'vitest',
          version: '^3.2.4',
          packageUrl: 'https://www.npmjs.com/package/vitest',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/vitest-dev/vitest',
        },
        {
          name: '@vue/test-utils',
          version: '^2.4.6',
          packageUrl: 'https://www.npmjs.com/package/@vue/test-utils',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/vuejs/test-utils',
        },
        {
          name: '@playwright/test',
          version: '^1.53.1',
          packageUrl: 'https://www.npmjs.com/package/@playwright/test',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/microsoft/playwright',
        },
        {
          name: 'jsdom',
          version: '^26.1.0',
          packageUrl: 'https://www.npmjs.com/package/jsdom',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/jsdom/jsdom',
        },
      ],
    },
    {
      id: 'android',
      title: t('settings.about.groups.android.title'),
      subtitle: t('settings.about.groups.android.subtitle'),
      entries: [
        {
          name: 'androidx.core:core-ktx',
          version: '1.15.0',
          packageUrl: 'https://developer.android.com/jetpack/androidx/releases/core',
          packageLabel: t('settings.about.actions.docs'),
          repoUrl: 'https://github.com/androidx/androidx',
        },
        {
          name: 'androidx.appcompat:appcompat',
          version: '1.7.0',
          packageUrl: 'https://developer.android.com/jetpack/androidx/releases/appcompat',
          packageLabel: t('settings.about.actions.docs'),
          repoUrl: 'https://github.com/androidx/androidx',
        },
        {
          name: 'com.google.android.material:material',
          version: '1.12.0',
          packageUrl: 'https://mvnrepository.com/artifact/com.google.android.material/material/1.12.0',
          packageLabel: t('settings.about.actions.package'),
          repoUrl: 'https://github.com/material-components/material-components-android',
        },
        {
          name: 'androidx.webkit:webkit',
          version: '1.12.1',
          packageUrl: 'https://developer.android.com/jetpack/androidx/releases/webkit',
          packageLabel: t('settings.about.actions.docs'),
          repoUrl: 'https://github.com/androidx/androidx',
        },
        {
          name: 'androidx.lifecycle:lifecycle-process',
          version: '2.8.7',
          packageUrl: 'https://developer.android.com/jetpack/androidx/releases/lifecycle',
          packageLabel: t('settings.about.actions.docs'),
          repoUrl: 'https://github.com/androidx/androidx',
        },
        {
          name: 'com.google.firebase:firebase-bom',
          version: '33.10.0',
          packageUrl: 'https://firebase.google.com/docs/android/learn-more#bom',
          packageLabel: t('settings.about.actions.docs'),
          repoUrl: 'https://github.com/firebase/firebase-android-sdk',
        },
        {
          name: 'com.google.firebase:firebase-messaging-ktx',
          version: 'via BOM',
          packageUrl: 'https://firebase.google.com/docs/cloud-messaging/android/client',
          packageLabel: t('settings.about.actions.docs'),
          repoUrl: 'https://github.com/firebase/firebase-android-sdk',
        },
      ],
    },
  ]
})

const settingsSections = computed(() => {
  return [
    {
      id: 'meshcorium',
      kind: 'vue',
      title: t('settings.sections.meshcorium.title'),
      subtitle: t('settings.sections.meshcorium.subtitle'),
    },
    {
      id: 'node',
      kind: 'vue',
      title: t('settings.sections.node.title'),
      subtitle: t('settings.sections.node.subtitle'),
    },
    {
      id: 'contacts',
      kind: 'vue',
      title: t('settings.sections.contacts.title'),
      subtitle: t('settings.sections.contacts.subtitle'),
    },
    {
      id: 'debug',
      kind: 'vue',
      title: t('settings.sections.debug.title'),
      subtitle: t('settings.sections.debug.subtitle'),
    },
    {
      id: 'about',
      kind: 'vue',
      title: t('settings.sections.about.title'),
      subtitle: t('settings.sections.about.subtitle'),
    },
  ]
})

const VALID_ROOT_SETTINGS_SECTIONS = new Set(['meshcorium', 'node', 'contacts', 'debug', 'about'])

function normalizeDebugSettingsSectionId(value) {
  return String(value || '').trim() === 'messages' ? 'messages' : 'debug'
}

function normalizeNodeCompanionSettingsSectionId(value) {
  const normalized = String(value || '').trim()
  return normalized === 'signal-metrics'
    ? 'signal-metrics'
    : (normalized === 'meshcore-params'
        ? 'meshcore-params'
        : (normalized === 'connection' ? 'connection' : 'general'))
}

function normalizeRootSettingsSectionId(value) {
  const normalized = String(value || '').trim()
  const normalizedRoot = normalized === 'contacts-admin' ? 'contacts' : normalized
  return VALID_ROOT_SETTINGS_SECTIONS.has(normalizedRoot) ? normalizedRoot : 'meshcorium'
}

function normalizeSettingsRouteState(sectionParam, subsectionParam) {
  const rootSectionId = normalizeRootSettingsSectionId(sectionParam)
  const debugSectionId = rootSectionId === 'debug'
    ? normalizeDebugSettingsSectionId(subsectionParam)
    : 'debug'
  const nodeSectionId = rootSectionId === 'node'
    ? normalizeNodeCompanionSettingsSectionId(subsectionParam)
    : 'general'
  return {
    rootSectionId,
    debugSectionId,
    nodeSectionId,
  }
}

function buildSettingsRouteLocation(rootSectionId, nestedSectionId = '') {
  const normalizedRoot = normalizeRootSettingsSectionId(rootSectionId)
  const params = {
    section: normalizedRoot,
  }
  if (normalizedRoot === 'debug') {
    const normalizedDebug = normalizeDebugSettingsSectionId(nestedSectionId)
    if (normalizedDebug === 'messages') {
      params.subsection = 'messages'
    }
  } else if (normalizedRoot === 'node') {
    const normalizedNode = normalizeNodeCompanionSettingsSectionId(nestedSectionId)
    if (normalizedNode !== 'general') {
      params.subsection = normalizedNode
    }
  }
  return {
    name: 'settings',
    params,
  }
}

function navigateToSettingsSection(rootSectionId, nestedSectionId = '', { replace = false } = {}) {
  const navigate = replace ? router.replace : router.push
  return navigate(buildSettingsRouteLocation(rootSectionId, nestedSectionId))
}

activeSettingsSectionId.value = normalizeRootSettingsSectionId(activeSettingsSectionId.value)
lastRootSettingsSectionId.value = normalizeRootSettingsSectionId(lastRootSettingsSectionId.value)

const activeSettingsSection = computed(() => {
  const normalizedId = normalizeRootSettingsSectionId(activeSettingsSectionId.value)
  if (normalizedId !== activeSettingsSectionId.value) {
    activeSettingsSectionId.value = normalizedId
  }
  return settingsSections.value.find((section) => section.id === normalizedId) || settingsSections.value[0]
})

function selectSettingsSection(section) {
  if (section.id === 'debug') {
    if (activeSettingsSectionId.value && activeSettingsSectionId.value !== 'debug') {
      lastRootSettingsSectionId.value = activeSettingsSectionId.value
    }
    void navigateToSettingsSection('debug')
    return
  }
  if (section.id === 'node') {
    if (activeSettingsSectionId.value && activeSettingsSectionId.value !== 'node') {
      lastRootSettingsSectionId.value = activeSettingsSectionId.value
    }
    void navigateToSettingsSection('node')
    return
  }
  lastRootSettingsSectionId.value = section.id
  void navigateToSettingsSection(section.id)
}

function requestDeleteContactsAdmin(mode) {
  const normalizedMode = String(mode || 'all').trim() || 'all'
  const summary = contactsAdminSummary.value
  const messageKey = normalizedMode === 'repeaters-only'
    ? 'settings.contacts.actions.deleteRepeatersConfirm'
    : (normalizedMode === 'non-favorites-no-direct'
      ? 'settings.contacts.actions.deleteSweepConfirm'
      : 'settings.contacts.actions.deleteAllConfirm')
  const noteKey = normalizedMode === 'non-favorites-no-direct'
    ? 'settings.contacts.actions.deleteSweepNote'
    : 'settings.contacts.actions.deleteCommonNote'
  confirmDialog.value = {
    open: true,
    title: t('settings.contacts.actions.confirmTitle'),
    message: t(messageKey),
    note: t(noteKey, {
      favorites: summary.nodeFavorites,
      directHistory: summary.nodeDirectHistory,
    }),
    confirmLabel: t('settings.contacts.actions.confirm'),
    confirmDisabled: false,
    action: async () => deleteContactsAdmin(normalizedMode),
  }
}

async function deleteContactsAdmin(mode) {
  const config = buildNodeCompanionConfig()
  if (!config || contactsAdminBusyMode.value) {
    return
  }
  contactsAdminBusyMode.value = String(mode || 'all')
  try {
    const data = await session.api('/api/contacts/delete', {
      method: 'POST',
      body: JSON.stringify({
        ...config,
        mode: contactsAdminBusyMode.value,
        protect_favorites: true,
      }),
    })
    await session.loadContacts({ refresh: false }).catch(() => {})
    await session.syncSessionState({ light: true }).catch(() => {})
    const removed = Math.max(0, Number(data?.removed || 0))
    const remaining = Math.max(0, Number(data?.remaining || 0))
    const statusKey = contactsAdminBusyMode.value === 'non-favorites-no-direct'
      ? 'settings.contacts.status.cleanedNonFavorites'
      : 'settings.contacts.status.deleted'
    session.setStatus(t(statusKey, { removed, remaining }))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('settings.status.saveFailed')), true)
  } finally {
    contactsAdminBusyMode.value = ''
  }
}

function selectDebugSettingsSection(sectionId) {
  const normalized = normalizeDebugSettingsSectionId(sectionId)
  void navigateToSettingsSection('debug', normalized === 'messages' ? 'messages' : '')
}

function leaveDebugSettingsMode() {
  void navigateToSettingsSection(lastRootSettingsSectionId.value || 'meshcorium')
}

function selectNodeCompanionSection(sectionId) {
  const normalized = normalizeNodeCompanionSettingsSectionId(sectionId)
  void navigateToSettingsSection('node', normalized === 'general' ? '' : normalized)
}

function leaveNodeCompanionSettingsMode() {
  void navigateToSettingsSection(lastRootSettingsSectionId.value || 'meshcorium')
}

function selectMeshcoreParamsSection(sectionId) {
  activeMeshcoreParamsSectionId.value = normalizeMeshcoreParamsSectionId(sectionId)
}

function leaveMeshcoreParamsMode() {
  void navigateToSettingsSection('node')
}

function nowPerformanceMs() {
  if (typeof window !== 'undefined' && typeof window.performance !== 'undefined' && typeof window.performance.now === 'function') {
    return Number(window.performance.now())
  }
  return Date.now()
}

function getNodeCompanionWorkspaceTelemetry() {
  const root = settingsWorkspaceRef.value
  const rect = root?.getBoundingClientRect?.()
  const connectionSection = root?.querySelector?.('[data-node-companion-section="connection"]') || null
  const generalSection = root?.querySelector?.('[data-node-companion-section="general"]') || null
  const signalSection = root?.querySelector?.('[data-node-companion-section="signal-metrics"]') || null
  return {
    panelCount: root?.querySelectorAll?.('.mc-settings-panel')?.length || 0,
    textLength: String(root?.innerText || '').trim().length,
    rect: rect ? {
      width: Math.round(rect.width || 0),
      height: Math.round(rect.height || 0),
    } : null,
    connectionMounted: Boolean(connectionSection),
    connectionVisible: Boolean(connectionSection && connectionSection.offsetParent),
    generalVisible: Boolean(generalSection && generalSection.offsetParent),
    signalVisible: Boolean(signalSection && signalSection.offsetParent),
  }
}

async function logNodeCompanionDiagnostic(event, extra = {}) {
  const startedAt = Number(extra.startedAt || 0)
  const beforeNextTickAt = nowPerformanceMs()
  await nextTick()
  const afterNextTickAt = nowPerformanceMs()
  if (typeof window !== 'undefined') {
    await new Promise((resolve) => {
      window.requestAnimationFrame(() => resolve())
    })
  }
  const afterFirstRafAt = nowPerformanceMs()
  if (typeof window !== 'undefined') {
    await new Promise((resolve) => {
      window.requestAnimationFrame(() => resolve())
    })
  }
  const afterSecondRafAt = nowPerformanceMs()
  logFrontendDiagnostic('settings-node-diagnostic', {
    event,
    activeSettingsSectionId: activeSettingsSectionId.value,
    activeNodeCompanionSectionId: activeNodeCompanionSectionId.value,
    connected: Boolean(session.connected),
    selectedPort: String(session.selectedPort || ''),
    portsCount: Array.isArray(session.ports) ? session.ports.length : 0,
    savedConnectionsCount: Array.isArray(session.savedConnections) ? session.savedConnections.length : 0,
    hasSettingsPayload: Boolean(session.settingsPayload),
    loadingClientSettings: Boolean(session.loadingClientSettings),
    loadingPorts: Boolean(session.loadingPorts),
    syncingSession: Boolean(session.syncingSession),
    timing: {
      startedAt,
      beforeNextTickAt,
      afterNextTickAt,
      afterFirstRafAt,
      afterSecondRafAt,
      sinceStartMs: startedAt > 0 ? Math.max(0, Math.round(afterSecondRafAt - startedAt)) : null,
      nextTickMs: Math.max(0, Math.round(afterNextTickAt - beforeNextTickAt)),
      firstRafMs: Math.max(0, Math.round(afterFirstRafAt - afterNextTickAt)),
      secondRafMs: Math.max(0, Math.round(afterSecondRafAt - afterFirstRafAt)),
    },
    workspace: getNodeCompanionWorkspaceTelemetry(),
    ...extra,
  })
}

const { pause: pauseAutoRefresh, resume: resumeAutoRefresh } = useIntervalFn(() => {
  refreshSettingsState({ suppressStatus: true })
}, 30000, { immediate: false })

watch(visibility, (value) => {
  if (value === 'visible') {
    resumeAutoRefresh()
    refreshSettingsState({ suppressStatus: true })
    return
  }
  pauseAutoRefresh()
})

watch(() => session.self?.name, (value) => {
  nodeCompanionNameDraft.value = String(value || '').trim()
}, { immediate: true })

watch(signalMetricsRetentionDays, (value) => {
  signalMetricsRetentionDraft.value = value
}, { immediate: true })

watch(signalMetricsPollSeconds, (value) => {
  signalMetricsPollDraft.value = value
}, { immediate: true })

watch(() => session.settingsPayload?.settings, (settings) => {
  nodeCompanionAuthEnabledDraft.value = Boolean(settings?.auth_enabled)
  nodeCompanionAuthUsernameDraft.value = String(settings?.auth_username || '')
}, { immediate: true, deep: true })

watch(
  () => [route.params.section, route.params.subsection],
  ([sectionParam, subsectionParam]) => {
    const previousRootSectionId = normalizeRootSettingsSectionId(activeSettingsSectionId.value)
    const normalizedRoute = normalizeSettingsRouteState(sectionParam, subsectionParam)
    const canonicalTarget = buildSettingsRouteLocation(
      normalizedRoute.rootSectionId,
      normalizedRoute.rootSectionId === 'debug'
        ? normalizedRoute.debugSectionId
        : normalizedRoute.nodeSectionId,
    )
    const canonicalPath = router.resolve(canonicalTarget).path
    if (route.path !== canonicalPath) {
      void router.replace({
        ...canonicalTarget,
        query: route.query,
      })
      return
    }
    if (
      normalizedRoute.rootSectionId !== previousRootSectionId
      && previousRootSectionId
      && previousRootSectionId !== 'debug'
      && previousRootSectionId !== 'node'
    ) {
      lastRootSettingsSectionId.value = previousRootSectionId
    }
    activeSettingsSectionId.value = normalizedRoute.rootSectionId
    activeDebugSectionId.value = normalizedRoute.debugSectionId
    activeNodeCompanionSectionId.value = normalizedRoute.nodeSectionId
  },
  { immediate: true },
)

watch(() => [activeSettingsSectionId.value, session.selectedPort], ([sectionId, port], [prevSectionId, prevPort] = []) => {
  if (sectionId !== 'node' || String(port || '').trim() !== String(prevPort || '').trim()) {
    stopNodeCompanionListener({ silent: true })
  }
  if (String(sectionId || '').trim() !== 'debug' && String(prevSectionId || '').trim() === 'debug') {
    activeDebugSectionId.value = 'debug'
  }
  if (String(sectionId || '').trim() !== 'node' && String(prevSectionId || '').trim() === 'node') {
    activeNodeCompanionSectionId.value = 'general'
  }
})

watch(
  () => [activeSettingsSectionId.value, activeNodeCompanionSectionId.value],
  async ([sectionId, nodeSectionId], [prevSectionId, prevNodeSectionId] = []) => {
    if (sectionId !== 'node') {
      return
    }
    const startedAt = nowPerformanceMs()
    const token = nodeCompanionSwitchTiming.value.token + 1
    nodeCompanionSwitchTiming.value = {
      token,
      startedAt,
      settledLogged: false,
    }
    logFrontendDiagnostic('settings-node-diagnostic', {
      event: 'section-switch-start',
      activeSettingsSectionId: sectionId,
      activeNodeCompanionSectionId: nodeSectionId,
      fromSectionId: String(prevSectionId || ''),
      fromNodeSectionId: String(prevNodeSectionId || ''),
      toNodeSectionId: String(nodeSectionId || ''),
      connected: Boolean(session.connected),
      selectedPort: String(session.selectedPort || ''),
      portsCount: Array.isArray(session.ports) ? session.ports.length : 0,
      savedConnectionsCount: Array.isArray(session.savedConnections) ? session.savedConnections.length : 0,
      hasSettingsPayload: Boolean(session.settingsPayload),
      loadingClientSettings: Boolean(session.loadingClientSettings),
      loadingPorts: Boolean(session.loadingPorts),
      syncingSession: Boolean(session.syncingSession),
      timing: {
        startedAt,
      },
    })
    await logNodeCompanionDiagnostic('section-switch', {
      fromSectionId: String(prevSectionId || ''),
      fromNodeSectionId: String(prevNodeSectionId || ''),
      toNodeSectionId: String(nodeSectionId || ''),
      startedAt,
    })
  },
  { immediate: true },
)

watch(
  () => [isMeshcoreParamsSettingsMode.value, session.selfPublicKey, session.connected],
  ([enabled, publicKey, connected], [prevEnabled, prevPublicKey, prevConnected] = []) => {
    if (!enabled) {
      return
    }
    if (!connected) {
      meshcoreParamsPayload.value = null
      resetMeshcoreParamsDrafts()
      return
    }
    if (
      enabled !== prevEnabled
      || String(publicKey || '') !== String(prevPublicKey || '')
      || Boolean(connected) !== Boolean(prevConnected)
      || !meshcoreParamsPayload.value
    ) {
      void loadMeshcoreParams({ silent: true })
    }
  },
  { immediate: true },
)

watch(
  () => [
    activeSettingsSectionId.value,
    activeNodeCompanionSectionId.value,
    Boolean(session.settingsPayload),
    session.loadingClientSettings,
    session.loadingPorts,
    session.syncingSession,
    Array.isArray(session.ports) ? session.ports.length : 0,
    Array.isArray(session.savedConnections) ? session.savedConnections.length : 0,
  ],
  async ([sectionId, nodeSectionId, hasSettingsPayload, loadingClientSettings, loadingPorts, syncingSession]) => {
    if (sectionId !== 'node') {
      return
    }
    if (nodeCompanionSwitchTiming.value.settledLogged) {
      return
    }
    if (loadingClientSettings || loadingPorts || syncingSession) {
      return
    }
    nodeCompanionSwitchTiming.value = {
      ...nodeCompanionSwitchTiming.value,
      settledLogged: true,
    }
    await logNodeCompanionDiagnostic('section-data-settled', {
      startedAt: nodeCompanionSwitchTiming.value.startedAt,
      hasSettingsPayload: Boolean(hasSettingsPayload),
      toNodeSectionId: String(nodeSectionId || ''),
    })
  },
  { immediate: true },
)

onMounted(async () => {
  window.addEventListener('keydown', handleSettingsEscape)
  resumeAutoRefresh()
  await refreshSettingsState({ includePorts: true })
  if (!session.statusText) {
    session.setStatus(t('settings.status.ready'))
  }
})

watch(
  () => [activeSettingsSectionId.value, activeDebugSectionId.value, session.selectedPort, session.connected],
  async ([sectionId, debugSectionId]) => {
    if (sectionId !== 'debug') {
      return
    }
    if (debugSectionId === 'messages') {
      await loadMessageDebugSummary().catch(() => {})
      return
    }
    await loadContactDebugPayload().catch(() => {})
  },
  { immediate: true },
)

watch(
  () => [activeSettingsSectionId.value, activeNodeCompanionSectionId.value, session.selectedPort, visibility.value, signalMetricsPollSeconds.value],
  async ([sectionId, nodeSection]) => {
    if (sectionId === 'node' && nodeSection === 'signal-metrics') {
      await loadSignalMetricsPayload().catch(() => {})
    }
    ensureSignalMetricsLiveTimer()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleSettingsEscape)
  if (clearMessageDbUnlockTimer != null) {
    window.clearInterval(clearMessageDbUnlockTimer)
    clearMessageDbUnlockTimer = null
  }
  stopNotificationSoundPreview('regular')
  stopNotificationSoundPreview('mention')
  stopNotificationSoundPreview('direct')
  stopNodeCompanionListener({ silent: true })
  clearSignalMetricsLiveTimer()
  pauseAutoRefresh()
})
</script>

<template>
  <ShellPageFrame
    scroller-class="mc-sidebar--settings"
    scroller-header-class="mc-sidebar-top--settings"
    workspace-class="mc-content--shell-settings"
  >
    <template #workspace-top>
      <ShellPhonebar />
    </template>

    <template #scroller-header>
      <div v-if="isMeshcoreParamsSettingsMode" class="mc-scroller-copy mc-scroller-copy--settings-debug">
        <button class="mc-settings-debug-back" type="button" @click="leaveMeshcoreParamsMode">
          {{ t('settings.nodeCompanion.meshcoreParams.backToNode') }}
        </button>
        <h1 class="mc-scroller-title mc-scroller-title--shell-top">{{ t('settings.nodeCompanion.sections.meshcoreParams.title') }}</h1>
      </div>
      <div v-else-if="isDebugSettingsMode" class="mc-scroller-copy mc-scroller-copy--settings-debug">
        <button class="mc-settings-debug-back" type="button" @click="leaveDebugSettingsMode">
          {{ t('settings.debug.backToSettings') }}
        </button>
        <h1 class="mc-scroller-title mc-scroller-title--shell-top">{{ t('settings.sections.debug.title') }}</h1>
      </div>
      <div v-else-if="isNodeCompanionSettingsMode" class="mc-scroller-copy mc-scroller-copy--settings-debug">
        <button class="mc-settings-debug-back" type="button" @click="leaveNodeCompanionSettingsMode">
          {{ t('settings.nodeCompanion.backToSettings') }}
        </button>
        <h1 class="mc-scroller-title mc-scroller-title--shell-top">{{ t('settings.sections.node.title') }}</h1>
      </div>
      <div v-else class="mc-scroller-copy mc-scroller-copy--shell-top">
        <h1 class="mc-scroller-title mc-scroller-title--shell-top">{{ t('settings.title') }}</h1>
      </div>
    </template>

    <template #scroller-body>
      <div class="mc-list-scroll mc-list-scroll--settings">
        <template v-if="isMeshcoreParamsSettingsMode">
          <button
            v-for="section in meshcoreParamsSections"
            :key="section.id"
            class="mc-settings-nav-item"
            :class="{ active: section.id === activeMeshcoreParamsSectionId }"
            type="button"
            @click="selectMeshcoreParamsSection(section.id)"
          >
            <div class="mc-settings-nav-copy">
              <div class="mc-settings-nav-title-row">
                <p class="mc-settings-nav-title">{{ section.title }}</p>
              </div>
              <p class="mc-settings-nav-subtitle">{{ section.subtitle }}</p>
            </div>
          </button>
        </template>
        <template v-else-if="isDebugSettingsMode">
          <button
            v-for="section in debugSettingsSections"
            :key="section.id"
            class="mc-settings-nav-item"
            :class="{ active: section.id === activeDebugSectionId }"
            type="button"
            @click="selectDebugSettingsSection(section.id)"
          >
            <div class="mc-settings-nav-copy">
              <div class="mc-settings-nav-title-row">
                <p class="mc-settings-nav-title">{{ section.title }}</p>
              </div>
              <p class="mc-settings-nav-subtitle">{{ section.subtitle }}</p>
            </div>
          </button>
        </template>
        <template v-else-if="isNodeCompanionSettingsMode">
          <button
            v-for="section in nodeCompanionSections"
            :key="section.id"
            class="mc-settings-nav-item"
            :class="{ active: section.id === activeNodeCompanionSectionId }"
            type="button"
            @click="selectNodeCompanionSection(section.id)"
          >
            <div class="mc-settings-nav-copy">
              <div class="mc-settings-nav-title-row">
                <p class="mc-settings-nav-title">{{ section.title }}</p>
              </div>
              <p class="mc-settings-nav-subtitle">{{ section.subtitle }}</p>
            </div>
          </button>
        </template>
        <template v-else>
        <button
          v-for="section in settingsSections"
          :key="section.id"
          class="mc-settings-nav-item"
          :class="{ active: section.id === activeSettingsSection.id }"
          type="button"
          @click="selectSettingsSection(section)"
        >
          <div class="mc-settings-nav-copy">
            <div class="mc-settings-nav-title-row">
              <p class="mc-settings-nav-title">{{ section.title }}</p>
            </div>
            <p class="mc-settings-nav-subtitle">{{ section.subtitle }}</p>
          </div>
        </button>
        </template>
      </div>
    </template>

    <template #scroller-footer>
      <div class="mc-status" :class="{ 'is-error': session.statusError }">
        {{ session.statusText || serviceStatusCopy }}
      </div>
    </template>

    <template #workspace-header>
      <header class="mc-workspace-header">
        <div class="mc-workspace-copy">
          <h2 class="mc-workspace-title">{{ activeSettingsSection.id === 'debug' ? activeDebugSectionTitle : (activeSettingsSection.id === 'node' ? activeNodeCompanionSectionTitle : activeSettingsSection.title) }}</h2>
          <p class="mc-workspace-subtitle">{{ activeSettingsSection.id === 'debug' ? activeDebugSectionSubtitle : (activeSettingsSection.id === 'node' ? activeNodeCompanionSectionSubtitle : activeSettingsSection.subtitle) }}</p>
        </div>
      </header>
    </template>

    <template #workspace-body>
      <div ref="settingsWorkspaceRef" class="mc-settings-workspace">
      <template v-if="activeSettingsSection.id === 'meshcorium'">
        <div class="mc-settings-section-stack mc-settings-section-stack--meshcorium">
        <section class="mc-settings-panel">
          <div class="mc-settings-panel-copy">
            <h3>{{ t('settings.sections.meshcorium.title') }}</h3>
            <p>{{ t('settings.meshcorium.subtitle') }}</p>
          </div>

          <div class="mc-settings-rows">
            <label class="mc-settings-row">
              <div class="mc-settings-row-label">
                <strong>{{ t('settings.meshcorium.language.title') }}</strong>
                <span>{{ t('settings.meshcorium.language.subtitle') }}</span>
              </div>
              <div class="mc-settings-row-control">
                <PluginDropdown
                  :model-value="activeLocale"
                  :options="localeDropdownOptions"
                  :min-width="220"
                  @update:model-value="changeLocale"
                />
              </div>
            </label>

            <div class="mc-settings-row">
              <div class="mc-settings-row-label">
                <strong>{{ t('settings.meshcorium.background.title') }}</strong>
                <span>{{ t('settings.meshcorium.background.subtitle') }}</span>
              </div>
              <div class="mc-settings-row-control mc-settings-row-control--stack">
                <div class="mc-settings-inline-controls">
                  <PluginDropdown
                    :model-value="pageBackgroundId"
                    :options="backgroundDropdownOptions"
                    :min-width="220"
                    @update:model-value="updatePageBackgroundId"
                  />
                  <div class="mc-settings-checkbox">
                    <input
                      type="checkbox"
                      :checked="pageBackgroundBlurEnabled"
                      @change="updatePageBackgroundBlurEnabled($event.target.checked)"
                    />
                    <span>{{ t('settings.meshcorium.background.blurToggle') }}</span>
                  </div>
                </div>
              </div>
            </div>

            <label class="mc-settings-row">
              <div class="mc-settings-row-label">
                <strong>{{ t('settings.meshcorium.chatBackground.title') }}</strong>
                <span>{{ t('settings.meshcorium.chatBackground.subtitle') }}</span>
              </div>
              <div class="mc-settings-row-control">
                <PluginDropdown
                  :model-value="chatBackgroundId"
                  :options="chatBackgroundDropdownOptions"
                  :min-width="220"
                  @update:model-value="updateChatBackgroundId"
                />
              </div>
            </label>

            <label v-if="pageBackgroundBlurEnabled" class="mc-settings-row">
              <div class="mc-settings-row-label">
                <strong>{{ t('settings.meshcorium.background.blurAmountTitle') }}</strong>
                <span>{{ t('settings.meshcorium.background.blurAmountSubtitle') }}</span>
              </div>
              <div class="mc-settings-row-control mc-settings-row-control--stack">
                <div class="mc-settings-range-wrap">
                  <div class="mc-settings-range-meta">
                    <span>{{ t('settings.meshcorium.background.blurRangeMin') }}</span>
                    <strong>{{ backgroundBlurDraftPx }}px</strong>
                  </div>
                  <input
                    class="mc-settings-range"
                    type="range"
                    min="0"
                    max="32"
                    step="1"
                    :value="backgroundBlurDraftPx"
                    @input="handleBackgroundBlurInput"
                  />
                </div>
              </div>
            </label>

            <label class="mc-settings-row">
              <div class="mc-settings-row-label">
                <strong>{{ t('settings.meshcorium.background.uploadTitle') }}</strong>
                <span>{{ t('settings.meshcorium.background.uploadSubtitle') }}</span>
              </div>
              <div class="mc-settings-row-control mc-settings-row-control--stack">
                <div class="mc-settings-upload-actions">
                  <button class="mc-button mc-button--ghost" type="button" :disabled="uploadingWallpaper" @click="openWallpaperPicker">
                    {{ uploadingWallpaper ? t('settings.meshcorium.background.uploading') : t('settings.meshcorium.background.uploadButton') }}
                  </button>
                  <span class="mc-settings-file-note">{{ t('settings.meshcorium.background.directoryNote') }}</span>
                </div>
                <input
                  ref="wallpaperFileInput"
                  type="file"
                  accept=".jpg,.jpeg,.png,.webp,.gif,.avif,image/*"
                  hidden
                  @change="handleWallpaperUpload"
                />
              </div>
            </label>
          </div>
        </section>

        <section class="mc-settings-panel">
          <div class="mc-settings-panel-copy">
            <h3>{{ t('settings.meshcorium.notifications.title') }}</h3>
            <p>{{ t('settings.meshcorium.notifications.subtitle') }}</p>
          </div>

          <div class="mc-settings-rows">
            <label class="mc-settings-row">
              <div class="mc-settings-row-label">
                <strong>{{ t('settings.nodeCompanion.connection.notificationSounds.regularTitle') }}</strong>
              </div>
              <div class="mc-settings-row-control">
                <div class="mc-settings-inline-controls mc-settings-inline-controls--sound-preview">
                  <select
                    class="mc-settings-native-select"
                    :value="String(regularNotificationSoundFile || '')"
                    :disabled="!notificationSoundOptions.length"
                    @change="updateRegularNotificationSoundFile($event.target.value)"
                  >
                    <option v-if="!notificationSoundOptions.length" value="">
                      {{ t('settings.nodeCompanion.connection.notificationSounds.regularSubtitle') }}
                    </option>
                    <option
                      v-for="option in notificationSoundOptions"
                      :key="option.value"
                      :value="String(option.value || '')"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                  <button
                    class="mc-settings-sound-preview-button"
                    :class="{ 'is-playing': regularNotificationSoundPreviewPlaying }"
                    type="button"
                    :disabled="!regularNotificationSoundFile"
                    :title="t('settings.meshcorium.notifications.previewSound')"
                    :aria-label="t('settings.meshcorium.notifications.previewSound')"
                    @click="playNotificationSoundPreview('regular')"
                  >
                    <img :src="playSoundIconUrl" alt="" aria-hidden="true" />
                  </button>
                </div>
              </div>
            </label>

            <label class="mc-settings-row">
              <div class="mc-settings-row-label">
                <strong>{{ t('settings.nodeCompanion.connection.notificationSounds.mentionTitle') }}</strong>
              </div>
              <div class="mc-settings-row-control">
                <div class="mc-settings-inline-controls mc-settings-inline-controls--sound-preview">
                  <select
                    class="mc-settings-native-select"
                    :value="String(mentionNotificationSoundFile || '')"
                    :disabled="!notificationSoundOptions.length"
                    @change="updateMentionNotificationSoundFile($event.target.value)"
                  >
                    <option v-if="!notificationSoundOptions.length" value="">
                      {{ t('settings.nodeCompanion.connection.notificationSounds.mentionSubtitle') }}
                    </option>
                    <option
                      v-for="option in notificationSoundOptions"
                      :key="option.value"
                      :value="String(option.value || '')"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                  <button
                    class="mc-settings-sound-preview-button"
                    :class="{ 'is-playing': mentionNotificationSoundPreviewPlaying }"
                    type="button"
                    :disabled="!mentionNotificationSoundFile"
                    :title="t('settings.meshcorium.notifications.previewSound')"
                    :aria-label="t('settings.meshcorium.notifications.previewSound')"
                    @click="playNotificationSoundPreview('mention')"
                  >
                    <img :src="playSoundIconUrl" alt="" aria-hidden="true" />
                  </button>
                </div>
              </div>
            </label>

            <label class="mc-settings-row">
              <div class="mc-settings-row-label">
                <strong>{{ t('settings.nodeCompanion.connection.notificationSounds.directTitle') }}</strong>
              </div>
              <div class="mc-settings-row-control">
                <div class="mc-settings-inline-controls mc-settings-inline-controls--sound-preview">
                  <select
                    class="mc-settings-native-select"
                    :value="String(directNotificationSoundFile || '')"
                    :disabled="!notificationSoundOptions.length"
                    @change="updateDirectNotificationSoundFile($event.target.value)"
                  >
                    <option v-if="!notificationSoundOptions.length" value="">
                      {{ t('settings.nodeCompanion.connection.notificationSounds.directSubtitle') }}
                    </option>
                    <option
                      v-for="option in notificationSoundOptions"
                      :key="option.value"
                      :value="String(option.value || '')"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                  <button
                    class="mc-settings-sound-preview-button"
                    :class="{ 'is-playing': directNotificationSoundPreviewPlaying }"
                    type="button"
                    :disabled="!directNotificationSoundFile"
                    :title="t('settings.meshcorium.notifications.previewSound')"
                    :aria-label="t('settings.meshcorium.notifications.previewSound')"
                    @click="playNotificationSoundPreview('direct')"
                  >
                    <img :src="playSoundIconUrl" alt="" aria-hidden="true" />
                  </button>
                </div>
              </div>
            </label>
          </div>
        </section>

        <section class="mc-settings-panel">
          <div class="mc-settings-panel-copy">
            <h3>{{ t('settings.meshcorium.auth.title') }}</h3>
            <p>{{ t('settings.meshcorium.auth.subtitle') }}</p>
          </div>
          <div class="mc-settings-rows">
            <div class="mc-settings-row">
              <div class="mc-settings-row-label">
                <strong>{{ t('settings.nodeCompanion.connection.auth.enableTitle') }}</strong>
                <span>{{ t('settings.nodeCompanion.connection.auth.enableSubtitle') }}</span>
              </div>
              <div class="mc-settings-row-control">
                <div class="mc-settings-checkbox">
                  <input v-model="nodeCompanionAuthEnabledDraft" type="checkbox" />
                </div>
              </div>
            </div>

            <label class="mc-settings-row">
              <div class="mc-settings-row-label">
                <strong>{{ t('settings.nodeCompanion.connection.auth.usernameTitle') }}</strong>
                <span>{{ t('settings.nodeCompanion.connection.auth.usernameSubtitle') }}</span>
              </div>
              <div class="mc-settings-row-control">
                <input
                  v-model="nodeCompanionAuthUsernameDraft"
                  class="mc-settings-inline-input"
                  type="text"
                  maxlength="64"
                  :placeholder="t('settings.nodeCompanion.connection.auth.usernamePlaceholder')"
                />
              </div>
            </label>

            <label class="mc-settings-row">
              <div class="mc-settings-row-label">
                <strong>{{ t('settings.nodeCompanion.connection.auth.passwordTitle') }}</strong>
                <span>{{ authPasswordConfigured ? t('settings.nodeCompanion.connection.auth.passwordConfigured') : t('settings.nodeCompanion.connection.auth.passwordMissing') }}</span>
              </div>
              <div class="mc-settings-row-control">
                <input
                  v-model="nodeCompanionAuthPasswordDraft"
                  class="mc-settings-inline-input"
                  type="password"
                  maxlength="128"
                  :placeholder="t('settings.nodeCompanion.connection.auth.passwordPlaceholder')"
                />
              </div>
            </label>
          </div>
          <div class="mc-settings-actions-row">
            <button class="mc-button mc-button--primary" type="button" @click="saveNodeCompanionAuth">
              {{ t('settings.nodeCompanion.connection.auth.apply') }}
            </button>
            <button class="mc-button mc-button--ghost" type="button" @click="logoutNodeCompanionAuthBrowser">
              {{ t('settings.nodeCompanion.connection.auth.logout') }}
            </button>
          </div>
        </section>

        </div>
      </template>

      <template v-else-if="activeSettingsSection.id === 'node'">
        <div
          v-if="activeNodeCompanionSectionId === 'signal-metrics'"
          key="node-signal-metrics"
          class="mc-settings-section-stack"
          data-node-companion-section="signal-metrics"
        >
          <section class="mc-settings-panel">
            <div class="mc-settings-signal-line-weight mc-settings-signal-line-weight--top">
              <div class="mc-settings-panel-copy">
                <h3>{{ t('settings.nodeCompanion.signalMetrics.controls.lineWeight') }}</h3>
                <p>{{ t('settings.nodeCompanion.signalMetrics.controls.lineWeightSubtitle') }}</p>
              </div>
              <input
                v-model.number="signalMetricsLineWeight"
                class="mc-settings-range"
                type="range"
                min="1"
                max="100"
                step="1"
              />
            </div>

            <div v-if="signalMetricsLoading" class="mc-settings-signal-empty">
              {{ t('settings.nodeCompanion.signalMetrics.loading') }}
            </div>
            <div v-else-if="!signalMetricsHasVisibleSeries" class="mc-settings-signal-empty">
              {{ t('settings.nodeCompanion.signalMetrics.emptyHidden') }}
            </div>
            <div v-else-if="!signalMetricsChartMarkup" class="mc-settings-signal-empty">
              {{ t('settings.nodeCompanion.signalMetrics.empty') }}
            </div>
            <div
              v-else
              class="mc-settings-signal-chart"
              @mousemove="syncSignalMetricsHoverFromEvent"
              @mouseleave="clearSignalMetricsHover"
            >
              <div class="mc-settings-signal-chart-shell" v-html="signalMetricsChartMarkup"></div>
              <div class="mc-settings-signal-hover" :class="{ hidden: !signalMetricsHoverText }">{{ signalMetricsHoverText }}</div>
            </div>

            <div class="mc-settings-signal-summary">
              <span v-for="item in signalMetricsSummaryItems" :key="item" class="mc-settings-signal-chip">{{ item }}</span>
            </div>
          </section>

          <section class="mc-settings-panel">
            <div class="mc-settings-signal-controls">
              <div class="mc-settings-toggle-card">
                <input v-model="signalMetricsShowSnr" type="checkbox" />
                <span class="mc-settings-toggle-copy">
                  <strong>{{ t('settings.nodeCompanion.signalMetrics.series.snr') }}</strong>
                  <span>{{ t('settings.nodeCompanion.signalMetrics.series.snrSubtitle') }}</span>
                </span>
              </div>
              <div class="mc-settings-toggle-card">
                <input v-model="signalMetricsShowNoise" type="checkbox" />
                <span class="mc-settings-toggle-copy">
                  <strong>{{ t('settings.nodeCompanion.signalMetrics.series.noise') }}</strong>
                  <span>{{ t('settings.nodeCompanion.signalMetrics.series.noiseSubtitle') }}</span>
                </span>
              </div>
              <div class="mc-settings-toggle-card">
                <input v-model="signalMetricsShowRepeaters" type="checkbox" />
                <span class="mc-settings-toggle-copy">
                  <strong>{{ t('settings.nodeCompanion.signalMetrics.series.repeaters') }}</strong>
                  <span>{{ t('settings.nodeCompanion.signalMetrics.series.repeatersSubtitle') }}</span>
                </span>
              </div>

              <div class="mc-settings-signal-controls-grid">
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.signalMetrics.controls.range') }}</strong>
                    <span>{{ t('settings.nodeCompanion.signalMetrics.controls.rangeSubtitle') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <PluginDropdown
                      :model-value="signalMetricsRangeSeconds"
                      :options="signalMetricsRangeOptions"
                      :min-width="180"
                      @update:model-value="updateSignalMetricsRange"
                    />
                  </div>
                </label>

                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.signalMetrics.controls.retention') }}</strong>
                    <span>{{ t('settings.nodeCompanion.signalMetrics.controls.retentionSubtitle') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <input v-model.number="signalMetricsRetentionDraft" class="mc-settings-text-input mc-settings-text-input--narrow" type="number" min="1" max="365" step="1" />
                  </div>
                </label>

                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.signalMetrics.controls.poll') }}</strong>
                    <span>{{ t('settings.nodeCompanion.signalMetrics.controls.pollSubtitle') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <PluginDropdown
                      :model-value="signalMetricsPollDraft"
                      :options="[
                        { value: 5, label: '5' },
                        { value: 10, label: '10' },
                        { value: 15, label: '15' },
                        { value: 30, label: '30' },
                        { value: 60, label: '60' },
                        { value: 120, label: '120' },
                      ]"
                      :min-width="120"
                      @update:model-value="updateSignalMetricsPollDraft"
                    />
                  </div>
                </label>
              </div>

              <div class="mc-settings-debug-actions">
                <button class="mc-button mc-button--primary" type="button" @click="applySignalMetricsSettings">
                  {{ t('settings.nodeCompanion.signalMetrics.controls.apply') }}
                </button>
              </div>
            </div>
          </section>
        </div>

        <div
          v-else-if="activeNodeCompanionSectionId === 'connection'"
          key="node-connection"
          class="mc-settings-section-stack"
          data-node-companion-section="connection"
        >
          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.nodeCompanion.sections.connection.title') }}</h3>
              <p>{{ t('settings.nodeCompanion.sections.connection.subtitle') }}</p>
            </div>

            <div class="mc-settings-rows">
              <label class="mc-settings-row">
                <div class="mc-settings-row-label">
                  <strong>{{ t('settings.nodeCompanion.connection.fields.port') }}</strong>
                  <span>{{ t('settings.nodeCompanion.connection.fields.portSubtitle') }}</span>
                </div>
                <div class="mc-settings-row-control">
                  <div class="mc-settings-inline-controls">
                    <select
                      class="mc-settings-native-select"
                      :value="nodeConnectionRenderModel.selectedPort"
                      :disabled="!nodeConnectionRenderModel.portOptions.length"
                      @change="updateSelectedPort($event.target.value)"
                    >
                      <option v-if="!nodeConnectionRenderModel.portOptions.length" value="">{{ t('connect.fields.selectPort') }}</option>
                      <option
                        v-for="option in nodeConnectionRenderModel.portOptions"
                        :key="option.value"
                        :value="String(option.value || '')"
                      >
                        {{ option.triggerLabel || option.label }}
                      </option>
                    </select>
                    <button class="mc-icon-button" type="button" :aria-label="t('common.refreshPorts')" @click="refreshNodeCompanionPorts">
                      ↻
                    </button>
                  </div>
                </div>
              </label>

              <label class="mc-settings-row">
                <div class="mc-settings-row-label">
                  <strong>{{ t('settings.nodeCompanion.connection.fields.baudrate') }}</strong>
                  <span>{{ nodeCompanionPortLabel }}</span>
                </div>
                <div class="mc-settings-row-control">
                  <select
                    class="mc-settings-native-select"
                    :value="nodeConnectionRenderModel.selectedBaudrate"
                    @change="updateSelectedBaudrate(Number($event.target.value || session.DEFAULT_BAUDRATE))"
                  >
                    <option
                      v-for="option in nodeConnectionRenderModel.baudrateOptions"
                      :key="option.value"
                      :value="String(option.value || '')"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                </div>
              </label>

              <div class="mc-settings-row">
                <div class="mc-settings-row-label">
                  <strong>{{ t('settings.nodeCompanion.connection.autoConnect.title') }}</strong>
                  <span>{{ t('settings.nodeCompanion.connection.autoConnect.subtitle') }}</span>
                </div>
                <div class="mc-settings-row-control">
                  <div class="mc-settings-checkbox">
                    <input
                      type="checkbox"
                      :checked="nodeConnectionRenderModel.autoConnectOnServiceStart"
                      @change="updateAutoConnectOnServiceStart($event.target.checked)"
                    />
                  </div>
                </div>
              </div>

              <div v-if="nodeConnectionRenderModel.autoConnectOnServiceStart" class="mc-settings-row">
                <div class="mc-settings-row-label">
                  <strong>{{ t('settings.nodeCompanion.connection.startupMode.title') }}</strong>
                  <span>{{ t('settings.nodeCompanion.connection.startupMode.subtitle') }}</span>
                </div>
                <div class="mc-settings-row-control">
                  <div class="mc-settings-checkbox">
                    <input
                      type="checkbox"
                      :checked="nodeConnectionRenderModel.startupUseLastSuccessful"
                      @change="updateStartupUseLastSuccessful($event.target.checked)"
                    />
                  </div>
                </div>
              </div>

              <div class="mc-settings-row">
                <div class="mc-settings-row-label">
                  <strong>{{ t('settings.nodeCompanion.connection.accessAllContacts.title') }}</strong>
                  <span>{{ t('settings.nodeCompanion.connection.accessAllContacts.subtitle') }}</span>
                </div>
                <div class="mc-settings-row-control">
                  <div class="mc-settings-checkbox">
                    <input
                      type="checkbox"
                      :checked="nodeConnectionRenderModel.accessAllMeshcoriumContacts"
                      @change="updateAccessAllMeshcoriumContacts($event.target.checked)"
                    />
                  </div>
                </div>
              </div>

            </div>
          </section>

          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.nodeCompanion.connection.history.title') }}</h3>
              <p>{{ t('settings.nodeCompanion.connection.history.subtitle') }}</p>
            </div>
            <div class="mc-connect-history-list mc-connect-history-list--settings">
              <button
                v-for="profile in nodeConnectionRenderModel.historyProfiles"
                :key="profile.key"
                class="mc-connect-history-card"
                type="button"
                @click="selectSavedConnectionStartupProfile(profile.raw)"
              >
                <div class="mc-connect-history-preview">
                  <img
                    v-if="profile.previewUrl"
                    :src="profile.previewUrl"
                    alt=""
                  />
                  <span v-else>◈</span>
                </div>
                <div class="mc-connect-history-main">
                  <div class="mc-connect-history-top">
                    <strong>{{ profile.displayName }}</strong>
                    <span class="mc-connect-history-kind">{{ profile.raw.connection_type || t('common.usb') }}</span>
                  </div>
                  <div class="mc-connect-history-bottom">
                    <span>{{ profile.modelName }}</span>
                    <span>{{ profile.port }}</span>
                    <span>{{ profile.baudrate }}</span>
                  </div>
                </div>
              </button>
              <div v-if="!nodeConnectionRenderModel.historyProfiles.length" class="mc-connect-history-empty">{{ t('settings.nodeCompanion.connection.history.empty') }}</div>
            </div>
          </section>

          <section class="mc-settings-panel mc-settings-panel--note">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.nodeCompanion.connection.note.title') }}</h3>
              <p>{{ nodeConnectionRenderModel.connectionNote }}</p>
            </div>
          </section>
        </div>

        <div
          v-else-if="activeNodeCompanionSectionId === 'meshcore-params'"
          key="node-meshcore-params"
          class="mc-settings-section-stack"
          data-node-companion-section="meshcore-params"
        >
          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ activeMeshcoreParamsSection.title }}</h3>
              <p>{{ activeMeshcoreParamsSection.subtitle }}</p>
            </div>

            <div class="mc-settings-rows">
              <div class="mc-settings-row">
                <div class="mc-settings-row-label">
                  <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.snapshot') }}</strong>
                  <span>{{ t(`settings.nodeCompanion.meshcoreParams.groups.${meshcoreParamsGroupKey}.previewBody`) }}</span>
                </div>
                <div class="mc-settings-row-control">
                  <button class="mc-secondary-button" type="button" :disabled="meshcoreParamsLoading || !meshcoreParamsAvailable" @click="loadMeshcoreParams()">
                    {{ meshcoreParamsLoading ? t('settings.nodeCompanion.meshcoreParams.loading') : t('settings.nodeCompanion.meshcoreParams.refresh') }}
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section v-if="!meshcoreParamsAvailable" class="mc-settings-panel mc-settings-panel--note">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.nodeCompanion.meshcoreParams.unavailableTitle') }}</h3>
              <p>{{ t('settings.nodeCompanion.meshcoreParams.unavailableBody') }}</p>
            </div>
          </section>

          <template v-else-if="meshcoreParamsPayload">
            <section v-if="activeMeshcoreParamsSection.id === 'radio'" class="mc-settings-panel">
              <div class="mc-settings-panel-copy">
                <h3>{{ t('settings.nodeCompanion.meshcoreParams.cards.radio.title') }}</h3>
                <p>{{ t('settings.nodeCompanion.meshcoreParams.cards.radio.body') }}</p>
              </div>
              <div class="mc-settings-rows">
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.frequency') }}</strong>
                    <span>
                      {{ t('settings.nodeCompanion.meshcoreParams.fields.maxTxPower') }}: {{ meshcoreParamsRadio.max_tx_power ?? t('common.na') }}
                      · {{ t('settings.nodeCompanion.meshcoreParams.fields.frequencyRange') }}
                    </span>
                  </div>
                  <div class="mc-settings-row-control">
                    <input
                      v-model="meshcoreParamsRadioDraft.freq_mhz"
                      class="mc-settings-native-select"
                      type="number"
                      :min="meshcoreParamsRadioConstraints.freq_mhz_min ?? 300"
                      :max="meshcoreParamsRadioConstraints.freq_mhz_max ?? 2500"
                      step="0.001"
                    />
                  </div>
                </label>
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.bandwidth') }}</strong>
                    <span>
                      {{ t('settings.nodeCompanion.meshcoreParams.fields.allowedRepeatRanges') }}
                      <template v-if="Array.isArray(meshcoreParamsRadio.allowed_repeat_ranges) && meshcoreParamsRadio.allowed_repeat_ranges.length">
                        : {{ meshcoreParamsRadio.allowed_repeat_ranges.map((item) => `${item.lower_freq_mhz}-${item.upper_freq_mhz} MHz`).join(', ') }}
                      </template>
                    </span>
                  </div>
                  <div class="mc-settings-row-control">
                    <input
                      v-model="meshcoreParamsRadioDraft.bw_khz"
                      class="mc-settings-native-select"
                      type="number"
                      :min="meshcoreParamsRadioConstraints.bw_khz_min ?? 7"
                      :max="meshcoreParamsRadioConstraints.bw_khz_max ?? 500"
                      step="0.1"
                    />
                  </div>
                </label>
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.sf') }}</strong>
                    <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.cr') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <div class="mc-settings-inline-controls">
                      <select v-model="meshcoreParamsRadioDraft.sf" class="mc-settings-native-select">
                        <option v-for="value in [5, 6, 7, 8, 9, 10, 11, 12]" :key="`sf-${value}`" :value="value">{{ value }}</option>
                      </select>
                      <select v-model="meshcoreParamsRadioDraft.cr" class="mc-settings-native-select">
                        <option v-for="value in [5, 6, 7, 8]" :key="`cr-${value}`" :value="value">{{ value }}</option>
                      </select>
                    </div>
                  </div>
                </label>
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.txPower') }}</strong>
                    <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.clientRepeat') }}</span>
                  </div>
                  <div class="mc-settings-row-control mc-settings-row-control--stack">
                    <input
                      v-model="meshcoreParamsRadioDraft.tx_power_dbm"
                      class="mc-settings-native-select"
                      type="number"
                      :min="meshcoreParamsRadioConstraints.tx_power_dbm_min ?? -9"
                      :max="meshcoreParamsRadioConstraints.tx_power_dbm_max ?? meshcoreParamsRadio.max_tx_power ?? 30"
                      step="1"
                    />
                    <label class="mc-settings-inline-toggle">
                      <input
                        v-model="meshcoreParamsRadioDraft.client_repeat"
                        type="checkbox"
                        :disabled="meshcoreParamsRadioConstraints.client_repeat_requires_allowed_range && !meshcoreParamsRadio.client_repeat_allowed"
                      />
                      <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.clientRepeat') }}</span>
                    </label>
                    <span
                      v-if="meshcoreParamsRadioConstraints.client_repeat_requires_allowed_range && !meshcoreParamsRadio.client_repeat_allowed"
                      class="mc-settings-inline-hint"
                    >
                      {{ t('settings.nodeCompanion.meshcoreParams.notes.clientRepeatUnavailable') }}
                    </span>
                  </div>
                </label>
              </div>
              <div class="mc-settings-card-actions">
                <button class="mc-primary-button" type="button" :disabled="meshcoreParamsBusyMode === 'radio'" @click="applyMeshcoreRadioParams">
                  {{ meshcoreParamsBusyMode === 'radio' ? t('settings.nodeCompanion.actions.applying') : t('settings.nodeCompanion.actions.apply') }}
                </button>
              </div>
            </section>

            <section v-else-if="activeMeshcoreParamsSection.id === 'identity'" class="mc-settings-panel">
              <div class="mc-settings-panel-copy">
                <h3>{{ t('settings.nodeCompanion.meshcoreParams.cards.identity.title') }}</h3>
                <p>{{ t('settings.nodeCompanion.meshcoreParams.cards.identity.body') }}</p>
              </div>
              <div class="mc-settings-rows">
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.name') }}</strong>
                    <span>
                      {{ t('settings.nodeCompanion.meshcoreParams.fields.publicKey') }}: {{ meshcoreParamsIdentity.public_key || t('common.na') }}
                      <template v-if="meshcoreParamsIdentityConstraints.name_max_utf8_bytes">
                        · {{ t('settings.nodeCompanion.meshcoreParams.fields.nameMaxBytes', { count: meshcoreParamsIdentityConstraints.name_max_utf8_bytes }) }}
                      </template>
                    </span>
                  </div>
                  <div class="mc-settings-row-control">
                      <input v-model="meshcoreParamsIdentityDraft.name" class="mc-settings-native-select" type="text" />
                  </div>
                </label>
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.latitude') }}</strong>
                    <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.longitude') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <div class="mc-settings-inline-controls">
                      <input
                        v-model="meshcoreParamsIdentityDraft.lat"
                        class="mc-settings-native-select"
                        type="number"
                        :min="meshcoreParamsIdentityConstraints.lat_min ?? -90"
                        :max="meshcoreParamsIdentityConstraints.lat_max ?? 90"
                        step="0.000001"
                      />
                      <input
                        v-model="meshcoreParamsIdentityDraft.lon"
                        class="mc-settings-native-select"
                        type="number"
                        :min="meshcoreParamsIdentityConstraints.lon_min ?? -180"
                        :max="meshcoreParamsIdentityConstraints.lon_max ?? 180"
                        step="0.000001"
                      />
                    </div>
                  </div>
                </label>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.deviceModel') }}</strong>
                    <span>{{ meshcoreParamsIdentity.manufacturer_model || t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.deviceTime') }}</strong>
                    <span>{{ meshcoreParamsIdentity.device_time_utc || t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.firmware') }}</strong>
                    <span>{{ meshcoreParamsIdentity.semantic_version || t('common.na') }}</span>
                  </div>
                </div>
              </div>
              <div class="mc-settings-card-actions">
                <button class="mc-primary-button" type="button" :disabled="meshcoreParamsBusyMode === 'identity'" @click="applyMeshcoreIdentityParams">
                  {{ meshcoreParamsBusyMode === 'identity' ? t('settings.nodeCompanion.actions.applying') : t('settings.nodeCompanion.actions.apply') }}
                </button>
                <button
                  class="mc-button mc-button--ghost"
                  type="button"
                  :disabled="!meshcoreParamsAvailable || nodeCompanionSyncingTime"
                  @click="syncNodeCompanionTime"
                >
                  {{ nodeCompanionSyncingTime ? t('settings.nodeCompanion.actions.syncingTime') : t('settings.nodeCompanion.actions.syncTime') }}
                </button>
                <button
                  class="mc-button mc-button--ghost"
                  type="button"
                  :disabled="!meshcoreParamsAvailable || nodeCompanionSendingAdvert"
                  @click="sendNodeCompanionAdvert"
                >
                  {{ nodeCompanionSendingAdvert ? t('settings.nodeCompanion.actions.sendingAdvert') : t('advert.actions.direct') }}
                </button>
                <button
                  class="mc-button mc-button--ghost"
                  type="button"
                  :disabled="!meshcoreParamsAvailable || nodeCompanionSendingAdvert"
                  @click="sendNodeCompanionFloodAdvert"
                >
                  {{ nodeCompanionSendingAdvert ? t('settings.nodeCompanion.actions.sendingAdvert') : t('advert.actions.flood') }}
                </button>
              </div>
            </section>

            <section v-else-if="activeMeshcoreParamsSection.id === 'routing'" class="mc-settings-panel">
              <div class="mc-settings-panel-copy">
                <h3>{{ t('settings.nodeCompanion.meshcoreParams.cards.routing.title') }}</h3>
                <p>{{ t('settings.nodeCompanion.meshcoreParams.cards.routing.body') }}</p>
              </div>
              <div class="mc-settings-rows">
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.multiAcks') }}</strong>
                    <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.manualAddOnly') }}</span>
                  </div>
                  <div class="mc-settings-row-control mc-settings-row-control--stack">
                    <input
                      v-model="meshcoreParamsRoutingDraft.multi_acks"
                      class="mc-settings-native-select"
                      type="number"
                      :min="meshcoreParamsRoutingConstraints.multi_acks_min ?? 0"
                      :max="meshcoreParamsRoutingConstraints.multi_acks_max ?? 1"
                      step="1"
                    />
                    <label class="mc-settings-inline-toggle">
                      <input v-model="meshcoreParamsRoutingDraft.manual_add_only" type="checkbox" />
                      <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.manualAddOnly') }}</span>
                    </label>
                  </div>
                </label>
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.telemetryBase') }}</strong>
                    <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.telemetryLocation') }} / {{ t('settings.nodeCompanion.meshcoreParams.fields.telemetryEnvironment') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <div class="mc-settings-inline-controls">
                      <select v-model="meshcoreParamsRoutingDraft.telemetry_mode_base" class="mc-settings-native-select">
                        <option v-for="option in meshcoreTelemetryModeOptions" :key="`tele-base-${option.value}`" :value="option.value">{{ option.label }}</option>
                      </select>
                      <select v-model="meshcoreParamsRoutingDraft.telemetry_mode_loc" class="mc-settings-native-select">
                        <option v-for="option in meshcoreTelemetryModeOptions" :key="`tele-loc-${option.value}`" :value="option.value">{{ option.label }}</option>
                      </select>
                      <select v-model="meshcoreParamsRoutingDraft.telemetry_mode_env" class="mc-settings-native-select">
                        <option v-for="option in meshcoreTelemetryModeOptions" :key="`tele-env-${option.value}`" :value="option.value">{{ option.label }}</option>
                      </select>
                    </div>
                  </div>
                </label>
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.rxDelayBase') }}</strong>
                    <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.airtimeFactor') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <div class="mc-settings-inline-controls">
                      <input
                        v-model="meshcoreParamsRoutingDraft.rx_delay_base"
                        class="mc-settings-native-select"
                        type="number"
                        :min="meshcoreParamsRoutingConstraints.rx_delay_base_min ?? 0"
                        :max="meshcoreParamsRoutingConstraints.rx_delay_base_max ?? 20"
                        step="0.001"
                      />
                      <input
                        v-model="meshcoreParamsRoutingDraft.airtime_factor"
                        class="mc-settings-native-select"
                        type="number"
                        :min="meshcoreParamsRoutingConstraints.airtime_factor_min ?? 0"
                        :max="meshcoreParamsRoutingConstraints.airtime_factor_max ?? 9"
                        step="0.001"
                      />
                    </div>
                  </div>
                </label>
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.pathHashMode') }}</strong>
                    <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.autoaddMaxHops') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <div class="mc-settings-inline-controls">
                      <select v-model="meshcoreParamsRoutingDraft.path_hash_mode" class="mc-settings-native-select">
                        <option v-for="option in meshcorePathHashModeOptions" :key="`path-${option.value}`" :value="option.value">{{ option.label }}</option>
                      </select>
                      <input
                        v-model="meshcoreParamsRoutingDraft.autoadd_max_hops"
                        class="mc-settings-native-select"
                        type="number"
                        :min="meshcoreParamsRoutingConstraints.autoadd_max_hops_min ?? 0"
                        :max="meshcoreParamsRoutingConstraints.autoadd_max_hops_max ?? 64"
                        step="1"
                      />
                    </div>
                  </div>
                </label>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.autoaddFlags') }}</strong>
                    <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.autoaddBody') }}</span>
                  </div>
                  <div class="mc-settings-row-control mc-settings-row-control--stack">
                    <label class="mc-settings-inline-toggle"><input v-model="meshcoreParamsRoutingDraft.autoadd_overwrite_oldest" type="checkbox" /><span>{{ t('settings.nodeCompanion.meshcoreParams.fields.autoaddOverwriteOldest') }}</span></label>
                    <label class="mc-settings-inline-toggle"><input v-model="meshcoreParamsRoutingDraft.autoadd_chat" type="checkbox" /><span>{{ t('settings.nodeCompanion.meshcoreParams.fields.autoaddChat') }}</span></label>
                    <label class="mc-settings-inline-toggle"><input v-model="meshcoreParamsRoutingDraft.autoadd_repeater" type="checkbox" /><span>{{ t('settings.nodeCompanion.meshcoreParams.fields.autoaddRepeater') }}</span></label>
                    <label class="mc-settings-inline-toggle"><input v-model="meshcoreParamsRoutingDraft.autoadd_room_server" type="checkbox" /><span>{{ t('settings.nodeCompanion.meshcoreParams.fields.autoaddRoomServer') }}</span></label>
                    <label class="mc-settings-inline-toggle"><input v-model="meshcoreParamsRoutingDraft.autoadd_sensor" type="checkbox" /><span>{{ t('settings.nodeCompanion.meshcoreParams.fields.autoaddSensor') }}</span></label>
                  </div>
                </div>
              </div>
              <div class="mc-settings-card-actions">
                <button class="mc-primary-button" type="button" :disabled="meshcoreParamsBusyMode === 'routing'" @click="applyMeshcoreRoutingParams">
                  {{ meshcoreParamsBusyMode === 'routing' ? t('settings.nodeCompanion.actions.applying') : t('settings.nodeCompanion.actions.apply') }}
                </button>
              </div>
            </section>

            <section v-else-if="activeMeshcoreParamsSection.id === 'security'" class="mc-settings-panel">
              <div class="mc-settings-panel-copy">
                <h3>{{ t('settings.nodeCompanion.meshcoreParams.cards.security.title') }}</h3>
                <p>{{ t('settings.nodeCompanion.meshcoreParams.cards.security.body') }}</p>
              </div>
              <div class="mc-settings-rows">
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.blePin') }}</strong>
                    <span>{{ t('settings.nodeCompanion.meshcoreParams.notes.securityUnsupported') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <input
                      v-model="meshcoreParamsSecurityDraft.ble_pin"
                      class="mc-settings-native-select"
                      type="number"
                      :min="meshcoreParamsSecurityConstraints.ble_pin_zero_allowed ? 0 : (meshcoreParamsSecurityConstraints.ble_pin_min ?? 100000)"
                      :max="meshcoreParamsSecurityConstraints.ble_pin_max ?? 999999"
                      step="1"
                    />
                  </div>
                </label>
              </div>
              <div class="mc-settings-card-actions">
                <button class="mc-primary-button" type="button" :disabled="meshcoreParamsBusyMode === 'security'" @click="applyMeshcoreSecurityParams">
                  {{ meshcoreParamsBusyMode === 'security' ? t('settings.nodeCompanion.actions.applying') : t('settings.nodeCompanion.actions.apply') }}
                </button>
              </div>
            </section>

            <section v-else-if="activeMeshcoreParamsSection.id === 'region-gps'" class="mc-settings-panel">
              <div class="mc-settings-panel-copy">
                <h3>{{ t('settings.nodeCompanion.meshcoreParams.cards.regionGps.title') }}</h3>
                <p>{{ t('settings.nodeCompanion.meshcoreParams.cards.regionGps.body') }}</p>
              </div>
              <div class="mc-settings-rows">
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.gpsEnabled') }}</strong>
                    <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.gpsInterval') }}</span>
                  </div>
                  <div class="mc-settings-row-control mc-settings-row-control--stack">
                    <label class="mc-settings-inline-toggle">
                      <input v-model="meshcoreParamsRegionGpsDraft.gps_enabled" type="checkbox" />
                      <span>{{ t('settings.nodeCompanion.meshcoreParams.fields.gpsEnabled') }}</span>
                    </label>
                    <input
                      v-model="meshcoreParamsRegionGpsDraft.gps_interval"
                      class="mc-settings-native-select"
                      type="number"
                      :min="meshcoreParamsRegionGpsConstraints.gps_interval_min ?? 0"
                      :max="meshcoreParamsRegionGpsConstraints.gps_interval_max ?? 86400"
                      step="1"
                    />
                  </div>
                </div>
                <label class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.advertPolicy') }}</strong>
                    <span>{{ t('settings.nodeCompanion.meshcoreParams.notes.regionUnsupported') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <select v-model="meshcoreParamsRegionGpsDraft.advert_loc_policy" class="mc-settings-native-select">
                      <option v-for="option in meshcoreAdvertLocPolicyOptions" :key="`advert-${option.value}`" :value="option.value">{{ option.label }}</option>
                    </select>
                  </div>
                </label>
              </div>
              <div class="mc-settings-card-actions">
                <button class="mc-primary-button" type="button" :disabled="meshcoreParamsBusyMode === 'region-gps'" @click="applyMeshcoreRegionGpsParams">
                  {{ meshcoreParamsBusyMode === 'region-gps' ? t('settings.nodeCompanion.actions.applying') : t('settings.nodeCompanion.actions.apply') }}
                </button>
              </div>
            </section>

            <section v-else-if="activeMeshcoreParamsSection.id === 'bridge-hardware'" class="mc-settings-panel mc-settings-panel--note">
              <div class="mc-settings-panel-copy">
                <h3>{{ t('settings.nodeCompanion.meshcoreParams.cards.bridgeHardware.title') }}</h3>
                <p>{{ t('settings.nodeCompanion.meshcoreParams.notes.bridgeReadonly') }}</p>
              </div>
              <div class="mc-settings-rows">
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.deviceModel') }}</strong>
                    <span>{{ meshcoreParamsBridgeHardware.manufacturer_model || t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.firmware') }}</strong>
                    <span>{{ meshcoreParamsBridgeHardware.semantic_version || t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.uptime') }}</strong>
                    <span>{{ formatDurationCompact(meshcoreParamsBridgeHardware.core_stats?.uptime_secs) }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.coreQueue') }}</strong>
                    <span>{{ meshcoreParamsBridgeHardware.core_stats?.queue_len ?? t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.coreErrors') }}</strong>
                    <span>{{ meshcoreParamsBridgeHardware.core_stats?.errors ?? t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.batteryMillivolts') }}</strong>
                    <span>{{ meshcoreParamsBridgeHardware.core_stats?.battery_mv ?? t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.packetsReceived') }}</strong>
                    <span>{{ meshcoreParamsBridgeHardware.packet_stats?.received ?? t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.packetsSent') }}</strong>
                    <span>{{ meshcoreParamsBridgeHardware.packet_stats?.sent ?? t('common.na') }}</span>
                  </div>
                </div>
              </div>
              <div class="mc-settings-panel-copy">
                <pre class="mc-settings-json-block">{{ formatJsonPayload(meshcoreParamsBridgeHardware) }}</pre>
              </div>
            </section>

            <section v-else-if="activeMeshcoreParamsSection.id === 'persisted-prefs'" class="mc-settings-panel mc-settings-panel--note">
              <div class="mc-settings-panel-copy">
                <h3>{{ t('settings.nodeCompanion.meshcoreParams.cards.persistedPrefs.title') }}</h3>
                <p>{{ t('settings.nodeCompanion.meshcoreParams.notes.persistedReadonly') }}</p>
              </div>
              <div class="mc-settings-rows">
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.manualAddRaw') }}</strong>
                    <span>{{ formatMeshcoreStateLabel(meshcoreParamsPersistedPrefs.manual_add_contacts_raw & 1) }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.telemetryBase') }}</strong>
                    <span>{{ resolveSettingsOptionLabel(meshcoreTelemetryModeOptions, meshcoreParamsPersistedPrefs.telemetry_modes?.base ?? 0) }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.telemetryLocation') }}</strong>
                    <span>{{ resolveSettingsOptionLabel(meshcoreTelemetryModeOptions, meshcoreParamsPersistedPrefs.telemetry_modes?.location ?? 0) }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.telemetryEnvironment') }}</strong>
                    <span>{{ resolveSettingsOptionLabel(meshcoreTelemetryModeOptions, meshcoreParamsPersistedPrefs.telemetry_modes?.environment ?? 0) }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.clientRepeat') }}</strong>
                    <span>{{ formatMeshcoreStateLabel(meshcoreParamsPersistedPrefs.client_repeat) }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.blePin') }}</strong>
                    <span>{{ meshcoreParamsPersistedPrefs.ble_pin || t('settings.values.notConfigured') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.gpsEnabled') }}</strong>
                    <span>{{ formatMeshcoreStateLabel(meshcoreParamsPersistedPrefs.gps_enabled) }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.gpsInterval') }}</strong>
                    <span>{{ meshcoreParamsPersistedPrefs.gps_interval ?? t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.advertPolicy') }}</strong>
                    <span>{{ resolveSettingsOptionLabel(meshcoreAdvertPolicyOptions, meshcoreParamsPersistedPrefs.advert_loc_policy ?? 0) }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.pathHashMode') }}</strong>
                    <span>{{ resolveSettingsOptionLabel(meshcorePathHashModeOptions, meshcoreParamsPersistedPrefs.path_hash_mode ?? 0) }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.rxDelayBase') }}</strong>
                    <span>{{ meshcoreParamsPersistedPrefs.rx_delay_base ?? t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.airtimeFactor') }}</strong>
                    <span>{{ meshcoreParamsPersistedPrefs.airtime_factor ?? t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.autoaddConfigRaw') }}</strong>
                    <span>{{ meshcoreParamsPersistedPrefs.autoadd_config ?? 0 }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.autoaddMaxHops') }}</strong>
                    <span>{{ meshcoreParamsPersistedPrefs.autoadd_max_hops ?? t('common.na') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.autoaddFlagsEnabled') }}</strong>
                    <span>{{ meshcorePersistedAutoaddLabels.length ? meshcorePersistedAutoaddLabels.join(', ') : t('settings.nodeCompanion.meshcoreParams.fields.noneEnabled') }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.customVars') }}</strong>
                    <span>{{ Object.keys(meshcoreParamsRawCustomVars).length }}</span>
                  </div>
                </div>
                <div class="mc-settings-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('settings.nodeCompanion.meshcoreParams.fields.capabilities') }}</strong>
                    <span>{{ Object.keys(meshcoreParamsCapabilities).length }}</span>
                  </div>
                </div>
              </div>
              <div class="mc-settings-panel-copy">
                <h3>{{ t('settings.nodeCompanion.meshcoreParams.fields.snapshot') }}</h3>
                <pre class="mc-settings-json-block">{{ formatJsonPayload(meshcoreParamsPersistedPrefs) }}</pre>
              </div>
              <div class="mc-settings-panel-copy">
                <h3>{{ t('settings.nodeCompanion.meshcoreParams.fields.customVars') }}</h3>
                <pre class="mc-settings-json-block">{{ formatJsonPayload(meshcoreParamsRawCustomVars) }}</pre>
              </div>
              <div class="mc-settings-panel-copy">
                <h3>{{ t('settings.nodeCompanion.meshcoreParams.fields.capabilities') }}</h3>
                <pre class="mc-settings-json-block">{{ formatJsonPayload(meshcoreParamsCapabilities) }}</pre>
              </div>
            </section>
          </template>

          <section v-else class="mc-settings-panel mc-settings-panel--note">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.nodeCompanion.meshcoreParams.loading') }}</h3>
              <p>{{ t('settings.nodeCompanion.meshcoreParams.note.body') }}</p>
            </div>
          </section>

          <section class="mc-settings-panel mc-settings-panel--note">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.nodeCompanion.meshcoreParams.note.title') }}</h3>
              <p>{{ t('settings.nodeCompanion.meshcoreParams.note.body') }}</p>
            </div>
          </section>
          <section v-if="meshcoreParamsCompanionCliRescueOnly" class="mc-settings-panel mc-settings-panel--note">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.nodeCompanion.meshcoreParams.note.cliLimitTitle') }}</h3>
              <p>{{ t('settings.nodeCompanion.meshcoreParams.note.cliLimitBody') }}</p>
            </div>
          </section>
        </div>

        <div
          v-else
          key="node-general"
          class="mc-settings-section-stack"
          data-node-companion-section="general"
        >
          <section class="mc-settings-panel mc-settings-panel--node-tools">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.sections.node.title') }}</h3>
              <p>{{ t('settings.nodeCompanion.subtitle') }}</p>
            </div>

            <div class="mc-settings-node-layout">
              <div class="mc-settings-node-main">
              <label class="mc-settings-row">
                <div class="mc-settings-row-label">
                  <strong>{{ t('settings.nodeCompanion.nickname.title') }}</strong>
                  <span>{{ t('settings.nodeCompanion.nickname.subtitle') }}</span>
                </div>
                <div class="mc-settings-row-control mc-settings-row-control--stack">
                  <div class="mc-settings-node-input-wrap">
                    <input
                      v-model="nodeCompanionNameDraft"
                      class="mc-settings-text-input"
                      type="text"
                      maxlength="32"
                      :placeholder="t('settings.nodeCompanion.nickname.placeholder')"
                      :disabled="!nodeCompanionAvailable || nodeCompanionSaving"
                    />
                    <button
                      class="mc-button mc-button--primary"
                      type="button"
                      :disabled="!nodeCompanionAvailable || nodeCompanionSaving"
                      @click="saveNodeCompanionName"
                    >
                      {{ nodeCompanionSaving ? t('settings.nodeCompanion.actions.applying') : t('settings.nodeCompanion.actions.apply') }}
                    </button>
                  </div>
                </div>
              </label>

              <div class="mc-settings-node-actions">
                <button
                  class="mc-button mc-button--ghost"
                  type="button"
                  :disabled="!nodeCompanionAvailable || nodeCompanionSyncingTime"
                  @click="syncNodeCompanionTime"
                >
                  {{ nodeCompanionSyncingTime ? t('settings.nodeCompanion.actions.syncingTime') : t('settings.nodeCompanion.actions.syncTime') }}
                </button>
                <button
                  class="mc-button mc-button--ghost"
                  type="button"
                  :disabled="!nodeCompanionAvailable"
                  @click="toggleNodeCompanionListener"
                >
                  {{ nodeCompanionListenerLabel }}
                </button>
                <button
                  class="mc-button mc-button--ghost"
                  type="button"
                  :disabled="!nodeCompanionAvailable || nodeCompanionSendingAdvert"
                  @click="sendNodeCompanionAdvert"
                >
                  {{ nodeCompanionSendingAdvert ? t('settings.nodeCompanion.actions.sendingAdvert') : t('settings.nodeCompanion.actions.sendAdvert') }}
                </button>
                <button
                  class="mc-button mc-button--ghost"
                  type="button"
                  :disabled="!nodeCompanionAvailable || nodeCompanionRefreshingContacts"
                  @click="refreshNodeCompanionContacts"
                >
                  {{ nodeCompanionRefreshingContacts ? t('settings.nodeCompanion.actions.refreshingContacts') : t('settings.nodeCompanion.actions.refreshContacts') }}
                </button>
              </div>
            </div>

            <aside class="mc-settings-node-summary">
              <div class="mc-settings-node-preview">
                <img
                  v-if="nodeCompanionPreviewUrl"
                  class="mc-settings-node-preview-image"
                  :src="nodeCompanionPreviewUrl"
                  :alt="nodeCompanionModelSummary"
                />
                <div v-else class="mc-settings-node-preview-fallback">{{ t('settings.nodeCompanion.summary.noPreview') }}</div>
              </div>

              <div class="mc-settings-node-summary-table">
                <div class="mc-settings-node-summary-row">
                  <div class="mc-settings-node-summary-label">{{ t('settings.nodeCompanion.summary.model') }}</div>
                  <div class="mc-settings-node-summary-value">{{ nodeCompanionModelSummary }}</div>
                </div>
                <div class="mc-settings-node-summary-row">
                  <div class="mc-settings-node-summary-label">{{ t('settings.nodeCompanion.summary.firmware') }}</div>
                  <div class="mc-settings-node-summary-value">{{ nodeCompanionFirmwareSummary }}</div>
                </div>
                <div class="mc-settings-node-summary-row">
                  <div class="mc-settings-node-summary-label">{{ t('settings.nodeCompanion.summary.publicKey') }}</div>
                  <div class="mc-settings-node-summary-value">{{ nodeCompanionPublicKeySummary }}</div>
                </div>
                <div class="mc-settings-node-summary-row">
                  <div class="mc-settings-node-summary-label">{{ t('settings.nodeCompanion.summary.contacts') }}</div>
                  <div class="mc-settings-node-summary-value">{{ nodeCompanionContactSummary }}</div>
                </div>
                <div class="mc-settings-node-summary-row">
                  <div class="mc-settings-node-summary-label">{{ t('settings.nodeCompanion.summary.channels') }}</div>
                  <div class="mc-settings-node-summary-value">{{ nodeCompanionChannelSummary }}</div>
                </div>
                <div class="mc-settings-node-summary-row">
                  <div class="mc-settings-node-summary-label">{{ t('settings.nodeCompanion.summary.status') }}</div>
                  <div class="mc-settings-node-summary-value">{{ nodeCompanionStatusSummary }}</div>
                </div>
              </div>
            </aside>
          </div>
        </section>
        </div>
      </template>

      <template v-else-if="activeSettingsSection.id === 'contacts'">
        <section class="mc-settings-panel">
          <div class="mc-settings-panel-copy">
            <h3>{{ t('settings.contacts.nodeTitle') }}</h3>
          </div>

          <div class="mc-settings-contacts-capacity">
            <div class="mc-settings-contacts-capacity-head">
              <strong>{{ contactsAdminSummary.nodeResident }}/{{ contactsAdminSummary.nodeLimit }}</strong>
              <span>{{ contactsAdminUsagePercent }}%</span>
            </div>
            <div class="mc-settings-contacts-capacity-bar">
              <span
                v-for="item in contactsAdminNodeFillItems"
                :key="item.id"
                class="mc-settings-contacts-capacity-fill"
                :class="item.className"
                :style="{ width: `${item.width}%` }"
              ></span>
            </div>
            <div class="mc-settings-contacts-legend">
              <span
                v-for="item in contactsAdminLegendItems"
                :key="item.id"
                class="mc-settings-contacts-legend-item"
              >
                <span class="mc-settings-contacts-legend-dot" :class="item.className"></span>
                <span>{{ item.label }} <strong>{{ contactLegendCount(contactsAdminSummary, 'node', item.countKey) }}</strong></span>
              </span>
            </div>
          </div>
        </section>

        <section class="mc-settings-panel">
          <div class="mc-settings-panel-copy">
            <h3>{{ t('settings.contacts.meshcoriumTitle') }}</h3>
          </div>

          <div class="mc-settings-contacts-capacity mc-settings-contacts-capacity--database">
            <div class="mc-settings-contacts-capacity-head">
              <strong>{{ contactsAdminSummary.dbTotal }}</strong>
            </div>
            <div class="mc-settings-contacts-capacity-bar">
              <span
                v-for="item in contactsMeshcoriumFillItems"
                :key="item.id"
                class="mc-settings-contacts-capacity-fill"
                :class="item.className"
                :style="{ width: `${item.width}%` }"
              ></span>
            </div>
            <div class="mc-settings-contacts-legend">
              <span
                v-for="item in contactsAdminLegendItems"
                :key="item.id"
                class="mc-settings-contacts-legend-item"
              >
                <span class="mc-settings-contacts-legend-dot" :class="item.className"></span>
                <span>{{ item.label }} <strong>{{ contactLegendCount(contactsAdminSummary, 'db', item.countKey) }}</strong></span>
              </span>
            </div>
          </div>
        </section>

      </template>

      <template v-else-if="activeSettingsSection.id === 'debug'">
        <template v-if="activeDebugSectionId === 'messages'">
          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.debug.messages.summary.title') }}</h3>
            </div>
            <div class="mc-settings-message-summary-row">
              <article
                v-for="item in messageDebugSummaryCards"
                :key="item.id"
                class="mc-settings-message-summary-item"
              >
                <div class="mc-settings-message-summary-bubble">
                  <strong>{{ item.value }}</strong>
                </div>
                <span class="mc-settings-message-summary-label">{{ item.label }}</span>
              </article>
            </div>
          </section>

          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.debug.messages.regularTitle') }}</h3>
              <p>{{ t('settings.debug.messages.regularSubtitle') }}</p>
            </div>
            <div class="mc-settings-debug-button-grid">
              <button class="mc-button mc-button--ghost" type="button" :disabled="!session.connected || !session.selectedPort" @click="requestSetAllMessagesReadState(true, 'regular')">
                {{ t('notifications.actions.markRegularRead') }}
              </button>
              <button class="mc-button mc-button--ghost" type="button" :disabled="!session.connected || !session.selectedPort" @click="requestSetAllMessagesReadState(false, 'regular')">
                {{ t('notifications.actions.markRegularUnread') }}
              </button>
            </div>
          </section>

          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.debug.messages.mentionsTitle') }}</h3>
              <p>{{ t('settings.debug.messages.mentionsSubtitle') }}</p>
            </div>
            <div class="mc-settings-debug-button-grid">
              <button class="mc-button mc-button--ghost" type="button" :disabled="!session.connected || !session.selectedPort" @click="requestSetAllMessagesReadState(true, 'mention')">
                {{ t('notifications.actions.markMentionsRead') }}
              </button>
              <button class="mc-button mc-button--ghost" type="button" :disabled="!session.connected || !session.selectedPort" @click="requestSetAllMessagesReadState(false, 'mention')">
                {{ t('notifications.actions.markMentionsUnread') }}
              </button>
            </div>
          </section>

          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.debug.messages.directTitle') }}</h3>
              <p>{{ t('settings.debug.messages.directSubtitle') }}</p>
            </div>
            <div class="mc-settings-debug-button-grid">
              <button class="mc-button mc-button--ghost" type="button" :disabled="!session.connected || !session.selectedPort" @click="requestSetAllMessagesReadState(true, 'direct')">
                {{ t('notifications.actions.markDirectRead') }}
              </button>
              <button class="mc-button mc-button--ghost" type="button" :disabled="!session.connected || !session.selectedPort" @click="requestSetAllMessagesReadState(false, 'direct')">
                {{ t('notifications.actions.markDirectUnread') }}
              </button>
            </div>
          </section>

          <section class="mc-settings-panel mc-settings-panel--danger">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('settings.meshcorium.clearMessages.title') }}</h3>
              <p>{{ t('settings.meshcorium.clearMessages.subtitle') }}</p>
            </div>
            <div class="mc-settings-danger-actions">
              <button class="mc-button mc-button--danger" type="button" @click="openClearMessageDbDialog">
                {{ t('settings.meshcorium.clearMessages.action') }}
              </button>
            </div>
          </section>
        </template>

        <template v-else>
        <section class="mc-settings-panel">
          <div class="mc-settings-panel-copy">
            <h3>{{ t('settings.debug.battery.title') }}</h3>
            <p>{{ batteryDebugNote }}</p>
          </div>
          <pre class="mc-settings-debug-output">{{ formatJsonPayload(batteryDebugPayload) }}</pre>
        </section>

        <section class="mc-settings-panel">
          <div class="mc-settings-panel-copy">
            <h3>{{ t('settings.debug.contacts.title') }}</h3>
            <p>{{ contactDebugNote }}</p>
          </div>
          <div class="mc-settings-debug-actions">
            <button
              class="mc-button mc-button--ghost"
              type="button"
              :disabled="contactDebugLoading || !session.connected || !session.selectedPort"
              @click="loadContactDebugPayload"
            >
              {{ contactDebugLoading ? t('settings.debug.contacts.refreshing') : t('settings.debug.contacts.refresh') }}
            </button>
          </div>
          <pre class="mc-settings-debug-output">{{ contactDebugOutput }}</pre>
        </section>
        </template>
      </template>

      <template v-else-if="activeSettingsSection.id === 'about'">
        <section class="mc-settings-hero-card mc-settings-about-hero">
          <div class="mc-settings-about-hero-head">
            <div class="mc-settings-about-brand">
              <img
                class="mc-settings-about-logo"
                :src="meshcoriumBrandLogoUrl"
                alt="MeshCorium"
              />
              <div class="mc-settings-hero-copy">
                <span class="mc-settings-about-kicker">{{ t('settings.about.brandKicker') }}</span>
                <h3>{{ t('settings.about.title') }}</h3>
                <p>{{ t('settings.about.subtitle') }}</p>
              </div>
            </div>

            <dl class="mc-settings-about-version">
              <dt>{{ t('settings.about.versionLabel') }}</dt>
              <dd>{{ meshcoriumDisplayVersion }}</dd>
            </dl>
          </div>
        </section>

        <section class="mc-settings-panel">
          <div class="mc-settings-panel-copy">
            <h3>{{ t('settings.about.referencesTitle') }}</h3>
            <p>{{ t('settings.about.referencesSubtitle') }}</p>
          </div>
        </section>

        <section
          v-for="group in aboutLinkGroups"
          :key="group.id"
          class="mc-settings-panel"
        >
          <div class="mc-settings-panel-copy">
            <h3>{{ group.title }}</h3>
            <p>{{ group.subtitle }}</p>
          </div>

          <div class="mc-settings-about-list">
            <p
              v-for="entry in group.entries"
              :key="`${group.id}:${entry.name}`"
              class="mc-settings-about-item"
            >
              <strong>{{ entry.name }}</strong>
              <span> {{ entry.version }}.</span>
              <span> </span>
              <a class="mc-settings-inline-link" :href="entry.packageUrl" target="_blank" rel="noreferrer noopener">
                  {{ entry.packageLabel }}
              </a>
              <span> · </span>
              <a class="mc-settings-inline-link" :href="entry.repoUrl" target="_blank" rel="noreferrer noopener">
                  {{ t('settings.about.actions.git') }}
              </a>
            </p>
          </div>
        </section>
      </template>
      </div>
    </template>
  </ShellPageFrame>

  <MessagesConfirmSheet
    :model="confirmSheetModel"
    @close="closeConfirmDialog"
    @submit="submitConfirmDialog"
  />
</template>
