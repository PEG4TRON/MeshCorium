let frontendDiagnosticsEnabled = true

function currentLocationContext() {
  if (typeof window === 'undefined') {
    return {
      routePath: '',
      routeSearch: '',
      routeHash: '',
    }
  }
  return {
    routePath: String(window.location.pathname || ''),
    routeSearch: String(window.location.search || ''),
    routeHash: String(window.location.hash || ''),
  }
}

export function setFrontendDiagnosticsEnabled(value) {
  frontendDiagnosticsEnabled = Boolean(value)
}

export function isFrontendDiagnosticsEnabled() {
  return frontendDiagnosticsEnabled
}

export function logFrontendDiagnostic(kind, payload = {}) {
  const context = {
    kind: String(kind || '').trim() || 'unknown',
    timestamp: new Date().toISOString(),
    ...currentLocationContext(),
    ...(payload && typeof payload === 'object' ? payload : {}),
  }

  console.error(`[meshcorium] ${context.kind}`, context)

  if (typeof window === 'undefined' || !isFrontendDiagnosticsEnabled()) {
    return context
  }

  const body = JSON.stringify(context)
  fetch('/api/frontend-diagnostic', {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
    },
    body,
    keepalive: true,
  }).catch(() => {})

  return context
}
