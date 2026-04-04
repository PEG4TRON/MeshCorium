<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useStorage, useWindowSize } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import ContactsRepeaterGeoSheet from '../components/contacts/ContactsRepeaterGeoSheet.vue'
import ContactsRouteEditorSheet from '../components/contacts/ContactsRouteEditorSheet.vue'
import MessagesConfirmSheet from '../components/messages/MessagesConfirmSheet.vue'
import ShellPageFrame from '../components/layout/ShellPageFrame.vue'
import ShellPhonebar from '../components/layout/ShellPhonebar.vue'
import PluginDropdown from '../components/ui/PluginDropdown.vue'
import {
  buildContactRouteInputFromContact,
  buildKnownRoutePublicKeys,
  buildRoutePrefixHexFromPublicKeys,
  buildStoredContactRouteHops,
  choosePreferredRouteHashLenBytes,
  preferredRouteHopDisplayLength,
  resolveContactRouteTokens,
  resolvePreferredRouteHopToken,
  routeTokensFromInput,
} from '../lib/contactRoutes'
import {
  classifyContactKind,
  contactAvatarEmoji,
  contactAvatarText,
  contactCanDirect,
  contactCanManageRepeater,
  contactDisplayName,
  contactHasSavedRepeaterAuth,
  contactHasCoordinates,
  contactResidencyLabel,
  getContactPrefix,
  isContactFavorite,
  isContactOnNode,
  normalizePublicKey,
  shortContactPublicKey,
} from '../lib/contacts'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { width } = useWindowSize()

const contactsLoading = ref(false)
const groupsLoading = ref(false)
const contactsSearchTerm = ref('')
const contactsToolsCollapsed = ref(true)
const openContactsControl = ref(null)
const groupNameDialog = ref({
  open: false,
  mode: 'create',
  value: '',
  navigateToGroups: false,
})
const groupEditorOpen = ref(false)
const groupEditorBusy = ref(false)
const groupEditorSelection = ref([])
const groupEditorSearchTerm = ref('')
const groupEditorOrder = ref('heard-recently')
const groupEditorFilter = ref('all')
const routeEditorOpen = ref(false)
const routeEditorContactKey = ref('')
const routeEditorInput = ref('')
const routeTraceSequential = ref(true)
const routeTraceBusy = ref(false)
const routeTraceJobId = ref('')
const routeTraceResult = ref(null)
let contactsEventSource = null
const repeaterGeoSheetOpen = ref(false)
const repeaterLoginPassword = ref('')
const repeaterLoginRememberAuth = ref(false)
const repeaterLoginSavedAuthBypassKey = ref('')
const repeaterLoginSavedAuthRetryBlockKey = ref('')
const repeaterLoginNotice = ref({
  message: '',
  allowRetry: false,
})
const repeaterLoginBusy = ref(false)
const repeaterManagementPassword = ref('')
const repeaterManagementBusyAction = ref('')
const repeaterManagementDrafts = ref({})
const confirmDialog = ref({
  open: false,
  title: '',
  message: '',
  note: '',
  confirmLabel: '',
  confirmDisabled: false,
  action: null,
})
const groupsPayload = ref({
  groups: {},
  effective_groups: {},
  scope: null,
})
let routeTraceEventSource = null
let routeTraceFailureTimer = 0

const contactsOrder = useStorage('contacts_list_order', 'heard-recently')
const contactsFilter = useStorage('contacts_list_filter', 'all')
const selectedContactGroupFilter = useStorage('contacts_selected_group', 'all')

const repeaterCategories = computed(() => ([
  { id: 'basic', label: t('contactsView.repeater.categories.basic') },
  { id: 'radio', label: t('contactsView.repeater.categories.radio') },
  { id: 'location-gps', label: t('contactsView.repeater.categories.locationGps') },
  { id: 'routing', label: t('contactsView.repeater.categories.routing') },
  { id: 'adverts', label: t('contactsView.repeater.categories.adverts') },
  { id: 'bridge', label: t('contactsView.repeater.categories.bridge') },
  { id: 'acl', label: t('contactsView.repeater.categories.acl') },
  { id: 'region', label: t('contactsView.repeater.categories.region') },
  { id: 'actions', label: t('contactsView.repeater.categories.actions') },
]))

function buildRepeaterManagementInitialDraft(contact) {
  const lat = Number(contact?.lat)
  const lon = Number(contact?.lon)
  return {
    basic_name: String(contact?.adv_name || '').trim(),
    basic_admin_password: '',
    basic_guest_password: '',
    basic_owner_info: '',
    basic_powersaving: 'unchanged',
    basic_allow_read_only: 'unchanged',
    radio_freq: '',
    radio_bw: '250',
    radio_sf: '11',
    radio_cr: '5',
    radio_tx: '',
    radio_temp_freq: '',
    radio_temp_bw: '250',
    radio_temp_sf: '11',
    radio_temp_cr: '5',
    radio_temp_timeout: '',
    radio_adc_multiplier: '',
    location_lat: Number.isFinite(lat) ? String(lat) : '',
    location_lon: Number.isFinite(lon) ? String(lon) : '',
    gps_state: 'unchanged',
    gps_advert: 'unchanged',
    routing_repeat: 'unchanged',
    routing_path_hash_mode: '',
    routing_loop_detect: 'unchanged',
    routing_rxdelay: '',
    routing_txdelay: '',
    routing_direct_txdelay: '',
    routing_af: '',
    routing_int_thresh: '',
    routing_agc_reset_interval: '',
    routing_multi_acks: 'unchanged',
    routing_flood_max: '',
    advert_local_interval: '',
    advert_flood_interval: '',
    bridge_enabled: 'unchanged',
    bridge_delay: '',
    bridge_source: 'unchanged',
    bridge_baud: '',
    bridge_channel: '',
    bridge_secret: '',
    acl_pubkey: '',
    acl_permission: '3',
    region_home: '',
    region_allow_mode: 'allowf',
    region_allow_name: '',
    region_put_name: '',
    region_put_parent: '',
    region_remove_name: '',
  }
}

function repeaterTrimmedDraftValue(draft, key) {
  return String(draft?.[key] || '').trim()
}

function repeaterRequireTrimmedValue(draft, key, errorMessage) {
  const value = repeaterTrimmedDraftValue(draft, key)
  if (!value) {
    throw new Error(errorMessage)
  }
  return value
}

function parseRepeaterNumberField(draft, key, errorMessage, options = {}) {
  const rawValue = repeaterTrimmedDraftValue(draft, key)
  if (!rawValue) {
    throw new Error(errorMessage)
  }
  const numericValue = Number(rawValue)
  if (!Number.isFinite(numericValue)) {
    throw new Error(t('contactsView.repeater.errors.numberRequired', { label: errorMessage }))
  }
  if (options.min != null && numericValue < Number(options.min)) {
    throw new Error(t('contactsView.repeater.errors.numberMin', { label: errorMessage, min: options.min }))
  }
  if (options.max != null && numericValue > Number(options.max)) {
    throw new Error(t('contactsView.repeater.errors.numberMax', { label: errorMessage, max: options.max }))
  }
  return rawValue
}

function ensureRepeaterManagementDraft(contact) {
  const publicKey = normalizePublicKey(contact?.public_key)
  if (!publicKey) {
    return buildRepeaterManagementInitialDraft(contact)
  }
  if (!repeaterManagementDrafts.value[publicKey]) {
    repeaterManagementDrafts.value[publicKey] = buildRepeaterManagementInitialDraft(contact)
  }
  return repeaterManagementDrafts.value[publicKey]
}

const contactsMode = computed(() => {
  if (route.name === 'contacts-groups') {
    return 'groups'
  }
  if (route.name === 'contacts-repeater-login') {
    return 'repeater-login'
  }
  if (route.name === 'contacts-repeater') {
    return 'repeater-management'
  }
  return 'root'
})

const isContactsRootMode = computed(() => contactsMode.value === 'root')
const isGroupsMode = computed(() => contactsMode.value === 'groups')
const isRepeaterLoginMode = computed(() => contactsMode.value === 'repeater-login')
const isRepeaterManagementMode = computed(() => contactsMode.value === 'repeater-management')
const isMobile = computed(() => width.value <= 980)
const isShellMobile = computed(() => width.value <= 760)
const effectiveToolsCollapsed = computed(() => {
  return isShellMobile.value
    ? contactsToolsCollapsed.value
    : (Boolean(selectedContact.value) && contactsToolsCollapsed.value)
})

function normalizeContactRouteKey(value) {
  return normalizePublicKey(value)
}

function normalizeContactGroupFilter(value) {
  const next = String(value || '').trim()
  return next || 'all'
}

function normalizeContactsOrder(value) {
  const next = String(value || '').trim()
  return ['heard-recently', 'latest-messages', 'a-z'].includes(next) ? next : 'heard-recently'
}

function normalizeContactsFilter(value) {
  const next = String(value || '').trim()
  return ['all', 'chat', 'repeater', 'room', 'sensor', 'favorites', 'unread'].includes(next) ? next : 'all'
}

function normalizeGroupName(value) {
  return String(value || '').trim()
}

function getUnreadCount(contact) {
  const prefix = getContactPrefix(contact)
  return Math.max(
    0,
    Number(session.unreadSummary?.contact_unread_counts?.[prefix] ?? contact?.unread_count ?? 0),
  )
}

function getMentionCount(contact) {
  const prefix = getContactPrefix(contact)
  return Math.max(0, Number(session.unreadSummary?.contact_mention_counts?.[prefix] ?? 0))
}

function getContactLastMessageAt(contact) {
  return Math.max(0, Number(contact?.last_message_at || 0))
}

function getContactLastSeenAt(contact) {
  return Math.max(
    Math.max(0, Number(contact?.last_interaction_at || 0)),
    Math.max(0, Number(contact?.last_advert || 0)),
    getContactLastMessageAt(contact),
  )
}

function getContactPreview(contact) {
  if (contactHasDirectConversation(contact)) {
    return ''
  }
  const text = String(contact?.last_message_text || '').trim()
  if (!text) {
    return ''
  }
  if (contact?.last_message_from_self) {
    return t('messages.youPrefix', { text })
  }
  return text
}

function formatAgo(epoch) {
  const value = Math.max(0, Number(epoch || 0))
  if (!value) {
    return t('contactsView.time.never')
  }
  const diff = Math.max(0, Math.floor(Date.now() / 1000) - value)
  if (diff < 45) {
    return t('contactsView.time.justNow')
  }
  if (diff < 3600) {
    return t('contactsView.time.minutesAgo', { count: Math.max(1, Math.round(diff / 60)) })
  }
  if (diff < 86400) {
    return t('contactsView.time.hoursAgo', { count: Math.max(1, Math.round(diff / 3600)) })
  }
  return t('contactsView.time.daysAgo', { count: Math.max(1, Math.round(diff / 86400)) })
}

function formatContactActivityIndicator(label, epoch, suffix = '') {
  const value = Math.max(0, Number(epoch || 0))
  if (!value) {
    return `${label}: ${t('contactsView.time.never')}`
  }
  return `${label}: ${formatAgo(value)}${suffix ? ` ${suffix}` : ''}`
}

function formatContactCoordinates(contact) {
  if (!contactHasCoordinates(contact)) {
    return ''
  }
  return `${Number(contact.lat).toFixed(5)}, ${Number(contact.lon).toFixed(5)}`
}

function formatContactRoute(contact) {
  const pathLen = Number(contact?.out_path_len ?? -1)
  if (pathLen < 0) {
    return t('contactsView.route.flood')
  }
  const hops = buildStoredContactRouteHops(contact)
  if (!hops.length || pathLen === 0) {
    return t('contactsView.route.direct')
  }
  const knownCandidates = buildKnownRoutePublicKeys({
    selfPublicKey: session.self?.public_key,
    contacts: session.contacts,
  })
  const display = hops
    .map((hop) => resolvePreferredRouteHopToken(hop, knownCandidates, preferredRouteHopDisplayLength()))
    .filter(Boolean)
  return display.length ? display.join(' -> ') : t('contactsView.route.static')
}

function contactHasDirectConversation(contact) {
  return Math.max(0, Number(contact?.last_message_at || 0)) > 0
}

function summarizeContacts(contacts) {
  const items = Array.isArray(contacts) ? contacts : []
  const nodeResident = items.filter((contact) => isContactOnNode(contact)).length
  const nodeNonFavorites = items.filter((contact) => isContactOnNode(contact) && !isContactFavorite(contact)).length
  const dbOnly = items.filter((contact) => !isContactOnNode(contact)).length
  return {
    nodeResident,
    nodeNonFavorites,
    dbOnly,
    total: items.length,
  }
}

function buildContactRow(contact, { active = false } = {}) {
  const key = normalizeContactRouteKey(contact?.public_key || getContactPrefix(contact))
  const kind = classifyContactKind(contact)
  const unreadCount = getUnreadCount(contact)
  const mentionCount = getMentionCount(contact)
  const preview = getContactPreview(contact)
  return {
    raw: contact,
    key,
    title: contactDisplayName(contact, t('messages.fallback.unnamedContact')),
    shortKey: shortContactPublicKey(contact),
    kind,
    kindBadge: t(`messages.contactKindBadges.${kind}`),
    kindLabel: t(`messages.contactKinds.${kind}`),
    favorite: isContactFavorite(contact),
    onNode: isContactOnNode(contact),
    residency: contactResidencyLabel(contact, {
      onNode: t('contactsView.residency.onNode'),
      dbOnly: t('contactsView.residency.dbOnly'),
    }),
    routeLabel: formatContactRoute(contact),
    lastSeenAgo: formatAgo(getContactLastSeenAt(contact)),
    canDirect: contactCanDirect(contact),
    canManageRepeater: contactCanManageRepeater(contact),
    emoji: contactAvatarEmoji(contact, t('messages.fallback.unnamedContact')),
    avatar: contactAvatarText(contact, t('messages.fallback.unnamedContact')),
    hasCoordinates: contactHasCoordinates(contact),
    coordinatesText: formatContactCoordinates(contact),
    unreadCount,
    mentionCount,
    preview,
    active,
  }
}

function resolveContactByKey(key) {
  const normalizedKey = normalizeContactRouteKey(key)
  if (!normalizedKey) {
    return null
  }
  return session.contacts.find((contact) => {
    const publicKey = normalizePublicKey(contact?.public_key)
    const prefix = getContactPrefix(contact)
    return normalizedKey === publicKey || normalizedKey === prefix
  }) || null
}

function closeTransientContactsControls() {
  openContactsControl.value = null
}

function clearRepeaterLoginNotice() {
  repeaterLoginNotice.value = {
    message: '',
    allowRetry: false,
  }
}

function isRepeaterLoginTimeoutError(error) {
  const message = String(error instanceof Error ? error.message : error || '').trim().toLowerCase()
  return message.includes('empty frame while waiting for repeater login result')
}

function setRepeaterLoginErrorNotice(error, { useSavedAuth = false } = {}) {
  if (isRepeaterLoginTimeoutError(error)) {
    repeaterLoginNotice.value = {
      message: t('contactsView.repeater.loginRetryNotice'),
      allowRetry: true,
    }
    if (useSavedAuth) {
      repeaterLoginSavedAuthRetryBlockKey.value = normalizePublicKey(selectedRepeaterContact.value?.public_key)
    }
    session.setStatus(t('contactsView.repeater.loginRetryNotice'), true)
    return
  }
  clearRepeaterLoginNotice()
  session.setStatus(error instanceof Error ? error.message : String(error || t('common.error')), true)
}

const selectedRouteContactKey = computed(() => {
  if (isContactsRootMode.value) {
    return normalizeContactRouteKey(route.query.contact)
  }
  if (isRepeaterLoginMode.value || isRepeaterManagementMode.value) {
    return normalizeContactRouteKey(route.params.publicKey)
  }
  return ''
})

const selectedContact = computed(() => resolveContactByKey(selectedRouteContactKey.value))
const selectedRepeaterContact = computed(() => {
  return selectedContact.value && contactCanManageRepeater(selectedContact.value)
    ? selectedContact.value
    : null
})
const selectedContactHasSavedRepeaterAuth = computed(() => contactHasSavedRepeaterAuth(selectedContact.value))
const repeaterLoginUsesSavedAuth = computed(() => {
  const publicKey = normalizePublicKey(selectedRepeaterContact.value?.public_key)
  if (!isRepeaterLoginMode.value || !publicKey || !selectedRepeaterContact.value) {
    return false
  }
  if (!contactHasSavedRepeaterAuth(selectedRepeaterContact.value)) {
    return false
  }
  return repeaterLoginSavedAuthBypassKey.value !== publicKey
})

const repeaterLoginSavedAuthRetryAllowed = computed(() => {
  const publicKey = normalizePublicKey(selectedRepeaterContact.value?.public_key)
  if (!publicKey || !repeaterLoginUsesSavedAuth.value) {
    return false
  }
  return repeaterLoginSavedAuthRetryBlockKey.value === publicKey && repeaterLoginNotice.value.allowRetry
})
const selectedGroupName = computed(() => {
  if (!isGroupsMode.value) {
    return ''
  }
  return String(route.query.group || '').trim()
})

