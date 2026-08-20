export const DEFAULT_WIFI_PORT = 5000

export function normalizeWifiHost(value) {
  const next = String(value || '').trim()
  if (!next) {
    return ''
  }
  if (next.startsWith('tcp://')) {
    return next.slice('tcp://'.length).trim()
  }
  return next
}

export function parseWifiEndpoint(value) {
  const raw = normalizeWifiHost(value)
  if (!raw) {
    return { host: '', port: String(DEFAULT_WIFI_PORT) }
  }
  if (raw.startsWith('[') && raw.includes(']')) {
    const end = raw.indexOf(']')
    const host = raw.slice(1, end).trim()
    const remainder = raw.slice(end + 1).trim()
    if (remainder.startsWith(':')) {
      return { host, port: remainder.slice(1).trim() || String(DEFAULT_WIFI_PORT) }
    }
    return { host, port: String(DEFAULT_WIFI_PORT) }
  }
  if (raw.includes(':') && raw.indexOf(':') === raw.lastIndexOf(':')) {
    const [hostPart, portPart] = raw.split(':')
    return {
      host: hostPart.trim(),
      port: portPart.trim() || String(DEFAULT_WIFI_PORT),
    }
  }
  return { host: raw, port: String(DEFAULT_WIFI_PORT) }
}

export function normalizeWifiPort(value, fallback = String(DEFAULT_WIFI_PORT)) {
  const text = String(value ?? '').trim()
  if (!text) {
    return String(fallback || DEFAULT_WIFI_PORT)
  }
  if (!/^\d+$/.test(text)) {
    return text
  }
  const numeric = Number(text)
  if (!Number.isInteger(numeric) || numeric < 1 || numeric > 65535) {
    return text
  }
  return String(numeric)
}

export function buildWifiTransportId(host, port) {
  const normalizedHost = normalizeWifiHost(host).replace(/^\[(.*)\]$/, '$1').trim()
  if (!normalizedHost) {
    return ''
  }
  const normalizedPort = normalizeWifiPort(port, '')
  if (!/^\d+$/.test(normalizedPort)) {
    return normalizedHost
  }
  const hostLabel = normalizedHost.includes(':') ? `[${normalizedHost}]` : normalizedHost
  return `${hostLabel}:${normalizedPort}`
}

