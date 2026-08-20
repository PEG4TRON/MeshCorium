export function detectNativeShell() {
  if (typeof window === 'undefined') {
    return false
  }

  try {
    if (
      window.MeshcoriumAndroid
      && typeof window.MeshcoriumAndroid.isNativeShell === 'function'
      && window.MeshcoriumAndroid.isNativeShell()
    ) {
      return true
    }
  } catch {
    // Используем User-Agent fallback ниже.
  }

  return /MeshcoriumAndroidWebClient\//i.test(
    String(window.navigator?.userAgent || ''),
  )
}

export function markNativeShellDocument() {
  if (typeof document === 'undefined') {
    return false
  }

  const enabled = detectNativeShell()
  document.documentElement.classList.toggle('mc-native-shell', enabled)
  return enabled
}

export function sendNativeDockState(payload = {}) {
  if (!detectNativeShell()) {
    return
  }

  try {
    window.MeshcoriumAndroid?.updateDockState?.(
      JSON.stringify(payload),
    )
  } catch {
    // Native bridge не должен ломать web-версию.
  }
}

export function installNativeActionBridge(router) {
  if (typeof window === 'undefined') {
    return
  }

  window.__meshcoriumNativeAction = async (rawAction) => {
    const action = String(rawAction || '').trim().toLowerCase()
    const current = router.currentRoute.value

    if (action === 'notifications') {
      const path = current.name === 'connect'
        ? '/messages'
        : current.path

      await router.push({
        path,
        query: {
          ...current.query,
          panel: 'notifications',
        },
      })
      return true
    }

    const routeByAction = {
      messages: '/messages',
      contacts: '/contacts',
      maps: '/maps',
      settings: '/settings',
    }

    const path = routeByAction[action]
    if (!path) {
      return false
    }

    await router.push(path)
    return true
  }
}
