<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useDocumentVisibility, useIntervalFn } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import NodeConnectPanel from '../connect/NodeConnectPanel.vue'
import MobileDockButton from './MobileDockButton.vue'
import MessagesAdvertSheet from '../messages/MessagesAdvertSheet.vue'
const MessagesNotificationsSheet = defineAsyncComponent(() => import('../messages/MessagesNotificationsSheet.vue'))
const MessagesConsoleSheet = defineAsyncComponent(() => import('../messages/MessagesConsoleSheet.vue'))
import { describeRestorePendingStatus, buildConnectedSessionStatus, packetTypeLabel } from '../../lib/sessionLiveState'
import { useSessionStore } from '../../stores/session'
import { useUpdateCheck } from '../../composables/useUpdateCheck'
import { useIsMobile } from '../../composables/useIsMobile'
import { useNativeShell } from '../../composables/useNativeShell'
import { sendNativeDockState } from '../../lib/nativeShell'
import {
  buildCloseShellPanelLocation,
  buildOpenShellPanelLocation,
  buildToggleShellPanelLocation,
  getActiveShellPanel,
} from '../../lib/shellPanels'

const router = useRouter()
const route = useRoute()
const session = useSessionStore()
const { t, locale } = useI18n()
const visibility = useDocumentVisibility()
const { isMobile } = useIsMobile()
const { isNativeShell } = useNativeShell()

const nativeActiveDockItem = computed(() => {
  if (notificationsOpen.value) {
    return 'notifications'
  }
  if (route.name === 'messages') {
    return 'messages'
  }
  if (isContactsRoute.value) {
    return 'contacts'
  }
  if (isMapsRoute.value) {
    return 'maps'
  }
  if (route.name === 'settings') {
    return 'settings'
  }
  return 'none'
})

watch(
  () => ({
    active: nativeActiveDockItem.value,
    panel: activeShellPanel.value,
    notificationBadge: mobileNotificationBadge.value,
    connected: Boolean(session.connected),
  }),
  (state) => {
    sendNativeDockState(state)
  },
  {
    immediate: true,
    deep: true,
  },
)

const bellIconUrl = '/icons/bell-icon.svg'
const messagesIconUrl = '/icons/paper-plane.png'
const advertIconUrl = '/icons/mesh_broadcast_icon.svg'
const contactsIconUrl = '/icons/contacts-icon.svg'
const mapIconUrl = '/icons/map-icon.svg'
const settingsIconUrl = '/icons/settings-icon.svg'
const disconnectIconUrl = '/icons/disconnect-icon.svg?v=19'
const consoleIconUrl = '/icons/console-icon.svg'
const wikiIconUrl = '/icons/wiki-icon.svg?v=2'
const bootstrapped = ref(false)
const refreshing = ref(false)
const phonebarTick = ref(Date.now())
const advertBusy = ref(false)
const advertMode = ref('')
const notificationsMentionsCollapsed = ref(false)
const notificationsRegularCollapsed = ref(false)
const notificationsDirectCollapsed = ref(false)
const consoleEntries = ref([])
const consoleAutoScroll = ref(true)
const consoleFilter = ref('none')
const consoleSearchTerm = ref('')
const consoleSearchMatchIndex = ref(-1)
const consoleLogRef = ref(null)
const consoleEventSource = ref(null)
const notificationEventSource = ref(null)
const railRef = ref(null)
const railGlowCompressed = ref(false)
const railGlowGeometry = ref({
  visible: false,
  left: 0,
  top: 0,
  width: 0,
  height: 0,
})
const unreadSummary = computed(() => session.unreadSummary || {})
const railButtonElements = {}

const { updateCheck, updateAvailable, startUpdateCheckPolling, stopUpdateCheckPolling } = useUpdateCheck(session)
let railGlowMeasureFrame = 0
let railGlowReleaseTimer = 0
let unreadRefreshTimer = 0
let consoleEventSourceKey = ''
let notificationEventSourceKey = ''
let browserNotificationGestureArmed = false

function normalizePublicKey(value) {
  return String(value || '').trim().toLowerCase()
}

function getContactPrefix(contactOrKey) {
  const raw = typeof contactOrKey === 'string'
    ? contactOrKey
    : (contactOrKey?.pubkey_prefix || contactOrKey?.public_key || '')
  return normalizePublicKey(raw).slice(0, 12)
}

function normalizeOwnerId(value) {
  const normalized = String(value || '').trim().toLowerCase()
  return /^[0-9a-f]{64}$/.test(normalized) ? normalized : ''
}

