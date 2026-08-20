export const HOME_NODE_GEO_MAX_DISTANCE_KM = 400

export function safeCoordinate(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) {
    return null
  }
  return numeric
}

export function isCoordinatePairValid(lat, lon) {
  return lat != null && lon != null && Math.abs(lat) <= 90 && Math.abs(lon) <= 180
}

export function extractValidGeoPoint(source) {
  const lat = safeCoordinate(source?.lat)
  const lon = safeCoordinate(source?.lon)
  if (!isCoordinatePairValid(lat, lon)) {
    return null
  }
  return { lat, lon }
}

export function geoDistanceKm(from, to) {
  if (!from || !to) {
    return null
  }
  const fromLat = safeCoordinate(from.lat)
  const fromLon = safeCoordinate(from.lon)
  const toLat = safeCoordinate(to.lat)
  const toLon = safeCoordinate(to.lon)
  if (!isCoordinatePairValid(fromLat, fromLon) || !isCoordinatePairValid(toLat, toLon)) {
    return null
  }
  const radians = Math.PI / 180
  const dLat = (toLat - fromLat) * radians
  const dLon = (toLon - fromLon) * radians
  const a = (
    Math.sin(dLat / 2) ** 2
    + Math.cos(fromLat * radians) * Math.cos(toLat * radians) * Math.sin(dLon / 2) ** 2
  )
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
  return 6371 * c
}

export function isGeoWithinHomeDistance(point, homePoint, maxDistanceKm = HOME_NODE_GEO_MAX_DISTANCE_KM) {
  if (!point) {
    return false
  }
  if (!homePoint) {
    return true
  }
  const distanceKm = geoDistanceKm(point, homePoint)
  if (distanceKm == null) {
    return false
  }
  return distanceKm <= Number(maxDistanceKm || HOME_NODE_GEO_MAX_DISTANCE_KM)
}
