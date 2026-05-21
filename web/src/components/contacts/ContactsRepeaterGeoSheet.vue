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
  'pick',
])

const { t } = useI18n()

const mapViewportRef = ref(null)
const mapInstance = ref(null)
const mapMarkers = ref([])
const mapContextMenu = ref({
  open: false,
  x: 0,
  y: 0,
  lat: null,
  lon: null,
})

const mapSignature = computed(() => JSON.stringify({
  open: Boolean(props.model?.open),
  selfPoint: props.model?.selfPoint
    ? {
      lat: Number(props.model.selfPoint.lat || 0),
      lon: Number(props.model.selfPoint.lon || 0),
      label: String(props.model.selfPoint.label || ''),
    }
    : null,
  repeaterPoint: props.model?.repeaterPoint
    ? {
      lat: Number(props.model.repeaterPoint.lat || 0),
      lon: Number(props.model.repeaterPoint.lon || 0),
      label: String(props.model.repeaterPoint.label || ''),
    }
    : null,
}))

function closeMapContextMenu() {
  mapContextMenu.value = {
    open: false,
    x: 0,
    y: 0,
    lat: null,
    lon: null,
  }
}

function destroyMap() {
  closeMapContextMenu()
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

function markerPoints() {
  return [
    props.model?.selfPoint
      ? {
        ...props.model.selfPoint,
        kind: 'self',
      }
      : null,
    props.model?.repeaterPoint
      ? {
        ...props.model.repeaterPoint,
        kind: 'repeater',
      }
      : null,
  ].filter((point) => Number.isFinite(Number(point?.lat)) && Number.isFinite(Number(point?.lon)))
}

function buildMarkerElement(point) {
  const element = document.createElement('div')
  element.className = `mc-contact-route-marker is-${String(point?.kind || 'repeater')}`
  element.textContent = point?.kind === 'self' ? '⌂' : '●'
  element.title = String(point?.label || '')
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
  mapMarkers.value = markerPoints().map((point) => {
    const marker = new window.maplibregl.Marker({
      element: buildMarkerElement(point),
      anchor: 'center',
    }).setLngLat([Number(point.lon), Number(point.lat)])
    marker.addTo(mapInstance.value)
    return marker
  })
}

function fitMapToPoints() {
  if (!mapInstance.value || !window.maplibregl) {
    return
  }
  const points = markerPoints()
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
    padding: 64,
    maxZoom: 13,
    duration: 0,
  })
}

function clampContextMenuPosition(x, y) {
  const viewport = mapViewportRef.value
  if (!viewport) {
    return { x, y }
  }
  const width = viewport.clientWidth
  const height = viewport.clientHeight
  const menuWidth = 220
  const menuHeight = 112
  return {
    x: Math.max(12, Math.min(x, width - menuWidth - 12)),
    y: Math.max(12, Math.min(y, height - menuHeight - 12)),
  }
}

function openMapContextMenu(event) {
  if (!mapInstance.value || !mapViewportRef.value) {
    return
  }
  const viewportRect = mapViewportRef.value.getBoundingClientRect()
  const point = [event.point?.x || 0, event.point?.y || 0]
  const lngLat = event.lngLat
  if (!lngLat) {
    return
  }
  const clamped = clampContextMenuPosition(
    point[0],
    point[1],
  )
  mapContextMenu.value = {
    open: true,
    x: clamped.x,
    y: clamped.y,
    lat: Number(lngLat.lat),
    lon: Number(lngLat.lng),
    viewportLeft: viewportRect.left,
    viewportTop: viewportRect.top,
  }
}

function applyRepeaterGeoFromContextMenu() {
  if (!mapContextMenu.value.open) {
    return
  }
  emit('pick', {
    lat: Number(mapContextMenu.value.lat),
    lon: Number(mapContextMenu.value.lon),
  })
  closeMapContextMenu()
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
  const points = markerPoints()
  const anchorPoint = points[0] || {
    lat: 0,
    lon: 0,
  }
  const instance = new window.maplibregl.Map({
    container: mapViewportRef.value,
    style: OPENFREEMAP_STYLE_URL,
    center: [Number(anchorPoint.lon), Number(anchorPoint.lat)],
    zoom: points.length ? 8 : 2,
    attributionControl: false,
  })
  mapInstance.value = instance
  instance.addControl(new window.maplibregl.NavigationControl(), 'top-right')
  instance.on('load', () => {
    syncMarkers()
    fitMapToPoints()
  })
  instance.on('contextmenu', openMapContextMenu)
  instance.on('click', closeMapContextMenu)
  instance.on('dragstart', closeMapContextMenu)
  instance.on('zoomstart', closeMapContextMenu)
  await nextTick()
  instance.resize()
  syncMarkers()
  fitMapToPoints()
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
})

onBeforeUnmount(() => {
  destroyMap()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="model.open" class="mc-overlay mc-overlay--soft" @click="emit('close')">
      <section class="mc-contact-route-sheet mc-contact-route-sheet--geo" @click.stop>
        <div class="mc-contact-route-head">
          <div>
            <h2>{{ t('contactsView.repeater.geoSheet.title') }}</h2>
            <p>{{ t('contactsView.repeater.geoSheet.subtitle', { target: model.targetTitle || t('messages.fallback.unnamedContact') }) }}</p>
          </div>
          <button class="mc-map-route-close" type="button" @click="emit('close')">×</button>
        </div>

        <div class="mc-contact-route-map mc-contact-route-map--geo">
          <div ref="mapViewportRef" class="mc-contact-route-map-viewport" />
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
              <button
                class="mc-map-action-button mc-map-context-action"
                type="button"
                @click="applyRepeaterGeoFromContextMenu"
              >
                {{ t('contactsView.repeater.geoSheet.contextAction') }}
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </Teleport>
</template>
