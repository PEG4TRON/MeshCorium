import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useStorage } from '@vueuse/core'

import { i18n } from '../i18n'
import { normalizeStopState } from '../lib/sessionLiveState'

const DEFAULT_TIMEOUT = 4.0
const DEFAULT_BAUDRATE = 115200

function buildUnreadSummary(source = {}) {
  return {
    channel_unread_counts: isPlainObject(source?.channel_unread_counts) ? source.channel_unread_counts : {},
    contact_unread_counts: isPlainObject(source?.contact_unread_counts) ? source.contact_unread_counts : {},
    channel_mention_counts: isPlainObject(source?.channel_mention_counts) ? source.channel_mention_counts : {},
    contact_mention_counts: isPlainObject(source?.contact_mention_counts) ? source.contact_mention_counts : {},
    channel_first_unread_ids: isPlainObject(source?.channel_first_unread_ids) ? source.channel_first_unread_ids : {},
    contact_first_unread_ids: isPlainObject(source?.contact_first_unread_ids) ? source.contact_first_unread_ids : {},
    channel_last_unread_ids: isPlainObject(source?.channel_last_unread_ids) ? source.channel_last_unread_ids : {},
    contact_last_unread_ids: isPlainObject(source?.contact_last_unread_ids) ? source.contact_last_unread_ids : {},
    channel_first_mention_ids: isPlainObject(source?.channel_first_mention_ids) ? source.channel_first_mention_ids : {},
    contact_first_mention_ids: isPlainObject(source?.contact_first_mention_ids) ? source.contact_first_mention_ids : {},
    channel_last_mention_ids: isPlainObject(source?.channel_last_mention_ids) ? source.channel_last_mention_ids : {},
    contact_last_mention_ids: isPlainObject(source?.contact_last_mention_ids) ? source.contact_last_mention_ids : {},
    mention_entries: sanitizeObjectArray(source?.mention_entries),
  }
}

function getNotificationSoundUrl(fileName) {
  const safeName = String(fileName || '').trim()
  return safeName ? `/sounds/${encodeURIComponent(safeName)}` : ''
}

function normalizePort(value) {
  const next = String(value || '').trim()
  return next && next !== '-' ? next : ''
}

function normalizeConnectionDescriptor(source = {}, fallback = {}) {
  const sourceConnection = isPlainObject(source?.connection) ? source.connection : {}
  const fallbackConnection = isPlainObject(fallback?.connection) ? fallback.connection : {}
  const transportType = String(
    sourceConnection.transport_type
    || source?.transport_type
    || fallbackConnection.transport_type
    || fallback?.transport_type
    || 'serial'
  ).trim().toLowerCase() || 'serial'
  const transportId = normalizePort(
    sourceConnection.transport_id
    || sourceConnection.port
    || source?.transport_id
    || source?.port
    || fallbackConnection.transport_id
    || fallbackConnection.port
    || fallback?.transport_id
    || fallback?.port
  )
  const baudrate = Number(
    sourceConnection.baudrate
    || source?.baudrate
    || fallbackConnection.baudrate
    || fallback?.baudrate
    || DEFAULT_BAUDRATE
  ) || DEFAULT_BAUDRATE
  const timeout = Number(
    sourceConnection.timeout
    || source?.timeout
    || fallbackConnection.timeout
    || fallback?.timeout
    || DEFAULT_TIMEOUT
  ) || DEFAULT_TIMEOUT
  return {
    transport_type: transportType,
    transport_id: transportId,
    display_label: String(sourceConnection.display_label || source?.display_label || fallbackConnection.display_label || fallback?.display_label || transportId || '').trim(),
    adapter_id: String(sourceConnection.adapter_id || source?.adapter_id || fallbackConnection.adapter_id || fallback?.adapter_id || '').trim(),
    pin: String(sourceConnection.pin || source?.pin || '').trim(),
    port: transportType === 'serial' ? transportId : normalizePort(source?.port || fallback?.port),
    baudrate,
    timeout,
  }
}

function normalizePublicKeyPrefix(value) {
  return String(value || '').trim().toLowerCase().slice(0, 12)
}

function isPausedSessionStopState(value) {
  const normalized = normalizeStopState(value)
  const stopReason = String(normalized?.stop_reason || normalized?.last_stop_reason || '').trim().toLowerCase()
  return stopReason === 'paused-session'
}

function hasOwnField(payload, key) {
  return Boolean(payload) && Object.prototype.hasOwnProperty.call(payload, key)
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function shallowEqualPlainObject(left, right) {
  if (left === right) {
    return true
  }
  if (!isPlainObject(left) || !isPlainObject(right)) {
    return false
  }
  const leftKeys = Object.keys(left)
  const rightKeys = Object.keys(right)
  if (leftKeys.length !== rightKeys.length) {
    return false
  }
  for (const key of leftKeys) {
    if (!Object.prototype.hasOwnProperty.call(right, key) || !Object.is(left[key], right[key])) {
      return false
    }
  }
  return true
}

function preserveShallowObjectRef(previous, next) {
  if (!isPlainObject(next)) {
    return next || null
  }
  return shallowEqualPlainObject(previous, next) ? previous : next
}

function shallowEqualObjectArray(left, right) {
  if (left === right) {
    return true
  }
  if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) {
    return false
  }
  for (let index = 0; index < left.length; index += 1) {
    const leftItem = left[index]
    const rightItem = right[index]
    if (isPlainObject(leftItem) && isPlainObject(rightItem)) {
      if (!shallowEqualPlainObject(leftItem, rightItem)) {
        return false
      }
      continue
    }
    if (!Object.is(leftItem, rightItem)) {
      return false
    }
  }
  return true
}

