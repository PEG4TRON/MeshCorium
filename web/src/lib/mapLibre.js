let mapLibreLoadPromise = null

export const MAP_PROVIDER_OSM_RASTER = 'osm_raster'
export const MAP_PROVIDER_OFM_LIBERTY = 'ofm_liberty'
export const MAP_PROVIDER_DEFAULT = MAP_PROVIDER_OSM_RASTER
export const MAP_PROVIDER_OPTIONS = [
  { value: MAP_PROVIDER_OSM_RASTER, label: 'OSM Raster', triggerLabel: 'OSM Raster' },
  { value: MAP_PROVIDER_OFM_LIBERTY, label: 'OFM Liberty', triggerLabel: 'OFM Liberty' },
]

export const OPENFREEMAP_STYLE_ORIGIN = 'https://tiles.openfreemap.org/styles/liberty'
export const OPENFREEMAP_STYLE_URL = `/api/tiles/proxy?url=${encodeURIComponent(OPENFREEMAP_STYLE_ORIGIN)}`
export function createOsmRasterStyle() {
  return {
    version: 8,
    sources: {
      osm: {
        type: 'raster',
        tiles: [
          'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        ],
        tileSize: 256,
        attribution: '© OpenStreetMap contributors',
      },
    },
    layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
  }
}

export const OSM_RASTER_STYLE = createOsmRasterStyle()
export const MAP_STYLE_BOOT_TIMEOUT_MS = 6000

const TILE_PROXY_ORIGINS = ['tiles.openfreemap.org', 'tile.openstreetmap.org']

export function tileTransformRequest(url) {
  if (url.startsWith('/api/tiles/proxy') || url.includes('/api/tiles/proxy?')) {
    return { url }
  }
  if (TILE_PROXY_ORIGINS.some((origin) => url.includes(origin))) {
    return { url: `/api/tiles/proxy?url=${encodeURIComponent(url)}` }
  }
  return { url }
}

export function normalizeMapProvider(value) {
  const provider = String(value || '').trim().toLowerCase()
  return provider === MAP_PROVIDER_OFM_LIBERTY ? MAP_PROVIDER_OFM_LIBERTY : MAP_PROVIDER_DEFAULT
}

export function buildSelectedMapStyle(provider = MAP_PROVIDER_DEFAULT) {
  return normalizeMapProvider(provider) === MAP_PROVIDER_OFM_LIBERTY
    ? OPENFREEMAP_STYLE_URL
    : createOsmRasterStyle()
}

export function buildFallbackMapStyle() {
  return createOsmRasterStyle()
}

export function shouldFallbackToRasterMapStyle(event, mapReady = false) {
  const sourceId = String(event?.sourceId || event?.source?.id || '').trim()
  const errorMessage = String(event?.error?.message || event?.message || '').trim()
  return Boolean(sourceId || errorMessage) || !mapReady
}

function ensureMapLibreCss() {
  if (typeof document === 'undefined') {
    return
  }
  if (document.querySelector('link[data-maplibre-css="1"]')) {
    return
  }
  const css = document.createElement('link')
  css.rel = 'stylesheet'
  css.href = '/vendor/maplibre/maplibre-gl.css'
  css.dataset.maplibreCss = '1'
  document.head.appendChild(css)
}

export async function ensureMapLibreLoaded() {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return false
  }
  if (window.maplibregl) {
    return true
  }
  if (mapLibreLoadPromise) {
    return mapLibreLoadPromise
  }
  mapLibreLoadPromise = new Promise((resolve, reject) => {
    ensureMapLibreCss()
    const existing = document.querySelector('script[data-maplibre-js="1"]')
    if (existing) {
      if (window.maplibregl) {
        resolve(true)
        return
      }
      existing.addEventListener('load', () => resolve(true), { once: true })
      existing.addEventListener('error', () => reject(new Error('MapLibre GL JS failed to load.')), { once: true })
      return
    }
    const script = document.createElement('script')
    script.src = '/vendor/maplibre/maplibre-gl.js'
    script.async = true
    script.dataset.maplibreJs = '1'
    script.onload = () => resolve(true)
    script.onerror = () => reject(new Error('MapLibre GL JS failed to load.'))
    document.head.appendChild(script)
  }).finally(() => {
    if (!window.maplibregl) {
      mapLibreLoadPromise = null
    }
  })
  return mapLibreLoadPromise
}
