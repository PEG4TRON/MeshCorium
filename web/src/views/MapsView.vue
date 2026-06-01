<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useStorage } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import {
  MAP_PROVIDER_OFM_LIBERTY,
  MAP_PROVIDER_OPTIONS,
  MAP_STYLE_BOOT_TIMEOUT_MS,
  buildFallbackMapStyle,
  buildSelectedMapStyle,
  ensureMapLibreLoaded,
  normalizeMapProvider,
  shouldFallbackToRasterMapStyle,
  tileTransformRequest,
} from '../lib/mapLibre'
import { extractValidGeoPoint, geoDistanceKm, isGeoWithinHomeDistance, safeCoordinate as safeGeoCoordinate, HOME_NODE_GEO_MAX_DISTANCE_KM } from '../lib/geo'
import { resolveNodePreviewUrl } from '../lib/nodePreview'
import { useIsMobile } from '../composables/useIsMobile'
import ShellPageFrame from '../components/layout/ShellPageFrame.vue'
import ShellPhonebar from '../components/layout/ShellPhonebar.vue'
import PluginDropdown from '../components/ui/PluginDropdown.vue'
import { useSessionStore } from '../stores/session'
import { filterStatusTextForTransport } from '../lib/statusText'

const session = useSessionStore()
const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()

const MAP_MIN_ZOOM = 1
const MAP_MAX_ZOOM = 18
const MAP_DEFAULT_BOUNDS = {
  minLat: 55.55,
  maxLat: 55.95,
  minLon: 37.35,
  maxLon: 37.85,
}
const MAP_MAIN_PATH = '/maps'
const MAP_TRACE_PATH = '/maps/route-checks'
const geoIconUrl = '/icons/geo.svg'

const mapViewportRef = ref(null)
const mapInstance = ref(null)
const mapMarkers = ref([])
const mapReady = ref(false)
const mapLoading = ref(false)
const mapError = ref('')
const contactsLoading = ref(false)
const viewportMode = ref('all')
const manualView = ref(null)
const emojiMarkersEnabled = useStorage('maps_emoji_markers_enabled', false)
const mapThemeMode = useStorage('maps_theme_mode', 'light')
const selectedMapProvider = computed(() => normalizeMapProvider(session.settingsPayload?.settings?.map_provider))
const mapProviderOptions = computed(() => MAP_PROVIDER_OPTIONS)
const mapMaxDistanceKm = computed(() => {
  const raw = session.settingsPayload?.settings?.map_max_distance_km
  const parsed = parseInt(raw, 10)
  return Number.isFinite(parsed) && parsed >= 1 ? parsed : HOME_NODE_GEO_MAX_DISTANCE_KM
})
const traceSelectedKeys = ref([])
const traceManualInput = ref('')
const traceSequential = ref(true)
const traceHashLen = ref(2)
const traceBusy = ref(false)
const traceJobId = ref('')
const traceResult = ref(null)
const tracePickerOpen = ref(false)
const tracePickerSearch = ref('')
const rulerPoints = ref([])
const mapContextMenu = ref({
  open: false,
  x: 0,
  y: 0,
  lat: null,
  lon: null,
  kind: 'map',
  rulerPointId: null,
})
const scrollerMode = ref('main')

const { isMobile } = useIsMobile()
const mobileScrollerOpen = ref(false)

function toggleMobileScroller() {
  mobileScrollerOpen.value = !mobileScrollerOpen.value
}
function closeMobileScroller() {
  mobileScrollerOpen.value = false
}

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
  return filterStatusTextForTransport(session.statusText, session.selectedTransportType) || serviceStatusCopy.value
})

const channelCountSummary = computed(() => {
  const visibleCount = Math.max(0, Number(session.sessionSnapshot?.channels_count || 0))
  return { visibleCount, totalSlots: Math.max(0, Number(session.device?.max_channels || 0)) }
})
const contactCountSummary = computed(() => {
  const summary = session.sessionSnapshot?.contact_summary || {}
  return {
    nodeResident: Math.max(0, Number(summary?.node_resident || 0)),
    nodeLimit: Math.max(0, Number(summary?.node_limit || 0)),
    dbTotal: Math.max(0, Number(summary?.db_total || 0)),
  }
})

const normalizedMapThemeMode = computed(() => {
  return String(mapThemeMode.value || '').trim().toLowerCase() === 'dark' ? 'dark' : 'light'
})

const mapThemeToggleLabel = computed(() => {
  return normalizedMapThemeMode.value === 'dark'
    ? t('maps.controls.themeDark')
    : t('maps.controls.themeLight')
})

const mapThemeToggleTooltip = computed(() => {
  return normalizedMapThemeMode.value === 'dark'
    ? t('maps.controls.switchToLight')
    : t('maps.controls.switchToDark')
})

let resizeObserver = null
let ignoreMoveEndUntil = 0
let mapMountPromise = null
let mapBootTimerId = 0
let mapMountToken = 0
let traceEventSource = null
let routeOverlayFrame = 0
let rulerPointIdSeq = 0
let activeMapPopup = null
let lastMarkerSyncSignature = ''
let lastAppliedRouteFocusSignature = ''
let lastOpenedRouteFocusPopupSignature = ''

function clearMapBootTimer() {
  if (!mapBootTimerId) {
    return
  }
  window.clearTimeout(mapBootTimerId)
  mapBootTimerId = 0
}

function cancelRouteOverlayFrame() {
  if (!routeOverlayFrame) {
    return
  }
  window.cancelAnimationFrame(routeOverlayFrame)
  routeOverlayFrame = 0
}

function closeMapContextMenu() {
  mapContextMenu.value = {
    open: false,
    x: 0,
    y: 0,
    lat: null,
    lon: null,
    kind: 'map',
    rulerPointId: null,
  }
}

function clampContextMenuPosition(rawX, rawY, menuWidth, menuHeight) {
  const viewportEl = mapViewportRef.value
  if (!viewportEl) {
    return { x: 12, y: 12 }
  }
  const bounds = viewportEl.getBoundingClientRect()
  return {
    x: Math.max(12, Math.min(Math.max(12, bounds.width - menuWidth - 12), rawX)),
    y: Math.max(12, Math.min(Math.max(12, bounds.height - menuHeight - 12), rawY)),
  }
}

function openMapPointContextMenu(event) {
  const position = clampContextMenuPosition(
    Number(event?.point?.x ?? 0),
    Number(event?.point?.y ?? 0),
    210,
    124,
  )
  mapContextMenu.value = {
    open: true,
    x: position.x,
    y: position.y,
    lat: clampMapLatitude(Number(event?.lngLat?.lat)),
    lon: normalizeMapLongitude(Number(event?.lngLat?.lng)),
    kind: 'map',
    rulerPointId: null,
  }
}

function openRulerPointContextMenu(point, event) {
  const viewportEl = mapViewportRef.value
  if (!viewportEl) {
    return
  }
  const bounds = viewportEl.getBoundingClientRect()
  const position = clampContextMenuPosition(
    Number(event?.clientX ?? 0) - bounds.left,
    Number(event?.clientY ?? 0) - bounds.top,
    210,
    86,
  )
  mapContextMenu.value = {
    open: true,
    x: position.x,
    y: position.y,
    lat: clampMapLatitude(Number(point?.lat)),
    lon: normalizeMapLongitude(Number(point?.lon)),
    kind: 'ruler-point',
    rulerPointId: Number(point?.id || 0) || null,
  }
}

function toggleMapThemeMode() {
  mapThemeMode.value = normalizedMapThemeMode.value === 'dark' ? 'light' : 'dark'
}

async function openTraceScroller() {
  await syncScrollerRoute('trace', { replace: false })
}

async function closeTraceScroller() {
  const historyBackPath = typeof window !== 'undefined'
    ? String(window.history.state?.back || '').trim()
    : ''
  if (historyBackPath === MAP_MAIN_PATH) {
    await router.back()
    return
  }
  await syncScrollerRoute('main', { replace: true })
}

function routePathToScrollerMode(pathname) {
  return String(pathname || '').trim() === MAP_TRACE_PATH ? 'trace' : 'main'
}

function syncScrollerModeFromRoute() {
  const nextMode = routePathToScrollerMode(route.path)
  if (scrollerMode.value !== nextMode) {
    scrollerMode.value = nextMode
  }
}

async function syncScrollerRoute(nextMode = scrollerMode.value, options = {}) {
  const normalizedMode = nextMode === 'trace' ? 'trace' : 'main'
  const nextPath = normalizedMode === 'trace' ? MAP_TRACE_PATH : MAP_MAIN_PATH
  if (String(route.path || '') === nextPath) {
    if (scrollerMode.value !== normalizedMode) {
      scrollerMode.value = normalizedMode
    }
    return
  }
  scrollerMode.value = normalizedMode
  const navigate = options?.replace ? router.replace : router.push
  await navigate({
    path: nextPath,
    query: route.query,
  })
}

function normalizePublicKey(value) {
  return String(value || '').trim().toLowerCase()
}

function routeTokensFromInput(value) {
  return String(value || '')
    .split(',')
    .map((item) => String(item || '').trim().toUpperCase())
    .filter(Boolean)
}

const safeCoordinate = safeGeoCoordinate

function clampMapLatitude(lat) {
  return Math.max(-85.05112878, Math.min(85.05112878, lat))
}

function normalizeMapLongitude(lon) {
  return ((((lon + 180) % 360) + 360) % 360) - 180
}

function formatDistance(distanceKm) {
  const numericDistanceKm = Number(distanceKm)
  if (!Number.isFinite(numericDistanceKm)) {
    return ''
  }
  const activeLocale = String(locale.value || 'ru')
  if (numericDistanceKm < 1) {
    return `${new Intl.NumberFormat(activeLocale, { maximumFractionDigits: 0 }).format(Math.round(numericDistanceKm * 1000))} м`
  }
  let maximumFractionDigits = 2
  if (numericDistanceKm >= 10) {
    maximumFractionDigits = 1
  }
  if (numericDistanceKm >= 100) {
    maximumFractionDigits = 0
  }
  return `${new Intl.NumberFormat(activeLocale, { minimumFractionDigits: 0, maximumFractionDigits }).format(numericDistanceKm)} км`
}

function contactDisplayName(contact) {
  return String(contact?.adv_name || contact?.name || contact?.pubkey_prefix || contact?.public_key || '').trim() || t('messages.fallback.unnamedContact')
}

function firstEmojiInText(value) {
  const text = String(value || '').trim()
  if (!text) {
    return ''
  }
  const match = text.match(/(\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?(?:\u200D\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?)*)/u)
  return match ? match[1] : ''
}

function pointLabel(point) {
  if (point.kind === 'self') {
    return t('maps.legend.self')
  }
  if (point.kind === 'repeater') {
    return t('maps.legend.repeater')
  }
  return t('maps.legend.contact')
}

function pointSortScore(point) {
  if (point.kind === 'self') return 0
  if (point.favorite) return 1
  if (point.kind === 'repeater') return 2
  return 3
}

const nodeDisplayName = computed(() => {
  return String(session.self?.name || session.device?.manufacturer_model || '').trim() || t('common.unknownNode')
})

const selfPreviewUrl = computed(() => {
  return resolveNodePreviewUrl(session.device?.manufacturer_model || session.self?.name || '')
})

const hasSelfCoordinates = computed(() => {
  return Boolean(extractValidGeoPoint(session.self))
})

const mapPoints = computed(() => {
  const homePoint = extractValidGeoPoint(session.self)
  const points = []
  for (const contact of Array.isArray(session.contacts) ? session.contacts : []) {
    const coords = extractValidGeoPoint(contact)
    if (!coords || !isGeoWithinHomeDistance(coords, homePoint, mapMaxDistanceKm.value)) {
      continue
    }
    const publicKey = normalizePublicKey(contact?.public_key)
    const displayName = contactDisplayName(contact)
    points.push({
      key: publicKey || `contact:${normalizePublicKey(contact?.pubkey_prefix || displayName)}`,
      kind: Number(contact?.adv_type || 0) === 2 ? 'repeater' : 'contact',
      favorite: Boolean(contact?.is_favorite),
      lat: coords.lat,
      lon: coords.lon,
      label: displayName,
      displayName,
      publicKey,
      shortPublicKey: String(contact?.pubkey_prefix || '').trim().slice(0, 4).toUpperCase(),
      emoji: firstEmojiInText(displayName),
      updatedAt: Number(contact?.updated_at || contact?.last_interaction_at || contact?.last_advert || 0),
    })
  }
  if (homePoint) {
    points.push({
      key: 'self',
      kind: 'self',
      favorite: false,
      lat: homePoint.lat,
      lon: homePoint.lon,
      label: nodeDisplayName.value,
      displayName: nodeDisplayName.value,
      publicKey: normalizePublicKey(session.self?.public_key),
      shortPublicKey: '',
      emoji: '',
      previewUrl: selfPreviewUrl.value,
      updatedAt: 0,
    })
  }
  return points
})

