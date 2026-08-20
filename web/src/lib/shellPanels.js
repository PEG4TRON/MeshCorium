const SUPPORTED_SHELL_PANELS = new Set(['notifications', 'console', 'advert'])

function normalizePanelName(panel) {
  const normalized = String(panel || '').trim()
  return SUPPORTED_SHELL_PANELS.has(normalized) ? normalized : ''
}

function normalizeRouteLocation(route = {}) {
  return {
    path: String(route.path || '/'),
    query: route.query && typeof route.query === 'object' ? { ...route.query } : {},
  }
}

export function getActiveShellPanel(route = {}) {
  return normalizePanelName(route?.query?.panel)
}

export function isShellPanelActive(route = {}, panel = '') {
  const normalized = normalizePanelName(panel)
  return Boolean(normalized) && getActiveShellPanel(route) === normalized
}

export function buildOpenShellPanelLocation(route = {}, panel = '') {
  const normalized = normalizePanelName(panel)
  const location = normalizeRouteLocation(route)
  if (!normalized) {
    delete location.query.panel
    return location
  }
  return {
    path: location.path,
    query: {
      ...location.query,
      panel: normalized,
    },
  }
}

export function buildCloseShellPanelLocation(route = {}) {
  const location = normalizeRouteLocation(route)
  delete location.query.panel
  return location
}

export function buildToggleShellPanelLocation(route = {}, panel = '') {
  const normalized = normalizePanelName(panel)
  if (!normalized || isShellPanelActive(route, normalized)) {
    return buildCloseShellPanelLocation(route)
  }
  return buildOpenShellPanelLocation(route, normalized)
}
