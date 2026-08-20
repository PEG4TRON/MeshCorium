export function normalizeRouteHopToken(token) {
  const normalized = String(token || '').trim().toUpperCase()
  if (!normalized || !/^[0-9A-F]+$/.test(normalized)) {
    return ''
  }
  return normalized
}

export function routeTokensFromInput(value) {
  return String(value || '')
    .split(',')
    .map((token) => token.trim().toUpperCase())
    .filter(Boolean)
}

export function extractMessageRouteHops(message) {
  return String(message?.path_hashes || '')
    .trim()
    .toUpperCase()
    .split(/\s*->\s*/)
    .map((hop) => hop.trim())
    .filter(Boolean)
}

export function buildStoredContactRouteHops(contact) {
  const pathLen = Number(contact?.out_path_len ?? 0)
  const hashLen = Math.max(1, Number(contact?.out_path_hash_len || 1))
  const rawPath = String(contact?.out_path || '').trim().toUpperCase()
  if (!rawPath || pathLen <= 0) {
    return []
  }
  const chunkSize = hashLen * 2
  const hops = []
  for (let index = 0; index < pathLen; index += 1) {
    const chunk = rawPath.slice(index * chunkSize, (index + 1) * chunkSize)
    if (chunk.length !== chunkSize) {
      break
    }
    hops.push(chunk)
  }
  return hops
}

export function buildKnownRoutePublicKeys({
  selfPublicKey = '',
  contacts = [],
  extraPublicKeys = [],
} = {}) {
  const pool = new Set()
  const remember = (value) => {
    const token = normalizeRouteHopToken(value)
    if (token) {
      pool.add(token)
    }
  }
  remember(selfPublicKey)
  for (const contact of contacts || []) {
    remember(contact?.public_key)
  }
  for (const publicKey of extraPublicKeys || []) {
    remember(publicKey)
  }
  return Array.from(pool)
}

export function preferredRouteHopDisplayLength() {
  return 4
}

export function resolvePreferredRouteHopToken(
  hop,
  knownCandidates = [],
  preferredHexLen = preferredRouteHopDisplayLength(),
) {
  const normalized = normalizeRouteHopToken(hop)
  if (!normalized) {
    return ''
  }
  if (normalized.length >= preferredHexLen) {
    return normalized.slice(0, preferredHexLen)
  }
  const expanded = Array.from(knownCandidates || [])
    .map((token) => normalizeRouteHopToken(token))
    .filter((token) => token && token.startsWith(normalized) && token.length >= preferredHexLen)
    .map((token) => token.slice(0, preferredHexLen))
  const unique = Array.from(new Set(expanded))
  if (unique.length === 1) {
    return unique[0]
  }
  return normalized
}

export function buildContactRouteInputFromContact(contact, knownCandidates = []) {
  return buildStoredContactRouteHops(contact)
    .map((hop) => resolvePreferredRouteHopToken(hop, knownCandidates))
    .filter(Boolean)
    .join(', ')
}

export function buildRoutePrefixHexFromPublicKeys(publicKeys, hashLenBytes) {
  const hexLen = Math.max(0, Number(hashLenBytes || 0)) * 2
  if (!hexLen) {
    return ''
  }
  return Array.from(publicKeys || [])
    .map((publicKey) => normalizeRouteHopToken(publicKey).slice(0, hexLen))
    .filter((token) => token.length === hexLen)
    .join('')
    .toLowerCase()
}

export function choosePreferredRouteHashLenBytes(
  publicKeys,
  {
    contacts = [],
    selfPublicKey = '',
  } = {},
) {
  const normalized = Array.from(publicKeys || [])
    .map((publicKey) => normalizeRouteHopToken(publicKey))
    .filter(Boolean)
  if (!normalized.length) {
    return 2
  }
  const candidates = buildKnownRoutePublicKeys({
    selfPublicKey,
    contacts,
    extraPublicKeys: normalized,
  })
  for (const hashLenBytes of [2, 4, 8, 1]) {
    const hexLen = hashLenBytes * 2
    if (!normalized.every((token) => token.length >= hexLen)) {
      continue
    }
    const prefixes = normalized.map((token) => token.slice(0, hexLen))
    const uniqueAcrossKnownContacts = prefixes.every((prefix) => (
      candidates.filter((token) => token.length >= hexLen && token.startsWith(prefix)).length === 1
    ))
    if (uniqueAcrossKnownContacts) {
      return hashLenBytes
    }
  }
  for (const hashLenBytes of [8, 4, 2, 1]) {
    const hexLen = hashLenBytes * 2
    if (normalized.every((token) => token.length >= hexLen)) {
      return hashLenBytes
    }
  }
  return 2
}

export function resolveContactRouteTokens(tokens, repeaterContacts = []) {
  return Array.from(tokens || []).map((token) => {
    const normalized = normalizeRouteHopToken(token)
    const matches = Array.from(repeaterContacts || []).filter((contact) => {
      return normalizeRouteHopToken(contact?.public_key).startsWith(normalized)
    })
    const unique = matches.length === 1 ? matches[0] : null
    return {
      token: normalized,
      matches,
      unique,
    }
  })
}

export function buildContactRoutePayloadFromMessage(message, knownCandidates = []) {
  const hops = extractMessageRouteHops(message)
  if (!hops.length) {
    return null
  }
  const normalized = hops
    .map((hop) => resolvePreferredRouteHopToken(hop, knownCandidates) || normalizeRouteHopToken(hop))
    .filter(Boolean)
  if (!normalized.length) {
    return null
  }
  const hopHexLen = normalized.every((hop) => hop.length >= 4)
    ? 4
    : normalized.every((hop) => hop.length >= 2)
      ? 2
      : 0
  if (!hopHexLen || hopHexLen % 2 !== 0) {
    return null
  }
  if (!normalized.every((hop) => hop.length >= hopHexLen && /^[0-9A-F]+$/.test(hop))) {
    return null
  }
  const hashLen = hopHexLen / 2
  if (hashLen < 1 || hashLen > 4) {
    return null
  }
  const reversed = [...normalized].reverse().map((hop) => hop.slice(0, hopHexLen))
  return {
    route_path_len: reversed.length,
    route_path_hash_len: hashLen,
    route_path_hex: reversed.join('').toLowerCase(),
  }
}
