<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useTitle } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { setFrontendDiagnosticsEnabled } from './lib/frontendDiagnostics'
import { resolveCachedWallpaperAsset } from './lib/wallpaperCache'
import { useSessionStore } from './stores/session'

const route = useRoute()
const session = useSessionStore()
const { t } = useI18n()
const unreadTitleBadge = computed(() => Math.max(0, Number(session.browserUnreadBadgeCount || 0)))
const pageTitle = computed(() => {
  const titleKey = String(route.meta?.titleKey || '').trim()
  const routeTitle = titleKey ? String(t(titleKey)).trim() : String(route.meta?.title || '').trim()
  const baseTitle = routeTitle ? `${routeTitle} | Meshcorium` : 'Meshcorium'
  return unreadTitleBadge.value > 0 ? `(${unreadTitleBadge.value > 99 ? '99+' : unreadTitleBadge.value}) ${baseTitle}` : baseTitle
})

useTitle(pageTitle)

const resolvedWallpaperUrl = ref('')
let releaseWallpaperUrl = null

function releaseResolvedWallpaperUrl() {
  if (typeof releaseWallpaperUrl === 'function') {
    releaseWallpaperUrl()
    releaseWallpaperUrl = null
  }
  resolvedWallpaperUrl.value = ''
}

const backgroundSettings = computed(() => {
  const settings = session.settingsPayload?.settings || {}
  return {
    backgroundId: String(settings.page_background_id || 'default').trim() || 'default',
    blurEnabled: Boolean(settings.page_background_blur_enabled),
    blurPx: Math.max(0, Math.min(32, Number(settings.page_background_blur_px || 0) || 0)),
  }
})

function resolvePageBackgroundModel() {
  const { backgroundId, blurEnabled, blurPx } = backgroundSettings.value
  if (backgroundId === 'aurora') {
    return {
      image: [
        'radial-gradient(circle at 18% 20%, rgba(90, 180, 255, 0.32), transparent 28%)',
        'radial-gradient(circle at 78% 22%, rgba(104, 214, 173, 0.22), transparent 26%)',
        'radial-gradient(circle at 52% 78%, rgba(255, 196, 92, 0.12), transparent 22%)',
        'linear-gradient(180deg, #10202f 0%, #0b141d 100%)',
      ].join(', '),
      size: 'cover',
      position: 'center',
      filter: blurEnabled ? `blur(${blurPx}px)` : 'none',
    }
  }
  if (backgroundId === 'grid') {
    return {
      image: [
        'linear-gradient(rgba(82, 142, 196, 0.09) 1px, transparent 1px)',
        'linear-gradient(90deg, rgba(82, 142, 196, 0.09) 1px, transparent 1px)',
        'radial-gradient(circle at center, rgba(48, 92, 136, 0.18), transparent 56%)',
        'linear-gradient(180deg, #0f1c28 0%, #09111a 100%)',
      ].join(', '),
      size: '36px 36px, 36px 36px, cover, cover',
      position: 'center',
      filter: blurEnabled ? `blur(${blurPx}px)` : 'none',
    }
  }
  if (backgroundId.startsWith('wallpaper:')) {
    const wallpaperName = backgroundId.slice('wallpaper:'.length).trim()
    if (wallpaperName && resolvedWallpaperUrl.value) {
      return {
        image: [
          'linear-gradient(180deg, rgba(8, 14, 20, 0.24), rgba(8, 14, 20, 0.42))',
          `url("${resolvedWallpaperUrl.value}")`,
        ].join(', '),
        size: 'cover, cover',
        position: 'center',
        filter: blurEnabled ? `blur(${blurPx}px)` : 'none',
      }
    }
  }
  return {
    image: [
      'radial-gradient(circle at 12% 10%, rgba(50, 138, 221, 0.14), transparent 28%)',
      'radial-gradient(circle at 88% 90%, rgba(79, 188, 159, 0.08), transparent 26%)',
      'linear-gradient(180deg, #10202f 0%, #0d1923 100%)',
    ].join(', '),
    size: 'cover',
    position: 'center',
    filter: blurEnabled ? `blur(${blurPx}px)` : 'none',
  }
}

watch(
  () => backgroundSettings.value.backgroundId,
  async (backgroundId, _previous, onCleanup) => {
    let cancelled = false
    onCleanup(() => {
      cancelled = true
    })
    releaseResolvedWallpaperUrl()
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
      resolvedWallpaperUrl.value = asset.url
      releaseWallpaperUrl = asset.revoke
    } catch (error) {
      console.error('[meshcorium] wallpaper-cache', {
        message: error instanceof Error ? error.message : String(error || 'unknown'),
        wallpaperName,
      })
      if (!cancelled) {
        resolvedWallpaperUrl.value = `/wallpappers/${encodeURIComponent(wallpaperName)}`
      }
    }
  },
  { immediate: true },
)

watch([backgroundSettings, resolvedWallpaperUrl], () => {
  if (typeof document === 'undefined') {
    return
  }
  const model = resolvePageBackgroundModel()
  const root = document.documentElement
  root.style.setProperty('--mc-page-backdrop-image', model.image)
  root.style.setProperty('--mc-page-backdrop-size', model.size)
  root.style.setProperty('--mc-page-backdrop-position', model.position)
  root.style.setProperty('--mc-page-backdrop-filter', model.filter)
}, { immediate: true, deep: true })

watch(
  () => session.settingsPayload?.settings?.frontend_diagnostics_enabled,
  (enabled) => {
    if (enabled == null) {
      return
    }
    setFrontendDiagnosticsEnabled(Boolean(enabled))
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  releaseResolvedWallpaperUrl()
})
</script>

<template>
  <RouterView />
</template>