const repeaterCategoryId = computed(() => {
  if (!isRepeaterManagementMode.value) {
    return ''
  }
  const rawCategory = String(route.params.category || '').trim().toLowerCase()
  if (!rawCategory) {
    return ''
  }
  return repeaterCategories.value.some((entry) => entry.id === rawCategory) ? rawCategory : ''
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

const scrollerFooterStatus = computed(() => {
  return String(session.statusText || '').trim() || serviceStatusCopy.value
})

const totalContactSummary = computed(() => {
  const summary = session.sessionSnapshot?.contact_summary || {}
  return {
    nodeResident: Math.max(0, Number(summary.node_resident || 0)),
    nodeLimit: Math.max(0, Number(summary.node_limit || session.device?.max_contacts_base || session.device?.max_contacts || 0)),
    dbTotal: Math.max(0, Number(summary.db_total || session.sessionSnapshot?.contacts_count || session.contacts.length || 0)),
    dbOnly: Math.max(0, Number(summary.db_only || 0)),
    nodeNonFavorites: Math.max(0, Number(summary.node_non_favorites || 0)),
    policyNonFavoriteLimit: Math.max(0, Number(summary.policy_non_favorite_limit || 50)),
  }
})

const orderOptions = computed(() => ([
  { value: 'latest-messages', label: t('contactsView.orderOptions.latestMessages') },
  { value: 'heard-recently', label: t('contactsView.orderOptions.heardRecently') },
  { value: 'a-z', label: t('contactsView.orderOptions.alphabetical') },
]))

const filterOptions = computed(() => ([
  { value: 'all', label: t('contactsView.filterOptions.all') },
  { value: 'chat', label: t('contactsView.filterOptions.users') },
  { value: 'repeater', label: t('contactsView.filterOptions.repeaters') },
  { value: 'room', label: t('contactsView.filterOptions.rooms') },
  { value: 'sensor', label: t('contactsView.filterOptions.sensors') },
  { value: 'favorites', label: t('contactsView.filterOptions.favorites') },
  { value: 'unread', label: t('contactsView.filterOptions.unread') },
]))

const effectiveGroupsMap = computed(() => {
  const source = groupsPayload.value?.effective_groups
  return source && typeof source === 'object' && !Array.isArray(source) ? source : {}
})

const groupEntries = computed(() => {
  return Object.entries(effectiveGroupsMap.value)
    .sort(([left], [right]) => {
      const leftFav = left === 'favorites'
      const rightFav = right === 'favorites'
      if (leftFav !== rightFav) {
        return leftFav ? -1 : 1
      }
      return left.localeCompare(right, 'ru')
    })
    .map(([name, members]) => ({
      name,
      members: Array.isArray(members) ? members : [],
      count: Array.isArray(members) ? members.length : 0,
      active: String(selectedGroupName.value || '') === name,
    }))
})

const groupFilterOptions = computed(() => {
  const base = [
    { value: 'all', label: t('contactsView.groupOptions.allGroups') },
    ...groupEntries.value.map((group) => ({
      value: group.name,
      label: group.name,
      meta: t('contactsView.groups.memberCount', { count: group.count }),
    })),
  ]
  base.push({ value: '__add_group__', label: t('contactsView.groupOptions.addGroup') })
  return base
})

function contactMatchesTypeFilter(contact, filterValue) {
  const kind = classifyContactKind(contact)
  if (filterValue === 'chat') {
    return kind === 'user'
  }
  if (filterValue === 'repeater' || filterValue === 'room' || filterValue === 'sensor') {
    return kind === filterValue
  }
  return true
}

function contactIsInSelectedGroup(contact) {
  const selectedGroup = normalizeContactGroupFilter(selectedContactGroupFilter.value)
  if (selectedGroup === 'all') {
    return true
  }
  const members = effectiveGroupsMap.value?.[selectedGroup]
  if (!Array.isArray(members) || !members.length) {
    return false
  }
  const publicKey = normalizePublicKey(contact?.public_key)
  return publicKey ? members.includes(publicKey) : false
}

const visibleContacts = computed(() => {
  let contacts = Array.isArray(session.contacts) ? session.contacts.slice() : []
  if (contactsFilter.value === 'favorites') {
    contacts = contacts.filter((contact) => isContactFavorite(contact))
  } else if (contactsFilter.value === 'unread') {
    contacts = contacts.filter((contact) => getUnreadCount(contact) > 0)
  } else if (contactsFilter.value !== 'all') {
    contacts = contacts.filter((contact) => contactMatchesTypeFilter(contact, contactsFilter.value))
  }
  contacts = contacts.filter((contact) => contactIsInSelectedGroup(contact))
  if (contactsOrder.value === 'latest-messages') {
    contacts.sort((left, right) => getContactLastMessageAt(right) - getContactLastMessageAt(left))
  } else if (contactsOrder.value === 'a-z') {
    contacts.sort((left, right) => contactDisplayName(left, t('messages.fallback.unnamedContact')).localeCompare(
      contactDisplayName(right, t('messages.fallback.unnamedContact')),
      'ru',
    ))
  } else {
    contacts.sort((left, right) => getContactLastSeenAt(right) - getContactLastSeenAt(left))
  }
  const search = String(contactsSearchTerm.value || '').trim().toLowerCase()
  if (search) {
    contacts = contacts.filter((contact) => {
      return contactDisplayName(contact, t('messages.fallback.unnamedContact')).toLowerCase().includes(search)
        || String(contact?.public_key || '').toLowerCase().includes(search)
    })
  }
  return contacts
})

const visibleContactSummary = computed(() => summarizeContacts(visibleContacts.value))

const contactsRows = computed(() => {
  return visibleContacts.value.map((contact) => {
    const key = normalizeContactRouteKey(contact?.public_key || getContactPrefix(contact))
    return buildContactRow(contact, {
      active: Boolean(key) && key === selectedRouteContactKey.value,
    })
  })
})

const listSummaryText = computed(() => {
  if (!session.connected) {
    return t('contactsView.summary.disconnected')
  }
  if (!session.contacts.length) {
    return contactsLoading.value ? t('contactsView.loading') : t('contactsView.summary.empty')
  }
  if (!contactsRows.value.length) {
    return t('contactsView.summary.filteredEmpty')
  }
  return t('contactsView.summary.populated', {
    visible: contactsRows.value.length,
    total: session.contacts.length,
    visibleNodeResident: visibleContactSummary.value.nodeResident,
    visibleNodeNonFavorites: visibleContactSummary.value.nodeNonFavorites,
    visibleDbOnly: visibleContactSummary.value.dbOnly,
    totalNodeResident: totalContactSummary.value.nodeResident,
    totalNodeLimit: totalContactSummary.value.nodeLimit || '—',
    totalNodeNonFavorites: totalContactSummary.value.nodeNonFavorites,
    totalPolicyLimit: totalContactSummary.value.policyNonFavoriteLimit || 50,
    totalDbTotal: totalContactSummary.value.dbTotal,
  })
})

const selectedGroup = computed(() => {
  if (!selectedGroupName.value) {
    return null
  }
  return groupEntries.value.find((entry) => entry.name === selectedGroupName.value) || null
})

const selectedGroupIsFavorites = computed(() => selectedGroup.value?.name === 'favorites')

const selectedGroupMembers = computed(() => {
  if (!selectedGroup.value) {
    return []
  }
  const memberSet = new Set(selectedGroup.value.members.map((entry) => normalizePublicKey(entry)))
  return (Array.isArray(session.contacts) ? session.contacts : [])
    .filter((contact) => memberSet.has(normalizePublicKey(contact?.public_key)))
    .map((contact) => buildContactRow(contact))
})

const contactGroupsScopeLabel = computed(() => {
  const scope = groupsPayload.value?.scope || null
  const scopeKey = String(scope?.scope_key || '').trim()
  if (!scopeKey) {
    return t('contactsView.groups.scopeClient')
  }
  const activePort = String(scope?.active_port || '').trim()
  const activeBaudrate = Number(scope?.active_baudrate || 0)
  if (activePort) {
    return t('contactsView.groups.scopeRadio', {
      port: activePort,
      baudrate: activeBaudrate || 115200,
    })
  }
  return t('contactsView.groups.scopeRadioGeneric', { scope: scopeKey })
})

const selectedGroupWorkspaceNote = computed(() => {
  if (!selectedGroup.value) {
    return ''
  }
  return selectedGroupIsFavorites.value
    ? t('contactsView.groups.favoritesNote')
    : t('contactsView.groups.customNote')
})

const groupEditorVisibleContacts = computed(() => {
  const search = String(groupEditorSearchTerm.value || '').trim().toLowerCase()
  let contacts = Array.isArray(session.contacts) ? session.contacts.slice() : []
  if (groupEditorFilter.value === 'favorites') {
    contacts = contacts.filter((contact) => isContactFavorite(contact))
  } else if (groupEditorFilter.value === 'unread') {
    contacts = contacts.filter((contact) => getUnreadCount(contact) > 0)
  } else if (groupEditorFilter.value !== 'all') {
    contacts = contacts.filter((contact) => contactMatchesTypeFilter(contact, groupEditorFilter.value))
  }
  if (groupEditorOrder.value === 'latest-messages') {
    contacts.sort((left, right) => getContactLastMessageAt(right) - getContactLastMessageAt(left))
  } else if (groupEditorOrder.value === 'a-z') {
    contacts.sort((left, right) => contactDisplayName(left, t('messages.fallback.unnamedContact')).localeCompare(
      contactDisplayName(right, t('messages.fallback.unnamedContact')),
      'ru',
    ))
  } else {
    contacts.sort((left, right) => getContactLastSeenAt(right) - getContactLastSeenAt(left))
  }
  if (search) {
    contacts = contacts.filter((contact) => {
      return contactDisplayName(contact, t('messages.fallback.unnamedContact')).toLowerCase().includes(search)
        || String(contact?.public_key || '').toLowerCase().includes(search)
    })
  }
  return contacts.map((contact) => buildContactRow(contact))
})

const groupEditorSelectionSet = computed(() => new Set(groupEditorSelection.value.map((entry) => normalizePublicKey(entry))))

const activeRepeaterCategory = computed(() => {
  if (!repeaterCategoryId.value) {
    return null
  }
  return repeaterCategories.value.find((entry) => entry.id === repeaterCategoryId.value) || null
})

const selectedRepeaterManagementDraft = computed(() => {
  return selectedRepeaterContact.value ? ensureRepeaterManagementDraft(selectedRepeaterContact.value) : null
})

const repeaterBasicCards = computed(() => ([
  {
    id: 'basic-name',
    title: t('contactsView.repeater.basicCards.name.title'),
    description: t('contactsView.repeater.basicCards.name.description'),
    applyLabel: t('contactsView.repeater.basicCards.name.apply'),
    buildCommands(draft) {
      const value = repeaterRequireTrimmedValue(draft, 'basic_name', t('contactsView.repeater.errors.nameRequired'))
      return [`set name ${value}`]
    },
    onSuccess({ contact, draft }) {
      patchRepeaterContact(contact?.public_key, { adv_name: repeaterTrimmedDraftValue(draft, 'basic_name') })
    },
    fields: [
      {
        key: 'basic_name',
        label: t('contactsView.repeater.basicCards.name.fieldLabel'),
        type: 'text',
        placeholder: t('contactsView.repeater.basicCards.name.placeholder'),
        maxLength: 32,
      },
    ],
  },
  {
    id: 'basic-admin-password',
    title: t('contactsView.repeater.basicCards.adminPassword.title'),
    description: t('contactsView.repeater.basicCards.adminPassword.description'),
    applyLabel: t('contactsView.repeater.basicCards.adminPassword.apply'),
    buildCommands(draft) {
      const value = repeaterRequireTrimmedValue(draft, 'basic_admin_password', t('contactsView.repeater.errors.adminPasswordRequired'))
      return [`password ${value}`]
    },
    onSuccess({ draft }) {
      const password = repeaterTrimmedDraftValue(draft, 'basic_admin_password')
      repeaterManagementPassword.value = password
      repeaterLoginPassword.value = password
    },
    fields: [
      {
        key: 'basic_admin_password',
        label: t('contactsView.repeater.basicCards.adminPassword.fieldLabel'),
        type: 'password',
        placeholder: t('contactsView.repeater.basicCards.adminPassword.placeholder'),
        maxLength: 96,
      },
    ],
  },
  {
    id: 'basic-guest-password',
    title: t('contactsView.repeater.basicCards.guestPassword.title'),
    description: t('contactsView.repeater.basicCards.guestPassword.description'),
    applyLabel: t('contactsView.repeater.basicCards.guestPassword.apply'),
    buildCommands(draft) {
      const value = repeaterRequireTrimmedValue(draft, 'basic_guest_password', t('contactsView.repeater.errors.guestPasswordRequired'))
      return [`set guest.password ${value}`]
    },
    fields: [
      {
        key: 'basic_guest_password',
        label: t('contactsView.repeater.basicCards.guestPassword.fieldLabel'),
        type: 'text',
        placeholder: t('contactsView.repeater.basicCards.guestPassword.placeholder'),
        maxLength: 96,
      },
    ],
  },
  {
    id: 'basic-owner-info',
    title: t('contactsView.repeater.basicCards.ownerInfo.title'),
    description: t('contactsView.repeater.basicCards.ownerInfo.description'),
    applyLabel: t('contactsView.repeater.basicCards.ownerInfo.apply'),
    buildCommands(draft) {
      const value = repeaterRequireTrimmedValue(draft, 'basic_owner_info', t('contactsView.repeater.errors.ownerInfoRequired'))
      return [`set owner.info ${value.replace(/\n+/g, '|')}`]
    },
    fields: [
      {
        key: 'basic_owner_info',
        label: t('contactsView.repeater.basicCards.ownerInfo.fieldLabel'),
        type: 'textarea',
        placeholder: t('contactsView.repeater.basicCards.ownerInfo.placeholder'),
        maxLength: 240,
        rows: 4,
      },
    ],
  },
  {
    id: 'basic-flags',
    title: t('contactsView.repeater.basicCards.flags.title'),
    description: t('contactsView.repeater.basicCards.flags.description'),
    applyLabel: t('contactsView.repeater.basicCards.flags.apply'),
    buildCommands(draft) {
      const commands = []
      const powerSaving = repeaterTrimmedDraftValue(draft, 'basic_powersaving')
      const allowReadOnly = repeaterTrimmedDraftValue(draft, 'basic_allow_read_only')
      if (powerSaving && powerSaving !== 'unchanged') {
        commands.push(`powersaving ${powerSaving}`)
      }
      if (allowReadOnly && allowReadOnly !== 'unchanged') {
        commands.push(`set allow.read.only ${allowReadOnly}`)
      }
      if (!commands.length) {
        throw new Error(t('contactsView.repeater.errors.flagsRequired'))
      }
      return commands
    },
    fields: [
      {
        key: 'basic_powersaving',
        label: t('contactsView.repeater.basicCards.flags.powerSaving'),
        type: 'select',
        options: [
          { value: 'unchanged', label: t('contactsView.repeater.unchanged') },
          { value: 'on', label: t('common.on') },
          { value: 'off', label: t('common.off') },
        ],
      },
      {
        key: 'basic_allow_read_only',
        label: t('contactsView.repeater.basicCards.flags.allowReadOnly'),
        type: 'select',
        options: [
          { value: 'unchanged', label: t('contactsView.repeater.unchanged') },
          { value: 'on', label: t('common.on') },
          { value: 'off', label: t('common.off') },
        ],
      },
    ],
  },
]))

const repeaterBandwidthOptions = computed(() => (
  ['7.8', '10.4', '15.6', '20.8', '31.25', '41.7', '62.5', '125', '250', '500']
    .map((value) => ({ value, label: value }))
))

const repeaterSfOptions = computed(() => (
  ['5', '6', '7', '8', '9', '10', '11', '12']
    .map((value) => ({ value, label: value }))
))

const repeaterCrOptions = computed(() => (
  ['5', '6', '7', '8']
    .map((value) => ({ value, label: `4/${value}` }))
))

const repeaterRadioCards = computed(() => ([
  {
    id: 'radio-main',
    title: t('contactsView.repeater.radioCards.main.title'),
    description: t('contactsView.repeater.radioCards.main.description'),
    applyLabel: t('contactsView.repeater.radioCards.main.apply'),
    buildCommands(draft) {
      const freq = parseRepeaterNumberField(draft, 'radio_freq', t('contactsView.repeater.radioFields.frequency'), { min: 300, max: 2500 })
      const bw = repeaterRequireTrimmedValue(draft, 'radio_bw', t('contactsView.repeater.errors.bandwidthRequired'))
      const sf = repeaterRequireTrimmedValue(draft, 'radio_sf', t('contactsView.repeater.errors.sfRequired'))
      const cr = repeaterRequireTrimmedValue(draft, 'radio_cr', t('contactsView.repeater.errors.crRequired'))
      return [`set radio ${freq},${bw},${sf},${cr}`]
    },
    fields: [
      {
        key: 'radio_freq',
        label: t('contactsView.repeater.radioFields.frequency'),
        type: 'number',
        placeholder: '869.525',
        min: 300,
        max: 2500,
        step: '0.001',
      },
      {
        key: 'radio_bw',
        label: t('contactsView.repeater.radioFields.bandwidth'),
        type: 'select',
        options: repeaterBandwidthOptions.value,
      },
      {
        key: 'radio_sf',
        label: t('contactsView.repeater.radioFields.sf'),
        type: 'select',
        options: repeaterSfOptions.value,
      },
      {
        key: 'radio_cr',
        label: t('contactsView.repeater.radioFields.cr'),
        type: 'select',
        options: repeaterCrOptions.value,
      },
    ],
  },
  {
    id: 'radio-tx',
    title: t('contactsView.repeater.radioCards.tx.title'),
    description: t('contactsView.repeater.radioCards.tx.description'),
    applyLabel: t('contactsView.repeater.radioCards.tx.apply'),
    buildCommands(draft) {
      const txPower = parseRepeaterNumberField(draft, 'radio_tx', t('contactsView.repeater.radioFields.txPower'), { min: 1, max: 22 })
      return [`set tx ${txPower}`]
    },
    fields: [
      {
        key: 'radio_tx',
        label: t('contactsView.repeater.radioFields.txPower'),
        type: 'number',
        placeholder: '17',
        min: 1,
        max: 22,
        step: '1',
      },
    ],
  },
  {
    id: 'radio-temp',
    title: t('contactsView.repeater.radioCards.temp.title'),
    description: t('contactsView.repeater.radioCards.temp.description'),
    applyLabel: t('contactsView.repeater.radioCards.temp.apply'),
    buildCommands(draft) {
      const freq = parseRepeaterNumberField(draft, 'radio_temp_freq', t('contactsView.repeater.radioFields.frequency'), { min: 300, max: 2500 })
      const bw = repeaterRequireTrimmedValue(draft, 'radio_temp_bw', t('contactsView.repeater.errors.bandwidthRequired'))
      const sf = repeaterRequireTrimmedValue(draft, 'radio_temp_sf', t('contactsView.repeater.errors.sfRequired'))
      const cr = repeaterRequireTrimmedValue(draft, 'radio_temp_cr', t('contactsView.repeater.errors.crRequired'))
      const timeout = parseRepeaterNumberField(draft, 'radio_temp_timeout', t('contactsView.repeater.radioFields.timeout'), { min: 1 })
      return [`tempradio ${freq},${bw},${sf},${cr},${timeout}`]
    },
    fields: [
      {
        key: 'radio_temp_freq',
        label: t('contactsView.repeater.radioFields.frequency'),
        type: 'number',
        placeholder: '869.525',
        min: 300,
        max: 2500,
        step: '0.001',
      },
      {
        key: 'radio_temp_bw',
        label: t('contactsView.repeater.radioFields.bandwidth'),
        type: 'select',
        options: repeaterBandwidthOptions.value,
      },
      {
        key: 'radio_temp_sf',
        label: t('contactsView.repeater.radioFields.sf'),
        type: 'select',
        options: repeaterSfOptions.value,
      },
      {
        key: 'radio_temp_cr',
        label: t('contactsView.repeater.radioFields.cr'),
        type: 'select',
        options: repeaterCrOptions.value,
      },
      {
        key: 'radio_temp_timeout',
        label: t('contactsView.repeater.radioFields.timeout'),
        type: 'number',
        placeholder: '15',
        min: 1,
        step: '1',
      },
    ],
  },
  {
    id: 'radio-adc',
    title: t('contactsView.repeater.radioCards.adc.title'),
    description: t('contactsView.repeater.radioCards.adc.description'),
    applyLabel: t('contactsView.repeater.radioCards.adc.apply'),
    buildCommands(draft) {
      const multiplier = parseRepeaterNumberField(draft, 'radio_adc_multiplier', t('contactsView.repeater.radioFields.adcMultiplier'), { min: 0, max: 10 })
      return [`set adc.multiplier ${multiplier}`]
    },
    fields: [
      {
        key: 'radio_adc_multiplier',
        label: t('contactsView.repeater.radioFields.adcMultiplier'),
        type: 'number',
        placeholder: '1.00',
        min: 0,
        max: 10,
        step: '0.01',
      },
    ],
  },
]))

const repeaterLocationCards = computed(() => ([
  {
    id: 'location-coords',
    title: t('contactsView.repeater.locationCards.coords.title'),
    description: t('contactsView.repeater.locationCards.coords.description'),
    applyLabel: t('contactsView.repeater.locationCards.coords.apply'),
    actions: [
      {
        id: 'location-pick-on-map',
        label: t('contactsView.repeater.locationCards.coords.pickOnMap'),
        kind: 'open-geo-picker',
      },
    ],
    buildCommands(draft) {
      const commands = []
      const lat = repeaterTrimmedDraftValue(draft, 'location_lat')
      const lon = repeaterTrimmedDraftValue(draft, 'location_lon')
      if (lat) {
        parseRepeaterNumberField(draft, 'location_lat', t('contactsView.repeater.locationFields.latitude'), { min: -90, max: 90 })
        commands.push(`set lat ${lat}`)
      }
      if (lon) {
        parseRepeaterNumberField(draft, 'location_lon', t('contactsView.repeater.locationFields.longitude'), { min: -180, max: 180 })
        commands.push(`set lon ${lon}`)
      }
      if (!commands.length) {
        throw new Error(t('contactsView.repeater.errors.coordsRequired'))
      }
      return commands
    },
    onSuccess({ contact, draft }) {
      const patch = {}
      const lat = repeaterTrimmedDraftValue(draft, 'location_lat')
      const lon = repeaterTrimmedDraftValue(draft, 'location_lon')
      if (lat) {
        patch.lat = Number(lat)
      }
      if (lon) {
        patch.lon = Number(lon)
      }
      patchRepeaterContact(contact?.public_key, patch)
    },
    fields: [
      {
        key: 'location_lat',
        label: t('contactsView.repeater.locationFields.latitude'),
        type: 'number',
        placeholder: '55.755826',
        min: -90,
        max: 90,
        step: '0.000001',
      },
      {
        key: 'location_lon',
        label: t('contactsView.repeater.locationFields.longitude'),
        type: 'number',
        placeholder: '37.617300',
        min: -180,
        max: 180,
        step: '0.000001',
      },
    ],
  },
  {
    id: 'gps-state',
    title: t('contactsView.repeater.locationCards.state.title'),
    description: t('contactsView.repeater.locationCards.state.description'),
    applyLabel: t('contactsView.repeater.locationCards.state.apply'),
    buildCommands(draft) {
      const value = repeaterTrimmedDraftValue(draft, 'gps_state')
      if (!value || value === 'unchanged') {
        throw new Error(t('contactsView.repeater.errors.gpsStateRequired'))
      }
      return [`gps ${value}`]
    },
    fields: [
      {
        key: 'gps_state',
        label: t('contactsView.repeater.locationFields.gps'),
        type: 'select',
        options: [
          { value: 'unchanged', label: t('contactsView.repeater.unchanged') },
          { value: 'on', label: t('common.on') },
          { value: 'off', label: t('common.off') },
        ],
      },
    ],
  },
  {
    id: 'gps-advert',
    title: t('contactsView.repeater.locationCards.advert.title'),
    description: t('contactsView.repeater.locationCards.advert.description'),
    applyLabel: t('contactsView.repeater.locationCards.advert.apply'),
    buildCommands(draft) {
      const value = repeaterTrimmedDraftValue(draft, 'gps_advert')
      if (!value || value === 'unchanged') {
        throw new Error(t('contactsView.repeater.errors.gpsAdvertRequired'))
      }
      return [`gps advert ${value}`]
    },
    fields: [
      {
        key: 'gps_advert',
        label: t('contactsView.repeater.locationFields.policy'),
        type: 'select',
        options: [
          { value: 'unchanged', label: t('contactsView.repeater.unchanged') },
          { value: 'none', label: 'none' },
          { value: 'share', label: 'share' },
          { value: 'prefs', label: 'prefs' },
        ],
      },
    ],
  },
  {
    id: 'gps-actions',
    title: t('contactsView.repeater.locationCards.actions.title'),
    description: t('contactsView.repeater.locationCards.actions.description'),
    actions: [
      {
        id: 'gps-sync',
        label: t('contactsView.repeater.locationCards.actions.sync'),
        commands: ['gps sync'],
      },
      {
        id: 'gps-setloc',
        label: t('contactsView.repeater.locationCards.actions.setloc'),
        commands: ['gps setloc'],
      },
    ],
  },
]))

const repeaterRoutingCards = computed(() => ([
  {
    id: 'routing-flags',
    title: t('contactsView.repeater.routingCards.flags.title'),
    description: t('contactsView.repeater.routingCards.flags.description'),
    applyLabel: t('contactsView.repeater.routingCards.flags.apply'),
    buildCommands(draft) {
      const commands = []
      const repeat = repeaterTrimmedDraftValue(draft, 'routing_repeat')
      const multiAcks = repeaterTrimmedDraftValue(draft, 'routing_multi_acks')
      if (repeat && repeat !== 'unchanged') {
        commands.push(`set repeat ${repeat}`)
      }
      if (multiAcks && multiAcks !== 'unchanged') {
        commands.push(`set multi.acks ${multiAcks}`)
      }
      if (!commands.length) {
        throw new Error(t('contactsView.repeater.errors.routingFlagsRequired'))
      }
      return commands
    },
    fields: [
      {
        key: 'routing_repeat',
        label: t('contactsView.repeater.routingFields.repeat'),
        type: 'select',
        options: [
          { value: 'unchanged', label: t('contactsView.repeater.unchanged') },
          { value: 'on', label: t('common.on') },
          { value: 'off', label: t('common.off') },
        ],
      },
      {
        key: 'routing_multi_acks',
        label: t('contactsView.repeater.routingFields.multiAcks'),
        type: 'select',
        options: [
          { value: 'unchanged', label: t('contactsView.repeater.unchanged') },
          { value: '1', label: t('contactsView.repeater.routingFields.enable') },
          { value: '0', label: t('contactsView.repeater.routingFields.disable') },
        ],
      },
    ],
  },
  {
    id: 'routing-delays',
    title: t('contactsView.repeater.routingCards.delays.title'),
    description: t('contactsView.repeater.routingCards.delays.description'),
    applyLabel: t('contactsView.repeater.routingCards.delays.apply'),
    buildCommands(draft) {
      const commands = []
      const rxdelay = repeaterTrimmedDraftValue(draft, 'routing_rxdelay')
      const txdelay = repeaterTrimmedDraftValue(draft, 'routing_txdelay')
      const directTxdelay = repeaterTrimmedDraftValue(draft, 'routing_direct_txdelay')
      if (rxdelay) {
        parseRepeaterNumberField(draft, 'routing_rxdelay', t('contactsView.repeater.routingFields.rxDelay'), { min: 0, max: 20 })
        commands.push(`set rxdelay ${rxdelay}`)
      }
      if (txdelay) {
        parseRepeaterNumberField(draft, 'routing_txdelay', t('contactsView.repeater.routingFields.txDelay'), { min: 0, max: 2 })
        commands.push(`set txdelay ${txdelay}`)
      }
      if (directTxdelay) {
        parseRepeaterNumberField(draft, 'routing_direct_txdelay', t('contactsView.repeater.routingFields.directTxDelay'), { min: 0, max: 2 })
        commands.push(`set direct.txdelay ${directTxdelay}`)
      }
      if (!commands.length) {
        throw new Error(t('contactsView.repeater.errors.routingDelayRequired'))
      }
      return commands
    },
    fields: [
      {
        key: 'routing_rxdelay',
        label: t('contactsView.repeater.routingFields.rxDelay'),
        type: 'number',
        placeholder: '0.0',
        min: 0,
        max: 20,
        step: '0.1',
      },
      {
        key: 'routing_txdelay',
        label: t('contactsView.repeater.routingFields.txDelay'),
        type: 'number',
        placeholder: '0.5',
        min: 0,
        max: 2,
        step: '0.1',
      },
      {
        key: 'routing_direct_txdelay',
        label: t('contactsView.repeater.routingFields.directTxDelay'),
        type: 'number',
        placeholder: '0.2',
        min: 0,
        max: 2,
        step: '0.1',
      },
    ],
  },
  {
    id: 'routing-airtime',
    title: t('contactsView.repeater.routingCards.airtime.title'),
    description: t('contactsView.repeater.routingCards.airtime.description'),
    applyLabel: t('contactsView.repeater.routingCards.airtime.apply'),
    buildCommands(draft) {
      const commands = []
      const af = repeaterTrimmedDraftValue(draft, 'routing_af')
      const intThresh = repeaterTrimmedDraftValue(draft, 'routing_int_thresh')
      const agcResetInterval = repeaterTrimmedDraftValue(draft, 'routing_agc_reset_interval')
      if (af) {
        parseRepeaterNumberField(draft, 'routing_af', t('contactsView.repeater.routingFields.af'), { min: 0, max: 9 })
        commands.push(`set af ${af}`)
      }
      if (intThresh) {
        parseRepeaterNumberField(draft, 'routing_int_thresh', t('contactsView.repeater.routingFields.interferenceThreshold'))
        commands.push(`set int.thresh ${intThresh}`)
      }
      if (agcResetInterval) {
        parseRepeaterNumberField(draft, 'routing_agc_reset_interval', t('contactsView.repeater.routingFields.agcResetInterval'), { min: 0 })
        commands.push(`set agc.reset.interval ${agcResetInterval}`)
      }
      if (!commands.length) {
        throw new Error(t('contactsView.repeater.errors.routingThresholdRequired'))
      }
      return commands
    },
    fields: [
      {
        key: 'routing_af',
        label: t('contactsView.repeater.routingFields.af'),
        type: 'number',
        placeholder: '1.0',
        min: 0,
        max: 9,
        step: '0.1',
      },
      {
        key: 'routing_int_thresh',
        label: t('contactsView.repeater.routingFields.interferenceThreshold'),
        type: 'number',
        placeholder: '0.0',
        step: '0.1',
      },
      {
        key: 'routing_agc_reset_interval',
        label: t('contactsView.repeater.routingFields.agcResetInterval'),
        type: 'number',
        placeholder: '0',
        min: 0,
        step: '4',
      },
    ],
  },
  {
    id: 'routing-path',
    title: t('contactsView.repeater.routingCards.path.title'),
    description: t('contactsView.repeater.routingCards.path.description'),
    applyLabel: t('contactsView.repeater.routingCards.path.apply'),
    buildCommands(draft) {
      const commands = []
      const pathHashMode = repeaterTrimmedDraftValue(draft, 'routing_path_hash_mode')
      const loopDetect = repeaterTrimmedDraftValue(draft, 'routing_loop_detect')
      const floodMax = repeaterTrimmedDraftValue(draft, 'routing_flood_max')
      if (pathHashMode) {
        commands.push(`set path.hash.mode ${pathHashMode}`)
      }
      if (loopDetect && loopDetect !== 'unchanged') {
        commands.push(`set loop.detect ${loopDetect}`)
      }
      if (floodMax) {
        parseRepeaterNumberField(draft, 'routing_flood_max', t('contactsView.repeater.routingFields.floodMax'), { min: 0, max: 64 })
        commands.push(`set flood.max ${floodMax}`)
      }
      if (!commands.length) {
        throw new Error(t('contactsView.repeater.errors.routingFloodRequired'))
      }
      return commands
    },
    fields: [
      {
        key: 'routing_path_hash_mode',
        label: t('contactsView.repeater.routingFields.pathHashMode'),
        type: 'select',
        options: [
          { value: '', label: t('contactsView.repeater.unchanged') },
          { value: '0', label: '0 · 1 byte' },
          { value: '1', label: '1 · 2 bytes' },
          { value: '2', label: '2 · 3 bytes' },
        ],
      },
      {
        key: 'routing_loop_detect',
        label: t('contactsView.repeater.routingFields.loopDetect'),
        type: 'select',
        options: [
          { value: 'unchanged', label: t('contactsView.repeater.unchanged') },
          { value: 'off', label: 'off' },
          { value: 'minimal', label: 'minimal' },
          { value: 'moderate', label: 'moderate' },
          { value: 'strict', label: 'strict' },
        ],
      },
      {
        key: 'routing_flood_max',
        label: t('contactsView.repeater.routingFields.floodMax'),
        type: 'number',
        placeholder: '64',
        min: 0,
        max: 64,
        step: '1',
      },
    ],
  },
]))

const repeaterAdvertCards = computed(() => ([
  {
    id: 'advert-intervals',
    title: t('contactsView.repeater.advertCards.intervals.title'),
    description: t('contactsView.repeater.advertCards.intervals.description'),
    applyLabel: t('contactsView.repeater.advertCards.intervals.apply'),
    buildCommands(draft) {
      const commands = []
      const localInterval = repeaterTrimmedDraftValue(draft, 'advert_local_interval')
      const floodInterval = repeaterTrimmedDraftValue(draft, 'advert_flood_interval')
      if (localInterval) {
        parseRepeaterNumberField(draft, 'advert_local_interval', t('contactsView.repeater.advertFields.localInterval'), { min: 0, max: 240 })
        commands.push(`set advert.interval ${localInterval}`)
      }
      if (floodInterval) {
        parseRepeaterNumberField(draft, 'advert_flood_interval', t('contactsView.repeater.advertFields.floodInterval'), { min: 0, max: 168 })
        commands.push(`set flood.advert.interval ${floodInterval}`)
      }
      if (!commands.length) {
        throw new Error(t('contactsView.repeater.errors.advertIntervalRequired'))
      }
      return commands
    },
    fields: [
      {
        key: 'advert_local_interval',
        label: t('contactsView.repeater.advertFields.localInterval'),
        type: 'number',
        placeholder: '0 или 60-240',
        min: 0,
        max: 240,
        step: '1',
      },
      {
        key: 'advert_flood_interval',
        label: t('contactsView.repeater.advertFields.floodInterval'),
        type: 'number',
        placeholder: '0 или 3-168',
        min: 0,
        max: 168,
        step: '1',
      },
    ],
  },
  {
    id: 'advert-actions',
    title: t('contactsView.repeater.advertCards.actions.title'),
    description: t('contactsView.repeater.advertCards.actions.description'),
    actions: [
      {
        id: 'advert-flood',
        label: t('contactsView.repeater.advertCards.actions.flood'),
        commands: ['advert'],
      },
      {
        id: 'advert-zerohop',
        label: t('contactsView.repeater.advertCards.actions.zerohop'),
        commands: ['advert.zerohop'],
      },
    ],
  },
]))

const repeaterBridgeCards = computed(() => ([
  {
    id: 'bridge-main',
    title: t('contactsView.repeater.bridgeCards.core.title'),
    description: t('contactsView.repeater.bridgeCards.core.description'),
    applyLabel: t('contactsView.repeater.bridgeCards.core.apply'),
    buildCommands(draft) {
      const commands = []
      const enabled = repeaterTrimmedDraftValue(draft, 'bridge_enabled')
      const delay = repeaterTrimmedDraftValue(draft, 'bridge_delay')
      const source = repeaterTrimmedDraftValue(draft, 'bridge_source')
      if (enabled && enabled !== 'unchanged') {
        commands.push(`set bridge.enabled ${enabled}`)
      }
      if (delay) {
        parseRepeaterNumberField(draft, 'bridge_delay', t('contactsView.repeater.bridgeFields.delay'), { min: 0, max: 10000 })
        commands.push(`set bridge.delay ${delay}`)
      }
      if (source && source !== 'unchanged') {
        commands.push(`set bridge.source ${source}`)
      }
      if (!commands.length) {
        throw new Error(t('contactsView.repeater.errors.bridgeParameterRequired'))
      }
      return commands
    },
    fields: [
      {
        key: 'bridge_enabled',
        label: t('contactsView.repeater.bridgeFields.enabled'),
        type: 'select',
        options: [
          { value: 'unchanged', label: t('contactsView.repeater.unchanged') },
          { value: 'on', label: t('common.on') },
          { value: 'off', label: t('common.off') },
        ],
      },
      {
        key: 'bridge_delay',
        label: t('contactsView.repeater.bridgeFields.delay'),
        type: 'number',
        placeholder: '500',
        min: 0,
        max: 10000,
        step: '1',
      },
      {
        key: 'bridge_source',
        label: t('contactsView.repeater.bridgeFields.source'),
        type: 'select',
        options: [
          { value: 'unchanged', label: t('contactsView.repeater.unchanged') },
          { value: 'logTx', label: 'logTx' },
          { value: 'logRx', label: 'logRx' },
        ],
      },
    ],
  },
  {
    id: 'bridge-transport',
    title: t('contactsView.repeater.bridgeCards.transport.title'),
    description: t('contactsView.repeater.bridgeCards.transport.description'),
    applyLabel: t('contactsView.repeater.bridgeCards.transport.apply'),
    buildCommands(draft) {
      const commands = []
      const baudrate = repeaterTrimmedDraftValue(draft, 'bridge_baud')
      const channel = repeaterTrimmedDraftValue(draft, 'bridge_channel')
      const secret = repeaterTrimmedDraftValue(draft, 'bridge_secret')
      if (baudrate) {
        commands.push(`set bridge.baud ${baudrate}`)
      }
      if (channel) {
        parseRepeaterNumberField(draft, 'bridge_channel', t('contactsView.repeater.bridgeFields.channel'), { min: 1, max: 14 })
        commands.push(`set bridge.channel ${channel}`)
      }
      if (secret) {
        commands.push(`set bridge.secret ${secret}`)
      }
      if (!commands.length) {
        throw new Error(t('contactsView.repeater.errors.bridgeTransportRequired'))
      }
      return commands
    },
    fields: [
      {
        key: 'bridge_baud',
        label: t('contactsView.repeater.bridgeFields.baudrate'),
        type: 'select',
        options: [
          { value: '', label: t('contactsView.repeater.unchanged') },
          { value: '9600', label: '9600' },
          { value: '19200', label: '19200' },
          { value: '38400', label: '38400' },
          { value: '57600', label: '57600' },
          { value: '115200', label: '115200' },
        ],
      },
      {
        key: 'bridge_channel',
        label: t('contactsView.repeater.bridgeFields.channel'),
        type: 'number',
        placeholder: '1-14',
        min: 1,
        max: 14,
        step: '1',
      },
      {
        key: 'bridge_secret',
        label: t('contactsView.repeater.bridgeFields.secret'),
        type: 'text',
        placeholder: t('contactsView.repeater.bridgeFields.secretPlaceholder'),
        maxLength: 15,
      },
    ],
  },
]))

const repeaterAclCards = computed(() => ([
  {
    id: 'acl-setperm',
    title: t('contactsView.repeater.aclCards.entry.title'),
    description: t('contactsView.repeater.aclCards.entry.description'),
    applyLabel: t('contactsView.repeater.aclCards.entry.apply'),
    buildCommands(draft) {
      const publicKey = repeaterRequireTrimmedValue(draft, 'acl_pubkey', t('contactsView.repeater.errors.aclPublicKeyRequired')).toLowerCase()
      if (!/^[0-9a-f]{64}$/.test(publicKey)) {
        throw new Error(t('contactsView.repeater.errors.aclPublicKeyInvalid'))
      }
      const permission = repeaterRequireTrimmedValue(draft, 'acl_permission', t('contactsView.repeater.errors.aclPermissionRequired'))
      return [permission === 'remove' ? `setperm ${publicKey}` : `setperm ${publicKey} ${permission}`]
    },
    fields: [
      {
        key: 'acl_pubkey',
        label: t('contactsView.repeater.aclFields.publicKey'),
        type: 'text',
        placeholder: t('contactsView.repeater.aclFields.publicKeyPlaceholder'),
        maxLength: 64,
      },
      {
        key: 'acl_permission',
        label: t('contactsView.repeater.aclFields.permission'),
        type: 'select',
        options: [
          { value: '0', label: t('contactsView.repeater.aclFields.permissions.guest') },
          { value: '1', label: t('contactsView.repeater.aclFields.permissions.readOnly') },
          { value: '2', label: t('contactsView.repeater.aclFields.permissions.readWrite') },
          { value: '3', label: t('contactsView.repeater.aclFields.permissions.admin') },
          { value: 'remove', label: t('contactsView.repeater.aclFields.permissions.remove') },
        ],
      },
    ],
  },
]))

const repeaterRegionCards = computed(() => ([
  {
    id: 'region-home',
    title: t('contactsView.repeater.regionCards.home.title'),
    description: t('contactsView.repeater.regionCards.home.description'),
    applyLabel: t('contactsView.repeater.regionCards.home.apply'),
    buildCommands(draft) {
      const value = repeaterRequireTrimmedValue(draft, 'region_home', t('contactsView.repeater.errors.regionHomeRequired'))
      return [`region home ${value}`]
    },
    fields: [
      {
        key: 'region_home',
        label: t('contactsView.repeater.regionFields.regionName'),
        type: 'text',
        placeholder: t('contactsView.repeater.regionFields.homePlaceholder'),
        maxLength: 64,
      },
    ],
  },
  {
    id: 'region-allow-deny',
    title: t('contactsView.repeater.regionCards.allowDeny.title'),
    description: t('contactsView.repeater.regionCards.allowDeny.description'),
    applyLabel: t('contactsView.repeater.regionCards.allowDeny.apply'),
    buildCommands(draft) {
      const mode = repeaterRequireTrimmedValue(draft, 'region_allow_mode', t('contactsView.repeater.errors.regionModeRequired'))
      const value = repeaterRequireTrimmedValue(draft, 'region_allow_name', t('contactsView.repeater.errors.regionNameRequired'))
      return [`region ${mode} ${value}`]
    },
    fields: [
      {
        key: 'region_allow_mode',
        label: t('contactsView.repeater.regionFields.mode'),
        type: 'select',
        options: [
          { value: 'allowf', label: 'allowf' },
          { value: 'denyf', label: 'denyf' },
        ],
      },
      {
        key: 'region_allow_name',
        label: t('contactsView.repeater.regionFields.regionName'),
        type: 'text',
        placeholder: t('contactsView.repeater.regionFields.allowPlaceholder'),
        maxLength: 64,
      },
    ],
  },
  {
    id: 'region-put',
    title: t('contactsView.repeater.regionCards.put.title'),
    description: t('contactsView.repeater.regionCards.put.description'),
    applyLabel: t('contactsView.repeater.regionCards.put.apply'),
    buildCommands(draft) {
      const name = repeaterRequireTrimmedValue(draft, 'region_put_name', t('contactsView.repeater.errors.regionPutNameRequired'))
      const parent = repeaterTrimmedDraftValue(draft, 'region_put_parent')
      return [parent ? `region put ${name} ${parent}` : `region put ${name}`]
    },
    fields: [
      {
        key: 'region_put_name',
        label: t('contactsView.repeater.regionFields.regionName'),
        type: 'text',
        placeholder: t('contactsView.repeater.regionFields.putPlaceholder'),
        maxLength: 64,
      },
      {
        key: 'region_put_parent',
        label: t('contactsView.repeater.regionFields.parentName'),
        type: 'text',
        placeholder: t('contactsView.repeater.regionFields.parentPlaceholder'),
        maxLength: 64,
      },
    ],
  },
  {
    id: 'region-remove',
    title: t('contactsView.repeater.regionCards.remove.title'),
    description: t('contactsView.repeater.regionCards.remove.description'),
    applyLabel: t('contactsView.repeater.regionCards.remove.apply'),
    buildCommands(draft) {
      const value = repeaterRequireTrimmedValue(draft, 'region_remove_name', t('contactsView.repeater.errors.regionRemoveRequired'))
      return [`region remove ${value}`]
    },
    fields: [
      {
        key: 'region_remove_name',
        label: t('contactsView.repeater.regionFields.regionName'),
        type: 'text',
        placeholder: t('contactsView.repeater.regionFields.removePlaceholder'),
        maxLength: 64,
      },
    ],
  },
  {
    id: 'region-actions',
    title: t('contactsView.repeater.regionCards.actions.title'),
    description: t('contactsView.repeater.regionCards.actions.description'),
    actions: [
      {
        id: 'region-save',
        label: t('contactsView.repeater.regionCards.actions.save'),
        commands: ['region save'],
      },
    ],
  },
]))

const repeaterActionCards = computed(() => ([
  {
    id: 'actions-ops',
    title: t('contactsView.repeater.actionCards.operational.title'),
    description: t('contactsView.repeater.actionCards.operational.description'),
    actions: [
      {
        id: 'action-clock-sync',
        label: t('contactsView.repeater.actionCards.operational.clockSync'),
        commands: ['clock sync'],
      },
      {
        id: 'action-clear-stats',
        label: t('contactsView.repeater.actionCards.operational.clearStats'),
        commands: ['clear stats'],
      },
      {
        id: 'action-log-start',
        label: t('contactsView.repeater.actionCards.operational.logStart'),
        commands: ['log start'],
      },
      {
        id: 'action-log-stop',
        label: t('contactsView.repeater.actionCards.operational.logStop'),
        commands: ['log stop'],
      },
      {
        id: 'action-log-erase',
        label: t('contactsView.repeater.actionCards.operational.logErase'),
        commands: ['log erase'],
      },
    ],
  },
  {
    id: 'actions-danger',
    title: t('contactsView.repeater.actionCards.danger.title'),
    description: t('contactsView.repeater.actionCards.danger.description'),
    actions: [
      {
        id: 'action-reboot',
        label: t('contactsView.repeater.actionCards.danger.reboot'),
        commands: ['reboot'],
        tone: 'danger',
        confirmMessage: t('contactsView.repeater.actionCards.danger.rebootConfirm'),
      },
      {
        id: 'action-clkreboot',
        label: t('contactsView.repeater.actionCards.danger.clkreboot'),
        commands: ['clkreboot'],
        tone: 'danger',
        confirmMessage: t('contactsView.repeater.actionCards.danger.clkrebootConfirm'),
      },
    ],
  },
  {
    id: 'actions-serial-only',
    title: t('contactsView.repeater.actionCards.serialOnly.title'),
    description: t('contactsView.repeater.actionCards.serialOnly.description'),
    actions: [
      {
        id: 'action-erase',
        label: t('contactsView.repeater.actionCards.serialOnly.eraseFilesystem'),
        notice: t('contactsView.repeater.actionCards.serialOnly.notice'),
        tone: 'danger',
      },
    ],
  },
]))

const activeRepeaterCards = computed(() => {
  if (repeaterCategoryId.value === 'basic') {
    return repeaterBasicCards.value
  }
  if (repeaterCategoryId.value === 'radio') {
    return repeaterRadioCards.value
  }
  if (repeaterCategoryId.value === 'location-gps') {
    return repeaterLocationCards.value
  }
  if (repeaterCategoryId.value === 'routing') {
    return repeaterRoutingCards.value
  }
  if (repeaterCategoryId.value === 'adverts') {
    return repeaterAdvertCards.value
  }
  if (repeaterCategoryId.value === 'bridge') {
    return repeaterBridgeCards.value
  }
  if (repeaterCategoryId.value === 'acl') {
    return repeaterAclCards.value
  }
  if (repeaterCategoryId.value === 'region') {
    return repeaterRegionCards.value
  }
  if (repeaterCategoryId.value === 'actions') {
    return repeaterActionCards.value
  }
  return []
})

const workspaceHeaderTitle = computed(() => {
  if (isGroupsMode.value) {
    return t('contactsView.workspace.groupsTitle')
  }
  if (isRepeaterLoginMode.value) {
    return t('contactsView.workspace.repeaterLoginTitle')
  }
  if (isRepeaterManagementMode.value) {
    return t('contactsView.workspace.repeaterManagementTitle')
  }
  if (selectedContact.value) {
    return contactDisplayName(selectedContact.value, t('messages.fallback.unnamedContact'))
  }
  return t('contactsView.workspace.rootTitle')
})

const workspaceHeaderSubtitle = computed(() => {
  if (isGroupsMode.value) {
    return selectedGroup.value
      ? `${t('contactsView.workspace.groupsSelectedSubtitle', { name: selectedGroup.value.name, count: selectedGroup.value.count })} · ${contactGroupsScopeLabel.value}`
      : `${t('contactsView.workspace.groupsSubtitle')} · ${contactGroupsScopeLabel.value}`
  }
  if (isRepeaterLoginMode.value) {
    return t('contactsView.workspace.repeaterLoginSubtitle')
  }
  if (isRepeaterManagementMode.value) {
    const descriptionKeyByCategoryId = {
      'location-gps': 'locationGps',
    }
    return activeRepeaterCategory.value
      ? t(`contactsView.workspace.repeaterCategoryDescriptions.${descriptionKeyByCategoryId[activeRepeaterCategory.value.id] || activeRepeaterCategory.value.id}`)
      : t('contactsView.workspace.repeaterManagementRootSubtitle')
  }
  if (selectedContact.value) {
    return [
      t(`messages.contactKinds.${classifyContactKind(selectedContact.value)}`),
      contactResidencyLabel(selectedContact.value, {
        onNode: t('contactsView.residency.onNode'),
        dbOnly: t('contactsView.residency.dbOnly'),
      }),
      formatContactRoute(selectedContact.value),
      shortContactPublicKey(selectedContact.value),
    ].filter(Boolean).join(' · ')
  }
  return t('contactsView.workspace.rootSubtitle')
})

const showMobileDetailOnly = computed(() => {
  return isShellMobile.value && isContactsRootMode.value && Boolean(selectedContact.value)
})

const showWorkspaceMobileList = computed(() => {
  return isShellMobile.value && isContactsRootMode.value && !selectedContact.value
})

const selectedContactRow = computed(() => {
  return selectedContact.value ? buildContactRow(selectedContact.value, { active: true }) : null
})

const selectedRepeaterContactRow = computed(() => {
  return selectedRepeaterContact.value ? buildContactRow(selectedRepeaterContact.value, { active: true }) : null
})

const showDesktopRepeaterLoginOverlay = computed(() => {
  return isRepeaterLoginMode.value && !isShellMobile.value
})

const selectedContactGroupTags = computed(() => {
  const tags = Array.isArray(selectedContact.value?.group_tags) ? selectedContact.value.group_tags : []
  return tags.length ? tags : [t('contactsView.groups.none')]
})

const selectedContactTrafficIndicatorText = computed(() => {
  if (!selectedContact.value) {
    return ''
  }
  const backend = selectedContact.value?.backend || {}
  const trafficAt = Number(backend?.last_public_traffic_at || selectedContact.value?.last_interaction_at || 0)
  return formatContactActivityIndicator(t('contactsView.activity.traffic'), trafficAt)
})

const selectedContactAdvertIndicatorText = computed(() => {
  if (!selectedContact.value) {
    return ''
  }
  const backend = selectedContact.value?.backend || {}
  const advertAt = Number(backend?.last_public_advert_at || selectedContact.value?.last_advert || 0)
  const advertMode = String(backend?.last_public_advert_mode || '').trim().toLowerCase()
  const suffix = advertMode ? `(${advertMode})` : ''
  return formatContactActivityIndicator(t('contactsView.activity.advert'), advertAt, suffix)
})

const selectedContactHistoryText = computed(() => {
  if (!selectedContact.value) {
    return ''
  }
  const lastMaterializedAt = Number(selectedContact.value?.last_materialized_at || 0)
  const lastRemovedAt = Number(selectedContact.value?.last_removed_from_node_at || 0)
  return t('contactsView.history.summary', {
    materialized: lastMaterializedAt ? formatAgo(lastMaterializedAt) : t('contactsView.time.never'),
    removed: lastRemovedAt ? formatAgo(lastRemovedAt) : t('contactsView.time.never'),
  })
})

const selectedContactHasDirect = computed(() => {
  return selectedContact.value ? contactHasDirectConversation(selectedContact.value) : false
})

const selectedContactDirectTitle = computed(() => {
  if (!selectedContact.value) {
    return ''
  }
  if (contactCanManageRepeater(selectedContact.value)) {
    return t('contactsView.workspace.repeaterToolingTitle')
  }
  if (contactCanDirect(selectedContact.value)) {
    return t('contactsView.workspace.directDialogTitle')
  }
  return t('contactsView.workspace.interactionTitle')
})

const selectedContactDirectDescription = computed(() => {
  if (!selectedContact.value) {
    return ''
  }
  if (contactCanDirect(selectedContact.value)) {
    return selectedContactHasDirect.value
      ? t('contactsView.direct.existingConversation')
      : t('contactsView.direct.missingConversation')
  }
  if (contactCanManageRepeater(selectedContact.value)) {
    return t('contactsView.direct.repeaterOnly')
  }
  return t('contactsView.direct.noDirect')
})

const selectedContactFavoriteActionLabel = computed(() => {
  return isContactFavorite(selectedContact.value)
    ? t('contactsView.actions.favoriteOn')
    : t('contactsView.actions.favoriteOff')
})

const repeaterContacts = computed(() => {
  return session.contacts.filter((contact) => classifyContactKind(contact) === 'repeater')
})

const routeKnownCandidates = computed(() => {
  return buildKnownRoutePublicKeys({
    selfPublicKey: session.self?.public_key,
    contacts: session.contacts,
  })
})

const routeEditorContact = computed(() => resolveContactByKey(routeEditorContactKey.value))

const routeEditorSelection = computed(() => {
  const entries = resolveContactRouteTokens(routeTokensFromInput(routeEditorInput.value), repeaterContacts.value)
  const ordered = []
  const seen = new Set()
  for (const entry of entries) {
    const publicKey = normalizePublicKey(entry.unique?.public_key)
    if (!publicKey || seen.has(publicKey)) {
      continue
    }
    seen.add(publicKey)
    ordered.push(publicKey)
  }
  return ordered
})

const routeEditorSelectedContacts = computed(() => {
  const repeaterMap = new Map(repeaterContacts.value.map((contact) => [normalizePublicKey(contact?.public_key), contact]))
  return routeEditorSelection.value
    .map((publicKey) => repeaterMap.get(publicKey) || null)
    .filter(Boolean)
})

const routeEditorResolvedEntries = computed(() => {
  return resolveContactRouteTokens(routeTokensFromInput(routeEditorInput.value), repeaterContacts.value).map((entry) => {
    if (entry.unique) {
      const publicKey = normalizePublicKey(entry.unique?.public_key)
      return {
        token: entry.token,
        unique: true,
        publicKey,
        title: contactDisplayName(entry.unique, t('messages.fallback.unnamedContact')),
        shortKey: shortContactPublicKey(entry.unique),
        note: entry.token,
        selected: routeEditorSelection.value.includes(publicKey),
      }
    }
    return {
      token: entry.token,
      unique: false,
      note: entry.matches.length
        ? t('contactsView.routeEditor.ambiguousToken', { token: entry.token, count: entry.matches.length })
        : t('contactsView.routeEditor.missingToken', { token: entry.token }),
    }
  })
})

const routeEditorMapRepeaters = computed(() => {
  return repeaterContacts.value
    .filter((contact) => contactHasCoordinates(contact))
    .map((contact) => ({
      lat: Number(contact.lat),
      lon: Number(contact.lon),
      kind: 'repeater',
      label: contactDisplayName(contact, t('messages.fallback.unnamedContact')),
      publicKey: normalizePublicKey(contact.public_key),
      selected: routeEditorSelection.value.includes(normalizePublicKey(contact.public_key)),
    }))
})

const routeEditorRoutePoints = computed(() => {
  const points = []
  if (contactHasCoordinates(session.self)) {
    points.push({
      lat: Number(session.self.lat),
      lon: Number(session.self.lon),
      kind: 'self',
      label: String(session.self?.name || t('common.unknownNode')),
      publicKey: normalizePublicKey(session.self?.public_key),
    })
  }
  for (const contact of routeEditorSelectedContacts.value) {
    if (!contactHasCoordinates(contact)) {
      continue
    }
    points.push({
      lat: Number(contact.lat),
      lon: Number(contact.lon),
      kind: 'repeater',
      label: contactDisplayName(contact, t('messages.fallback.unnamedContact')),
      publicKey: normalizePublicKey(contact.public_key),
      selected: true,
    })
  }
  if (routeEditorContact.value && contactHasCoordinates(routeEditorContact.value)) {
    points.push({
      lat: Number(routeEditorContact.value.lat),
      lon: Number(routeEditorContact.value.lon),
      kind: 'contact',
      label: contactDisplayName(routeEditorContact.value, t('messages.fallback.unnamedContact')),
      publicKey: normalizePublicKey(routeEditorContact.value.public_key),
    })
  }
  return points
})

const routeEditorSummaryText = computed(() => {
  const traceStatus = String(routeTraceResult.value?.status || '')
  if (traceStatus === 'queued') {
    return t('maps.trace.status.queued')
  }
  if (traceStatus === 'running' || routeTraceBusy.value) {
    return t('maps.trace.status.running')
  }
  if (traceStatus === 'cancelled') {
    return t('maps.trace.status.cancelled')
  }
  if (traceStatus === 'error') {
    return String(routeTraceResult.value?.error || t('maps.trace.status.error'))
  }
  if (traceStatus === 'completed' && routeTraceResult.value?.success) {
    return t('maps.trace.status.success', { hops: Number(routeTraceResult.value?.hop_count || 0) })
  }
  if (traceStatus === 'completed' && routeTraceResult.value && !routeTraceResult.value.success) {
    return t('maps.trace.status.failed', { hop: Number(routeTraceResult.value?.failure_at_hop || 0) || '?' })
  }
  if (!routeEditorSelectedContacts.value.length) {
    return t('contactsView.routeEditor.summaryEmpty')
  }
  return t('contactsView.routeEditor.summarySelected', {
    route: routeEditorSelectedContacts.value.map((contact) => shortContactPublicKey(contact)).join(' -> '),
  })
})

const routeTraceStepModels = computed(() => {
  const steps = Array.isArray(routeTraceResult.value?.steps) ? routeTraceResult.value.steps : []
  return steps.map((step) => {
    const prefixHops = Number(step?.prefix_hops || 0) || 0
    const pending = Boolean(step?.pending)
    const success = !pending && Boolean(step?.success)
    const failed = !pending && !success
    const participants = routeEditorSelectedContacts.value.slice(0, prefixHops)
    const participantLabel = participants.length
      ? participants.map((contact) => shortContactPublicKey(contact)).join(' → ')
      : t('maps.trace.step.unknownPath')
    const roundTripMs = Number(step?.trace?.round_trip_ms || 0) || 0
    const segmentMs = Number(step?.segment_ms_estimate || 0) || 0
    const finalSnr = step?.trace?.final_snr
    const hopLabels = Array.isArray(step?.trace?.path_hops)
      ? step.trace.path_hops
        .map((hop) => String(hop?.hash_hex || '').trim())
        .filter(Boolean)
      : []
    return {
      key: `step:${prefixHops}`,
      prefixHops,
      pending,
      success,
      failed,
      participantLabel,
      meta: pending
        ? t('maps.trace.step.pending')
        : success
          ? t('maps.trace.step.successMeta', {
            roundTripMs,
            segmentMs: segmentMs || roundTripMs,
            finalSnr: finalSnr == null ? 'n/a' : Number(finalSnr).toFixed(1),
          })
          : t('maps.trace.step.failedMeta'),
      hopLabels,
    }
  })
})

const routeTraceLineBadges = computed(() => {
  const tracedSegmentCount = routeEditorSelectedContacts.value.length
  if (!tracedSegmentCount || !routeTraceResult.value) {
    return []
  }
  const steps = Array.isArray(routeTraceResult.value.steps) ? routeTraceResult.value.steps : []
  if (!steps.length) {
    return []
  }
  if (routeTraceResult.value.sequential) {
    return Array.from({ length: tracedSegmentCount }, (_, segmentIndex) => {
      const step = steps.find((entry) => Number(entry?.prefix_hops || 0) === segmentIndex + 1) || null
      if (!step) {
        return null
      }
      if (step.pending) {
        return {
          segmentIndex,
          failed: false,
          txLabel: 'TX…',
          rxLabel: 'RX…',
        }
      }
      if (!step.success || !step.trace) {
        return {
          segmentIndex,
          failed: true,
          txLabel: 'TX timeout',
          rxLabel: 'RX none',
        }
      }
      const pathHops = Array.isArray(step.trace.path_hops) ? step.trace.path_hops : []
      const txSnr = pathHops.length ? pathHops[pathHops.length - 1]?.snr : null
      const segmentMs = Math.max(0, Number(step.segment_ms_estimate || step.trace.round_trip_ms || 0))
      return {
        segmentIndex,
        failed: false,
        txLabel: `TX ~${segmentMs}ms${txSnr != null ? ` · ${Number(txSnr).toFixed(1)}dB` : ''}`,
        rxLabel: `RX ~${segmentMs}ms${step.trace.final_snr != null ? ` · ${Number(step.trace.final_snr).toFixed(1)}dB` : ''}`,
      }
    }).filter(Boolean)
  }
  const step = steps[steps.length - 1] || null
  if (step?.pending) {
    return Array.from({ length: tracedSegmentCount }, (_, segmentIndex) => ({
      segmentIndex,
      failed: false,
      txLabel: 'TX…',
      rxLabel: 'RX…',
    }))
  }
  if (!step || !step.trace || !step.success) {
    return []
  }
  const averageMs = tracedSegmentCount > 0
    ? Math.max(0, Math.round(Number(step.trace.round_trip_ms || step.segment_ms_estimate || 0) / tracedSegmentCount))
    : 0
  const pathHops = Array.isArray(step.trace.path_hops) ? step.trace.path_hops : []
  return Array.from({ length: tracedSegmentCount }, (_, segmentIndex) => ({
    segmentIndex,
    failed: false,
    txLabel: `TX ~${averageMs}ms${pathHops[segmentIndex]?.snr != null ? ` · ${Number(pathHops[segmentIndex].snr).toFixed(1)}dB` : ''}`,
    rxLabel: `RX ~${averageMs}ms${step.trace.final_snr != null ? ` · ${Number(step.trace.final_snr).toFixed(1)}dB` : ''}`,
  }))
})

const routeEditorModel = computed(() => ({
  open: routeEditorOpen.value && Boolean(routeEditorContact.value),
  contactTitle: routeEditorContact.value
    ? contactDisplayName(routeEditorContact.value, t('messages.fallback.unnamedContact'))
    : '',
  inputValue: routeEditorInput.value,
  resolvedEntries: routeEditorResolvedEntries.value,
  selectedContacts: routeEditorSelectedContacts.value,
  mapRepeaters: routeEditorMapRepeaters.value,
  routePoints: routeEditorRoutePoints.value,
  canResetStoredRoute: Boolean(routeEditorContact.value && buildStoredContactRouteHops(routeEditorContact.value).length),
  canStartTrace: routeEditorSelectedContacts.value.length > 0 && !routeTraceBusy.value,
  canCancelTrace: routeTraceBusy.value,
  summaryText: routeEditorSummaryText.value,
  traceSequential: routeTraceSequential.value,
  traceBusy: routeTraceBusy.value,
  traceResult: routeTraceResult.value,
  traceStepModels: routeTraceStepModels.value,
  traceLineBadges: routeTraceLineBadges.value,
  traceLegendVisible: Boolean(routeTraceLineBadges.value.length || routeTraceResult.value?.success),
  traceFailureVisible: Boolean(routeTraceResult.value && !routeTraceResult.value.success && routeTraceResult.value.failure_visible !== false),
}))

const repeaterGeoSheetModel = computed(() => ({
  open: repeaterGeoSheetOpen.value && Boolean(selectedRepeaterContact.value),
  targetTitle: selectedRepeaterContact.value
    ? contactDisplayName(selectedRepeaterContact.value, t('messages.fallback.unnamedContact'))
    : '',
  selfPoint: contactHasCoordinates(session.self)
    ? {
      lat: Number(session.self.lat),
      lon: Number(session.self.lon),
      label: String(session.self?.name || t('common.unknownNode')),
    }
    : null,
  repeaterPoint: selectedRepeaterContact.value && contactHasCoordinates(selectedRepeaterContact.value)
    ? {
      lat: Number(selectedRepeaterContact.value.lat),
      lon: Number(selectedRepeaterContact.value.lon),
      label: contactDisplayName(selectedRepeaterContact.value, t('messages.fallback.unnamedContact')),
    }
    : null,
}))

async function ensureContactsLoaded({ refresh = false } = {}) {
  if (!session.connected || contactsLoading.value) {
    return
  }
  if (!refresh && session.contacts.length) {
    return
  }
  contactsLoading.value = true
  try {
    await session.loadContacts({ refresh })
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('contactsView.status.loadFailed')), true)
  } finally {
    contactsLoading.value = false
  }
}

