<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { extractValidGeoPoint, isGeoWithinHomeDistance, safeCoordinate as safeGeoCoordinate } from '../../lib/geo'
import { ensureMapLibreLoaded } from '../../lib/mapLibre'
import { resolveNodePreviewUrl } from '../../lib/nodePreview'
import { useSessionStore } from '../../stores/session'

const props = defineProps({
  model: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['close'])

const session = useSessionStore()
const { t } = useI18n()

const MAP_MIN_ZOOM = 1
const MAP_MAX_ZOOM = 16
const OPENFREEMAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty'
const MAP_STYLE_BOOT_TIMEOUT_MS = 6000

const mapViewportRef = ref(null)
const mapInstance = ref(null)
const mapReady = ref(false)
const mapLoading = ref(false)
const mapError = ref('')

let mapMountPromise = null
let mapBootTimerId = 0
let mapMountToken = 0
let routeOverlayFrame = 0

function pointTypeLabel(point) {
  if (point.kind === 'self') {
    return t('maps.legend.self')
  }
  if (point.kind === 'contact') {
    return t('maps.legend.contact')
  }
  return t('maps.legend.repeater')
}

function normalizePublicKey(value) {
  return String(value || '').trim().toLowerCase()
}

const safeCoordinate = safeGeoCoordinate

function clampMapLatitude(lat) {
  return Math.max(-85.05112878, Math.min(85.05112878, lat))
}

function normalizeMapLongitude(lon) {
  return ((((lon + 180) % 360) + 360) % 360) - 180
}

function contactDisplayName(contact) {
  return String(contact?.adv_name || contact?.name || contact?.pubkey_prefix || contact?.public_key || '').trim()
    || t('messages.fallback.unnamedContact')
}

function normalizeRouteHopToken(token) {
  const normalized = String(token || '').trim().toUpperCase()
  if (!normalized || !/^[0-9A-F]+$/.test(normalized)) {
    return ''
  }
  return normalized
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

function matchStoredContactRouteHop(contact, hop) {
  const normalizedHop = normalizeRouteHopToken(hop)
  if (!normalizedHop) {
    return false
  }
  return buildStoredContactRouteHops(contact).some((token) => token.startsWith(normalizedHop))
}

function collectKnownRouteHopCandidates() {
  const candidates = new Set()
  const remember = (token) => {
    const normalized = normalizeRouteHopToken(token)
    if (normalized) {
      candidates.add(normalized)
    }
  }
  remember(session.self?.public_key)
  for (const contact of (Array.isArray(session.contacts) ? session.contacts : [])) {
    remember(contact?.public_key)
    for (const hop of buildStoredContactRouteHops(contact)) {
      remember(hop)
    }
  }
  const modelHops = Array.isArray(props.model?.hops) ? props.model.hops : []
  for (const hop of modelHops) {
    remember(hop)
  }
  return Array.from(candidates)
}

function resolvePreferredRouteHopToken(hop, preferredHexLen = 4) {
  const normalized = normalizeRouteHopToken(hop)
  if (!normalized) {
    return ''
  }
  if (normalized.length >= preferredHexLen) {
    return normalized.slice(0, preferredHexLen)
  }
  const candidatePrefixes = new Set()
  for (const candidate of collectKnownRouteHopCandidates()) {
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
  return resolvePreferredRouteHopToken(hop, 4) || normalizeRouteHopToken(hop)
}

function buildFallbackMapStyle() {
  return {
    version: 8,
    name: 'MeshCorium fallback',
    sources: {},
    layers: [
      {
        id: 'meshcorium-background',
        type: 'background',
        paint: {
          'background-color': '#10202f',
        },
      },
    ],
  }
}

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

function destroyMap() {
  mapMountToken += 1
  mapMountPromise = null
  clearMapBootTimer()
  cancelRouteOverlayFrame()
  mapViewportRef.value?.querySelector('.mc-map-route-overlay')?.remove()
  mapViewportRef.value?.querySelector('.mc-map-route-callout-layer')?.remove()
  if (mapInstance.value) {
    try {
      mapInstance.value.remove()
    } catch {
      // Ignore stale map cleanup failures.
    }
  }
  mapInstance.value = null
  mapReady.value = false
  mapLoading.value = false
}

const activeMessageRoute = computed(() => {
  if (!props.model?.open) {
    return null
  }
  const hops = Array.isArray(props.model?.hops)
    ? props.model.hops.map((hop) => String(hop || '').trim().toUpperCase()).filter(Boolean)
    : []
  if (!hops.length) {
    return null
  }
  return {
    hops,
    preview: String(props.model?.preview || '').trim(),
    conversationKind: String(props.model?.conversationKind || '').trim() || 'channel',
  }
})

const repeaterMapPoints = computed(() => {
  const homePoint = extractValidGeoPoint(session.self)
  return (Array.isArray(session.contacts) ? session.contacts : [])
    .filter((contact) => Number(contact?.adv_type || 0) === 2)
    .map((contact) => {
      const coords = extractValidGeoPoint(contact)
      if (!coords || !isGeoWithinHomeDistance(coords, homePoint)) {
        return null
      }
      return {
        key: normalizePublicKey(contact?.public_key) || `repeater:${normalizePublicKey(contact?.pubkey_prefix)}`,
        kind: 'repeater',
        lat: coords.lat,
        lon: coords.lon,
        displayName: contactDisplayName(contact),
        publicKey: normalizePublicKey(contact?.public_key),
        shortPublicKey: String(contact?.pubkey_prefix || '').trim().slice(0, 4).toUpperCase(),
        routeTokens: buildStoredContactRouteHops(contact),
      }
    })
    .filter(Boolean)
})

const selfRoutePoint = computed(() => {
  const coords = extractValidGeoPoint(session.self)
  if (!coords) {
    return null
  }
  return {
    key: 'self',
    kind: 'self',
    lat: coords.lat,
    lon: coords.lon,
    displayName: String(session.self?.name || session.device?.manufacturer_model || '').trim() || t('common.unknownNode'),
    publicKey: normalizePublicKey(session.self?.public_key),
    shortPublicKey: String(session.self?.public_key || '').trim().slice(0, 4).toUpperCase(),
    previewUrl: resolveNodePreviewUrl(session.device?.manufacturer_model || session.self?.name || ''),
  }
})

const participantMapPoints = computed(() => {
  const homePoint = extractValidGeoPoint(session.self)
  const requested = Array.isArray(props.model?.participants) ? props.model.participants : []
  return requested.map((participant, index) => {
    const publicKey = normalizePublicKey(participant?.public_key)
    const publicKeyPrefix = normalizePublicKey(participant?.pubkey_prefix).slice(0, 12)
    const normalizedName = String(participant?.name || '').trim().toLowerCase()
    const directCoords = extractValidGeoPoint(participant)
    const contact = directCoords ? null : ((Array.isArray(session.contacts) ? session.contacts : []).find((entry) => {
      const entryKey = normalizePublicKey(entry?.public_key)
      const entryPrefix = normalizePublicKey(entry?.pubkey_prefix || entry?.public_key).slice(0, 12)
      const entryName = String(contactDisplayName(entry) || '').trim().toLowerCase()
      return (publicKey && entryKey === publicKey)
        || (publicKeyPrefix && entryPrefix === publicKeyPrefix)
        || (normalizedName && entryName === normalizedName)
    }) || null)
    const coords = directCoords || extractValidGeoPoint(contact)
    if (!coords || !isGeoWithinHomeDistance(coords, homePoint)) {
      return null
    }
    return {
      key: `participant:${publicKey || publicKeyPrefix || normalizedName || index}:${index}`,
      kind: 'contact',
      lat: coords.lat,
      lon: coords.lon,
      displayName: String(participant?.name || contactDisplayName(contact)).trim() || t('messages.fallback.unnamedContact'),
      publicKey,
      shortPublicKey: String(participant?.pubkey_prefix || contact?.pubkey_prefix || '').trim().slice(0, 4).toUpperCase(),
      role: String(participant?.role || 'participant').trim(),
    }
  }).filter(Boolean).filter((point, index, points) => {
    return points.findIndex((entry) => entry.key === point.key) === index
  })
})

const activeMessageRouteModel = computed(() => {
  const payload = activeMessageRoute.value
  if (!payload) {
    return null
  }
  const routeEntries = payload.hops.map((hop, index) => {
    const normalizedHop = normalizeRouteHopToken(hop).toLowerCase()
    const visiblePoints = repeaterMapPoints.value.filter((point) => {
      if (point.publicKey.startsWith(normalizedHop)) {
        return true
      }
      return Array.isArray(point.routeTokens) && point.routeTokens.some((token) => String(token || '').trim().toLowerCase().startsWith(normalizedHop))
    })
    return {
      hop,
      displayHop: expandRouteHopForDisplay(hop),
      index,
      visiblePoints,
      primaryVisiblePoint: visiblePoints[0] || null,
    }
  })
  const knownRoutePoints = []
  for (const participantPoint of participantMapPoints.value) {
    knownRoutePoints.push(participantPoint)
  }
  if (selfRoutePoint.value) {
    knownRoutePoints.push(selfRoutePoint.value)
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
  if (selfRoutePoint.value && visibleEntries.length) {
    const lastEntry = visibleEntries[visibleEntries.length - 1]
    routeSegments.push({
      from: lastEntry.primaryVisiblePoint,
      to: selfRoutePoint.value,
      kind: Math.max(0, routeEntries.length - lastEntry.index - 1) > 0 ? 'gap' : 'route',
    })
  }
  if (participantMapPoints.value.length) {
    const firstVisibleRepeater = visibleEntries[0]?.primaryVisiblePoint || null
    const endpointTarget = firstVisibleRepeater || selfRoutePoint.value || null
    if (endpointTarget) {
      for (const participantPoint of participantMapPoints.value) {
        routeSegments.unshift({
          from: participantPoint,
          to: endpointTarget,
          kind: 'participant',
        })
      }
    }
  }
  return {
    ...payload,
    routeEntries,
    participantPoints: participantMapPoints.value,
    knownRoutePoints: dedupedKnownRoutePoints,
    routeSegments,
  }
})

function focusPoint(point, { animate = true } = {}) {
  if (!mapInstance.value || !point) {
    return
  }
  mapInstance.value[animate ? 'easeTo' : 'jumpTo']({
    center: [point.lon, point.lat],
    zoom: Math.max(12, Number(mapInstance.value.getZoom?.() || 12)),
    duration: animate ? 240 : 0,
  })
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

function projectMapPoint(point) {
  if (!mapInstance.value || !point) {
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

function estimateParticipantLabelWidth(point) {
  const name = String(point?.displayName || '').trim()
  const shortKey = String(point?.shortPublicKey || '').trim()
  const longestLine = Math.max(name.length, shortKey.length, 6)
  return Math.max(108, Math.min(220, 28 + (longestLine * 7)))
}

function renderRouteOverlay() {
  const viewport = mapViewportRef.value
  const model = activeMessageRouteModel.value
  if (!viewport) {
    return
  }
  viewport.querySelector('.mc-map-route-overlay')?.remove()
  viewport.querySelector('.mc-map-route-callout-layer')?.remove()
  if (!mapInstance.value || !model || !model.knownRoutePoints.length) {
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
  const calloutLayer = document.createElement('div')
  calloutLayer.className = 'mc-map-route-callout-layer'
  let hasPaths = false
  for (const segment of model.routeSegments) {
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
  for (const point of model.knownRoutePoints) {
    const projected = projectMapPoint(point)
    if (!projected) {
      continue
    }
    const pointClass = point.kind === 'self'
      ? 'mc-map-route-point-self'
      : (point.kind === 'repeater' ? 'mc-map-route-point-repeater' : 'mc-map-route-point-contact')
    const haloClass = point.kind === 'self'
      ? 'mc-map-route-point-self-halo'
      : (point.kind === 'repeater' ? 'mc-map-route-point-repeater-halo' : 'mc-map-route-point-contact-halo')

    const halo = document.createElementNS(svgNS, 'circle')
    halo.setAttribute('class', haloClass)
    halo.setAttribute('cx', projected.x.toFixed(2))
    halo.setAttribute('cy', projected.y.toFixed(2))
    halo.setAttribute('r', point.kind === 'self' ? '11' : '9')
    svg.appendChild(halo)

    const dot = document.createElementNS(svgNS, 'circle')
    dot.setAttribute('class', pointClass)
    dot.setAttribute('cx', projected.x.toFixed(2))
    dot.setAttribute('cy', projected.y.toFixed(2))
    dot.setAttribute('r', point.kind === 'self' ? '7' : '6')
    svg.appendChild(dot)

    if (point.kind !== 'contact' && point.kind !== 'repeater' && point.kind !== 'self') {
      hasPaths = true
      continue
    }
    {
      const labelWidth = estimateParticipantLabelWidth(point)
      const labelHeight = 42
      const labelX = Math.max(6, Math.min(width - labelWidth - 6, projected.x - (labelWidth / 2)))
      const labelY = Math.max(6, projected.y - 56)
      const host = document.createElement('div')
      host.className = 'mc-map-route-point-callout'
      host.style.left = `${labelX.toFixed(2)}px`
      host.style.top = `${labelY.toFixed(2)}px`
      host.style.width = `${labelWidth}px`
      host.style.minHeight = `${labelHeight}px`

      const nameLine = document.createElement('div')
      nameLine.className = 'mc-map-route-point-callout-name'
      nameLine.textContent = String(point.displayName || '')
      host.appendChild(nameLine)

      const keyLine = document.createElement('div')
      keyLine.className = 'mc-map-route-point-callout-key'
      keyLine.textContent = String(point.shortPublicKey || '').trim() || '????'
      host.appendChild(keyLine)

      calloutLayer.appendChild(host)
    }
    hasPaths = true
  }
  if (!hasPaths) {
    return
  }
  viewport.appendChild(svg)
  viewport.appendChild(calloutLayer)
}

function scheduleRouteOverlayRender() {
  cancelRouteOverlayFrame()
  routeOverlayFrame = window.requestAnimationFrame(() => {
    routeOverlayFrame = 0
    renderRouteOverlay()
  })
}

function geometricRouteCenter(points) {
  const validPoints = Array.isArray(points) ? points.filter(Boolean) : []
  if (!validPoints.length) {
    return null
  }
  const lat = validPoints.reduce((sum, point) => sum + Number(point.lat || 0), 0) / validPoints.length
  const lon = validPoints.reduce((sum, point) => sum + Number(point.lon || 0), 0) / validPoints.length
  return {
    lat: clampMapLatitude(lat),
    lon: normalizeMapLongitude(lon),
  }
}

function routeViewportZoom(points, viewportWidth, viewportHeight) {
  if (!Array.isArray(points) || !points.length) {
    return 11
  }
  if (points.length === 1) {
    return 13
  }
  const minLat = Math.min(...points.map((point) => point.lat))
  const maxLat = Math.max(...points.map((point) => point.lat))
  const minLon = Math.min(...points.map((point) => point.lon))
  const maxLon = Math.max(...points.map((point) => point.lon))
  const latSpan = Math.max(0.08, maxLat - minLat)
  const lonSpan = Math.max(0.08, maxLon - minLon)
  const zoomX = Math.log2((Math.max(360, viewportWidth) * 360) / (lonSpan * 256))
  const zoomY = Math.log2((Math.max(240, viewportHeight) * 170) / (latSpan * 256))
  return Math.max(MAP_MIN_ZOOM, Math.min(MAP_MAX_ZOOM, Math.floor(Math.min(zoomX, zoomY))))
}

function focusRouteViewport({ animate = false } = {}) {
  const model = activeMessageRouteModel.value
  if (!mapInstance.value || !model || !model.knownRoutePoints.length) {
    return
  }
  const viewportEl = mapViewportRef.value
  const center = geometricRouteCenter(model.knownRoutePoints)
  if (!center) {
    return
  }
  const zoom = routeViewportZoom(
    model.knownRoutePoints,
    Number(viewportEl?.clientWidth || 0),
    Number(viewportEl?.clientHeight || 0),
  )
  mapInstance.value[animate ? 'easeTo' : 'jumpTo']({
    center: [center.lon, center.lat],
    zoom,
    duration: animate ? 260 : 0,
  })
}

async function mountMap() {
  if (!props.model?.open || !mapViewportRef.value || mapInstance.value) {
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
      const knownPoints = activeMessageRouteModel.value?.knownRoutePoints || []
      const center = geometricRouteCenter(knownPoints)
        || { lat: 55.75, lon: 37.62 }
      const zoom = routeViewportZoom(
        knownPoints,
        Number(mapViewportRef.value?.clientWidth || 0),
        Number(mapViewportRef.value?.clientHeight || 0),
      )
      const instance = new window.maplibregl.Map({
        container: mapViewportRef.value,
        style: OPENFREEMAP_STYLE_URL,
        center: [center.lon, center.lat],
        zoom,
        attributionControl: false,
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
          scheduleRouteOverlayRender()
        })
      }

      const fallbackToLocalStyle = () => {
        if (mountToken !== mapMountToken || mapInstance.value !== instance || instance.__meshcoriumFallbackStyleApplied) {
          return
        }
        instance.__meshcoriumFallbackStyleApplied = true
        try {
          instance.setStyle(buildFallbackMapStyle())
        } catch {
          // Ignore style fallback failures.
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
      instance.on('error', () => {
        if (!mapReady.value) {
          fallbackToLocalStyle()
        }
      })
      instance.on('move', scheduleRouteOverlayRender)
      instance.on('zoom', scheduleRouteOverlayRender)
      instance.on('resize', scheduleRouteOverlayRender)
      instance.on('idle', scheduleRouteOverlayRender)
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

watch(() => props.model?.open, async (open) => {
  if (!open) {
    destroyMap()
    return
  }
  await nextTick()
  await mountMap()
})

watch(activeMessageRouteModel, () => {
  if (!props.model?.open || !mapInstance.value) {
    return
  }
  scheduleRouteOverlayRender()
})

onBeforeUnmount(() => {
  destroyMap()
})

onMounted(async () => {
  if (!props.model?.open) {
    return
  }
  await nextTick()
  await mountMap()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="model.open" class="mc-overlay" @click="emit('close')">
      <section class="mc-message-route-sheet" @click.stop>
        <div class="mc-map-stage mc-map-stage--message-route">
          <div class="mc-map-route-panel mc-map-route-panel--sheet">
            <div class="mc-map-route-panel-head">
              <div>
                <h3>{{ t('maps.messageRoute.title') }}</h3>
                <p>{{ activeMessageRouteModel?.preview || t('maps.messageRoute.emptyPreview') }}</p>
              </div>
              <button class="mc-map-route-close" type="button" @click="emit('close')">×</button>
            </div>
            <div v-if="activeMessageRouteModel" class="mc-map-route-panel-meta">
              <span class="mc-map-chip">{{ activeMessageRouteModel.conversationKind === 'contact' ? 'Direct' : 'Channel' }}</span>
              <span class="mc-map-chip">{{ t('maps.messageRoute.hopCount', { count: activeMessageRouteModel.hops.length }) }}</span>
              <span class="mc-map-chip">{{ t('maps.messageRoute.matchedCount', { count: activeMessageRouteModel.routeEntries.filter((entry) => entry.visiblePoints.length).length }) }}</span>
            </div>
            <div v-if="activeMessageRouteModel" class="mc-map-route-panel-list">
              <div
                v-for="entry in activeMessageRouteModel.routeEntries"
                :key="entry.hop"
                class="mc-map-route-panel-item"
                :class="{ missing: !entry.visiblePoints.length }"
                @click="entry.primaryVisiblePoint && focusPoint(entry.primaryVisiblePoint)"
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

          <div ref="mapViewportRef" class="mc-map-viewport" :class="{ 'is-ready': mapReady }" :aria-label="t('maps.messageRoute.title')"></div>
        </div>
      </section>
    </div>
  </Teleport>
</template>
