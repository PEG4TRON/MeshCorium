<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ensureMapLibreLoaded } from '../../lib/mapLibre'

const OPENFREEMAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty'

const props = defineProps({
  model: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits([
  'close',
  'update:input-value',
  'update:trace-sequential',
  'clear-input',
  'toggle-public-key',
  'save',
  'reset-stored',
  'start-trace',
  'cancel-trace',
])

const { t } = useI18n()

const mapViewportRef = ref(null)
const mapInstance = ref(null)
const mapMarkers = ref([])
let overlayFrame = 0

const mapSignature = computed(() => JSON.stringify({
  open: Boolean(props.model?.open),
  repeaters: Array.isArray(props.model?.mapRepeaters)
    ? props.model.mapRepeaters.map((point) => ({
      key: String(point?.publicKey || ''),
      lat: Number(point?.lat || 0),
      lon: Number(point?.lon || 0),
      selected: Boolean(point?.selected),
      kind: String(point?.kind || ''),
    }))
    : [],
  route: Array.isArray(props.model?.routePoints)
    ? props.model.routePoints.map((point) => ({
      key: String(point?.publicKey || ''),
      lat: Number(point?.lat || 0),
      lon: Number(point?.lon || 0),
      kind: String(point?.kind || ''),
    }))
    : [],
}))

function cancelOverlayFrame() {
  if (!overlayFrame) {
    return
  }
  window.cancelAnimationFrame(overlayFrame)
  overlayFrame = 0
}

function destroyMap() {
  cancelOverlayFrame()
  for (const marker of mapMarkers.value) {
    try {
      marker.remove()
    } catch {
      // ignore marker cleanup failures
    }
  }
  mapMarkers.value = []
  if (mapInstance.value) {
    try {
      mapInstance.value.remove()
    } catch {
      // ignore map cleanup failures
    }
  }
  mapInstance.value = null
  if (mapViewportRef.value) {
    mapViewportRef.value.innerHTML = ''
  }
}

function buildMarkerElement(point) {
  const element = document.createElement('button')
  element.type = 'button'
  element.className = `mc-contact-route-marker is-${String(point?.kind || 'repeater')}`
  if (point?.selected) {
    element.classList.add('is-selected')
  }
  if (point?.kind === 'self') {
    element.textContent = '⌂'
  } else if (point?.kind === 'contact') {
    element.textContent = '◎'
  } else {
    element.textContent = '●'
  }
  element.title = String(point?.label || '')
  if (point?.kind !== 'repeater') {
    element.disabled = true
  } else {
    element.addEventListener('click', (event) => {
      event.preventDefault()
      event.stopPropagation()
      emit('toggle-public-key', String(point?.publicKey || ''))
    })
  }
  return element
}

function syncMarkers() {
  for (const marker of mapMarkers.value) {
    try {
      marker.remove()
    } catch {
      // ignore marker cleanup failures
    }
  }
  mapMarkers.value = []
  if (!mapInstance.value || !window.maplibregl) {
    return
  }
  const points = [
    ...(Array.isArray(props.model?.mapRepeaters) ? props.model.mapRepeaters : []),
    ...((Array.isArray(props.model?.routePoints) ? props.model.routePoints : []).filter((point) => (
      point?.kind === 'self' || point?.kind === 'contact'
    ))),
  ]
  mapMarkers.value = points
    .filter((point) => Number.isFinite(Number(point?.lat)) && Number.isFinite(Number(point?.lon)))
    .map((point) => {
      const marker = new window.maplibregl.Marker({
        element: buildMarkerElement(point),
        anchor: 'center',
      }).setLngLat([Number(point.lon), Number(point.lat)])
      marker.addTo(mapInstance.value)
      return marker
    })
}

function buildLinePath(points) {
  if (!mapInstance.value || points.length < 2) {
    return ''
  }
  const commands = []
  for (let index = 0; index < points.length; index += 1) {
    const projected = mapInstance.value.project([Number(points[index].lon), Number(points[index].lat)])
    const x = Number(projected?.x)
    const y = Number(projected?.y)
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return ''
    }
    commands.push(`${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`)
  }
  return commands.join(' ')
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

function renderRouteOverlay() {
  const viewport = mapViewportRef.value
  if (!viewport) {
    return
  }
  viewport.querySelector('.mc-contact-route-overlay-host')?.remove()
  viewport.querySelector('.mc-contact-route-failure')?.remove()
  if (!mapInstance.value) {
    return
  }
  const points = (Array.isArray(props.model?.routePoints) ? props.model.routePoints : [])
    .filter((point) => Number.isFinite(Number(point?.lat)) && Number.isFinite(Number(point?.lon)))
  if (points.length < 2) {
    return
  }
  const svgNS = 'http://www.w3.org/2000/svg'
  const host = document.createElement('div')
  host.className = 'mc-contact-route-overlay-host'
  const svg = document.createElementNS(svgNS, 'svg')
  svg.setAttribute('class', 'mc-contact-route-overlay')
  svg.setAttribute('viewBox', `0 0 ${Math.max(1, viewport.clientWidth)} ${Math.max(1, viewport.clientHeight)}`)
  svg.setAttribute('width', String(Math.max(1, viewport.clientWidth)))
  svg.setAttribute('height', String(Math.max(1, viewport.clientHeight)))
  for (let index = 0; index < points.length - 1; index += 1) {
    const pathData = buildLinePath([points[index], points[index + 1]])
    if (!pathData) {
      continue
    }
    const traceBadge = Array.isArray(props.model?.traceLineBadges)
      ? props.model.traceLineBadges.find((entry) => Number(entry?.segmentIndex) === index) || null
      : null
    const base = document.createElementNS(svgNS, 'path')
    base.setAttribute('class', 'mc-contact-route-overlay-base')
    if (traceBadge?.failed) {
      base.classList.add('failed')
    }
    base.setAttribute('d', pathData)
    svg.appendChild(base)
    const glow = document.createElementNS(svgNS, 'path')
    glow.setAttribute('class', 'mc-contact-route-overlay-glow')
    if (traceBadge?.failed) {
      glow.classList.add('failed')
    }
    glow.setAttribute('d', pathData)
    svg.appendChild(glow)
    if (!traceBadge) {
      continue
    }
    const start = mapInstance.value.project([Number(points[index].lon), Number(points[index].lat)])
    const end = mapInstance.value.project([Number(points[index + 1].lon), Number(points[index + 1].lat)])
    if (!Number.isFinite(Number(start?.x)) || !Number.isFinite(Number(start?.y)) || !Number.isFinite(Number(end?.x)) || !Number.isFinite(Number(end?.y))) {
      continue
    }
    const midX = (start.x + end.x) / 2
    const midY = (start.y + end.y) / 2
    const dx = end.x - start.x
    const dy = end.y - start.y
    const length = Math.max(1, Math.hypot(dx, dy))
    const normalX = -dy / length
    const normalY = dx / length
    appendTraceBadgeStack(
      svg,
      midX + normalX * 18,
      midY + normalY * 18,
      traceBadge.rxLabel,
      traceBadge.txLabel,
    )
  }
  host.appendChild(svg)
  viewport.appendChild(host)
  if (props.model?.traceFailureVisible) {
    const failure = document.createElement('div')
    failure.className = 'mc-contact-route-failure'
    failure.textContent = t('contactsView.routeEditor.traceFailure')
    viewport.appendChild(failure)
  }
}

function scheduleRouteOverlay() {
  cancelOverlayFrame()
  overlayFrame = window.requestAnimationFrame(() => {
    overlayFrame = 0
    renderRouteOverlay()
  })
}

function fitMapToPoints() {
  if (!mapInstance.value || !window.maplibregl) {
    return
  }
  const points = [
    ...(Array.isArray(props.model?.mapRepeaters) ? props.model.mapRepeaters : []),
    ...(Array.isArray(props.model?.routePoints) ? props.model.routePoints : []),
  ].filter((point) => Number.isFinite(Number(point?.lat)) && Number.isFinite(Number(point?.lon)))
  if (!points.length) {
    return
  }
  if (points.length === 1) {
    mapInstance.value.easeTo({
      center: [Number(points[0].lon), Number(points[0].lat)],
      zoom: 12,
      duration: 0,
    })
    return
  }
  const bounds = new window.maplibregl.LngLatBounds()
  for (const point of points) {
    bounds.extend([Number(point.lon), Number(point.lat)])
  }
  mapInstance.value.fitBounds(bounds, {
    padding: 56,
    maxZoom: 13,
    duration: 0,
  })
}

async function mountMap() {
  if (!props.model?.open || !mapViewportRef.value) {
    return
  }
  if (!window.maplibregl) {
    try {
      await ensureMapLibreLoaded()
    } catch {
      if (mapViewportRef.value) {
        mapViewportRef.value.innerHTML = `<div class="mc-contact-route-map-empty">${t('maps.status.unavailable')}</div>`
      }
      return
    }
  }
  if (!props.model?.open || !mapViewportRef.value || !window.maplibregl) {
    return
  }
  destroyMap()
  const points = (Array.isArray(props.model?.routePoints) ? props.model.routePoints : [])
    .filter((point) => Number.isFinite(Number(point?.lat)) && Number.isFinite(Number(point?.lon)))
  const firstPoint = points[0] || (Array.isArray(props.model?.mapRepeaters) ? props.model.mapRepeaters[0] : null)
  if (!firstPoint) {
    mapViewportRef.value.innerHTML = `<div class="mc-contact-route-map-empty">${t('maps.empty.noPointsSubtitle')}</div>`
    return
  }
  const instance = new window.maplibregl.Map({
    container: mapViewportRef.value,
    style: OPENFREEMAP_STYLE_URL,
    center: [Number(firstPoint.lon), Number(firstPoint.lat)],
    zoom: 8,
    attributionControl: false,
  })
  mapInstance.value = instance
  instance.addControl(new window.maplibregl.NavigationControl(), 'top-right')
  const sync = () => {
    syncMarkers()
    scheduleRouteOverlay()
  }
  instance.on('load', () => {
    fitMapToPoints()
    sync()
  })
  instance.on('move', scheduleRouteOverlay)
  instance.on('moveend', scheduleRouteOverlay)
  instance.on('zoom', scheduleRouteOverlay)
  instance.on('zoomend', scheduleRouteOverlay)
  instance.on('resize', scheduleRouteOverlay)
  instance.on('idle', scheduleRouteOverlay)
  await nextTick()
  instance.resize()
  sync()
}

watch(() => props.model?.open, async (open) => {
  if (!open) {
    destroyMap()
    return
  }
  await nextTick()
  await mountMap()
})

watch(mapSignature, async () => {
  if (!props.model?.open) {
    return
  }
  if (!mapInstance.value) {
    await nextTick()
    await mountMap()
    return
  }
  syncMarkers()
  fitMapToPoints()
  scheduleRouteOverlay()
})

onBeforeUnmount(() => {
  destroyMap()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="model.open" class="mc-overlay mc-overlay--soft" @click="emit('close')">
      <section class="mc-contact-route-sheet" @click.stop>
        <div class="mc-contact-route-head">
          <div>
            <h2>{{ t('contactsView.routeEditor.title') }}</h2>
            <p>{{ t('contactsView.routeEditor.subtitle', { target: model.contactTitle || t('messages.fallback.unnamedContact') }) }}</p>
          </div>
          <button class="mc-map-route-close" type="button" @click="emit('close')">×</button>
        </div>

        <div class="mc-contact-route-body">
          <aside class="mc-contact-route-side">
            <label class="mc-settings-row mc-settings-row--contacts">
              <div class="mc-settings-row-label">
                <strong>{{ t('contactsView.routeEditor.inputLabel') }}</strong>
                <span>{{ t('contactsView.routeEditor.inputHint') }}</span>
              </div>
              <div class="mc-settings-row-control">
                <div class="mc-contact-route-input-wrap">
                  <textarea
                    :value="model.inputValue"
                    class="mc-contact-route-input"
                    spellcheck="false"
                    :placeholder="t('contactsView.routeEditor.inputPlaceholder')"
                    @input="emit('update:input-value', $event.target.value)"
                  />
                  <button class="mc-contact-route-clear" type="button" @click="emit('clear-input')">
                    {{ t('common.clear') }}
                  </button>
                </div>
              </div>
            </label>

            <div class="mc-contact-route-tools">
              <button class="mc-button mc-button--ghost" type="button" :disabled="!model.canStartTrace" @click="emit('start-trace')">
                {{ model.traceBusy ? t('contactsView.routeEditor.traceBusy') : t('contactsView.routeEditor.openTrace') }}
              </button>
              <button
                v-if="model.traceBusy"
                class="mc-button mc-button--ghost"
                type="button"
                @click="emit('cancel-trace')"
              >
                {{ t('contactsView.routeEditor.cancelTrace') }}
              </button>
              <button
                class="mc-button mc-button--ghost"
                type="button"
                :disabled="!model.canResetStoredRoute"
                @click="emit('reset-stored')"
              >
                {{ t('contactsView.routeEditor.resetStored') }}
              </button>
            </div>

            <label class="mc-contact-route-trace-toggle">
              <input
                :checked="model.traceSequential"
                type="checkbox"
                :disabled="model.traceBusy"
                @change="emit('update:trace-sequential', $event.target.checked)"
              >
              <span>{{ t('contactsView.routeEditor.traceSequential') }}</span>
            </label>

            <p class="mc-contact-route-summary">{{ model.summaryText }}</p>

            <div
              v-if="model.traceResult"
              class="mc-map-trace-status"
              :class="{ 'is-error': model.traceResult && !model.traceBusy && !model.traceResult.success && model.traceResult.status !== 'cancelled' }"
            >
              {{ model.summaryText }}
            </div>

            <div v-if="model.traceLegendVisible" class="mc-contact-route-trace-legend">
              <span class="mc-contact-route-trace-legend-item">
                <span class="mc-contact-route-trace-legend-swatch tx" />
                {{ t('contactsView.routeEditor.traceLegendTx') }}
              </span>
              <span class="mc-contact-route-trace-legend-item">
                <span class="mc-contact-route-trace-legend-swatch rx" />
                {{ t('contactsView.routeEditor.traceLegendRx') }}
              </span>
            </div>

            <div class="mc-contact-route-resolved-list mc-list-scroll">
              <template v-if="model.resolvedEntries?.length">
                <template v-for="entry in model.resolvedEntries" :key="entry.token">
                  <button
                    v-if="entry.unique"
                    type="button"
                    class="mc-contact-route-resolved-item"
                    :class="{ active: entry.selected }"
                    @click="emit('toggle-public-key', entry.publicKey)"
                  >
                    <div>
                      <p class="mc-contact-route-resolved-title">{{ entry.title }}</p>
                      <p class="mc-contact-route-resolved-meta">{{ entry.shortKey }} · {{ entry.note }}</p>
                    </div>
                    <span class="mc-contact-route-resolved-check">{{ entry.selected ? '●' : '+' }}</span>
                  </button>
                  <div v-else class="mc-contact-route-resolved-item is-unresolved">
                    <p class="mc-contact-route-resolved-title">{{ entry.token }}</p>
                    <p class="mc-contact-route-resolved-meta">{{ entry.note }}</p>
                  </div>
                </template>
              </template>
              <div v-else class="mc-contact-route-empty">
                {{ t('contactsView.routeEditor.empty') }}
              </div>
            </div>

            <div v-if="model.traceStepModels?.length" class="mc-map-trace-steps">
              <article
                v-for="step in model.traceStepModels"
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
                        : (
                          step.success
                            ? t('maps.trace.step.successShort')
                            : t('maps.trace.step.failedShort')
                        )
                    }}
                  </span>
                </div>
                <div class="mc-map-trace-step-route">{{ step.participantLabel }}</div>
                <div class="mc-map-trace-step-meta">{{ step.meta }}</div>
                <div v-if="step.hopLabels.length" class="mc-map-trace-step-hops">
                  {{ step.hopLabels.join(' · ') }}
                </div>
              </article>
            </div>

            <div class="mc-contact-route-actions">
              <button class="mc-button mc-button--ghost" type="button" @click="emit('close')">
                {{ t('common.cancel') }}
              </button>
              <button class="mc-button mc-button--primary" type="button" @click="emit('save')">
                {{ t('common.save') }}
              </button>
            </div>
          </aside>

          <div class="mc-contact-route-map">
            <div ref="mapViewportRef" class="mc-contact-route-map-viewport" />
          </div>
        </div>
      </section>
    </div>
  </Teleport>
</template>