async function ensureGroupsLoaded() {
  if (!session.connected || groupsLoading.value) {
    return
  }
  groupsLoading.value = true
  try {
    const params = new URLSearchParams()
    const config = session.configBody()
    if (config.port) {
      params.set('port', String(config.port))
      params.set('baudrate', String(config.baudrate))
    }
    const payload = await session.api(`/api/contact-groups${params.toString() ? `?${params.toString()}` : ''}`)
    applyContactGroupsPayload(payload)
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('contactsView.status.groupsLoadFailed')), true)
  } finally {
    groupsLoading.value = false
  }
}

function getCurrentContactGroupScopeRequest() {
  const config = session.configBody()
  return {
    port: String(config.port || ''),
    baudrate: Number(config.baudrate || 115200),
  }
}

function patchContactsWithEffectiveGroups(effectiveGroups) {
  const groupsMap = effectiveGroups && typeof effectiveGroups === 'object' ? effectiveGroups : {}
  const contacts = Array.isArray(session.contacts) ? session.contacts : []
  if (!contacts.length) {
    return
  }
  const nextContacts = contacts.map((contact) => {
    const publicKey = normalizePublicKey(contact?.public_key)
    const groupTags = Object.entries(groupsMap)
      .filter(([, members]) => Array.isArray(members) && members.includes(publicKey))
      .map(([name]) => name)
      .sort((left, right) => {
        const leftFav = left === 'favorites'
        const rightFav = right === 'favorites'
        if (leftFav !== rightFav) {
          return leftFav ? -1 : 1
        }
        return left.localeCompare(right, 'ru')
      })
    return {
      ...contact,
      group_tags: groupTags,
    }
  })
  session.patchSessionSnapshotFields({
    active: session.connected,
    contacts: nextContacts,
    contacts_count: nextContacts.length,
  })
}