const favoritePointCount = computed(() => mapPoints.value.filter((point) => point.favorite).length)
const traceCandidatePoints = computed(() => {
  return mapPoints.value
    .filter((point) => point.kind === 'repeater' && point.publicKey)
    .slice()
    .sort((left, right) => {
      const scoreDiff = pointSortScore(left) - pointSortScore(right)
      if (scoreDiff !== 0) {
        return scoreDiff
      }
      if (left.favorite !== right.favorite) {
        return left.favorite ? -1 : 1
      }
      return String(left.displayName || '').localeCompare(String(right.displayName || ''))
    })
})

const filteredTracePickerPoints = computed(() => {
  const needle = String(tracePickerSearch.value || '').trim().toLowerCase()
  if (!needle) {
    return traceCandidatePoints.value
  }
  return traceCandidatePoints.value.filter((point) => {
    return String(point.displayName || '').toLowerCase().includes(needle)
      || String(point.shortPublicKey || '').toLowerCase().includes(needle)
      || String(point.publicKey || '').toLowerCase().includes(needle)
  })
})

const repeaterMapPoints = computed(() => {
  return mapPoints.value.filter((point) => point.kind === 'repeater')
})

const activeMessageRoute = computed(() => {
  if (String(route.query.route_source || '') !== 'message') {
    return null
  }
  const hops = String(route.query.route_hops || '')
    .split(',')
    .map((hop) => String(hop || '').trim().toUpperCase())
    .filter(Boolean)
  if (!hops.length) {
    return null
  }
  return {
    hops,
    preview: String(route.query.route_preview || '').trim(),
    messageId: Number(route.query.route_message_id || 0) || 0,
    conversationKind: String(route.query.route_conversation_kind || '').trim() || 'channel',
  }
})

const activeMessageRouteModel = computed(() => {
  const payload = activeMessageRoute.value
  if (!payload) {
    return null
  }
  const repeaterPoints = repeaterMapPoints.value
  const routeEntries = payload.hops.map((hop, index) => {
    const visiblePoints = repeaterPoints.filter((point) => point.publicKey.startsWith(String(hop || '').toLowerCase()))
    return {
      hop,
      displayHop: hop.slice(0, 4) || hop,
      index,
      visiblePoints,
      primaryVisiblePoint: visiblePoints[0] || null,
    }
  })
  const knownRoutePoints = []
  const selfPoint = mapPoints.value.find((point) => point.kind === 'self') || null
  if (selfPoint) {
    knownRoutePoints.push(selfPoint)
  }
  for (const entry of routeEntries) {
    if (entry.primaryVisiblePoint) {
      knownRoutePoints.push(entry.primaryVisiblePoint)
    }
  }
  const dedupedKnownRoutePoints = [...new Map(
    knownRoutePoints.map((point) => [String(point.key || point.publicKey || ''), point]),
  ).values()]
  const visibleEntries = routeEntries.filter((entry) => entry.primaryVisiblePoint)
  const routeSegments = []
  for (let index = 1; index < visibleEntries.length; index += 1) {
    const previous = visibleEntries[index - 1]
    const current = visibleEntries[index]
    routeSegments.push({
      from: previous.primaryVisiblePoint,
      to: current.primaryVisiblePoint,
      kind: Math.max(0, current.index - previous.index - 1) > 0 ? 'gap' : 'route',
    })
  }
  if (selfPoint && visibleEntries.length) {
    const lastEntry = visibleEntries[visibleEntries.length - 1]
    routeSegments.push({
      from: lastEntry.primaryVisiblePoint,
      to: selfPoint,
      kind: Math.max(0, routeEntries.length - lastEntry.index - 1) > 0 ? 'gap' : 'route',
    })
  }
  return {
    ...payload,
    routeEntries,
    knownRoutePoints: dedupedKnownRoutePoints,
    routeSegments,
  }
})

const contactLocationCount = computed(() => {
  const homePoint = extractValidGeoPoint(session.self)
  return (Array.isArray(session.contacts) ? session.contacts : []).reduce((sum, contact) => {
    const coords = extractValidGeoPoint(contact)
    if (!coords || !isGeoWithinHomeDistance(coords, homePoint, mapMaxDistanceKm.value)) {
      return sum
    }
    return sum + 1
  }, 0)
})

const currentMapCenter = computed(() => {
  if (manualView.value && Number.isFinite(manualView.value.lat) && Number.isFinite(manualView.value.lon)) {
    return {
      lat: clampMapLatitude(Number(manualView.value.lat)),
      lon: normalizeMapLongitude(Number(manualView.value.lon)),
    }
  }
  return {
    lat: clampMapLatitude(Number(mapViewport.value.center.lat)),
    lon: normalizeMapLongitude(Number(mapViewport.value.center.lon)),
  }
})

const routeFocusTarget = computed(() => {
  const lat = Number(route.query.focus_lat)
  const lon = Number(route.query.focus_lon)
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return null
  }
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) {
    return null
  }
  return {
    lat,
    lon,
    key: normalizePublicKey(route.query.focus_key),
    label: String(route.query.focus_label || '').trim(),
  }
})

const viewportSignature = computed(() => {
  return mapPoints.value
    .map((point) => `${point.key}:${point.lat.toFixed(5)}:${point.lon.toFixed(5)}:${point.favorite ? 1 : 0}:${point.emoji}`)
    .join('|')
})

const selectedTracePoints = computed(() => {
  const candidateMap = new Map(
    traceCandidatePoints.value.map((point) => [normalizePublicKey(point.publicKey), point]),
  )
  return traceSelectedKeys.value
    .map((value) => candidateMap.get(normalizePublicKey(value)) || null)
    .filter(Boolean)
})

const traceRouteOverlayModel = computed(() => {
  const selfPoint = mapPoints.value.find((point) => point.kind === 'self') || null
  const routePoints = []
  if (selfPoint) {
    routePoints.push(selfPoint)
  }
  routePoints.push(...selectedTracePoints.value)
  return {
    routePoints,
    hasSelfPoint: Boolean(selfPoint),
  }
})

const routeTraceQuerySelection = computed(() => {
  return String(route.query.route_public_keys || '')
    .split(',')
    .map((value) => normalizePublicKey(value))
    .filter(Boolean)
})

