import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useStorage } from '@vueuse/core'

import { i18n } from '../i18n'
import { batteryProfileForNode, normalizeBatteryProfileMap } from '../lib/batteryProfile'
import { normalizeStopState } from '../lib/sessionLiveState'
import {
  buildWifiTransportId,
  DEFAULT_WIFI_PORT,
  normalizeWifiHost,
  normalizeWifiPort,
  parseWifiEndpoint,
} from '../lib/wifiTransport'

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

function normalizeBaudrate(value, fallback = DEFAULT_BAUDRATE) {
  if (value === 0 || value === '0') {
    return 0
  }
  const numeric = Number(value)
  if (Number.isFinite(numeric) && numeric > 0) {
    return numeric
  }
  return Number(fallback || DEFAULT_BAUDRATE) || DEFAULT_BAUDRATE
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
  const rawBaudrate = normalizeBaudrate(
    sourceConnection.baudrate
    ?? source?.baudrate
    ?? fallbackConnection.baudrate
    ?? fallback?.baudrate
    ?? DEFAULT_BAUDRATE,
  )
  const baudrate = transportType === 'serial' ? rawBaudrate : 0
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

function buildConnectionKey(source = {}, fallback = {}) {
  const connection = normalizeConnectionDescriptor(source, fallback)
  if (!connection.transport_id) {
    return ''
  }
  const parts = [
    String(connection.transport_type || 'serial').trim().toLowerCase() || 'serial',
    connection.transport_id,
  ]
  if (parts[0] === 'serial') {
    parts.push(String(normalizeBaudrate(connection.baudrate, DEFAULT_BAUDRATE)))
  }
  return parts.join('::')
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
  const selectedWifiHost = useStorage('selected_wifi_host', '')
  const selectedWifiPort = useStorage('selected_wifi_port', String(DEFAULT_WIFI_PORT))
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
  const browserNotificationPermission = ref(getBrowserNotificationPermission())
  const notificationAudioCache = new Map()
  let contactsRequestPromise = null
  const transientDisconnectSuppressedUntil = ref(0)
  let browserUnreadSummaryPrimed = false
  let browserNotificationRequestPromise = null
  let lastBrowserNotificationAt = 0

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

  function normalizeOwnerId(value) {
    const normalized = String(value || '').trim().toLowerCase()
    return /^[0-9a-f]{64}$/.test(normalized) ? normalized : ''
  }

  function getCurrentOwnerId() {
    return normalizeOwnerId(selfPublicKey.value || self.value?.public_key || '')
  }

  function pushUniqueMuteKey(keys, next) {
    const normalized = String(next || '').trim().toLowerCase()
    if (normalized && !keys.includes(normalized)) {
      keys.push(normalized)
    }
  }

  function appendScopedAndLegacyMuteKey(keys, baseKey, ownerId = '') {
    const normalizedBaseKey = String(baseKey || '').trim().toLowerCase()
    if (!normalizedBaseKey) {
      return
    }
    const normalizedOwnerId = normalizeOwnerId(ownerId)
    const currentOwnerId = getCurrentOwnerId()
    if (normalizedOwnerId) {
      pushUniqueMuteKey(keys, `owner:${normalizedOwnerId}:${normalizedBaseKey}`)
      if (normalizedOwnerId === currentOwnerId) {
        pushUniqueMuteKey(keys, normalizedBaseKey)
      }
      return
    }
    pushUniqueMuteKey(keys, normalizedBaseKey)
    if (currentOwnerId) {
      pushUniqueMuteKey(keys, `owner:${currentOwnerId}:${normalizedBaseKey}`)
    }
  }

  function parseScopedConversationKey(rawValue) {
    const raw = String(rawValue || '').trim().toLowerCase()
    const ownerScopedMatch = /^owner:([0-9a-f]{64}):(channelid:.+|channel:\d+|contact:[0-9a-f]{1,12})$/i.exec(raw)
    if (ownerScopedMatch) {
      return {
        ownerId: ownerScopedMatch[1].toLowerCase(),
        baseKey: ownerScopedMatch[2].toLowerCase(),
      }
    }
    return {
      ownerId: '',
      baseKey: raw,
    }
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

  function getHighestPriorityMuteMode(modes = []) {
    if (modes.includes('all')) {
      return 'all'
    }
    if (modes.includes('regular')) {
      return 'regular'
    }
    return 'none'
  }

  function getChannelMuteKeys(value) {
    const keys = []
    if (isPlainObject(value)) {
      const ownerId = normalizeOwnerId(value?.owner_id || value?.ownerId || '')
      const identity = String(value?.channel_identity || '').trim()
      const idx = Number(value?.idx ?? -1)
      if (identity) {
        appendScopedAndLegacyMuteKey(keys, `channelid:${identity}`, ownerId)
      }
      if (Number.isFinite(idx) && idx >= 0) {
        appendScopedAndLegacyMuteKey(keys, `channel:${idx}`, ownerId)
      }
      return keys
    }
    const parsed = parseScopedConversationKey(value)
    const normalized = String(parsed.baseKey || '').trim()
    if (!normalized) {
      return keys
    }
    if (/^-?\d+$/.test(normalized)) {
      const idx = Number(normalized)
      if (Number.isFinite(idx) && idx >= 0) {
        appendScopedAndLegacyMuteKey(keys, `channel:${idx}`, parsed.ownerId)
      }
      return keys
    }
    if (normalized.startsWith('channelid:') || normalized.startsWith('channel:')) {
      appendScopedAndLegacyMuteKey(keys, normalized, parsed.ownerId)
      return keys
    }
    appendScopedAndLegacyMuteKey(keys, `channelid:${normalized}`, parsed.ownerId)
    return keys
  }

  function getContactMuteKeys(value) {
    const keys = []
    if (isPlainObject(value)) {
      const ownerId = normalizeOwnerId(value?.owner_id || value?.ownerId || '')
      const prefix = normalizePublicKeyPrefix(value?.pubkey_prefix || value?.public_key || '')
      if (prefix) {
        appendScopedAndLegacyMuteKey(keys, `contact:${prefix}`, ownerId)
      }
      return keys
    }
    const parsed = parseScopedConversationKey(value)
    if (parsed.baseKey.startsWith('contact:')) {
      appendScopedAndLegacyMuteKey(keys, parsed.baseKey, parsed.ownerId)
      return keys
    }
    const prefix = normalizePublicKeyPrefix(value)
    if (prefix) {
      appendScopedAndLegacyMuteKey(keys, `contact:${prefix}`, parsed.ownerId)
    }
    return keys
  }

  function getChannelMuteMode(value) {
    return getHighestPriorityMuteMode(
      getChannelMuteKeys(value).map((muteKey) => getConversationMuteModeByKey(muteKey)),
    )
  }

  function sumAudibleUnread(summary = {}) {
    const channelUnreadCounts = isPlainObject(summary?.channel_unread_counts) ? summary.channel_unread_counts : {}
    let total = 0
    for (const [channelKey, rawCount] of Object.entries(channelUnreadCounts)) {
      const muteMode = getChannelMuteMode(channelKey)
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
      const muteMode = getChannelMuteMode(channelKey)
      if (muteMode === 'all') {
        continue
      }
      total += Number(rawCount || 0)
    }
    for (const [contactKey, rawCount] of Object.entries(contactMentionCounts)) {
      const muteMode = getHighestPriorityMuteMode(
        getContactMuteKeys(contactKey).map((muteKey) => getConversationMuteModeByKey(muteKey)),
      )
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
      const muteMode = getHighestPriorityMuteMode(
        getContactMuteKeys(contactKey).map((muteKey) => getConversationMuteModeByKey(muteKey)),
      )
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

  function getBrowserNotificationPermission() {
    if (typeof Notification === 'undefined') {
      return 'unsupported'
    }
    return String(Notification.permission || 'default')
  }

  function buildBrowserUnreadTotals(summary = {}) {
    const regular = Math.max(0, Number(sumAudibleUnread(summary) || 0))
    const direct = Math.max(0, Number(sumAudibleDirectUnread(summary) || 0))
    const mentions = Math.max(0, Number(sumAudibleMentions(summary) || 0))
    return {
      regular,
      direct,
      mentions,
      unread: regular + direct,
      badge: regular + direct + mentions,
    }
  }

  const browserUnreadTotals = computed(() => buildBrowserUnreadTotals(unreadSummary.value))
  const browserUnreadBadgeCount = computed(() => Math.max(0, Number(browserUnreadTotals.value.badge || 0)))

  async function requestBrowserNotificationPermission() {
    browserNotificationPermission.value = getBrowserNotificationPermission()
    if (browserNotificationPermission.value !== 'default') {
      return browserNotificationPermission.value
    }
    if (typeof Notification === 'undefined' || typeof Notification.requestPermission !== 'function') {
      browserNotificationPermission.value = 'unsupported'
      return browserNotificationPermission.value
    }
    if (browserNotificationRequestPromise) {
      return browserNotificationRequestPromise
    }
    browserNotificationRequestPromise = Promise.resolve(Notification.requestPermission())
      .then((permission) => {
        browserNotificationPermission.value = String(permission || getBrowserNotificationPermission())
        return browserNotificationPermission.value
      })
      .catch(() => {
        browserNotificationPermission.value = getBrowserNotificationPermission()
        return browserNotificationPermission.value
      })
      .finally(() => {
        browserNotificationRequestPromise = null
      })
    return browserNotificationRequestPromise
  }

  function formatBrowserNotificationBody(totals) {
    const unread = Math.max(0, Number(totals.unread || 0))
    const mentions = Math.max(0, Number(totals.mentions || 0))
    if (mentions > 0) {
      return t('notifications.browser.bodyWithMentions', { unread, mentions })
    }
    return t('notifications.browser.bodyNoMentions', { unread })
  }

  function showBrowserUnreadNotification(totals) {
    browserNotificationPermission.value = getBrowserNotificationPermission()
    if (browserNotificationPermission.value !== 'granted' || typeof Notification === 'undefined') {
      return
    }
    const now = Date.now()
    if (now - lastBrowserNotificationAt < 2000) {
      return
    }
    lastBrowserNotificationAt = now
    const notification = new Notification(t('notifications.browser.title'), {
      body: formatBrowserNotificationBody(totals),
      icon: '/icons/Meshcorium3.png',
      badge: '/icons/bell-icon.svg',
      tag: 'meshcorium-unread',
      renotify: true,
      silent: true,
    })
    notification.onclick = () => {
      try {
        window.focus()
      } catch {
        // Browser focus can be denied; notification delivery should not fail.
      }
      notification.close()
    }
  }

  function maybeShowUnreadBrowserNotification(previousSummary = {}, nextSummary = {}) {
    if (!connected.value) {
      browserUnreadSummaryPrimed = true
      return
    }
    const previousTotals = buildBrowserUnreadTotals(previousSummary)
    const nextTotals = buildBrowserUnreadTotals(nextSummary)
    if (!browserUnreadSummaryPrimed) {
      browserUnreadSummaryPrimed = true
      return
    }
    const increased = (
      nextTotals.regular > previousTotals.regular
      || nextTotals.direct > previousTotals.direct
      || nextTotals.mentions > previousTotals.mentions
    )
    if (!increased || nextTotals.badge <= 0) {
      return
    }
    showBrowserUnreadNotification(nextTotals)
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
    maybeShowUnreadBrowserNotification(unreadSummary.value, nextSummary)
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
    browserUnreadSummaryPrimed = false
  }

  async function api(path, options = {}) {
    const fetchOptions = {
      credentials: 'same-origin',
      headers: {
        ...(options.body != null ? { 'Content-Type': 'application/json' } : {}),
        ...(options.headers || {}),
      },
      ...options,
    }
    if (fetchOptions.body != null && typeof fetchOptions.body === 'object') {
      fetchOptions.body = JSON.stringify(fetchOptions.body)
    }
    const response = await fetch(path, fetchOptions)
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
      const error = new Error(
        data?.error || `HTTP ${response.status}`
      )
      error.status = response.status
      error.code = String(data?.error_code || '')
      error.payload = data
      throw error
    }
    return data
  }

  function pickInitialSelection() {
    const storagePort = normalizePort(selectedPort.value)
    const storageBleDevice = normalizePort(selectedBleDevice.value)
    const storageWifiHost = normalizeWifiHost(selectedWifiHost.value)
    const storageWifiPort = normalizeWifiPort(selectedWifiPort.value)
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
    if (!storageWifiHost) {
      const nextWifiConnection = [startupConnection, lastSuccessfulConnection, firstSavedConnection]
        .find((connection) => connection.transport_type === 'wifi' && normalizePort(connection.transport_id))
      if (nextWifiConnection) {
        const parsed = parseWifiEndpoint(nextWifiConnection.transport_id)
        selectedWifiHost.value = parsed.host
        selectedWifiPort.value = normalizeWifiPort(parsed.port)
      } else {
        selectedWifiPort.value = String(DEFAULT_WIFI_PORT)
      }
    } else {
      selectedWifiHost.value = storageWifiHost
      selectedWifiPort.value = storageWifiPort
    }
  }

  function applyConnectionSelection(source = {}, fallback = {}) {
    const connection = normalizeConnectionDescriptor(source, fallback)
    const transportType = String(connection.transport_type || 'serial').trim().toLowerCase() || 'serial'
    selectedTransportType.value = transportType
    if (transportType === 'ble') {
      const transportId = normalizePort(connection.transport_id || connection.port)
      selectedBleDevice.value = transportId
      selectedBaudrate.value = Number(connection.baudrate || 0) || 0
      return
    }
    if (transportType === 'serial') {
      const port = normalizePort(connection.port || connection.transport_id)
      selectedPort.value = port
      selectedBaudrate.value = Number(connection.baudrate || DEFAULT_BAUDRATE) || DEFAULT_BAUDRATE
      return
    }
    if (transportType === 'wifi') {
      const parsed = parseWifiEndpoint(connection.transport_id || connection.port)
      selectedWifiHost.value = parsed.host
      selectedWifiPort.value = normalizeWifiPort(parsed.port)
      selectedBaudrate.value = 0
      return
    }
    selectedPort.value = normalizePort(connection.port || connection.transport_id)
    selectedBaudrate.value = Number(connection.baudrate || 0) || 0
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
        const nextTransportType = String(
          hasOwnField(patch, 'transport_type') ? patch?.transport_type : snapshot.transport_type,
        ).trim().toLowerCase() || 'serial'
        snapshot.baudrate = nextTransportType === 'serial'
          ? normalizeBaudrate(patch?.baudrate, DEFAULT_BAUDRATE)
          : 0
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
      baudrate: hasOwnField(data, 'baudrate')
        ? (((String(data?.transport_type || previous?.transport_type || 'serial').trim().toLowerCase() || 'serial') === 'serial')
            ? normalizeBaudrate(data?.baudrate, DEFAULT_BAUDRATE)
            : 0)
        : ((((String(previous?.transport_type || 'serial').trim().toLowerCase() || 'serial') === 'serial'))
            ? normalizeBaudrate(previous?.baudrate, DEFAULT_BAUDRATE)
            : 0),
      transport_type: hasOwnField(data, 'transport_type') ? (String(data?.transport_type || 'serial').trim().toLowerCase() || 'serial') : (previous?.transport_type || 'serial'),
      transport_id: hasOwnField(data, 'transport_id') ? normalizePort(data?.transport_id) : normalizePort(previous?.transport_id || previous?.port),
      collections_ready: nextCollectionsReady,
      contacts_count: nextContactsCount,
      contact_summary: nextContactSummary,
      channels_count: nextChannelsCount,
      recent_repeaters_count: nextRecentRepeatersCount,
    }
    if (nextActive) {
      applyConnectionSelection(data, previous)
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

  function isKnownBleSelection(address) {
    const target = normalizePort(address)
    if (!target) {
      return false
    }
    if (bleConnections.value.some((entry) => normalizePort(entry?.transport_id || entry?.address) === target)) {
      return true
    }
    return savedConnections.value.some((entry) => {
      const connection = normalizeConnectionDescriptor(entry)
      return connection.transport_type === 'ble' && normalizePort(connection.transport_id || connection.port) === target
    })
  }

  async function refreshBleConnections({ timeout = 6, resetKnownDevices = false, cachedOnly = false } = {}) {
    loadingBleConnections.value = true
    try {
      const query = new URLSearchParams({
        type: 'ble',
        timeout: String(Math.max(1, Number(timeout || 6))),
      })
      if (cachedOnly) {
        query.set('cached_only', '1')
      }
      if (resetKnownDevices) {
        query.set('reset', '1')
      }
      const data = await api(`/api/transports?${query.toString()}`)
      const bleTransport = Array.isArray(data?.transports)
        ? data.transports.find((entry) => String(entry?.transport_type || '') === 'ble')
        : null
      bleConnections.value = Array.isArray(bleTransport?.connections) ? bleTransport.connections : []
      if (normalizePort(selectedBleDevice.value) && !isKnownBleSelection(selectedBleDevice.value)) {
        selectedBleDevice.value = ''
      }
      if (bleTransport && bleTransport.available === false) {
        setStatus(bleTransport?.diagnostics?.message || bleTransport?.error || t('connect.ble.scanUnavailable'), true)
      } else if (!bleConnections.value.length) {
        setStatus(t('connect.ble.noDevices'), true)
      } else if (resetKnownDevices && Number(bleTransport?.reset?.count || 0) > 0) {
        setStatus(t('connect.ble.resetPairsDone', { count: Number(bleTransport?.reset?.count || 0) }))
      }
      if (!normalizePort(selectedBleDevice.value) && bleConnections.value.length) {
        selectedBleDevice.value = normalizePort(bleConnections.value[0]?.transport_id || bleConnections.value[0]?.address || '')
      }
      return bleConnections.value
    } finally {
      loadingBleConnections.value = false
    }
  }

  async function unpairBleDevice({ address = '', adapterId = '' } = {}) {
    const normalizedAddress = normalizePort(address)
    if (!normalizedAddress) {
      return null
    }
    const data = await api('/api/transports/ble/unpair', {
      method: 'POST',
      body: JSON.stringify({
        address: normalizedAddress,
        adapter_id: String(adapterId || '').trim(),
      }),
    })
    const result = isPlainObject(data?.result) ? data.result : null
    const removed = Boolean(result?.removed)
    if (!removed) {
      throw new Error(t('connect.ble.unpairFailed'))
    }
    bleConnections.value = bleConnections.value
      .map((entry) => {
        const entryAddress = normalizePort(entry?.transport_id || entry?.address)
        if (entryAddress !== normalizedAddress) {
          return entry
        }
        return {
          ...entry,
          paired: false,
          bonded: false,
          trusted: false,
          connected: false,
          cached: false,
        }
      })
      .filter((entry) => normalizePort(entry?.transport_id || entry?.address) !== normalizedAddress)
    if (normalizePort(selectedBleDevice.value) === normalizedAddress) {
      selectedBlePin.value = ''
    }
    await refreshBleConnections({ cachedOnly: true })
    setStatus(t('connect.ble.unpaired', { address: normalizedAddress }))
    return result
  }

  function configBody(extra = {}) {
    const connection = selectedConnection.value
    const port = normalizePort(connection.port || connection.transport_id)
    const baudrate = connection.transport_type === 'serial'
      ? normalizeBaudrate(connection.baudrate, DEFAULT_BAUDRATE)
      : 0
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

  function buildConnectionBody(connectionSource, extra = {}) {
    const connection = normalizeConnectionDescriptor(connectionSource)
    const port = normalizePort(connection.port || connection.transport_id)
    const baudrate = connection.transport_type === 'serial'
      ? normalizeBaudrate(connection.baudrate, DEFAULT_BAUDRATE)
      : 0
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

  function resolveRequestConnection() {
    if (connected.value && activeSessionConnection.value?.transport_id) {
      return activeSessionConnection.value
    }
    return selectedConnection.value
  }

  function activeConfigBody(extra = {}) {
    return buildConnectionBody(resolveRequestConnection(), extra)
  }

  function buildEventStreamQueryFromConnection(connectionSource, extra = {}) {
    const connection = normalizeConnectionDescriptor(connectionSource)
    const port = normalizePort(connection.port || connection.transport_id)
    if (!port) {
      return null
    }
    const query = new URLSearchParams({
      port,
      baudrate: String(
        connection.transport_type === 'serial'
          ? normalizeBaudrate(connection.baudrate, DEFAULT_BAUDRATE)
          : 0
      ),
      timeout: String(Number(connection.timeout || DEFAULT_TIMEOUT) || DEFAULT_TIMEOUT),
    })
    for (const [key, value] of Object.entries(extra || {})) {
      if (value == null) {
        continue
      }
      query.set(String(key), String(value))
    }
    return query
  }

  function activeEventStreamQuery(extra = {}) {
    return buildEventStreamQueryFromConnection(resolveRequestConnection(), extra)
  }

  async function syncSessionState({ light = true } = {}) {
    const connection = resolveRequestConnection()
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
      body: JSON.stringify(activeConfigBody()),
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
          body: JSON.stringify(activeConfigBody({ refresh })),
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
    const connection = resolveRequestConnection()
    const resolvedPort = normalizePort(port || connection.port || connection.transport_id)
    if (!resolvedPort || !connected.value) {
      clearUnreadSummary()
      return unreadSummary.value
    }
    const data = await api('/api/messages/unread', {
      method: 'POST',
      body: JSON.stringify({
        transport_type: connection.transport_type,
        transport_id: connection.transport_id,
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
    const port = normalizePort(connection.port || connection.transport_id)
    if (connection.transport_type === 'wifi') {
      const host = normalizeWifiHost(selectedWifiHost.value)
      const wifiPort = String(selectedWifiPort.value || '').trim()
      if (!host) {
        throw new Error(t('connect.status.wifiHostRequired'))
      }
      if (!/^\d+$/.test(wifiPort)) {
        throw new Error(t('connect.status.wifiPortInvalid'))
      }
      const numericPort = Number(wifiPort)
      if (!Number.isInteger(numericPort) || numericPort < 1 || numericPort > 65535) {
        throw new Error(t('connect.status.wifiPortInvalid'))
      }
    }
    if (!port) {
      if (connection.transport_type === 'wifi') {
        throw new Error(t('connect.status.wifiHostRequired'))
      }
      throw new Error(connection.transport_type === 'ble' ? t('connect.status.bleRequired') : t('connect.status.portRequired'))
    }
    connecting.value = true
    patchSessionSnapshotFields({ stop_state: null })
    setStatus(t('connect.status.connectingTo', { port: connection.display_label || port }))
    try {
      const payload = await api('/api/connect', {
        method: 'POST',
        body: JSON.stringify(configBody({
          light,
          allow_ble_bond_repair: connection.transport_type === 'ble' && Boolean(connection.pin),
        })),
      })
      patchSessionSnapshotFields({
        ...payload,
        active: true,
      })
      applyConnectionSelection(payload, connection)
      await loadClientSettings()
      clearConnectNotice()
      setStatus(t('connect.status.connectedTo', { target: payload?.self?.name || connection.display_label || port }))
      return payload
    } catch (error) {
      await loadClientSettings()
      throw error
    } finally {
      connecting.value = false
    }
  }

  async function disconnectNode() {
    const connection = resolveRequestConnection()
    const port = normalizePort(connection.port || connection.transport_id)
    if (!port) {
      return
    }
    await api('/api/disconnect', {
      method: 'POST',
      body: JSON.stringify(activeConfigBody()),
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
  const batteryProfilesByNodeId = computed(() => normalizeBatteryProfileMap(settingsPayload.value?.settings?.battery_profile_by_node_id))
  const currentNodeBatteryProfile = computed(() => batteryProfileForNode(settingsPayload.value?.settings, selfPublicKey.value))
  const sessionSnapshotConnection = computed(() => {
    const connection = normalizeConnectionDescriptor(sessionSnapshot.value?.connection || sessionSnapshot.value || {})
    return connection.transport_id ? connection : null
  })
  const selectedConnection = computed(() => {
    const rawTransportType = String(selectedTransportType.value || 'serial').trim().toLowerCase()
    const transportType = ['serial', 'ble', 'wifi'].includes(rawTransportType) ? rawTransportType : 'serial'
    if (transportType === 'wifi') {
      const host = normalizeWifiHost(selectedWifiHost.value)
      const port = normalizeWifiPort(selectedWifiPort.value)
      const transportId = buildWifiTransportId(host, port)
      return normalizeConnectionDescriptor({
        connection: {
          transport_type: 'wifi',
          transport_id: transportId,
          display_label: transportId || host || 'Wi-Fi',
          timeout: DEFAULT_TIMEOUT,
        },
        port: transportId,
      })
    }
    if (transportType === 'ble') {
      const bleDevice = bleConnections.value.find(
        (entry) => normalizePort(entry?.transport_id || entry?.address) === normalizePort(selectedBleDevice.value),
      ) || savedConnections.value.find((entry) => {
        const connection = normalizeConnectionDescriptor(entry)
        return connection.transport_type === 'ble' && normalizePort(connection.transport_id) === normalizePort(selectedBleDevice.value)
      }) || {}
      const transportId = normalizePort(selectedBleDevice.value || bleDevice?.transport_id || bleDevice?.address)
      return normalizeConnectionDescriptor({
        connection: {
          transport_type: 'ble',
          transport_id: transportId,
          display_label: String(bleDevice?.display_label || bleDevice?.name || bleDevice?.node_name || bleDevice?.manufacturer_model || transportId || '').trim(),
          adapter_id: String(bleDevice?.adapter_id || '').trim(),
          pin: String(selectedBlePin.value || bleDevice?.pin || '').trim(),
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
  const activeSessionConnection = computed(() => {
    const activeSessionEntries = Array.isArray(activeSessions.value) ? activeSessions.value : []
    const snapshotConnection = sessionSnapshotConnection.value
    const selected = selectedConnection.value
    const findByKey = (connectionSource) => {
      const key = buildConnectionKey(connectionSource)
      if (!key) {
        return null
      }
      return activeSessionEntries.find((entry) => buildConnectionKey(entry) === key) || null
    }
    if (connected.value) {
      const snapshotMatch = snapshotConnection ? findByKey(snapshotConnection) : null
      if (snapshotMatch) {
        return normalizeConnectionDescriptor(snapshotMatch, snapshotConnection)
      }
      if (snapshotConnection?.transport_id) {
        return snapshotConnection
      }
      const selectedMatch = findByKey(selected)
      if (selectedMatch) {
        return normalizeConnectionDescriptor(selectedMatch, selected)
      }
      if (activeSessionEntries.length) {
        return normalizeConnectionDescriptor(activeSessionEntries[0])
      }
    }
    return normalizeConnectionDescriptor(selected)
  })
  const activeConnectionKey = computed(() => buildConnectionKey(activeSessionConnection.value))
  const activeConnectionPort = computed(() => normalizePort(activeSessionConnection.value?.port || activeSessionConnection.value?.transport_id))
  const activeConnectionBaudrate = computed(() => (
    String(activeSessionConnection.value?.transport_type || 'serial').trim().toLowerCase() === 'serial'
      ? normalizeBaudrate(activeSessionConnection.value?.baudrate, DEFAULT_BAUDRATE)
      : 0
  ))
  const transientDisconnectSuppressed = computed(() => Number(transientDisconnectSuppressedUntil.value || 0) > Date.now())

  return {
    DEFAULT_TIMEOUT,
    DEFAULT_BAUDRATE,
    ports,
    bleConnections,
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
    selectedWifiHost,
    selectedWifiPort,
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
    browserNotificationPermission,
    browserUnreadTotals,
    browserUnreadBadgeCount,
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
    batteryProfilesByNodeId,
    currentNodeBatteryProfile,
    sessionSnapshotConnection,
    selectedSavedConnection,
    activeSessionConnection,
    activeConnectionKey,
    activeConnectionPort,
    activeConnectionBaudrate,
    setStatus,
    showConnectNotice,
    clearConnectNotice,
    suppressTransientDisconnect,
    clearTransientDisconnectSuppression,
    setMessagesHydrating,
    noteRadioTransmission,
    clearRadioTransmission,
    requestBrowserNotificationPermission,
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
    unpairBleDevice,
    configBody,
    activeConfigBody,
    activeEventStreamQuery,
    syncSessionState,
    loadChannels,
    loadContacts,
    loadUnreadSummary,
    connectNode,
    disconnectNode,
    forgetSavedConnection,
  }
})