function applyContactGroupsPayload(payload) {
  groupsPayload.value = {
    groups: payload?.groups || {},
    effective_groups: payload?.effective_groups || {},
    scope: payload?.scope || null,
  }
  patchContactsWithEffectiveGroups(groupsPayload.value.effective_groups)
}

function buildRootQuery(nextContactKey = '') {
  const nextQuery = { ...route.query }
  if (nextContactKey) {
    nextQuery.contact = nextContactKey
  } else {
    delete nextQuery.contact
  }
  return nextQuery
}

async function selectContact(contactKey = '') {
  if (!isContactsRootMode.value) {
    return
  }
  if (contactKey) {
    contactsToolsCollapsed.value = true
    closeTransientContactsControls()
  } else {
    closeTransientContactsControls()
  }
  await router.replace({
    path: '/contacts',
    query: buildRootQuery(contactKey),
  })
}

async function openGroupsRoute(groupName = '') {
  const query = groupName ? { group: groupName } : {}
  await router.push({
    path: '/contacts/groups',
    query,
  })
}

async function selectGroup(groupName = '') {
  if (!isGroupsMode.value) {
    return
  }
  const nextQuery = { ...route.query }
  if (groupName) {
    nextQuery.group = groupName
  } else {
    delete nextQuery.group
  }
  await router.replace({
    path: '/contacts/groups',
    query: nextQuery,
  })
}

async function openRootContacts() {
  await router.push({
    path: '/contacts',
    query: selectedContact.value ? buildRootQuery(selectedRouteContactKey.value) : {},
  })
}

async function openRepeaterCategory(categoryId = 'basic') {
  if (!selectedRouteContactKey.value) {
    return
  }
  await router.replace({
    path: `/contacts/repeater/${encodeURIComponent(selectedRouteContactKey.value)}/${encodeURIComponent(categoryId)}`,
    query: {},
  })
}

async function openRepeaterManagementRoot() {
  if (!selectedRouteContactKey.value) {
    return
  }
  await router.replace({
    path: `/contacts/repeater/${encodeURIComponent(selectedRouteContactKey.value)}`,
    query: {},
  })
}

function openRepeaterGeoSheet() {
  if (!selectedRepeaterContact.value || !selectedRepeaterManagementDraft.value) {
    return
  }
  repeaterGeoSheetOpen.value = true
}

function closeRepeaterGeoSheet() {
  repeaterGeoSheetOpen.value = false
}

function applyRepeaterGeoFromMap(payload) {
  const draft = selectedRepeaterManagementDraft.value
  if (!draft) {
    return
  }
  draft.location_lat = Number(payload?.lat).toFixed(6)
  draft.location_lon = Number(payload?.lon).toFixed(6)
  closeRepeaterGeoSheet()
}

function toggleContactsControl(kind) {
  if (effectiveToolsCollapsed.value) {
    return
  }
  openContactsControl.value = openContactsControl.value === kind ? null : kind
}

function toggleContactsToolsCollapsed() {
  if (!isShellMobile.value && !selectedContact.value) {
    return
  }
  contactsToolsCollapsed.value = !contactsToolsCollapsed.value
  if (contactsToolsCollapsed.value) {
    closeTransientContactsControls()
  }
}

function setContactsOrder(value) {
  contactsOrder.value = normalizeContactsOrder(value)
  closeTransientContactsControls()
}

function setContactsFilter(value) {
  contactsFilter.value = normalizeContactsFilter(value)
  closeTransientContactsControls()
}

function resetContactsFilters() {
  contactsSearchTerm.value = ''
  contactsOrder.value = 'heard-recently'
  contactsFilter.value = 'all'
  selectedContactGroupFilter.value = 'all'
  closeTransientContactsControls()
}

async function setSelectedContactGroupFilter(value) {
  const normalized = normalizeContactGroupFilter(value)
  if (normalized === '__add_group__') {
    closeTransientContactsControls()
    openCreateGroupDialog({ navigateToGroups: false })
    return
  }
  selectedContactGroupFilter.value = normalized
}

function onListItemKeydown(event, contactKey) {
  if (event.key !== 'Enter' && event.key !== ' ') {
    return
  }
  event.preventDefault()
  selectContact(contactKey)
}

async function openContactOnMap(contact) {
  if (!contactHasCoordinates(contact)) {
    return
  }
  const lat = Number(contact?.lat)
  const lon = Number(contact?.lon)
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return
  }
  await router.push({
    path: '/maps',
    query: {
      focus_lat: String(lat),
      focus_lon: String(lon),
      focus_key: normalizePublicKey(contact?.public_key),
      focus_label: contactDisplayName(contact, t('messages.fallback.unnamedContact')),
    },
  })
}

async function importContactFromClipboard() {
  if (!navigator?.clipboard?.readText) {
    session.setStatus(t('contactsView.status.clipboardUnavailable'), true)
    return
  }
  try {
    const uri = String(await navigator.clipboard.readText()).trim()
    if (!uri || !uri.startsWith('meshcore://')) {
      session.setStatus(t('contactsView.status.invalidContactUri'), true)
      return
    }
    await session.api('/api/contacts/import', {
      method: 'POST',
      body: JSON.stringify({
        ...session.configBody(),
        uri,
      }),
    })
    await ensureContactsLoaded({ refresh: true })
    await ensureGroupsLoaded()
    session.setStatus(t('contactsView.status.imported'))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('contactsView.status.importFailed')), true)
  }
}

async function exportSelfAdvert() {
  if (!navigator?.clipboard?.writeText) {
    session.setStatus(t('contactsView.status.clipboardUnavailable'), true)
    return
  }
  try {
    const payload = await session.api('/api/contacts/export-self', {
      method: 'POST',
      body: JSON.stringify(session.configBody()),
    })
    const uri = String(payload?.uri || '').trim()
    if (!uri) {
      session.setStatus(t('contactsView.status.exportFailed'), true)
      return
    }
    await navigator.clipboard.writeText(uri)
    session.setStatus(t('contactsView.status.exported'))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('contactsView.status.exportFailed')), true)
  }
}

function closeGroupNameDialog() {
  groupNameDialog.value = {
    open: false,
    mode: 'create',
    value: '',
    navigateToGroups: false,
  }
}

function openCreateGroupDialog({ navigateToGroups = false } = {}) {
  groupNameDialog.value = {
    open: true,
    mode: 'create',
    value: '',
    navigateToGroups,
  }
}

function openRenameGroupDialog() {
  if (!selectedGroup.value || selectedGroupIsFavorites.value) {
    return
  }
  groupNameDialog.value = {
    open: true,
    mode: 'rename',
    value: selectedGroup.value.name,
    navigateToGroups: true,
  }
}