function getCurrentOwnerId() {
  return normalizeOwnerId(session.self?.public_key || session.selfPublicKey || '')
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

function buildSelfContact() {
  const publicKey = normalizePublicKey(session.self?.public_key || session.selfPublicKey || '')
  if (!publicKey) {
    return null
  }
  return {
    public_key: publicKey,
    pubkey_prefix: publicKey.slice(0, 12),
    adv_name: String(session.self?.name || session.selfName || '').trim(),
    name: String(session.self?.name || session.selfName || '').trim(),
  }
}

function normalizeMutedConversationsMap(value) {
  const source = value && typeof value === 'object' ? value : {}
  const next = {}
  for (const [rawKey, rawMode] of Object.entries(source)) {
    const key = String(rawKey || '').trim().toLowerCase()
    const mode = String(rawMode || '').trim().toLowerCase()
    if (!key) {
      continue
    }
    if (mode === 'regular' || mode === 'all') {
      next[key] = mode
    }
  }
  return next
}

function getOwnerPort() {
  return String(session.activeConnectionPort || '')
}

function buildOwnerEventStreamKey() {
  return String(session.activeConnectionKey || '')
}

const activeShellPanel = computed(() => {
  return getActiveShellPanel(route)
})
const globalAdvertOpen = computed(() => activeShellPanel.value === 'advert')
const notificationsOpen = computed({
  get() {
    return activeShellPanel.value === 'notifications'
  },
  set(value) {
    if (value) {
      void openShellPanel('notifications')
      return
    }
    if (notificationsOpen.value) {
      void closeShellPanel()
    }
  },
})
const consoleOpen = computed({
  get() {
    return activeShellPanel.value === 'console'
  },
  set(value) {
    if (value) {
      void openShellPanel('console')
      return
    }
    if (consoleOpen.value) {
      void closeShellPanel()
    }
  },
})

const isMessagesRoute = computed(() => route.name === 'messages')
const isMapsRoute = computed(() => route.name === 'maps' || route.name === 'maps-route-checks')
const isContactsRoute = computed(() => (
  route.name === 'contacts'
  || route.name === 'contacts-groups'
  || route.name === 'contacts-repeater-login'
  || route.name === 'contacts-repeater'
))
const showGlobalMobileDock = computed(
  () => isMobile.value
    && !isNativeShell.value
    && !isMessagesRoute.value
    && !isContactsRoute.value,
)

const activeRailKey = computed(() => {
  if (notificationsOpen.value) {
    return 'notifications'
  }
  if (consoleOpen.value) {
    return 'console'
  }
  if (globalAdvertOpen.value) {
    return 'advert'
  }
  if (route.name === 'messages') {
    return 'messages'
  }
  if (isContactsRoute.value) {
    return 'contacts'
  }
  if (isMapsRoute.value) {
    return 'maps'
  }
  if (route.name === 'settings') {
    return 'settings'
  }
  return ''
})

const railGlowStyle = computed(() => {
  const geometry = railGlowGeometry.value
  return {
    width: `${geometry.width}px`,
    height: `${geometry.height}px`,
    opacity: geometry.visible ? '1' : '0',
    transform: `translate3d(${geometry.left}px, ${geometry.top}px, 0) scale(${railGlowCompressed.value ? 0.78 : 1})`,
  }
})

function setRailButtonElement(key, element) {
  if (element) {
    railButtonElements[key] = element
    return
  }
  delete railButtonElements[key]
}

function measureRailGlow() {
  railGlowMeasureFrame = 0
  const key = String(activeRailKey.value || '').trim()
  const rail = railRef.value
  const button = key ? railButtonElements[key] : null
  if (!rail || !button) {
    railGlowGeometry.value = {
      visible: false,
      left: 0,
      top: 0,
      width: 0,
      height: 0,
    }
    return
  }
  const railRect = rail.getBoundingClientRect()
  const buttonRect = button.getBoundingClientRect()
  const paddingX = 7
  const paddingY = 6
  railGlowGeometry.value = {
    visible: true,
    left: Math.round(buttonRect.left - railRect.left - paddingX),
    top: Math.round(buttonRect.top - railRect.top - paddingY),
    width: Math.round(buttonRect.width + (paddingX * 2)),
    height: Math.round(buttonRect.height + (paddingY * 2)),
  }
}

function scheduleRailGlowMeasure() {
  if (railGlowMeasureFrame) {
    cancelAnimationFrame(railGlowMeasureFrame)
  }
  railGlowMeasureFrame = requestAnimationFrame(() => {
    measureRailGlow()
  })
}

function animateRailGlowTransition() {
  railGlowCompressed.value = true
  scheduleRailGlowMeasure()
  if (railGlowReleaseTimer) {
    window.clearTimeout(railGlowReleaseTimer)
  }
  railGlowReleaseTimer = window.setTimeout(() => {
    railGlowCompressed.value = false
  }, 190)
}

const mutedConversationsMap = computed(() => normalizeMutedConversationsMap(session.settingsPayload?.settings?.muted_conversations))

function getConversationMuteKey(kind, value) {
  if (String(kind || '').trim().toLowerCase() === 'channel') {
    return getChannelMuteKeys(value)[0] || ''
  }
  return getContactMuteKeys(value)[0] || ''
}

function getConversationMuteModeByKey(muteKey) {
  if (!muteKey) {
    return 'none'
  }
  const mode = String(mutedConversationsMap.value[muteKey] || '').trim().toLowerCase()
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

function getChannelMuteKeys(value, fallback = null) {
  const keys = []
  const appendIdentityAndIdx = (source) => {
    if (!source || typeof source !== 'object') {
      return
    }
    const ownerId = normalizeOwnerId(source.ownerId || source.owner_id || '')
    const identity = String(source.channelIdentity || source.channel_identity || '').trim()
    const idx = Number(source.channelIdx ?? source.channel_idx ?? source.idx ?? -1)
    if (identity) {
      appendScopedAndLegacyMuteKey(keys, `channelid:${identity}`, ownerId)
    }
    if (Number.isFinite(idx) && idx >= 0) {
      appendScopedAndLegacyMuteKey(keys, `channel:${idx}`, ownerId)
    }
  }
  appendIdentityAndIdx(value)
  appendIdentityAndIdx(fallback)
  if (keys.length) {
    return keys
  }
  const parsed = parseScopedConversationKey(value)
  const normalized = String(parsed.baseKey || '').trim()
  if (!normalized) {
    return keys
  }
  if (normalized.startsWith('channelid:') || normalized.startsWith('channel:')) {
    appendScopedAndLegacyMuteKey(keys, normalized, parsed.ownerId)
    return keys
  }
  if (/^-?\d+$/.test(normalized)) {
    const idx = Number(normalized)
    if (Number.isFinite(idx) && idx >= 0) {
      appendScopedAndLegacyMuteKey(keys, `channel:${idx}`, parsed.ownerId)
    }
    return keys
  }
  appendScopedAndLegacyMuteKey(keys, `channelid:${normalized}`, parsed.ownerId)
  return keys
}

function getContactMuteKeys(value) {
  const keys = []
  if (value && typeof value === 'object') {
    const ownerId = normalizeOwnerId(value.ownerId || value.owner_id || '')
    const prefix = getContactPrefix(value)
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
  const prefix = getContactPrefix(value)
  if (prefix) {
    appendScopedAndLegacyMuteKey(keys, `contact:${prefix}`, parsed.ownerId)
  }
  return keys
}

function getChannelMuteMode(value, fallback = null) {
  return getHighestPriorityMuteMode(
    getChannelMuteKeys(value, fallback).map((muteKey) => getConversationMuteModeByKey(muteKey)),
  )
}

function isConversationRegularMutedByKey(muteKey) {
  const mode = getConversationMuteModeByKey(muteKey)
  return mode === 'regular' || mode === 'all'
}

const totalRegularUnreadCount = computed(() => {
  const channelUnreadCounts = unreadSummary.value.channel_unread_counts || {}
  return Object.entries(channelUnreadCounts).reduce((sum, [channelKey, rawCount]) => {
    if (getChannelMuteMode(channelKey) === 'regular' || getChannelMuteMode(channelKey) === 'all') {
      return sum
    }
    return sum + Number(rawCount || 0)
  }, 0)
})

const totalDirectUnreadCount = computed(() => {
  const contactUnreadCounts = unreadSummary.value.contact_unread_counts || {}
  return Object.entries(contactUnreadCounts).reduce((sum, [contactKey, rawCount]) => {
    const muteMode = getHighestPriorityMuteMode(
      getContactMuteKeys(contactKey).map((muteKey) => getConversationMuteModeByKey(muteKey)),
    )
    if (muteMode === 'regular' || muteMode === 'all') {
      return sum
    }
    return sum + Number(rawCount || 0)
  }, 0)
})

const totalUnreadCount = computed(() => totalRegularUnreadCount.value + totalDirectUnreadCount.value)
const mobileNotificationBadge = computed(() => {
  if (totalMentionCount.value > 0) {
    return totalMentionCount.value > 99 ? '99+' : String(totalMentionCount.value)
  }
  if (totalUnreadCount.value > 0) {
    return totalUnreadCount.value > 99 ? '99+' : String(totalUnreadCount.value)
  }
  return updateAvailable.value ? 'U' : ''
})

const totalMentionCount = computed(() => {
  const channelMentionCounts = unreadSummary.value.channel_mention_counts || {}
  const channelsTotal = Object.entries(channelMentionCounts).reduce((sum, [channelKey, rawCount]) => {
    if (getChannelMuteMode(channelKey) === 'all') {
      return sum
    }
    return sum + Number(rawCount || 0)
  }, 0)
  const contactMentionCounts = unreadSummary.value.contact_mention_counts || {}
  const contactsTotal = Object.entries(contactMentionCounts).reduce((sum, [contactKey, rawCount]) => {
    const muteMode = getHighestPriorityMuteMode(
      getContactMuteKeys(contactKey).map((muteKey) => getConversationMuteModeByKey(muteKey)),
    )
    if (muteMode === 'all') {
      return sum
    }
    return sum + Number(rawCount || 0)
  }, 0)
  return channelsTotal + contactsTotal
})

const pausedSessionShellState = computed(() => {
  if (session.connected || !bootstrapped.value) {
    return false
  }
  const stopReason = String(
    session.stopState?.stop_reason
      || session.stopState?.last_stop_reason
      || '',
  ).trim().toLowerCase()
  return stopReason === 'paused-session'
})

const repeaterLoginShellState = computed(() => route.name === 'contacts-repeater-login')

const disconnectOverlaySuppressed = computed(() => {
  return pausedSessionShellState.value || repeaterLoginShellState.value || session.transientDisconnectSuppressed
})

const shellBlurred = computed(() => {
  return ((!session.connected && bootstrapped.value && !disconnectOverlaySuppressed.value))
    || notificationsOpen.value
    || consoleOpen.value
    || globalAdvertOpen.value
})

const pageBackdropBlurred = computed(() => {
  return ((!session.connected && bootstrapped.value && !disconnectOverlaySuppressed.value))
    || notificationsOpen.value
    || consoleOpen.value
    || globalAdvertOpen.value
    || showMessagesSyncOverlay.value
})

const showMessagesSyncOverlay = computed(() => {
  return route.name === 'messages' && session.connected && session.messagesHydrating
})

const syncTargetName = computed(() => {
  return String(session.self?.name || session.device?.manufacturer_model || 'meshcore').trim() || 'meshcore'
})

const phoneBarNodeName = computed(() => {
  const selfName = String(session.self?.name || '').trim()
  if (selfName) {
    return selfName
  }
  const saved = session.selectedSavedConnection || null
  return String(saved?.node_name || t('common.offline'))
})

async function loadUnreadCounts() {
  if (!session.connected || !getOwnerPort()) {
    session.clearUnreadSummary()
    return
  }
  await session.loadUnreadSummary({
    port: getOwnerPort(),
    mentionName: String(session.self?.name || ''),
  })
}

async function refreshShellState({ includePorts = false, suppressStatus = false } = {}) {
  if (refreshing.value) {
    return
  }
  refreshing.value = true
  try {
    await session.loadClientSettings()
    let syncedConnectionKey = ''
    if (!isMessagesRoute.value) {
      const previousSnapshot = session.sessionSnapshot ? { ...session.sessionSnapshot } : { active: false }
      const wasConnected = Boolean(previousSnapshot?.active)
      syncedConnectionKey = String(session.activeConnectionKey || '')
      let snapshot = await session.syncSessionState({ light: true })
      if (wasConnected && !snapshot?.active) {
        session.applySessionSnapshot(previousSnapshot)
        snapshot = await session.syncSessionState({ light: false })
      }
    }
    const backgroundTasks = [loadUnreadCounts()]
    if (includePorts) {
      backgroundTasks.push(session.refreshPorts())
    }
    if ((isMapsRoute.value || isContactsRoute.value) && session.connected && session.collectionsReady && !session.contacts.length) {
      backgroundTasks.push(session.loadContacts())
    }
    await Promise.all(backgroundTasks)
    if (!isMessagesRoute.value) {
      const currentConnectionKey = String(session.activeConnectionKey || '')
      if (currentConnectionKey && currentConnectionKey !== syncedConnectionKey) {
        await session.syncSessionState({ light: true })
      }
    }
    if (!suppressStatus && session.connected) {
      session.setStatus(buildConnectedSessionStatus({
        t,
        targetName: phoneBarNodeName.value,
        collectionsReady: session.collectionsReady,
        queueState: session.queueState,
      }))
    }
  } catch (error) {
    if (!suppressStatus) {
      session.setStatus(error instanceof Error ? error.message : String(error || t('connect.status.loadFailed')), true)
    }
  } finally {
    refreshing.value = false
  }
}

function parseGifId(value) {
  const trimmed = String(value || '').trim()
  const match = /^g:([A-Za-z0-9_-]+)$/.exec(trimmed)
  return match ? String(match[1] || '') : ''
}

function contactDisplayName(contact) {
  return String(contact?.adv_name || contact?.name || getContactPrefix(contact) || contact?.public_key || '').trim() || t('messages.fallback.unnamedContact')
}

function contactAvatarEmoji(contact) {
  const text = contactDisplayName(contact)
  const match = text.match(/(\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?(?:\u200D\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?)*)/u)
  return match ? match[1] : ''
}

function contactAvatarText(contact) {
  const emoji = contactAvatarEmoji(contact)
  if (emoji) {
    return emoji
  }
  return (contactDisplayName(contact) || '?').slice(0, 2).toUpperCase()
}

function normalizeChannelName(value) {
  return String(value || '').trim()
}

function isPublicChannel(channel) {
  const normalizedName = normalizeChannelName(channel?.name).toLowerCase()
  return normalizedName.startsWith('#') || normalizedName === 'public' || Boolean(channel?.is_public)
}

function isOfficialPublicChannel(channel) {
  const normalizedName = normalizeChannelName(channel?.name).replace(/^#+/, '').toLowerCase()
  const normalizedIdentity = String(channel?.channel_identity || '').trim().toLowerCase()
  return normalizedName === 'public' || normalizedIdentity === 'public::#public'
}

function channelAvatarSymbol(channel) {
  if (isOfficialPublicChannel(channel)) {
    return '📣'
  }
  return isPublicChannel(channel) ? '#' : '🔒'
}

function formatChannelPreview(channel) {
  const preview = String(channel?.last_message_preview || '').trim()
  if (!preview) {
    return String(channel?.description || t('messages.fallback.channelPreview'))
  }
  if (parseGifId(preview)) {
    return t('messages.gif.messageLabel')
  }
  return channel?.last_message_from_self ? t('messages.youPrefix', { text: preview }) : preview
}

function formatContactPreview(contact) {
  const preview = String(contact?.last_message_text || '').trim()
  if (!preview) {
    return t('messages.fallback.directPreview')
  }
  if (parseGifId(preview)) {
    return t('messages.gif.messageLabel')
  }
  return contact?.last_message_from_self ? t('messages.youPrefix', { text: preview }) : preview
}

function buildMentionPreviewText(text, fallback = '') {
  const preview = String(text || '').trim()
  if (preview) {
    if (parseGifId(preview)) {
      return t('messages.gif.messageLabel')
    }
    return preview
  }
  return String(fallback || '').trim() || t('notifications.empty.noneUnread')
}

function findChannelByNotificationKey(key) {
  const parsedKey = parseChannelNotificationKey(key)
  const normalizedKey = parsedKey.identity || (parsedKey.idx != null ? String(parsedKey.idx) : parsedKey.raw)
  if (!normalizedKey) {
    return null
  }
  return session.channels.find((channel) => {
    const channelOwnerId = normalizeOwnerId(channel?.owner_id || '')
    const channelIdentity = String(channel?.channel_identity || '').trim()
    const channelIdx = String(channel?.idx ?? '').trim()
    if (parsedKey.ownerId && channelOwnerId && parsedKey.ownerId !== channelOwnerId) {
      return false
    }
    return normalizedKey === channelIdentity || normalizedKey === channelIdx
  }) || null
}

function parseChannelNotificationKey(key) {
  const raw = String(key || '').trim()
  const parsed = parseScopedConversationKey(raw)
  const normalized = String(parsed.baseKey || '').trim()
  const identityMatch = /^channelid:(.+)$/i.exec(normalized)
  if (identityMatch) {
    return {
      raw,
      ownerId: parsed.ownerId,
      idx: null,
      identity: identityMatch[1],
    }
  }
  const idxMatch = /^channel:(\d+)$/i.exec(normalized)
  if (idxMatch) {
    return {
      raw,
      ownerId: parsed.ownerId,
      idx: Number(idxMatch[1]),
      identity: '',
    }
  }
  const numericIdx = Number(normalized)
  if (Number.isFinite(numericIdx) && raw !== '') {
    return {
      raw,
      ownerId: parsed.ownerId,
      idx: numericIdx,
      identity: '',
    }
  }
  return {
    raw,
    ownerId: parsed.ownerId,
    idx: null,
    identity: normalized || raw,
  }
}

function buildChannelNotificationTarget(channelKey, fallback = {}) {
  const parsed = parseChannelNotificationKey(channelKey || fallback.channel_identity || fallback.channel_idx)
  const channel = findChannelByNotificationKey(parsed.identity || (parsed.idx != null ? parsed.idx : parsed.raw))
  const channelIdx = Number(channel?.idx ?? parsed.idx ?? fallback.channel_idx ?? -1)
  const channelIdentity = String(channel?.channel_identity || parsed.identity || fallback.channel_identity || '').trim()
  const title = String(
    channel?.name
    || fallback.channel_name
    || (channelIdentity || '')
    || (Number.isFinite(channelIdx) && channelIdx >= 0 ? `#${channelIdx}` : t('messages.fallback.channel'))
  ).trim()
  return {
    channel,
    channelIdx,
    channelIdentity,
    title,
    avatarSymbol: channelAvatarSymbol(channel || { idx: channelIdx, name: fallback.channel_name || channelIdentity }),
    preview: formatChannelPreview(channel || { description: channelIdentity || t('messages.fallback.channelPreview') }),
  }
}

function findContactByNotificationKey(key) {
  const parsed = parseScopedConversationKey(key)
  const normalizedKey = normalizePublicKey(
    parsed.baseKey.startsWith('contact:')
      ? parsed.baseKey.slice('contact:'.length)
      : key,
  )
  if (!normalizedKey) {
    return null
  }
  const contact = session.contacts.find((contact) => {
    const contactOwnerId = normalizeOwnerId(contact?.owner_id || '')
    const publicKey = normalizePublicKey(contact?.public_key)
    const prefix = getContactPrefix(contact)
    if (parsed.ownerId && contactOwnerId && parsed.ownerId !== contactOwnerId) {
      return false
    }
    return normalizedKey === publicKey || normalizedKey === prefix
  }) || null
  if (contact) {
    return contact
  }
  const selfContact = buildSelfContact()
  if (selfContact) {
    const selfPublicKey = normalizePublicKey(selfContact.public_key)
    const selfPrefix = getContactPrefix(selfContact)
    if (normalizedKey === selfPublicKey || normalizedKey === selfPrefix) {
      return selfContact
    }
  }
  return null
}

function escapeHtml(text) {
  return String(text || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function formatConsoleTimestamp() {
  return new Date().toLocaleString(locale.value === 'en' ? 'en-US' : 'ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function classifyConsolePayload(payload) {
  const source = JSON.stringify(payload || {}).toLowerCase()
  if (!source) {
    return ['session']
  }
  if (source.includes('error')) {
    return ['errors']
  }
  if (source.includes('send-confirmed')) {
    return ['delivery', 'send-confirmed']
  }
  if (source.includes('advert') || source.includes('radio')) {
    return ['advert-radio']
  }
  if (source.includes('channel')) {
    return ['channel']
  }
  if (source.includes('direct') || source.includes('contact')) {
    return ['direct']
  }
  return ['session']
}

function appendConsoleEntry(payload) {
  const filters = [...new Set(classifyConsolePayload(payload))]
  consoleEntries.value = [
    ...consoleEntries.value.slice(-159),
    {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      payload,
      filters,
      text: `${formatConsoleTimestamp()}\n${JSON.stringify(payload, null, 2)}\n`,
    },
  ]
}

function openMessages(panel = '') {
  const nextPanel = String(panel || '').trim()
  if (route.name === 'messages' && activeShellPanel.value === nextPanel && !nextPanel) {
    return
  }
  void router.push({
    path: '/messages',
    query: nextPanel ? { panel: nextPanel } : {},
  })
}

async function openShellPanel(panel = '') {
  const nextPanel = String(panel || '').trim()
  if (!nextPanel) {
    await closeShellPanel()
    return
  }
  await router.replace(buildToggleShellPanelLocation(route, nextPanel))
}

async function closeShellPanel() {
  if (!activeShellPanel.value) {
    return
  }
  await router.replace(buildCloseShellPanelLocation(route))
}

async function openAdvertPanel() {
  await router.replace(buildOpenShellPanelLocation(route, 'advert'))
}

async function closeGlobalAdvertPanel() {
  if (!globalAdvertOpen.value) {
    return
  }
  await router.replace(buildCloseShellPanelLocation(route))
}

async function sendAdvert(flood = false) {
  advertBusy.value = true
  advertMode.value = flood ? 'flood' : 'direct'
  try {
    session.setStatus(t('messages.status.sendingPacket', {
      type: packetTypeLabel(flood ? 'advert-flood' : 'advert-direct', { t }),
    }))
    await session.api('/api/advert', {
      method: 'POST',
      body: JSON.stringify({
        ...session.activeConfigBody(),
        flood: Boolean(flood),
      }),
    })
    session.noteRadioTransmission()
    session.setStatus(t(flood ? 'advert.status.floodSent' : 'advert.status.directSent'))
    await closeGlobalAdvertPanel()
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('advert.status.failed')), true)
  } finally {
    advertBusy.value = false
  }
}

const advertSheetModel = computed(() => {
  return {
    open: globalAdvertOpen.value,
    busy: advertBusy.value,
    mode: advertMode.value,
  }
})

const notificationSoundEnabled = computed(() => Boolean(session.settingsPayload?.settings?.notifications_sound_enabled))

const mentionNotificationEntries = computed(() => {
  const unreadMentionEntries = Array.isArray(unreadSummary.value.mention_entries) ? unreadSummary.value.mention_entries : []
  if (unreadMentionEntries.length) {
    return unreadMentionEntries.map((entry) => {
      const conversationKind = String(entry?.conversation_kind || '').trim().toLowerCase()
      if (conversationKind === 'channel') {
        const summaryKey = getChannelMuteKeys({
          owner_id: entry?.owner_id || '',
          channel_identity: entry?.channel_identity || '',
          idx: entry?.channel_idx,
        })[0] || String(entry?.channel_identity || entry?.channel_idx || '').trim()
        const target = buildChannelNotificationTarget(summaryKey, entry)
        return {
          kind: 'channel',
          key: `mention:channel:${Number(entry?.id || 0) || `${target.channelIdentity}:${target.channelIdx}`}`,
          title: target.title,
          preview: buildMentionPreviewText(entry?.text, target.preview),
          avatarSymbol: target.avatarSymbol,
          unreadCount: Number(unreadSummary.value.channel_unread_counts?.[summaryKey] || unreadSummary.value.channel_unread_counts?.[target.channelIdentity] || unreadSummary.value.channel_unread_counts?.[String(target.channelIdx)] || 0),
          mentionCount: 1,
          highlightTone: 'mention',
          value: target.channelIdx,
          channelIdentity: target.channelIdentity,
          focusMessageId: Number(entry?.id || 0),
        }
      }
      const contactKey = getContactMuteKeys({
        owner_id: entry?.owner_id || '',
        public_key: entry?.public_key || '',
        pubkey_prefix: entry?.pubkey_prefix || '',
      })[0] || String(entry?.public_key || entry?.pubkey_prefix || '').trim()
      const contact = findContactByNotificationKey(contactKey)
      const prefix = String(entry?.pubkey_prefix || getContactPrefix(contact) || '').trim().toLowerCase()
      const publicKey = String(contact?.public_key || prefix).trim()
      return {
        kind: 'contact',
        key: `mention:contact:${Number(entry?.id || 0) || prefix}`,
        title: contactDisplayName(contact || { public_key: prefix, pubkey_prefix: prefix }),
        preview: buildMentionPreviewText(entry?.text, formatContactPreview(contact || {})),
        avatarSymbol: contactAvatarText(contact || { public_key: prefix, pubkey_prefix: prefix }),
        unreadCount: Number(unreadSummary.value.contact_unread_counts?.[contactKey] || unreadSummary.value.contact_unread_counts?.[prefix] || 0),
        mentionCount: 1,
        highlightTone: 'mention',
        value: publicKey,
        focusMessageId: Number(entry?.id || 0),
      }
    }).filter((entry) => {
      if (entry.kind === 'channel') {
        return (Number.isFinite(Number(entry.value)) && Number(entry.value) >= 0) || Boolean(String(entry.channelIdentity || '').trim())
      }
      return Boolean(String(entry.value || '').trim())
    })
  }
  const entries = []
  for (const [channelKey, rawCount] of Object.entries(unreadSummary.value.channel_mention_counts || {})) {
    const count = Number(rawCount || 0)
    if (!count) {
      continue
    }
    const target = buildChannelNotificationTarget(channelKey)
    if (getChannelMuteMode(channelKey, target) === 'all') {
      continue
    }
    entries.push({
      kind: 'channel',
      key: `mention:channel:${channelKey}`,
      title: target.title,
      preview: target.preview,
      avatarSymbol: target.avatarSymbol,
      unreadCount: Number(unreadSummary.value.channel_unread_counts?.[channelKey] || unreadSummary.value.channel_unread_counts?.[String(target.channelIdx)] || 0),
      mentionCount: count,
      highlightTone: 'mention',
      value: target.channelIdx,
      channelIdentity: target.channelIdentity,
      focusMessageId: Number(unreadSummary.value.channel_first_mention_ids?.[channelKey] || unreadSummary.value.channel_first_unread_ids?.[channelKey] || 0),
    })
  }
  for (const [contactKey, rawCount] of Object.entries(unreadSummary.value.contact_mention_counts || {})) {
    const count = Number(rawCount || 0)
    if (!count) {
      continue
    }
    const contact = findContactByNotificationKey(contactKey)
    const prefix = getContactPrefix(contact) || normalizePublicKey(contactKey).slice(0, 12)
    const muteMode = getHighestPriorityMuteMode(
      getContactMuteKeys(contact || contactKey).map((muteKey) => getConversationMuteModeByKey(muteKey)),
    )
    if (muteMode === 'all') {
      continue
    }
    entries.push({
      kind: 'contact',
      key: `mention:contact:${contactKey}`,
      title: contactDisplayName(contact || { public_key: prefix, pubkey_prefix: prefix }),
      preview: formatContactPreview(contact || {}),
      avatarSymbol: contactAvatarText(contact || { public_key: prefix, pubkey_prefix: prefix }),
      unreadCount: Number(unreadSummary.value.contact_unread_counts?.[contactKey] || unreadSummary.value.contact_unread_counts?.[prefix] || 0),
      mentionCount: count,
      highlightTone: 'mention',
      value: String(contact?.public_key || prefix).trim(),
      focusMessageId: Number(unreadSummary.value.contact_first_mention_ids?.[contactKey] || unreadSummary.value.contact_first_mention_ids?.[prefix] || unreadSummary.value.contact_first_unread_ids?.[contactKey] || 0),
    })
  }
  return entries
})

const regularNotificationEntries = computed(() => {
  const entries = []
  for (const [channelKey, rawCount] of Object.entries(unreadSummary.value.channel_unread_counts || {})) {
    const count = Number(rawCount || 0)
    if (!count) {
      continue
    }
    const target = buildChannelNotificationTarget(channelKey)
    if (!target.channelIdentity || target.channelIdentity === '') {
      continue
    }
    if (getChannelMuteMode(channelKey, target) === 'regular' || getChannelMuteMode(channelKey, target) === 'all') {
      continue
    }
    entries.push({
      kind: 'channel',
      key: `regular:channel:${channelKey}`,
      title: target.title,
      preview: target.preview,
      avatarSymbol: target.avatarSymbol,
      unreadCount: count,
      mentionCount: Number(unreadSummary.value.channel_mention_counts?.[channelKey] || 0),
      highlightTone: 'unread',
      value: target.channelIdx,
      channelIdentity: target.channelIdentity,
      focusMessageId: Number(unreadSummary.value.channel_first_unread_ids?.[channelKey] || unreadSummary.value.channel_first_mention_ids?.[channelKey] || 0),
    })
  }
  return entries
})

const directNotificationEntries = computed(() => {
  const entries = []
  for (const [contactKey, rawCount] of Object.entries(unreadSummary.value.contact_unread_counts || {})) {
    const count = Number(rawCount || 0)
    if (!count) {
      continue
    }
    const contact = findContactByNotificationKey(contactKey)
    const prefix = getContactPrefix(contact) || normalizePublicKey(contactKey).slice(0, 12)
    const muteMode = getHighestPriorityMuteMode(
      getContactMuteKeys(contact || contactKey).map((muteKey) => getConversationMuteModeByKey(muteKey)),
    )
    if (muteMode === 'regular' || muteMode === 'all') {
      continue
    }
    entries.push({
      kind: 'contact',
      key: `direct:contact:${contactKey}`,
      title: contactDisplayName(contact || { public_key: prefix, pubkey_prefix: prefix }),
      preview: formatContactPreview(contact || {}),
      avatarSymbol: contactAvatarText(contact || { public_key: prefix, pubkey_prefix: prefix }),
      unreadCount: count,
      mentionCount: Number(unreadSummary.value.contact_mention_counts?.[contactKey] || unreadSummary.value.contact_mention_counts?.[prefix] || 0),
      highlightTone: 'direct',
      value: String(contact?.public_key || prefix).trim(),
      focusMessageId: Number(unreadSummary.value.contact_first_unread_ids?.[contactKey] || unreadSummary.value.contact_first_unread_ids?.[prefix] || unreadSummary.value.contact_first_mention_ids?.[contactKey] || 0),
    })
  }
  return entries
})

const updateNotificationEntry = computed(() => {
  if (!updateAvailable.value) return null
  return {
    kind: 'update',
    key: 'meshcorium-update',
    title: t('notifications.updateTitle'),
    preview: t('notifications.updateSubtitle', { version: updateCheck.value.next_version }),
    avatarSymbol: '⬆',
    nextVersion: updateCheck.value.next_version,
  }
})

const notificationsMetaText = computed(() => {
  if (!totalUnreadCount.value && !mentionNotificationEntries.value.length) {
    return t('notifications.empty.noneUnread')
  }
  const params = {
    chats: regularNotificationEntries.value.length + directNotificationEntries.value.length,
    unread: totalUnreadCount.value,
    mentions: mentionNotificationEntries.value.length,
  }
  return params.mentions > 0
    ? t('notifications.meta.summaryWithMentions', params)
    : t('notifications.meta.summaryNoMentions', params)
})

const notificationsSheetModel = computed(() => {
  return {
    open: notificationsOpen.value,
    notificationSoundEnabled: notificationSoundEnabled.value,
    notificationsMetaText: notificationsMetaText.value,
    totalUnreadCount: totalUnreadCount.value,
    totalRegularUnreadCount: totalRegularUnreadCount.value,
    totalDirectUnreadCount: totalDirectUnreadCount.value,
    totalMentionCount: totalMentionCount.value,
    bellIconUrl,
    mentionsCollapsed: notificationsMentionsCollapsed.value,
    regularCollapsed: notificationsRegularCollapsed.value,
    directCollapsed: notificationsDirectCollapsed.value,
    mentionEntries: mentionNotificationEntries.value,
    regularEntries: regularNotificationEntries.value,
    directEntries: directNotificationEntries.value,
    updateEntry: updateNotificationEntry.value,
  }
})

const filteredConsoleEntries = computed(() => {
  const filter = String(consoleFilter.value || 'none')
  return consoleEntries.value.filter((entry) => filter === 'none' || entry.filters.includes(filter))
})

const consoleFilterOptions = computed(() => {
  return [
    { value: 'none', label: t('console.filters.none') },
    { value: 'session', label: t('console.filters.session') },
    { value: 'channel', label: t('console.filters.channel') },
    { value: 'direct', label: t('console.filters.direct') },
    { value: 'delivery', label: t('console.filters.delivery') },
    { value: 'advert-radio', label: t('console.filters.advertRadio') },
    { value: 'errors', label: t('console.filters.errors') },
    { value: 'send-confirmed', label: t('console.filters.sendConfirmed') },
  ]
})

const consolePlainText = computed(() => {
  if (!filteredConsoleEntries.value.length) {
    return consoleEntries.value.length ? t('console.empty.filtered') : t('console.empty.stopped')
  }
  return filteredConsoleEntries.value.map((entry) => entry.text).join('\n')
})

const consoleHtml = computed(() => {
  const searchTerm = String(consoleSearchTerm.value || '').trim()
  if (!searchTerm) {
    return escapeHtml(consolePlainText.value)
  }
  const source = consolePlainText.value
  const sourceLower = source.toLowerCase()
  const needleLower = searchTerm.toLowerCase()
  let cursor = 0
  let html = ''
  while (cursor < source.length) {
    const index = sourceLower.indexOf(needleLower, cursor)
    if (index === -1) {
      html += escapeHtml(source.slice(cursor))
      break
    }
    html += escapeHtml(source.slice(cursor, index))
    html += `<span class="mc-console-hit">${escapeHtml(source.slice(index, index + searchTerm.length))}</span>`
    cursor = index + searchTerm.length
  }
  return html
})

const consoleSheetModel = computed(() => {
  return {
    open: consoleOpen.value,
    autoScroll: consoleAutoScroll.value,
    filter: consoleFilter.value,
    filterOptions: consoleFilterOptions.value,
    searchTerm: consoleSearchTerm.value,
    searchMatchIndex: consoleSearchMatchIndex.value,
    consoleHtml: consoleHtml.value,
    selfData: session.self,
    deviceData: session.device,
    bindLogRef: setConsoleLogElement,
  }
})

function syncConsoleSearchMatchState(options = {}) {
  const host = consoleLogRef.value
  if (!host) {
    return
  }
  const matches = Array.from(host.querySelectorAll('.mc-console-hit'))
  if (!matches.length) {
    consoleSearchMatchIndex.value = -1
    return
  }
  if (consoleSearchMatchIndex.value < 0 || consoleSearchMatchIndex.value >= matches.length) {
    consoleSearchMatchIndex.value = 0
  }
  matches.forEach((match, index) => {
    match.classList.toggle('active', index === consoleSearchMatchIndex.value)
  })
  if (options.scrollActive) {
    matches[consoleSearchMatchIndex.value]?.scrollIntoView({ block: 'center', inline: 'nearest' })
  }
}

function setConsoleLogElement(element) {
  consoleLogRef.value = element
  if (!element) {
    return
  }
  nextTick(() => {
    syncConsoleSearchMatchState()
    if (consoleOpen.value && consoleAutoScroll.value && consoleLogRef.value) {
      consoleLogRef.value.scrollTop = consoleLogRef.value.scrollHeight
    }
  })
}

function handleConsoleScroll() {
  const host = consoleLogRef.value
  if (!host) {
    return
  }
  consoleAutoScroll.value = (host.scrollHeight - host.scrollTop - host.clientHeight) < 24
}

function enableConsoleAutoScroll() {
  consoleAutoScroll.value = true
  nextTick(() => {
    if (consoleLogRef.value) {
      consoleLogRef.value.scrollTop = consoleLogRef.value.scrollHeight
    }
  })
}

function moveConsoleSearchMatch(direction) {
  const host = consoleLogRef.value
  if (!host) {
    return
  }
  const matches = Array.from(host.querySelectorAll('.mc-console-hit'))
  if (!matches.length) {
    return
  }
  const delta = direction < 0 ? -1 : 1
  consoleSearchMatchIndex.value = ((consoleSearchMatchIndex.value + delta) % matches.length + matches.length) % matches.length
  consoleAutoScroll.value = false
  nextTick(() => syncConsoleSearchMatchState({ scrollActive: true }))
}

function clearConsoleLog() {
  consoleEntries.value = []
  consoleAutoScroll.value = true
}

function saveConsoleLogSnapshot() {
  const payload = consolePlainText.value.trim() || `${t('console.empty.noEventsCaptured')}\n`
  const stamp = new Date().toISOString().replace(/[:.]/g, '-')
  const blob = new Blob([payload], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `meshcore_live_events_${stamp}.txt`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
  session.setStatus(t('console.status.saved'))
}

function stopConsoleListening() {
  if (consoleEventSource.value) {
    consoleEventSource.value.close()
    consoleEventSource.value = null
  }
  consoleEventSourceKey = ''
}

function stopNotificationListening() {
  if (notificationEventSource.value) {
    notificationEventSource.value.close()
    notificationEventSource.value = null
  }
  notificationEventSourceKey = ''
}

function scheduleUnreadRefresh(delayMs = 120) {
  if (unreadRefreshTimer) {
    window.clearTimeout(unreadRefreshTimer)
  }
  unreadRefreshTimer = window.setTimeout(() => {
    unreadRefreshTimer = 0
    void loadUnreadCounts()
  }, Math.max(0, Number(delayMs || 0)))
}

function startConsoleListening() {
  if (!session.connected || !getOwnerPort()) {
    stopConsoleListening()
    return
  }
  const eventStreamKey = buildOwnerEventStreamKey()
  if (consoleEventSource.value && consoleEventSourceKey === eventStreamKey) {
    return
  }
  stopConsoleListening()
  const query = session.activeEventStreamQuery() || new URLSearchParams()
  const source = new EventSource(`/api/events?${query.toString()}`)
  consoleEventSource.value = source
  consoleEventSourceKey = eventStreamKey
  source.onmessage = (event) => {
    let payload = {}
    try {
      const raw = String(event.data || '').trim()
      payload = raw ? JSON.parse(raw) : {}
    } catch {
      return
    }
    if (payload.event === 'heartbeat') {
      return
    }
    appendConsoleEntry(payload)
  }
  source.onerror = () => {
    if (!consoleOpen.value) {
      stopConsoleListening()
    }
  }
}

function startNotificationListening() {
  if (isMessagesRoute.value || !session.connected || !getOwnerPort()) {
    stopNotificationListening()
    return
  }
  const eventStreamKey = buildOwnerEventStreamKey()
  if (notificationEventSource.value && notificationEventSourceKey === eventStreamKey) {
    return
  }
  stopNotificationListening()
  const query = session.activeEventStreamQuery() || new URLSearchParams()
  const source = new EventSource(`/api/events?${query.toString()}`)
  notificationEventSource.value = source
  notificationEventSourceKey = eventStreamKey
  source.onmessage = (event) => {
    let payload = {}
    try {
      payload = JSON.parse(String(event.data || '{}'))
    } catch {
      return
    }
    if (payload.event === 'heartbeat') {
      return
    }
    if (payload.event === 'message') {
      scheduleUnreadRefresh()
    }
  }
  source.onerror = () => {
    if (!session.connected || isMessagesRoute.value) {
      stopNotificationListening()
    }
  }
}

async function ensureNotificationCollectionsReady() {
  if (!session.connected || !session.collectionsReady) {
    return
  }
  const jobs = []
  if (!session.channels.length) {
    jobs.push(session.loadChannels())
  }
  if (!session.contacts.length) {
    jobs.push(session.loadContacts())
  }
  if (jobs.length) {
    await Promise.allSettled(jobs)
  }
}

async function toggleNotificationSoundEnabled() {
  try {
    await session.toggleNotificationSoundEnabled()
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('notifications.sound.off')), true)
  }
}

async function setAllMessagesReadState(scope = 'regular') {
  const normalizedScope = String(scope || 'regular')
  const mentionName = String(session.self?.name || '')
  const data = await session.api('/api/messages/read-state', {
    method: 'POST',
    body: JSON.stringify({
      ...session.activeConfigBody(),
      is_read: true,
      scope: normalizedScope,
      mention_name: mentionName,
    }),
  })
  await loadUnreadCounts()
  const total = normalizedScope === 'mention'
    ? Number(data.mention_messages || 0) + Number(data.mention_contact_messages || 0)
    : normalizedScope === 'direct'
      ? Number(data.contact_messages || 0)
      : Number(data.messages || 0) + (normalizedScope === 'channel' ? 0 : Number(data.contact_messages || 0))
  session.setStatus(t(
    normalizedScope === 'mention'
      ? 'notifications.status.markedMentionsRead'
      : normalizedScope === 'direct'
        ? 'notifications.status.markedDirectMessagesRead'
        : 'notifications.status.markedMessagesRead',
    { total },
  ))
}

async function openNotificationEntry(entry) {
  notificationsOpen.value = false
  if (entry?.kind === 'update') {
    await router.push('/settings/about')
    return
  }
  const focusMessageId = Number(entry?.focusMessageId || 0)
  const tone = String(entry?.highlightTone || '').trim().toLowerCase()
  if (entry?.kind === 'channel') {
    const channelIdentity = String(entry?.channelIdentity || '').trim()
    const channelIdx = Number(entry?.value)
    await router.push({
      path: '/messages',
      query: {
        ...(Number.isFinite(channelIdx) && channelIdx >= 0 ? { channel: String(channelIdx) } : {}),
        ...(channelIdentity ? { channel_identity: channelIdentity } : {}),
        ...(focusMessageId > 0 ? { focus: String(focusMessageId) } : {}),
        ...((tone === 'mention' || tone === 'unread' || tone === 'direct') ? { tone } : {}),
      },
    })
    return
  }
  await router.push({
    path: '/messages',
    query: {
      contact: String(entry?.value || ''),
      ...(focusMessageId > 0 ? { focus: String(focusMessageId) } : {}),
      ...((tone === 'mention' || tone === 'unread' || tone === 'direct') ? { tone } : {}),
    },
  })
}

function openSettings() {
  router.push('/settings')
}

function openMaps() {
  router.push('/maps')
}

function openContacts() {
  router.push('/contacts')
}

async function disconnectAndStay() {
  try {
    await session.disconnectNode()
    await router.replace({ path: route.path })
    await loadUnreadCounts()
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('common.disconnect')), true)
  }
}

function handleShellEscape(event) {
  if (event.defaultPrevented || event.key !== 'Escape') {
    return
  }
  if (activeShellPanel.value) {
    event.preventDefault()
    void closeShellPanel()
  }
}

function disarmBrowserNotificationGesture() {
  if (!browserNotificationGestureArmed) {
    return
  }
  browserNotificationGestureArmed = false
  window.removeEventListener('pointerdown', handleBrowserNotificationGesture)
  window.removeEventListener('keydown', handleBrowserNotificationGesture)
}

function handleBrowserNotificationGesture() {
  void session.requestBrowserNotificationPermission()
  disarmBrowserNotificationGesture()
}

function armBrowserNotificationGesture() {
  if (browserNotificationGestureArmed || session.browserNotificationPermission !== 'default') {
    return
  }
  browserNotificationGestureArmed = true
  window.addEventListener('pointerdown', handleBrowserNotificationGesture, { passive: true })
  window.addEventListener('keydown', handleBrowserNotificationGesture)
}

watch(() => [session.radioStats?.last_tx_secs, session.radioStats?.tx_air_secs], ([nextLastTx, nextAirTx], [prevLastTx, prevAirTx] = []) => {
  if (
    (nextLastTx != null && prevLastTx != null && Number(nextLastTx) > Number(prevLastTx))
    || (nextAirTx != null && prevAirTx != null && Number(nextAirTx) > Number(prevAirTx))
  ) {
    session.noteRadioTransmission()
  }
})

watch(() => [phonebarTick.value, session.connected, session.stopState?.reconnect_attempts, session.stopState?.next_reconnect_at], () => {
  if (session.connected || session.connecting) {
    return
  }
  const restoreStatus = describeRestorePendingStatus(session.stopState, {
    t,
    locale: locale.value,
  })
  if (restoreStatus) {
    session.setStatus(restoreStatus)
  }
})

watch(() => [session.activeConnectionKey, session.self?.name], async ([nextConnectionKey]) => {
  if (!nextConnectionKey) {
    session.clearUnreadSummary()
    return
  }
  if (session.connected) {
    await loadUnreadCounts()
  }
})

watch(activeRailKey, async () => {
  await nextTick()
  animateRailGlowTransition()
}, { immediate: true })

watch(notificationsOpen, async (open) => {
  if (!open) {
    return
  }
  await ensureNotificationCollectionsReady()
  await loadUnreadCounts()
})

watch(
  () => [consoleOpen.value, session.connected, session.activeConnectionKey],
  ([open, connected, activeConnectionKey]) => {
    if (open && connected && String(activeConnectionKey || '').trim()) {
      startConsoleListening()
      return
    }
    stopConsoleListening()
  },
  { immediate: true },
)

watch(
  () => [isMessagesRoute.value, session.connected, session.activeConnectionKey],
  ([messagesRoute, connected, activeConnectionKey]) => {
    if (messagesRoute || !connected || !String(activeConnectionKey || '').trim()) {
      stopNotificationListening()
      return
    }
    startNotificationListening()
  },
  { immediate: true },
)

watch([consoleOpen, filteredConsoleEntries, consoleSearchTerm], async () => {
  await nextTick()
  syncConsoleSearchMatchState()
  if (consoleOpen.value && consoleAutoScroll.value && consoleLogRef.value) {
    consoleLogRef.value.scrollTop = consoleLogRef.value.scrollHeight
  }
})

const { pause: pausePhonebarTick, resume: resumePhonebarTick } = useIntervalFn(() => {
  phonebarTick.value = Date.now()
}, 1000, { immediate: false })

const { pause: pauseAutoRefresh, resume: resumeAutoRefresh } = useIntervalFn(() => {
  if (isMessagesRoute.value) {
    return
  }
  refreshShellState({ suppressStatus: true })
}, 30000, { immediate: false })

watch(visibility, (value) => {
  if (value === 'visible') {
    resumeAutoRefresh()
    if (!isMessagesRoute.value) {
      refreshShellState({ suppressStatus: true })
    }
    return
  }
  pauseAutoRefresh()
})

onMounted(async () => {
  window.addEventListener('keydown', handleShellEscape)
  window.addEventListener('resize', scheduleRailGlowMeasure)
  armBrowserNotificationGesture()
  resumePhonebarTick()
  resumeAutoRefresh()
  await refreshShellState({ includePorts: true, suppressStatus: true })
  startUpdateCheckPolling()
  bootstrapped.value = true
  await nextTick()
  scheduleRailGlowMeasure()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleShellEscape)
  window.removeEventListener('resize', scheduleRailGlowMeasure)
  pausePhonebarTick()
  pauseAutoRefresh()
  stopConsoleListening()
  stopNotificationListening()
  stopUpdateCheckPolling()
  disarmBrowserNotificationGesture()
  if (unreadRefreshTimer) {
    window.clearTimeout(unreadRefreshTimer)
    unreadRefreshTimer = 0
  }
  if (railGlowMeasureFrame) {
    cancelAnimationFrame(railGlowMeasureFrame)
  }
  if (railGlowReleaseTimer) {
    window.clearTimeout(railGlowReleaseTimer)
  }
})
</script>

<template>
  <div class="mc-page" :class="{ 'is-backdrop-blurred': pageBackdropBlurred, 'mc-page--global-mobile-dock': showGlobalMobileDock }">
    <div class="mc-shell" :class="{ 'is-blurred': shellBlurred }">
      <aside ref="railRef" class="mc-rail">
        <div
          class="mc-rail-active-glow"
          :class="{ 'is-visible': railGlowGeometry.visible }"
          :style="railGlowStyle"
          aria-hidden="true"
        ></div>
        <button
          v-tooltip="{ content: t('notifications.title'), theme: 'meshcorium-tooltip' }"
          class="mc-rail-button mc-rail-button--icon-only"
          :class="{ active: notificationsOpen, 'is-pulsing': totalRegularUnreadCount > 0 || totalDirectUnreadCount > 0 || totalMentionCount > 0 || updateAvailable }"
          type="button"
          :ref="(element) => setRailButtonElement('notifications', element)"
          :aria-label="t('notifications.title')"
          @click="openShellPanel('notifications')"
        >
          <img :src="bellIconUrl" :alt="t('notifications.title')" />
          <span v-if="totalRegularUnreadCount" class="mc-rail-badge">{{ totalRegularUnreadCount > 99 ? '99+' : totalRegularUnreadCount }}</span>
          <span v-if="totalDirectUnreadCount" class="mc-rail-badge mc-rail-badge--direct">{{ totalDirectUnreadCount > 99 ? '99+' : totalDirectUnreadCount }}</span>
          <span v-if="totalMentionCount" class="mc-rail-badge mc-rail-badge--mention">{{ totalMentionCount > 99 ? '99+' : totalMentionCount }}</span>
          <span v-if="updateAvailable" class="mc-rail-badge mc-rail-badge--update">U</span>
        </button>
        <button
          v-tooltip="{ content: t('messages.title'), theme: 'meshcorium-tooltip' }"
          class="mc-rail-button"
          :class="{ active: route.name === 'messages' && !activeShellPanel }"
          type="button"
          :ref="(element) => setRailButtonElement('messages', element)"
          :aria-label="t('messages.title')"
          @click="openMessages()"
        >
          <img :src="messagesIconUrl" :alt="t('messages.title')" />
        </button>
        <button
          v-tooltip="{ content: t('common.contacts'), theme: 'meshcorium-tooltip' }"
          class="mc-rail-button"
          :class="{ active: isContactsRoute && !activeShellPanel }"
          type="button"
          :ref="(element) => setRailButtonElement('contacts', element)"
          :aria-label="t('common.contacts')"
          @click="openContacts"
        >
          <img :src="contactsIconUrl" :alt="t('common.contacts')" />
        </button>
        <button
          v-tooltip="{ content: t('common.maps'), theme: 'meshcorium-tooltip' }"
          class="mc-rail-button"
          :class="{ active: isMapsRoute }"
          type="button"
          :ref="(element) => setRailButtonElement('maps', element)"
          :aria-label="t('common.maps')"
          @click="openMaps"
        >
          <img :src="mapIconUrl" :alt="t('common.maps')" />
        </button>
        <div class="mc-rail-divider"></div>
        <button
          v-tooltip="{ content: t('console.title'), theme: 'meshcorium-tooltip' }"
          class="mc-rail-button"
          :class="{ active: consoleOpen }"
          type="button"
          :ref="(element) => setRailButtonElement('console', element)"
          :aria-label="t('console.title')"
          @click="openShellPanel('console')"
        >
          <img :src="consoleIconUrl" :alt="t('console.title')" />
        </button>
        <button
          v-tooltip="{ content: t('advert.send'), theme: 'meshcorium-tooltip' }"
          class="mc-rail-button"
          :class="{ active: activeShellPanel === 'advert' || globalAdvertOpen }"
          type="button"
          :ref="(element) => setRailButtonElement('advert', element)"
          :aria-label="t('advert.send')"
          @click="openAdvertPanel"
        >
          <img :src="advertIconUrl" :alt="t('advert.send')" />
        </button>
        <button
          v-tooltip="{ content: t('common.wiki'), theme: 'meshcorium-tooltip' }"
          class="mc-rail-button"
          :class="{ active: route.name === 'wiki' }"
          type="button"
          :ref="(element) => setRailButtonElement('wiki', element)"
          :aria-label="t('common.wiki')"
          @click="router.push('/wiki')"
        >
          <img :src="wikiIconUrl" :alt="t('common.wiki')" />
        </button>
        <div class="mc-rail-spacer"></div>
        <div class="mc-rail-divider"></div>
        <button
          v-tooltip="{ content: t('common.settings'), theme: 'meshcorium-tooltip' }"
          class="mc-rail-button"
          :class="{ active: route.name === 'settings' }"
          type="button"
          :ref="(element) => setRailButtonElement('settings', element)"
          :aria-label="t('common.settings')"
          @click="openSettings"
        >
          <img :src="settingsIconUrl" :alt="t('common.settings')" />
        </button>
        <button
          v-tooltip="{ content: t('common.disconnect'), theme: 'meshcorium-tooltip' }"
          class="mc-rail-button mc-rail-button--danger"
          type="button"
          :aria-label="t('common.disconnect')"
          @click="disconnectAndStay"
        >
          <img :src="disconnectIconUrl" :alt="t('common.disconnect')" />
        </button>
      </aside>

      <RouterView />
    </div>

    <nav v-if="showGlobalMobileDock" class="mc-global-mobile-dock">
      <MobileDockButton
        :icon="bellIconUrl"
        label="Notif"
        :active="notificationsOpen"
        :badge="mobileNotificationBadge"
        :badge-class="updateAvailable && !totalUnreadCount && !totalMentionCount ? 'update' : (totalMentionCount ? 'mention' : '')"
        @click="openShellPanel('notifications')"
      />
      <MobileDockButton :icon="messagesIconUrl" label="Chats" @click="openMessages()" />
      <MobileDockButton :icon="contactsIconUrl" label="Contacts" @click="openContacts" />
      <MobileDockButton :icon="mapIconUrl" label="Map" :active="isMapsRoute && !activeShellPanel" @click="openMaps" />
      <MobileDockButton :icon="wikiIconUrl" label="Wiki" :active="route.name === 'wiki' && !activeShellPanel" @click="router.push('/wiki')" />
      <MobileDockButton :icon="settingsIconUrl" label="Settings" :active="route.name === 'settings' && !activeShellPanel" @click="openSettings" />
    </nav>

    <div v-if="bootstrapped && !session.connected && !disconnectOverlaySuppressed" class="mc-overlay" @click.self>
      <NodeConnectPanel @connected="loadUnreadCounts" />
    </div>

    <div v-if="showMessagesSyncOverlay" class="mc-overlay mc-overlay--soft">
      <section class="mc-sync-float">
        <p class="mc-overline">{{ t('messages.sync.overline') }}</p>
        <h3>{{ t('messages.sync.title') }}</h3>
        <p>{{ t('messages.sync.message', { target: syncTargetName }) }}</p>
      </section>
    </div>

    <MessagesAdvertSheet
      :model="advertSheetModel"
      @close="closeGlobalAdvertPanel"
      @send-flood="sendAdvert(true)"
      @send-direct="sendAdvert(false)"
    />

    <MessagesNotificationsSheet
      :model="notificationsSheetModel"
      @close="notificationsOpen = false"
      @toggle-sound="toggleNotificationSoundEnabled"
      @update:mentions-collapsed="notificationsMentionsCollapsed = $event"
      @update:regular-collapsed="notificationsRegularCollapsed = $event"
      @update:direct-collapsed="notificationsDirectCollapsed = $event"
      @mark-mentions-read="setAllMessagesReadState('mention')"
      @mark-regular-read="setAllMessagesReadState('channel')"
      @mark-direct-read="setAllMessagesReadState('direct')"
      @open-entry="openNotificationEntry"
    />

    <MessagesConsoleSheet
      :model="consoleSheetModel"
      @close="consoleOpen = false"
      @save="saveConsoleLogSnapshot"
      @update:search-term="consoleSearchTerm = $event"
      @move-search-match="moveConsoleSearchMatch"
      @enable-auto-scroll="enableConsoleAutoScroll"
      @update:filter="consoleFilter = $event"
      @clear="clearConsoleLog"
      @scroll-log="handleConsoleScroll"
    />
  </div>
</template>
