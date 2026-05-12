<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useIntervalFn, useStorage, useTextareaAutosize } from '@vueuse/core'
import 'vue3-emoji-picker/css'

import { useMessagesConversationList } from '../composables/useMessagesConversationList'
import { useMessagesReadTracking } from '../composables/useMessagesReadTracking'
import { useMessagesVirtualChat } from '../composables/useMessagesVirtualChat'
import MessagesChatHistoryPane from '../components/messages/MessagesChatHistoryPane.vue'
import MessagesComposerBar from '../components/messages/MessagesComposerBar.vue'
import MessagesConfirmSheet from '../components/messages/MessagesConfirmSheet.vue'
import MessagesConversationSidebar from '../components/messages/MessagesConversationSidebar.vue'
import MessagesChannelEditorWorkspace from '../components/messages/MessagesChannelEditorWorkspace.vue'
import MessagesWorkspaceHeader from '../components/messages/MessagesWorkspaceHeader.vue'
import MessagesEmptyWorkspace from '../components/messages/MessagesEmptyWorkspace.vue'
import MessagesMessageContextMenu from '../components/messages/MessagesMessageContextMenu.vue'
import MessagesRouteMapSheetLoading from '../components/messages/MessagesRouteMapSheetLoading.vue'
import ShellPageFrame from '../components/layout/ShellPageFrame.vue'
import ShellPhonebar from '../components/layout/ShellPhonebar.vue'
import {
  buildContactRoutePayloadFromMessage,
  buildKnownRoutePublicKeys,
} from '../lib/contactRoutes'
import { resolveDisplayedBatteryPercent } from '../lib/batteryProfile'
import { resolveNodePreviewUrl } from '../lib/nodePreview'
import { resolveCachedWallpaperAsset } from '../lib/wallpaperCache'
import {
  appendQueueStateStatus,
  buildConnectedSessionStatus,
  describeQueueDrainStatus,
  describeRestorePendingStatus,
  normalizeStopState,
  packetTypeLabel,
} from '../lib/sessionLiveState'
import { filterStatusTextForTransport } from '../lib/statusText'
import { useSessionStore } from '../stores/session'

const MessagesGifPickerSheet = defineAsyncComponent(() => import('../components/messages/MessagesGifPickerSheet.vue'))
const MessagesRouteMapSheet = defineAsyncComponent({
  loader: () => import('../components/messages/MessagesRouteMapSheet.vue'),
  delay: 0,
  suspensible: false,
  loadingComponent: MessagesRouteMapSheetLoading,
})

const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const { t, locale } = useI18n()

const bellIconUrl = '/icons/bell-icon.svg'
const messagesIconUrl = '/icons/paper-plane.png'
const advertIconUrl = '/icons/mesh_broadcast_icon.svg'
const usbIconUrl = '/icons/icons8-usb-100.png'
const MAX_MESSAGE_BODY_BYTES = 192
const OFFICIAL_PUBLIC_CHANNEL_NAME = '#public'
const OFFICIAL_PUBLIC_CHANNEL_PSK_HEX = '8b3387e9c5cdea6ac9e5edbaa115cd72'
const GIPHY_API_KEY = 'sXpGFDGZs0Dv1mmNFvYaGUvYwKX0PWIh'
const GIPHY_PICKER_LIMIT = 25
const INITIAL_HISTORY_LIMIT = 50
const HISTORY_PAGE_SIZE = 50
const DIALOG_CACHE_ENTRY_LIMIT = 8
const DIALOG_CACHE_MESSAGE_LIMIT = 150
const DIALOG_SENT_HISTORY_ENTRY_LIMIT = 8
const DIALOG_SENT_HISTORY_MAX_ITEMS = 20
const HYDRATION_DIALOG_SETTLE_MS = 1800
const CONVERSATION_ROW_ESTIMATED_HEIGHT = 77
const CONVERSATION_ROW_OVERSCAN_PX = 500
const MESSAGE_VIRTUAL_ESTIMATED_HEIGHT = 128
const MESSAGE_VIRTUAL_GAP = 16
const MESSAGE_VIRTUAL_OVERSCAN_PX = 900
const DEFAULT_CHAT_BACKPLANE_URL = '/icons/chat-backplane-blue.jpg'

const selectedConversationKind = ref('channel')
const selectedChannelIdx = ref(null)
const selectedChannelIdentity = ref('')
const selectedContactKey = ref('')
const messages = ref([])
const messageConversationDirectory = ref({
  channels: [],
  contacts: [],
})
const loadingConversationDirectory = ref(false)
const loadingMessages = ref(false)
const loadingOlderMessages = ref(false)
const draftText = ref('')
const composerHistoryIndex = ref(-1)
const composerHistoryDraftSnapshot = ref('')
const composerHistoryApplying = ref(false)
const replyDraft = ref(null)
const gifPickerOpen = ref(false)
const gifPickerBusy = ref(false)
const gifPickerLoadingMore = ref(false)
const gifPickerError = ref('')
const gifPickerSearchTerm = ref('')
const gifPickerItems = ref([])
const gifPickerOffset = ref(0)
const gifPickerHasMore = ref(true)
const sending = ref(false)
const activeConversationTotalMessages = ref(0)
const composerTextarea = ref(null)
const emojiPickerOpen = ref(false)
const animatedMessageKeys = ref([])
const unreadRefreshTimer = ref(null)
const unreadRequestSeq = ref(0)
const unreadAppliedSeq = ref(0)
const historyLoadSeq = ref(0)
const topHistoryPaginationArmed = ref(true)
const suppressTopPaginationUntil = ref(0)
const chatEditMode = ref(false)
const workspaceMode = ref('chat')
const channelEditorBusy = ref(false)
const channelEditorDeleteBusy = ref(false)
const channelEditorSecretPreview = ref('')
const channelEditorHashPreview = ref('')
const channelEditorForm = ref({
  channelIdx: null,
  channelIdentity: '',
  type: 'hashtag',
  name: '',
  hashtag: '',
  pskHex: '',
})

const notificationsOpen = computed({
  get() {
    return route.name === 'messages' && String(route.query.panel || '') === 'notifications'
  },
  set(value) {
    if (value) {
      router.replace({ path: '/messages', query: { panel: 'notifications' } })
      return
    }
    if (route.name === 'messages' && String(route.query.panel || '') === 'notifications') {
      router.replace({ path: '/messages' })
    }
  },
})
const notificationsMentionsCollapsed = ref(false)
const notificationsRegularCollapsed = ref(false)
const chatActionsMenuOpen = ref(false)
const dialogHistoryCache = useStorage('meshcorium_dialog_history_cache_v1', {}, globalThis.sessionStorage)
const channelDialogOrder = useStorage('meshcorium_channel_dialog_order_v1', [])
const sentDraftHistoryCache = useStorage('meshcorium_sent_draft_history_v2', {}, globalThis.sessionStorage)

const consoleOpen = computed({
  get() {
    return route.name === 'messages' && String(route.query.panel || '') === 'console'
  },
  set(value) {
    if (value) {
      router.replace({ path: '/messages', query: { panel: 'console' } })
      return
    }
    if (route.name === 'messages' && String(route.query.panel || '') === 'console') {
      router.replace({ path: '/messages' })
    }
  },
})
const consoleEntries = ref([])
const consoleAutoScroll = ref(true)
const consoleFilter = ref('none')
const consoleSearchTerm = ref('')
const consoleSearchMatchIndex = ref(-1)
const consoleLogRef = ref(null)
const resolvedChatWallpaperUrl = ref('')
let releaseChatWallpaperUrl = null

const advertOpen = computed({
  get() {
    return route.name === 'messages' && String(route.query.panel || '') === 'advert'
  },
  set(value) {
    if (value) {
      router.replace({ path: '/messages', query: { panel: 'advert' } })
      return
    }
    if (route.name === 'messages' && String(route.query.panel || '') === 'advert') {
      router.replace({ path: '/messages' })
    }
  },
})
const eventSource = ref(null)
const phonebarTick = ref(Date.now())
const lastRadioTxSecs = ref(null)
const lastHydrationChangeAt = ref(0)
let conversationCacheWriteTimerId = 0
let pendingConversationCacheWrite = null
let messageTopPaginationIntentHost = null
let hydrationCompletionTimerId = 0
let notificationHighlightTimerId = 0
let eventSourceKey = ''

const confirmDialog = ref({
  open: false,
  title: '',
  message: '',
  confirmLabel: '',
  action: null,
})

const messageContextMenu = ref({
  open: false,
  messageId: 0,
  x: 0,
  y: 0,
  routeParticipant: null,
})
const messageRouteSheet = ref({
  open: false,
  hops: [],
  preview: '',
  conversationKind: 'channel',
  messageId: 0,
  participants: [],
})
const notificationHighlightState = ref({
  messageId: 0,
  tone: '',
})

const footerStatusText = computed(() => {
  return filterStatusTextForTransport(session.statusText, session.selectedTransportType)
})

const unreadSummary = computed(() => session.unreadSummary || {})
const accessAllMeshcoriumMessages = computed(() => Boolean(session.settingsPayload?.settings?.access_all_meshcorium_messages !== false))
const accessAllMeshcoriumChannels = computed(() => {
  const channels = Array.isArray(session.channels) ? session.channels : []
  return channels.some((channel) => Boolean(channel?.access_all_messages_enabled))
})