function closeConfirmDialog() {
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

function openConfirmDialog(options = {}) {
  confirmDialog.value = {
    open: true,
    title: String(options.title || t('common.confirmation')),
    message: String(options.message || ''),
    note: String(options.note || ''),
    confirmLabel: String(options.confirmLabel || t('common.confirm')),
    confirmDisabled: false,
    action: typeof options.action === 'function' ? options.action : null,
  }
}

async function submitConfirmDialog() {
  const action = confirmDialog.value?.action
  closeConfirmDialog()
  if (typeof action === 'function') {
    await action()
  }
}

async function createContactGroup(name, { navigateToGroups = false } = {}) {
  const normalized = normalizeGroupName(name)
  if (!normalized) {
    return
  }
  if (normalized.toLowerCase() === 'all') {
    session.setStatus(t('contactsView.status.groupNameReservedAll'), true)
    return
  }
  if (normalized.toLowerCase() === 'favorites') {
    session.setStatus(t('contactsView.status.groupNameReservedFavorites'), true)
    return
  }
  if (groupEntries.value.some((entry) => entry.name === normalized)) {
    session.setStatus(t('contactsView.status.groupAlreadyExists'), true)
    return
  }
  const payload = await session.api('/api/contact-groups/save', {
    method: 'POST',
    body: JSON.stringify({
      ...getCurrentContactGroupScopeRequest(),
      group_name: normalized,
      members: [],
    }),
  })
  applyContactGroupsPayload(payload)
  closeGroupNameDialog()
  if (navigateToGroups || isGroupsMode.value) {
    await openGroupsRoute(normalized)
  }
  session.setStatus(t('contactsView.status.groupCreated', { name: normalized }))
}

async function renameSelectedGroup(nextName) {
  const current = normalizeGroupName(selectedGroup.value?.name)
  const normalized = normalizeGroupName(nextName)
  if (!current || !selectedGroup.value) {
    session.setStatus(t('contactsView.status.groupNotFound'), true)
    return
  }
  if (!normalized || normalized === current) {
    closeGroupNameDialog()
    return
  }
  if (normalized.toLowerCase() === 'all') {
    session.setStatus(t('contactsView.status.groupNameReservedAll'), true)
    return
  }
  if (normalized.toLowerCase() === 'favorites') {
    session.setStatus(t('contactsView.status.groupNameReservedFavorites'), true)
    return
  }
  if (groupEntries.value.some((entry) => entry.name === normalized)) {
    session.setStatus(t('contactsView.status.groupAlreadyExists'), true)
    return
  }
  const payload = await session.api('/api/contact-groups/rename', {
    method: 'POST',
    body: JSON.stringify({
      ...getCurrentContactGroupScopeRequest(),
      old_name: current,
      new_name: normalized,
    }),
  })
  applyContactGroupsPayload(payload)
  if (selectedContactGroupFilter.value === current) {
    selectedContactGroupFilter.value = normalized
  }
  closeGroupNameDialog()
  await openGroupsRoute(normalized)
  session.setStatus(t('contactsView.status.groupRenamed', { name: normalized }))
}

async function submitGroupNameDialog() {
  if (!groupNameDialog.value.open) {
    return
  }
  if (groupNameDialog.value.mode === 'rename') {
    await renameSelectedGroup(groupNameDialog.value.value)
    return
  }
  await createContactGroup(groupNameDialog.value.value, {
    navigateToGroups: Boolean(groupNameDialog.value.navigateToGroups),
  })
}

function openDeleteSelectedGroupConfirm() {
  if (!selectedGroup.value || selectedGroupIsFavorites.value) {
    return
  }
  openConfirmDialog({
    title: t('contactsView.actions.deleteGroup'),
    message: t('contactsView.confirmations.deleteGroup.message', { name: selectedGroup.value.name }),
    note: t('contactsView.confirmations.deleteGroup.note'),
    confirmLabel: t('contactsView.actions.deleteGroup'),
    action: deleteSelectedGroup,
  })
}

async function deleteSelectedGroup() {
  const current = normalizeGroupName(selectedGroup.value?.name)
  if (!current || !selectedGroup.value) {
    session.setStatus(t('contactsView.status.groupNotFound'), true)
    return
  }
  if (selectedGroupIsFavorites.value) {
    session.setStatus(t('contactsView.status.groupNameReservedFavorites'), true)
    return
  }
  const payload = await session.api('/api/contact-groups/delete', {
    method: 'POST',
    body: JSON.stringify({
      ...getCurrentContactGroupScopeRequest(),
      group_name: current,
    }),
  })
  applyContactGroupsPayload(payload)
  if (selectedContactGroupFilter.value === current) {
    selectedContactGroupFilter.value = 'all'
  }
  await selectGroup('')
  session.setStatus(t('contactsView.status.groupDeleted', { name: current }))
}

async function applyContactsActionResult(data, successMessage) {
  const nextContacts = Array.isArray(data?.contacts) ? data.contacts : null
  if (nextContacts) {
    session.patchSessionSnapshotFields({
      active: session.connected,
      contacts: nextContacts,
      contacts_count: nextContacts.length,
      contact_summary: data?.contact_summary ?? session.sessionSnapshot?.contact_summary ?? null,
    })
  } else {
    await ensureContactsLoaded({ refresh: true })
  }
  await ensureGroupsLoaded()
  if (data?.materialized_on_node) {
    session.setStatus(`${successMessage} ${t('contactsView.status.materializedSuffix')}`)
    return
  }
  session.setStatus(successMessage)
}

async function runSelectedContactAction(path, body, successMessage) {
  if (!selectedContact.value) {
    session.setStatus(t('contactsView.status.selectContactFirst'), true)
    return
  }
  const data = await session.api(path, {
    method: 'POST',
    body: JSON.stringify({
      ...session.configBody(),
      public_key: selectedContact.value.public_key,
      ...(body || {}),
    }),
  })
  const uri = String(data?.uri || '').trim()
  if (uri) {
    if (!navigator?.clipboard?.writeText) {
      throw new Error(t('contactsView.status.clipboardUnavailable'))
    }
    await navigator.clipboard.writeText(uri)
  }
  await applyContactsActionResult(data, successMessage)
}

async function deleteNodeContacts(mode = 'non-favorites-no-direct') {
  const data = await session.api('/api/contacts/delete', {
    method: 'POST',
    body: JSON.stringify({
      ...session.configBody(),
      mode,
      protect_favorites: true,
    }),
  })
  const nextContacts = Array.isArray(data?.contacts) ? data.contacts : null
  if (nextContacts) {
    session.patchSessionSnapshotFields({
      active: session.connected,
      contacts: nextContacts,
      contacts_count: nextContacts.length,
      contact_summary: data?.contact_summary ?? session.sessionSnapshot?.contact_summary ?? null,
    })
  } else {
    await ensureContactsLoaded({ refresh: true })
  }
  await ensureGroupsLoaded()
  session.setStatus(
    mode === 'non-favorites-no-direct'
      ? t('contactsView.status.nodeCleanupDone', { removed: Number(data?.removed || 0) })
      : t('contactsView.status.nodeCleanupGeneric', {
        removed: Number(data?.removed || 0),
        remaining: Number(data?.remaining || 0),
      }),
  )
}

function openNodeCleanupConfirm() {
  openConfirmDialog({
    title: t('contactsView.actions.nodeCleanup'),
    message: t('contactsView.confirmations.nodeCleanup.message'),
    note: t('contactsView.confirmations.nodeCleanup.note'),
    confirmLabel: t('contactsView.actions.nodeCleanup'),
    action: () => deleteNodeContacts('non-favorites-no-direct'),
  })
}

function openGroupEditor() {
  if (!selectedGroup.value) {
    session.setStatus(t('contactsView.status.groupSelectFirst'), true)
    return
  }
  groupEditorSelection.value = Array.isArray(selectedGroup.value.members) ? [...selectedGroup.value.members] : []
  groupEditorSearchTerm.value = ''
  groupEditorOrder.value = 'heard-recently'
  groupEditorFilter.value = 'all'
  groupEditorBusy.value = false
  groupEditorOpen.value = true
}

function closeGroupEditor() {
  groupEditorOpen.value = false
  groupEditorBusy.value = false
  groupEditorSelection.value = []
}

function toggleGroupEditorMember(publicKey, checked) {
  const normalized = normalizePublicKey(publicKey)
  const selected = new Set(groupEditorSelection.value.map((entry) => normalizePublicKey(entry)))
  if (checked) {
    selected.add(normalized)
  } else {
    selected.delete(normalized)
  }
  groupEditorSelection.value = [...selected]
}

function selectAllVisibleGroupEditorContacts() {
  const selected = new Set(groupEditorSelection.value.map((entry) => normalizePublicKey(entry)))
  for (const contact of groupEditorVisibleContacts.value) {
    selected.add(contact.key)
  }
  groupEditorSelection.value = [...selected]
}

function invertVisibleGroupEditorContacts() {
  const selected = new Set(groupEditorSelection.value.map((entry) => normalizePublicKey(entry)))
  for (const contact of groupEditorVisibleContacts.value) {
    if (selected.has(contact.key)) {
      selected.delete(contact.key)
    } else {
      selected.add(contact.key)
    }
  }
  groupEditorSelection.value = [...selected]
}

function clearGroupEditorSelection() {
  groupEditorSelection.value = []
}

function setGroupEditorOrder(value) {
  groupEditorOrder.value = normalizeContactsOrder(value)
}

function setGroupEditorFilter(value) {
  groupEditorFilter.value = normalizeContactsFilter(value)
}

async function saveGroupEditorSelection() {
  if (!selectedGroup.value) {
    session.setStatus(t('contactsView.status.groupSelectFirst'), true)
    return
  }
  groupEditorBusy.value = true
  try {
    if (selectedGroupIsFavorites.value) {
      const config = session.configBody()
      if (!session.connected || !config.port) {
        throw new Error(t('contactsView.status.groupFavoritesRequiresConnection'))
      }
      const payload = await session.api('/api/contact-groups/favorites-sync', {
        method: 'POST',
        body: JSON.stringify({
          ...config,
          members: groupEditorSelection.value,
        }),
      })
      if (Array.isArray(payload?.contacts)) {
        session.patchSessionSnapshotFields({
          active: session.connected,
          contacts: payload.contacts,
          contacts_count: payload.contacts.length,
          contact_summary: payload.contact_summary ?? session.sessionSnapshot?.contact_summary ?? null,
        })
      } else {
        await ensureContactsLoaded({ refresh: true })
      }
      await ensureGroupsLoaded()
      session.setStatus(t('contactsView.status.groupFavoritesSynced'))
    } else {
      const payload = await session.api('/api/contact-groups/save', {
        method: 'POST',
        body: JSON.stringify({
          ...getCurrentContactGroupScopeRequest(),
          group_name: selectedGroup.value.name,
          members: groupEditorSelection.value,
        }),
      })
      applyContactGroupsPayload(payload)
      session.setStatus(t('contactsView.status.groupMembersSaved', {
        name: selectedGroup.value.name,
        count: groupEditorSelection.value.length,
      }))
    }
    closeGroupEditor()
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('contactsView.status.groupSaveFailed')), true)
  } finally {
    groupEditorBusy.value = false
  }
}

async function openMessagesDirect(publicKey, { focusComposer = false } = {}) {
  const normalizedKey = normalizePublicKey(publicKey)
  if (!normalizedKey) {
    return
  }
  await router.push({
    path: '/messages',
    query: {
      contact: normalizedKey,
      ...(focusComposer ? { compose: '1' } : {}),
    },
  })
}

async function openSelectedDirectConversation() {
  if (!selectedContact.value || !contactCanDirect(selectedContact.value)) {
    session.setStatus(t('contactsView.status.directUnavailable'), true)
    return
  }
  await openMessagesDirect(selectedContact.value.public_key)
}

async function startSelectedDirectConversation() {
  if (!selectedContact.value || !contactCanDirect(selectedContact.value)) {
    session.setStatus(t('contactsView.status.directUnavailable'), true)
    return
  }
  await openMessagesDirect(selectedContact.value.public_key, { focusComposer: true })
  session.setStatus(t('contactsView.status.directComposerOpened', {
    target: contactDisplayName(selectedContact.value, t('messages.fallback.unnamedContact')),
  }))
}

async function openSelectedRepeaterManagement() {
  if (!selectedContact.value || !contactCanManageRepeater(selectedContact.value)) {
    return
  }
  const key = normalizePublicKey(selectedContact.value.public_key)
  if (!key) {
    return
  }
  repeaterLoginSavedAuthRetryBlockKey.value = ''
  clearRepeaterLoginNotice()
  await router.push({
    path: `/contacts/repeater-login/${encodeURIComponent(key)}`,
    query: {},
  })
}

async function closeRepeaterLogin() {
  repeaterLoginBusy.value = false
  repeaterLoginPassword.value = ''
  repeaterLoginRememberAuth.value = false
  repeaterLoginSavedAuthBypassKey.value = ''
  repeaterLoginSavedAuthRetryBlockKey.value = ''
  clearRepeaterLoginNotice()
  await router.push({
    path: '/contacts',
    query: buildRootQuery(selectedRouteContactKey.value),
  })
}

async function submitRepeaterLogin() {
  const contact = selectedRepeaterContact.value
  if (!contact) {
    session.setStatus(t('contactsView.status.repeaterTargetMissing'), true)
    return
  }
  const config = session.configBody()
  if (!config.port) {
    session.setStatus(t('contactsView.status.repeaterSerialRequired'), true)
    return
  }
  const publicKey = normalizePublicKey(contact.public_key)
  const useSavedAuth = repeaterLoginUsesSavedAuth.value
  const password = useSavedAuth ? '' : String(repeaterLoginPassword.value || '').trim()
  if (!useSavedAuth && !password) {
    session.setStatus(t('contactsView.status.repeaterPasswordRequired'), true)
    return
  }
  repeaterLoginBusy.value = true
  session.suppressTransientDisconnect(30000)
  clearRepeaterLoginNotice()
  try {
    const requestBody = {
      ...config,
      public_key: contact.public_key,
      remember_auth: !useSavedAuth && repeaterLoginRememberAuth.value,
    }
    if (!useSavedAuth) {
      requestBody.password = password
    }
    const payload = await session.api('/api/repeater/login', {
      method: 'POST',
      body: JSON.stringify(requestBody),
    })
    repeaterManagementPassword.value = useSavedAuth ? '' : password
    repeaterLoginPassword.value = ''
    repeaterLoginRememberAuth.value = false
    repeaterLoginSavedAuthBypassKey.value = ''
    repeaterLoginSavedAuthRetryBlockKey.value = ''
    if (payload?.contact) {
      patchRepeaterContact(publicKey, payload.contact)
    } else {
      patchRepeaterContact(publicKey, {})
    }
    patchRepeaterContact(publicKey, {
      is_favorite: true,
      group_tags: Array.from(new Set([...(Array.isArray(contact?.group_tags) ? contact.group_tags : []), 'favorites'])),
      repeater_auth_saved: Boolean(useSavedAuth || requestBody.remember_auth),
      backend: {
        ...(contact?.backend || {}),
        is_favorite: true,
        repeater_auth_saved: Boolean(useSavedAuth || requestBody.remember_auth),
        repeater_auth_saved_at: Boolean(useSavedAuth || requestBody.remember_auth)
          ? Math.floor(Date.now() / 1000)
          : Number(contact?.backend?.repeater_auth_saved_at || 0),
      },
    })
    await router.push({
      path: `/contacts/repeater/${encodeURIComponent(publicKey)}/basic`,
      query: {},
    })
    session.setStatus([
      t('contactsView.status.repeaterPasswordConfirmed', {
        target: contactDisplayName(contact, t('messages.fallback.unnamedContact')),
      }),
      payload?.materialized_on_node ? t('contactsView.status.materializedSuffix') : '',
    ].filter(Boolean).join(' '))
  } catch (error) {
    if (useSavedAuth) {
      if (!isRepeaterLoginTimeoutError(error)) {
        repeaterLoginSavedAuthBypassKey.value = publicKey
      }
    }
    setRepeaterLoginErrorNotice(error, { useSavedAuth })
  } finally {
    repeaterLoginBusy.value = false
    session.suppressTransientDisconnect(12000)
  }
}

function patchRepeaterContact(publicKey, patch = {}) {
  const normalized = normalizePublicKey(publicKey)
  if (!normalized) {
    return
  }
  const nextContacts = session.contacts.map((entry) => {
    const currentKey = normalizePublicKey(entry?.public_key)
    if (currentKey !== normalized) {
      return entry
    }
    const nextBackend = patch?.backend || entry?.backend
      ? {
          ...(entry?.backend || {}),
          ...(patch?.backend || {}),
        }
      : undefined
    const nextCompanion = patch?.companion || entry?.companion
      ? {
          ...(entry?.companion || {}),
          ...(patch?.companion || {}),
        }
      : undefined
    return {
      ...entry,
      ...patch,
      ...(nextBackend ? { backend: nextBackend } : {}),
      ...(nextCompanion ? { companion: nextCompanion } : {}),
    }
  })
  session.patchSessionSnapshotFields({
    active: session.connected,
    contacts: nextContacts,
    contacts_count: nextContacts.length,
  })
}

function touchContactActivityByPrefix(prefix, patch = {}) {
  const normalizedPrefix = getContactPrefix(prefix)
  if (!normalizedPrefix) {
    return false
  }
  const nowEpoch = Math.floor(Date.now() / 1000)
  return session.updateContactSnapshotByPrefix(normalizedPrefix, {
    last_interaction_at: nowEpoch,
    backend: {
      last_interaction_at: nowEpoch,
      last_public_traffic_at: nowEpoch,
      ...((patch && patch.backend) || {}),
    },
    ...(patch || {}),
  })
}

function touchContactActivityByPublicKey(publicKey, patch = {}) {
  const normalizedPublicKey = normalizePublicKey(publicKey)
  if (!normalizedPublicKey) {
    return false
  }
  return touchContactActivityByPrefix(normalizedPublicKey, patch)
}

async function deleteSelectedRepeaterAuth() {
  const contact = selectedContact.value
  if (!contact || !contactCanManageRepeater(contact)) {
    session.setStatus(t('contactsView.status.repeaterTargetMissing'), true)
    return
  }
  const payload = await session.api('/api/repeater/auth/delete', {
    method: 'POST',
    body: JSON.stringify({
      ...session.configBody(),
      public_key: contact.public_key,
    }),
  })
  if (payload?.contact) {
    patchRepeaterContact(contact.public_key, payload.contact)
  } else {
    patchRepeaterContact(contact.public_key, {
      repeater_auth_saved: false,
      repeater_auth_saved_at: 0,
      backend: {
        ...(contact?.backend || {}),
        repeater_auth_saved: false,
        repeater_auth_saved_at: 0,
      },
    })
  }
  repeaterManagementPassword.value = ''
  repeaterLoginPassword.value = ''
  repeaterLoginRememberAuth.value = false
  repeaterLoginSavedAuthBypassKey.value = ''
  repeaterLoginSavedAuthRetryBlockKey.value = ''
  clearRepeaterLoginNotice()
  session.setStatus(t('contactsView.status.repeaterAuthDeleted'))
}

async function runRepeaterCliBatch(commands, successMessage, busyKey) {
  const contact = selectedRepeaterContact.value
  if (!contact || !contactCanManageRepeater(contact)) {
    throw new Error(t('contactsView.status.repeaterTargetMissing'))
  }
  const config = session.configBody()
  if (!config.port) {
    throw new Error(t('contactsView.status.repeaterSerialRequired'))
  }
  const password = String(repeaterManagementPassword.value || '').trim()
  const useSavedAuth = Boolean(!password && contactHasSavedRepeaterAuth(contact))
  if (!password && !useSavedAuth) {
    throw new Error(t('contactsView.status.repeaterPasswordExpired'))
  }
  if (!Array.isArray(commands) || !commands.length) {
    throw new Error(t('contactsView.status.repeaterCommandsMissing'))
  }
  repeaterManagementBusyAction.value = String(busyKey || '')
  try {
    const payload = await session.api('/api/repeater/cli', {
      method: 'POST',
      body: JSON.stringify({
        ...config,
        public_key: contact.public_key,
        commands,
        ...(password ? { password } : {}),
      }),
    })
    session.setStatus([
      successMessage,
      payload?.materialized_on_node ? t('contactsView.status.materializedSuffix') : '',
    ].filter(Boolean).join(' '))
    return payload
  } finally {
    repeaterManagementBusyAction.value = ''
  }
}

function resolveActiveRepeaterCard(cardId) {
  return activeRepeaterCards.value.find((card) => card.id === cardId) || null
}

function repeaterActionButtonClass(action) {
  return action?.tone === 'danger' ? 'mc-button mc-button--danger' : 'mc-button mc-button--ghost'
}

async function applyRepeaterCard(cardId) {
  const card = resolveActiveRepeaterCard(cardId)
  const draft = selectedRepeaterManagementDraft.value
  if (!card || !draft || !selectedRepeaterContact.value) {
    session.setStatus(t('contactsView.repeater.managementInvalidNote'), true)
    return
  }
  try {
    const commands = card.buildCommands(draft)
    const payload = await runRepeaterCliBatch(
      commands,
      t('contactsView.repeater.cardApplied', { title: card.title }),
      card.id,
    )
    if (typeof card.onSuccess === 'function') {
      card.onSuccess({
        contact: selectedRepeaterContact.value,
        draft,
        payload,
      })
    }
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('common.error')), true)
  }
}

async function runRepeaterCardAction(cardId, actionId) {
  const card = resolveActiveRepeaterCard(cardId)
  const action = card?.actions?.find((entry) => entry.id === actionId) || null
  if (!card || !action) {
    session.setStatus(t('common.error'), true)
    return
  }
  if (action.kind === 'open-geo-picker') {
    openRepeaterGeoSheet()
    return
  }
  const executeAction = async () => {
    try {
      await runRepeaterCliBatch(
        action.commands || [],
        t('contactsView.repeater.cardApplied', { title: action.label }),
        action.id,
      )
    } catch (error) {
      session.setStatus(error instanceof Error ? error.message : String(error || t('common.error')), true)
    }
  }
  if (action.notice) {
    session.setStatus(String(action.notice), true)
    return
  }
  if (action.confirmMessage) {
    openConfirmDialog({
      title: action.label,
      message: String(action.confirmMessage),
      confirmLabel: action.label,
      action: executeAction,
    })
    return
  }
  await executeAction()
}

async function toggleSelectedFavorite() {
  if (!selectedContact.value) {
    return
  }
  const nextFavorite = !isContactFavorite(selectedContact.value)
  await runSelectedContactAction(
    '/api/contacts/favorite',
    { favorite: nextFavorite },
    nextFavorite
      ? t('contactsView.status.favoriteAdded')
      : t('contactsView.status.favoriteRemoved'),
  )
}

async function shareSelectedContact() {
  await runSelectedContactAction('/api/contacts/share', {}, t('contactsView.status.contactShared'))
}

async function exportSelectedContact() {
  await runSelectedContactAction('/api/contacts/export', {}, t('contactsView.status.contactExported'))
}

function openRouteEditorPlaceholder() {
  if (!selectedContact.value || !contactCanDirect(selectedContact.value)) {
    session.setStatus(t('contactsView.status.directUnavailable'), true)
    return
  }
  clearRouteTraceState()
  routeEditorContactKey.value = normalizePublicKey(selectedContact.value.public_key)
  routeEditorInput.value = buildContactRouteInputFromContact(selectedContact.value, routeKnownCandidates.value)
  routeEditorOpen.value = true
}

async function closeRouteEditor() {
  if (routeTraceJobId.value) {
    await cancelActiveRouteTrace('dialog-closed', { preserveCancelledResult: false, silent: true })
  }
  stopRouteTraceEventStream()
  clearRouteTraceState()
  routeEditorOpen.value = false
  routeEditorContactKey.value = ''
  routeEditorInput.value = ''
}

