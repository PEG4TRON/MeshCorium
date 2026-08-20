const WALLPAPER_CACHE_NAME = 'meshcorium-wallpapers-v1'

function originalWallpaperUrl(fileName) {
  return `/wallpappers/${encodeURIComponent(String(fileName || '').trim())}`
}

function detectPhysicalScreenTarget() {
  if (typeof window === 'undefined') {
    return null
  }
  const dpr = Math.max(1, Math.min(4, Number(window.devicePixelRatio || 1) || 1))
  const screenWidth = Math.max(0, Number(window.screen?.width || 0))
  const screenHeight = Math.max(0, Number(window.screen?.height || 0))
  const viewportWidth = Math.max(0, Number(window.innerWidth || 0))
  const viewportHeight = Math.max(0, Number(window.innerHeight || 0))
  const cssWidth = Math.max(screenWidth, viewportWidth, 1)
  const cssHeight = Math.max(screenHeight, viewportHeight, 1)
  return {
    width: Math.max(1, Math.round(cssWidth * dpr)),
    height: Math.max(1, Math.round(cssHeight * dpr)),
    dpr,
  }
}

function wallpaperCacheRequest(fileName, target) {
  return new Request(
    `https://meshcorium.local/__wallpaper-cache__/${encodeURIComponent(fileName)}?w=${target.width}&h=${target.height}&dpr=${target.dpr}`,
    { method: 'GET' },
  )
}

function blobToObjectUrl(blob) {
  const url = URL.createObjectURL(blob)
  return {
    url,
    revoke() {
      URL.revokeObjectURL(url)
    },
  }
}

function loadImageElement(url) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.decoding = 'async'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('wallpaper image failed to load'))
    image.src = url
  })
}

async function renderResizedWallpaperBlob(sourceBlob, target) {
  const bitmap = typeof createImageBitmap === 'function' ? await createImageBitmap(sourceBlob) : null
  const sourceWidth = Math.max(1, Number(bitmap?.width || 0))
  const sourceHeight = Math.max(1, Number(bitmap?.height || 0))
  const objectUrl = bitmap ? null : URL.createObjectURL(sourceBlob)
  const fallbackImage = bitmap ? null : await loadImageElement(objectUrl)
  const canvas = document.createElement('canvas')
  canvas.width = target.width
  canvas.height = target.height
  const context = canvas.getContext('2d', { alpha: false })
  if (!context) {
    throw new Error('wallpaper canvas context unavailable')
  }
  context.imageSmoothingEnabled = true
  context.imageSmoothingQuality = 'high'
  const drawSource = bitmap || fallbackImage
  const drawWidth = Math.max(1, bitmap ? sourceWidth : Number(fallbackImage?.naturalWidth || 0))
  const drawHeight = Math.max(1, bitmap ? sourceHeight : Number(fallbackImage?.naturalHeight || 0))
  const scale = Math.max(target.width / drawWidth, target.height / drawHeight)
  const scaledWidth = drawWidth * scale
  const scaledHeight = drawHeight * scale
  const offsetX = Math.round((target.width - scaledWidth) / 2)
  const offsetY = Math.round((target.height - scaledHeight) / 2)
  context.drawImage(drawSource, offsetX, offsetY, scaledWidth, scaledHeight)
  const resultBlob = await new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error('wallpaper canvas export failed'))
        return
      }
      resolve(blob)
    }, 'image/webp', 0.9)
  })
  bitmap?.close?.()
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
  }
  return resultBlob
}

export async function resolveCachedWallpaperAsset(fileName) {
  const normalizedName = String(fileName || '').trim()
  const directUrl = originalWallpaperUrl(normalizedName)
  if (
    !normalizedName
    || typeof window === 'undefined'
    || typeof document === 'undefined'
    || typeof caches === 'undefined'
  ) {
    return {
      url: directUrl,
      revoke() {},
    }
  }
  const target = detectPhysicalScreenTarget()
  if (!target) {
    return {
      url: directUrl,
      revoke() {},
    }
  }
  const cache = await caches.open(WALLPAPER_CACHE_NAME)
  const cacheRequest = wallpaperCacheRequest(normalizedName, target)
  const cachedResponse = await cache.match(cacheRequest)
  if (cachedResponse) {
    const cachedBlob = await cachedResponse.blob()
    return blobToObjectUrl(cachedBlob)
  }
  const networkResponse = await fetch(directUrl, { credentials: 'same-origin' })
  if (!networkResponse.ok) {
    throw new Error(`wallpaper fetch failed: HTTP ${networkResponse.status}`)
  }
  const sourceBlob = await networkResponse.blob()
  const resizedBlob = await renderResizedWallpaperBlob(sourceBlob, target)
  await cache.put(cacheRequest, new Response(resizedBlob, {
    headers: {
      'Content-Type': resizedBlob.type || 'image/webp',
      'Cache-Control': 'max-age=31536000',
    },
  }))
  return blobToObjectUrl(resizedBlob)
}
