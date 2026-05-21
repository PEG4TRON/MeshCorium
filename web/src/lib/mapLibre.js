let mapLibreLoadPromise = null

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