function clearRouteEditorInput() {
  routeEditorInput.value = ''
}

function toggleRouteEditorPublicKey(publicKey) {
  const normalized = normalizePublicKey(publicKey)
  if (!normalized) {
    return
  }
  const current = routeEditorSelection.value.slice()
  const next = current.includes(normalized)
    ? current.filter((value) => value !== normalized)
    : [...current, normalized]
  routeEditorInput.value = next
    .map((value) => String(value || '').trim().toUpperCase().slice(0, preferredRouteHopDisplayLength()))
    .filter(Boolean)
    .join(', ')
}

async function saveRouteEditor() {
  const contact = routeEditorContact.value
  if (!contact) {
    session.setStatus(t('contactsView.status.selectContactFirst'), true)
    return
  }
  if (!routeEditorSelection.value.length) {
    const data = await session.api('/api/contacts/reset-path', {
      method: 'POST',
      body: JSON.stringify({
        ...session.configBody(),
        public_key: contact.public_key,
      }),
    })
    await applyContactsActionResult(data, t('contactsView.status.routeReset'))
    closeRouteEditor()
    return
  }
  const routeHashLenBytes = choosePreferredRouteHashLenBytes(routeEditorSelection.value, {
    contacts: session.contacts,
    selfPublicKey: session.self?.public_key,
  })
  const routePathHex = buildRoutePrefixHexFromPublicKeys(routeEditorSelection.value, routeHashLenBytes)
  const data = await session.api('/api/contacts/set-path', {
    method: 'POST',
    body: JSON.stringify({
      ...session.configBody(),
      public_key: contact.public_key,
      route_path_len: routeEditorSelection.value.length,
      route_path_hash_len: routeHashLenBytes,
      route_path_hex: routePathHex,
    }),
  })
  await applyContactsActionResult(data, t('contactsView.status.routeSaved'))
  closeRouteEditor()
}

async function resetStoredRouteFromEditor() {
  const contact = routeEditorContact.value
  if (!contact) {
    return
  }
  const data = await session.api('/api/contacts/reset-path', {
    method: 'POST',
    body: JSON.stringify({
      ...session.configBody(),
      public_key: contact.public_key,
    }),
  })
  await applyContactsActionResult(data, t('contactsView.status.routeReset'))
  routeEditorInput.value = ''
}

function stopRouteTraceEventStream() {
  if (routeTraceEventSource) {
    routeTraceEventSource.close()
    routeTraceEventSource = null
  }
}

function stopContactsEventStream() {
  if (contactsEventSource) {
    contactsEventSource.close()
    contactsEventSource = null
  }
}

function ensureContactsEventStream() {
  if (contactsEventSource || !session.connected || !session.selectedPort) {
    return
  }
  const query = new URLSearchParams({
    port: String(session.selectedPort || ''),
    baudrate: String(session.selectedBaudrate || session.DEFAULT_BAUDRATE),
    timeout: String(session.DEFAULT_TIMEOUT),
  })
  const source = new EventSource(`/api/events?${query.toString()}`)
  contactsEventSource = source
  source.onmessage = (event) => {
    const payload = JSON.parse(String(event.data || '{}'))
    if (payload?.event === 'heartbeat') {
      return
    }
    if (payload?.event === 'contacts-sync') {
      session.patchSessionSnapshotFields({
        contacts: Array.isArray(payload.contacts) ? payload.contacts : [],
        contacts_count: Array.isArray(payload.contacts) ? payload.contacts.length : session.contacts.length,
        contact_summary: payload.contact_summary || null,
        recent_repeaters_count: payload.recent_repeaters_count,
      })
      return
    }
    if (payload?.event === 'raw-advert') {
      session.noteRadioTransmission()
      const nowEpoch = Math.floor(Date.now() / 1000)
      touchContactActivityByPublicKey(payload.public_key, {
        last_advert: nowEpoch,
        backend: {
          last_public_traffic_at: nowEpoch,
          last_public_advert_at: nowEpoch,
          last_public_advert_mode: Number(payload.path_len || 0) === 0 ? 'direct' : 'flood',
        },
      })
      if (payload.recent_repeaters_count != null) {
        session.patchSessionSnapshotFields({
          recent_repeaters_count: payload.recent_repeaters_count,
        })
      }
      return
    }
    if (payload?.event === 'message') {
      const nowEpoch = Math.floor(Date.now() / 1000)
      touchContactActivityByPrefix(payload.pubkey_prefix || payload.public_key || '', {
        last_message_text: String(payload.text || ''),
        last_message_at: Number(payload.sender_timestamp || nowEpoch),
        last_message_from_self: Boolean(payload.from_self),
      })
      if (payload.recent_repeaters_count != null) {
        session.patchSessionSnapshotFields({
          recent_repeaters_count: payload.recent_repeaters_count,
        })
      }
      return
    }
    if (payload?.event === 'send-confirmed') {
      session.noteRadioTransmission()
    }
  }
  source.onerror = () => {
    if (!session.connected) {
      stopContactsEventStream()
    }
  }
}

function clearRouteTraceFailureTimer() {
  if (!routeTraceFailureTimer) {
    return
  }
  window.clearTimeout(routeTraceFailureTimer)
  routeTraceFailureTimer = 0
}

function scheduleRouteTraceFailureCard() {
  clearRouteTraceFailureTimer()
  if (!routeTraceResult.value || routeTraceResult.value.success || String(routeTraceResult.value.status || '') !== 'completed') {
    return
  }
  routeTraceFailureTimer = window.setTimeout(() => {
    routeTraceFailureTimer = 0
    if (routeTraceResult.value && !routeTraceResult.value.success) {
      routeTraceResult.value = {
        ...routeTraceResult.value,
        failure_visible: false,
      }
    }
  }, 3000)
}

function clearRouteTraceState() {
  clearRouteTraceFailureTimer()
  routeTraceJobId.value = ''
  routeTraceBusy.value = false
  routeTraceResult.value = null
}

function applyRouteTraceEventPayload(payload) {
  const incomingJobId = String(payload?.job_id || '').trim()
  if (incomingJobId && routeTraceJobId.value && incomingJobId !== String(routeTraceJobId.value)) {
    return
  }
  if (payload?.trace && typeof payload.trace === 'object') {
    routeTraceResult.value = {
      ...payload.trace,
      failure_visible: payload.trace.status === 'completed' && !payload.trace.success,
    }
  }
  const status = String(payload?.status || routeTraceResult.value?.status || '')
  if (status === 'queued' || status === 'running' || status === 'started' || status === 'progress') {
    routeTraceBusy.value = true
    return
  }
  routeTraceBusy.value = false
  routeTraceJobId.value = ''
  stopRouteTraceEventStream()
  scheduleRouteTraceFailureCard()
  if (status === 'completed' && routeTraceResult.value?.success) {
    session.setStatus(t('maps.trace.status.success', { hops: Number(routeTraceResult.value?.hop_count || 0) }))
  } else if (status === 'completed') {
    session.setStatus(t('maps.trace.status.failed', { hop: Number(routeTraceResult.value?.failure_at_hop || 0) || '?' }), true)
  } else if (status === 'cancelled') {
    session.setStatus(t('maps.trace.status.cancelled'))
  } else if (status === 'error') {
    session.setStatus(String(payload?.message || routeTraceResult.value?.error || t('maps.trace.status.error')), true)
  }
}

function ensureRouteTraceEventStream() {
  if (routeTraceEventSource || !session.connected) {
    return
  }
  const query = new URLSearchParams({
    port: String(session.selectedPort || ''),
    baudrate: String(session.selectedBaudrate || session.DEFAULT_BAUDRATE),
    timeout: String(session.DEFAULT_TIMEOUT),
  })
  const source = new EventSource(`/api/events?${query.toString()}`)
  routeTraceEventSource = source
  source.onmessage = (event) => {
    const payload = JSON.parse(String(event.data || '{}'))
    if (payload?.event === 'heartbeat') {
      return
    }
    if (payload?.event === 'contact-route-trace') {
      applyRouteTraceEventPayload(payload)
    }
  }
  source.onerror = () => {
    if (routeTraceBusy.value) {
      session.setStatus(t('maps.trace.status.listenerUnavailable'), true)
    }
  }
}

async function startRouteTraceFromEditor() {
  const contact = routeEditorContact.value
  if (!contact) {
    session.setStatus(t('contactsView.status.selectContactFirst'), true)
    return
  }
  if (!session.connected) {
    session.setStatus(t('maps.status.connectRequired'), true)
    return
  }
  if (!routeEditorSelection.value.length) {
    session.setStatus(t('maps.trace.status.selectRouteFirst'), true)
    return
  }
  if (routeTraceJobId.value) {
    await cancelActiveRouteTrace('trace-restarted', { preserveCancelledResult: false, silent: true })
  }
  const routeHashLenBytes = choosePreferredRouteHashLenBytes(routeEditorSelection.value, {
    contacts: session.contacts,
    selfPublicKey: session.self?.public_key,
  })
  routeTraceBusy.value = true
  routeTraceResult.value = {
    status: 'queued',
    success: false,
    cancelled: false,
    route_path_hash_len: routeHashLenBytes,
    hop_count: routeEditorSelection.value.length,
    sequential: Boolean(routeTraceSequential.value),
    steps: [],
    failure_at_hop: null,
    failure_reason: null,
    error: null,
    failure_visible: false,
  }
  ensureRouteTraceEventStream()
  session.setStatus(t('maps.trace.status.queued'))
  try {
    const payload = await session.api('/api/contacts/trace-route/start', {
      method: 'POST',
      body: JSON.stringify({
        ...session.configBody(),
        public_key: contact.public_key,
        selected_public_keys: routeEditorSelection.value.slice(),
        route_path_hash_len: routeHashLenBytes,
        sequential: Boolean(routeTraceSequential.value),
      }),
    })
    routeTraceJobId.value = String(payload?.job_id || '')
    if (payload?.trace && typeof payload.trace === 'object') {
      routeTraceResult.value = {
        ...payload.trace,
        failure_visible: payload.trace.status === 'completed' && !payload.trace.success,
      }
    }
    const immediateStatus = String(routeTraceResult.value?.status || '')
    if (immediateStatus === 'completed' || immediateStatus === 'cancelled' || immediateStatus === 'error') {
      applyRouteTraceEventPayload({
        job_id: routeTraceJobId.value,
        status: immediateStatus,
        trace: routeTraceResult.value,
      })
    }
  } catch (error) {
    stopRouteTraceEventStream()
    clearRouteTraceState()
    session.setStatus(error instanceof Error ? error.message : String(error || t('maps.trace.status.error')), true)
  }
}

async function cancelActiveRouteTrace(reason = 'cancelled', options = {}) {
  const jobId = String(routeTraceJobId.value || '').trim()
  stopRouteTraceEventStream()
  clearRouteTraceFailureTimer()
  routeTraceBusy.value = false
  routeTraceJobId.value = ''
  if (options?.preserveCancelledResult !== false) {
    routeTraceResult.value = {
      ...(routeTraceResult.value || {}),
      status: 'cancelled',
      success: false,
      cancelled: true,
      failure_visible: false,
      sequential: Boolean(routeTraceSequential.value),
    }
  } else {
    routeTraceResult.value = null
  }
  if (!jobId) {
    if (!options?.silent) {
      session.setStatus(t('maps.trace.status.cancelled'))
    }
    return false
  }
  try {
    await session.api('/api/contacts/trace-route/cancel', {
      method: 'POST',
      body: JSON.stringify({
        ...session.configBody(),
        job_id: jobId,
        reason,
      }),
    })
  } catch {
    // ignore cancellation transport failures
  }
  if (!options?.silent) {
    session.setStatus(t('maps.trace.status.cancelled'))
  }
  return true
}

function openSelectedContactGroups() {
  const firstTag = selectedContactGroupTags.value.find((entry) => entry !== t('contactsView.groups.none')) || ''
  openGroupsRoute(firstTag)
}

function openRemoveFromNodeConfirm() {
  if (!selectedContact.value) {
    return
  }
  openConfirmDialog({
    title: t('contactsView.actions.removeFromNode'),
    message: t('contactsView.confirmations.removeFromNode.message', {
      target: contactDisplayName(selectedContact.value, t('messages.fallback.unnamedContact')),
    }),
    note: t('contactsView.confirmations.removeFromNode.note'),
    confirmLabel: t('contactsView.actions.removeFromNode'),
    action: () => runSelectedContactAction('/api/contacts/delete-one', {}, t('contactsView.status.nodeCopyRemoved')),
  })
}

function openDeleteBackendConfirm() {
  if (!selectedContact.value) {
    return
  }
  openConfirmDialog({
    title: t('contactsView.actions.deleteBackend'),
    message: t('contactsView.confirmations.deleteBackend.message', {
      target: contactDisplayName(selectedContact.value, t('messages.fallback.unnamedContact')),
    }),
    note: t('contactsView.confirmations.deleteBackend.note'),
    confirmLabel: t('contactsView.actions.deleteBackend'),
    action: () => runSelectedContactAction('/api/contacts/delete-backend-one', {}, t('contactsView.status.contactDeletedBackend')),
  })
}

watch(
  () => [session.connected, contactsMode.value],
  ([connected, mode]) => {
    if (connected && (mode === 'root' || mode === 'groups' || mode === 'repeater-login' || mode === 'repeater-management')) {
      ensureContactsLoaded()
      ensureContactsEventStream()
    }
    if (connected && (mode === 'root' || mode === 'groups')) {
      ensureGroupsLoaded()
    }
    if (!connected) {
      stopContactsEventStream()
    }
  },
  { immediate: true },
)

watch(
  () => [session.selectedPort, session.selectedBaudrate, session.contacts.length, contactsMode.value],
  ([, , , mode]) => {
    if (session.connected && (mode === 'root' || mode === 'groups')) {
      ensureGroupsLoaded()
    }
  },
)

watch(
  () => [session.selectedPort, session.selectedBaudrate, session.connected],
  () => {
    stopContactsEventStream()
    if (session.connected) {
      ensureContactsEventStream()
    }
  },
)

watch(
  () => [groupEntries.value.length, selectedGroupName.value, contactsMode.value],
  async ([length, name, mode]) => {
    if (mode !== 'groups' || !length || name) {
      return
    }
    await selectGroup(groupEntries.value[0]?.name || '')
  },
)

watch(
  () => groupEntries.value.map((entry) => entry.name),
  (names) => {
    const current = normalizeContactGroupFilter(selectedContactGroupFilter.value)
    if (current !== 'all' && !names.includes(current)) {
      selectedContactGroupFilter.value = 'all'
    }
  },
  { immediate: true },
)

watch(
  () => [contactsMode.value, selectedRouteContactKey.value, selectedContact.value ? normalizeContactRouteKey(selectedContact.value.public_key) : '', contactsLoading.value],
  async ([mode, key, resolvedKey, loading]) => {
    if (mode !== 'root' || !key || loading || resolvedKey) {
      return
    }
    await selectContact('')
  },
)

watch(
  () => selectedContact.value,
  (contact) => {
    if (!contact) {
      closeTransientContactsControls()
    }
  },
)

watch(
  () => selectedRepeaterContact.value,
  (contact) => {
    if (contact) {
      ensureRepeaterManagementDraft(contact)
      return
    }
    repeaterGeoSheetOpen.value = false
    repeaterManagementBusyAction.value = ''
  },
  { immediate: true },
)

watch(
  () => [contactsMode.value, selectedRouteContactKey.value, repeaterLoginUsesSavedAuth.value, repeaterLoginBusy.value],
  ([mode, routeContactKey, shouldUseSavedAuth, busy]) => {
    if (mode !== 'repeater-login' || !routeContactKey || !shouldUseSavedAuth || busy) {
      return
    }
    if (repeaterLoginSavedAuthRetryBlockKey.value === normalizeContactRouteKey(routeContactKey)) {
      return
    }
    queueMicrotask(() => {
      if (contactsMode.value === 'repeater-login' && repeaterLoginUsesSavedAuth.value && !repeaterLoginBusy.value) {
        submitRepeaterLogin().catch(() => {})
      }
    })
  },
  { immediate: true },
)

watch(
  () => contactsMode.value,
  (mode, previousMode) => {
    if (mode !== 'repeater-login') {
      repeaterLoginBusy.value = false
      repeaterLoginPassword.value = ''
      repeaterLoginRememberAuth.value = false
      repeaterLoginSavedAuthBypassKey.value = ''
      repeaterLoginSavedAuthRetryBlockKey.value = ''
      clearRepeaterLoginNotice()
    }
    if (mode !== 'repeater-management' && previousMode === 'repeater-management') {
      repeaterGeoSheetOpen.value = false
      repeaterManagementPassword.value = ''
      repeaterManagementBusyAction.value = ''
    }
  },
)

watch(
  () => routeEditorContact.value,
  (contact) => {
    if (!contact && routeEditorOpen.value) {
      closeRouteEditor()
    }
  },
)

watch(
  () => selectedGroup.value?.name || '',
  (name) => {
    if (!name) {
      closeGroupEditor()
      if (groupNameDialog.value.mode === 'rename') {
        closeGroupNameDialog()
      }
    }
  },
)

watch(
  () => routeEditorSelection.value.join(','),
  async (next, previous) => {
    if (next === previous) {
      return
    }
    if (routeTraceJobId.value) {
      await cancelActiveRouteTrace('selection-changed', { preserveCancelledResult: false, silent: true })
      return
    }
    if (routeTraceResult.value) {
      clearRouteTraceState()
    }
  },
)

function handleContactsEscape(event) {
  if (event.defaultPrevented || event.key !== 'Escape') {
    return
  }
  if (confirmDialog.value.open) {
    event.preventDefault()
    closeConfirmDialog()
    return
  }
  if (routeEditorOpen.value) {
    event.preventDefault()
    void closeRouteEditor()
    return
  }
  if (repeaterGeoSheetOpen.value) {
    event.preventDefault()
    closeRepeaterGeoSheet()
    return
  }
  if (groupEditorOpen.value) {
    event.preventDefault()
    closeGroupEditor()
    return
  }
  if (groupNameDialog.value.open) {
    event.preventDefault()
    closeGroupNameDialog()
    return
  }
  if (contactsMode.value === 'repeater-login') {
    event.preventDefault()
    void closeRepeaterLogin()
    return
  }
  if (openContactsControl.value) {
    event.preventDefault()
    closeTransientContactsControls()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleContactsEscape)
  contactsOrder.value = normalizeContactsOrder(contactsOrder.value)
  contactsFilter.value = normalizeContactsFilter(contactsFilter.value)
  selectedContactGroupFilter.value = normalizeContactGroupFilter(selectedContactGroupFilter.value)
  if (session.connected) {
    ensureContactsLoaded()
    ensureContactsEventStream()
    if (isContactsRootMode.value || isGroupsMode.value) {
      ensureGroupsLoaded()
    }
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleContactsEscape)
  stopContactsEventStream()
  stopRouteTraceEventStream()
  clearRouteTraceFailureTimer()
})
</script>

