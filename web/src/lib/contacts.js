export function normalizePublicKey(value) {
  return String(value || '').trim().toLowerCase()
}

export function getContactPrefix(contactOrKey) {
  const raw = typeof contactOrKey === 'string'
    ? contactOrKey
    : (contactOrKey?.pubkey_prefix || contactOrKey?.public_key || '')
  return normalizePublicKey(raw).slice(0, 12)
}

export function classifyContactKind(contact) {
  const advType = Number(contact?.adv_type || 0)
  if (advType === 2) {
    return 'repeater'
  }
  if (advType === 3) {
    return 'room'
  }
  if (advType === 4) {
    return 'sensor'
  }
  return 'user'
}

export function contactCanDirect(contact) {
  return classifyContactKind(contact) !== 'repeater'
}

export function contactCanManageRepeater(contact) {
  const kind = classifyContactKind(contact)
  return kind === 'repeater' || kind === 'room'
}

export function contactDisplayName(contact, fallback = 'Unknown') {
  return String(
    contact?.adv_name
    || contact?.name
    || getContactPrefix(contact)
    || contact?.public_key
    || fallback,
  ).trim() || fallback
}

export function firstEmojiInText(value) {
  const text = String(value || '').trim()
  if (!text) {
    return ''
  }
  const match = text.match(/(\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?(?:\u200D\p{Extended_Pictographic}(?:\uFE0F|\uFE0E)?)*)/u)
  return match ? match[1] : ''
}

export function contactAvatarEmoji(contact, fallback = 'Unknown') {
  return firstEmojiInText(contactDisplayName(contact, fallback))
}

export function contactAvatarText(contact, fallback = 'Unknown') {
  const emoji = contactAvatarEmoji(contact, fallback)
  if (emoji) {
    return emoji
  }
  return contactDisplayName(contact, fallback).slice(0, 2).toUpperCase()
}

export function shortContactPublicKey(contactOrKey) {
  const normalized = typeof contactOrKey === 'string'
    ? normalizePublicKey(contactOrKey)
    : normalizePublicKey(contactOrKey?.pubkey_prefix || contactOrKey?.public_key || '')
  return normalized.slice(0, 4).toUpperCase()
}

export function isContactOnNode(contact) {
  return Boolean(contact?.is_on_node)
}

export function isContactFavorite(contact) {
  return Boolean(contact?.flags?.favorite || contact?.is_favorite)
}

export function contactHasSavedRepeaterAuth(contact) {
  return Boolean(contact?.backend?.repeater_auth_saved || contact?.repeater_auth_saved)
}

export function contactResidencyLabel(contact, labels = {}) {
  return isContactOnNode(contact)
    ? (labels.onNode || 'В ноде')
    : (labels.dbOnly || 'Только БД')
}

export function contactHasCoordinates(contact) {
  const lat = Number(contact?.lat)
  const lon = Number(contact?.lon)
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return false
  }
  if (!lat && !lon) {
    return false
  }
  return lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180
}