function preserveShallowArrayRef(previous, next) {
  if (!Array.isArray(next)) {
    return []
  }
  return shallowEqualObjectArray(previous, next) ? previous : next
}

function sanitizeObjectArray(items) {
  if (!Array.isArray(items)) {
    return []
  }
  return items.filter((item) => isPlainObject(item))
}

function shouldPreserveNonEmptyCollection(previousItems, nextItems, options = {}) {
  const {
    nextActive,
    nextCollectionsReady,
    nextCount,
  } = options
  if (!nextActive) {
    return false
  }
  if (!Array.isArray(previousItems) || !previousItems.length) {
    return false
  }
  if (!Array.isArray(nextItems) || nextItems.length > 0) {
    return false
  }
  if (!nextCollectionsReady) {
    return true
  }
  if (nextCount == null) {
    return true
  }
  return Number(nextCount || 0) > 0
}

export const useSessionStore = defineStore('session', () => {
  const { t } = i18n.global
  const ports = ref([])
  const bleConnections = ref([])
  const bleDiagnostics = ref(null)
  const bleLastScanAt = ref(0)
  const savedConnections = ref([])
  const activeSessions = ref([])
  const recoveringSessions = ref([])
  const resolvedStartupConnection = ref(null)
  const lastSuccessfulConfig = ref(null)
  const settingsPayload = ref(null)
  const sessionSnapshot = ref({ active: false })
  const connectNotice = ref(null)

  // USB compatibility aliases. New transport-aware calls should use
  // selectedConnection/configBody(), while existing Vue surfaces still bind
  // these storage keys until a non-USB transport UI exists.
  const selectedPort = useStorage('selected_port', '')
  const selectedBaudrate = useStorage('selected_baudrate', DEFAULT_BAUDRATE)
  const selectedTransportType = useStorage('selected_transport_type', 'serial')
  const selectedBleDevice = useStorage('selected_ble_device', '')
  const selectedBlePin = ref('')

  const statusText = ref('')
  const statusError = ref(false)
  const loadingClientSettings = ref(false)
  const loadingPorts = ref(false)
  const loadingBleConnections = ref(false)
  const loadingContacts = ref(false)
  const syncingSession = ref(false)
  const connecting = ref(false)
  const messagesHydrating = ref(false)
  const radioTxObservedAt = ref(0)
  const unreadSummary = ref(buildUnreadSummary())
  const unreadSummaryPrimed = ref(false)
  const notificationAudioCache = new Map()
  let contactsRequestPromise = null
  const transientDisconnectSuppressedUntil = ref(0)

  function setStatus(message, isError = false) {
    statusText.value = String(message || '')
    statusError.value = Boolean(isError)
  }

  function showConnectNotice(message, isError = true) {
    connectNotice.value = {
      message: String(message || ''),
      isError: Boolean(isError),
      issuedAt: Date.now(),
    }
  }

  function clearConnectNotice() {
    connectNotice.value = null
  }

  function suppressTransientDisconnect(ms = 12000) {
    transientDisconnectSuppressedUntil.value = Math.max(
      Number(transientDisconnectSuppressedUntil.value || 0),
      Date.now() + Math.max(0, Number(ms) || 0),
    )
  }

  function clearTransientDisconnectSuppression() {
    transientDisconnectSuppressedUntil.value = 0
  }

  function setMessagesHydrating(value) {
    messagesHydrating.value = Boolean(value)
  }

  function getMutedConversationsMap() {
    const source = settingsPayload.value?.settings?.muted_conversations
    return isPlainObject(source) ? source : {}
  }

  function getConversationMuteModeByKey(muteKey) {
    if (!muteKey) {
      return 'none'
    }
    const mode = String(getMutedConversationsMap()[muteKey] || '').trim().toLowerCase()
    return mode === 'regular' || mode === 'all' ? mode : 'none'
  }

  function sumAudibleUnread(summary = {}) {
    const channelUnreadCounts = isPlainObject(summary?.channel_unread_counts) ? summary.channel_unread_counts : {}
    let total = 0
    for (const [channelKey, rawCount] of Object.entries(channelUnreadCounts)) {
      const muteMode = getConversationMuteModeByKey(`channel:${String(channelKey).trim().toLowerCase()}`)
      if (muteMode === 'regular' || muteMode === 'all') {
        continue
      }
      total += Number(rawCount || 0)
    }
    return total
  }

  function sumAudibleMentions(summary = {}) {
    const channelMentionCounts = isPlainObject(summary?.channel_mention_counts) ? summary.channel_mention_counts : {}
    const contactMentionCounts = isPlainObject(summary?.contact_mention_counts) ? summary.contact_mention_counts : {}
    let total = 0
    for (const [channelKey, rawCount] of Object.entries(channelMentionCounts)) {
      const muteMode = getConversationMuteModeByKey(`channel:${String(channelKey).trim().toLowerCase()}`)
      if (muteMode === 'all') {
        continue
      }
      total += Number(rawCount || 0)
    }
    for (const [contactKey, rawCount] of Object.entries(contactMentionCounts)) {
      const muteMode = getConversationMuteModeByKey(`contact:${String(contactKey).trim().toLowerCase()}`)
      if (muteMode === 'all') {
        continue
      }
      total += Number(rawCount || 0)
    }
    return total
  }

  function sumAudibleDirectUnread(summary = {}) {
    const contactUnreadCounts = isPlainObject(summary?.contact_unread_counts) ? summary.contact_unread_counts : {}
    let total = 0
    for (const [contactKey, rawCount] of Object.entries(contactUnreadCounts)) {
      const muteMode = getConversationMuteModeByKey(`contact:${String(contactKey).trim().toLowerCase()}`)
      if (muteMode === 'regular' || muteMode === 'all') {
        continue
      }
      total += Number(rawCount || 0)
    }
    return total
  }

  function getNotificationSoundFile(kind = 'regular') {
    if (kind === 'mention') {
      return String(settingsPayload.value?.settings?.notification_mention_sound_file || '')
    }
    if (kind === 'direct') {
      return String(settingsPayload.value?.settings?.notification_direct_sound_file || '')
    }
    return String(settingsPayload.value?.settings?.notification_regular_sound_file || '')
  }

  function playNotificationSound(kind = 'regular') {
    if (!settingsPayload.value?.settings?.notifications_sound_enabled) {
      return
    }
    if (typeof Audio === 'undefined') {
      return
    }
    const url = getNotificationSoundUrl(getNotificationSoundFile(kind))
    if (!url) {
      return
    }
    const cachedAudio = notificationAudioCache.get(url) || new Audio(url)
    cachedAudio.preload = 'auto'
    notificationAudioCache.set(url, cachedAudio)
    const audio = cachedAudio.cloneNode(true)
    const playPromise = audio.play()
    if (playPromise && typeof playPromise.catch === 'function') {
      playPromise.catch(() => {})
    }
  }

  function maybePlayUnreadSummarySound(previousSummary = {}, nextSummary = {}) {
    if (!connected.value) {
      unreadSummaryPrimed.value = true
      return
    }
    const nextMentions = sumAudibleMentions(nextSummary)
    const previousMentions = sumAudibleMentions(previousSummary)
    const nextDirectUnread = sumAudibleDirectUnread(nextSummary)
    const previousDirectUnread = sumAudibleDirectUnread(previousSummary)
    const nextUnread = sumAudibleUnread(nextSummary)
    const previousUnread = sumAudibleUnread(previousSummary)
    if (!unreadSummaryPrimed.value) {
      unreadSummaryPrimed.value = true
      return
    }
    const soundKinds = []
    if (nextMentions > previousMentions) {
      soundKinds.push('mention')
    }
    if (nextDirectUnread > previousDirectUnread) {
      soundKinds.push('direct')
    }
    if (nextUnread > previousUnread) {
      soundKinds.push('regular')
    }
    for (const kind of soundKinds) {
      playNotificationSound(kind)
    }
  }

  function noteRadioTransmission() {
    radioTxObservedAt.value = Date.now()
  }

  function clearRadioTransmission() {
    radioTxObservedAt.value = 0
  }

  function applyUnreadSummary(data = {}) {
    const nextSummary = buildUnreadSummary(data)
    maybePlayUnreadSummarySound(unreadSummary.value, nextSummary)
    unreadSummary.value = nextSummary
  }

  function patchUnreadSummary(mutator) {
    if (typeof mutator !== 'function') {
      return
    }
    const nextSummary = buildUnreadSummary(unreadSummary.value)
    mutator(nextSummary)
    unreadSummary.value = buildUnreadSummary(nextSummary)
  }

  function clearUnreadSummary() {
    unreadSummary.value = buildUnreadSummary()
    unreadSummaryPrimed.value = false
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(options.headers || {}),
      },
      ...options,
    })
    const raw = await response.text()
    let data = {}
    if (raw) {
      try {
        data = JSON.parse(raw)
      } catch (error) {
        if (response.ok) {
          throw error
        }
        data = {}
      }
    }
    if (response.status === 401 && data?.auth_required) {
      const nextPath = window.location.pathname + window.location.search
      window.location.href = `/login?next=${encodeURIComponent(nextPath)}`
      throw new Error(t('common.authRequired'))
    }
    if (!response.ok) {
      throw new Error(data?.error || `HTTP ${response.status}`)
    }
    return data
  }

  function pickInitialSelection() {
    const storagePort = normalizePort(selectedPort.value)
    const storageBleDevice = normalizePort(selectedBleDevice.value)
    const storageBaudrate = Number(selectedBaudrate.value || DEFAULT_BAUDRATE)
    const startup = resolvedStartupConnection.value || {}
    const lastSuccessful = lastSuccessfulConfig.value || {}
    const firstSaved = savedConnections.value[0] || {}
    const firstPort = ports.value[0]?.transport_id || ports.value[0]?.device || ''
    const startupConnection = normalizeConnectionDescriptor(startup)
    const lastSuccessfulConnection = normalizeConnectionDescriptor(lastSuccessful)
    const firstSavedConnection = normalizeConnectionDescriptor(firstSaved)
    const storedTransportType = String(selectedTransportType.value || '').trim().toLowerCase()
    const nextTransportType = ['serial', 'ble', 'wifi'].includes(storedTransportType)
      ? storedTransportType
      : (startupConnection.transport_type || lastSuccessfulConnection.transport_type || firstSavedConnection.transport_type || 'serial')

    const nextPort = normalizePort(
      storagePort
      || startupConnection.port
      || lastSuccessfulConnection.port
      || firstSavedConnection.port
      || firstPort
    )
    const nextBaudrate = Number(
      storagePort
        ? storageBaudrate
        : startupConnection.baudrate
          || lastSuccessfulConnection.baudrate
          || firstSavedConnection.baudrate
          || DEFAULT_BAUDRATE
    ) || DEFAULT_BAUDRATE

    selectedPort.value = nextPort
    selectedBaudrate.value = nextBaudrate
    selectedTransportType.value = nextTransportType
    if (!storageBleDevice) {
      const nextBleDevice = [startupConnection, lastSuccessfulConnection, firstSavedConnection]
        .find((connection) => connection.transport_type === 'ble' && normalizePort(connection.transport_id))
      if (nextBleDevice) {
        selectedBleDevice.value = normalizePort(nextBleDevice.transport_id)
      }
    }
  }

  function applyClientSettingsPayload(data) {
    settingsPayload.value = preserveShallowObjectRef(settingsPayload.value, data || null)
    savedConnections.value = preserveShallowArrayRef(savedConnections.value, Array.isArray(data?.saved_connections) ? data.saved_connections : [])
    activeSessions.value = preserveShallowArrayRef(activeSessions.value, Array.isArray(data?.active_sessions) ? data.active_sessions : [])
    recoveringSessions.value = preserveShallowArrayRef(recoveringSessions.value, Array.isArray(data?.recovering_sessions) ? data.recovering_sessions : [])
    resolvedStartupConnection.value = preserveShallowObjectRef(resolvedStartupConnection.value, data?.resolved_startup_connection || null)
    lastSuccessfulConfig.value = preserveShallowObjectRef(lastSuccessfulConfig.value, data?.last_successful_config || null)
  }

  async function updateClientSettings(patch = {}) {
    const previousPayload = settingsPayload.value ? JSON.parse(JSON.stringify(settingsPayload.value)) : null
    const nextPatch = { ...(patch || {}) }
    if (settingsPayload.value?.settings) {
      applyClientSettingsPayload({
        ...settingsPayload.value,
        settings: {
          ...settingsPayload.value.settings,
          ...nextPatch,
        },
      })
    }
    try {
      const data = await api('/api/client-settings', {
        method: 'POST',
        body: JSON.stringify(nextPatch),
      })
      applyClientSettingsPayload(data)
      return data
    } catch (error) {
      if (previousPayload) {
        applyClientSettingsPayload(previousPayload)
      }
      throw error
    }
  }

  async function toggleNotificationSoundEnabled() {
    const current = Boolean(settingsPayload.value?.settings?.notifications_sound_enabled)
    return updateClientSettings({
      notifications_sound_enabled: !current,
    })
  }

  function ensureSessionSnapshotObject() {
    if (!sessionSnapshot.value || typeof sessionSnapshot.value !== 'object') {
      sessionSnapshot.value = { active: false }
    }
    return sessionSnapshot.value
  }

  function mutateSessionSnapshot(mutator) {
    const snapshot = ensureSessionSnapshotObject()
    mutator(snapshot)
  }

  function patchSessionSnapshotFields(patch = {}) {
    mutateSessionSnapshot((snapshot) => {
      if (hasOwnField(patch, 'active')) {
        snapshot.active = Boolean(patch?.active)
      }
      if (hasOwnField(patch, 'device')) {
        snapshot.device = preserveShallowObjectRef(snapshot.device, patch?.device || null)
      }
      if (hasOwnField(patch, 'self')) {
        snapshot.self = preserveShallowObjectRef(snapshot.self, patch?.self || null)
      }
      if (hasOwnField(patch, 'contacts')) {
        snapshot.contacts = sanitizeObjectArray(patch?.contacts)
      }
      if (hasOwnField(patch, 'channels')) {
        snapshot.channels = sanitizeObjectArray(patch?.channels)
      }
      if (hasOwnField(patch, 'radio_stats')) {
        snapshot.radio_stats = preserveShallowObjectRef(snapshot.radio_stats, patch?.radio_stats || null)
      }
      if (hasOwnField(patch, 'queue_state')) {
        snapshot.queue_state = preserveShallowObjectRef(snapshot.queue_state, patch?.queue_state || null)
      }
      if (hasOwnField(patch, 'stop_state')) {
        snapshot.stop_state = preserveShallowObjectRef(snapshot.stop_state, normalizeStopState(patch?.stop_state || null))
      }
      if (hasOwnField(patch, 'self_telemetry')) {
        snapshot.self_telemetry = preserveShallowObjectRef(snapshot.self_telemetry, patch?.self_telemetry || null)
      }
      if (hasOwnField(patch, 'battery_info')) {
        snapshot.battery_info = preserveShallowObjectRef(snapshot.battery_info, patch?.battery_info || null)
      }
      if (hasOwnField(patch, 'connection')) {
        snapshot.connection = preserveShallowObjectRef(snapshot.connection, normalizeConnectionDescriptor(patch))
      }
      if (hasOwnField(patch, 'port')) {
        snapshot.port = normalizePort(patch?.port)
      }
      if (hasOwnField(patch, 'baudrate')) {
        snapshot.baudrate = Number(patch?.baudrate || DEFAULT_BAUDRATE) || DEFAULT_BAUDRATE
      }
      if (hasOwnField(patch, 'transport_type')) {
        snapshot.transport_type = String(patch?.transport_type || 'serial').trim().toLowerCase() || 'serial'
      }
      if (hasOwnField(patch, 'transport_id')) {
        snapshot.transport_id = normalizePort(patch?.transport_id)
      }
      if (hasOwnField(patch, 'collections_ready')) {
        snapshot.collections_ready = Boolean(patch?.collections_ready)
      }
      if (hasOwnField(patch, 'contacts_count')) {
        snapshot.contacts_count = patch?.contacts_count ?? null
      }
      if (hasOwnField(patch, 'contact_summary')) {
        snapshot.contact_summary = preserveShallowObjectRef(snapshot.contact_summary, patch?.contact_summary || null)
      }
      if (hasOwnField(patch, 'channels_count')) {
        snapshot.channels_count = patch?.channels_count ?? null
      }
      if (hasOwnField(patch, 'recent_repeaters_count')) {
        snapshot.recent_repeaters_count = patch?.recent_repeaters_count ?? null
      }
    })
  }

  function updateChannelSnapshot(channelIdx, patch = {}) {
    const normalizedIdx = Number(channelIdx)
    if (!Number.isFinite(normalizedIdx)) {
      return false
    }
    let updated = false
    mutateSessionSnapshot((snapshot) => {
      const channelsList = Array.isArray(snapshot.channels) ? snapshot.channels : []
      const target = channelsList.find((channel) => Number(channel?.idx) === normalizedIdx)
      if (!target) {
        return
      }
      Object.assign(target, patch || {})
      snapshot.channels_count = channelsList.length
      updated = true
    })
    return updated
  }

  function updateContactSnapshotByPrefix(prefix, patch = {}) {
    const normalizedPrefix = normalizePublicKeyPrefix(prefix)
    if (!normalizedPrefix) {
      return false
    }
    let updated = false
    mutateSessionSnapshot((snapshot) => {
      const contactsList = Array.isArray(snapshot.contacts) ? snapshot.contacts : []
      const target = contactsList.find((contact) => normalizePublicKeyPrefix(contact?.pubkey_prefix || contact?.public_key || '') === normalizedPrefix)
      if (!target) {
        return
      }
      Object.assign(target, patch || {})
      snapshot.contacts_count = contactsList.length
      updated = true
    })
    return updated
  }

  function applySessionSnapshot(data) {
    const previous = sessionSnapshot.value || {}
    const incomingStopState = hasOwnField(data, 'stop_state')
      ? normalizeStopState(data?.stop_state || null)
      : (previous?.stop_state || null)
    const requestedActive = Boolean(hasOwnField(data, 'active') ? data?.active : previous?.active)
    const nextActive = requestedActive || isPausedSessionStopState(incomingStopState)
    const nextCollectionsReady = Boolean(hasOwnField(data, 'collections_ready') ? data?.collections_ready : previous?.collections_ready)
    const incomingContacts = hasOwnField(data, 'contacts')
      ? sanitizeObjectArray(data?.contacts)
      : sanitizeObjectArray(previous?.contacts)
    const incomingChannels = hasOwnField(data, 'channels')
      ? sanitizeObjectArray(data?.channels)
      : sanitizeObjectArray(previous?.channels)
    const nextContactsCount = hasOwnField(data, 'contacts_count') ? (data?.contacts_count ?? null) : (previous?.contacts_count ?? null)
    const nextContactSummary = hasOwnField(data, 'contact_summary')
      ? preserveShallowObjectRef(previous?.contact_summary, data?.contact_summary || null)
      : (previous?.contact_summary || null)
    const nextChannelsCount = hasOwnField(data, 'channels_count') ? (data?.channels_count ?? null) : (previous?.channels_count ?? null)
    const nextRecentRepeatersCount = hasOwnField(data, 'recent_repeaters_count')
      ? (data?.recent_repeaters_count ?? null)
      : (previous?.recent_repeaters_count ?? null)
    const nextContacts = shouldPreserveNonEmptyCollection(previous?.contacts, incomingContacts, {
      nextActive,
      nextCollectionsReady,
      nextCount: nextContactsCount,
    })
      ? previous.contacts
      : incomingContacts
    const nextChannels = shouldPreserveNonEmptyCollection(previous?.channels, incomingChannels, {
      nextActive,
      nextCollectionsReady,
      nextCount: nextChannelsCount,
    })
      ? previous.channels
      : incomingChannels
    sessionSnapshot.value = {
      active: nextActive,
      device: hasOwnField(data, 'device')
        ? preserveShallowObjectRef(previous?.device, data?.device || null)
        : (previous?.device || null),
      self: hasOwnField(data, 'self')
        ? preserveShallowObjectRef(previous?.self, data?.self || null)
        : (previous?.self || null),
      contacts: nextContacts,
      channels: nextChannels,
      radio_stats: hasOwnField(data, 'radio_stats')
        ? preserveShallowObjectRef(previous?.radio_stats, data?.radio_stats || null)
        : (previous?.radio_stats || null),
      queue_state: hasOwnField(data, 'queue_state')
        ? preserveShallowObjectRef(previous?.queue_state, data?.queue_state || null)
        : (previous?.queue_state || null),
      stop_state: preserveShallowObjectRef(previous?.stop_state, incomingStopState),
      self_telemetry: hasOwnField(data, 'self_telemetry')
        ? preserveShallowObjectRef(previous?.self_telemetry, data?.self_telemetry || null)
        : (previous?.self_telemetry || null),
      battery_info: hasOwnField(data, 'battery_info')
        ? preserveShallowObjectRef(previous?.battery_info, data?.battery_info || null)
        : (previous?.battery_info || null),
      connection: hasOwnField(data, 'connection')
        ? preserveShallowObjectRef(previous?.connection, normalizeConnectionDescriptor(data, previous))
        : (previous?.connection || null),
      port: hasOwnField(data, 'port') ? normalizePort(data?.port) : normalizePort(previous?.port),
      baudrate: hasOwnField(data, 'baudrate') ? (Number(data?.baudrate || DEFAULT_BAUDRATE) || DEFAULT_BAUDRATE) : (Number(previous?.baudrate || DEFAULT_BAUDRATE) || DEFAULT_BAUDRATE),
      transport_type: hasOwnField(data, 'transport_type') ? (String(data?.transport_type || 'serial').trim().toLowerCase() || 'serial') : (previous?.transport_type || 'serial'),
      transport_id: hasOwnField(data, 'transport_id') ? normalizePort(data?.transport_id) : normalizePort(previous?.transport_id || previous?.port),
      collections_ready: nextCollectionsReady,
      contacts_count: nextContactsCount,
      contact_summary: nextContactSummary,
      channels_count: nextChannelsCount,
      recent_repeaters_count: nextRecentRepeatersCount,
    }
  }

  async function loadClientSettings() {
    loadingClientSettings.value = true
    try {
      const data = await api('/api/client-settings')
      applyClientSettingsPayload(data)
      pickInitialSelection()
      return data
    } finally {
      loadingClientSettings.value = false
    }
  }

  async function refreshPorts() {
    loadingPorts.value = true
    try {
      const data = await api('/api/ports')
      ports.value = Array.isArray(data?.ports) ? data.ports : []
      if (selectedTransportType.value === 'serial' && !normalizePort(selectedPort.value)) {
        pickInitialSelection()
      }
      if (
        selectedTransportType.value === 'serial'
        && ports.value.length
        && normalizePort(selectedPort.value)
        && !ports.value.some((entry) => normalizePort(entry?.transport_id || entry?.device) === normalizePort(selectedPort.value))
      ) {
        selectedPort.value = normalizePort(ports.value[0]?.transport_id || ports.value[0]?.device || '')
      }
      if (!ports.value.length) {
        setStatus(t('connect.status.noVisiblePorts'), true)
      }
      return ports.value
    } finally {
      loadingPorts.value = false
    }
  }

  async function refreshBleConnections({ timeout = 6 } = {}) {
    loadingBleConnections.value = true
    try {
      const query = new URLSearchParams({
        type: 'ble',
        timeout: String(Math.max(1, Number(timeout || 6))),
      })
      const data = await api(`/api/transports?${query.toString()}`)
      const bleTransport = Array.isArray(data?.transports)
        ? data.transports.find((entry) => String(entry?.transport_type || '') === 'ble')
        : null
      bleLastScanAt.value = Date.now()
      bleConnections.value = Array.isArray(bleTransport?.connections) ? bleTransport.connections : []
      bleDiagnostics.value = bleTransport?.diagnostics || null
      if (bleTransport && bleTransport.available === false) {
        setStatus(bleTransport?.diagnostics?.message || bleTransport?.error || t('connect.ble.scanUnavailable'), true)
      } else if (!bleConnections.value.length) {
        setStatus(t('connect.ble.noDevices'), true)
        if (!bleDiagnostics.value) {
          bleDiagnostics.value = {
            kind: 'scan-empty',
            message: t('connect.ble.noDevices'),
            hints: [
              t('connect.ble.hints.powerCycle'),
              t('connect.ble.hints.ensureAdvertising'),
              t('connect.ble.hints.keepAgentOpen'),
            ],
          }
        }
      } else {
        bleDiagnostics.value = null
      }
      if (!normalizePort(selectedBleDevice.value) && bleConnections.value.length) {
        selectedBleDevice.value = normalizePort(bleConnections.value[0]?.transport_id || bleConnections.value[0]?.address || '')
      }
      return bleConnections.value
    } finally {
      loadingBleConnections.value = false
    }
  }

  function configBody(extra = {}) {
    const connection = selectedConnection.value
    const port = normalizePort(connection.port || connection.transport_id)
    const baudrate = Number(connection.baudrate || DEFAULT_BAUDRATE)
    return {
      connection,
      transport_type: connection.transport_type,
      transport_id: connection.transport_id,
      port,
      baudrate,
      timeout: Number(connection.timeout || DEFAULT_TIMEOUT) || DEFAULT_TIMEOUT,
      ...extra,
    }
  }

  async function syncSessionState({ light = true } = {}) {
    const connection = selectedConnection.value
    const port = normalizePort(connection.port || connection.transport_id)
    if (!port) {
      sessionSnapshot.value = { active: false }
      return sessionSnapshot.value
    }
    syncingSession.value = true
    try {
      const query = new URLSearchParams({
        port,
        light: light ? '1' : '0',
      })
      const data = await api(`/api/session?${query.toString()}`)
      const normalizedStopState = normalizeStopState(data?.stop_state || null)
      if (data?.active) {
        applySessionSnapshot(data)
      } else if (isPausedSessionStopState(normalizedStopState)) {
        patchSessionSnapshotFields({
          active: true,
          queue_state: data?.queue_state || null,
          stop_state: normalizedStopState,
        })
      } else {
        patchSessionSnapshotFields({
          active: false,
          queue_state: data?.queue_state || null,
          stop_state: normalizedStopState,
        })
      }
      return data
    } finally {
      syncingSession.value = false
    }
  }

  async function loadChannels() {
    if (connected.value && !collectionsReady.value) {
      return channels.value
    }
    const data = await api('/api/channels', {
      method: 'POST',
      body: JSON.stringify(configBody()),
    })
    const nextChannels = sanitizeObjectArray(data?.channels)
    patchSessionSnapshotFields({
      active: connected.value,
      channels: nextChannels,
      collections_ready: sessionSnapshot.value?.collections_ready,
      channels_count: nextChannels.length,
    })
    return channels.value
  }

  async function loadContacts({ refresh = false } = {}) {
    if (connected.value && !collectionsReady.value && !refresh) {
      return contacts.value
    }
    if (contactsRequestPromise && !refresh) {
      return contactsRequestPromise
    }
    const request = (async () => {
      loadingContacts.value = true
      try {
        const data = await api('/api/contacts', {
          method: 'POST',
          body: JSON.stringify(configBody({ refresh })),
        })
        const nextContacts = sanitizeObjectArray(data?.contacts)
        patchSessionSnapshotFields({
          active: connected.value,
          contacts: nextContacts,
          collections_ready: sessionSnapshot.value?.collections_ready,
          contacts_count: nextContacts.length,
          contact_summary: data?.contact_summary || null,
        })
        return contacts.value
      } finally {
        loadingContacts.value = false
        if (contactsRequestPromise === request) {
          contactsRequestPromise = null
        }
      }
    })()
    if (!refresh) {
      contactsRequestPromise = request
    }
    return request
  }

  async function loadUnreadSummary({ port = '', mentionName = '' } = {}) {
    const connection = selectedConnection.value
    const resolvedPort = normalizePort(port || connection.port || connection.transport_id)
    if (!resolvedPort || !connected.value) {
      clearUnreadSummary()
      return unreadSummary.value
    }
    const data = await api('/api/messages/unread', {
      method: 'POST',
      body: JSON.stringify({
        port: resolvedPort,
        mention_name: String(mentionName || self.value?.name || ''),
        include_entries: true,
      }),
    })
    applyUnreadSummary(data)
    return unreadSummary.value
  }

  async function connectNode({ light = false } = {}) {
    const connection = selectedConnection.value
    if (connection.transport_type === 'wifi') {
      throw new Error(t('connect.status.wifiUnavailable'))
    }
    const port = normalizePort(connection.port || connection.transport_id)
    if (!port) {
      throw new Error(connection.transport_type === 'ble' ? t('connect.status.bleRequired') : t('connect.status.portRequired'))
    }
    connecting.value = true
    setStatus(t('connect.status.connectingTo', { port: connection.display_label || port }))
    try {
      const payload = await api('/api/connect', {
        method: 'POST',
        body: JSON.stringify(configBody({ light })),
      })
      patchSessionSnapshotFields({
        ...payload,
        active: true,
      })
      await loadClientSettings()
      clearConnectNotice()
      setStatus(t('connect.status.connectedTo', { target: payload?.self?.name || connection.display_label || port }))
      return payload
    } finally {
      connecting.value = false
    }
  }

  async function disconnectNode() {
    const connection = selectedConnection.value
    const port = normalizePort(connection.port || connection.transport_id)
    if (!port) {
      return
    }
    await api('/api/disconnect', {
      method: 'POST',
      body: JSON.stringify(configBody()),
    })
    patchSessionSnapshotFields({ active: false, queue_state: null, stop_state: null })
    clearUnreadSummary()
    clearRadioTransmission()
    setStatus(t('connect.status.disconnected'))
  }

  async function forgetSavedConnection(profileOrKey) {
    const key = isPlainObject(profileOrKey) ? String(profileOrKey?.key || '') : String(profileOrKey || '')
    if (!key.trim()) {
      return settingsPayload.value
    }
    const data = await api('/api/client-settings/forget-connection', {
      method: 'POST',
      body: JSON.stringify({ key }),
    })
    applyClientSettingsPayload(data)
    return data
  }

  const connected = computed(() => {
    return Boolean(sessionSnapshot.value?.active) || isPausedSessionStopState(sessionSnapshot.value?.stop_state || null)
  })
  const device = computed(() => sessionSnapshot.value?.device || null)
  const self = computed(() => sessionSnapshot.value?.self || null)
  const contacts = computed(() => Array.isArray(sessionSnapshot.value?.contacts) ? sessionSnapshot.value.contacts : [])
  const channels = computed(() => Array.isArray(sessionSnapshot.value?.channels) ? sessionSnapshot.value.channels : [])
  const radioStats = computed(() => sessionSnapshot.value?.radio_stats || null)
  const queueState = computed(() => sessionSnapshot.value?.queue_state || null)
  const stopState = computed(() => sessionSnapshot.value?.stop_state || null)
  const selfTelemetry = computed(() => sessionSnapshot.value?.self_telemetry || null)
  const batteryInfo = computed(() => sessionSnapshot.value?.battery_info || null)
  const recentRepeaterCount = computed(() => Math.max(0, Number(sessionSnapshot.value?.recent_repeaters_count || 0)))
  const collectionsReady = computed(() => Boolean(sessionSnapshot.value?.collections_ready))
  const selfName = computed(() => String(self.value?.name || '').trim())
  const selfPublicKey = computed(() => String(self.value?.public_key || '').trim())
  const deviceModel = computed(() => String(device.value?.manufacturer_model || '').trim())
  const notificationSoundEnabled = computed(() => Boolean(settingsPayload.value?.settings?.notifications_sound_enabled))
  const selectedBleDeviceInfo = computed(() => {
    const target = normalizePort(selectedBleDevice.value)
    return bleConnections.value.find((entry) => normalizePort(entry?.transport_id || entry?.address) === target) || null
  })
  const selectedConnection = computed(() => {
    const rawTransportType = String(selectedTransportType.value || 'serial').trim().toLowerCase()
    const transportType = ['serial', 'ble', 'wifi'].includes(rawTransportType) ? rawTransportType : 'serial'
    if (transportType === 'wifi') {
      return normalizeConnectionDescriptor({
        connection: {
          transport_type: 'wifi',
          transport_id: '',
          display_label: 'Wi-Fi',
          timeout: DEFAULT_TIMEOUT,
        },
      })
    }
    if (transportType === 'ble') {
      const bleDevice = selectedBleDeviceInfo.value || {}
      const transportId = normalizePort(selectedBleDevice.value || bleDevice?.transport_id || bleDevice?.address)
      return normalizeConnectionDescriptor({
        connection: {
          transport_type: 'ble',
          transport_id: transportId,
          display_label: String(bleDevice?.display_label || bleDevice?.name || transportId || '').trim(),
          adapter_id: String(bleDevice?.adapter_id || '').trim(),
          pin: String(selectedBlePin.value || '').trim(),
          timeout: Math.max(DEFAULT_TIMEOUT, 8),
        },
      })
    }
    return normalizeConnectionDescriptor({
      transport_type: 'serial',
      transport_id: selectedPort.value,
      port: selectedPort.value,
      baudrate: selectedBaudrate.value,
      timeout: DEFAULT_TIMEOUT,
    })
  })
  const selectedSavedConnection = computed(() => {
    return savedConnections.value.find((item) => (
      normalizeConnectionDescriptor(item).transport_id === selectedConnection.value.transport_id
      && normalizeConnectionDescriptor(item).transport_type === selectedConnection.value.transport_type
      && (selectedConnection.value.transport_type !== 'serial' || Number(item?.baudrate || 0) === Number(selectedBaudrate.value || DEFAULT_BAUDRATE))
    )) || null
  })
  const transientDisconnectSuppressed = computed(() => Number(transientDisconnectSuppressedUntil.value || 0) > Date.now())

  return {
    DEFAULT_TIMEOUT,
    DEFAULT_BAUDRATE,
    ports,
    bleConnections,
    bleDiagnostics,
    bleLastScanAt,
    savedConnections,
    activeSessions,
    recoveringSessions,
    resolvedStartupConnection,
    lastSuccessfulConfig,
    settingsPayload,
    sessionSnapshot,
    connectNotice,
    transientDisconnectSuppressed,
    selectedConnection,
    selectedPort,
    selectedBaudrate,
    selectedTransportType,
    selectedBleDevice,
    selectedBlePin,
    statusText,
    statusError,
    loadingClientSettings,
    loadingPorts,
    loadingBleConnections,
    loadingContacts,
    syncingSession,
    connecting,
    messagesHydrating,
    radioTxObservedAt,
    unreadSummary,
    connected,
    device,
    self,
    contacts,
    channels,
    radioStats,
    queueState,
    stopState,
    selfTelemetry,
    batteryInfo,
    recentRepeaterCount,
    collectionsReady,
    selfName,
    selfPublicKey,
    deviceModel,
    notificationSoundEnabled,
    selectedBleDeviceInfo,
    selectedSavedConnection,
    setStatus,
    showConnectNotice,
    clearConnectNotice,
    suppressTransientDisconnect,
    clearTransientDisconnectSuppression,
    setMessagesHydrating,
    noteRadioTransmission,
    clearRadioTransmission,
    applyUnreadSummary,
    patchUnreadSummary,
    clearUnreadSummary,
    api,
    pickInitialSelection,
    applyClientSettingsPayload,
    updateClientSettings,
    toggleNotificationSoundEnabled,
    mutateSessionSnapshot,
    patchSessionSnapshotFields,
    updateChannelSnapshot,
    updateContactSnapshotByPrefix,
    applySessionSnapshot,
    loadClientSettings,
    refreshPorts,
    refreshBleConnections,
    configBody,
    syncSessionState,
    loadChannels,
    loadContacts,
    loadUnreadSummary,
    connectNode,
    disconnectNode,
    forgetSavedConnection,
  }
})