const traceStepModels = computed(() => {
  const steps = Array.isArray(traceResult.value?.steps) ? traceResult.value.steps : []
  return steps.map((step) => {
    const prefixHops = Number(step?.prefix_hops || 0) || 0
    const pending = Boolean(step?.pending)
    const success = !pending && Boolean(step?.success)
    const failed = !pending && !success
    const participants = selectedTracePoints.value.slice(0, prefixHops)
    const participantLabel = participants.length
      ? participants.map((point) => point.displayName).join(' → ')
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

const traceStatusSummary = computed(() => {
  if (traceBusy.value) {
    return traceResult.value?.status === 'queued'
      ? t('maps.trace.status.queued')
      : t('maps.trace.status.running')
  }
  if (!traceResult.value) {
    return t('maps.trace.status.idle')
  }
  if (traceResult.value.status === 'cancelled') {
    return t('maps.trace.status.cancelled')
  }
  if (traceResult.value.status === 'error') {
    return traceResult.value.error || t('maps.trace.status.error')
  }
  if (traceResult.value.success) {
    return t('maps.trace.status.success', { hops: Number(traceResult.value.hop_count || 0) })
  }
  const failureAtHop = Number(traceResult.value.failure_at_hop || 0) || 0
  return t('maps.trace.status.failed', { hop: failureAtHop || '?' })
})

const traceLineBadges = computed(() => {
  const model = traceRouteOverlayModel.value
  const tracedSegmentCount = Math.max(0, model.routePoints.length - (model.hasSelfPoint ? 1 : 0))
  if (!tracedSegmentCount || !traceResult.value) {
    return []
  }
  const steps = Array.isArray(traceResult.value.steps) ? traceResult.value.steps : []
  if (!steps.length) {
    return []
  }
  if (traceResult.value.sequential) {
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

const rulerSegmentModels = computed(() => {
  const points = Array.isArray(rulerPoints.value) ? rulerPoints.value : []
  const segments = []
  let totalDistanceKm = 0
  for (let index = 1; index < points.length; index += 1) {
    const from = points[index - 1]
    const to = points[index]
    const distanceKm = geoDistanceKm(from, to)
    if (distanceKm == null) {
      continue
    }
    totalDistanceKm += distanceKm
    segments.push({
      key: `segment:${from.id}:${to.id}`,
      fromId: from.id,
      toId: to.id,
      label: `${formatDistance(distanceKm)} (${formatDistance(totalDistanceKm)})`,
    })
  }
  return segments
})

const mapViewport = computed(() => {
  const allPoints = mapPoints.value
  const points = scrollerMode.value === 'trace'
    ? allPoints.filter((point) => point.kind === 'repeater' || point.kind === 'self')
    : allPoints
  const selfPoint = allPoints.find((point) => point.kind === 'self') || null
  const preferSelf = viewportMode.value === 'self' && selfPoint
  let minLat = MAP_DEFAULT_BOUNDS.minLat
  let maxLat = MAP_DEFAULT_BOUNDS.maxLat
  let minLon = MAP_DEFAULT_BOUNDS.minLon
  let maxLon = MAP_DEFAULT_BOUNDS.maxLon

  if (preferSelf) {
    let halfLatSpan = 0.0135
    let halfLonSpan = 0.02
    if (points.length) {
      const farthestLat = Math.max(...points.map((point) => Math.abs(point.lat - selfPoint.lat)))
      const farthestLon = Math.max(...points.map((point) => Math.abs(point.lon - selfPoint.lon)))
      halfLatSpan = Math.max(0.0135, farthestLat * 1.2)
      halfLonSpan = Math.max(0.02, farthestLon * 1.2)
    }
    minLat = Math.max(-85, selfPoint.lat - halfLatSpan)
    maxLat = Math.min(85, selfPoint.lat + halfLatSpan)
    minLon = Math.max(-180, selfPoint.lon - halfLonSpan)
    maxLon = Math.min(180, selfPoint.lon + halfLonSpan)
  } else if (points.length) {
    minLat = Math.min(...points.map((point) => point.lat))
    maxLat = Math.max(...points.map((point) => point.lat))
    minLon = Math.min(...points.map((point) => point.lon))
    maxLon = Math.max(...points.map((point) => point.lon))
    const latSpan = Math.max(0.08, maxLat - minLat)
    const lonSpan = Math.max(0.08, maxLon - minLon)
    const latPad = Math.min(20, latSpan * 0.35)
    const lonPad = Math.min(20, lonSpan * 0.35)
    minLat = Math.max(-85, minLat - latPad)
    maxLat = Math.min(85, maxLat + latPad)
    minLon = Math.max(-180, minLon - lonPad)
    maxLon = Math.min(180, maxLon + lonPad)
  }

  const viewportWidth = Math.max(360, Number(mapViewportRef.value?.clientWidth || 960))
  const viewportHeight = Math.max(240, Number(mapViewportRef.value?.clientHeight || 640))
  const lonSpan = Math.max(0.0001, Math.abs(maxLon - minLon))
  const latSpan = Math.max(0.0001, Math.abs(maxLat - minLat))
  const zoomX = Math.log2((viewportWidth * 360) / (lonSpan * 256))
  const zoomY = Math.log2((viewportHeight * 170) / (latSpan * 256))
  const recommendedZoom = preferSelf
    ? 13
    : (
      points.length <= 1
        ? 11
        : Math.floor(Math.min(zoomX, zoomY))
    )
  const centerLat = preferSelf ? clampMapLatitude(selfPoint.lat) : clampMapLatitude((minLat + maxLat) / 2)
  const centerLon = preferSelf ? normalizeMapLongitude(selfPoint.lon) : normalizeMapLongitude((minLon + maxLon) / 2)
  const zoom = Math.max(
    MAP_MIN_ZOOM,
    Math.min(
      MAP_MAX_ZOOM,
      Number.isFinite(manualView.value?.zoom) ? manualView.value.zoom : recommendedZoom,
    ),
  )

  return {
    points,
    center: {
      lat: clampMapLatitude(Number.isFinite(manualView.value?.lat) ? manualView.value.lat : centerLat),
      lon: normalizeMapLongitude(Number.isFinite(manualView.value?.lon) ? manualView.value.lon : centerLon),
    },
    zoom,
    bounds: [
      [Math.max(-180, minLon), Math.max(-85, minLat)],
      [Math.min(180, maxLon), Math.min(85, maxLat)],
    ],
  }
})

function clearMarkers() {
  if (activeMapPopup) {
    try {
      activeMapPopup.remove()
    } catch (error) {
      console.error('[meshcorium] map-popup-remove', {
        message: error instanceof Error ? error.message : String(error || 'unknown'),
      })
    }
  }
  activeMapPopup = null
  for (const marker of mapMarkers.value) {
    try {
      marker.remove()
    } catch (error) {
      console.error('[meshcorium] map-marker-remove', {
        message: error instanceof Error ? error.message : String(error || 'unknown'),
      })
    }
  }
  mapMarkers.value = []
  lastMarkerSyncSignature = ''
}

function destroyMap() {
  mapMountToken += 1
  mapMountPromise = null
  clearMapBootTimer()
  cancelRouteOverlayFrame()
  mapViewportRef.value?.querySelector('.mc-map-route-overlay')?.remove()
  mapViewportRef.value?.querySelector('.mc-map-ruler-overlay')?.remove()
  clearMarkers()
  if (mapInstance.value) {
    try {
      mapInstance.value.remove()
    } catch (error) {
      console.error('[meshcorium] map-remove', {
        message: error instanceof Error ? error.message : String(error || 'unknown'),
      })
    }
  }
  mapInstance.value = null
  mapReady.value = false
  mapLoading.value = false
}

function scheduleProgrammaticMove(durationMs = 320) {
  ignoreMoveEndUntil = Date.now() + durationMs
}

function buildMarkerElement(point) {
  const element = document.createElement('button')
  element.type = 'button'
  element.className = `mc-map-marker mc-map-marker--${point.kind}`
  element.setAttribute('aria-label', String(point.displayName || point.label || point.kind))
  if (point.favorite) {
    element.classList.add('is-favorite')
  }
  if (scrollerMode.value === 'trace' && traceSelectedKeys.value.includes(normalizePublicKey(point.publicKey))) {
    element.classList.add('is-trace-selected')
  }
  if (point.kind === 'self' && point.previewUrl) {
    const preview = document.createElement('img')
    preview.className = 'mc-map-marker-preview'
    preview.src = point.previewUrl
    preview.alt = ''
    element.appendChild(preview)
    return element
  }
  if (emojiMarkersEnabled.value && point.kind !== 'self' && point.emoji) {
    const emoji = document.createElement('span')
    emoji.className = 'mc-map-marker-emoji'
    emoji.textContent = point.emoji
    element.appendChild(emoji)
    return element
  }
  const dot = document.createElement('span')
  dot.className = 'mc-map-marker-dot'
  element.appendChild(dot)
  return element
}

function buildPopup(point) {
  if (!window.maplibregl) {
    return null
  }
  const popupHost = document.createElement('div')
  popupHost.className = 'mc-map-popup'

  const title = document.createElement('div')
  title.className = 'mc-map-popup-title'
  title.textContent = String(point.displayName || point.label || point.kind)
  popupHost.appendChild(title)

  const meta = document.createElement('div')
  meta.className = 'mc-map-popup-meta'
  meta.textContent = pointLabel(point)
  popupHost.appendChild(meta)

  if (point.shortPublicKey) {
    const keyLine = document.createElement('div')
    keyLine.className = 'mc-map-popup-key'
    keyLine.textContent = point.shortPublicKey
    popupHost.appendChild(keyLine)
  }

  if (point.kind !== 'self') {
    const actions = document.createElement('div')
    actions.className = 'mc-map-popup-actions'

    if (point.kind === 'contact' && point.publicKey) {
      const chatButton = document.createElement('button')
      chatButton.type = 'button'
      chatButton.className = 'mc-map-popup-action-button'
      chatButton.textContent = t('maps.popup.openChat')
      chatButton.addEventListener('click', (event) => {
        event.preventDefault()
        event.stopPropagation()
        openContactChatFromMap(point.publicKey).catch((error) => {
          session.setStatus(error instanceof Error ? error.message : String(error || t('maps.status.chatOpenFailed')), true)
        })
      })
      actions.appendChild(chatButton)
    }

    const rulerButton = document.createElement('button')
    rulerButton.type = 'button'
    rulerButton.className = 'mc-map-popup-action-button'
    rulerButton.textContent = t('maps.popup.ruler')
    rulerButton.addEventListener('click', (event) => {
      event.preventDefault()
      event.stopPropagation()
      addMapPointToRuler(point)
    })
    actions.appendChild(rulerButton)

    popupHost.appendChild(actions)
  }

  return new window.maplibregl.Popup({
    closeButton: false,
    closeOnClick: true,
    offset: 18,
    className: 'mc-map-popup-shell',
  }).setDOMContent(popupHost)
}

async function openContactChatFromMap(publicKey) {
  const normalized = normalizePublicKey(publicKey)
  if (!normalized) {
    return
  }
  await router.push({
    path: '/messages',
    query: { contact: normalized },
  })
}

function nextRulerPointId() {
  rulerPointIdSeq += 1
  return rulerPointIdSeq
}

function appendRulerPoint(lat, lon) {
  return {
    id: nextRulerPointId(),
    lat,
    lon,
  }
}

function addMapPointToRuler(point) {
  const lat = Number(point?.lat)
  const lon = Number(point?.lon)
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return
  }
  const nextPoints = Array.isArray(rulerPoints.value) ? [...rulerPoints.value] : []
  if (!nextPoints.length) {
    const selfCoords = extractValidGeoPoint(session.self)
    if (!selfCoords) {
      session.setStatus(t('maps.status.selfLocationMissing'), true)
      return
    }
    nextPoints.push(appendRulerPoint(selfCoords.lat, selfCoords.lon))
  }
  nextPoints.push(appendRulerPoint(lat, lon))
  rulerPoints.value = nextPoints
  activeMapPopup?.remove()
}

function buildMarkerSyncSignature() {
  return [
    scrollerMode.value,
    emojiMarkersEnabled.value ? 'emoji' : 'dot',
    traceSelectedKeys.value.join(','),
    mapViewport.value.points
      .map((point) => [
        point.key,
        point.kind,
        point.favorite ? 1 : 0,
        point.lat.toFixed(5),
        point.lon.toFixed(5),
        point.emoji,
      ].join(':'))
      .join('|'),
  ].join('::')
}

function openMarkerPopup(marker, point) {
  if (!mapInstance.value || !window.maplibregl || !point) {
    return false
  }
  if (activeMapPopup) {
    try {
      activeMapPopup.remove()
    } catch (error) {
      console.error('[meshcorium] map-popup-replace', {
        message: error instanceof Error ? error.message : String(error || 'unknown'),
      })
    }
    activeMapPopup = null
  }
  const popup = buildPopup(point)
  if (!popup) {
    return false
  }
  if (typeof popup.on === 'function') {
    popup.on('close', () => {
      if (activeMapPopup === popup) {
        activeMapPopup = null
      }
    })
  }
  popup.setLngLat([point.lon, point.lat]).addTo(mapInstance.value)
  activeMapPopup = popup
  return true
}

function syncMarkers() {
  if (!mapInstance.value || !window.maplibregl) {
    return
  }
  const signature = buildMarkerSyncSignature()
  if (signature === lastMarkerSyncSignature && mapMarkers.value.length === mapViewport.value.points.length) {
    return
  }
  clearMarkers()
  mapMarkers.value = mapViewport.value.points.map((point) => {
    const marker = new window.maplibregl.Marker({
      element: buildMarkerElement(point),
      anchor: 'center',
    }).setLngLat([point.lon, point.lat])
    marker.__meshcoriumPointKey = point.key
    marker.__meshcoriumPointData = point
    if (scrollerMode.value === 'trace' && point.kind === 'repeater') {
      marker.getElement()?.addEventListener('click', (event) => {
        event.preventDefault()
        event.stopPropagation()
        toggleTracePoint(point)
      })
    } else {
      marker.getElement()?.addEventListener('click', (event) => {
        event.preventDefault()
        event.stopPropagation()
        openMarkerPopup(marker, point)
      })
    }
    marker.addTo(mapInstance.value)
    return marker
  })
  lastMarkerSyncSignature = signature
}

function buildRouteOverlayPath(points) {
  if (!mapInstance.value || !Array.isArray(points) || points.length < 2) {
    return ''
  }
  const commands = []
  for (let index = 0; index < points.length; index += 1) {
    const point = points[index]
    const projected = mapInstance.value.project([point.lon, point.lat])
    const x = Number(projected?.x)
    const y = Number(projected?.y)
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return ''
    }
    commands.push(`${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`)
  }
  return commands.join(' ')
}

function buildRulerPointProjection(point) {
  if (!mapInstance.value) {
    return null
  }
  const projected = mapInstance.value.project([point.lon, point.lat])
  const x = Number(projected?.x)
  const y = Number(projected?.y)
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return null
  }
  return { x, y }
}

function renderMessageRouteOverlay() {
  const viewport = mapViewportRef.value
  const messageModel = activeMessageRouteModel.value
  const traceModel = scrollerMode.value === 'trace' ? traceRouteOverlayModel.value : null
  if (!viewport) {
    return
  }
  viewport.querySelector('.mc-map-route-overlay')?.remove()
  if (!mapInstance.value) {
    return
  }
  const width = Math.max(1, Number(viewport.clientWidth || 0))
  const height = Math.max(1, Number(viewport.clientHeight || 0))
  const svgNS = 'http://www.w3.org/2000/svg'
  const svg = document.createElementNS(svgNS, 'svg')
  svg.setAttribute('class', 'mc-map-route-overlay')
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`)
  svg.setAttribute('width', String(width))
  svg.setAttribute('height', String(height))
  let hasPaths = false
  if (messageModel?.knownRoutePoints.length) {
    for (const segment of messageModel.routeSegments) {
      const pathData = buildRouteOverlayPath([segment.from, segment.to])
      if (!pathData) {
        continue
      }
      const base = document.createElementNS(svgNS, 'path')
      base.setAttribute('class', 'mc-map-route-line-base')
      base.setAttribute('d', pathData)
      svg.appendChild(base)
      const flow = document.createElementNS(svgNS, 'path')
      flow.setAttribute('class', segment.kind === 'gap' ? 'mc-map-route-line-gap' : 'mc-map-route-line-flow')
      flow.setAttribute('d', pathData)
      svg.appendChild(flow)
      hasPaths = true
    }
  } else if (traceModel?.routePoints.length > 1) {
    for (let index = 0; index < traceModel.routePoints.length - 1; index += 1) {
      const from = traceModel.routePoints[index]
      const to = traceModel.routePoints[index + 1]
      const pathData = buildRouteOverlayPath([from, to])
      if (!pathData) {
        continue
      }
      const traceBadge = traceLineBadges.value.find((entry) => entry.segmentIndex === index) || null
      const base = document.createElementNS(svgNS, 'path')
      base.setAttribute('class', 'mc-map-trace-line-base')
      if (traceBadge?.failed) {
        base.classList.add('failed')
      }
      base.setAttribute('d', pathData)
      svg.appendChild(base)
      const flow = document.createElementNS(svgNS, 'path')
      flow.setAttribute('class', 'mc-map-trace-line-flow')
      if (traceBadge?.failed) {
        flow.classList.add('failed')
      }
      flow.setAttribute('d', pathData)
      svg.appendChild(flow)
      hasPaths = true
      if (!traceBadge) {
        continue
      }
      const start = mapInstance.value.project([from.lon, from.lat])
      const end = mapInstance.value.project([to.lon, to.lat])
      if (!Number.isFinite(Number(start?.x)) || !Number.isFinite(Number(start?.y)) || !Number.isFinite(Number(end?.x)) || !Number.isFinite(Number(end?.y))) {
        continue
      }
      const midX = (start.x + end.x) / 2
      const midY = (start.y + end.y) / 2
      appendTraceBadgeStack(svg, midX, midY, traceBadge.rxLabel, traceBadge.txLabel)
    }
  }
  if (hasPaths) {
    viewport.appendChild(svg)
  }

  viewport.querySelector('.mc-map-ruler-overlay')?.remove()
  if (!rulerPoints.value.length) {
    return
  }
  const rulerOverlay = document.createElement('div')
  rulerOverlay.className = 'mc-map-ruler-overlay'
  const rulerSvg = document.createElementNS(svgNS, 'svg')
  rulerSvg.setAttribute('class', 'mc-map-ruler-svg')
  rulerSvg.setAttribute('viewBox', `0 0 ${width} ${height}`)
  rulerSvg.setAttribute('width', String(width))
  rulerSvg.setAttribute('height', String(height))
  const labelLayer = document.createElement('div')
  labelLayer.className = 'mc-map-ruler-label-layer'
  const pointLayer = document.createElement('div')
  pointLayer.className = 'mc-map-ruler-point-layer'
  const projectedPointMap = new Map()

  for (const point of rulerPoints.value) {
    const projection = buildRulerPointProjection(point)
    if (!projection) {
      continue
    }
    projectedPointMap.set(point.id, projection)
    const pointButton = document.createElement('button')
    pointButton.type = 'button'
    pointButton.className = 'mc-map-ruler-point'
    pointButton.setAttribute('aria-label', t('maps.ruler.pointLabel'))
    pointButton.style.left = `${projection.x}px`
    pointButton.style.top = `${projection.y}px`
    pointButton.addEventListener('mousedown', (event) => {
      event.stopPropagation()
    })
    pointButton.addEventListener('click', (event) => {
      event.preventDefault()
      event.stopPropagation()
    })
    pointButton.addEventListener('contextmenu', (event) => {
      event.preventDefault()
      event.stopPropagation()
      openRulerPointContextMenu(point, event)
    })
    pointLayer.appendChild(pointButton)
  }

  for (const segment of rulerSegmentModels.value) {
    const fromPoint = rulerPoints.value.find((point) => point.id === segment.fromId) || null
    const toPoint = rulerPoints.value.find((point) => point.id === segment.toId) || null
    if (!fromPoint || !toPoint) {
      continue
    }
    const pathData = buildRouteOverlayPath([fromPoint, toPoint])
    if (!pathData) {
      continue
    }
    const base = document.createElementNS(svgNS, 'path')
    base.setAttribute('class', 'mc-map-ruler-line-base')
    base.setAttribute('d', pathData)
    rulerSvg.appendChild(base)
    const line = document.createElementNS(svgNS, 'path')
    line.setAttribute('class', 'mc-map-ruler-line')
    line.setAttribute('d', pathData)
    rulerSvg.appendChild(line)

    const fromProjection = projectedPointMap.get(segment.fromId)
    const toProjection = projectedPointMap.get(segment.toId)
    if (!fromProjection || !toProjection) {
      continue
    }
    const label = document.createElement('div')
    label.className = 'mc-map-ruler-segment-label'
    label.textContent = segment.label
    label.style.left = `${(fromProjection.x + toProjection.x) / 2}px`
    label.style.top = `${(fromProjection.y + toProjection.y) / 2}px`
    labelLayer.appendChild(label)
  }

  rulerOverlay.appendChild(rulerSvg)
  rulerOverlay.appendChild(labelLayer)
  rulerOverlay.appendChild(pointLayer)
  viewport.appendChild(rulerOverlay)
}

function appendTraceBadgeStack(svg, x, y, rxText, txText) {
  const rxLabel = String(rxText || '')
  const txLabel = String(txText || '')
  const width = Math.max(96, Math.round(Math.max(rxLabel.length, txLabel.length) * 6.3) + 18)
  const height = 20
  const stackTop = y - height
  appendTraceBadge(svg, x, stackTop, width, height, rxLabel, 'rx')
  appendTraceBadge(svg, x, stackTop + height - 1, width, height, txLabel, 'tx')
}

function appendTraceBadge(svg, x, y, width, height, text, kind) {
  const svgNS = 'http://www.w3.org/2000/svg'
  const rect = document.createElementNS(svgNS, 'rect')
  rect.setAttribute('class', `mc-map-trace-badge-bg ${kind}`)
  rect.setAttribute('x', (x - width / 2).toFixed(2))
  rect.setAttribute('y', y.toFixed(2))
  rect.setAttribute('rx', '10')
  rect.setAttribute('ry', '10')
  rect.setAttribute('width', String(width))
  rect.setAttribute('height', String(height))
  svg.appendChild(rect)
  const label = document.createElementNS(svgNS, 'text')
  label.setAttribute('class', 'mc-map-trace-badge')
  label.setAttribute('x', x.toFixed(2))
  label.setAttribute('y', (y + height / 2).toFixed(2))
  label.textContent = String(text || '')
  svg.appendChild(label)
}

function scheduleMessageRouteOverlayRender() {
  cancelRouteOverlayFrame()
  routeOverlayFrame = window.requestAnimationFrame(() => {
    routeOverlayFrame = 0
    renderMessageRouteOverlay()
  })
}

function fitToActiveMessageRoute({ animate = false } = {}) {
  const model = activeMessageRouteModel.value
  if (!mapInstance.value || !model || !model.knownRoutePoints.length || !window.maplibregl) {
    return
  }
  if (model.knownRoutePoints.length === 1) {
    const point = model.knownRoutePoints[0]
    scheduleProgrammaticMove(animate ? 640 : 220)
    mapInstance.value[animate ? 'easeTo' : 'jumpTo']({
      center: [point.lon, point.lat],
      zoom: 13,
      duration: animate ? 260 : 0,
    })
    return
  }
  const bounds = new window.maplibregl.LngLatBounds()
  for (const point of model.knownRoutePoints) {
    bounds.extend([point.lon, point.lat])
  }
  scheduleProgrammaticMove(animate ? 640 : 220)
  mapInstance.value.fitBounds(bounds, {
    padding: fitPadding(),
    duration: animate ? 260 : 0,
    maxZoom: 14,
  })
}

function openPopupForPointKey(pointKey) {
  const targetKey = String(pointKey || '').trim()
  if (!targetKey) {
    return false
  }
  for (const marker of mapMarkers.value) {
    if (String(marker?.__meshcoriumPointKey || '') !== targetKey) {
      continue
    }
    return openMarkerPopup(marker, marker.__meshcoriumPointData || null)
  }
  return false
}

function fitPadding() {
  return window.innerWidth <= 900
    ? { top: 48, right: 32, bottom: 48, left: 32 }
    : { top: 84, right: 84, bottom: 84, left: 84 }
}

function applyMapProviderStyle(provider = selectedMapProvider.value) {
  const instance = mapInstance.value
  if (!instance) {
    return
  }
  instance.__meshcoriumFallbackStyleApplied = false
  try {
    instance.setStyle(buildSelectedMapStyle(provider))
  } catch (error) {
    console.error('[meshcorium] map-provider-style', {
      provider,
      message: error instanceof Error ? error.message : String(error || 'unknown'),
    })
    instance.__meshcoriumFallbackStyleApplied = true
    instance.setStyle(buildFallbackMapStyle())
  }
  window.requestAnimationFrame(() => {
    if (mapInstance.value !== instance) {
      return
    }
    instance.resize()
    applyViewport({ force: true })
    scheduleMessageRouteOverlayRender()
  })
}

async function updateMapProvider(provider) {
  const normalizedProvider = normalizeMapProvider(provider)
  if (normalizedProvider === selectedMapProvider.value) {
    return
  }
  applyMapProviderStyle(normalizedProvider)
  try {
    await session.updateClientSettings({ map_provider: normalizedProvider })
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('maps.provider.saveFailed')), true)
    applyMapProviderStyle(selectedMapProvider.value)
  }
}

async function updateMapMaxDistance(km) {
  const parsed = parseInt(km, 10)
  const value = Number.isFinite(parsed) && parsed >= 1 ? parsed : HOME_NODE_GEO_MAX_DISTANCE_KM
  if (value === mapMaxDistanceKm.value) {
    return
  }
  try {
    await session.updateClientSettings({ map_max_distance_km: value })
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('maps.distance.saveFailed')), true)
  }
}

function applyViewport({ animate = false, force = false } = {}) {
  if (!mapInstance.value) {
    return
  }
  syncMarkers()
  if (manualView.value && !force) {
    return
  }
  const viewport = mapViewport.value
  scheduleProgrammaticMove(animate ? 640 : 220)
  if (viewportMode.value === 'self' && hasSelfCoordinates.value) {
    mapInstance.value[animate ? 'easeTo' : 'jumpTo']({
      center: [viewport.center.lon, viewport.center.lat],
      zoom: viewport.zoom,
      duration: animate ? 260 : 0,
    })
    return
  }
  if (viewport.points.length > 1) {
    mapInstance.value.fitBounds(viewport.bounds, {
      padding: fitPadding(),
      duration: animate ? 260 : 0,
      maxZoom: 14,
    })
    return
  }
  mapInstance.value[animate ? 'easeTo' : 'jumpTo']({
    center: [viewport.center.lon, viewport.center.lat],
    zoom: viewport.zoom,
    duration: animate ? 260 : 0,
  })
}

async function ensureContactsLoaded() {
  if (!session.connected || !session.collectionsReady || contactsLoading.value) {
    return
  }
  const loadedContacts = Array.isArray(session.contacts) ? session.contacts.length : 0
  if (loadedContacts > 0) {
    return
  }
  contactsLoading.value = true
  try {
    await session.loadContacts()
    if (mapInstance.value) {
      applyViewport({ force: true })
      scheduleMessageRouteOverlayRender()
    }
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('maps.status.contactsLoadFailed')), true)
  } finally {
    contactsLoading.value = false
  }
}

async function mountMap() {
  if (!session.connected || !mapViewportRef.value || mapInstance.value) {
    return
  }
  if (mapMountPromise) {
    return mapMountPromise
  }
  mapLoading.value = true
  mapError.value = ''
  const mountToken = ++mapMountToken
  mapMountPromise = (async () => {
    try {
      await ensureMapLibreLoaded()
      if (mountToken !== mapMountToken) {
        return
      }
      if (!mapViewportRef.value || !window.maplibregl) {
        throw new Error(t('maps.status.unavailable'))
      }
      const viewport = mapViewport.value
      const instance = new window.maplibregl.Map({
        container: mapViewportRef.value,
        style: buildSelectedMapStyle(selectedMapProvider.value),
        center: [viewport.center.lon, viewport.center.lat],
        zoom: viewport.zoom,
        attributionControl: false,
        transformRequest: tileTransformRequest,
      })
      mapInstance.value = instance

      const finalizeMapReady = () => {
        if (mountToken !== mapMountToken || mapInstance.value !== instance) {
          return
        }
        clearMapBootTimer()
        mapReady.value = true
        mapLoading.value = false
        window.requestAnimationFrame(() => {
          if (mapInstance.value !== instance) {
            return
          }
          instance.resize()
          applyViewport({ force: true })
        })
      }

      const fallbackToLocalStyle = () => {
        if (mountToken !== mapMountToken || mapInstance.value !== instance || instance.__meshcoriumFallbackStyleApplied) {
          return
        }
        instance.__meshcoriumFallbackStyleApplied = true
        try {
          instance.setStyle(buildFallbackMapStyle())
        } catch (error) {
          console.error('[meshcorium] map-style-fallback', {
            message: error instanceof Error ? error.message : String(error || 'unknown'),
          })
        }
      }

      clearMapBootTimer()
      mapBootTimerId = window.setTimeout(() => {
        fallbackToLocalStyle()
      }, MAP_STYLE_BOOT_TIMEOUT_MS)

      instance.addControl(new window.maplibregl.NavigationControl(), 'top-right')
      instance.on('load', finalizeMapReady)
      instance.once('render', finalizeMapReady)
      instance.once('idle', finalizeMapReady)
      instance.on('error', (event) => {
        if (instance.__meshcoriumFallbackStyleApplied) {
          return
        }
        // OpenFreeMap can finish the first render before sprites/raster/vector tiles fail on the LAN stand.
        // Any source/tile/sprite error means the visible basemap may be incomplete, so switch to OSM raster.
        const shouldFallback = shouldFallbackToRasterMapStyle(event, mapReady.value)
        if (shouldFallback && selectedMapProvider.value === MAP_PROVIDER_OFM_LIBERTY) {
          fallbackToLocalStyle()
        }
      })
      instance.on('moveend', () => {
        if (!mapInstance.value || Date.now() < ignoreMoveEndUntil) {
          return
        }
        const center = mapInstance.value.getCenter()
        manualView.value = {
          lat: clampMapLatitude(center.lat),
          lon: normalizeMapLongitude(center.lng),
          zoom: mapInstance.value.getZoom(),
        }
        viewportMode.value = 'manual'
      })
      instance.on('contextmenu', (event) => {
        openMapPointContextMenu(event)
      })
      instance.on('click', closeMapContextMenu)
      instance.on('dragstart', closeMapContextMenu)
      instance.on('movestart', closeMapContextMenu)
      instance.on('move', scheduleMessageRouteOverlayRender)
      instance.on('zoom', scheduleMessageRouteOverlayRender)
      instance.on('resize', scheduleMessageRouteOverlayRender)
      instance.on('idle', scheduleMessageRouteOverlayRender)
      window.requestAnimationFrame(() => {
        if (mapInstance.value !== instance) {
          return
        }
        instance.resize()
        applyViewport({ force: true })
        fitToActiveMessageRoute()
        scheduleMessageRouteOverlayRender()
        finalizeMapReady()
      })
    } catch (error) {
      if (mountToken !== mapMountToken) {
        return
      }
      destroyMap()
      mapError.value = error instanceof Error ? error.message : String(error || t('maps.status.unavailable'))
    } finally {
      if (mountToken === mapMountToken) {
        mapMountPromise = null
      }
    }
  })()
  return mapMountPromise
}

function focusPoint(point, { openPopup = true } = {}) {
  if (!point) {
    return
  }
  viewportMode.value = 'manual'
  manualView.value = {
    lat: point.lat,
    lon: point.lon,
    zoom: point.kind === 'self' ? 13 : Math.max(12, Number(mapInstance.value?.getZoom?.() || 0) || 12),
  }
  if (!mapInstance.value) {
    return
  }
  scheduleProgrammaticMove(720)
  mapInstance.value.easeTo({
    center: [point.lon, point.lat],
    zoom: manualView.value.zoom,
    duration: 280,
  })
  if (openPopup) {
    window.setTimeout(() => {
      openPopupForPointKey(point.key)
    }, 260)
  }
}

function centerOnSelf() {
  if (!hasSelfCoordinates.value) {
    session.setStatus(t('maps.status.selfLocationMissing'), true)
    return
  }
  viewportMode.value = 'self'
  manualView.value = null
  applyViewport({ animate: true, force: true })
}

function applyRouteFocusTarget() {
  const target = routeFocusTarget.value
  if (!target) {
    lastAppliedRouteFocusSignature = ''
    lastOpenedRouteFocusPopupSignature = ''
    return
  }
  const signature = `${target.lat}:${target.lon}:${target.key}:${target.label}`
  if (signature !== lastAppliedRouteFocusSignature) {
    viewportMode.value = 'manual'
    manualView.value = {
      lat: clampMapLatitude(target.lat),
      lon: normalizeMapLongitude(target.lon),
      zoom: Math.max(12, Number(mapInstance.value?.getZoom?.() || 0) || 13),
    }
    if (mapInstance.value) {
      scheduleProgrammaticMove(720)
      mapInstance.value.easeTo({
        center: [manualView.value.lon, manualView.value.lat],
        zoom: manualView.value.zoom,
        duration: 280,
      })
    }
    lastAppliedRouteFocusSignature = signature
    lastOpenedRouteFocusPopupSignature = ''
  }
  if (!target.key || !mapInstance.value || signature === lastOpenedRouteFocusPopupSignature) {
    return
  }
  if (openPopupForPointKey(target.key)) {
    lastOpenedRouteFocusPopupSignature = signature
  }
}

function fitAllPoints() {
  viewportMode.value = 'all'
  manualView.value = null
  applyViewport({ animate: true, force: true })
}

async function applySelfLocation(scope = 'local', coordsOverride = null) {
  if (!session.connected || !session.self?.public_key) {
    session.setStatus(t('maps.status.connectRequired'), true)
    return
  }
  const coords = coordsOverride && Number.isFinite(Number(coordsOverride.lat)) && Number.isFinite(Number(coordsOverride.lon))
    ? {
      lat: clampMapLatitude(Number(coordsOverride.lat)),
      lon: normalizeMapLongitude(Number(coordsOverride.lon)),
    }
    : currentMapCenter.value
  const payload = await session.api('/api/node/self-location', {
    method: 'POST',
    body: JSON.stringify({
      ...session.activeConfigBody(),
      scope: String(scope || 'local'),
      lat: Number(coords.lat.toFixed(6)),
      lon: Number(coords.lon.toFixed(6)),
    }),
  })
  const patch = {
    active: session.connected,
  }
  if (payload?.device) {
    patch.device = payload.device
  }
  if (payload?.self) {
    patch.self = payload.self
  }
  if (Array.isArray(payload?.channels)) {
    patch.channels = payload.channels
  }
  if (Object.prototype.hasOwnProperty.call(payload || {}, 'radio_stats')) {
    patch.radio_stats = payload.radio_stats || null
  }
  if (Object.prototype.hasOwnProperty.call(payload || {}, 'self_telemetry')) {
    patch.self_telemetry = payload.self_telemetry || null
  }
  if (Object.prototype.hasOwnProperty.call(payload || {}, 'battery_info')) {
    patch.battery_info = payload.battery_info || null
  }
  session.patchSessionSnapshotFields(patch)
  session.setStatus(
    t(
      scope === 'global'
        ? 'maps.status.nodeLocationSaved'
        : 'maps.status.localLocationSaved',
      {
        coords: `${coords.lat.toFixed(6)}, ${coords.lon.toFixed(6)}`,
      },
    ),
  )
  closeMapContextMenu()
  applyViewport({ animate: true, force: true })
}

async function applyNodeLocationFromContextMenu() {
  const lat = Number(mapContextMenu.value.lat)
  const lon = Number(mapContextMenu.value.lon)
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    closeMapContextMenu()
    return
  }
  await applySelfLocation('global', { lat, lon })
}

function addRulerPointFromContextMenu() {
  const lat = Number(mapContextMenu.value.lat)
  const lon = Number(mapContextMenu.value.lon)
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    closeMapContextMenu()
    return
  }
  rulerPoints.value = [
    ...rulerPoints.value,
    appendRulerPoint(lat, lon),
  ]
  closeMapContextMenu()
}

function deleteRulerPointFromContextMenu() {
  const targetId = Number(mapContextMenu.value.rulerPointId || 0)
  if (!targetId) {
    closeMapContextMenu()
    return
  }
  const removeIndex = rulerPoints.value.findIndex((point) => point.id === targetId)
  if (removeIndex < 0) {
    closeMapContextMenu()
    return
  }
  rulerPoints.value = rulerPoints.value.slice(0, removeIndex)
  closeMapContextMenu()
}

function refreshViewport() {
  if (!mapInstance.value) {
    return
  }
  mapInstance.value.resize()
  applyViewport({ force: !manualView.value })
  scheduleMessageRouteOverlayRender()
}

function syncTraceSelection() {
  const availableKeys = new Set(traceCandidatePoints.value.map((point) => point.publicKey))
  traceSelectedKeys.value = traceSelectedKeys.value.filter((key) => availableKeys.has(normalizePublicKey(key)))
}

function syncTraceInputFromSelection() {
  const candidateMap = new Map(
    traceCandidatePoints.value.map((point) => [normalizePublicKey(point.publicKey), point]),
  )
  traceManualInput.value = traceSelectedKeys.value
    .map((key) => candidateMap.get(normalizePublicKey(key))?.shortPublicKey || String(key || '').trim().slice(0, 4).toUpperCase())
    .filter(Boolean)
    .join(', ')
}

function resolveTraceTokens(tokens) {
  return tokens.map((token) => {
    const matches = traceCandidatePoints.value.filter((point) => String(point.publicKey || '').toUpperCase().startsWith(String(token || '').toUpperCase()))
    const unique = matches.length === 1 ? matches[0] : null
    return { token, matches, unique }
  })
}

function rebuildTraceSelectionFromInput(value) {
  traceManualInput.value = String(value || '')
  const entries = resolveTraceTokens(routeTokensFromInput(value))
  const ordered = []
  const seen = new Set()
  for (const entry of entries) {
    const publicKey = normalizePublicKey(entry.unique?.publicKey)
    if (!publicKey || seen.has(publicKey)) {
      continue
    }
    seen.add(publicKey)
    ordered.push(publicKey)
  }
  traceSelectedKeys.value = ordered
}

function toggleTracePoint(point) {
  const publicKey = normalizePublicKey(point?.publicKey)
  if (!publicKey) {
    return
  }
  if (traceBusy.value) {
    return
  }
  if (traceSelectedKeys.value.includes(publicKey)) {
    traceSelectedKeys.value = traceSelectedKeys.value.filter((value) => value !== publicKey)
    return
  }
  traceSelectedKeys.value = [...traceSelectedKeys.value, publicKey]
}

function clearTraceSelection() {
  if (traceBusy.value) {
    return
  }
  traceSelectedKeys.value = []
}

function openTracePicker() {
  tracePickerSearch.value = ''
  tracePickerOpen.value = true
}

function closeTracePicker() {
  tracePickerOpen.value = false
  tracePickerSearch.value = ''
}

function handleMapsEscape(event) {
  if (event.defaultPrevented || event.key !== 'Escape') {
    return
  }
  if (tracePickerOpen.value) {
    event.preventDefault()
    closeTracePicker()
    return
  }
  if (mapContextMenu.value.open) {
    event.preventDefault()
    closeMapContextMenu()
    return
  }
  if (activeMessageRouteModel.value) {
    event.preventDefault()
    void clearActiveMessageRoute()
  }
}

function addTracePointFromPicker(point) {
  const publicKey = normalizePublicKey(point?.publicKey)
  if (!publicKey || traceBusy.value) {
    return
  }
  if (!traceSelectedKeys.value.includes(publicKey)) {
    traceSelectedKeys.value = [...traceSelectedKeys.value, publicKey]
  }
  closeTracePicker()
}

async function clearActiveMessageRoute() {
  const nextQuery = { ...route.query }
  delete nextQuery.route_source
  delete nextQuery.route_hops
  delete nextQuery.route_message_id
  delete nextQuery.route_conversation_kind
  delete nextQuery.route_preview
  await router.replace({
    path: scrollerMode.value === 'trace' ? MAP_TRACE_PATH : MAP_MAIN_PATH,
    query: nextQuery,
  })
}

function stopTraceEventStream() {
  if (traceEventSource) {
    traceEventSource.close()
    traceEventSource = null
  }
}

function applyTraceEventPayload(payload) {
  if (payload?.job_id && traceJobId.value && String(payload.job_id) !== String(traceJobId.value)) {
    return
  }
  if (payload?.trace && typeof payload.trace === 'object') {
    traceResult.value = payload.trace
  }
  const status = String(payload?.status || traceResult.value?.status || '')
  if (status === 'queued' || status === 'running' || status === 'started' || status === 'progress') {
    traceBusy.value = true
    return
  }
  traceBusy.value = false
  if (status === 'completed' && traceResult.value?.success) {
    session.setStatus(t('maps.trace.status.success', { hops: Number(traceResult.value?.hop_count || 0) }))
  } else if (status === 'completed') {
    session.setStatus(
      t('maps.trace.status.failed', { hop: Number(traceResult.value?.failure_at_hop || 0) || '?' }),
      true,
    )
  } else if (status === 'cancelled') {
    session.setStatus(t('maps.trace.status.cancelled'))
  } else if (status === 'error') {
    session.setStatus(String(payload?.message || traceResult.value?.error || t('maps.trace.status.error')), true)
  }
  stopTraceEventStream()
}

function ensureTraceEventStream() {
  if (traceEventSource || !session.connected) {
    return
  }
  const query = session.activeEventStreamQuery() || new URLSearchParams()
  const source = new EventSource(`/api/events?${query.toString()}`)
  traceEventSource = source
  source.onmessage = (event) => {
    const payload = JSON.parse(String(event.data || '{}'))
    if (payload?.event === 'heartbeat') {
      return
    }
    if (payload?.event === 'contact-route-trace') {
      applyTraceEventPayload(payload)
    }
  }
  source.onerror = () => {
    if (traceBusy.value) {
      session.setStatus(t('maps.trace.status.listenerUnavailable'), true)
    }
  }
}

async function startRouteTrace() {
  if (!session.connected) {
    session.setStatus(t('maps.status.connectRequired'), true)
    return
  }
  syncTraceSelection()
  if (!traceSelectedKeys.value.length) {
    session.setStatus(t('maps.trace.status.selectRouteFirst'), true)
    return
  }
  stopTraceEventStream()
  ensureTraceEventStream()
  traceBusy.value = true
  traceResult.value = null
  traceJobId.value = ''
  try {
    const payload = await session.api('/api/contacts/trace-route/start', {
      method: 'POST',
      body: JSON.stringify({
        ...session.activeConfigBody(),
        selected_public_keys: traceSelectedKeys.value.slice(),
        route_path_hash_len: Number(traceHashLen.value || 2) || 2,
        sequential: Boolean(traceSequential.value),
      }),
    })
    traceJobId.value = String(payload?.job_id || '')
    if (payload?.trace && typeof payload.trace === 'object') {
      traceResult.value = payload.trace
    }
  } catch (error) {
    traceBusy.value = false
    stopTraceEventStream()
    throw error
  }
}

async function cancelRouteTrace(reason = 'cancelled') {
  if (!traceJobId.value) {
    traceBusy.value = false
    stopTraceEventStream()
    return
  }
  try {
    await session.api('/api/contacts/trace-route/cancel', {
      method: 'POST',
      body: JSON.stringify({
        ...session.activeConfigBody(),
        job_id: traceJobId.value,
        reason,
      }),
    })
  } finally {
    traceBusy.value = false
    stopTraceEventStream()
  }
}

watch(() => session.connected, async (connected) => {
  if (!connected) {
    destroyMap()
    mapError.value = ''
    stopTraceEventStream()
    traceBusy.value = false
    traceJobId.value = ''
    return
  }
  const contactsPromise = ensureContactsLoaded()
  await mountMap()
  await contactsPromise
}, { immediate: true })

watch(viewportSignature, () => {
  if (!mapInstance.value) {
    return
  }
  applyViewport()
})

watch(() => Boolean(emojiMarkersEnabled.value), () => {
  if (!mapInstance.value) {
    return
  }
  syncMarkers()
})

watch(traceCandidatePoints, () => {
  syncTraceSelection()
  syncTraceInputFromSelection()
})

watch(traceSelectedKeys, () => {
  syncTraceInputFromSelection()
  if (!mapInstance.value) {
    return
  }
  syncMarkers()
  scheduleMessageRouteOverlayRender()
})

watch(
  () => [scrollerMode.value, routeTraceQuerySelection.value.join(',')],
  ([mode, keys]) => {
    if (mode !== 'trace') {
      return
    }
    const nextKeys = String(keys || '')
      .split(',')
      .map((value) => normalizePublicKey(value))
      .filter(Boolean)
    if (!nextKeys.length) {
      return
    }
    traceSelectedKeys.value = nextKeys
  },
  { immediate: true },
)

watch(scrollerMode, () => {
  if (!mapInstance.value) {
    return
  }
  syncMarkers()
  scheduleMessageRouteOverlayRender()
})

watch(traceResult, () => {
  if (!mapInstance.value) {
    return
  }
  scheduleMessageRouteOverlayRender()
})

watch(rulerPoints, () => {
  if (!mapInstance.value) {
    return
  }
  scheduleMessageRouteOverlayRender()
})

watch(() => route.path, () => {
  syncScrollerModeFromRoute()
})

watch(
  () => [route.query.focus_lat, route.query.focus_lon, route.query.focus_key, route.query.focus_label, mapReady.value, viewportSignature.value],
  () => {
    applyRouteFocusTarget()
  },
  { immediate: true },
)

watch(activeMessageRouteModel, (model) => {
  if (!model) {
    mapViewportRef.value?.querySelector('.mc-map-route-overlay')?.remove()
    return
  }
  if (mapInstance.value) {
    fitToActiveMessageRoute({ animate: true })
    scheduleMessageRouteOverlayRender()
  }
})

onMounted(async () => {
  window.addEventListener('keydown', handleMapsEscape)
  syncScrollerModeFromRoute()
  const contactsPromise = ensureContactsLoaded()
  await mountMap()
  await contactsPromise
  applyRouteFocusTarget()
  if (typeof ResizeObserver !== 'undefined' && mapViewportRef.value) {
    resizeObserver = new ResizeObserver(() => {
      refreshViewport()
    })
    resizeObserver.observe(mapViewportRef.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleMapsEscape)
  cancelRouteTrace('maps-view-unmounted').catch(() => {})
  stopTraceEventStream()
  closeMapContextMenu()
  rulerPoints.value = []
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  destroyMap()
})
</script>

<template>
  <!-- MOBILE: Fullscreen map with floating controls + bottom-sheet sidebar -->
  <div v-if="isMobile" class="mc-maps-mobile-shell">
    <ShellPhonebar class="mc-maps-mobile-phonebar-top" />

    <div class="mc-maps-mobile-viewport">
      <section class="mc-map-stage">
        <div v-if="activeMessageRouteModel" class="mc-map-route-panel">
          <div class="mc-map-route-panel-head">
            <div>
              <h3>{{ t('maps.messageRoute.title') }}</h3>
              <p>{{ activeMessageRouteModel.preview || t('maps.messageRoute.emptyPreview') }}</p>
            </div>
            <button class="mc-map-route-close" type="button" @click="clearActiveMessageRoute">×</button>
          </div>
          <div class="mc-map-route-panel-meta">
            <span class="mc-map-chip">{{ activeMessageRouteModel.conversationKind === 'contact' ? 'Direct' : 'Channel' }}</span>
            <span class="mc-map-chip">{{ t('maps.messageRoute.hopCount', { count: activeMessageRouteModel.hops.length }) }}</span>
            <span class="mc-map-chip">{{ t('maps.messageRoute.matchedCount', { count: activeMessageRouteModel.routeEntries.filter((entry) => entry.visiblePoints.length).length }) }}</span>
          </div>
          <div class="mc-map-route-panel-list">
            <div
              v-for="entry in activeMessageRouteModel.routeEntries"
              :key="entry.hop"
              class="mc-map-route-panel-item"
              :class="{ missing: !entry.visiblePoints.length }"
            >
              <div class="mc-map-route-panel-item-head">
                <span class="mc-map-route-panel-item-hop">{{ entry.displayHop }}</span>
                <span class="mc-map-route-panel-item-state">
                  {{ entry.visiblePoints.length ? t('maps.messageRoute.matched') : t('maps.messageRoute.missing') }}
                </span>
              </div>
              <div class="mc-map-route-panel-item-body">
                {{
                  entry.visiblePoints.length
                    ? entry.visiblePoints.map((point) => point.displayName).join(', ')
                    : t('maps.messageRoute.noMatch')
                }}
              </div>
            </div>
          </div>
        </div>
        <div v-if="mapLoading && !mapInstance" class="mc-map-stage-overlay">
          <div class="mc-workspace-empty mc-workspace-empty--maps">
            <h3>{{ t('maps.status.loadingTitle') }}</h3>
            <p>{{ t('maps.status.loadingSubtitle') }}</p>
          </div>
        </div>

        <div v-else-if="mapError" class="mc-map-stage-overlay">
          <div class="mc-workspace-empty mc-workspace-empty--maps">
            <h3>{{ t('maps.status.unavailableTitle') }}</h3>
            <p>{{ mapError }}</p>
          </div>
        </div>

        <div
          ref="mapViewportRef"
          class="mc-map-viewport"
          :class="{ 'is-ready': mapReady, 'is-dark': normalizedMapThemeMode === 'dark' }"
          :aria-label="t('maps.title')"
        ></div>
        <div
          v-if="mapContextMenu.open"
          class="mc-map-context-layer"
          @click="closeMapContextMenu"
          @contextmenu.prevent="closeMapContextMenu"
        >
          <div
            class="mc-map-context-menu"
            :style="{ left: `${mapContextMenu.x}px`, top: `${mapContextMenu.y}px` }"
            @click.stop
            @contextmenu.prevent
          >
            <p class="mc-map-context-coords">
              {{ Number(mapContextMenu.lat).toFixed(5) }}, {{ Number(mapContextMenu.lon).toFixed(5) }}
            </p>
            <template v-if="mapContextMenu.kind === 'ruler-point'">
              <button
                class="mc-map-action-button mc-map-context-action"
                type="button"
                @click="deleteRulerPointFromContextMenu"
              >
                {{ t('maps.contextMenu.deleteRulerPoint') }}
              </button>
            </template>
            <template v-else>
              <button
                class="mc-map-action-button mc-map-context-action"
                type="button"
                @click="addRulerPointFromContextMenu"
              >
                {{ t('maps.contextMenu.addRulerPoint') }}
              </button>
              <button
                class="mc-map-action-button mc-map-context-action"
                type="button"
                :disabled="!session.connected"
                @click="applyNodeLocationFromContextMenu"
              >
                {{ t('maps.contextMenu.setHomeNodeGeo') }}
              </button>
            </template>
          </div>
        </div>
      </section>

      <!-- Floating map controls -->
      <div class="mc-maps-mobile-float-controls">
        <button
          class="mc-maps-mobile-float-btn"
          type="button"
          :aria-label="t('maps.title')"
          @click="toggleMobileScroller"
        >
          ☰
        </button>
        <button
          class="mc-maps-mobile-float-btn"
          type="button"
          :aria-label="t('maps.controls.centerSelf')"
          :disabled="!hasSelfCoordinates"
          @click="centerOnSelf"
        >
          <img :src="geoIconUrl" alt="" style="width: 18px; height: 18px;" />
        </button>
        <button
          class="mc-maps-mobile-float-btn"
          type="button"
          :aria-label="mapThemeToggleTooltip"
          @click="toggleMapThemeMode"
        >
          {{ normalizedMapThemeMode === 'dark' ? '☀' : '🌙' }}
        </button>
      </div>
    </div>

    <!-- Sidebar bottom sheet overlay -->
    <Teleport to="body">
      <div v-if="mobileScrollerOpen" class="mc-maps-mobile-sidebar-overlay" @click.self="closeMobileScroller">
        <div class="mc-maps-mobile-sidebar-panel" @click.stop>
          <header class="mc-maps-mobile-sidebar-header">
            <button class="mc-maps-mobile-sidebar-close" type="button" @click="closeMobileScroller">✕</button>
            <h2 v-if="scrollerMode === 'trace'">{{ t('maps.trace.title') }}</h2>
            <h2 v-else>{{ t('maps.title') }}</h2>
          </header>

          <div class="mc-maps-mobile-sidebar-body">
            <template v-if="scrollerMode === 'trace'">
              <section class="mc-map-trace-screen">
                <button class="mc-map-back-button" type="button" @click="closeTraceScroller">
                  {{ t('maps.trace.controls.back') }}
                </button>

                <section class="mc-map-trace-card">
                  <div class="mc-map-location-header">
                    <h2>{{ t('maps.trace.title') }}</h2>
                  </div>
                  <div class="mc-map-trace-controls">
                    <label class="mc-map-trace-select mc-map-trace-select--route">
                      <span>{{ t('maps.trace.controls.route') }}</span>
                      <div class="mc-map-trace-input-row">
                        <input
                          :value="traceManualInput"
                          class="mc-map-trace-input"
                          type="text"
                          :disabled="traceBusy"
                          :placeholder="t('maps.trace.controls.routePlaceholder')"
                          @input="rebuildTraceSelectionFromInput($event.target.value)"
                        >
                        <button class="mc-map-action-button mc-map-action-button--icon" type="button" :disabled="traceBusy" @click="openTracePicker">
                          +
                        </button>
                      </div>
                    </label>
                    <label class="mc-map-trace-toggle">
                      <input v-model="traceSequential" type="checkbox" :disabled="traceBusy">
                      <span>{{ t('maps.trace.controls.sequential') }}</span>
                    </label>
                    <label class="mc-map-trace-select">
                      <span>{{ t('maps.trace.controls.hashLen') }}</span>
                      <select v-model.number="traceHashLen" :disabled="traceBusy">
                        <option :value="1">1</option>
                        <option :value="2">2</option>
                        <option :value="4">4</option>
                        <option :value="8">8</option>
                      </select>
                    </label>
                  </div>
                  <div class="mc-map-trace-actions">
                    <button class="mc-map-action-button" type="button" :disabled="traceBusy || !traceSelectedKeys.length" @click="startRouteTrace">
                      {{ t('maps.trace.controls.start') }}
                    </button>
                    <button class="mc-map-action-button" type="button" :disabled="!traceBusy" @click="cancelRouteTrace('user-cancelled')">
                      {{ t('maps.trace.controls.cancel') }}
                    </button>
                    <button class="mc-map-action-button" type="button" :disabled="traceBusy || !traceSelectedKeys.length" @click="clearTraceSelection">
                      {{ t('maps.trace.controls.clear') }}
                    </button>
                  </div>
                  <div class="mc-map-trace-status" :class="{ 'is-error': traceResult && !traceBusy && !traceResult.success && traceResult.status !== 'cancelled' }">
                    {{ traceStatusSummary }}
                  </div>
                  <div v-if="selectedTracePoints.length" class="mc-map-trace-point-list">
                    <button
                      v-for="point in selectedTracePoints"
                      :key="point.key"
                      class="mc-map-trace-point"
                      type="button"
                      :class="{ active: true }"
                      :disabled="traceBusy"
                      @click="toggleTracePoint(point)"
                      @dblclick.prevent="focusPoint(point)"
                    >
                      <span class="mc-map-trace-point-main">
                        <span class="mc-map-trace-point-name">{{ point.displayName }}</span>
                        <span class="mc-map-trace-point-meta">{{ t('maps.legend.repeater') }}</span>
                      </span>
                      <span class="mc-map-trace-point-check">●</span>
                    </button>
                  </div>
                  <div v-else class="mc-map-trace-empty">
                    {{ t('maps.trace.empty.noRoute') }}
                  </div>
                  <div v-if="traceStepModels.length" class="mc-map-trace-steps">
                    <div
                      v-for="step in traceStepModels"
                      :key="step.key"
                      class="mc-map-trace-step"
                      :class="{ pending: step.pending, success: step.success, failed: step.failed }"
                    >
                      <div class="mc-map-trace-step-head">
                        <span class="mc-map-trace-step-title">{{ t('maps.trace.step.title', { hop: step.prefixHops }) }}</span>
                        <span class="mc-map-trace-step-state">
                          {{
                            step.pending
                              ? t('maps.trace.step.pendingShort')
                              : step.success
                                ? t('maps.trace.step.successShort')
                                : t('maps.trace.step.failedShort')
                          }}
                        </span>
                      </div>
                      <div class="mc-map-trace-step-route">{{ step.participantLabel }}</div>
                      <div class="mc-map-trace-step-meta">{{ step.meta }}</div>
                      <div v-if="step.hopLabels.length" class="mc-map-trace-step-hops">
                        {{ step.hopLabels.join(' · ') }}
                      </div>
                    </div>
                  </div>
                </section>
              </section>
            </template>

            <template v-else>
              <section class="mc-map-panel">
                <div class="mc-map-summary">
                  <div class="mc-map-summary-card">
                    <span class="mc-map-summary-value">{{ mapPoints.length }}</span>
                    <span class="mc-map-summary-label">{{ t('maps.stats.points') }}</span>
                  </div>
                  <div class="mc-map-summary-card">
                    <span class="mc-map-summary-value">{{ contactLocationCount }}</span>
                    <span class="mc-map-summary-label">{{ t('maps.stats.contactLocations') }}</span>
                  </div>
                  <div class="mc-map-summary-card">
                    <span class="mc-map-summary-value">{{ favoritePointCount }}</span>
                    <span class="mc-map-summary-label">{{ t('maps.stats.favorites') }}</span>
                  </div>
                </div>

                <div class="mc-map-actions">
                  <button class="mc-map-action-button" type="button" @click="fitAllPoints">
                    {{ t('maps.controls.fitAll') }}
                  </button>
                  <button
                    class="mc-map-action-button"
                    type="button"
                    :class="{ active: emojiMarkersEnabled }"
                    @click="emojiMarkersEnabled = !emojiMarkersEnabled"
                  >
                    {{ t('maps.controls.emojiMarkers') }}
                  </button>
                </div>

                <div class="mc-map-legend-card">
                  <div class="mc-map-legend-title">{{ t('maps.legend.title') }}</div>
                  <div class="mc-map-legend-list">
                    <div class="mc-map-legend-item">
                      <span class="mc-map-legend-self">
                        <img v-if="selfPreviewUrl" :src="selfPreviewUrl" alt="" />
                        <span v-else class="mc-map-legend-self-fallback"></span>
                      </span>
                      <span>{{ t('maps.legend.self') }}</span>
                    </div>
                    <div class="mc-map-legend-item">
                      <span class="mc-map-legend-dot mc-map-legend-dot--contact"></span>
                      <span>{{ t('maps.legend.contact') }}</span>
                    </div>
                    <div class="mc-map-legend-item">
                      <span class="mc-map-legend-dot mc-map-legend-dot--repeater"></span>
                      <span>{{ t('maps.legend.repeater') }}</span>
                    </div>
                    <div class="mc-map-legend-item">
                      <span class="mc-map-legend-dot mc-map-legend-dot--contact is-favorite"></span>
                      <span>{{ t('maps.legend.favoriteContact') }}</span>
                    </div>
                    <div class="mc-map-legend-item">
                      <span class="mc-map-legend-dot mc-map-legend-dot--repeater is-favorite"></span>
                      <span>{{ t('maps.legend.favoriteRepeater') }}</span>
                    </div>
                  </div>
                </div>
              </section>

              <section class="mc-map-provider-card mc-settings-rows">
                <label class="mc-settings-row mc-map-provider-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('maps.provider.title') }}</strong>
                    <span>{{ t('maps.provider.subtitle') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <PluginDropdown
                      :model-value="selectedMapProvider"
                      :options="mapProviderOptions"
                      :min-width="220"
                      @update:model-value="updateMapProvider"
                    />
                  </div>
                </label>
              </section>

              <section class="mc-map-distance-card mc-settings-rows">
                <label class="mc-settings-row mc-map-distance-row">
                  <div class="mc-settings-row-label">
                    <strong>{{ t('maps.distance.title') }}</strong>
                    <span>{{ t('maps.distance.subtitle') }}</span>
                  </div>
                  <div class="mc-settings-row-control">
                    <input
                      class="mc-map-distance-input"
                      type="number"
                      :value="mapMaxDistanceKm"
                      min="1"
                      max="20000"
                      step="1"
                      @change="updateMapMaxDistance($event.target.value)"
                    >
                    <span class="mc-map-distance-unit">км</span>
                  </div>
                </label>
              </section>

              <section class="mc-map-location-card">
                <div class="mc-map-location-header">
                  <h2>{{ t('maps.trace.title') }}</h2>
                  <p>{{ t('maps.trace.subtitle') }}</p>
                </div>
                <button class="mc-map-action-button mc-map-action-button--wide" type="button" @click="openTraceScroller">
                  {{ t('maps.trace.controls.open') }}
                </button>
              </section>
            </template>
          </div>

          <footer class="mc-maps-mobile-sidebar-footer">
            <div class="mc-status" :class="{ 'is-error': session.statusError }">
              {{ scrollerFooterStatus }}
            </div>
          </footer>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="tracePickerOpen" class="mc-overlay mc-overlay--soft" @click="closeTracePicker">
        <section class="mc-map-trace-picker" @click.stop>
          <div class="mc-map-route-panel-head">
            <div>
              <h3>{{ t('maps.trace.controls.pickRepeater') }}</h3>
              <p>{{ t('maps.trace.controls.pickRepeaterSubtitle') }}</p>
            </div>
            <button class="mc-map-route-close" type="button" @click="closeTracePicker">×</button>
          </div>
          <input
            v-model="tracePickerSearch"
            class="mc-map-trace-picker-search"
            type="text"
            :placeholder="t('maps.trace.controls.searchPlaceholder')"
          >
          <div class="mc-map-trace-picker-list mc-list-scroll">
            <button
              v-for="point in filteredTracePickerPoints"
              :key="`picker:${point.key}`"
              class="mc-map-trace-point"
              type="button"
              @click="addTracePointFromPicker(point)"
            >
              <span class="mc-map-trace-point-main">
                <span class="mc-map-trace-point-name">{{ point.displayName }}</span>
                <span class="mc-map-trace-point-meta">{{ point.shortPublicKey || t('maps.legend.repeater') }}</span>
              </span>
              <span class="mc-map-trace-point-check">+</span>
            </button>
            <div v-if="!filteredTracePickerPoints.length" class="mc-map-trace-empty">
              {{ t('maps.trace.empty.noSearchMatches') }}
            </div>
          </div>
        </section>
      </div>
    </Teleport>
  </div>

  <!-- Mobile nodebar -->
  <div v-if="isMobile" class="mc-maps-mobile-nodebar">
    <div class="mc-phonebar-row">
      <div class="mc-phonebar-left">
        <div class="mc-metric">ch: <strong>{{ channelCountSummary.visibleCount }}/{{ channelCountSummary.totalSlots }}</strong></div>
        <div class="mc-metric">cont: <strong>{{ contactCountSummary.nodeResident }}/{{ contactCountSummary.nodeLimit }}/{{ contactCountSummary.dbTotal }}</strong></div>
      </div>
      <div class="mc-phonebar-right">
        <span class="mc-node-led" :class="session.connected ? 'status-connected' : 'status-disconnected'"></span>
        <div class="mc-node-name"><strong>{{ nodeDisplayName }}</strong></div>
      </div>
    </div>
  </div>

  <!-- DESKTOP: Split sidebar + map -->
  <div v-else class="mc-maps-route">
    <ShellPageFrame
      scroller-class="mc-sidebar--maps"
      :scroller-header-class="scrollerMode === 'trace' ? 'mc-sidebar-top--maps-trace' : 'mc-sidebar-top--maps'"
      workspace-class="mc-content--shell-body mc-content--maps"
    >
      <template #workspace-top>
        <ShellPhonebar />
      </template>

      <template #scroller-header>
        <div class="mc-scroller-copy" :class="{ 'mc-scroller-copy--maps-trace': scrollerMode === 'trace', 'mc-scroller-copy--maps': scrollerMode !== 'trace' }">
          <template v-if="scrollerMode === 'trace'">
            <h1 class="mc-scroller-title">{{ t('maps.trace.title') }}</h1>
          </template>
          <template v-else>
            <h1 class="mc-scroller-title mc-scroller-title--maps">{{ t('maps.title') }}</h1>
          </template>
        </div>
      </template>

      <template #scroller-body>
        <div class="mc-list-scroll mc-list-scroll--maps">
          <template v-if="scrollerMode === 'trace'">
            <section class="mc-map-trace-screen">
              <button class="mc-map-back-button" type="button" @click="closeTraceScroller">
                {{ t('maps.trace.controls.back') }}
              </button>

              <section class="mc-map-trace-card">
                <div class="mc-map-location-header">
                  <h2>{{ t('maps.trace.title') }}</h2>
                </div>
                <div class="mc-map-trace-controls">
                  <label class="mc-map-trace-select mc-map-trace-select--route">
                    <span>{{ t('maps.trace.controls.route') }}</span>
                    <div class="mc-map-trace-input-row">
                      <input
                        :value="traceManualInput"
                        class="mc-map-trace-input"
                        type="text"
                        :disabled="traceBusy"
                        :placeholder="t('maps.trace.controls.routePlaceholder')"
                        @input="rebuildTraceSelectionFromInput($event.target.value)"
                      >
                      <button class="mc-map-action-button mc-map-action-button--icon" type="button" :disabled="traceBusy" @click="openTracePicker">
                        +
                      </button>
                    </div>
                  </label>
                  <label class="mc-map-trace-toggle">
                    <input v-model="traceSequential" type="checkbox" :disabled="traceBusy">
                    <span>{{ t('maps.trace.controls.sequential') }}</span>
                  </label>
                  <label class="mc-map-trace-select">
                    <span>{{ t('maps.trace.controls.hashLen') }}</span>
                    <select v-model.number="traceHashLen" :disabled="traceBusy">
                      <option :value="1">1</option>
                      <option :value="2">2</option>
                      <option :value="4">4</option>
                      <option :value="8">8</option>
                    </select>
                  </label>
                </div>
                <div class="mc-map-trace-actions">
                  <button class="mc-map-action-button" type="button" :disabled="traceBusy || !traceSelectedKeys.length" @click="startRouteTrace">
                    {{ t('maps.trace.controls.start') }}
                  </button>
                  <button class="mc-map-action-button" type="button" :disabled="!traceBusy" @click="cancelRouteTrace('user-cancelled')">
                    {{ t('maps.trace.controls.cancel') }}
                  </button>
                  <button class="mc-map-action-button" type="button" :disabled="traceBusy || !traceSelectedKeys.length" @click="clearTraceSelection">
                    {{ t('maps.trace.controls.clear') }}
                  </button>
                </div>
                <div class="mc-map-trace-status" :class="{ 'is-error': traceResult && !traceBusy && !traceResult.success && traceResult.status !== 'cancelled' }">
                  {{ traceStatusSummary }}
                </div>
                <div v-if="selectedTracePoints.length" class="mc-map-trace-point-list">
                  <button
                    v-for="point in selectedTracePoints"
                    :key="point.key"
                    class="mc-map-trace-point"
                    type="button"
                    :class="{ active: true }"
                    :disabled="traceBusy"
                    @click="toggleTracePoint(point)"
                    @dblclick.prevent="focusPoint(point)"
                  >
                    <span class="mc-map-trace-point-main">
                      <span class="mc-map-trace-point-name">{{ point.displayName }}</span>
                      <span class="mc-map-trace-point-meta">{{ t('maps.legend.repeater') }}</span>
                    </span>
                    <span class="mc-map-trace-point-check">●</span>
                  </button>
                </div>
                <div v-else class="mc-map-trace-empty">
                  {{ t('maps.trace.empty.noRoute') }}
                </div>
                <div v-if="traceStepModels.length" class="mc-map-trace-steps">
                  <div
                    v-for="step in traceStepModels"
                    :key="step.key"
                    class="mc-map-trace-step"
                    :class="{ pending: step.pending, success: step.success, failed: step.failed }"
                  >
                    <div class="mc-map-trace-step-head">
                      <span class="mc-map-trace-step-title">{{ t('maps.trace.step.title', { hop: step.prefixHops }) }}</span>
                      <span class="mc-map-trace-step-state">
                        {{
                          step.pending
                            ? t('maps.trace.step.pendingShort')
                            : step.success
                              ? t('maps.trace.step.successShort')
                              : t('maps.trace.step.failedShort')
                        }}
                      </span>
                    </div>
                    <div class="mc-map-trace-step-route">{{ step.participantLabel }}</div>
                    <div class="mc-map-trace-step-meta">{{ step.meta }}</div>
                    <div v-if="step.hopLabels.length" class="mc-map-trace-step-hops">
                      {{ step.hopLabels.join(' · ') }}
                    </div>
                  </div>
                </div>
              </section>
            </section>
          </template>

          <template v-else>
            <section class="mc-map-panel">
              <div class="mc-map-summary">
                <div class="mc-map-summary-card">
                  <span class="mc-map-summary-value">{{ mapPoints.length }}</span>
                  <span class="mc-map-summary-label">{{ t('maps.stats.points') }}</span>
                </div>
                <div class="mc-map-summary-card">
                  <span class="mc-map-summary-value">{{ contactLocationCount }}</span>
                  <span class="mc-map-summary-label">{{ t('maps.stats.contactLocations') }}</span>
                </div>
                <div class="mc-map-summary-card">
                  <span class="mc-map-summary-value">{{ favoritePointCount }}</span>
                  <span class="mc-map-summary-label">{{ t('maps.stats.favorites') }}</span>
                </div>
              </div>

              <div class="mc-map-actions">
                <button class="mc-map-action-button" type="button" @click="fitAllPoints">
                  {{ t('maps.controls.fitAll') }}
                </button>
                <button
                  class="mc-map-action-button"
                  type="button"
                  :class="{ active: emojiMarkersEnabled }"
                  @click="emojiMarkersEnabled = !emojiMarkersEnabled"
                >
                  {{ t('maps.controls.emojiMarkers') }}
                </button>
              </div>

              <div class="mc-map-legend-card">
                <div class="mc-map-legend-title">{{ t('maps.legend.title') }}</div>
                <div class="mc-map-legend-list">
                  <div class="mc-map-legend-item">
                    <span class="mc-map-legend-self">
                      <img v-if="selfPreviewUrl" :src="selfPreviewUrl" alt="" />
                      <span v-else class="mc-map-legend-self-fallback"></span>
                    </span>
                    <span>{{ t('maps.legend.self') }}</span>
                  </div>
                  <div class="mc-map-legend-item">
                    <span class="mc-map-legend-dot mc-map-legend-dot--contact"></span>
                    <span>{{ t('maps.legend.contact') }}</span>
                  </div>
                  <div class="mc-map-legend-item">
                    <span class="mc-map-legend-dot mc-map-legend-dot--repeater"></span>
                    <span>{{ t('maps.legend.repeater') }}</span>
                  </div>
                  <div class="mc-map-legend-item">
                    <span class="mc-map-legend-dot mc-map-legend-dot--contact is-favorite"></span>
                    <span>{{ t('maps.legend.favoriteContact') }}</span>
                  </div>
                  <div class="mc-map-legend-item">
                    <span class="mc-map-legend-dot mc-map-legend-dot--repeater is-favorite"></span>
                    <span>{{ t('maps.legend.favoriteRepeater') }}</span>
                  </div>
                </div>
              </div>
            </section>

            <section class="mc-map-provider-card mc-settings-rows">
              <label class="mc-settings-row mc-map-provider-row">
                <div class="mc-settings-row-label">
                  <strong>{{ t('maps.provider.title') }}</strong>
                  <span>{{ t('maps.provider.subtitle') }}</span>
                </div>
                <div class="mc-settings-row-control">
                  <PluginDropdown
                    :model-value="selectedMapProvider"
                    :options="mapProviderOptions"
                    :min-width="220"
                    @update:model-value="updateMapProvider"
                  />
                </div>
              </label>
            </section>

            <section class="mc-map-distance-card mc-settings-rows">
              <label class="mc-settings-row mc-map-distance-row">
                <div class="mc-settings-row-label">
                  <strong>{{ t('maps.distance.title') }}</strong>
                  <span>{{ t('maps.distance.subtitle') }}</span>
                </div>
                <div class="mc-settings-row-control">
                  <input
                    class="mc-map-distance-input"
                    type="number"
                    :value="mapMaxDistanceKm"
                    min="1"
                    max="20000"
                    step="1"
                    @change="updateMapMaxDistance($event.target.value)"
                  >
                  <span class="mc-map-distance-unit">км</span>
                </div>
              </label>
            </section>

            <section class="mc-map-location-card">
              <div class="mc-map-location-header">
                <h2>{{ t('maps.trace.title') }}</h2>
                <p>{{ t('maps.trace.subtitle') }}</p>
              </div>
              <button class="mc-map-action-button mc-map-action-button--wide" type="button" @click="openTraceScroller">
                {{ t('maps.trace.controls.open') }}
              </button>
            </section>

          </template>
        </div>
      </template>

      <template #workspace-header>
        <header class="mc-workspace-header mc-workspace-header--maps">
          <button
            v-tooltip="{ content: t('maps.controls.centerSelf'), theme: 'meshcorium-tooltip', placement: 'bottom' }"
            class="mc-icon-button mc-map-geo-button"
            type="button"
            :aria-label="t('maps.controls.centerSelf')"
            :disabled="!hasSelfCoordinates"
            @click="centerOnSelf"
          >
            <img :src="geoIconUrl" alt="" />
          </button>
          <button
            v-tooltip="{ content: mapThemeToggleTooltip, theme: 'meshcorium-tooltip', placement: 'bottom' }"
            class="mc-button mc-button--ghost mc-map-theme-toggle"
            type="button"
            :aria-label="mapThemeToggleTooltip"
            @click="toggleMapThemeMode"
          >
            {{ mapThemeToggleLabel }}
          </button>
          <p v-if="scrollerMode === 'trace'" class="mc-map-trace-header-note">
            {{ t('maps.trace.subtitle') }}
          </p>
          <div class="mc-map-status-row">
            <span class="mc-map-chip">{{ t('maps.status.pointsVisible', { count: mapPoints.length }) }}</span>
            <span class="mc-map-chip">{{ t('maps.status.selfLocation', { state: hasSelfCoordinates ? t('maps.status.available') : t('maps.status.missing') }) }}</span>
          </div>
        </header>
      </template>

      <template #workspace-body>
      <section class="mc-map-stage">
        <div v-if="activeMessageRouteModel" class="mc-map-route-panel">
          <div class="mc-map-route-panel-head">
            <div>
              <h3>{{ t('maps.messageRoute.title') }}</h3>
              <p>{{ activeMessageRouteModel.preview || t('maps.messageRoute.emptyPreview') }}</p>
            </div>
            <button class="mc-map-route-close" type="button" @click="clearActiveMessageRoute">×</button>
          </div>
          <div class="mc-map-route-panel-meta">
            <span class="mc-map-chip">{{ activeMessageRouteModel.conversationKind === 'contact' ? 'Direct' : 'Channel' }}</span>
            <span class="mc-map-chip">{{ t('maps.messageRoute.hopCount', { count: activeMessageRouteModel.hops.length }) }}</span>
            <span class="mc-map-chip">{{ t('maps.messageRoute.matchedCount', { count: activeMessageRouteModel.routeEntries.filter((entry) => entry.visiblePoints.length).length }) }}</span>
          </div>
          <div class="mc-map-route-panel-list">
            <div
              v-for="entry in activeMessageRouteModel.routeEntries"
              :key="entry.hop"
              class="mc-map-route-panel-item"
              :class="{ missing: !entry.visiblePoints.length }"
            >
              <div class="mc-map-route-panel-item-head">
                <span class="mc-map-route-panel-item-hop">{{ entry.displayHop }}</span>
                <span class="mc-map-route-panel-item-state">
                  {{ entry.visiblePoints.length ? t('maps.messageRoute.matched') : t('maps.messageRoute.missing') }}
                </span>
              </div>
              <div class="mc-map-route-panel-item-body">
                {{
                  entry.visiblePoints.length
                    ? entry.visiblePoints.map((point) => point.displayName).join(', ')
                    : t('maps.messageRoute.noMatch')
                }}
              </div>
            </div>
          </div>
        </div>
        <div v-if="mapLoading && !mapInstance" class="mc-map-stage-overlay">
          <div class="mc-workspace-empty mc-workspace-empty--maps">
            <h3>{{ t('maps.status.loadingTitle') }}</h3>
            <p>{{ t('maps.status.loadingSubtitle') }}</p>
          </div>
        </div>

        <div v-else-if="mapError" class="mc-map-stage-overlay">
          <div class="mc-workspace-empty mc-workspace-empty--maps">
            <h3>{{ t('maps.status.unavailableTitle') }}</h3>
            <p>{{ mapError }}</p>
          </div>
        </div>

        <div
          ref="mapViewportRef"
          class="mc-map-viewport"
          :class="{ 'is-ready': mapReady, 'is-dark': normalizedMapThemeMode === 'dark' }"
          :aria-label="t('maps.title')"
        ></div>
        <div
          v-if="mapContextMenu.open"
          class="mc-map-context-layer"
          @click="closeMapContextMenu"
          @contextmenu.prevent="closeMapContextMenu"
        >
          <div
            class="mc-map-context-menu"
            :style="{ left: `${mapContextMenu.x}px`, top: `${mapContextMenu.y}px` }"
            @click.stop
            @contextmenu.prevent
          >
            <p class="mc-map-context-coords">
              {{ Number(mapContextMenu.lat).toFixed(5) }}, {{ Number(mapContextMenu.lon).toFixed(5) }}
            </p>
            <template v-if="mapContextMenu.kind === 'ruler-point'">
              <button
                class="mc-map-action-button mc-map-context-action"
                type="button"
                @click="deleteRulerPointFromContextMenu"
              >
                {{ t('maps.contextMenu.deleteRulerPoint') }}
              </button>
            </template>
            <template v-else>
              <button
                class="mc-map-action-button mc-map-context-action"
                type="button"
                @click="addRulerPointFromContextMenu"
              >
                {{ t('maps.contextMenu.addRulerPoint') }}
              </button>
              <button
                class="mc-map-action-button mc-map-context-action"
                type="button"
                :disabled="!session.connected"
                @click="applyNodeLocationFromContextMenu"
              >
                {{ t('maps.contextMenu.setHomeNodeGeo') }}
              </button>
            </template>
          </div>
        </div>
      </section>
      </template>

      <template #scroller-footer>
        <div class="mc-status" :class="{ 'is-error': session.statusError }">
          {{ scrollerFooterStatus }}
        </div>
      </template>
    </ShellPageFrame>

    <Teleport to="body">
      <div v-if="tracePickerOpen" class="mc-overlay mc-overlay--soft" @click="closeTracePicker">
        <section class="mc-map-trace-picker" @click.stop>
          <div class="mc-map-route-panel-head">
            <div>
              <h3>{{ t('maps.trace.controls.pickRepeater') }}</h3>
              <p>{{ t('maps.trace.controls.pickRepeaterSubtitle') }}</p>
            </div>
            <button class="mc-map-route-close" type="button" @click="closeTracePicker">×</button>
          </div>
          <input
            v-model="tracePickerSearch"
            class="mc-map-trace-picker-search"
            type="text"
            :placeholder="t('maps.trace.controls.searchPlaceholder')"
          >
          <div class="mc-map-trace-picker-list mc-list-scroll">
            <button
              v-for="point in filteredTracePickerPoints"
              :key="`picker:${point.key}`"
              class="mc-map-trace-point"
              type="button"
              @click="addTracePointFromPicker(point)"
            >
              <span class="mc-map-trace-point-main">
                <span class="mc-map-trace-point-name">{{ point.displayName }}</span>
                <span class="mc-map-trace-point-meta">{{ point.shortPublicKey || t('maps.legend.repeater') }}</span>
              </span>
              <span class="mc-map-trace-point-check">+</span>
            </button>
            <div v-if="!filteredTracePickerPoints.length" class="mc-map-trace-empty">
              {{ t('maps.trace.empty.noSearchMatches') }}
            </div>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>