<template>
  <ShellPageFrame
    scroller-class="mc-sidebar--contacts"
    scroller-header-class="mc-sidebar-top--contacts"
    workspace-class="mc-content--contacts"
  >
    <template #scroller-header>
      <div v-if="isRepeaterManagementMode" class="mc-scroller-copy mc-scroller-copy--contacts-shell">
        <button class="mc-contacts-scroller-back" type="button" @click="openRootContacts">
          {{ t('contactsView.actions.backToContacts') }}
        </button>
        <h1 class="mc-scroller-title mc-scroller-title--shell-top">
          {{ t('contactsView.repeater.managementTitle') }}
        </h1>
      </div>
      <div v-else class="mc-scroller-copy mc-scroller-copy--center">
        <h2 class="mc-scroller-title">{{ t('contactsView.scrollerTitle') }}</h2>
        <p class="mc-scroller-subtitle">{{ t('contactsView.scrollerSubtitle') }}</p>
      </div>
    </template>

    <template #scroller-body>
      <div v-if="isContactsRootMode" class="mc-list-scroll mc-contacts-list-scroll">
        <div
          v-for="entry in contactsRows"
          :key="entry.key"
          class="mc-list-item mc-contacts-list-item"
          :class="{ active: entry.active }"
          role="button"
          tabindex="0"
          @click="selectContact(entry.key)"
          @keydown="onListItemKeydown($event, entry.key)"
        >
          <div class="mc-list-avatar" :class="{ 'is-emoji': !!entry.emoji }">
            <span>{{ entry.emoji || entry.avatar }}</span>
            <span v-if="entry.unreadCount" class="mc-list-badge">
              {{ entry.unreadCount > 99 ? '99+' : entry.unreadCount }}
            </span>
            <span v-if="entry.mentionCount" class="mc-list-badge mc-list-badge--mention">
              {{ entry.mentionCount > 99 ? '99+' : entry.mentionCount }}
            </span>
          </div>
          <div class="mc-list-main">
            <div class="mc-list-title-row">
              <p class="mc-list-title">
                {{ entry.title }}
                <span v-if="entry.favorite" class="mc-contacts-title-favorite" aria-hidden="true">★</span>
              </p>
            </div>
            <p class="mc-contacts-list-key">{{ entry.shortKey }}</p>
            <p class="mc-list-preview mc-contacts-list-meta">
              {{ entry.kindLabel }} · {{ entry.routeLabel }} · {{ entry.residency }}
            </p>
            <div v-if="entry.hasCoordinates" class="mc-contacts-geo-row">
              <button
                class="mc-contacts-geo-button"
                type="button"
                :aria-label="t('contactsView.actions.openMap')"
                @click.stop="openContactOnMap(entry.raw)"
              >
                📍
              </button>
              <span class="mc-contacts-geo-coords">{{ entry.coordinatesText }}</span>
            </div>
            <div class="mc-contacts-list-bottom-row">
              <p v-if="entry.preview" class="mc-list-preview">{{ entry.preview }}</p>
            </div>
          </div>
          <div class="mc-list-corner mc-contacts-list-corner">
            <span class="mc-contact-badge">{{ entry.kindBadge }}</span>
            <span class="mc-contact-badge is-residency">{{ entry.residency }}</span>
            <span class="mc-list-meta mc-contacts-list-corner-time">{{ entry.lastSeenAgo }}</span>
          </div>
        </div>
        <div v-if="!contactsRows.length" class="mc-list-empty">
          {{ contactsLoading ? t('contactsView.loading') : t('contactsView.emptyList') }}
        </div>
      </div>

      <div v-else-if="isGroupsMode" class="mc-list-scroll mc-contacts-list-scroll">
        <button
          v-for="group in groupEntries"
          :key="group.name"
          class="mc-list-item mc-contacts-list-item"
          :class="{ active: group.active }"
          type="button"
          @click="selectGroup(group.name)"
        >
          <div class="mc-list-avatar mc-list-avatar--group">#</div>
          <div class="mc-list-main">
            <div class="mc-list-title-row">
              <p class="mc-list-title">{{ group.name }}</p>
              <span class="mc-list-meta">{{ group.count }}</span>
            </div>
            <p class="mc-list-preview">{{ t('contactsView.groups.memberCount', { count: group.count }) }}</p>
          </div>
        </button>
        <div v-if="!groupEntries.length" class="mc-list-empty">
          {{ groupsLoading ? t('contactsView.groups.loading') : t('contactsView.groups.empty') }}
        </div>
      </div>

      <div v-else-if="isRepeaterManagementMode" class="mc-list-scroll mc-contacts-list-scroll">
        <button
          v-for="category in repeaterCategories"
          :key="category.id"
          class="mc-list-item mc-contacts-list-item mc-contacts-list-item--compact"
          :class="{ active: category.id === repeaterCategoryId }"
          type="button"
          @click="openRepeaterCategory(category.id)"
        >
          <div class="mc-list-main">
            <div class="mc-list-title-row">
              <p class="mc-list-title">{{ category.label }}</p>
            </div>
          </div>
        </button>
        <div v-if="!repeaterCategories.length" class="mc-list-empty">
          {{ t('contactsView.repeater.managementEmptyCategories') }}
        </div>
      </div>

      <div v-else class="mc-list-scroll mc-contacts-list-scroll">
        <div v-if="selectedRepeaterContactRow" class="mc-list-item mc-contacts-list-item mc-contacts-list-item--login-target">
          <div class="mc-list-avatar" :class="{ 'is-emoji': !!selectedRepeaterContactRow.emoji }">
            <span>{{ selectedRepeaterContactRow.emoji || selectedRepeaterContactRow.avatar }}</span>
          </div>
          <div class="mc-list-main">
            <div class="mc-list-title-row">
              <p class="mc-list-title">{{ selectedRepeaterContactRow.title }}</p>
            </div>
            <p class="mc-contacts-list-key">{{ selectedRepeaterContactRow.shortKey }}</p>
            <p class="mc-list-preview mc-contacts-list-meta">
              {{ selectedRepeaterContactRow.kindLabel }} · {{ selectedRepeaterContactRow.residency }}
            </p>
          </div>
          <div class="mc-list-corner mc-contacts-list-corner">
            <span class="mc-contact-badge">{{ selectedRepeaterContactRow.kindBadge }}</span>
          </div>
        </div>
        <div class="mc-list-empty">
          {{ t('contactsView.repeater.loginScrollerNote') }}
        </div>
      </div>
    </template>

    <template #scroller-footer>
      <div class="mc-status">
        {{ scrollerFooterStatus }}
      </div>
    </template>

    <template #workspace-top>
      <ShellPhonebar />
    </template>

    <template #workspace-header>
      <header class="mc-workspace-header mc-workspace-header--contacts">
        <div class="mc-workspace-copy">
          <h1 v-if="!isRepeaterManagementMode" class="mc-workspace-title">{{ workspaceHeaderTitle }}</h1>
          <p
            class="mc-workspace-subtitle"
            :class="{ 'mc-workspace-subtitle--contacts-repeater': isRepeaterManagementMode }"
          >
            {{ workspaceHeaderSubtitle }}
          </p>
        </div>
        <div v-if="isContactsRootMode && selectedContact" class="mc-workspace-actions">
          <button class="mc-button mc-button--ghost" type="button" @click="toggleContactsToolsCollapsed">
            {{ effectiveToolsCollapsed ? t('contactsView.toolset.expandTools') : t('contactsView.toolset.collapseTools') }}
          </button>
        </div>
      </header>
    </template>

    <template #workspace-body>
      <div class="mc-contacts-workspace-shell">
        <template v-if="isContactsRootMode">
          <section v-show="!effectiveToolsCollapsed" class="mc-contacts-tools-surface">
            <div class="mc-contacts-tools-grid">
              <label class="mc-settings-row mc-settings-row--contacts mc-settings-row--contacts-search">
                <div class="mc-settings-row-label">
                  <strong>{{ t('contactsView.toolset.searchLabel') }}</strong>
                  <span>{{ t('contactsView.toolset.searchHint') }}</span>
                </div>
                <div class="mc-settings-row-control">
                  <input
                    v-model="contactsSearchTerm"
                    class="mc-settings-inline-input"
                    type="text"
                    :placeholder="t('contactsView.toolset.searchPlaceholder')"
                  >
                </div>
              </label>

              <div v-if="!isMobile" class="mc-contacts-inline-controls">
                <label class="mc-settings-row mc-settings-row--contacts">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('contactsView.toolset.orderLabel') }}</strong>
                  </div>
                  <div class="mc-settings-row-control">
                    <PluginDropdown
                      :model-value="contactsOrder"
                      :options="orderOptions"
                      @update:model-value="setContactsOrder"
                    />
                  </div>
                </label>
                <label class="mc-settings-row mc-settings-row--contacts">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('contactsView.toolset.filterLabel') }}</strong>
                  </div>
                  <div class="mc-settings-row-control">
                    <PluginDropdown
                      :model-value="contactsFilter"
                      :options="filterOptions"
                      @update:model-value="setContactsFilter"
                    />
                  </div>
                </label>
              </div>

              <div v-else class="mc-contacts-mobile-controls">
                <button
                  class="mc-button mc-button--ghost mc-contacts-mobile-control"
                  :class="{ active: openContactsControl === 'order' }"
                  type="button"
                  @click="toggleContactsControl('order')"
                >
                  {{ t('contactsView.toolset.mobileOrder') }}
                </button>
                <button
                  class="mc-button mc-button--ghost mc-contacts-mobile-control"
                  :class="{ active: openContactsControl === 'filter' }"
                  type="button"
                  @click="toggleContactsControl('filter')"
                >
                  {{ t('contactsView.toolset.mobileFilter') }}
                </button>
                <div v-if="openContactsControl === 'order'" class="mc-contacts-mobile-control-panel">
                  <button
                    v-for="option in orderOptions"
                    :key="option.value"
                    class="mc-contacts-mobile-control-option"
                    :class="{ active: String(option.value) === String(contactsOrder) }"
                    type="button"
                    @click="setContactsOrder(option.value)"
                  >
                    {{ option.label }}
                  </button>
                </div>
                <div v-if="openContactsControl === 'filter'" class="mc-contacts-mobile-control-panel">
                  <button
                    v-for="option in filterOptions"
                    :key="option.value"
                    class="mc-contacts-mobile-control-option"
                    :class="{ active: String(option.value) === String(contactsFilter) }"
                    type="button"
                    @click="setContactsFilter(option.value)"
                  >
                    {{ option.label }}
                  </button>
                </div>
              </div>

              <label class="mc-settings-row mc-settings-row--contacts">
                <div class="mc-settings-row-label">
                  <strong>{{ t('contactsView.toolset.groupLabel') }}</strong>
                  <span>{{ t('contactsView.toolset.groupHint') }}</span>
                </div>
                <div class="mc-settings-row-control">
                  <PluginDropdown
                    :model-value="selectedContactGroupFilter"
                    :options="groupFilterOptions"
                    @update:model-value="setSelectedContactGroupFilter"
                  />
                </div>
              </label>

              <div class="mc-contacts-action-row">
                <button class="mc-button mc-button--ghost" type="button" @click="importContactFromClipboard">
                  {{ t('contactsView.actions.importClipboard') }}
                </button>
                <button class="mc-button mc-button--ghost" type="button" @click="exportSelfAdvert">
                  {{ t('contactsView.actions.copySelfAdvert') }}
                </button>
                <button class="mc-button mc-button--ghost" type="button" @click="openGroupsRoute()">
                  {{ t('contactsView.actions.openGroups') }}
                </button>
              </div>

              <div class="mc-contacts-summary-line">
                {{ listSummaryText }}
              </div>

              <div class="mc-contacts-toolset-footer">
                <button class="mc-button mc-button--ghost" type="button" @click="resetContactsFilters">
                  {{ t('contactsView.actions.clearFilters') }}
                </button>
              </div>
            </div>
          </section>
        </template>

        <section class="mc-contacts-workspace-main">
          <button
            v-if="showMobileDetailOnly"
            class="mc-button mc-button--ghost mc-contacts-mobile-back"
            type="button"
            @click="selectContact('')"
          >
            {{ t('contactsView.actions.backToList') }}
          </button>

          <template v-if="isContactsRootMode">
            <div v-if="showWorkspaceMobileList" class="mc-list-scroll mc-contacts-list-scroll mc-contacts-list-scroll--workspace">
              <div
                v-for="entry in contactsRows"
                :key="`workspace-${entry.key}`"
                class="mc-list-item mc-contacts-list-item"
                :class="{ active: entry.active }"
                role="button"
                tabindex="0"
                @click="selectContact(entry.key)"
                @keydown="onListItemKeydown($event, entry.key)"
              >
                <div class="mc-list-avatar" :class="{ 'is-emoji': !!entry.emoji }">
                  <span>{{ entry.emoji || entry.avatar }}</span>
                  <span v-if="entry.unreadCount" class="mc-list-badge">
                    {{ entry.unreadCount > 99 ? '99+' : entry.unreadCount }}
                  </span>
                  <span v-if="entry.mentionCount" class="mc-list-badge mc-list-badge--mention">
                    {{ entry.mentionCount > 99 ? '99+' : entry.mentionCount }}
                  </span>
                </div>
                <div class="mc-list-main">
                <div class="mc-list-title-row">
                  <p class="mc-list-title">
                    {{ entry.title }}
                    <span v-if="entry.favorite" class="mc-contacts-title-favorite" aria-hidden="true">★</span>
                  </p>
                </div>
                <p class="mc-contacts-list-key">{{ entry.shortKey }}</p>
                <p class="mc-list-preview mc-contacts-list-meta">
                  {{ entry.kindLabel }} · {{ entry.routeLabel }} · {{ entry.residency }}
                </p>
                  <div v-if="entry.hasCoordinates" class="mc-contacts-geo-row">
                    <button
                      class="mc-contacts-geo-button"
                      type="button"
                      :aria-label="t('contactsView.actions.openMap')"
                      @click.stop="openContactOnMap(entry.raw)"
                    >
                      📍
                    </button>
                    <span class="mc-contacts-geo-coords">{{ entry.coordinatesText }}</span>
                  </div>
                  <div class="mc-contacts-list-bottom-row">
                    <p v-if="entry.preview" class="mc-list-preview">{{ entry.preview }}</p>
                  </div>
                </div>
                <div class="mc-list-corner mc-contacts-list-corner">
                  <span class="mc-contact-badge">{{ entry.kindBadge }}</span>
                  <span class="mc-contact-badge is-residency">{{ entry.residency }}</span>
                  <span class="mc-list-meta mc-contacts-list-corner-time">{{ entry.lastSeenAgo }}</span>
                </div>
              </div>
            </div>
            <div v-else-if="selectedContact && selectedContactRow" class="mc-contacts-detail-stack">
              <div class="mc-contacts-card mc-contacts-summary-card">
                <div class="mc-contacts-card-head">
                  <div class="mc-list-avatar mc-contacts-card-avatar" :class="{ 'is-emoji': !!selectedContactRow.emoji }">
                    <span>{{ selectedContactRow.emoji || selectedContactRow.avatar }}</span>
                    <span v-if="selectedContactRow.unreadCount" class="mc-list-badge">
                      {{ selectedContactRow.unreadCount > 99 ? '99+' : selectedContactRow.unreadCount }}
                    </span>
                    <span v-if="selectedContactRow.mentionCount" class="mc-list-badge mc-list-badge--mention">
                      {{ selectedContactRow.mentionCount > 99 ? '99+' : selectedContactRow.mentionCount }}
                    </span>
                  </div>
                  <div class="mc-contacts-card-copy">
                    <h3>
                      {{ selectedContactRow.title }}
                      <span v-if="selectedContactRow.favorite" class="mc-contacts-title-favorite" aria-hidden="true">★</span>
                    </h3>
                    <p>
                      {{ selectedContactRow.kindLabel }}
                      ·
                      {{ selectedContactRow.residency }}
                      ·
                      {{ selectedContactRow.shortKey }}
                    </p>
                    <p class="mc-contacts-list-meta">
                      {{ selectedContactRow.routeLabel }} · {{ selectedContactRow.lastSeenAgo }}
                    </p>
                    <div v-if="selectedContactRow.hasCoordinates" class="mc-contacts-geo-row">
                      <button
                        class="mc-contacts-geo-button"
                        type="button"
                        :aria-label="t('contactsView.actions.openMap')"
                        @click="openContactOnMap(selectedContact)"
                      >
                        📍
                      </button>
                      <span class="mc-contacts-geo-coords">{{ selectedContactRow.coordinatesText }}</span>
                    </div>
                  </div>
                </div>
                <div class="mc-contacts-tag-row">
                  <div class="mc-contacts-tag-row-left">
                    <span
                      v-for="tag in selectedContactGroupTags"
                      :key="tag"
                      class="mc-contacts-tag-chip"
                      :class="{ 'is-muted': tag === t('contactsView.groups.none') }"
                    >
                      {{ tag }}
                    </span>
                  </div>
                  <div class="mc-contacts-tag-row-right">
                    <span class="mc-contacts-activity-indicator">{{ selectedContactTrafficIndicatorText }}</span>
                    <span class="mc-contacts-activity-indicator">{{ selectedContactAdvertIndicatorText }}</span>
                  </div>
                </div>
              </div>

              <div class="mc-contacts-placeholder-card mc-contacts-detail-meta-card">
                <div class="mc-contacts-detail-meta-grid">
                  <div class="mc-contacts-detail-meta-row">
                    <span class="mc-contacts-detail-meta-label">{{ t('contactsView.meta.residencyLabel') }}</span>
                    <div class="mc-contacts-detail-meta-value">
                      <span class="mc-contact-badge is-residency">{{ selectedContactRow.residency }}</span>
                    </div>
                  </div>
                  <div class="mc-contacts-detail-meta-row">
                    <span class="mc-contacts-detail-meta-label">{{ t('contactsView.meta.historyLabel') }}</span>
                    <div class="mc-contacts-detail-meta-value">
                      <span>{{ selectedContactHistoryText }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <div class="mc-contacts-action-grid">
                <button class="mc-button mc-button--ghost" type="button" @click="toggleSelectedFavorite">
                  {{ selectedContactFavoriteActionLabel }}
                </button>
                <button class="mc-button mc-button--ghost" type="button" @click="shareSelectedContact">
                  {{ t('contactsView.actions.share') }}
                </button>
                <button class="mc-button mc-button--ghost" type="button" @click="exportSelectedContact">
                  {{ t('contactsView.actions.export') }}
                </button>
                <button
                  v-if="selectedContactRow.canDirect"
                  class="mc-button mc-button--ghost"
                  type="button"
                  @click="openRouteEditorPlaceholder"
                >
                  {{ t('contactsView.actions.route') }}
                </button>
                <button
                  v-if="selectedContactRow.canManageRepeater"
                  class="mc-button mc-button--primary"
                  type="button"
                  @click="openSelectedRepeaterManagement"
                >
                  {{ t('contactsView.actions.openRepeaterManagement') }}
                </button>
                <button
                  class="mc-button mc-button--ghost"
                  type="button"
                  :disabled="!selectedContactRow.onNode"
                  @click="openRemoveFromNodeConfirm"
                >
                  {{ t('contactsView.actions.removeFromNode') }}
                </button>
                <button class="mc-button mc-button--danger" type="button" @click="openDeleteBackendConfirm">
                  {{ t('contactsView.actions.deleteBackend') }}
                </button>
                <button class="mc-button mc-button--ghost" type="button" @click="openSelectedContactGroups">
                  {{ t('contactsView.actions.groups') }}
                </button>
              </div>
              <div
                v-if="selectedContactRow.canManageRepeater && selectedContactHasSavedRepeaterAuth"
                class="mc-contacts-secondary-actions"
              >
                <button class="mc-button mc-button--ghost" type="button" @click="deleteSelectedRepeaterAuth">
                  {{ t('contactsView.actions.deleteRepeaterAuth') }}
                </button>
              </div>

              <div
                v-if="!selectedContactRow.canManageRepeater"
                class="mc-contacts-placeholder-card"
                :class="{ 'mc-contacts-placeholder-card--repeater-tooling': selectedContactRow.canManageRepeater }"
              >
                <h3 v-if="!selectedContactRow.canManageRepeater">{{ selectedContactDirectTitle }}</h3>
                <p
                  class="mc-contacts-direct-description"
                  :class="{ 'mc-contacts-direct-description--spaced': selectedContactRow.canDirect && !selectedContactHasDirect }"
                >
                  {{ selectedContactDirectDescription }}
                </p>
                <div
                  class="mc-contacts-action-grid"
                  :class="{
                    'mc-contacts-action-grid--single': selectedContactRow.canDirect && !selectedContactHasDirect,
                    'mc-contacts-action-grid--repeater-tooling': selectedContactRow.canManageRepeater,
                  }"
                >
                  <button
                    v-if="selectedContactRow.canDirect && selectedContactHasDirect"
                    class="mc-button mc-button--primary"
                    type="button"
                    @click="openSelectedDirectConversation"
                  >
                    {{ t('contactsView.actions.openDirect') }}
                  </button>
                  <button
                    v-else-if="selectedContactRow.canDirect"
                    class="mc-button mc-button--primary mc-button--direct-entry"
                    type="button"
                    @click="startSelectedDirectConversation"
                  >
                    {{ t('contactsView.actions.startDirect') }}
                  </button>
                  <button
                    v-if="selectedContactRow.canManageRepeater"
                    class="mc-button mc-button--ghost"
                    type="button"
                    @click="openSelectedRepeaterManagement"
                  >
                    {{ t('contactsView.actions.openRepeaterManagement') }}
                  </button>
                </div>
              </div>
            </div>
            <div v-else class="mc-contacts-placeholder-card mc-contacts-placeholder-card--empty-root">
              <h3>{{ t('contactsView.workspace.emptyTitle') }}</h3>
              <p>{{ t('contactsView.workspace.emptySubtitle') }}</p>
              <div class="mc-contacts-action-grid">
                <button class="mc-button mc-button--ghost" type="button" @click="importContactFromClipboard">
                  {{ t('contactsView.actions.importClipboard') }}
                </button>
                <button class="mc-button mc-button--ghost" type="button" @click="exportSelfAdvert">
                  {{ t('contactsView.actions.copySelfAdvert') }}
                </button>
                <button class="mc-button mc-button--ghost" type="button" @click="openGroupsRoute()">
                  {{ t('contactsView.actions.openGroups') }}
                </button>
                <button class="mc-button mc-button--danger" type="button" @click="openNodeCleanupConfirm">
                  {{ t('contactsView.actions.nodeCleanup') }}
                </button>
              </div>
            </div>
          </template>

          <template v-else-if="isGroupsMode">
            <div v-if="selectedGroup" class="mc-contacts-group-workspace">
              <section class="mc-contacts-group-members-pane">
                <header class="mc-contacts-group-members-header">
                  <div>
                    <h3>{{ t('contactsView.groups.membersTitle') }}</h3>
                    <p>{{ t('contactsView.groups.memberCount', { count: selectedGroupMembers.length }) }}</p>
                  </div>
                </header>
                <div class="mc-contacts-group-members-scroll">
                  <article
                    v-for="member in selectedGroupMembers"
                    :key="member.key"
                    class="mc-contacts-group-member-card"
                  >
                    <div class="mc-list-avatar" :class="{ 'is-emoji': !!member.emoji }">
                      <span>{{ member.emoji || member.avatar }}</span>
                      <span v-if="member.unreadCount" class="mc-list-badge">
                        {{ member.unreadCount > 99 ? '99+' : member.unreadCount }}
                      </span>
                      <span v-if="member.mentionCount" class="mc-list-badge mc-list-badge--mention">
                        {{ member.mentionCount > 99 ? '99+' : member.mentionCount }}
                      </span>
                    </div>
                    <div class="mc-list-main">
                    <div class="mc-list-title-row">
                      <p class="mc-list-title">
                          {{ member.title }}
                          <span v-if="member.favorite" class="mc-contacts-title-favorite" aria-hidden="true">★</span>
                      </p>
                    </div>
                    <p class="mc-contacts-list-key">{{ member.shortKey }}</p>
                    <p class="mc-list-preview mc-contacts-list-meta">
                      {{ member.kindLabel }} · {{ member.routeLabel }} · {{ member.residency }}
                    </p>
                      <div class="mc-contacts-list-bottom-row">
                        <p v-if="member.preview" class="mc-list-preview">{{ member.preview }}</p>
                        <span class="mc-list-meta mc-contacts-list-last-seen">{{ member.lastSeenAgo }}</span>
                      </div>
                    </div>
                    <div class="mc-list-corner mc-contacts-list-corner">
                      <span class="mc-contact-badge">{{ member.kindBadge }}</span>
                      <span class="mc-contact-badge is-residency">{{ member.residency }}</span>
                    </div>
                  </article>
                  <div v-if="!selectedGroupMembers.length" class="mc-list-empty">
                    {{ t('contactsView.groups.membersEmpty') }}
                  </div>
                </div>
              </section>

              <aside class="mc-contacts-group-tools-pane">
                <div class="mc-contacts-placeholder-card">
                  <h3>{{ selectedGroup.name }}</h3>
                  <p>{{ selectedGroupWorkspaceNote }}</p>
                  <div class="mc-contacts-detail-meta-grid mc-contacts-detail-meta-grid--compact">
                    <div class="mc-contacts-detail-meta-row">
                      <span class="mc-contacts-detail-meta-label">{{ t('contactsView.groups.scopeLabel') }}</span>
                      <div class="mc-contacts-detail-meta-value">
                        <span>{{ contactGroupsScopeLabel }}</span>
                      </div>
                    </div>
                    <div class="mc-contacts-detail-meta-row">
                      <span class="mc-contacts-detail-meta-label">{{ t('contactsView.groups.memberCountLabel') }}</span>
                      <div class="mc-contacts-detail-meta-value">
                        <span>{{ t('contactsView.groups.memberCount', { count: selectedGroupMembers.length }) }}</span>
                      </div>
                    </div>
                  </div>
                  <div class="mc-contacts-action-grid">
                    <button class="mc-button mc-button--primary" type="button" @click="openGroupEditor">
                      {{ t('contactsView.actions.editGroupMembers') }}
                    </button>
                    <button
                      class="mc-button mc-button--ghost"
                      type="button"
                      :disabled="selectedGroupIsFavorites"
                      @click="openRenameGroupDialog"
                    >
                      {{ t('contactsView.actions.renameGroup') }}
                    </button>
                    <button
                      class="mc-button mc-button--danger"
                      type="button"
                      :disabled="selectedGroupIsFavorites"
                      @click="openDeleteSelectedGroupConfirm"
                    >
                      {{ t('contactsView.actions.deleteGroup') }}
                    </button>
                  </div>
                </div>
              </aside>
            </div>
            <div v-else class="mc-contacts-placeholder-card">
              <h3>{{ t('contactsView.groups.emptyTitle') }}</h3>
              <p>{{ t('contactsView.groups.emptySubtitle') }}</p>
              <p>{{ contactGroupsScopeLabel }}</p>
              <div class="mc-contacts-action-grid">
                <button class="mc-button mc-button--primary" type="button" @click="openCreateGroupDialog({ navigateToGroups: true })">
                  {{ t('contactsView.actions.createGroup') }}
                </button>
              </div>
            </div>
          </template>

          <template v-else-if="isRepeaterLoginMode">
            <div class="mc-contacts-placeholder-card mc-contacts-repeater-login-mobile">
              <h3>{{ t('contactsView.repeater.loginTitle') }}</h3>
              <p>
                {{ t('contactsView.repeater.loginMeta', {
                  target: selectedRepeaterContact ? contactDisplayName(selectedRepeaterContact, t('messages.fallback.unnamedContact')) : shortContactPublicKey(selectedRouteContactKey),
                  publicKey: selectedRepeaterContact ? shortContactPublicKey(selectedRepeaterContact) : shortContactPublicKey(selectedRouteContactKey),
                }) }}
              </p>
              <p class="mc-contacts-card-note">
                {{ repeaterLoginUsesSavedAuth ? t('contactsView.repeater.savedAuthAutoLoginNote') : t('contactsView.repeater.loginMemoryNote') }}
              </p>
              <div v-if="repeaterLoginUsesSavedAuth" class="mc-contacts-repeater-login-autostate">
                {{ t('contactsView.repeater.savedAuthConnecting') }}
              </div>
              <div v-if="repeaterLoginNotice.message" class="mc-contacts-repeater-login-notice">
                {{ repeaterLoginNotice.message }}
              </div>
              <div v-if="selectedContactHasSavedRepeaterAuth" class="mc-contacts-secondary-actions">
                <button class="mc-button mc-button--ghost" type="button" :disabled="repeaterLoginBusy" @click="deleteSelectedRepeaterAuth">
                  {{ t('contactsView.actions.deleteRepeaterAuth') }}
                </button>
              </div>
              <template v-else>
                <label class="mc-settings-row mc-settings-row--contacts">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('contactsView.repeater.passwordLabel') }}</strong>
                    <span>{{ t('contactsView.repeater.passwordHint') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <input
                      v-model="repeaterLoginPassword"
                      class="mc-settings-inline-input"
                      type="password"
                      name="repeater-login-secret"
                      autocomplete="new-password"
                      autocapitalize="off"
                      autocorrect="off"
                      spellcheck="false"
                      data-lpignore="true"
                      data-1p-ignore="true"
                      data-form-type="other"
                      :placeholder="t('contactsView.repeater.passwordPlaceholder')"
                      :disabled="repeaterLoginBusy"
                      @keydown.enter.prevent="submitRepeaterLogin"
                    >
                  </div>
                </label>
                <div class="mc-settings-row mc-settings-row--contacts">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('contactsView.repeater.rememberAuthLabel') }}</strong>
                    <span>{{ t('contactsView.repeater.rememberAuthHint') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <div class="mc-settings-checkbox">
                      <input
                        v-model="repeaterLoginRememberAuth"
                        type="checkbox"
                        :disabled="repeaterLoginBusy"
                      />
                    </div>
                  </div>
                </div>
              </template>
              <div class="mc-contacts-action-grid" :class="{ 'mc-contacts-action-grid--single': repeaterLoginUsesSavedAuth }">
                <button class="mc-button mc-button--ghost" type="button" @click="closeRepeaterLogin">
                  {{ t('contactsView.actions.backToContacts') }}
                </button>
                <button
                  v-if="repeaterLoginSavedAuthRetryAllowed"
                  class="mc-button mc-button--primary"
                  type="button"
                  :disabled="repeaterLoginBusy || !selectedRepeaterContact"
                  @click="submitRepeaterLogin"
                >
                  {{ t('contactsView.repeater.retryLogin') }}
                </button>
                <button
                  v-if="!repeaterLoginUsesSavedAuth"
                  class="mc-button mc-button--primary"
                  type="button"
                  :disabled="repeaterLoginBusy || !selectedRepeaterContact"
                  @click="submitRepeaterLogin"
                >
                  {{ repeaterLoginBusy ? t('contactsView.repeater.loginBusy') : t('contactsView.repeater.loginSubmit') }}
                </button>
              </div>
            </div>
          </template>

          <template v-else>
            <div
              v-if="selectedRepeaterContact && selectedRepeaterContactRow"
              class="mc-contacts-repeater-workspace mc-contacts-repeater-workspace--detail-only"
            >
              <section class="mc-contacts-repeater-detail-pane">
                <div v-if="!activeRepeaterCategory" class="mc-contacts-placeholder-card">
                  <h3>{{ t('contactsView.repeater.managementIntroTitle') }}</h3>
                  <p>{{ t('contactsView.repeater.managementIntroNote') }}</p>
                </div>

                <div v-else class="mc-contacts-detail-stack">
                  <div class="mc-contacts-card mc-contacts-repeater-login-summary">
                    <div class="mc-contacts-card-head">
                      <div class="mc-list-avatar mc-contacts-card-avatar" :class="{ 'is-emoji': !!selectedRepeaterContactRow.emoji }">
                        <span>{{ selectedRepeaterContactRow.emoji || selectedRepeaterContactRow.avatar }}</span>
                      </div>
                      <div class="mc-contacts-card-copy">
                        <h3>{{ selectedRepeaterContactRow.title }}</h3>
                        <p>{{ selectedRepeaterContactRow.kindLabel }} · {{ selectedRepeaterContactRow.residency }} · {{ selectedRepeaterContactRow.shortKey }}</p>
                        <p class="mc-contacts-list-meta">{{ selectedRepeaterContactRow.routeLabel }} · {{ selectedRepeaterContactRow.lastSeenAgo }}</p>
                      </div>
                    </div>
                  </div>
                  <div class="mc-contacts-placeholder-card">
                    <h3>{{ activeRepeaterCategory.label }}</h3>
                    <p>
                      {{ t('contactsView.repeater.managementNote', {
                        target: contactDisplayName(selectedRepeaterContact, t('messages.fallback.unnamedContact')),
                        category: activeRepeaterCategory.label,
                      }) }}
                    </p>
                  </div>
                  <template v-if="activeRepeaterCards.length && selectedRepeaterManagementDraft">
                    <section class="mc-contacts-repeater-card-stack">
                      <article
                        v-for="card in activeRepeaterCards"
                        :key="card.id"
                        class="mc-settings-card mc-contacts-repeater-card"
                      >
                        <div class="mc-settings-card-copy">
                          <h3>{{ card.title }}</h3>
                          <p>{{ card.description }}</p>
                        </div>
                        <div class="mc-contacts-repeater-card-fields">
                          <template v-for="field in card.fields" :key="field.key">
                            <label class="mc-settings-row mc-settings-row--contacts">
                              <div class="mc-settings-row-label">
                                <strong>{{ field.label }}</strong>
                              </div>
                              <div class="mc-settings-row-control mc-settings-row-control--stack">
                                <textarea
                                  v-if="field.type === 'textarea'"
                                  v-model="selectedRepeaterManagementDraft[field.key]"
                                  class="mc-settings-inline-input mc-contacts-repeater-textarea"
                                  :rows="field.rows || 4"
                                  :maxlength="field.maxLength || 400"
                                  :placeholder="field.placeholder || ''"
                                  :disabled="repeaterManagementBusyAction === card.id"
                                ></textarea>
                                <select
                                  v-else-if="field.type === 'select'"
                                  v-model="selectedRepeaterManagementDraft[field.key]"
                                  class="mc-settings-native-select mc-contacts-repeater-select"
                                  :disabled="repeaterManagementBusyAction === card.id"
                                >
                                  <option
                                    v-for="option in field.options || []"
                                    :key="`${field.key}-${option.value}`"
                                    :value="option.value"
                                  >
                                    {{ option.label }}
                                  </option>
                                </select>
                                <input
                                  v-else
                                  v-model="selectedRepeaterManagementDraft[field.key]"
                                  class="mc-settings-inline-input mc-contacts-repeater-input"
                                  :type="field.type || 'text'"
                                  :maxlength="field.maxLength || undefined"
                                  :min="field.min ?? undefined"
                                  :max="field.max ?? undefined"
                                  :step="field.step ?? undefined"
                                  :placeholder="field.placeholder || ''"
                                  :disabled="repeaterManagementBusyAction === card.id"
                                >
                              </div>
                            </label>
                          </template>
                        </div>
                        <div class="mc-settings-card-actions">
                          <button
                            v-if="card.applyLabel"
                            class="mc-button mc-button--primary"
                            type="button"
                            :disabled="repeaterManagementBusyAction === card.id"
                            @click="applyRepeaterCard(card.id)"
                          >
                            {{ repeaterManagementBusyAction === card.id ? t('contactsView.repeater.applying') : card.applyLabel }}
                          </button>
                          <template v-if="card.actions?.length">
                            <button
                              v-for="action in card.actions"
                              :key="action.id"
                              :class="repeaterActionButtonClass(action)"
                              type="button"
                              :disabled="repeaterManagementBusyAction === action.id"
                              @click="runRepeaterCardAction(card.id, action.id)"
                            >
                              {{ repeaterManagementBusyAction === action.id ? t('contactsView.repeater.applying') : action.label }}
                            </button>
                          </template>
                        </div>
                        <template v-if="card.actions?.length">
                          <p
                            v-for="action in card.actions.filter((entry) => entry.notice)"
                            :key="`${card.id}-${action.id}-notice`"
                            class="mc-contacts-card-note"
                          >
                            {{ action.notice }}
                          </p>
                        </template>
                      </article>
                    </section>
                  </template>
                  <div v-else class="mc-contacts-placeholder-card">
                    <h3>{{ t('contactsView.repeater.categoryShellTitle') }}</h3>
                    <p>{{ t('contactsView.repeater.categoryShellNote') }}</p>
                  </div>
                </div>
              </section>
            </div>
            <div v-else class="mc-contacts-placeholder-card">
              <h3>{{ t('contactsView.repeater.managementInvalidTitle') }}</h3>
              <p>{{ t('contactsView.repeater.managementInvalidNote') }}</p>
              <button class="mc-button mc-button--ghost mc-contacts-shell-action" type="button" @click="openRootContacts">
                {{ t('contactsView.actions.backToContacts') }}
              </button>
            </div>
          </template>
        </section>
      </div>
    </template>
  </ShellPageFrame>

  <div
    v-if="groupNameDialog.open"
    class="mc-contacts-modal-backdrop"
    @click.self="closeGroupNameDialog"
  >
    <section class="mc-contacts-modal-sheet mc-contacts-modal-sheet--narrow">
      <header class="mc-contacts-modal-header">
        <div>
          <h3>{{ groupNameDialog.mode === 'rename' ? t('contactsView.groups.renameTitle') : t('contactsView.groups.createTitle') }}</h3>
          <p>{{ groupNameDialog.mode === 'rename' ? t('contactsView.groups.renameSubtitle') : t('contactsView.groups.createSubtitle') }}</p>
        </div>
        <button class="mc-button mc-button--ghost" type="button" @click="closeGroupNameDialog">
          {{ t('common.close') }}
        </button>
      </header>
      <div class="mc-contacts-modal-body">
        <label class="mc-settings-row mc-settings-row--contacts-search">
          <div class="mc-settings-row-label">
            <strong>{{ t('contactsView.groups.nameLabel') }}</strong>
          </div>
          <div class="mc-settings-row-control">
            <input
              v-model="groupNameDialog.value"
              class="mc-settings-inline-input"
              type="text"
              :placeholder="t('contactsView.groups.namePlaceholder')"
              @keydown.enter.prevent="submitGroupNameDialog"
            >
          </div>
        </label>
      </div>
      <footer class="mc-contacts-modal-footer">
        <button class="mc-button mc-button--ghost" type="button" @click="closeGroupNameDialog">
          {{ t('common.cancel') }}
        </button>
        <button class="mc-button mc-button--primary" type="button" @click="submitGroupNameDialog">
          {{ groupNameDialog.mode === 'rename' ? t('contactsView.actions.renameGroup') : t('contactsView.actions.createGroup') }}
        </button>
      </footer>
    </section>
  </div>

  <div
    v-if="groupEditorOpen"
    class="mc-contacts-modal-backdrop"
    @click.self="closeGroupEditor"
  >
    <section class="mc-contacts-modal-sheet mc-contacts-modal-sheet--wide">
      <header class="mc-contacts-modal-header">
        <div>
          <h3>
            {{ t('contactsView.groups.editorTitle', {
              name: selectedGroup?.name || '',
              selected: groupEditorSelectionSet.size,
              visible: groupEditorVisibleContacts.length,
            }) }}
          </h3>
          <p>{{ contactGroupsScopeLabel }}</p>
        </div>
        <button class="mc-button mc-button--ghost" type="button" @click="closeGroupEditor">
          {{ t('common.close') }}
        </button>
      </header>

      <div class="mc-contacts-group-editor-controls">
        <label class="mc-settings-row mc-settings-row--contacts-search">
          <div class="mc-settings-row-label">
            <strong>{{ t('contactsView.toolset.searchLabel') }}</strong>
          </div>
          <div class="mc-settings-row-control">
            <input
              v-model="groupEditorSearchTerm"
              class="mc-settings-inline-input"
              type="text"
              :placeholder="t('contactsView.toolset.searchPlaceholder')"
              :disabled="groupEditorBusy"
            >
          </div>
        </label>
        <div class="mc-contacts-group-editor-inline">
          <label class="mc-settings-row mc-settings-row--contacts">
            <div class="mc-settings-row-label">
              <strong>{{ t('contactsView.toolset.orderLabel') }}</strong>
            </div>
            <div class="mc-settings-row-control">
              <PluginDropdown
                :model-value="groupEditorOrder"
                :options="orderOptions"
                :disabled="groupEditorBusy"
                @update:model-value="setGroupEditorOrder"
              />
            </div>
          </label>
          <label class="mc-settings-row mc-settings-row--contacts">
            <div class="mc-settings-row-label">
              <strong>{{ t('contactsView.toolset.filterLabel') }}</strong>
            </div>
            <div class="mc-settings-row-control">
              <PluginDropdown
                :model-value="groupEditorFilter"
                :options="filterOptions"
                :disabled="groupEditorBusy"
                @update:model-value="setGroupEditorFilter"
              />
            </div>
          </label>
        </div>
        <div class="mc-contacts-group-editor-actions">
          <button class="mc-button mc-button--ghost" type="button" :disabled="groupEditorBusy" @click="selectAllVisibleGroupEditorContacts">
            {{ t('contactsView.actions.selectAllVisible') }}
          </button>
          <button class="mc-button mc-button--ghost" type="button" :disabled="groupEditorBusy" @click="invertVisibleGroupEditorContacts">
            {{ t('contactsView.actions.invertSelection') }}
          </button>
          <button class="mc-button mc-button--ghost" type="button" :disabled="groupEditorBusy" @click="clearGroupEditorSelection">
            {{ t('contactsView.actions.clearSelection') }}
          </button>
        </div>
      </div>

      <div class="mc-contacts-group-editor-list">
        <label
          v-for="entry in groupEditorVisibleContacts"
          :key="`editor-${entry.key}`"
          class="mc-contacts-group-editor-row"
        >
          <input
            type="checkbox"
            :checked="groupEditorSelectionSet.has(entry.key)"
            :disabled="groupEditorBusy"
            @change="toggleGroupEditorMember(entry.key, $event.target.checked)"
          >
          <div class="mc-list-avatar" :class="{ 'is-emoji': !!entry.emoji }">
            <span>{{ entry.emoji || entry.avatar }}</span>
          </div>
          <div class="mc-list-main">
            <div class="mc-list-title-row">
              <p class="mc-list-title">
                {{ entry.title }}
                <span v-if="entry.favorite" class="mc-contacts-title-favorite" aria-hidden="true">★</span>
              </p>
            </div>
            <p class="mc-contacts-list-key">{{ entry.shortKey }}</p>
            <p class="mc-list-preview mc-contacts-list-meta">
              {{ entry.kindLabel }} · {{ entry.routeLabel }} · {{ entry.residency }}
            </p>
            <div class="mc-contacts-list-bottom-row">
              <p v-if="entry.preview" class="mc-list-preview">{{ entry.preview }}</p>
              <span class="mc-list-meta mc-contacts-list-last-seen">{{ entry.lastSeenAgo }}</span>
            </div>
          </div>
        </label>
        <div v-if="!groupEditorVisibleContacts.length" class="mc-list-empty">
          {{ t('contactsView.groups.editorEmpty') }}
        </div>
      </div>

      <footer class="mc-contacts-modal-footer">
        <button class="mc-button mc-button--ghost" type="button" :disabled="groupEditorBusy" @click="closeGroupEditor">
          {{ t('common.cancel') }}
        </button>
        <button class="mc-button mc-button--primary" type="button" :disabled="groupEditorBusy" @click="saveGroupEditorSelection">
          {{ groupEditorBusy ? t('contactsView.groups.saving') : t('common.save') }}
        </button>
      </footer>
    </section>
  </div>

  <MessagesConfirmSheet
    :model="confirmDialog"
    @close="closeConfirmDialog"
    @submit="submitConfirmDialog"
  />

  <div
    v-if="showDesktopRepeaterLoginOverlay"
    class="mc-contacts-modal-backdrop"
    @click.self="closeRepeaterLogin"
  >
    <section class="mc-contacts-modal-sheet mc-contacts-modal-sheet--narrow mc-contacts-repeater-login-sheet">
      <header class="mc-contacts-modal-header">
        <div>
          <h3>{{ t('contactsView.repeater.loginTitle') }}</h3>
          <p>
            {{ t('contactsView.repeater.loginMeta', {
              target: selectedRepeaterContact ? contactDisplayName(selectedRepeaterContact, t('messages.fallback.unnamedContact')) : shortContactPublicKey(selectedRouteContactKey),
              publicKey: selectedRepeaterContact ? shortContactPublicKey(selectedRepeaterContact) : shortContactPublicKey(selectedRouteContactKey),
            }) }}
          </p>
        </div>
        <button class="mc-button mc-button--ghost" type="button" @click="closeRepeaterLogin">
          {{ t('common.close') }}
        </button>
      </header>
      <div class="mc-contacts-modal-body">
        <div v-if="selectedRepeaterContactRow" class="mc-contacts-card mc-contacts-repeater-login-summary">
          <div class="mc-contacts-card-head">
            <div class="mc-list-avatar mc-contacts-card-avatar" :class="{ 'is-emoji': !!selectedRepeaterContactRow.emoji }">
              <span>{{ selectedRepeaterContactRow.emoji || selectedRepeaterContactRow.avatar }}</span>
            </div>
            <div class="mc-contacts-card-copy">
              <h3>{{ selectedRepeaterContactRow.title }}</h3>
              <p>{{ selectedRepeaterContactRow.kindLabel }} · {{ selectedRepeaterContactRow.residency }} · {{ selectedRepeaterContactRow.shortKey }}</p>
            </div>
          </div>
        </div>
        <p class="mc-contacts-card-note">
          {{ repeaterLoginUsesSavedAuth ? t('contactsView.repeater.savedAuthAutoLoginNote') : t('contactsView.repeater.loginMemoryNote') }}
        </p>
        <div v-if="repeaterLoginUsesSavedAuth" class="mc-contacts-repeater-login-autostate">
          {{ t('contactsView.repeater.savedAuthConnecting') }}
        </div>
        <div v-if="repeaterLoginNotice.message" class="mc-contacts-repeater-login-notice">
          {{ repeaterLoginNotice.message }}
        </div>
        <div v-if="selectedContactHasSavedRepeaterAuth" class="mc-contacts-secondary-actions">
          <button class="mc-button mc-button--ghost" type="button" :disabled="repeaterLoginBusy" @click="deleteSelectedRepeaterAuth">
            {{ t('contactsView.actions.deleteRepeaterAuth') }}
          </button>
        </div>
        <template v-else>
          <label class="mc-settings-row mc-settings-row--contacts">
            <div class="mc-settings-row-label">
              <strong>{{ t('contactsView.repeater.passwordLabel') }}</strong>
              <span>{{ t('contactsView.repeater.passwordHint') }}</span>
            </div>
            <div class="mc-settings-row-control">
              <input
                v-model="repeaterLoginPassword"
                class="mc-settings-inline-input"
                type="password"
                name="repeater-login-secret"
                autocomplete="new-password"
                autocapitalize="off"
                autocorrect="off"
                spellcheck="false"
                data-lpignore="true"
                data-1p-ignore="true"
                data-form-type="other"
                :placeholder="t('contactsView.repeater.passwordPlaceholder')"
                :disabled="repeaterLoginBusy"
                @keydown.enter.prevent="submitRepeaterLogin"
              >
            </div>
          </label>
          <div class="mc-settings-row mc-settings-row--contacts">
            <div class="mc-settings-row-label">
              <strong>{{ t('contactsView.repeater.rememberAuthLabel') }}</strong>
              <span>{{ t('contactsView.repeater.rememberAuthHint') }}</span>
            </div>
            <div class="mc-settings-row-control">
              <div class="mc-settings-checkbox">
                <input
                  v-model="repeaterLoginRememberAuth"
                  type="checkbox"
                  :disabled="repeaterLoginBusy"
                />
              </div>
            </div>
          </div>
        </template>
      </div>
      <footer class="mc-contacts-modal-footer">
        <button class="mc-button mc-button--ghost" type="button" @click="closeRepeaterLogin">
          {{ t('common.cancel') }}
        </button>
        <button
          v-if="repeaterLoginSavedAuthRetryAllowed"
          class="mc-button mc-button--primary"
          type="button"
          :disabled="repeaterLoginBusy || !selectedRepeaterContact"
          @click="submitRepeaterLogin"
        >
          {{ t('contactsView.repeater.retryLogin') }}
        </button>
        <button
          v-if="!repeaterLoginUsesSavedAuth"
          class="mc-button mc-button--primary"
          type="button"
          :disabled="repeaterLoginBusy || !selectedRepeaterContact"
          @click="submitRepeaterLogin"
        >
          {{ repeaterLoginBusy ? t('contactsView.repeater.loginBusy') : t('contactsView.repeater.loginSubmit') }}
        </button>
      </footer>
    </section>
  </div>

  <ContactsRouteEditorSheet
    :model="routeEditorModel"
    @close="closeRouteEditor"
    @update:input-value="routeEditorInput = $event"
    @update:trace-sequential="routeTraceSequential = Boolean($event)"
    @clear-input="clearRouteEditorInput"
    @toggle-public-key="toggleRouteEditorPublicKey"
    @save="saveRouteEditor"
    @reset-stored="resetStoredRouteFromEditor"
    @start-trace="startRouteTraceFromEditor"
    @cancel-trace="cancelActiveRouteTrace('user-cancelled')"
  />

  <ContactsRepeaterGeoSheet
    :model="repeaterGeoSheetModel"
    @close="closeRepeaterGeoSheet"
    @pick="applyRepeaterGeoFromMap"
  />
</template>