function channelListMergeKey(channel) {
  const rawIdentity = String(channel?.channel_identity || '').trim()
  const idx = Number(channel?.idx ?? -1)
  const normalizedName = String(channel?.name || '').trim().replace(/^#+/, '').toLowerCase()
  const isOfficialPublicAlias = (
    rawIdentity.toLowerCase() === `public::${OFFICIAL_PUBLIC_CHANNEL_NAME}`
    || rawIdentity.toLowerCase() === 'public::public'
    || (Number.isFinite(idx) && idx === 0)
    || normalizedName === OFFICIAL_PUBLIC_CHANNEL_NAME.slice(1)
  )
  const identity = isOfficialPublicAlias ? `public::${OFFICIAL_PUBLIC_CHANNEL_NAME}` : rawIdentity
  if (identity) {
    return `identity:${identity}`
  }
  return Number.isFinite(idx) && idx >= 0 ? `idx:${idx}` : ''
}

function channelDialogOrderKey(channel) {
  return channelListMergeKey(channel)
}

function buildOfficialPublicChannelFallback() {
  return {
    idx: 0,
    name: OFFICIAL_PUBLIC_CHANNEL_NAME,
    secret_hex: '',
    hash: '',
    channel_identity: `public::${OFFICIAL_PUBLIC_CHANNEL_NAME}`,
    is_public: true,
    is_on_node: true,
  }
}

const conversationChannelsSource = computed(() => {
  const liveChannels = Array.isArray(session.channels) ? session.channels : []
  const merged = new Map()
  const upsertChannel = (channel, isOnNode = false) => {
    const key = channelListMergeKey(channel)
    if (!key) {
      return
    }
    const current = merged.get(key) || {}
    merged.set(key, {
      ...current,
      ...channel,
      is_on_node: Boolean(current?.is_on_node) || Boolean(isOnNode) || Boolean(channel?.is_on_node),
    })
  }
  if (accessAllMeshcoriumMessages.value && accessAllMeshcoriumChannels.value) {
    const directoryChannels = Array.isArray(messageConversationDirectory.value?.channels) ? messageConversationDirectory.value.channels : []
    for (const channel of directoryChannels) {
      upsertChannel(channel, false)
    }
  }
  for (const channel of liveChannels) {
    upsertChannel(channel, true)
  }
  const publicChannelKey = channelListMergeKey(buildOfficialPublicChannelFallback())
  if (
    session.connected
    && !merged.has(publicChannelKey)
  ) {
    upsertChannel(buildOfficialPublicChannelFallback(), true)
  }
  return Array.from(merged.values())
})
const conversationContactsSource = computed(() => {
  if (!accessAllMeshcoriumMessages.value) {
    return Array.isArray(session.contacts) ? session.contacts : []
  }
  const contacts = Array.isArray(messageConversationDirectory.value?.contacts) ? messageConversationDirectory.value.contacts : []
  return contacts.length ? contacts : (Array.isArray(session.contacts) ? session.contacts : [])
})
const requestedRouteContactKey = computed(() => {
  if (route.name !== 'messages') {
    return ''
  }
  return normalizePublicKey(route.query.contact)
})
const requestedRouteChannelIdx = computed(() => {
  if (route.name !== 'messages') {
    return null
  }
  const value = Number(route.query.channel)
  return Number.isFinite(value) && value >= 0 ? value : null
})
const requestedRouteChannelIdentity = computed(() => {
  if (route.name !== 'messages') {
    return ''
  }
  return String(route.query.channel_identity || '').trim()
})
const requestedRouteFocusMessageId = computed(() => {
  if (route.name !== 'messages') {
    return 0
  }
  const value = Number(route.query.focus)
  return Number.isFinite(value) && value > 0 ? value : 0
})
const requestedRouteHighlightTone = computed(() => {
  if (route.name !== 'messages') {
    return ''
  }
  const tone = String(route.query.tone || '').trim().toLowerCase()
  return tone === 'mention' || tone === 'unread' || tone === 'direct' ? tone : ''
})
const requestedRouteFocusComposer = computed(() => {
  if (route.name !== 'messages') {
    return false
  }
  const raw = String(route.query.compose || '').trim().toLowerCase()
  return raw === '1' || raw === 'true' || raw === 'yes'
})

function normalizePublicKey(value) {
  return String(value || '').trim().toLowerCase()
}

function getContactPrefix(contactOrKey) {
  const raw = typeof contactOrKey === 'string'
    ? contactOrKey
    : (contactOrKey?.pubkey_prefix || contactOrKey?.public_key || '')
  return normalizePublicKey(raw).slice(0, 12)
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

function contactDisplayName(contact) {
  return String(contact?.adv_name || contact?.name || getContactPrefix(contact) || contact?.public_key || '').trim() || t('messages.fallback.unnamedContact')
}

function contactKindLabel(contact) {
  const kind = Number(contact?.adv_type || 0)
  if (kind === 2) {
    return 'repeater'
  }
  if (kind === 3) {
    return 'room'
  }
  if (kind === 4) {
    return 'sensor'
  }
  return 'user'
}

function contactKindBadgeLabel(contact) {
  return t(`messages.contactKindBadges.${contactKindLabel(contact)}`)
}

function firstEmojiInText(value) {
  const text = String(value || '').trim()
  if (!text) {
    return ''
  }
  const match = text.match(/(\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?(?:\u200D\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?)*)/u)
  return match ? match[1] : ''
}

function contactAvatarEmoji(contact) {
  return firstEmojiInText(contactDisplayName(contact))
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

function parseGifId(value) {
  const trimmed = String(value || '').trim()
  const match = /^g:([A-Za-z0-9_-]+)$/.exec(trimmed)
  return match ? String(match[1] || '') : ''
}

function isRenderableRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function sanitizeMessageList(items) {
  if (!Array.isArray(items)) {
    return []
  }
  return items.filter((item) => isRenderableRecord(item))
}

function gifCdnUrl(gifId) {
  const normalized = String(gifId || '').trim()
  return normalized ? `https://media.giphy.com/media/${encodeURIComponent(normalized)}/giphy.gif` : ''
}

function gifPreviewUrl(gif) {
  return String(
    gif?.images?.fixed_height_small?.url
    || gif?.images?.fixed_width_small?.url
    || gif?.images?.downsized_small?.gif_url
    || gif?.images?.original?.url
    || '',
  ).trim()
}

function normalizeMeshcoreChannelName(value) {
  const normalized = normalizeChannelName(value)
  return normalized.replace(/^#+/, '').toLowerCase() === OFFICIAL_PUBLIC_CHANNEL_NAME.slice(1) ? OFFICIAL_PUBLIC_CHANNEL_NAME : normalized
}

function isHashtagChannelName(value) {
  return normalizeChannelName(value).startsWith('#')
}

function isOfficialPublicChannelName(value) {
  return normalizeMeshcoreChannelName(value).toLowerCase() === OFFICIAL_PUBLIC_CHANNEL_NAME
}

function isOfficialPublicChannel(channel) {
  return Boolean(
    isOfficialPublicChannelName(channel?.name)
    || String(channel?.channel_identity || '').trim().toLowerCase() === `public::${OFFICIAL_PUBLIC_CHANNEL_NAME}`,
  )
}

function isProtectedPublicChannel(channel) {
  return isOfficialPublicChannel(channel)
}

function isPublicChannel(channel) {
  const normalizedName = normalizeChannelName(channel?.name).toLowerCase()
  return normalizedName.startsWith('#') || normalizedName === 'public' || channel?.is_public
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

function displayChannelTitle(channelName, channelIdx, channelIdentity = '') {
  const normalizedName = normalizeChannelName(channelName)
  if (normalizedName) {
    return normalizedName
  }
  if (String(channelIdentity || '').trim().toLowerCase() === `public::${OFFICIAL_PUBLIC_CHANNEL_NAME}` || Number(channelIdx) === 0) {
    return OFFICIAL_PUBLIC_CHANNEL_NAME
  }
  return Number(channelIdx) >= 0 ? `#${Number(channelIdx)}` : t('messages.fallback.channel')
}

function formatContactPreview(contact) {
  const preview = String(contact?.last_message_text || '').trim()
  if (preview) {
    if (parseGifId(preview)) {
      return contact?.last_message_from_self
        ? t('messages.youPrefix', { text: t('messages.gif.messageLabel') })
        : t('messages.gif.messageLabel')
    }
    return contact?.last_message_from_self ? t('messages.youPrefix', { text: preview }) : preview
  }
  return getContactPrefix(contact) || t('messages.fallback.directChat')
}

function formatTimestamp(epoch) {
  const timestamp = Number(epoch || 0)
  if (!timestamp) {
    return ''
  }
  try {
    return new Date(timestamp * 1000).toLocaleString(locale.value === 'en' ? 'en-US' : 'ru-RU', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return String(timestamp)
  }
}

function formatConsoleTimestamp() {
  return new Date().toLocaleString(locale.value === 'en' ? 'en-US' : 'ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
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

const mutedConversationsMap = computed(() => normalizeMutedConversationsMap(session.settingsPayload?.settings?.muted_conversations))

function getConversationMuteKey(kind, value) {
  return getConversationMuteKeys(kind, value)[0] || ''
}

function getChannelMuteKey(channelOrIdx) {
  return getConversationMuteKey('channel', channelOrIdx)
}

function getContactMuteKey(contactOrPrefix) {
  return getConversationMuteKey('contact', contactOrPrefix)
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

function getConversationMuteKeys(kind, value) {
  const normalizedKind = String(kind || '').trim().toLowerCase()
  const keys = []
  if (normalizedKind === 'channel') {
    if (value && typeof value === 'object') {
      const ownerId = normalizeOwnerId(value.owner_id || value.ownerId || '')
      const channelIdentity = String(value.channel_identity || value.channelIdentity || '').trim()
      const channelIdx = Number(value.idx ?? value.channel_idx ?? value.channelIdx ?? -1)
      if (channelIdentity) {
        appendScopedAndLegacyMuteKey(keys, `channelid:${channelIdentity}`, ownerId)
      }
      if (Number.isFinite(channelIdx) && channelIdx >= 0) {
        appendScopedAndLegacyMuteKey(keys, `channel:${channelIdx}`, ownerId)
      }
      return keys
    }
    const parsed = parseScopedConversationKey(value)
    if (parsed.baseKey.startsWith('channelid:') || parsed.baseKey.startsWith('channel:')) {
      appendScopedAndLegacyMuteKey(keys, parsed.baseKey, parsed.ownerId)
      return keys
    }
    const channelIdx = Number(String(value || '').trim())
    if (Number.isFinite(channelIdx) && String(value || '').trim() !== '' && channelIdx >= 0) {
      appendScopedAndLegacyMuteKey(keys, `channel:${channelIdx}`, parsed.ownerId)
      return keys
    }
    if (String(value || '').trim()) {
      appendScopedAndLegacyMuteKey(keys, `channelid:${String(value || '').trim()}`, parsed.ownerId)
    }
    return keys
  }
  if (normalizedKind === 'contact') {
    if (value && typeof value === 'object') {
      const ownerId = normalizeOwnerId(value.owner_id || value.ownerId || '')
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
  }
  return keys
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

function getChannelMuteKeys(channelOrIdx) {
  return getConversationMuteKeys('channel', channelOrIdx)
}

function getContactMuteKeys(contactOrPrefix) {
  return getConversationMuteKeys('contact', contactOrPrefix)
}

function getChannelMuteMode(channelOrIdx) {
  return getHighestPriorityMuteMode(
    getChannelMuteKeys(channelOrIdx).map((muteKey) => getConversationMuteModeByKey(muteKey)),
  )
}

function getContactMuteMode(contactOrPrefix) {
  return getHighestPriorityMuteMode(
    getContactMuteKeys(contactOrPrefix).map((muteKey) => getConversationMuteModeByKey(muteKey)),
  )
}

function getConversationMuteModeForEntry(entry) {
  if (!entry?.kind) {
    return 'none'
  }
  if (entry.kind === 'channel') {
    return getChannelMuteMode(entry.channel)
  }
  return getHighestPriorityMuteMode(
    getContactMuteKeys(entry.contact).map((muteKey) => getConversationMuteModeByKey(muteKey)),
  )
}

function getCurrentConversationMuteKey() {
  if (selectedConversationKind.value === 'channel' && (selectedChannelIdx.value != null || selectedChannelIdentity.value)) {
    return getChannelMuteKey(selectedChannel.value || selectedChannelIdx.value)
  }
  if (selectedConversationKind.value === 'contact' && selectedContactKey.value) {
    return getContactMuteKey(selectedContact.value || selectedContactKey.value)
  }
  return ''
}

function getCurrentConversationMuteMode() {
  if (selectedConversationKind.value === 'channel' && (selectedChannelIdx.value != null || selectedChannelIdentity.value)) {
    return getChannelMuteMode(selectedChannel.value || {
      idx: selectedChannelIdx.value,
      channel_identity: selectedChannelIdentity.value,
    })
  }
  return getConversationMuteModeByKey(getCurrentConversationMuteKey())
}

function isConversationRegularMutedByKey(muteKey) {
  const mode = getConversationMuteModeByKey(muteKey)
  return mode === 'regular' || mode === 'all'
}

function isConversationMentionMutedByKey(muteKey) {
  return getConversationMuteModeByKey(muteKey) === 'all'
}

function conversationMuteIndicatorLabel(mode) {
  return t(mode === 'all' ? 'messages.chatMenu.muteIndicatorAll' : 'messages.chatMenu.muteIndicatorRegular')
}

function hasOwnSummaryValue(summaryMap, key) {
  return Boolean(summaryMap) && Object.prototype.hasOwnProperty.call(summaryMap, key)
}

function resolveChannelSummaryCount(summaryMap, channel, fallbackValue = null) {
  for (const key of getChannelMuteKeys(channel)) {
    const parsed = parseScopedConversationKey(key)
    if (hasOwnSummaryValue(summaryMap, parsed.baseKey)) {
      return Number(summaryMap[parsed.baseKey] || 0)
    }
    if (hasOwnSummaryValue(summaryMap, key)) {
      return Number(summaryMap[key] || 0)
    }
  }
  return fallbackValue == null ? null : Number(fallbackValue || 0)
}

function resolveContactSummaryCount(summaryMap, contact, fallbackValue = null) {
  for (const key of getContactMuteKeys(contact)) {
    const parsed = parseScopedConversationKey(key)
    const legacyPrefix = parsed.baseKey.startsWith('contact:') ? parsed.baseKey.slice('contact:'.length) : ''
    if (legacyPrefix && hasOwnSummaryValue(summaryMap, legacyPrefix)) {
      return Number(summaryMap[legacyPrefix] || 0)
    }
    if (hasOwnSummaryValue(summaryMap, key)) {
      return Number(summaryMap[key] || 0)
    }
    if (hasOwnSummaryValue(summaryMap, parsed.baseKey)) {
      return Number(summaryMap[parsed.baseKey] || 0)
    }
  }
  return fallbackValue == null ? null : Number(fallbackValue || 0)
}

function displayedChannelUnreadCount(channel) {
  if (getChannelMuteMode(channel) === 'regular' || getChannelMuteMode(channel) === 'all') {
    return 0
  }
  return resolveChannelSummaryCount(
    unreadSummary.value.channel_unread_counts,
    channel,
    channel?.unread_count ?? 0,
  )
}

function displayedChannelMentionCount(channel) {
  if (getChannelMuteMode(channel) === 'all') {
    return 0
  }
  return resolveChannelSummaryCount(
    unreadSummary.value.channel_mention_counts,
    channel,
    channel?.mention_count ?? 0,
  )
}

function displayedContactUnreadCount(contact) {
  const muteMode = getContactMuteMode(contact)
  if (muteMode === 'regular' || muteMode === 'all') {
    return 0
  }
  return resolveContactSummaryCount(
    unreadSummary.value.contact_unread_counts,
    contact,
    contact?.unread_count ?? 0,
  )
}

function displayedContactMentionCount(contact) {
  if (getContactMuteMode(contact) === 'all') {
    return 0
  }
  return resolveContactSummaryCount(
    unreadSummary.value.contact_mention_counts,
    contact,
    contact?.mention_count ?? 0,
  )
}

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

function escapeHtml(text) {
  return String(text || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function getOwnerPort() {
  return String(session.activeConnectionPort || '')
}

function applyConnectedStatusFromSnapshot(snapshot = session.sessionSnapshot) {
  session.setStatus(buildConnectedSessionStatus({
    t,
    targetName: String(snapshot?.self?.name || phoneBarNodeName.value || getOwnerPort() || 'meshcore').trim(),
    collectionsReady: Boolean(snapshot?.collections_ready ?? session.collectionsReady),
    queueState: snapshot?.queue_state || session.queueState,
  }))
}

function applyRestorePendingStatus() {
  if (session.connecting) {
    return
  }
  const restoreStatus = describeRestorePendingStatus(session.stopState, {
    t,
    locale: locale.value,
  })
  if (restoreStatus) {
    session.setStatus(restoreStatus)
  }
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

const {
  directConversationRows,
  channelScrollerRows,
  conversationHasEntries,
  conversationListItems,
  visibleConversationListWindow,
  updateConversationListMetrics,
  setConversationListScroller,
  ensureConversationRowResizeObserver,
  disconnectConversationRowResizeObserver,
  bindConversationRowElement,
} = useMessagesConversationList({
  session,
  channelsSource: conversationChannelsSource,
  contactsSource: conversationContactsSource,
  locale,
  t,
  unreadSummary,
  selectedConversationKind,
  selectedChannelIdx,
  selectedChannelIdentity,
  selectedContactKey,
  chatEditMode,
  channelDialogOrder,
  estimatedRowHeight: CONVERSATION_ROW_ESTIMATED_HEIGHT,
  overscanPx: CONVERSATION_ROW_OVERSCAN_PX,
  helpers: {
    channelDialogOrderKey,
    getContactPrefix,
    contactDisplayName,
    contactAvatarEmoji,
    contactKindLabel,
    contactKindBadgeLabel,
    formatContactPreview,
    formatChannelPreview,
    isPublicChannel,
    isProtectedPublicChannel,
    isOfficialPublicChannelName,
    channelAvatarSymbol,
    displayChannelTitle,
    displayedChannelUnreadCount,
    displayedChannelMentionCount,
    displayedContactUnreadCount,
    displayedContactMentionCount,
    getChannelMuteKey,
    getContactMuteKey,
    getConversationMuteModeForEntry,
    conversationMuteIndicatorLabel,
    normalizePublicKey,
    resolveChannelSummaryCount,
    resolveContactSummaryCount,
  },
})

const selectedChannel = computed(() => {
  if (selectedChannelIdx.value == null && !selectedChannelIdentity.value) {
    return null
  }
  const channel = conversationChannelsSource.value.find((channel) => (
    (selectedChannelIdentity.value && String(channel?.channel_identity || '').trim() === String(selectedChannelIdentity.value || '').trim())
    || (selectedChannelIdx.value != null && Number(channel?.idx) === Number(selectedChannelIdx.value))
  )) || null
  if (channel) {
    return channel
  }
  if (selectedChannelIdentity.value) {
    return {
      idx: selectedChannelIdx.value ?? 0,
      name: displayChannelTitle('', selectedChannelIdx.value ?? 0, selectedChannelIdentity.value),
      description: t('messages.fallback.channelPreview'),
      channel_identity: selectedChannelIdentity.value,
      is_on_node: false,
    }
  }
  return null
})

const selectedContact = computed(() => {
  const match = directConversationRows.value.find((row) => row.value === normalizePublicKey(selectedContactKey.value))
  return match?.contact || null
})

const currentConversation = computed(() => {
  return selectedConversationKind.value === 'contact' ? selectedContact.value : selectedChannel.value
})

const workspaceShowsChannelEditor = computed(() => {
  return workspaceMode.value === 'edit-channel' || workspaceMode.value === 'new-channel'
})

const editingChannel = computed(() => {
  const idx = Number(channelEditorForm.value.channelIdx ?? -1)
  if (idx < 0) {
    return null
  }
  const byIdentity = String(channelEditorForm.value.channelIdentity || '').trim()
  return (Array.isArray(session.channels) ? session.channels : []).find((channel) => (
    (byIdentity && String(channel?.channel_identity || '').trim() === byIdentity)
    || Number(channel?.idx ?? -1) === idx
  )) || null
})

const channelEditorProtectedPublic = computed(() => {
  if (workspaceMode.value !== 'edit-channel') {
    return false
  }
  return isProtectedPublicChannel(editingChannel.value)
})

const channelEditorCanEdit = computed(() => !channelEditorProtectedPublic.value)

const channelEditorCanDelete = computed(() => {
  return Boolean(
    workspaceMode.value === 'edit-channel'
    && session.connected
    && !channelEditorBusy.value
    && editingChannel.value != null,
  )
})

const currentConversationKey = computed(() => {
  if (selectedConversationKind.value === 'contact') {
    const contactKey = normalizePublicKey(selectedContactKey.value)
    return contactKey ? `contact:${contactKey}` : ''
  }
  if (selectedChannelIdx.value == null && !selectedChannelIdentity.value) {
    return ''
  }
  const identity = String(selectedChannelIdentity.value || '').trim()
  return identity ? `channel:${identity}` : `channel:${Number(selectedChannelIdx.value)}`
})

const hydrationConversationSignature = computed(() => {
  const expectedContacts = Math.max(0, Number(session.sessionSnapshot?.contacts_count ?? conversationContactsSource.value.length) || 0)
  const expectedChannels = Math.max(0, Number(session.sessionSnapshot?.channels_count ?? conversationChannelsSource.value.length) || 0)
  const loadedContacts = Math.max(0, Number(conversationContactsSource.value.length || 0))
  const loadedChannels = Math.max(0, Number(conversationChannelsSource.value.length || 0))
  const channelKeys = channelScrollerRows.value.map((row) => String(row.channelKey || row.value || '')).join('|')
  const directKeys = directConversationRows.value
    .map((row) => `${row.conversationKey || row.value}:${Number(row.contact?.last_message_at || 0)}`)
    .join('|')
  return `${expectedContacts}/${loadedContacts}::${expectedChannels}/${loadedChannels}::${channelKeys}::${directKeys}`
})

const canLoadOlderMessages = computed(() => {
  return Boolean(
    workspaceMode.value === 'chat'
    && currentConversation.value
    && !loadingMessages.value
    && !loadingOlderMessages.value
    && messages.value.length > 0
    && loadedConversationMessages.value < effectiveConversationTotalMessages.value
    && Number(messages.value[0]?.id || 0) > 0,
  )
})

const currentConversationTitle = computed(() => {
  if (selectedConversationKind.value === 'contact') {
    return selectedContact.value ? contactDisplayName(selectedContact.value) : t('messages.empty.noActiveDirect')
  }
  return selectedChannel.value?.name || t('messages.empty.noChannelSelected')
})

const channelEditorResolvedName = computed(() => {
  if (channelEditorForm.value.type === 'hashtag') {
    const hashtag = String(channelEditorForm.value.hashtag || '').trim().replace(/^#+/, '')
    if (!hashtag) {
      return ''
    }
    return hashtag.toLowerCase() === OFFICIAL_PUBLIC_CHANNEL_NAME.slice(1) ? OFFICIAL_PUBLIC_CHANNEL_NAME : `#${hashtag}`
  }
  return normalizeMeshcoreChannelName(channelEditorForm.value.name)
})

const channelEditorCanSave = computed(() => {
  if (!session.connected || channelEditorBusy.value || !channelEditorCanEdit.value) {
    return false
  }
  if (channelEditorForm.value.type === 'hashtag') {
    return Boolean(channelEditorResolvedName.value)
  }
  return Boolean(
    channelEditorResolvedName.value
    && normalizePskHex(channelEditorForm.value.pskHex).length === 32,
  )
})

const workspaceTitle = computed(() => {
  if (workspaceMode.value === 'edit-channel') {
    return t('messages.editor.workspace.editTitle', {
      name: editingChannel.value?.name || channelEditorResolvedName.value || t('messages.editor.fallback.channel'),
    })
  }
  if (workspaceMode.value === 'new-channel') {
    return t('messages.editor.workspace.newTitle')
  }
  return currentConversationTitle.value
})

const workspaceSubtitle = computed(() => {
  if (workspaceMode.value === 'edit-channel' || workspaceMode.value === 'new-channel') {
    return channelEditorForm.value.type === 'hashtag'
      ? t('messages.editor.workspace.hashtagSubtitle')
      : t('messages.editor.workspace.privateSubtitle')
  }
  if (selectedConversationKind.value === 'channel' && selectedChannel.value) {
    return selectedChannel.value.description || t('messages.workspace.channelHistory', { total: activeConversationTotalMessages.value })
  }
  if (selectedConversationKind.value === 'contact' && selectedContact.value) {
    return selectedContact.value.public_key
  }
  return t('messages.workspace.selectChannelSubtitle')
})

const channelEditorViewModel = computed(() => {
  return {
    type: channelEditorForm.value.type,
    channelIdxText: channelEditorForm.value.channelIdx == null
      ? t('messages.editor.fields.autoIndex')
      : String(channelEditorForm.value.channelIdx),
    hashtag: channelEditorForm.value.hashtag,
    name: channelEditorForm.value.name,
    resolvedName: channelEditorResolvedName.value,
    pskHex: channelEditorForm.value.pskHex,
    secretPreview: channelEditorSecretPreview.value || t('common.na'),
    channelHashPreview: channelEditorHashPreview.value || t('common.na'),
    canSave: channelEditorCanSave.value,
    canEdit: channelEditorCanEdit.value,
    canDelete: channelEditorCanDelete.value,
    busy: channelEditorBusy.value,
    deleteBusy: channelEditorDeleteBusy.value,
    hashtagTypeLabel: t('messages.editor.types.hashtag'),
    privateTypeLabel: t('messages.editor.types.private'),
    channelIdxLabel: t('messages.editor.fields.channelIdx'),
    hashtagNameLabel: t('messages.editor.fields.hashtagName'),
    hashtagPlaceholder: t('messages.editor.fields.hashtagPlaceholder'),
    channelNameLabel: t('messages.editor.fields.channelName'),
    channelNamePlaceholder: t('messages.editor.fields.namePlaceholder'),
    resolvedNameLabel: t('messages.editor.fields.resolvedName'),
    pskHexLabel: t('messages.editor.fields.pskHex'),
    pskHexPlaceholder: t('messages.editor.fields.pskPlaceholder'),
    secretPreviewLabel: t('messages.editor.fields.secretPreview'),
    channelHashLabel: t('messages.editor.fields.channelHash'),
    noteText: channelEditorProtectedPublic.value
      ? t('messages.editor.notes.publicDelete')
      : channelEditorForm.value.type === 'hashtag'
        ? t('messages.editor.notes.hashtag')
        : t('messages.editor.notes.private'),
    cancelLabel: t('common.cancel'),
    deleteLabel: channelEditorDeleteBusy.value ? t('messages.editor.actions.deleting') : t('messages.editor.actions.delete'),
    saveLabel: channelEditorBusy.value ? t('messages.editor.actions.saving') : t('common.save'),
  }
})

function buildConversationCacheKey(kind = selectedConversationKind.value, value = null) {
  if (kind === 'contact') {
    const contactKey = normalizePublicKey(value == null ? selectedContactKey.value : value)
    return contactKey ? `contact:${contactKey}` : ''
  }
  const channelValue = value == null ? selectedChannelIdx.value : value
  return channelValue == null ? '' : `channel:${Number(channelValue)}`
}

function readConversationCache(cacheKey) {
  if (!cacheKey) {
    return null
  }
  const entry = dialogHistoryCache.value?.[cacheKey]
  if (!entry || !Array.isArray(entry.messages)) {
    return null
  }
  return {
    total_count: Math.max(0, Number(entry.total_count || entry.messages.length || 0)),
    messages: sanitizeMessageList(entry.messages).slice(-DIALOG_CACHE_MESSAGE_LIMIT),
  }
}

function extractOutgoingDraftTexts(items) {
  const entries = []
  if (!Array.isArray(items)) {
    return entries
  }
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const message = items[index]
    if (!message?.from_self) {
      continue
    }
    const rawText = String(message?.text || '').trim()
    if (!rawText) {
      continue
    }
    entries.push(rawText)
  }
  return entries
}

function mergeUniqueOutgoingDraftTexts(...sources) {
  const result = []
  const seen = new Set()
  for (const source of sources) {
    if (!Array.isArray(source)) {
      continue
    }
    for (const rawValue of source) {
      const text = String(rawValue || '').trim()
      if (!text || seen.has(text)) {
        continue
      }
      seen.add(text)
      result.push(text)
      if (result.length >= DIALOG_SENT_HISTORY_MAX_ITEMS) {
        return result
      }
    }
  }
  return result
}

function readSentDraftHistory(cacheKey) {
  if (!cacheKey) {
    return []
  }
  const entry = sentDraftHistoryCache.value?.[cacheKey]
  if (!entry || !Array.isArray(entry.items)) {
    return []
  }
  return mergeUniqueOutgoingDraftTexts(entry.items)
}

function writeSentDraftHistory(cacheKey, nextItems) {
  if (!cacheKey) {
    return
  }
  const mergedItems = mergeUniqueOutgoingDraftTexts(nextItems)
  const nextCache = {
    ...(sentDraftHistoryCache.value || {}),
    [cacheKey]: {
      updated_at: Date.now(),
      items: mergedItems,
    },
  }
  const entries = Object.entries(nextCache)
    .sort((left, right) => Number(right[1]?.updated_at || 0) - Number(left[1]?.updated_at || 0))
    .slice(0, DIALOG_SENT_HISTORY_ENTRY_LIMIT)
  sentDraftHistoryCache.value = Object.fromEntries(entries)
}

function writeConversationCache(cacheKey, nextMessages, totalCount) {
  if (!cacheKey || !Array.isArray(nextMessages)) {
    return
  }
  const trimmedMessages = sanitizeMessageList(nextMessages).slice(-DIALOG_CACHE_MESSAGE_LIMIT)
  const nextCache = {
    ...(dialogHistoryCache.value || {}),
    [cacheKey]: {
      updated_at: Date.now(),
      total_count: Math.max(trimmedMessages.length, Number(totalCount || trimmedMessages.length || 0)),
      messages: trimmedMessages,
    },
  }
  const entries = Object.entries(nextCache)
    .sort((left, right) => Number(right[1]?.updated_at || 0) - Number(left[1]?.updated_at || 0))
    .slice(0, DIALOG_CACHE_ENTRY_LIMIT)
  dialogHistoryCache.value = Object.fromEntries(entries)
}

function flushConversationCacheWrite() {
  if (conversationCacheWriteTimerId) {
    window.clearTimeout(conversationCacheWriteTimerId)
    conversationCacheWriteTimerId = 0
  }
  if (!pendingConversationCacheWrite) {
    return
  }
  const { cacheKey, messagesSnapshot, totalCount } = pendingConversationCacheWrite
  pendingConversationCacheWrite = null
  writeConversationCache(cacheKey, messagesSnapshot, totalCount)
}

function scheduleConversationCacheWrite(cacheKey, nextMessages, totalCount, delayMs = 120) {
  if (!cacheKey || !Array.isArray(nextMessages)) {
    return
  }
  pendingConversationCacheWrite = {
    cacheKey,
    messagesSnapshot: nextMessages.slice(),
    totalCount,
  }
  if (conversationCacheWriteTimerId) {
    window.clearTimeout(conversationCacheWriteTimerId)
  }
  conversationCacheWriteTimerId = window.setTimeout(() => {
    conversationCacheWriteTimerId = 0
    flushConversationCacheWrite()
  }, Math.max(0, Number(delayMs) || 0))
}


const loadedConversationMessages = computed(() => {
  return Math.max(0, Number(messages.value.length || 0))
})

const effectiveConversationTotalMessages = computed(() => {
  return Math.max(loadedConversationMessages.value, Number(activeConversationTotalMessages.value || 0))
})

const conversationLoadedMeta = computed(() => {
  return t('messages.workspace.loadedOfTotal', {
    loaded: loadedConversationMessages.value,
    total: effectiveConversationTotalMessages.value,
  })
})

const nodePreviewUrl = computed(() => {
  return resolveNodePreviewUrl(session.deviceModel || session.selfName || '')
})

const shellBlurred = computed(() => {
  return !session.connected || notificationsOpen.value || consoleOpen.value || advertOpen.value || confirmDialog.value.open
})

const notificationSoundEnabled = computed(() => session.notificationSoundEnabled)

const batteryPercent = computed(() => {
  return resolveDisplayedBatteryPercent({
    telemetry: session.selfTelemetry || {},
    batteryInfo: session.batteryInfo || {},
    profile: session.currentNodeBatteryProfile,
  })
})

const recentRepeaterCount = computed(() => {
  const nowSeconds = Math.floor(phonebarTick.value / 1000)
  return session.contacts.filter((contact) => {
    if (Number(contact?.adv_type || 0) !== 2) {
      return false
    }
    const pathLen = Number(contact?.out_path_len)
    const isZeroHopPath = pathLen === 0 || pathLen === 255 || pathLen === -1
    if (!isZeroHopPath) {
      return false
    }
    const seenAt = Number(contact?.last_advert || contact?.last_zero_hop_seen || contact?.last_interaction_at || contact?.updated_at || 0)
    return seenAt > 0 && (nowSeconds - seenAt) <= 120
  }).length
})

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

function findChannelNotificationRowByMentionEntry(entry) {
  const channelIdentity = String(entry?.channel_identity || '').trim()
  const rawChannelIdx = Number(entry?.channel_idx ?? -1)
  const ownerId = normalizeOwnerId(entry?.owner_id || '')
  const conversationKey = getChannelMuteKey({
    owner_id: ownerId,
    idx: rawChannelIdx,
    channel_identity: channelIdentity,
  })
  return channelScrollerRows.value.find((row) => {
    if (conversationKey && String(row?.channelKey || '').trim().toLowerCase() === conversationKey.toLowerCase()) {
      return true
    }
    if (!ownerId && channelIdentity && String(row?.channel?.channel_identity || '').trim() === channelIdentity) {
      return true
    }
    return !ownerId && rawChannelIdx >= 0 && Number(row?.channel?.idx ?? -1) === rawChannelIdx
  }) || null
}

function findContactNotificationRowByMentionEntry(entry) {
  const prefix = String(entry?.pubkey_prefix || '').trim().toLowerCase()
  if (!prefix) {
    return null
  }
  const conversationKey = getContactMuteKey({
    owner_id: entry?.owner_id || '',
    pubkey_prefix: prefix,
  })
  return directConversationRows.value.find((row) => {
    if (conversationKey && String(row?.conversationKey || '').trim().toLowerCase() === conversationKey.toLowerCase()) {
      return true
    }
    return String(row?.prefix || '').trim().toLowerCase() === prefix
  }) || null
}

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

const nodeLinkStatus = computed(() => {
  if (!session.connected) {
    return 'disconnected'
  }
  return (phonebarTick.value - Number(session.radioTxObservedAt || 0)) <= 2400 ? 'tx' : 'connected'
})

const phoneBarNodeName = computed(() => {
  const selfName = String(session.selfName || '').trim()
  if (selfName) {
    return selfName
  }
  const saved = session.selectedSavedConnection
  return String(saved?.node_name || 'offline')
})

const totalUnreadCount = computed(() => {
  const channelsTotal = channelScrollerRows.value.reduce((sum, row) => sum + row.unreadCount, 0)
  const contactsTotal = directConversationRows.value.reduce((sum, row) => sum + row.unreadCount, 0)
  return channelsTotal + contactsTotal
})

const totalMentionCount = computed(() => {
  return mentionNotificationEntries.value.length
})

const currentConversationMuteMode = computed(() => getCurrentConversationMuteMode())

const workspaceHeaderModel = computed(() => {
  const muteMode = currentConversationMuteMode.value
  return {
    title: workspaceTitle.value,
    subtitle: workspaceSubtitle.value,
    showCloseButton: workspaceShowsChannelEditor.value,
    closeLabel: t('common.close'),
    chatMenuOpenLabel: t('messages.chatMenu.open'),
    chatMenuTitle: t('messages.chatMenu.title'),
    chatMenuDisabled: !currentConversation.value,
    clearLabel: t('messages.chatMenu.clear'),
    regularMuteActive: muteMode === 'regular',
    regularMuteLabel: t(muteMode === 'regular' ? 'messages.chatMenu.unmuteRegular' : 'messages.chatMenu.muteRegular'),
    allMuteActive: muteMode === 'all',
    allMuteLabel: t(muteMode === 'all' ? 'messages.chatMenu.unmuteAll' : 'messages.chatMenu.muteAll'),
  }
})

const workspaceEmptyModel = computed(() => {
  return {
    title: session.connected ? t('messages.empty.noChannelSelected') : t('messages.empty.connect'),
    subtitle: session.connected ? t('messages.workspace.selectChannelSubtitle') : t('messages.empty.connectToSeeChannels'),
  }
})

function releaseResolvedChatWallpaperUrl() {
  if (typeof releaseChatWallpaperUrl === 'function') {
    releaseChatWallpaperUrl()
    releaseChatWallpaperUrl = null
  }
  resolvedChatWallpaperUrl.value = ''
}

const chatBackgroundId = computed(() => {
  return String(session.settingsPayload?.settings?.chat_background_id || 'chat-backplane-blue').trim() || 'chat-backplane-blue'
})

const chatWorkspacePaneStyle = computed(() => {
  const backgroundId = chatBackgroundId.value
  let backgroundUrl = DEFAULT_CHAT_BACKPLANE_URL
  if (backgroundId.startsWith('wallpaper:')) {
    const wallpaperName = backgroundId.slice('wallpaper:'.length).trim()
    if (wallpaperName) {
      backgroundUrl = resolvedChatWallpaperUrl.value || `/wallpappers/${encodeURIComponent(wallpaperName)}`
    }
  }
  return {
    '--mc-chat-backplane-image': [
      'linear-gradient(180deg, rgba(6, 12, 18, 0.42), rgba(6, 12, 18, 0.66))',
      'radial-gradient(circle at 88% 16%, rgba(116, 189, 255, 0.18), transparent 28%)',
      'radial-gradient(circle at 12% 82%, rgba(72, 187, 159, 0.12), transparent 26%)',
      `url("${backgroundUrl}")`,
    ].join(', '),
    '--mc-chat-backplane-size': 'cover, cover, cover, cover',
    '--mc-chat-backplane-position': 'center, center, center, center',
  }
})

const mentionNotificationEntries = computed(() => {
  const unreadMentionEntries = Array.isArray(unreadSummary.value.mention_entries) ? unreadSummary.value.mention_entries : []
  if (unreadMentionEntries.length) {
    return unreadMentionEntries.map((entry) => {
      const conversationKind = String(entry?.conversation_kind || '').trim().toLowerCase()
      if (conversationKind === 'channel') {
        const row = findChannelNotificationRowByMentionEntry(entry)
        const summaryKey = getChannelMuteKey({
          owner_id: entry?.owner_id || '',
          channel_identity: entry?.channel_identity || '',
          idx: entry?.channel_idx,
        })
        const channelName = String(entry?.channel_name || '').trim()
        const rawChannelIdx = Number(entry?.channel_idx ?? -1)
        const title = row?.title || displayChannelTitle(channelName, rawChannelIdx, String(entry?.channel_identity || '').trim())
        const avatarSymbol = row?.avatarSymbol || channelAvatarSymbol({
          idx: rawChannelIdx,
          name: channelName,
          channel_identity: String(entry?.channel_identity || '').trim(),
        })
        const value = row?.value ?? rawChannelIdx
        return {
          kind: 'channel',
          key: `mention:channel:${Number(entry?.id || 0) || `${String(entry?.channel_identity || '').trim()}:${rawChannelIdx}`}`,
          title,
          preview: buildMentionPreviewText(entry?.text, row?.preview),
          avatarSymbol,
          unreadCount: row?.unreadCount || Number(unreadSummary.value.channel_unread_counts?.[summaryKey] || 0),
          mentionCount: 1,
          highlightTone: 'mention',
          value,
          focusMessageId: Number(entry?.id || 0),
        }
      }
      const row = findContactNotificationRowByMentionEntry(entry)
      const prefix = String(entry?.pubkey_prefix || '').trim().toLowerCase()
      const conversationKey = getContactMuteKey({
        owner_id: entry?.owner_id || '',
        pubkey_prefix: prefix,
      })
      const title = row?.displayName || prefix.toUpperCase() || t('messages.fallback.unnamedContact')
      const avatarSymbol = row?.avatarSymbol || title.slice(0, 2).toUpperCase()
      const value = row?.value || prefix
      return {
        kind: 'contact',
          key: `mention:contact:${Number(entry?.id || 0) || prefix}`,
          title,
          preview: buildMentionPreviewText(entry?.text, row?.preview),
          avatarSymbol,
          unreadCount: row?.unreadCount || Number(unreadSummary.value.contact_unread_counts?.[conversationKey] || unreadSummary.value.contact_unread_counts?.[prefix] || 0),
          mentionCount: 1,
        highlightTone: 'mention',
        value,
        focusMessageId: Number(entry?.id || 0),
      }
    }).filter((entry) => {
      if (entry.kind === 'channel') {
        const channelValue = Number(entry.value)
        return Number.isFinite(channelValue) && channelValue >= 0
      }
      return Boolean(String(entry.value || '').trim())
    })
  }
  const entries = []
  for (const row of channelScrollerRows.value) {
    if (!row.mentionCount) {
      continue
    }
    entries.push({
      kind: 'channel',
      key: `mention:channel:${row.channelKey}`,
      title: row.title,
      preview: row.preview,
      avatarSymbol: row.avatarSymbol,
      unreadCount: row.unreadCount,
      mentionCount: row.mentionCount,
      highlightTone: 'mention',
      value: row.value,
      focusMessageId: Number(unreadSummary.value.channel_first_mention_ids[row.channelKey] || unreadSummary.value.channel_first_unread_ids[row.channelKey] || 0),
    })
  }
  for (const row of directConversationRows.value) {
    if (!row.mentionCount) {
      continue
    }
    entries.push({
      kind: 'contact',
      key: `mention:contact:${row.conversationKey}`,
      title: row.displayName,
      preview: row.preview,
      avatarSymbol: row.avatarSymbol,
      unreadCount: row.unreadCount,
      mentionCount: row.mentionCount,
      highlightTone: 'mention',
      value: row.value,
      focusMessageId: Number(unreadSummary.value.contact_first_mention_ids[row.conversationKey] || unreadSummary.value.contact_first_mention_ids[row.prefix] || unreadSummary.value.contact_first_unread_ids[row.conversationKey] || unreadSummary.value.contact_first_unread_ids[row.prefix] || 0),
    })
  }
  return entries
})

const regularNotificationEntries = computed(() => {
  const entries = []
  for (const row of channelScrollerRows.value) {
    if (!row.unreadCount) {
      continue
    }
    entries.push({
      kind: 'channel',
      key: `regular:channel:${row.channelKey}`,
      title: row.title,
      preview: row.preview,
      avatarSymbol: row.avatarSymbol,
      unreadCount: row.unreadCount,
      mentionCount: row.mentionCount,
      highlightTone: 'unread',
      value: row.value,
      focusMessageId: Number(unreadSummary.value.channel_first_unread_ids[row.channelKey] || unreadSummary.value.channel_first_mention_ids[row.channelKey] || 0),
    })
  }
  for (const row of directConversationRows.value) {
    if (!row.unreadCount) {
      continue
    }
    entries.push({
      kind: 'contact',
      key: `regular:contact:${row.conversationKey}`,
      title: row.displayName,
      preview: row.preview,
      avatarSymbol: row.avatarSymbol,
      unreadCount: row.unreadCount,
      mentionCount: row.mentionCount,
      highlightTone: 'unread',
      value: row.value,
      focusMessageId: Number(unreadSummary.value.contact_first_unread_ids[row.conversationKey] || unreadSummary.value.contact_first_unread_ids[row.prefix] || unreadSummary.value.contact_first_mention_ids[row.conversationKey] || unreadSummary.value.contact_first_mention_ids[row.prefix] || 0),
    })
  }
  return entries
})

const notificationsMetaText = computed(() => {
  if (!totalUnreadCount.value && !mentionNotificationEntries.value.length) {
    return t('notifications.empty.noneUnread')
  }
  const params = {
    chats: regularNotificationEntries.value.length,
    unread: totalUnreadCount.value,
    mentions: mentionNotificationEntries.value.length,
  }
  return params.mentions > 0
    ? t('notifications.meta.summaryWithMentions', params)
    : t('notifications.meta.summaryNoMentions', params)
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

const draftBytesUsed = computed(() => {
  return new TextEncoder().encode(String(draftText.value || '')).length
})

const draftStructured = computed(() => {
  return parseStructuredMessage({
    text: draftText.value,
    from_self: true,
  })
})

const draftGifId = computed(() => parseGifId(draftStructured.value.body))

const outgoingDraftHistory = computed(() => {
  const cacheKey = currentConversationKey.value
  const cachedMessages = readConversationCache(cacheKey)?.messages || []
  return mergeUniqueOutgoingDraftTexts(
    extractOutgoingDraftTexts(messages.value),
    readSentDraftHistory(cacheKey),
    extractOutgoingDraftTexts(cachedMessages),
  )
})

const activeComposerHistoryDraft = computed(() => {
  const index = Number(composerHistoryIndex.value)
  if (index < 0) {
    return ''
  }
  return String(outgoingDraftHistory.value[index] || '')
})

const draftBytesLeft = computed(() => {
  return MAX_MESSAGE_BODY_BYTES - draftBytesUsed.value
})

const draftIsOverflow = computed(() => {
  return draftBytesLeft.value < 0
})

const composerByteCounterText = computed(() => {
  return t('messages.composer.bytesUsed', {
    used: draftBytesUsed.value,
    limit: MAX_MESSAGE_BODY_BYTES,
  })
})

const canSendCurrentDraft = computed(() => {
  if (selectedConversationKind.value === 'channel' && selectedChannel.value?.is_on_node === false) {
    return false
  }
  if (selectedConversationKind.value === 'contact' && selectedContact.value?.sendable === false) {
    return false
  }
  return !sending.value && Boolean(String(draftStructured.value.body || '').trim()) && !draftIsOverflow.value
})

const gifPickerHasResults = computed(() => gifPickerItems.value.length > 0)

const composerModel = computed(() => {
  return {
    conversationLoadedMeta: conversationLoadedMeta.value,
    draftGifId: draftGifId.value,
    draftIsOverflow: draftIsOverflow.value,
    composerByteCounterText: composerByteCounterText.value,
    canSendCurrentDraft: canSendCurrentDraft.value,
    sendLabel: sending.value ? t('messages.actions.sending') : t('messages.actions.send'),
    gifButtonLabel: t('messages.actions.gif'),
    emojiButtonLabel: t('messages.actions.emoji'),
    emojiPickerDisabled: Boolean(draftGifId.value),
    composerPlaceholder: t('messages.composer.placeholder'),
    replyActive: Boolean(replyDraft.value?.target),
    replyOverline: t('messages.composer.replyingTo'),
    replyTarget: String(replyDraft.value?.target || ''),
    replyPreview: String(replyDraft.value?.preview || t('messages.fallback.emptyMessage')),
    clearReplyLabel: t('messages.composer.clearReply'),
    gifMessageLabel: t('messages.gif.messageLabel'),
    removeGifLabel: t('messages.gif.remove'),
    emojiStaticTexts: {
      placeholder: t('messages.emoji.searchPlaceholder'),
      skinTone: t('messages.emoji.skinTone'),
    },
    emojiGroupNames: {
      recent: t('messages.emoji.groups.recent'),
      smileys_people: t('messages.emoji.groups.smileysPeople'),
      animals_nature: t('messages.emoji.groups.animalsNature'),
      food_drink: t('messages.emoji.groups.foodDrink'),
      activities: t('messages.emoji.groups.activities'),
      travel_places: t('messages.emoji.groups.travelPlaces'),
      objects: t('messages.emoji.groups.objects'),
      symbols: t('messages.emoji.groups.symbols'),
      flags: t('messages.emoji.groups.flags'),
    },
  }
})

const contextMenuMessage = computed(() => {
  const messageId = Number(messageContextMenu.value.messageId || 0)
  if (messageId > 0) {
    return messages.value.find((message) => Number(message?.id || 0) === messageId) || null
  }
  return null
})

const contextMenuStructuredMessage = computed(() => {
  return contextMenuMessage.value ? parseStructuredMessage(contextMenuMessage.value) : null
})

const currentDirectRouteContextContact = computed(() => {
  if (selectedConversationKind.value !== 'contact') {
    return null
  }
  return selectedContact.value || null
})

const currentDirectRouteHasStoredRoute = computed(() => {
  return Boolean(currentDirectRouteContextContact.value && buildStoredContactRouteHops(currentDirectRouteContextContact.value).length)
})

const messageContextMenuModel = computed(() => {
  const message = contextMenuMessage.value
  const structuredMessage = contextMenuStructuredMessage.value
  const preview = String(structuredMessage?.body || structuredMessage?.rawText || '').trim()
  const routeHops = message ? extractMessageRouteHops(message) : []
  return {
    open: Boolean(messageContextMenu.value.open && message && structuredMessage),
    x: Number(messageContextMenu.value.x || 0),
    y: Number(messageContextMenu.value.y || 0),
    title: t('messages.contextMenu.title'),
    preview: preview || t('messages.fallback.emptyMessage'),
    canReply: Boolean(message && !message.from_self && replyActionTargetName(message, structuredMessage)),
    canRouteMap: Boolean(message && routeHops.length),
    canToggleContactRoute: Boolean(message && routeHops.length && currentDirectRouteContextContact.value),
    canResend: Boolean(message?.from_self && composeResendMessageText(message)),
    canCopy: Boolean(message && copyableMessageText(message)),
    replyLabel: t('messages.contextMenu.reply'),
    routeMapLabel: t('messages.contextMenu.routeMap'),
    toggleContactRouteLabel: currentDirectRouteHasStoredRoute.value
      ? t('messages.contextMenu.resetContactRoute')
      : t('messages.contextMenu.saveContactRoute'),
    resendLabel: t('messages.contextMenu.resend'),
    copyLabel: t('messages.contextMenu.copy'),
  }
})

const gifPickerSheetModel = computed(() => {
  return {
    open: gifPickerOpen.value,
    searchTerm: gifPickerSearchTerm.value,
    busy: gifPickerBusy.value,
    loadingMore: gifPickerLoadingMore.value,
    errorText: gifPickerError.value,
    hasResults: gifPickerHasResults.value,
    items: gifPickerItems.value,
    gifPreviewUrl,
  }
})

const notificationsSheetModel = computed(() => {
  return {
    open: notificationsOpen.value,
    notificationSoundEnabled: notificationSoundEnabled.value,
    notificationsMetaText: notificationsMetaText.value,
    totalUnreadCount: totalUnreadCount.value,
    totalMentionCount: totalMentionCount.value,
    bellIconUrl,
    mentionsCollapsed: notificationsMentionsCollapsed.value,
    regularCollapsed: notificationsRegularCollapsed.value,
    mentionEntries: mentionNotificationEntries.value,
    regularEntries: regularNotificationEntries.value,
  }
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

const confirmSheetModel = computed(() => {
  return {
    open: confirmDialog.value.open,
    title: confirmDialog.value.title,
    message: confirmDialog.value.message,
    confirmLabel: confirmDialog.value.confirmLabel,
  }
})

function normalizePskHex(value) {
  return String(value || '').replaceAll(/[^0-9a-f]/gi, '').toLowerCase()
}

function utf8Bytes(value) {
  const text = String(value || '')
  if (typeof TextEncoder !== 'undefined') {
    return new TextEncoder().encode(text)
  }
  const encoded = unescape(encodeURIComponent(text))
  return Uint8Array.from(encoded, (char) => char.charCodeAt(0))
}

function bytesToHex(bytes) {
  return Array.from(bytes || [], (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function sha256FallbackDigestBytes(inputBytes) {
  const bytes = inputBytes instanceof Uint8Array ? inputBytes : Uint8Array.from(inputBytes || [])
  const bitLength = bytes.length * 8
  const totalLength = Math.ceil((bytes.length + 1 + 8) / 64) * 64
  const padded = new Uint8Array(totalLength)
  const view = new DataView(padded.buffer)
  const words = new Uint32Array(64)
  const hash = new Uint32Array([
    0x6a09e667,
    0xbb67ae85,
    0x3c6ef372,
    0xa54ff53a,
    0x510e527f,
    0x9b05688c,
    0x1f83d9ab,
    0x5be0cd19,
  ])
  const constants = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
    0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
    0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
    0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
    0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ])
  const rightRotate = (value, shift) => (value >>> shift) | (value << (32 - shift))

  padded.set(bytes)
  padded[bytes.length] = 0x80
  view.setUint32(totalLength - 8, Math.floor(bitLength / 0x100000000), false)
  view.setUint32(totalLength - 4, bitLength >>> 0, false)

  for (let offset = 0; offset < totalLength; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(offset + (index * 4), false)
    }
    for (let index = 16; index < 64; index += 1) {
      const s0 = rightRotate(words[index - 15], 7) ^ rightRotate(words[index - 15], 18) ^ (words[index - 15] >>> 3)
      const s1 = rightRotate(words[index - 2], 17) ^ rightRotate(words[index - 2], 19) ^ (words[index - 2] >>> 10)
      words[index] = (words[index - 16] + s0 + words[index - 7] + s1) >>> 0
    }

    let a = hash[0]
    let b = hash[1]
    let c = hash[2]
    let d = hash[3]
    let e = hash[4]
    let f = hash[5]
    let g = hash[6]
    let h = hash[7]

    for (let index = 0; index < 64; index += 1) {
      const s1 = rightRotate(e, 6) ^ rightRotate(e, 11) ^ rightRotate(e, 25)
      const ch = (e & f) ^ (~e & g)
      const temp1 = (h + s1 + ch + constants[index] + words[index]) >>> 0
      const s0 = rightRotate(a, 2) ^ rightRotate(a, 13) ^ rightRotate(a, 22)
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const temp2 = (s0 + maj) >>> 0

      h = g
      g = f
      f = e
      e = (d + temp1) >>> 0
      d = c
      c = b
      b = a
      a = (temp1 + temp2) >>> 0
    }

    hash[0] = (hash[0] + a) >>> 0
    hash[1] = (hash[1] + b) >>> 0
    hash[2] = (hash[2] + c) >>> 0
    hash[3] = (hash[3] + d) >>> 0
    hash[4] = (hash[4] + e) >>> 0
    hash[5] = (hash[5] + f) >>> 0
    hash[6] = (hash[6] + g) >>> 0
    hash[7] = (hash[7] + h) >>> 0
  }

  const digest = new Uint8Array(32)
  const digestView = new DataView(digest.buffer)
  for (let index = 0; index < hash.length; index += 1) {
    digestView.setUint32(index * 4, hash[index], false)
  }
  return digest
}

function sha256DigestBytesSync(input) {
  const bytes = input instanceof Uint8Array ? input : utf8Bytes(input)
  return sha256FallbackDigestBytes(bytes)
}

function sha256HexSync(text) {
  return bytesToHex(sha256DigestBytesSync(text))
}

function computeChannelHashHexSync(secretHex) {
  const normalized = normalizePskHex(secretHex)
  if (!normalized || normalized.length !== 32) {
    return ''
  }
  const bytes = Uint8Array.from(
    normalized.match(/.{2}/g)?.map((chunk) => Number.parseInt(chunk, 16)) || [],
  )
  return bytesToHex(sha256DigestBytesSync(bytes)).slice(0, 2)
}

function syncChannelEditorPreview() {
  if (channelEditorForm.value.type === 'hashtag') {
    const resolvedName = channelEditorResolvedName.value
    if (!resolvedName) {
      channelEditorSecretPreview.value = ''
      channelEditorHashPreview.value = ''
      return
    }
    const secretHex = isOfficialPublicChannelName(resolvedName)
      ? OFFICIAL_PUBLIC_CHANNEL_PSK_HEX
      : sha256HexSync(resolvedName).slice(0, 32)
    channelEditorSecretPreview.value = secretHex
    channelEditorHashPreview.value = computeChannelHashHexSync(secretHex)
    return
  }
  const secretHex = normalizePskHex(channelEditorForm.value.pskHex)
  channelEditorSecretPreview.value = secretHex
  channelEditorHashPreview.value = computeChannelHashHexSync(secretHex)
}

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

function fallbackMessageAuthor(message) {
  if (message?.from_self) {
    return String(session.selfName || t('messages.fallback.you'))
  }
  const sender = String(message?.sender_name || message?.author_name || message?.pubkey_prefix || '').trim()
  if (sender) {
    return sender
  }
  return selectedConversationKind.value === 'contact'
    ? contactDisplayName(selectedContact.value)
    : (selectedChannel.value?.name || t('messages.fallback.unknown'))
}

function parseReplyPrefix(source) {
  const raw = String(source || '').trim()
  if (!raw.startsWith('@[')) {
    return {
      replyTarget: '',
      remainder: raw,
    }
  }
  const closingIndex = raw.indexOf(']')
  if (closingIndex <= 2) {
    return {
      replyTarget: '',
      remainder: raw,
    }
  }
  return {
    replyTarget: raw.slice(2, closingIndex).trim(),
    remainder: raw.slice(closingIndex + 1).trim(),
  }
}

function parseStructuredMessage(message) {
  const fallbackAuthor = fallbackMessageAuthor(message)
  const rawText = String(message?.text || '').trim()
  if (!rawText) {
    return {
      author: fallbackAuthor,
      replyTarget: '',
      body: '',
      rawText: '',
    }
  }
  let author = fallbackAuthor
  let bodySource = rawText
  if (!message?.from_self && selectedConversationKind.value !== 'contact') {
    const colonIndex = rawText.indexOf(':')
    const hasStructuredPrefix = colonIndex > 0 && colonIndex <= 96 && !rawText.slice(0, colonIndex).includes('\n')
    if (hasStructuredPrefix) {
      author = rawText.slice(0, colonIndex).trim() || fallbackAuthor
      bodySource = rawText.slice(colonIndex + 1).trim()
    }
  }
  const parsedReply = parseReplyPrefix(bodySource)
  return {
    author,
    replyTarget: parsedReply.replyTarget,
    body: parsedReply.remainder,
    rawText,
  }
}

function composeReplyPrefix(targetName) {
  const cleanTarget = String(targetName || '').trim()
  return cleanTarget ? `@[${cleanTarget}] ` : ''
}

function prependReplyPrefix(source, targetName) {
  const prefix = composeReplyPrefix(targetName)
  const current = String(source || '')
  if (!prefix) {
    return current
  }
  return current.startsWith(prefix) ? current : `${prefix}${current}`
}

function stripReplyPrefix(source, targetName) {
  const prefix = composeReplyPrefix(targetName)
  const current = String(source || '')
  if (!prefix || !current.startsWith(prefix)) {
    return current
  }
  return current.slice(prefix.length)
}

function findContactByDisplayName(displayName) {
  const normalized = String(displayName || '').trim().toLowerCase()
  if (!normalized) {
    return null
  }
  return session.contacts.find((contact) => contactDisplayName(contact).trim().toLowerCase() === normalized) || null
}

function findContactByPublicKeyOrPrefix(value) {
  const normalized = normalizePublicKey(value)
  if (!normalized) {
    return null
  }
  const contact = session.contacts.find((contact) => {
    const publicKey = normalizePublicKey(contact?.public_key)
    const prefix = getContactPrefix(contact)
    return publicKey === normalized || prefix === normalized || publicKey.startsWith(normalized)
  }) || null
  if (contact) {
    return contact
  }
  const selfContact = buildSelfContact()
  if (selfContact) {
    const selfPublicKey = normalizePublicKey(selfContact.public_key)
    const selfPrefix = getContactPrefix(selfContact)
    if (selfPublicKey === normalized || selfPrefix === normalized || selfPublicKey.startsWith(normalized)) {
      return selfContact
    }
  }
  return null
}

function resolveMessageAuthorContact(message, structuredMessage = parseStructuredMessage(message)) {
  if (selectedConversationKind.value === 'contact') {
    if (message?.from_self) {
      return buildSelfContact()
    }
    return selectedContact.value
      || findContactByPublicKeyOrPrefix(message?.public_key || message?.pubkey_prefix || '')
      || findContactByDisplayName(structuredMessage?.author)
      || null
  }
  return findContactByPublicKeyOrPrefix(message?.public_key || message?.pubkey_prefix || '')
    || findContactByDisplayName(structuredMessage?.author)
    || null
}

function buildMessageRouteParticipants(message, structuredMessage) {
  const participants = []
  const seen = new Set()
  const remember = (contact, role, fallback = null) => {
    const fallbackPrefix = getContactPrefix(fallback)
    const fallbackName = String(fallback?.name || '').trim()
    if (!contact && !fallbackPrefix && !fallbackName) {
      return
    }
    const publicKey = normalizePublicKey(contact?.public_key)
    const prefix = getContactPrefix(contact) || fallbackPrefix
    const dedupeKey = publicKey || prefix || fallbackName.toLowerCase()
    if (!dedupeKey || seen.has(dedupeKey)) {
      return
    }
    seen.add(dedupeKey)
    participants.push({
      role,
      public_key: publicKey,
      pubkey_prefix: prefix,
      name: String(contact ? contactDisplayName(contact) : fallbackName).trim() || t('messages.fallback.unnamedContact'),
      lat: Number.isFinite(Number(contact?.lat)) ? Number(contact.lat) : null,
      lon: Number.isFinite(Number(contact?.lon)) ? Number(contact.lon) : null,
    })
  }
  if (selectedConversationKind.value === 'contact') {
    remember(selectedContact.value, message?.from_self ? 'target' : 'source')
    return participants
  }
  remember(resolveMessageAuthorContact(message, structuredMessage), 'source', {
    pubkey_prefix: message?.pubkey_prefix || message?.public_key || '',
    name: structuredMessage?.author || fallbackMessageAuthor(message),
  })
  return participants
}

function replyActionTargetName(message, structuredMessage) {
  if (message?.from_self) {
    return ''
  }
  if (selectedConversationKind.value === 'contact') {
    return selectedContact.value ? contactDisplayName(selectedContact.value) : ''
  }
  return String(structuredMessage?.author || '').trim()
}

function composeResendMessageText(message) {
  const structuredMessage = parseStructuredMessage(message)
  const body = String(structuredMessage.body || '').trim()
  const prefix = composeReplyPrefix(structuredMessage.replyTarget)
  return `${prefix}${body}`.trim() || String(structuredMessage.rawText || '').trim()
}

function copyableMessageText(message) {
  const structuredMessage = parseStructuredMessage(message)
  return String(structuredMessage.body || structuredMessage.rawText || '').trim()
}

function messageTextHasLinks(text) {
  return /\b((?:https?:\/\/|www\.)[^\s<]+)/i.test(String(text || ''))
}

function messageTextHtmlFromSource(source) {
  const normalizedSource = String(source || '')
  const pattern = /\b((?:https?:\/\/|www\.)[^\s<]+)/gi
  let cursor = 0
  let html = ''
  let match
  while ((match = pattern.exec(normalizedSource)) !== null) {
    const fullMatch = String(match[0] || '')
    let urlText = fullMatch
    let trailing = ''
    while (/[),.!?;:]$/.test(urlText)) {
      trailing = urlText.slice(-1) + trailing
      urlText = urlText.slice(0, -1)
    }
    const start = Number(match.index || 0)
    html += escapeHtml(normalizedSource.slice(cursor, start))
    const href = urlText.startsWith('www.') ? `https://${urlText}` : urlText
    html += `<a class="mc-message-link" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(urlText)}</a>`
    html += escapeHtml(trailing)
    cursor = start + fullMatch.length
  }
  html += escapeHtml(normalizedSource.slice(cursor))
  return html
}

function extractMessageRouteHops(message) {
  return String(message?.path_hashes || '')
    .trim()
    .toUpperCase()
    .split(/\s*->\s*/)
    .map((hop) => hop.trim())
    .filter(Boolean)
}

function normalizeRouteHopToken(token) {
  const normalized = String(token || '').trim().toUpperCase()
  if (!normalized || !/^[0-9A-F]+$/.test(normalized)) {
    return ''
  }
  return normalized
}

function preferredRouteHopDisplayLength() {
  return 4
}

function buildStoredContactRouteHops(contact) {
  const pathLen = Number(contact?.out_path_len ?? 0)
  const hashLen = Math.max(1, Number(contact?.out_path_hash_len || 1))
  const rawPath = String(contact?.out_path || '').trim().toUpperCase()
  if (!rawPath || pathLen <= 0) {
    return []
  }
  const chunkSize = hashLen * 2
  const hops = []
  for (let index = 0; index < pathLen; index += 1) {
    const chunk = rawPath.slice(index * chunkSize, (index + 1) * chunkSize)
    if (chunk.length !== chunkSize) {
      break
    }
    hops.push(chunk)
  }
  return hops
}

const repeaterRoutePublicKeys = computed(() => {
  return session.contacts
    .filter((contact) => contactKindLabel(contact) === 'repeater')
    .map((contact) => String(contact?.public_key || '').trim().toUpperCase())
    .filter(Boolean)
})

const knownRouteHopCandidates = computed(() => {
  const candidates = new Set()
  const remember = (token) => {
    const normalized = normalizeRouteHopToken(token)
    if (normalized) {
      candidates.add(normalized)
    }
  }
  remember(session.selfPublicKey)
  for (const contact of session.contacts) {
    remember(contact?.public_key)
    for (const hop of buildStoredContactRouteHops(contact)) {
      remember(hop)
    }
  }
  for (const message of messages.value) {
    for (const hop of extractMessageRouteHops(message)) {
      remember(hop)
    }
  }
  return Array.from(candidates)
})

function matchRepeaterPublicKeysByRouteHop(hop) {
  const normalizedHop = normalizeRouteHopToken(hop)
  if (!normalizedHop) {
    return []
  }
  return session.contacts
    .filter((contact) => contactKindLabel(contact) === 'repeater')
    .map((contact) => String(contact?.public_key || '').trim().toUpperCase())
    .filter((publicKey) => publicKey.startsWith(normalizedHop))
}

function resolvePreferredRouteHopToken(hop, preferredHexLen = preferredRouteHopDisplayLength()) {
  const normalized = normalizeRouteHopToken(hop)
  if (!normalized) {
    return ''
  }
  if (normalized.length >= preferredHexLen) {
    return normalized.slice(0, preferredHexLen)
  }
  const candidatePrefixes = new Set()
  for (const candidate of knownRouteHopCandidates.value) {
    if (candidate.length < preferredHexLen || !candidate.startsWith(normalized)) {
      continue
    }
    candidatePrefixes.add(candidate.slice(0, preferredHexLen))
  }
  if (candidatePrefixes.size >= 1) {
    return Array.from(candidatePrefixes).sort((left, right) => left.localeCompare(right))[0]
  }
  return normalized
}

function expandRouteHopForDisplay(hop) {
  const normalized = normalizeRouteHopToken(hop)
  if (!normalized) {
    return ''
  }
  const preferredLen = preferredRouteHopDisplayLength(normalized)
  const preferredToken = resolvePreferredRouteHopToken(normalized, preferredLen)
  if (preferredToken.length >= preferredLen) {
    return preferredToken
  }
  const matches = matchRepeaterPublicKeysByRouteHop(normalized)
  if (matches.length === 1) {
    return matches[0].slice(0, preferredLen) || preferredToken
  }
  if (matches.length > 1) {
    const keys = matches.filter(Boolean)
    let prefix = normalized
    while (prefix.length < preferredLen) {
      const nextChars = new Set(
        keys
          .map((key) => key[prefix.length] || '')
          .filter(Boolean),
      )
      if (nextChars.size !== 1) {
        break
      }
      prefix += Array.from(nextChars)[0]
    }
    return prefix.slice(0, preferredLen) || preferredToken
  }
  return preferredToken
}

function messageRenderKey(message) {
  const messageId = Number(message?.id || 0)
  if (messageId > 0) {
    return `message:${messageId}`
  }
  return `message:${message?.sender_timestamp || 0}:${message?.from_self ? 'self' : 'peer'}:${message?.text || ''}`
}

function isMessageAnimated(message) {
  return animatedMessageKeys.value.includes(messageRenderKey(message))
}

function buildRenderedMessage(message, isLastVisible = false) {
  const structuredMessage = parseStructuredMessage(message)
  const authorContact = resolveMessageAuthorContact(message, structuredMessage)
  const replyTargetContact = findContactByDisplayName(structuredMessage.replyTarget)
  const key = messageRenderKey(message)
  const gifId = parseGifId(structuredMessage.body)
  const routeMeta = messageRouteMeta(message)
  const messageId = Number(message?.id || 0)
  const isAnimated = animatedMessageKeys.value.includes(key)
  const showReadMarker = messageId > 0 && messageId === Number(readMarkerMessageId.value || 0)
  const timestampText = formatTimestamp(message?.sender_timestamp || message?.created_at || 0)
  const text = structuredMessage.body || t('messages.fallback.emptyMessage')
  const textHasLinks = !gifId && messageTextHasLinks(text)
  const textHtml = textHasLinks ? messageTextHtmlFromSource(text) : ''
  const signalMeta = messageSignalMeta(message)
  const hopsMeta = messageHops(message)
  const deliveryText = message?.from_self ? deliveryGlyph(message) : ''
  const highlightTone = messageId > 0 && messageId === Number(notificationHighlightState.value.messageId || 0)
    ? String(notificationHighlightState.value.tone || '').trim().toLowerCase()
    : ''
  const author = authorContact ? contactDisplayName(authorContact) : structuredMessage.author
  const replyTarget = replyTargetContact ? contactDisplayName(replyTargetContact) : structuredMessage.replyTarget
  return {
    key,
    source: message,
    messageId,
    authorContact,
    replyTargetContact,
    showReadMarker,
    isAnimated,
    author,
    authorResolved: Boolean(authorContact),
    replyTarget,
    replyTargetResolved: Boolean(replyTargetContact),
    timestampText,
    gifId,
    text,
    textHasLinks,
    textHtml,
    signalMeta,
    hopsMeta,
    routeMeta,
    deliveryText,
    highlightTone,
    bottomGap: isLastVisible ? 0 : MESSAGE_VIRTUAL_GAP,
    memo: [
      key,
      messageId,
      Boolean(message?.from_self),
      showReadMarker,
      isAnimated,
      author,
      normalizePublicKey(authorContact?.public_key),
      Boolean(authorContact),
      replyTarget,
      normalizePublicKey(replyTargetContact?.public_key),
      Boolean(replyTargetContact),
      timestampText,
      gifId,
      text,
      textHasLinks,
      textHtml,
      signalMeta,
      hopsMeta,
      routeMeta || '',
      deliveryText,
      highlightTone,
      isLastVisible,
    ],
  }
}

function setComposerTextarea(element) {
  composerTextarea.value = element
}

function resetComposerHistoryNavigation() {
  composerHistoryIndex.value = -1
  composerHistoryDraftSnapshot.value = ''
}

function focusComposerTextareaAtEnd() {
  nextTick(() => {
    const input = composerTextarea.value
    input?.focus?.()
    if (input instanceof HTMLTextAreaElement) {
      const cursor = input.value.length
      input.setSelectionRange(cursor, cursor)
    }
  })
}

function openContactFromMessage(contact) {
  const publicKey = normalizePublicKey(contact?.public_key)
  if (!publicKey) {
    return
  }
  router.push({
    path: '/contacts',
    query: {
      contact: publicKey,
    },
  })
}

function applyComposerHistoryDraft(nextDraft, nextIndex) {
  composerHistoryApplying.value = true
  draftText.value = String(nextDraft || '')
  composerHistoryIndex.value = Number(nextIndex)
  focusComposerTextareaAtEnd()
  nextTick(() => {
    composerHistoryApplying.value = false
  })
}

function isTextareaCaretCollapsed(textarea) {
  return Number(textarea.selectionStart) === Number(textarea.selectionEnd)
}

function isTextareaCaretOnLogicalTopLine(textarea) {
  const caret = Math.max(0, Number(textarea.selectionStart || 0))
  return !String(textarea.value || '').slice(0, caret).includes('\n')
}

function isTextareaCaretOnLogicalBottomLine(textarea) {
  const caret = Math.max(0, Number(textarea.selectionEnd || 0))
  return !String(textarea.value || '').slice(caret).includes('\n')
}

function stepComposerHistory(direction) {
  const history = outgoingDraftHistory.value
  if (!history.length) {
    return
  }
  if (direction < 0) {
    if (composerHistoryIndex.value < 0) {
      composerHistoryDraftSnapshot.value = String(draftText.value || '')
      applyComposerHistoryDraft(history[0], 0)
      return
    }
    const nextIndex = Math.min(history.length - 1, composerHistoryIndex.value + 1)
    if (nextIndex !== composerHistoryIndex.value) {
      applyComposerHistoryDraft(history[nextIndex], nextIndex)
    }
    return
  }
  if (composerHistoryIndex.value < 0) {
    return
  }
  const nextIndex = composerHistoryIndex.value - 1
  if (nextIndex >= 0) {
    applyComposerHistoryDraft(history[nextIndex], nextIndex)
    return
  }
  const restoreDraft = String(composerHistoryDraftSnapshot.value || '')
  composerHistoryApplying.value = true
  draftText.value = restoreDraft
  resetComposerHistoryNavigation()
  focusComposerTextareaAtEnd()
  nextTick(() => {
    composerHistoryApplying.value = false
  })
}

function handleComposerTextareaKeydown(event) {
  const textarea = event.target
  if (!(textarea instanceof HTMLTextAreaElement) || event.defaultPrevented) {
    return
  }
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
    return
  }
  if (event.key === 'ArrowUp') {
    if (!isTextareaCaretCollapsed(textarea)) {
      return
    }
    const historyActive = composerHistoryIndex.value >= 0
    if (!historyActive) {
      if (String(draftText.value || '') || !outgoingDraftHistory.value.length) {
        return
      }
      event.preventDefault()
      stepComposerHistory(-1)
      return
    }
    if (!isTextareaCaretOnLogicalTopLine(textarea)) {
      return
    }
    event.preventDefault()
    stepComposerHistory(-1)
    return
  }
  if (event.key === 'ArrowDown') {
    if (composerHistoryIndex.value < 0 || !isTextareaCaretCollapsed(textarea) || !isTextareaCaretOnLogicalBottomLine(textarea)) {
      return
    }
    event.preventDefault()
    stepComposerHistory(1)
  }
}

const {
  messageScroller,
  visibleMessageIds,
  virtualMessageWindow,
  visibleRenderedMessages,
  showScrollToBottomButton,
  isMessageScrollerNearBottom,
  updateScrollToBottomButtonVisibility,
  resetVirtualMessageLayout,
  updateMessageScrollerMetrics,
  setMessageScroller,
  ensureMessageVisibilityObserver,
  ensureMessageResizeObserver,
  disconnectMessageResizeObserver,
  disconnectMessageVisibilityObserver,
  bindMessageCardElement,
  cancelScheduledMessageScrollWork,
  scheduleVisibleReadTracking,
  scrollMessageIntoView,
  suspendProgrammaticReadTracking,
  scrollMessagesToBottom,
  handleMessageScroll: handleMessageScrollBase,
  scrollToNewestMessage: scrollToNewestMessageBase,
} = useMessagesVirtualChat({
  messages,
  workspaceMode,
  currentConversation,
  buildRenderedMessage,
  messageRenderKey,
  estimatedMessageHeight: MESSAGE_VIRTUAL_ESTIMATED_HEIGHT,
  overscanPx: MESSAGE_VIRTUAL_OVERSCAN_PX,
  messageGap: MESSAGE_VIRTUAL_GAP,
  onVisibleReadTracking: () => {
    markVisibleMessagesRead()
  },
})

const {
  readMarkerMessageId,
  shouldMarkIncomingMessageMentionRead,
  markVisibleMessagesRead,
} = useMessagesReadTracking({
  session,
  messages,
  currentConversationKey,
  selectedConversationKind,
  selectedContactKey,
  selectedChannelIdx,
  selectedChannelIdentity,
  activeConversationTotalMessages,
  visibleMessageIds,
  messageScroller,
  isMessageScrollerNearBottom,
  scheduleConversationCacheWrite,
  queueUnreadRefresh,
  getOwnerPort,
})

function animateMessageAppearance(message) {
  const key = messageRenderKey(message)
  animatedMessageKeys.value = [...animatedMessageKeys.value.filter((item) => item !== key), key]
  window.setTimeout(() => {
    animatedMessageKeys.value = animatedMessageKeys.value.filter((item) => item !== key)
  }, 420)
}

function queueUnreadRefresh(delayMs = 120) {
  if (unreadRefreshTimer.value) {
    return
  }
  unreadRefreshTimer.value = window.setTimeout(() => {
    unreadRefreshTimer.value = null
    void loadUnreadCounts()
  }, Math.max(0, Number(delayMs) || 0))
}

function getConversationReadMarkerTarget() {
  if (selectedConversationKind.value === 'contact') {
    for (const key of getContactMuteKeys(selectedContact.value || selectedContactKey.value)) {
      const parsed = parseScopedConversationKey(key)
      const legacyPrefix = parsed.baseKey.startsWith('contact:') ? parsed.baseKey.slice('contact:'.length) : ''
      const targetId = Number(
        unreadSummary.value.contact_first_unread_ids[key]
          || unreadSummary.value.contact_first_mention_ids[key]
          || unreadSummary.value.contact_first_unread_ids[legacyPrefix]
          || unreadSummary.value.contact_first_mention_ids[legacyPrefix]
          || 0,
      )
      if (targetId > 0) {
        return targetId
      }
    }
    return null
  }
  for (const channelKey of getChannelMuteKeys(selectedChannel.value || {
    idx: selectedChannelIdx.value,
    channel_identity: selectedChannelIdentity.value,
  })) {
    const parsed = parseScopedConversationKey(channelKey)
    const legacyChannelKey = parsed.baseKey.startsWith('channelid:')
      ? parsed.baseKey.slice('channelid:'.length)
      : (parsed.baseKey.startsWith('channel:') ? parsed.baseKey.slice('channel:'.length) : '')
    const targetId = Number(
      unreadSummary.value.channel_first_unread_ids[channelKey]
        || unreadSummary.value.channel_first_mention_ids[channelKey]
        || unreadSummary.value.channel_first_unread_ids[legacyChannelKey]
        || unreadSummary.value.channel_first_mention_ids[legacyChannelKey]
        || 0,
    )
    if (targetId > 0) {
      return targetId
    }
  }
  return null
}

function mergeUniqueMessages(prependMessages, existingMessages) {
  const seen = new Set()
  const merged = []
  for (const message of [...sanitizeMessageList(prependMessages), ...sanitizeMessageList(existingMessages)]) {
    const key = messageRenderKey(message)
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    merged.push(message)
  }
  return merged
}

function messageSignalMeta(message) {
  if (message?.snr == null || message?.snr === '') {
    return t('messages.metrics.snrNa')
  }
  return t('messages.metrics.snrValue', { value: message.snr })
}

function messageHops(message) {
  const pathLen = Number(message?.path_len ?? -1)
  if (pathLen < 0) {
    return t('messages.metrics.flood')
  }
  return t('messages.metrics.hops', { value: pathLen })
}

function messageRouteMeta(message) {
  const hops = extractMessageRouteHops(message)
  if (!hops.length) {
    return ''
  }
  return hops
    .map((hop) => expandRouteHopForDisplay(hop))
    .filter(Boolean)
    .join(' -> ')
}

function deliveryGlyph(message) {
  const status = String(message?.send_status || '')
  if (status === 'delivered') return '✓✓'
  if (status === 'sent') return '✓'
  return '…'
}

function ackHexesMatch(expectedAckHex, receivedAckHex) {
  const expected = String(expectedAckHex || '').trim().toLowerCase()
  const received = String(receivedAckHex || '').trim().toLowerCase()
  if (!expected || !received) {
    return false
  }
  if (expected.length % 2 !== 0 || received.length % 2 !== 0) {
    return false
  }
  const overlapBytes = Math.min(expected.length, received.length) / 2
  if (overlapBytes < 4) {
    return expected.length === received.length && expected === received
  }
  return expected.slice(0, overlapBytes * 2) === received.slice(0, overlapBytes * 2)
}

function applyChannelsSnapshot(nextChannels) {
  const sanitizedChannels = Array.isArray(nextChannels)
    ? nextChannels.filter((channel) => isRenderableRecord(channel))
    : []
  session.applySessionSnapshot({
    ...session.sessionSnapshot,
    active: session.connected,
    device: session.device,
    self: session.self,
    channels: sanitizedChannels,
    contacts: session.contacts,
    radio_stats: session.radioStats,
    self_telemetry: session.selfTelemetry,
    battery_info: session.batteryInfo,
    collections_ready: session.collectionsReady,
    contacts_count: session.sessionSnapshot?.contacts_count,
    channels_count: sanitizedChannels.length,
  })
}

function applyContactsSnapshot(nextContacts) {
  const sanitizedContacts = Array.isArray(nextContacts)
    ? nextContacts.filter((contact) => isRenderableRecord(contact))
    : []
  session.patchSessionSnapshotFields({
    active: session.connected,
    contacts: sanitizedContacts,
    contacts_count: sanitizedContacts.length,
  })
}

function syncConversationDirectoryPreviewIntoSession(directory = {}) {
  const directoryChannels = Array.isArray(directory?.channels) ? directory.channels : []
  const directoryContacts = Array.isArray(directory?.contacts) ? directory.contacts : []

  const liveChannels = Array.isArray(session.channels) ? session.channels : []
  if (liveChannels.length && directoryChannels.length) {
    const previewByKey = new Map(
      directoryChannels
        .map((channel) => [channelListMergeKey(channel), channel])
        .filter(([key]) => Boolean(key)),
    )
    let channelsChanged = false
    const nextChannels = liveChannels.map((channel) => {
      const preview = previewByKey.get(channelListMergeKey(channel))
      if (!preview) {
        return channel
      }
      const nextChannel = {
        ...channel,
        description: String(preview?.description || channel?.description || ''),
        last_message_preview: String(preview?.last_message_preview || channel?.last_message_preview || ''),
        last_message_from_self: Boolean(
          preview?.last_message_from_self ?? channel?.last_message_from_self ?? false,
        ),
        last_message_ts: Number(preview?.last_message_ts || channel?.last_message_ts || 0),
        unread_count: Number(preview?.unread_count || channel?.unread_count || 0),
        mention_count: Number(preview?.mention_count || channel?.mention_count || 0),
      }
      if (
        nextChannel.description !== channel?.description
        || nextChannel.last_message_preview !== channel?.last_message_preview
        || nextChannel.last_message_from_self !== Boolean(channel?.last_message_from_self)
        || nextChannel.last_message_ts !== Number(channel?.last_message_ts || 0)
        || nextChannel.unread_count !== Number(channel?.unread_count || 0)
        || nextChannel.mention_count !== Number(channel?.mention_count || 0)
      ) {
        channelsChanged = true
      }
      return nextChannel
    })
    if (channelsChanged) {
      applyChannelsSnapshot(nextChannels)
    }
  }

  const liveContacts = Array.isArray(session.contacts) ? session.contacts : []
  if (liveContacts.length && directoryContacts.length) {
    const previewByPrefix = new Map(
      directoryContacts
        .map((contact) => [getContactPrefix(contact?.pubkey_prefix || contact?.public_key || ''), contact])
        .filter(([prefix]) => Boolean(prefix)),
    )
    let contactsChanged = false
    const nextContacts = liveContacts.map((contact) => {
      const preview = previewByPrefix.get(getContactPrefix(contact?.pubkey_prefix || contact?.public_key || ''))
      if (!preview) {
        return contact
      }
      const nextContact = {
        ...contact,
        last_message_text: String(preview?.last_message_text || contact?.last_message_text || ''),
        last_message_at: Number(preview?.last_message_at || contact?.last_message_at || 0),
        last_message_from_self: Boolean(
          preview?.last_message_from_self ?? contact?.last_message_from_self ?? false,
        ),
        unread_count: Number(preview?.unread_count || contact?.unread_count || 0),
        mention_count: Number(preview?.mention_count || contact?.mention_count || 0),
      }
      if (
        nextContact.last_message_text !== contact?.last_message_text
        || nextContact.last_message_at !== Number(contact?.last_message_at || 0)
        || nextContact.last_message_from_self !== Boolean(contact?.last_message_from_self)
        || nextContact.unread_count !== Number(contact?.unread_count || 0)
        || nextContact.mention_count !== Number(contact?.mention_count || 0)
      ) {
        contactsChanged = true
      }
      return nextContact
    })
    if (contactsChanged) {
      applyContactsSnapshot(nextContacts)
    }
  }
}

function hasHydratedConversationEntries() {
  if (!session.collectionsReady) {
    return false
  }
  const contactCount = Math.max(0, Number(session.sessionSnapshot?.contacts_count ?? session.contacts.length) || 0)
  const channelCount = Math.max(0, Number(session.sessionSnapshot?.channels_count ?? session.channels.length) || 0)
  const loadedContacts = Math.max(0, Number(session.contacts.length || 0))
  const loadedChannels = Math.max(0, Number(session.channels.length || 0))
  if (loadedContacts < contactCount || loadedChannels < channelCount) {
    return false
  }
  return (Date.now() - lastHydrationChangeAt.value) >= HYDRATION_DIALOG_SETTLE_MS
}

function hasUsableConversationWorkspace() {
  if (!session.connected || loadingConversationDirectory.value) {
    return false
  }
  if (conversationListItems.value.length > 0 || currentConversation.value) {
    return true
  }
  if (!session.collectionsReady) {
    return false
  }
  const expectedContacts = Math.max(0, Number(session.sessionSnapshot?.contacts_count ?? conversationContactsSource.value.length) || 0)
  const expectedChannels = Math.max(0, Number(session.sessionSnapshot?.channels_count ?? conversationChannelsSource.value.length) || 0)
  return expectedContacts === 0 && expectedChannels === 0
}

function cancelHydrationCompletionCheck() {
  if (hydrationCompletionTimerId) {
    window.clearTimeout(hydrationCompletionTimerId)
    hydrationCompletionTimerId = 0
  }
}

function markHydrationListChanged() {
  lastHydrationChangeAt.value = Date.now()
}

function finishMessagesHydration() {
  cancelHydrationCompletionCheck()
  session.setMessagesHydrating(false)
}

function scheduleHydrationCompletionCheck() {
  cancelHydrationCompletionCheck()
  if (!session.messagesHydrating || !session.connected) {
    return
  }
  const remainingMs = Math.max(250, HYDRATION_DIALOG_SETTLE_MS - Math.max(0, Date.now() - lastHydrationChangeAt.value))
  hydrationCompletionTimerId = window.setTimeout(() => {
    hydrationCompletionTimerId = 0
    void maybeFinishMessagesHydration({ forceSync: true, loadHistoryIfNeeded: !messages.value.length })
  }, remainingMs)
}

async function maybeFinishMessagesHydration({ forceSync = false, loadHistoryIfNeeded = false } = {}) {
  if (!session.messagesHydrating) {
    return false
  }
  if (!session.connected) {
    finishMessagesHydration()
    return false
  }
  if (hasUsableConversationWorkspace()) {
    finishMessagesHydration()
    return true
  }
  if (forceSync) {
    try {
      const snapshot = await session.syncSessionState({ light: false })
      if (!snapshot?.active) {
        finishMessagesHydration()
        return false
      }
    } catch {
      scheduleHydrationCompletionCheck()
      return false
    }
  }
  await ensureConversationSelectionReady({ loadHistoryIfNeeded })
  if (hasHydratedConversationEntries()) {
    finishMessagesHydration()
    return true
  }
  scheduleHydrationCompletionCheck()
  return false
}

function clearConversationSelection() {
  workspaceMode.value = 'chat'
  selectedConversationKind.value = 'channel'
  selectedChannelIdx.value = null
  selectedChannelIdentity.value = ''
  selectedContactKey.value = ''
  messages.value = []
  activeConversationTotalMessages.value = 0
  replyDraft.value = null
  closeMessageContextMenu()
}

function ensureConversationSelectionReady() {
  const previousConversationKey = currentConversationKey.value
  const nextConversationKey = currentConversationKey.value
  if (selectedConversationKind.value === 'channel' && selectedChannelIdx.value != null && !selectedChannel.value) {
    clearConversationSelection()
    return
  }
  if (selectedConversationKind.value === 'contact' && selectedContactKey.value && !selectedContact.value) {
    clearConversationSelection()
    return
  }
  if (previousConversationKey && !nextConversationKey) {
    clearConversationSelection()
  }
}

async function waitForInitialCollectionsReady({ timeoutMs = 15000, pollIntervalMs = 750 } = {}) {
  const startedAt = Date.now()
  while ((Date.now() - startedAt) < timeoutMs) {
    if (!session.connected) {
      return false
    }
    await ensureConversationSelectionReady()
    if (hasHydratedConversationEntries()) {
      return true
    }
    try {
      const snapshot = await session.syncSessionState({ light: false })
      if (!snapshot?.active) {
        return false
      }
    } catch {
      // Keep the loading overlay alive and let SSE or the next poll advance hydration.
    }
    if (hasHydratedConversationEntries()) {
      return true
    }
    await new Promise((resolve) => window.setTimeout(resolve, pollIntervalMs))
  }
  return hasHydratedConversationEntries()
}

function populateChannelEditor(channel = null) {
  const name = normalizeMeshcoreChannelName(channel?.name)
  const hashtag = isHashtagChannelName(name) ? name.replace(/^#+/, '') : ''
  channelEditorForm.value = {
    channelIdx: channel == null ? null : Number(channel?.idx ?? null),
    channelIdentity: String(channel?.channel_identity || '').trim(),
    type: isHashtagChannelName(name) ? 'hashtag' : 'private',
    name: isHashtagChannelName(name) ? '' : name,
    hashtag,
    pskHex: isHashtagChannelName(name) ? '' : String(channel?.secret_hex || ''),
  }
  void syncChannelEditorPreview()
}

function openChannelEditor(channel) {
  if (!channel) {
    return
  }
  workspaceMode.value = 'edit-channel'
  populateChannelEditor(channel)
}

function startNewChannelEditor() {
  workspaceMode.value = 'new-channel'
  populateChannelEditor(null)
}

function setChannelEditorType(type) {
  if (String(type) === 'private') {
    channelEditorForm.value = {
      ...channelEditorForm.value,
      type: 'private',
      hashtag: '',
    }
    return
  }
  channelEditorForm.value = {
    ...channelEditorForm.value,
    type: 'hashtag',
    pskHex: '',
  }
}

function updateChannelEditorHashtag(value) {
  channelEditorForm.value = {
    ...channelEditorForm.value,
    hashtag: String(value || ''),
  }
}

function updateChannelEditorName(value) {
  channelEditorForm.value = {
    ...channelEditorForm.value,
    name: String(value || ''),
  }
}

function updateChannelEditorPskHex(value) {
  channelEditorForm.value = {
    ...channelEditorForm.value,
    pskHex: String(value || ''),
  }
}

function closeChannelEditor() {
  workspaceMode.value = 'chat'
  channelEditorBusy.value = false
  channelEditorDeleteBusy.value = false
}

function toggleChatEditMode() {
  chatEditMode.value = !chatEditMode.value
  if (!chatEditMode.value && workspaceShowsChannelEditor.value) {
    closeChannelEditor()
  }
}

function reorderChannelDialog({ sourceKey, targetKey, position = 'after' } = {}) {
  const source = String(sourceKey || '').trim()
  const target = String(targetKey || '').trim()
  if (!source || !target || source === target) {
    return
  }
  const currentKeys = channelScrollerRows.value
    .map((row) => String(row.reorderKey || '').trim())
    .filter(Boolean)
  const mergedKeys = [
    ...currentKeys,
    ...(Array.isArray(channelDialogOrder.value) ? channelDialogOrder.value.map((key) => String(key || '').trim()).filter(Boolean) : []),
  ]
  const uniqueKeys = [...new Set(mergedKeys)]
  const sourceIndex = uniqueKeys.indexOf(source)
  const targetIndex = uniqueKeys.indexOf(target)
  if (sourceIndex < 0 || targetIndex < 0) {
    return
  }
  uniqueKeys.splice(sourceIndex, 1)
  const targetIndexAfterRemoval = uniqueKeys.indexOf(target)
  const insertIndex = String(position) === 'before' ? targetIndexAfterRemoval : targetIndexAfterRemoval + 1
  uniqueKeys.splice(Math.max(0, insertIndex), 0, source)
  channelDialogOrder.value = uniqueKeys
  updateConversationListMetrics()
  session.setStatus(t('messages.editor.status.orderSaved'))
}

async function saveChannelEditor() {
  if (!channelEditorCanSave.value) {
    return
  }
  const isCreate = channelEditorForm.value.channelIdx == null
  const resolvedName = channelEditorResolvedName.value
  const normalizedPsk = normalizePskHex(channelEditorForm.value.pskHex)
  if (!resolvedName) {
    session.setStatus(t('messages.editor.status.nameRequired'), true)
    return
  }
  if (channelEditorForm.value.type === 'private' && normalizedPsk.length !== 32) {
    session.setStatus(t('messages.editor.status.pskInvalid'), true)
    return
  }
  channelEditorBusy.value = true
  try {
    const data = await session.api('/api/channels/save', {
      method: 'POST',
      body: JSON.stringify({
        ...session.activeConfigBody(),
        channel_idx: channelEditorForm.value.channelIdx,
        channel_name: resolvedName,
        channel_secret_hex: channelEditorForm.value.type === 'private' ? normalizedPsk : null,
      }),
    })
    const nextChannels = Array.isArray(data?.channels) ? data.channels : session.channels
    applyChannelsSnapshot(nextChannels)
    const savedChannel = nextChannels.find((channel) => Number(channel?.idx ?? -1) === Number(data?.channel?.idx ?? -1)) || data?.channel || null
    if (savedChannel) {
      selectedConversationKind.value = 'channel'
      selectedChannelIdx.value = Number(savedChannel.idx)
      selectedChannelIdentity.value = String(savedChannel.channel_identity || '').trim()
      selectedContactKey.value = ''
      populateChannelEditor(savedChannel)
      workspaceMode.value = 'edit-channel'
    }
    await loadUnreadCounts()
    await loadConversationDirectory()
    session.setStatus(t(
      isCreate ? 'messages.editor.status.channelCreated' : 'messages.editor.status.channelSaved',
      { name: data?.channel?.name || resolvedName },
    ))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('messages.editor.status.saveFailed')), true)
  } finally {
    channelEditorBusy.value = false
  }
}

function requestDeleteChannelEditor() {
  if (!channelEditorCanDelete.value || !editingChannel.value) {
    return
  }
  const targetName = String(editingChannel.value?.name || channelEditorResolvedName.value || OFFICIAL_PUBLIC_CHANNEL_NAME).trim()
  confirmDialog.value = {
    open: true,
    title: t('messages.editor.confirm.deleteTitle'),
    message: t('messages.editor.confirm.deleteMessage', { name: targetName }),
    confirmLabel: t('messages.editor.actions.delete'),
    action: async () => {
      if (!editingChannel.value) {
        return
      }
      const channelIdx = Number(editingChannel.value?.idx ?? channelEditorForm.value.channelIdx ?? -1)
      if (channelIdx < 0) {
        return
      }
      const deletedName = String(editingChannel.value?.name || targetName).trim() || OFFICIAL_PUBLIC_CHANNEL_NAME
      channelEditorDeleteBusy.value = true
      try {
        const data = await session.api('/api/channels/delete', {
          method: 'POST',
          body: JSON.stringify({
            ...session.activeConfigBody(),
            channel_idx: channelIdx,
          }),
        })
        const nextChannels = Array.isArray(data?.channels) ? data.channels : []
        applyChannelsSnapshot(nextChannels)
        if (selectedConversationKind.value === 'channel' && Number(selectedChannelIdx.value ?? -1) === channelIdx) {
          const nextSelectedChannel = nextChannels[0] || null
          selectedChannelIdx.value = nextSelectedChannel ? Number(nextSelectedChannel.idx) : null
          selectedChannelIdentity.value = String(nextSelectedChannel?.channel_identity || '').trim()
          selectedContactKey.value = ''
          messages.value = []
          activeConversationTotalMessages.value = 0
        }
        closeChannelEditor()
        await loadUnreadCounts()
        await loadConversationDirectory()
        if (selectedConversationKind.value === 'channel' && selectedChannelIdx.value != null) {
          await loadConversationHistory()
        }
        session.setStatus(t('messages.editor.status.channelDeleted', { name: deletedName }))
      } catch (error) {
        session.setStatus(
          error instanceof Error
            ? error.message
            : String(error || t('messages.editor.status.deleteFailed', { name: deletedName })),
          true,
        )
      } finally {
        channelEditorDeleteBusy.value = false
      }
    },
  }
}

function closeAllFloats() {
  notificationsOpen.value = false
  consoleOpen.value = false
  advertOpen.value = false
  closeMessageRouteSheet()
  closeMessageContextMenu()
  confirmDialog.value = {
    open: false,
    title: '',
    message: '',
    confirmLabel: t('common.confirm'),
    action: null,
  }
}

async function loadUnreadCounts() {
  if (!getOwnerPort()) {
    session.clearUnreadSummary()
    return
  }
  if (unreadRefreshTimer.value) {
    window.clearTimeout(unreadRefreshTimer.value)
    unreadRefreshTimer.value = null
  }
  const requestSeq = unreadRequestSeq.value + 1
  unreadRequestSeq.value = requestSeq
  const data = await session.loadUnreadSummary({
    port: getOwnerPort(),
    mentionName: String(session.selfName || ''),
  })
  if (requestSeq < unreadAppliedSeq.value) {
    return
  }
  unreadAppliedSeq.value = requestSeq
}

async function loadConversationDirectory() {
  if (!getOwnerPort()) {
    messageConversationDirectory.value = {
      channels: [],
      contacts: [],
    }
    return
  }
  loadingConversationDirectory.value = true
  try {
    const params = new URLSearchParams({
      port: getOwnerPort(),
      mention_name: String(session.selfName || ''),
    })
    const data = await session.api(`/api/messages/conversations?${params.toString()}`)
    messageConversationDirectory.value = {
      channels: Array.isArray(data?.channels) ? data.channels : [],
      contacts: Array.isArray(data?.contacts) ? data.contacts : [],
    }
    syncConversationDirectoryPreviewIntoSession(messageConversationDirectory.value)
    return messageConversationDirectory.value
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('messages.status.openFailed')), true)
    return messageConversationDirectory.value
  } finally {
    loadingConversationDirectory.value = false
  }
}

async function loadConversationHistory(options = {}) {
  const requestSeq = historyLoadSeq.value + 1
  historyLoadSeq.value = requestSeq
  const targetConversationKey = currentConversationKey.value
  const effectiveFocusMessageId = Number(options.focusMessageId || getConversationReadMarkerTarget() || 0) || null
  const notificationHighlightTone = String(options.notificationHighlightTone || '').trim().toLowerCase()
  const shouldUseCache = !effectiveFocusMessageId && !options.skipCache
  if (shouldUseCache) {
    const cached = readConversationCache(targetConversationKey)
    if (cached) {
      messages.value = sanitizeMessageList(cached.messages)
      activeConversationTotalMessages.value = Number(cached.total_count || messages.value.length)
      await nextTick()
      if (requestSeq === historyLoadSeq.value && currentConversationKey.value === targetConversationKey && messageScroller.value) {
        suspendProgrammaticReadTracking()
        scrollMessagesToBottom('auto')
        updateMessageScrollerMetrics()
        window.requestAnimationFrame(() => {
          updateScrollToBottomButtonVisibility()
          scheduleVisibleReadTracking(40)
        })
      }
    }
  }
  loadingMessages.value = true
  try {
    if (selectedConversationKind.value === 'channel' && (selectedChannelIdx.value != null || selectedChannelIdentity.value)) {
      const params = new URLSearchParams({
        channel_idx: String(selectedChannelIdx.value ?? 0),
        limit: String(effectiveFocusMessageId ? HISTORY_PAGE_SIZE : INITIAL_HISTORY_LIMIT),
      })
      if (selectedChannelIdentity.value) {
        params.set('channel_identity', String(selectedChannelIdentity.value))
      }
      if (getOwnerPort()) {
        params.set('port', getOwnerPort())
      }
      if (effectiveFocusMessageId) {
        params.set('anchor_message_id', String(effectiveFocusMessageId))
      }
      const data = await session.api(`/api/messages/channel?${params.toString()}`)
      if (requestSeq !== historyLoadSeq.value || currentConversationKey.value !== targetConversationKey) {
        return
      }
      writeSentDraftHistory(targetConversationKey, Array.isArray(data?.sent_history) ? data.sent_history : [])
      messages.value = sanitizeMessageList(data?.messages)
      activeConversationTotalMessages.value = Number(data?.total_count || messages.value.length)
      scheduleConversationCacheWrite(targetConversationKey, messages.value, activeConversationTotalMessages.value)
    } else if (selectedConversationKind.value === 'contact' && selectedContactKey.value) {
      const params = new URLSearchParams({
        public_key: String(selectedContactKey.value),
        limit: String(effectiveFocusMessageId ? HISTORY_PAGE_SIZE : INITIAL_HISTORY_LIMIT),
      })
      if (getOwnerPort()) {
        params.set('port', getOwnerPort())
      }
      if (effectiveFocusMessageId) {
        params.set('anchor_message_id', String(effectiveFocusMessageId))
      }
      const data = await session.api(`/api/messages/contact?${params.toString()}`)
      if (requestSeq !== historyLoadSeq.value || currentConversationKey.value !== targetConversationKey) {
        return
      }
      writeSentDraftHistory(targetConversationKey, Array.isArray(data?.sent_history) ? data.sent_history : [])
      messages.value = sanitizeMessageList(data?.messages)
      activeConversationTotalMessages.value = Number(data?.total_count || messages.value.length)
      scheduleConversationCacheWrite(targetConversationKey, messages.value, activeConversationTotalMessages.value)
    } else {
      messages.value = []
      activeConversationTotalMessages.value = 0
    }
    await nextTick()
    if (effectiveFocusMessageId) {
      suspendProgrammaticReadTracking()
      scrollMessageIntoView(effectiveFocusMessageId, 'center')
      applyNotificationMessageHighlight(effectiveFocusMessageId, notificationHighlightTone)
    } else if (messageScroller.value) {
      suspendProgrammaticReadTracking()
      scrollMessagesToBottom('auto')
      updateMessageScrollerMetrics()
    }
    window.requestAnimationFrame(() => {
      updateScrollToBottomButtonVisibility()
      scheduleVisibleReadTracking(40)
    })
  } finally {
    if (requestSeq === historyLoadSeq.value) {
      loadingMessages.value = false
    }
  }
}

function clearNotificationMessageHighlight() {
  if (notificationHighlightTimerId) {
    window.clearTimeout(notificationHighlightTimerId)
    notificationHighlightTimerId = 0
  }
  notificationHighlightState.value = {
    messageId: 0,
    tone: '',
  }
}

function applyNotificationMessageHighlight(messageId, tone = '') {
  const resolvedMessageId = Number(messageId || 0)
  const resolvedTone = String(tone || '').trim().toLowerCase()
  if (resolvedMessageId <= 0 || (resolvedTone !== 'mention' && resolvedTone !== 'unread' && resolvedTone !== 'direct')) {
    clearNotificationMessageHighlight()
    return
  }
  if (notificationHighlightTimerId) {
    window.clearTimeout(notificationHighlightTimerId)
    notificationHighlightTimerId = 0
  }
  notificationHighlightState.value = {
    messageId: resolvedMessageId,
    tone: resolvedTone,
  }
  notificationHighlightTimerId = window.setTimeout(() => {
    notificationHighlightTimerId = 0
    if (Number(notificationHighlightState.value.messageId || 0) === resolvedMessageId) {
      notificationHighlightState.value = {
        messageId: 0,
        tone: '',
      }
    }
  }, 2600)
}

async function loadOlderMessages() {
  if (!canLoadOlderMessages.value) {
    return
  }
  topHistoryPaginationArmed.value = false
  suppressTopPaginationUntil.value = Date.now() + 1200
  const oldestMessageId = Number(messages.value[0]?.id || 0)
  if (oldestMessageId <= 0) {
    return
  }
  const targetConversationKey = currentConversationKey.value
  const requestSeq = historyLoadSeq.value
  const host = messageScroller.value
  const previousScrollHeight = host?.scrollHeight || 0
  const previousScrollTop = host?.scrollTop || 0
  loadingOlderMessages.value = true
  try {
    if (selectedConversationKind.value === 'channel' && (selectedChannelIdx.value != null || selectedChannelIdentity.value)) {
      const params = new URLSearchParams({
        channel_idx: String(selectedChannelIdx.value ?? 0),
        limit: String(HISTORY_PAGE_SIZE),
        before_message_id: String(oldestMessageId),
      })
      if (selectedChannelIdentity.value) {
        params.set('channel_identity', String(selectedChannelIdentity.value))
      }
      if (getOwnerPort()) {
        params.set('port', getOwnerPort())
      }
      const data = await session.api(`/api/messages/channel?${params.toString()}`)
      if (requestSeq !== historyLoadSeq.value || currentConversationKey.value !== targetConversationKey) {
        return
      }
      const olderMessages = sanitizeMessageList(data?.messages)
      if (olderMessages.length) {
        messages.value = mergeUniqueMessages(olderMessages, messages.value)
        activeConversationTotalMessages.value = Math.max(messages.value.length, Number(data?.total_count || activeConversationTotalMessages.value))
        scheduleConversationCacheWrite(targetConversationKey, messages.value, activeConversationTotalMessages.value)
      }
    } else if (selectedConversationKind.value === 'contact' && selectedContactKey.value) {
      const params = new URLSearchParams({
        public_key: String(selectedContactKey.value),
        limit: String(HISTORY_PAGE_SIZE),
        before_message_id: String(oldestMessageId),
      })
      if (getOwnerPort()) {
        params.set('port', getOwnerPort())
      }
      const data = await session.api(`/api/messages/contact?${params.toString()}`)
      if (requestSeq !== historyLoadSeq.value || currentConversationKey.value !== targetConversationKey) {
        return
      }
      const olderMessages = sanitizeMessageList(data?.messages)
      if (olderMessages.length) {
        messages.value = mergeUniqueMessages(olderMessages, messages.value)
        activeConversationTotalMessages.value = Math.max(messages.value.length, Number(data?.total_count || activeConversationTotalMessages.value))
        scheduleConversationCacheWrite(targetConversationKey, messages.value, activeConversationTotalMessages.value)
      }
    }
    await nextTick()
    if (host && requestSeq === historyLoadSeq.value && currentConversationKey.value === targetConversationKey) {
      const nextScrollHeight = host.scrollHeight
      host.scrollTop = previousScrollTop + Math.max(0, nextScrollHeight - previousScrollHeight)
      updateMessageScrollerMetrics()
      window.setTimeout(() => {
        if (currentConversationKey.value === targetConversationKey) {
          updateMessageScrollerMetrics()
        }
      }, 180)
    }
  } finally {
    loadingOlderMessages.value = false
  }
}

async function selectChannel(channelOrIdx, options = {}) {
  const channel = channelOrIdx && typeof channelOrIdx === 'object' ? channelOrIdx : null
  const resolvedIdx = channel ? Number(channel?.idx ?? -1) : Number(channelOrIdx)
  markVisibleMessagesRead()
  workspaceMode.value = 'chat'
  selectedConversationKind.value = 'channel'
  selectedChannelIdx.value = Number.isFinite(resolvedIdx) ? resolvedIdx : null
  selectedChannelIdentity.value = String(channel?.channel_identity || '').trim()
  selectedContactKey.value = ''
  closeAllFloats()
  closeMessageContextMenu()
  await loadConversationHistory(options)
}

async function selectContact(contactOrKey, options = {}) {
  const publicKey = contactOrKey && typeof contactOrKey === 'object'
    ? String(contactOrKey.public_key || contactOrKey.pubkey_prefix || '')
    : contactOrKey
  markVisibleMessagesRead()
  workspaceMode.value = 'chat'
  selectedConversationKind.value = 'contact'
  selectedContactKey.value = normalizePublicKey(publicKey)
  selectedChannelIdx.value = null
  selectedChannelIdentity.value = ''
  closeAllFloats()
  closeMessageContextMenu()
  await loadConversationHistory(options)
}

function closeMessageContextMenu() {
  messageContextMenu.value = {
    open: false,
    messageId: 0,
    x: 0,
    y: 0,
    routeParticipant: null,
  }
}

function closeMessageRouteSheet() {
  messageRouteSheet.value = {
    open: false,
    hops: [],
    preview: '',
    conversationKind: 'channel',
    messageId: 0,
    participants: [],
  }
}

function openMessageContextMenu(payload) {
  const event = payload?.event
  const renderedMessage = payload?.renderedMessage
  const message = renderedMessage?.source
  const messageId = Number(renderedMessage?.messageId || message?.id || 0)
  if (!(event instanceof MouseEvent) || !message || messageId <= 0) {
    return
  }
  const structuredMessage = parseStructuredMessage(message)
  const canReply = Boolean(!message.from_self && replyActionTargetName(message, structuredMessage))
  const canRouteMap = Boolean(extractMessageRouteHops(message).length)
  const canResend = Boolean(message.from_self && composeResendMessageText(message))
  const canCopy = Boolean(copyableMessageText(message))
  if (!canReply && !canRouteMap && !canResend && !canCopy) {
    return
  }
  const menuWidth = 240
  const menuHeight = 180
  const margin = 12
  const x = Math.max(margin, Math.min(event.clientX, window.innerWidth - menuWidth - margin))
  const y = Math.max(margin, Math.min(event.clientY, window.innerHeight - menuHeight - margin))
  messageContextMenu.value = {
    open: true,
    messageId,
    x,
    y,
    routeParticipant: {
      role: 'source',
      public_key: normalizePublicKey(renderedMessage?.authorContact?.public_key),
      pubkey_prefix: getContactPrefix(renderedMessage?.authorContact || message?.pubkey_prefix || message?.public_key || ''),
      name: renderedMessage?.author || structuredMessage?.author || fallbackMessageAuthor(message),
      lat: Number.isFinite(Number(renderedMessage?.authorContact?.lat)) ? Number(renderedMessage.authorContact.lat) : null,
      lon: Number.isFinite(Number(renderedMessage?.authorContact?.lon)) ? Number(renderedMessage.authorContact.lon) : null,
    },
  }
}

async function openRouteMapFromContextMenu() {
  const message = contextMenuMessage.value
  const contextRouteParticipant = messageContextMenu.value.routeParticipant
  if (!message) {
    return
  }
  const hops = extractMessageRouteHops(message)
  closeMessageContextMenu()
  if (!hops.length) {
    session.setStatus(t('messages.contextMenu.routeMapMissing'), true)
    return
  }
  const structuredMessage = parseStructuredMessage(message)
  const preview = String(structuredMessage?.body || structuredMessage?.rawText || '').trim().slice(0, 160)
  messageRouteSheet.value = {
    open: true,
    hops,
    preview,
    conversationKind: String(selectedConversationKind.value || ''),
    messageId: Number(message?.id || 0) || 0,
    participants: [
      ...(((contextRouteParticipant?.public_key || contextRouteParticipant?.pubkey_prefix || contextRouteParticipant?.name) && selectedConversationKind.value !== 'contact')
        ? [contextRouteParticipant]
        : []),
      ...buildMessageRouteParticipants(message, structuredMessage),
    ],
  }
}

async function toggleDirectRouteFromContextMenu() {
  const message = contextMenuMessage.value
  const contact = currentDirectRouteContextContact.value
  closeMessageContextMenu()
  if (!contact) {
    session.setStatus(t('messages.contextMenu.routeContactMissing'), true)
    return
  }
  if (currentDirectRouteHasStoredRoute.value) {
    const data = await session.api('/api/contacts/reset-path', {
      method: 'POST',
      body: JSON.stringify({
        ...session.activeConfigBody(),
        public_key: contact.public_key,
      }),
    })
    if (Array.isArray(data?.contacts)) {
      session.patchSessionSnapshotFields({
        active: session.connected,
        contacts: data.contacts,
        contacts_count: data.contacts.length,
        contact_summary: data?.contact_summary ?? session.sessionSnapshot?.contact_summary ?? null,
      })
    }
    session.setStatus(
      data?.materialized_on_node
        ? t('messages.status.contactRouteResetMaterialized')
        : t('messages.status.contactRouteReset'),
    )
    return
  }
  const payload = buildContactRoutePayloadFromMessage(message, buildKnownRoutePublicKeys({
    selfPublicKey: session.self?.public_key,
    contacts: session.contacts,
  }))
  if (!payload) {
    session.setStatus(t('messages.contextMenu.routeSaveUnavailable'), true)
    return
  }
  const data = await session.api('/api/contacts/set-path', {
    method: 'POST',
    body: JSON.stringify({
      ...session.activeConfigBody(),
      public_key: contact.public_key,
      ...payload,
    }),
  })
  if (Array.isArray(data?.contacts)) {
    session.patchSessionSnapshotFields({
      active: session.connected,
      contacts: data.contacts,
      contacts_count: data.contacts.length,
      contact_summary: data?.contact_summary ?? session.sessionSnapshot?.contact_summary ?? null,
    })
  }
  session.setStatus(
    data?.materialized_on_node
      ? t('messages.status.contactRouteSavedMaterialized')
      : t('messages.status.contactRouteSaved'),
  )
}

function activateReplyFromMessage(message = contextMenuMessage.value) {
  if (!message) {
    return
  }
  const structuredMessage = parseStructuredMessage(message)
  const targetName = replyActionTargetName(message, structuredMessage)
  if (!targetName) {
    return
  }
  const previousTarget = String(replyDraft.value?.target || '').trim()
  replyDraft.value = {
    messageId: Number(message?.id || 0),
    target: targetName,
    preview: String(structuredMessage.body || t('messages.fallback.emptyMessage')).trim(),
  }
  const normalizedDraft = previousTarget ? stripReplyPrefix(draftText.value, previousTarget) : String(draftText.value || '')
  draftText.value = prependReplyPrefix(normalizedDraft, targetName)
  closeMessageContextMenu()
  nextTick(() => {
    composerTextarea.value?.focus?.()
    const input = composerTextarea.value
    if (input instanceof HTMLTextAreaElement) {
      const cursor = input.value.length
      input.setSelectionRange(cursor, cursor)
    }
  })
}

function clearReplyDraft() {
  const target = String(replyDraft.value?.target || '').trim()
  if (target) {
    draftText.value = stripReplyPrefix(draftText.value, target)
  }
  replyDraft.value = null
}

async function writeTextToClipboard(text) {
  if (navigator?.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'readonly')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  textarea.style.pointerEvents = 'none'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  textarea.remove()
}

async function copyMessageFromContextMenu() {
  const message = contextMenuMessage.value
  const text = copyableMessageText(message)
  closeMessageContextMenu()
  if (!text) {
    session.setStatus(t('messages.status.copyFailed'), true)
    return
  }
  try {
    await writeTextToClipboard(text)
    session.setStatus(t('messages.status.copied'))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : t('messages.status.copyFailed'), true)
  }
}

async function sendMessageText(text, options = {}) {
  if (sending.value) {
    return false
  }
  const normalizedText = String(text || '').trim()
  if (!normalizedText) {
    return false
  }
  const payloadBytes = new TextEncoder().encode(normalizedText).length
  if (payloadBytes > MAX_MESSAGE_BODY_BYTES) {
    session.setStatus(t('messages.composer.limitExceeded', { limit: MAX_MESSAGE_BODY_BYTES }), true)
    return false
  }
  sending.value = true
  try {
    const shouldStickToBottom = isMessageScrollerNearBottom()
    if (selectedConversationKind.value === 'channel' && selectedChannelIdx.value != null) {
      if (selectedChannel.value?.is_on_node === false) {
        session.setStatus(t('messages.status.channelNotOnNode'), true)
        return false
      }
      session.setStatus(t('messages.status.sendingPacket', { type: packetTypeLabel('channel', { t }) }))
      const data = await session.api('/api/messages/channel/send', {
        method: 'POST',
        body: JSON.stringify({
          ...session.activeConfigBody(),
          channel_idx: Number(selectedChannelIdx.value),
          text: normalizedText,
        }),
      })
      if (data?.message) {
        session.noteRadioTransmission()
        updateChannelPreview(data.message)
        writeSentDraftHistory(
          currentConversationKey.value,
          mergeUniqueOutgoingDraftTexts([normalizedText], readSentDraftHistory(currentConversationKey.value)),
        )
        messages.value = sanitizeMessageList([...messages.value, { ...data.message, is_read: true, is_mention_read: shouldMarkIncomingMessageMentionRead(data.message) }])
        activeConversationTotalMessages.value = Math.max(activeConversationTotalMessages.value + 1, messages.value.length)
        scheduleConversationCacheWrite(currentConversationKey.value, messages.value, activeConversationTotalMessages.value)
        if (shouldStickToBottom) {
          animateMessageAppearance(data.message)
        }
      }
    } else if (selectedConversationKind.value === 'contact' && selectedContactKey.value) {
      if (selectedContact.value?.sendable === false) {
        session.setStatus(t('messages.status.contactKeyUnavailable'), true)
        return false
      }
      session.setStatus(t('messages.status.sendingPacket', { type: packetTypeLabel('direct', { t }) }))
      const data = await session.api('/api/messages/contact/send', {
        method: 'POST',
        body: JSON.stringify({
          ...session.activeConfigBody(),
          public_key: String(selectedContactKey.value),
          text: normalizedText,
        }),
      })
      if (data?.message) {
        session.noteRadioTransmission()
        updateContactPreview(data.message)
        writeSentDraftHistory(
          currentConversationKey.value,
          mergeUniqueOutgoingDraftTexts([normalizedText], readSentDraftHistory(currentConversationKey.value)),
        )
        messages.value = sanitizeMessageList([...messages.value, { ...data.message, is_read: true, is_mention_read: shouldMarkIncomingMessageMentionRead(data.message) }])
        activeConversationTotalMessages.value = Math.max(activeConversationTotalMessages.value + 1, messages.value.length)
        scheduleConversationCacheWrite(currentConversationKey.value, messages.value, activeConversationTotalMessages.value)
        if (shouldStickToBottom) {
          animateMessageAppearance(data.message)
        }
      }
    }
    await loadConversationDirectory()
    if (options.clearDraft !== false) {
      draftText.value = ''
    }
    if (options.clearReply !== false) {
      replyDraft.value = null
    }
    await nextTick()
    if (shouldStickToBottom) {
      scrollMessagesToBottom('smooth')
    }
    updateScrollToBottomButtonVisibility()
    applyConnectedStatusFromSnapshot()
    return true
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('messages.status.sendFailed')), true)
    return false
  } finally {
    sending.value = false
  }
}

async function resendMessageFromContextMenu() {
  const message = contextMenuMessage.value
  const text = composeResendMessageText(message)
  closeMessageContextMenu()
  if (!text) {
    session.setStatus(t('messages.status.sendFailed'), true)
    return
  }
  await sendMessageText(text, {
    clearDraft: false,
    clearReply: false,
  })
}

async function sendMessage() {
  await sendMessageText(draftText.value, {
    clearDraft: true,
    clearReply: true,
  })
}

async function loadTrendingGifs({ append = false } = {}) {
  if (append) {
    if (gifPickerBusy.value || gifPickerLoadingMore.value || !gifPickerHasMore.value) {
      return
    }
    gifPickerLoadingMore.value = true
  } else {
    gifPickerBusy.value = true
    gifPickerError.value = ''
    gifPickerOffset.value = 0
    gifPickerHasMore.value = true
  }
  const requestOffset = append ? gifPickerOffset.value : 0
  try {
    const response = await fetch(
      `https://api.giphy.com/v1/gifs/trending?api_key=${encodeURIComponent(GIPHY_API_KEY)}&limit=${GIPHY_PICKER_LIMIT}&offset=${requestOffset}&rating=g`,
    )
    if (!response.ok) {
      throw new Error('trending')
    }
    const data = await response.json()
    const nextItems = Array.isArray(data?.data) ? data.data : []
    gifPickerItems.value = append ? [...gifPickerItems.value, ...nextItems] : nextItems
    gifPickerOffset.value = gifPickerItems.value.length
    gifPickerHasMore.value = nextItems.length >= GIPHY_PICKER_LIMIT
  } catch {
    if (!append) {
      gifPickerError.value = t('messages.gif.errors.load')
    }
  } finally {
    if (append) {
      gifPickerLoadingMore.value = false
    } else {
      gifPickerBusy.value = false
    }
  }
}

async function searchGifs({ append = false } = {}) {
  const query = String(gifPickerSearchTerm.value || '').trim()
  if (!query) {
    await loadTrendingGifs({ append })
    return
  }
  if (append) {
    if (gifPickerBusy.value || gifPickerLoadingMore.value || !gifPickerHasMore.value) {
      return
    }
    gifPickerLoadingMore.value = true
  } else {
    gifPickerBusy.value = true
    gifPickerError.value = ''
    gifPickerOffset.value = 0
    gifPickerHasMore.value = true
  }
  const requestOffset = append ? gifPickerOffset.value : 0
  try {
    const response = await fetch(
      `https://api.giphy.com/v1/gifs/search?api_key=${encodeURIComponent(GIPHY_API_KEY)}&q=${encodeURIComponent(query)}&limit=${GIPHY_PICKER_LIMIT}&offset=${requestOffset}&rating=g`,
    )
    if (!response.ok) {
      throw new Error('search')
    }
    const data = await response.json()
    const nextItems = Array.isArray(data?.data) ? data.data : []
    gifPickerItems.value = append ? [...gifPickerItems.value, ...nextItems] : nextItems
    gifPickerOffset.value = gifPickerItems.value.length
    gifPickerHasMore.value = nextItems.length >= GIPHY_PICKER_LIMIT
  } catch {
    if (!append) {
      gifPickerError.value = t('messages.gif.errors.search')
    }
  } finally {
    if (append) {
      gifPickerLoadingMore.value = false
    } else {
      gifPickerBusy.value = false
    }
  }
}

async function loadMoreGifs() {
  if (String(gifPickerSearchTerm.value || '').trim()) {
    await searchGifs({ append: true })
    return
  }
  await loadTrendingGifs({ append: true })
}

async function openGifPicker() {
  emojiPickerOpen.value = false
  gifPickerOpen.value = true
  gifPickerSearchTerm.value = ''
  await loadTrendingGifs()
}

function closeGifPicker() {
  gifPickerOpen.value = false
}

function selectGif(gifId) {
  const normalized = String(gifId || '').trim()
  if (!normalized) {
    return
  }
  draftText.value = `g:${normalized}`
  gifPickerOpen.value = false
}

function clearDraftGif() {
  const replyPrefix = composeReplyPrefix(replyDraft.value?.target || '')
  draftText.value = replyPrefix
  nextTick(() => {
    composerTextarea.value?.focus?.()
  })
}

async function clearGifSearch() {
  gifPickerSearchTerm.value = ''
  await loadTrendingGifs()
}

async function retryGifPickerRequest() {
  if (String(gifPickerSearchTerm.value || '').trim()) {
    await searchGifs()
    return
  }
  await loadTrendingGifs()
}

async function confirmClearMessages() {
  confirmDialog.value = {
    open: true,
    title: t('messages.confirm.clearTitle'),
    message: t('messages.confirm.clearMessage'),
    confirmLabel: t('common.clear'),
    action: async () => {
      await session.api('/api/messages/clear', {
        method: 'POST',
        body: JSON.stringify(session.activeConfigBody()),
      })
      messages.value = []
      activeConversationTotalMessages.value = 0
      writeSentDraftHistory(currentConversationKey.value, [])
      scheduleConversationCacheWrite(currentConversationKey.value, messages.value, activeConversationTotalMessages.value)
      await loadUnreadCounts()
      await loadConversationDirectory()
      session.setStatus(t('messages.status.cleared'))
    },
  }
}

async function setConversationMuteModeByKey(muteKey, mode) {
  if (!muteKey) {
    return
  }
  const normalizedMode = String(mode || 'none').trim().toLowerCase()
  const nextMuted = {
    ...mutedConversationsMap.value,
  }
  if (normalizedMode === 'none') {
    delete nextMuted[muteKey]
  } else if (normalizedMode === 'regular' || normalizedMode === 'all') {
    nextMuted[muteKey] = normalizedMode
  } else {
    return
  }
  await session.updateClientSettings({
    muted_conversations: nextMuted,
    muted_conversations_updated_at: Date.now(),
  })
}

async function toggleCurrentConversationMuteMode(mode) {
  const muteKey = getCurrentConversationMuteKey()
  if (!muteKey) {
    return
  }
  const normalizedMode = String(mode || '').trim().toLowerCase()
  const nextMode = currentConversationMuteMode.value === normalizedMode ? 'none' : normalizedMode
  try {
    await setConversationMuteModeByKey(muteKey, nextMode)
    chatActionsMenuOpen.value = false
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('common.unknown')), true)
  }
}

function openClearMessagesDialogFromMenu() {
  chatActionsMenuOpen.value = false
  void confirmClearMessages()
}

async function submitConfirmDialog() {
  const action = confirmDialog.value.action
  confirmDialog.value = {
    open: false,
    title: '',
    message: '',
    confirmLabel: t('common.confirm'),
    action: null,
  }
  if (typeof action === 'function') {
    await action()
  }
}

async function setAllMessagesReadState(scope = 'regular') {
  const normalizedScope = String(scope || 'regular')
  const mentionName = String(session.selfName || '')
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
  await loadConversationDirectory()
  if (currentConversation.value) {
    await loadConversationHistory()
  }
  const total = normalizedScope === 'mention'
    ? Number(data.mention_messages || 0) + Number(data.mention_contact_messages || 0)
    : Number(data.messages || 0) + Number(data.contact_messages || 0)
  session.setStatus(t(
    normalizedScope === 'mention' ? 'notifications.status.markedMentionsRead' : 'notifications.status.markedMessagesRead',
    { total },
  ))
}

function requestSetAllMessagesReadState(scope = 'regular') {
  const normalizedScope = String(scope || 'regular')
  confirmDialog.value = {
    open: true,
    title: t('common.confirmation'),
    message: normalizedScope === 'mention'
      ? t('notifications.confirm.markMentionsRead')
      : t('notifications.confirm.markRegularRead'),
    confirmLabel: t('notifications.actions.markRead'),
    action: async () => setAllMessagesReadState(normalizedScope),
  }
}

async function openNotificationEntry(entry) {
  notificationsOpen.value = false
  if (entry.kind === 'channel') {
    await selectChannel(entry.value, {
      focusMessageId: entry.focusMessageId,
      notificationHighlightTone: entry.highlightTone,
    })
    return
  }
  await selectContact(entry.value, {
    focusMessageId: entry.focusMessageId,
    notificationHighlightTone: entry.highlightTone,
  })
}

function openConnectScreenAfterDisconnect(message) {
  stopListening()
  closeAllFloats()
  session.showConnectNotice(message, true)
  router.replace({ path: '/messages' })
}

function updateChannelPreview(message) {
  session.updateChannelSnapshot(message?.channel_idx, {
    last_message_preview: message.text || '',
    last_message_from_self: Boolean(message.from_self),
    last_message_ts: Number(message.sender_timestamp || Math.floor(Date.now() / 1000)),
  })
}

function updateContactPreview(message) {
  const prefix = getContactPrefix(message?.pubkey_prefix || message?.public_key || '')
  session.updateContactSnapshotByPrefix(prefix, {
    last_message_text: message.text || '',
    last_message_at: Number(message.sender_timestamp || Math.floor(Date.now() / 1000)),
    last_message_from_self: Boolean(message.from_self),
  })
}

function handleIncomingMessage(payload) {
  const shouldStickToBottom = isMessageScrollerNearBottom()
  if (payload.message_type === 'channel') {
    updateChannelPreview(payload)
    if (selectedConversationKind.value === 'channel' && Number(selectedChannelIdx.value) === Number(payload.channel_idx)) {
      const nextMessage = shouldStickToBottom
        ? { ...payload, is_read: true, is_mention_read: shouldMarkIncomingMessageMentionRead(payload) }
        : payload
      messages.value = sanitizeMessageList([...messages.value, nextMessage])
      activeConversationTotalMessages.value = Math.max(activeConversationTotalMessages.value + 1, messages.value.length)
      scheduleConversationCacheWrite(currentConversationKey.value, messages.value, activeConversationTotalMessages.value)
      if (shouldStickToBottom) {
        animateMessageAppearance(payload)
        nextTick(() => {
          scrollMessagesToBottom('smooth')
          scheduleVisibleReadTracking(40)
          updateScrollToBottomButtonVisibility()
        })
      }
    } else {
      nextTick(() => updateScrollToBottomButtonVisibility())
    }
    return
  }
  updateContactPreview(payload)
  if (selectedConversationKind.value === 'contact' && getContactPrefix(selectedContactKey.value) === getContactPrefix(payload.public_key || payload.pubkey_prefix || '')) {
    const nextMessage = shouldStickToBottom
      ? { ...payload, is_read: true, is_mention_read: shouldMarkIncomingMessageMentionRead(payload) }
      : payload
    messages.value = sanitizeMessageList([...messages.value, nextMessage])
    activeConversationTotalMessages.value = Math.max(activeConversationTotalMessages.value + 1, messages.value.length)
    scheduleConversationCacheWrite(currentConversationKey.value, messages.value, activeConversationTotalMessages.value)
    if (shouldStickToBottom) {
      animateMessageAppearance(payload)
      nextTick(() => {
        scrollMessagesToBottom('smooth')
        scheduleVisibleReadTracking(40)
        updateScrollToBottomButtonVisibility()
      })
    } else {
      nextTick(() => updateScrollToBottomButtonVisibility())
    }
  }
}

function handleMessageScroll() {
  closeMessageContextMenu()
  const host = messageScroller.value
  if (
    host
    && host.scrollTop <= 40
    && canLoadOlderMessages.value
    && topHistoryPaginationArmed.value
    && Date.now() >= suppressTopPaginationUntil.value
  ) {
    void loadOlderMessages()
  }
  handleMessageScrollBase()
}

function markTopPaginationIntentReady() {
  topHistoryPaginationArmed.value = true
}

function detachMessageTopPaginationIntentListeners() {
  if (!(messageTopPaginationIntentHost instanceof HTMLElement)) {
    messageTopPaginationIntentHost = null
    return
  }
  messageTopPaginationIntentHost.removeEventListener('wheel', markTopPaginationIntentReady)
  messageTopPaginationIntentHost.removeEventListener('touchstart', markTopPaginationIntentReady)
  messageTopPaginationIntentHost.removeEventListener('pointerdown', markTopPaginationIntentReady)
  messageTopPaginationIntentHost.removeEventListener('keydown', markTopPaginationIntentReady)
  messageTopPaginationIntentHost = null
}

function attachMessageTopPaginationIntentListeners(host) {
  detachMessageTopPaginationIntentListeners()
  if (!(host instanceof HTMLElement)) {
    return
  }
  host.addEventListener('wheel', markTopPaginationIntentReady, { passive: true })
  host.addEventListener('touchstart', markTopPaginationIntentReady, { passive: true })
  host.addEventListener('pointerdown', markTopPaginationIntentReady, { passive: true })
  host.addEventListener('keydown', markTopPaginationIntentReady)
  messageTopPaginationIntentHost = host
}

function scrollToNewestMessage() {
  scrollToNewestMessageBase()
}

function insertEmojiAtCursor(emojiText) {
  const emoji = String(emojiText || '').trim()
  if (!emoji) {
    return
  }
  const element = composerTextarea.value
  const currentValue = String(draftText.value || '')
  if (!(element instanceof HTMLTextAreaElement)) {
    draftText.value = `${currentValue}${emoji}`
    return
  }
  const selectionStart = Number(element.selectionStart ?? currentValue.length)
  const selectionEnd = Number(element.selectionEnd ?? selectionStart)
  draftText.value = `${currentValue.slice(0, selectionStart)}${emoji}${currentValue.slice(selectionEnd)}`
  nextTick(() => {
    const nextCursor = selectionStart + emoji.length
    element.focus()
    element.setSelectionRange(nextCursor, nextCursor)
  })
}

function handleEmojiSelect(emoji) {
  insertEmojiAtCursor(emoji?.i || '')
}

function markDeliveredByAck(ackHex) {
  messages.value = messages.value.map((message) => {
    if (!message?.from_self || !ackHexesMatch(message?.expected_ack_hex, ackHex)) {
      return message
    }
    return {
      ...message,
      send_status: 'delivered',
      acked_at: message?.acked_at || Math.floor(Date.now() / 1000),
    }
  })
  scheduleConversationCacheWrite(currentConversationKey.value, messages.value, activeConversationTotalMessages.value)
}

function markChannelRelayed(channelIdx, senderTimestamp, text, fullText, messageId, sendStatus, pathLen, pathHashes) {
  const candidateTexts = new Set(
    [String(text || ''), String(fullText || '')].filter((value) => value),
  )
  messages.value = messages.value.map((message) => {
    if (messageId && Number(message?.id || 0) === Number(messageId)) {
      const nextStatus = sendStatus ? String(sendStatus) : String(message?.send_status || '')
      return {
        ...message,
        send_status: nextStatus,
        acked_at: nextStatus === 'delivered'
          ? (message?.acked_at || Math.floor(Date.now() / 1000))
          : message?.acked_at,
        path_len: Number(pathLen ?? message?.path_len ?? -1),
        path_hashes: String(pathHashes || message?.path_hashes || ''),
      }
    }
    if (Number(message?.channel_idx || -1) !== Number(channelIdx)) {
      return message
    }
    if (Number(message?.sender_timestamp || 0) !== Number(senderTimestamp)) {
      return message
    }
    if (!candidateTexts.has(String(message?.text || ''))) {
      return message
    }
    const nextStatus = sendStatus ? String(sendStatus) : String(message?.send_status || '')
    return {
      ...message,
      send_status: nextStatus,
      acked_at: nextStatus === 'delivered'
        ? (message?.acked_at || Math.floor(Date.now() / 1000))
        : message?.acked_at,
      path_len: Number(pathLen ?? message?.path_len ?? -1),
      path_hashes: String(pathHashes || message?.path_hashes || ''),
    }
  })
  scheduleConversationCacheWrite(currentConversationKey.value, messages.value, activeConversationTotalMessages.value)
}

function stopListening() {
  if (eventSource.value) {
    eventSource.value.close()
    eventSource.value = null
  }
  eventSourceKey = ''
}

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

function startListening() {
  if (!getOwnerPort()) {
    stopListening()
    return
  }
  const nextEventSourceKey = [
    String(session.activeConnectionKey || ''),
  ].join('|')
  if (eventSource.value && eventSourceKey === nextEventSourceKey) {
    return
  }
  stopListening()
  const query = session.activeEventStreamQuery() || new URLSearchParams()
  const source = new EventSource(`/api/events?${query.toString()}`)
  eventSource.value = source
  eventSourceKey = nextEventSourceKey
  source.onmessage = async (event) => {
    const payload = JSON.parse(String(event.data || '{}'))
    if (payload.event === 'heartbeat') {
      return
    }
    appendConsoleEntry(payload)
    if (payload.event === 'connected') {
      session.applySessionSnapshot({ ...payload, active: true })
      markHydrationListChanged()
      applyConnectedStatusFromSnapshot({ ...session.sessionSnapshot, ...payload, active: true })
      await ensureConversationSelectionReady({ loadHistoryIfNeeded: true })
      if (session.messagesHydrating) {
        await loadUnreadCounts()
        await maybeFinishMessagesHydration({ loadHistoryIfNeeded: !messages.value.length })
      }
      return
    }
    if (payload.event === 'contacts-sync') {
      applyContactsSnapshot(payload.contacts)
      session.patchSessionSnapshotFields({
        recent_repeaters_count: payload.recent_repeaters_count,
        contact_summary: payload.contact_summary || null,
      })
      markHydrationListChanged()
      if (session.messagesHydrating) {
        await loadUnreadCounts()
      }
      await ensureConversationSelectionReady({ loadHistoryIfNeeded: !messages.value.length })
      if (session.messagesHydrating) {
        await maybeFinishMessagesHydration({ loadHistoryIfNeeded: !messages.value.length })
      }
      return
    }
    if (payload.event === 'client-settings') {
      session.applyClientSettingsPayload({
        ...session.settingsPayload,
        settings: payload.settings || {},
      })
      return
    }
    if (payload.event === 'radio-stats') {
      const nextTxSecs = payload.radio_stats?.tx_air_secs == null ? null : Number(payload.radio_stats.tx_air_secs)
      if (nextTxSecs != null && lastRadioTxSecs.value != null && nextTxSecs > lastRadioTxSecs.value) {
        session.noteRadioTransmission()
      }
      lastRadioTxSecs.value = nextTxSecs
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
      const activeQueueStatus = appendQueueStateStatus('', session.queueState, { t }).trim()
      if (activeQueueStatus) {
        session.setStatus(activeQueueStatus)
        return
      }
      const queueDrainStatus = describeQueueDrainStatus(payload.reason || '', session.queueState, { t })
      if (queueDrainStatus) {
        session.setStatus(queueDrainStatus)
        return
      }
      applyConnectedStatusFromSnapshot()
      return
    }
    if (payload.event === 'disconnected') {
      finishMessagesHydration()
      session.applySessionSnapshot({
        ...session.sessionSnapshot,
        active: false,
        queue_state: payload.queue_state || null,
        stop_state: normalizeStopState({
          ...(payload.stop_state || {}),
          port: getOwnerPort(),
          intentional: !payload.auto_reconnect,
          stop_reason: payload.stop_reason || payload.reason || '',
          last_stop_kind: payload.stop_kind || '',
          last_stop_reason: payload.stop_reason || payload.reason || '',
          last_failure_kind: payload.failure_kind || '',
          last_reconnect_reason: payload.auto_reconnect ? (payload.reason || '') : '',
          reconnect_scheduled_at: payload.reconnect_scheduled_at || (payload.auto_reconnect ? Date.now() / 1000 : 0),
          reconnect_delay_secs: payload.reconnect_delay_secs || 0,
          next_reconnect_at: payload.next_reconnect_at || 0,
          reconnect_attempts: payload.reconnect_attempts || 0,
          last_connected_at: session.stopState?.last_connected_at || 0,
          last_failure_at: payload.auto_reconnect ? Math.floor(Date.now() / 1000) : 0,
        }),
      })
      applyRestorePendingStatus()
      messages.value = []
      openConnectScreenAfterDisconnect(t('connect.notice.disconnected'))
      return
    }
    if (payload.event === 'error' && !payload.auto_reconnect) {
      session.setStatus(String(payload.message || t('messages.status.listenerUnavailable')), true)
      return
    }
    if (payload.event === 'message') {
      if (payload.recent_repeaters_count != null) {
        session.patchSessionSnapshotFields({
          recent_repeaters_count: payload.recent_repeaters_count,
        })
      }
      handleIncomingMessage(payload)
      await loadUnreadCounts()
      return
    }
    if (payload.event === 'channel-relayed') {
      markChannelRelayed(
        payload.channel_idx,
        payload.sender_timestamp,
        payload.text,
        payload.full_text,
        payload.id,
        payload.send_status,
        payload.path_len,
        payload.path_hashes,
      )
      if (payload.recent_repeaters_count != null) {
        session.patchSessionSnapshotFields({
          recent_repeaters_count: payload.recent_repeaters_count,
        })
      }
      return
    }
    if (payload.event === 'send-confirmed') {
      markDeliveredByAck(payload.ack_hex)
      session.noteRadioTransmission()
      return
    }
    if (payload.event === 'raw-advert') {
      if (payload.recent_repeaters_count != null) {
        session.patchSessionSnapshotFields({
          recent_repeaters_count: payload.recent_repeaters_count,
        })
      }
      session.noteRadioTransmission()
    }
  }
  source.onerror = () => {
    if (session.connected && !session.connecting) {
      const restoreStatus = describeRestorePendingStatus(session.stopState, {
        t,
        locale: locale.value,
      })
      session.setStatus(restoreStatus || t('messages.status.listenerReconnecting'))
      return
    }
    session.setStatus(t('messages.status.listenerUnavailable'))
  }
}

async function ensureScreenReady() {
  session.setMessagesHydrating(true)
  clearConversationSelection()
  markHydrationListChanged()
  scheduleHydrationCompletionCheck()
  try {
    if (!session.settingsPayload) {
      await session.loadClientSettings()
    }
    if (!session.ports.length) {
      await session.refreshPorts()
    }
    const snapshot = await session.syncSessionState({ light: false })
    if (!snapshot?.active) {
      finishMessagesHydration()
      router.replace({ name: 'connect' })
      return
    }
    if (session.collectionsReady && !session.channels.length) {
      await session.loadChannels()
    }
    if (session.collectionsReady && !session.contacts.length) {
      await session.loadContacts()
    }
    lastRadioTxSecs.value = session.radioStats?.tx_air_secs == null ? null : Number(session.radioStats.tx_air_secs)
    applyConnectedStatusFromSnapshot()
    await loadUnreadCounts()
    await loadConversationDirectory()
    await applyRequestedRouteConversation()
    await ensureConversationSelectionReady({ loadHistoryIfNeeded: true })
    startListening()
    if (!hasHydratedConversationEntries()) {
      await waitForInitialCollectionsReady()
    }
    await maybeFinishMessagesHydration({ loadHistoryIfNeeded: true })
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('messages.status.openFailed')), true)
    finishMessagesHydration()
  }
}

async function applyRequestedRouteConversation() {
  const requestedContactKey = requestedRouteContactKey.value
  const requestedChannelIdx = requestedRouteChannelIdx.value
  const requestedChannelIdentity = requestedRouteChannelIdentity.value
  const requestedFocusMessageId = requestedRouteFocusMessageId.value
  const requestedHighlightTone = requestedRouteHighlightTone.value
  const requestedFocusComposer = requestedRouteFocusComposer.value
  if (requestedChannelIdx != null || requestedChannelIdentity) {
    const requestedChannel = requestedChannelIdentity
      ? conversationChannelsSource.value.find((channel) => String(channel?.channel_identity || '').trim() === requestedChannelIdentity) || null
      : null
    const channelTarget = requestedChannel || {
      idx: requestedChannelIdx,
      channel_identity: requestedChannelIdentity,
      name: requestedChannelIdentity || (requestedChannelIdx != null ? `#${requestedChannelIdx}` : ''),
      is_on_node: requestedChannelIdx != null,
    }
    if (
      selectedConversationKind.value !== 'channel'
      || (
        requestedChannelIdentity
          ? String(selectedChannelIdentity.value || '').trim() !== requestedChannelIdentity
          : Number(selectedChannelIdx.value ?? -1) !== Number(requestedChannelIdx)
      )
    ) {
      await selectChannel(channelTarget, {
        focusMessageId: requestedFocusMessageId,
        notificationHighlightTone: requestedHighlightTone,
      })
    } else if (requestedFocusMessageId > 0) {
      await loadConversationHistory({
        focusMessageId: requestedFocusMessageId,
        notificationHighlightTone: requestedHighlightTone,
        skipCache: true,
      })
    }
    const nextQuery = { ...route.query }
    delete nextQuery.channel
    delete nextQuery.channel_identity
    delete nextQuery.focus
    delete nextQuery.tone
    delete nextQuery.compose
    await router.replace({
      path: '/messages',
      query: nextQuery,
    })
    if (requestedFocusComposer) {
      await nextTick()
      composerTextarea.value?.focus?.()
    }
    return true
  }
  if (!requestedContactKey) {
    return false
  }
  const requestedContact = conversationContactsSource.value.find((contact) => {
    const publicKey = normalizePublicKey(contact?.public_key)
    const prefix = getContactPrefix(contact)
    return publicKey === requestedContactKey || prefix === requestedContactKey
  })
  if (!requestedContact) {
    return false
  }
  const targetContactKey = normalizePublicKey(requestedContact?.public_key || requestedContactKey)
  if (
    selectedConversationKind.value !== 'contact'
    || normalizePublicKey(selectedContactKey.value) !== targetContactKey
  ) {
    await selectContact(targetContactKey, {
      focusMessageId: requestedFocusMessageId,
      notificationHighlightTone: requestedHighlightTone,
    })
  } else if (requestedFocusMessageId > 0) {
    await loadConversationHistory({
      focusMessageId: requestedFocusMessageId,
      notificationHighlightTone: requestedHighlightTone,
      skipCache: true,
    })
  }
  const nextQuery = { ...route.query }
  delete nextQuery.contact
  delete nextQuery.focus
  delete nextQuery.tone
  delete nextQuery.compose
  await router.replace({
    path: '/messages',
    query: nextQuery,
  })
  if (requestedFocusComposer) {
    await nextTick()
    composerTextarea.value?.focus?.()
  }
  return true
}

async function toggleNotificationSoundEnabled() {
  try {
    await session.toggleNotificationSoundEnabled()
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('notifications.sound.off')), true)
  }
}

async function disconnectAndStop() {
  await session.disconnectNode()
  messages.value = []
  openConnectScreenAfterDisconnect(t('connect.notice.disconnected'))
}

function handleGlobalPointerDown(event) {
  if (!messageContextMenu.value.open) {
    return
  }
  const target = event.target
  if (!(target instanceof Element)) {
    closeMessageContextMenu()
    return
  }
  if (target.closest('.mc-message-context-menu')) {
    return
  }
  closeMessageContextMenu()
}

function handleGlobalKeydown(event) {
  if (event.defaultPrevented || event.key !== 'Escape') {
    return
  }
  if (confirmDialog.value.open) {
    event.preventDefault()
    confirmDialog.value = {
      open: false,
      title: '',
      message: '',
      confirmLabel: t('common.confirm'),
      action: null,
    }
    return
  }
  if (messageRouteSheet.value.open) {
    event.preventDefault()
    closeMessageRouteSheet()
    return
  }
  if (messageContextMenu.value.open) {
    event.preventDefault()
    closeMessageContextMenu()
    return
  }
  if (gifPickerOpen.value) {
    event.preventDefault()
    closeGifPicker()
    return
  }
  if (emojiPickerOpen.value) {
    event.preventDefault()
    emojiPickerOpen.value = false
    return
  }
  if (chatActionsMenuOpen.value) {
    event.preventDefault()
    chatActionsMenuOpen.value = false
  }
}

watch(
  () => [
    channelEditorForm.value.type,
    channelEditorForm.value.name,
    channelEditorForm.value.hashtag,
    channelEditorForm.value.pskHex,
  ],
  () => {
    if (!workspaceShowsChannelEditor.value) {
      return
    }
    void syncChannelEditorPreview()
  },
)

watch(() => session.radioStats?.tx_air_secs, (nextValue, prevValue) => {
  if (nextValue == null) {
    return
  }
  if (prevValue != null && Number(nextValue) > Number(prevValue)) {
    session.noteRadioTransmission()
  }
  lastRadioTxSecs.value = Number(nextValue)
})

watch(
  () => [
    requestedRouteContactKey.value,
    requestedRouteChannelIdx.value,
    requestedRouteFocusMessageId.value,
    requestedRouteHighlightTone.value,
    conversationContactsSource.value.length,
    conversationChannelsSource.value.length,
    route.name,
  ],
  async ([requestedContactKey, requestedChannelIdx, requestedFocusMessageId, requestedHighlightTone, _contactCount, _channelCount, routeName]) => {
    if (
      routeName !== 'messages'
      || (!requestedContactKey && requestedChannelIdx == null && !requestedFocusMessageId && !requestedHighlightTone)
    ) {
      return
    }
    await applyRequestedRouteConversation()
  },
)

watch(
  () => [
    route.name,
    session.connected,
    session.activeConnectionKey,
    accessAllMeshcoriumMessages.value,
    session.selfName,
  ],
  async ([routeName, connected, activeConnectionKey]) => {
    if (routeName !== 'messages' || !connected || !String(activeConnectionKey || '').trim()) {
      return
    }
    await loadConversationDirectory()
  },
)

watch(
  chatBackgroundId,
  async (backgroundId, _previous, onCleanup) => {
    let cancelled = false
    onCleanup(() => {
      cancelled = true
    })
    releaseResolvedChatWallpaperUrl()
    if (!String(backgroundId || '').startsWith('wallpaper:')) {
      return
    }
    const wallpaperName = String(backgroundId || '').slice('wallpaper:'.length).trim()
    if (!wallpaperName) {
      return
    }
    try {
      const asset = await resolveCachedWallpaperAsset(wallpaperName)
      if (cancelled) {
        asset.revoke()
        return
      }
      resolvedChatWallpaperUrl.value = asset.url
      releaseChatWallpaperUrl = asset.revoke
    } catch (error) {
      console.error('[meshcorium] chat-wallpaper-cache', {
        message: error instanceof Error ? error.message : String(error || 'unknown'),
        wallpaperName,
      })
      if (!cancelled) {
        resolvedChatWallpaperUrl.value = `/wallpappers/${encodeURIComponent(wallpaperName)}`
      }
    }
  },
  { immediate: true },
)

watch(() => [phonebarTick.value, session.connected, session.stopState?.reconnect_attempts, session.stopState?.next_reconnect_at], () => {
  if (!session.connected && !session.connecting) {
    applyRestorePendingStatus()
  }
})

watch([consoleOpen, filteredConsoleEntries, consoleSearchTerm], async () => {
  await nextTick()
  syncConsoleSearchMatchState()
  if (consoleOpen.value && consoleAutoScroll.value && consoleLogRef.value) {
    consoleLogRef.value.scrollTop = consoleLogRef.value.scrollHeight
  }
})

watch(draftText, (nextValue) => {
  if (!composerHistoryApplying.value) {
    if (
      composerHistoryIndex.value >= 0
      && String(nextValue || '') === activeComposerHistoryDraft.value
    ) {
      return
    }
    resetComposerHistoryNavigation()
  }
  const target = String(replyDraft.value?.target || '').trim()
  if (!target) {
    return
  }
  if (!String(nextValue || '').startsWith(composeReplyPrefix(target))) {
    replyDraft.value = null
  }
})

watch(
  () => [
    workspaceMode.value,
    currentConversationKey.value,
    messages.value.length,
  ],
  async () => {
    resetComposerHistoryNavigation()
    if (!currentConversation.value || workspaceShowsChannelEditor.value) {
      chatActionsMenuOpen.value = false
    }
    await nextTick()
    updateMessageScrollerMetrics()
    updateScrollToBottomButtonVisibility()
  },
)

watch(() => conversationListItems.value.length, async () => {
  await nextTick()
  updateConversationListMetrics()
  ensureConversationRowResizeObserver()
  if (session.messagesHydrating) {
    void maybeFinishMessagesHydration({ loadHistoryIfNeeded: !messages.value.length })
  }
})

watch(() => hydrationConversationSignature.value, () => {
  if (!session.messagesHydrating) {
    return
  }
  markHydrationListChanged()
  scheduleHydrationCompletionCheck()
})

watch(() => loadingConversationDirectory.value, (nextValue) => {
  if (!session.messagesHydrating || nextValue) {
    return
  }
  void maybeFinishMessagesHydration({ loadHistoryIfNeeded: !messages.value.length })
})

watch(() => session.messagesHydrating, (nextValue) => {
  if (nextValue) {
    markHydrationListChanged()
    scheduleHydrationCompletionCheck()
    return
  }
  cancelHydrationCompletionCheck()
})

watch(() => currentConversationKey.value, async () => {
  topHistoryPaginationArmed.value = true
  suppressTopPaginationUntil.value = 0
  closeMessageContextMenu()
  replyDraft.value = null
  resetVirtualMessageLayout()
  await nextTick()
  updateMessageScrollerMetrics()
  ensureMessageResizeObserver()
  ensureMessageVisibilityObserver()
})

watch(messageScroller, async () => {
  attachMessageTopPaginationIntentListeners(messageScroller.value)
  resetVirtualMessageLayout()
  await nextTick()
  updateMessageScrollerMetrics()
  ensureMessageResizeObserver()
  ensureMessageVisibilityObserver()
})

useTextareaAutosize({
  element: composerTextarea,
  input: draftText,
})

const { pause: pausePhonebarTick, resume: resumePhonebarTick } = useIntervalFn(() => {
  phonebarTick.value = Date.now()
}, 1000, { immediate: false })

onMounted(() => {
  ensureScreenReady()
  resumePhonebarTick()
  window.addEventListener('pointerdown', handleGlobalPointerDown)
  window.addEventListener('keydown', handleGlobalKeydown)
  nextTick(() => {
    updateConversationListMetrics()
    ensureConversationRowResizeObserver()
    updateMessageScrollerMetrics()
    ensureMessageResizeObserver()
    ensureMessageVisibilityObserver()
  })
})

onBeforeUnmount(() => {
  stopListening()
  pausePhonebarTick()
  releaseResolvedChatWallpaperUrl()
  clearNotificationMessageHighlight()
  window.removeEventListener('pointerdown', handleGlobalPointerDown)
  window.removeEventListener('keydown', handleGlobalKeydown)
  finishMessagesHydration()
  detachMessageTopPaginationIntentListeners()
  cancelScheduledMessageScrollWork()
  flushConversationCacheWrite()
  disconnectConversationRowResizeObserver()
  disconnectMessageResizeObserver()
  disconnectMessageVisibilityObserver()
  if (unreadRefreshTimer.value) {
    window.clearTimeout(unreadRefreshTimer.value)
    unreadRefreshTimer.value = null
  }
})
</script>

<template>
  <div class="mc-messages-route">
    <ShellPageFrame workspace-class="mc-content--shell-body">
      <template #workspace-top>
        <ShellPhonebar />
      </template>

      <template #scroller-header>
        <MessagesConversationSidebar
          section="header"
          :chat-edit-mode="chatEditMode"
          @toggle-edit-mode="toggleChatEditMode"
        />
      </template>

      <template #scroller-body>
        <MessagesConversationSidebar
          section="body"
          :chat-edit-mode="chatEditMode"
          :conversation-list-items="conversationListItems"
          :visible-conversation-list-window="visibleConversationListWindow"
          :scroller-entries-length="conversationHasEntries ? 1 : 0"
          :bind-scroller-ref="setConversationListScroller"
          :bind-row-element="bindConversationRowElement"
          @update-scroller-metrics="updateConversationListMetrics"
          @select-channel="selectChannel"
          @select-contact="selectContact"
          @open-channel-editor="openChannelEditor"
          @start-new-channel-editor="startNewChannelEditor"
          @reorder-channel="reorderChannelDialog"
        />
      </template>

      <template #scroller-footer>
        <MessagesConversationSidebar
          section="footer"
          :status-text="footerStatusText"
          :status-error="session.statusError"
          :connected="session.connected"
        />
      </template>

      <template #workspace-header>
        <MessagesWorkspaceHeader
          :model="workspaceHeaderModel"
          :menu-open="chatActionsMenuOpen"
          @update:menu-open="chatActionsMenuOpen = $event"
          @close-editor="closeChannelEditor"
          @open-clear-dialog="openClearMessagesDialogFromMenu"
          @toggle-regular-mute="toggleCurrentConversationMuteMode('regular')"
          @toggle-all-mute="toggleCurrentConversationMuteMode('all')"
        />
      </template>

      <template #workspace-body>
        <MessagesChannelEditorWorkspace
          v-if="workspaceShowsChannelEditor"
          :model="channelEditorViewModel"
          @set-type="setChannelEditorType"
          @update:hashtag="updateChannelEditorHashtag"
          @update:name="updateChannelEditorName"
          @update:psk-hex="updateChannelEditorPskHex"
          @close="closeChannelEditor"
          @delete="requestDeleteChannelEditor"
          @save="saveChannelEditor"
        />

        <MessagesEmptyWorkspace
          v-else-if="!currentConversation"
          :model="workspaceEmptyModel"
        />

        <div v-else class="mc-chat-workspace-pane" :style="chatWorkspacePaneStyle">
          <MessagesChatHistoryPane
            :loading-older-messages="loadingOlderMessages"
            :messages-length="messages.length"
            :virtual-message-window="virtualMessageWindow"
            :visible-rendered-messages="visibleRenderedMessages"
            :loading-messages="loadingMessages"
            :show-scroll-to-bottom-button="showScrollToBottomButton"
            :gif-cdn-url="gifCdnUrl"
            :bind-scroller-ref="setMessageScroller"
            :bind-message-card-element="bindMessageCardElement"
            @scroll="handleMessageScroll"
            @scroll-to-bottom="scrollToNewestMessage"
            @message-context-menu="openMessageContextMenu"
            @open-contact="openContactFromMessage"
          />

          <MessagesComposerBar
            v-if="workspaceMode === 'chat'"
            :model="composerModel"
            :emoji-picker-open="emojiPickerOpen"
            :draft-text="draftText"
            :gif-cdn-url="gifCdnUrl"
            :bind-textarea-ref="setComposerTextarea"
            :on-textarea-keydown="handleComposerTextareaKeydown"
            @open-gif-picker="openGifPicker"
            @update:emoji-picker-open="emojiPickerOpen = $event"
            @select-emoji="handleEmojiSelect"
            @clear-reply="clearReplyDraft"
            @clear-draft-gif="clearDraftGif"
            @update:draft-text="draftText = $event"
            @send-message="sendMessage"
          />
        </div>
      </template>
    </ShellPageFrame>

    <MessagesGifPickerSheet
      :model="gifPickerSheetModel"
      @close="closeGifPicker"
      @update:search-term="gifPickerSearchTerm = $event"
      @search="searchGifs"
      @clear-search="clearGifSearch"
      @retry="retryGifPickerRequest"
      @load-more="loadMoreGifs"
      @select-gif="selectGif"
    />

    <MessagesConfirmSheet
      :model="confirmSheetModel"
      @close="confirmDialog.open = false"
      @submit="submitConfirmDialog"
    />

    <MessagesRouteMapSheet
      :model="messageRouteSheet"
      @close="closeMessageRouteSheet"
    />

    <MessagesMessageContextMenu
      :model="messageContextMenuModel"
      @close="closeMessageContextMenu"
      @reply="activateReplyFromMessage()"
      @route-map="openRouteMapFromContextMenu"
      @toggle-contact-route="toggleDirectRouteFromContextMenu"
      @resend="resendMessageFromContextMenu"
      @copy="copyMessageFromContextMenu"
    />
  </div>
</template>
