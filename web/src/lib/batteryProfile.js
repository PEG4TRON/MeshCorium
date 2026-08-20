const DEFAULT_CHEMISTRY = 'nmc'
const MIN_CUSTOM_MV = 1000
const MAX_CUSTOM_MV = 6000

const PRESET_RANGES = {
  nmc: { min_mv: 3000, max_mv: 4200 },
  lipo: { min_mv: 3000, max_mv: 4200 },
  lifepo4: { min_mv: 2600, max_mv: 3650 },
}

export function normalizeBatteryChemistry(value) {
  const normalized = String(value || '').trim().toLowerCase()
  return normalized === 'lifepo4' || normalized === 'lipo' ? normalized : DEFAULT_CHEMISTRY
}

export function batteryVoltageRangeForChemistry(chemistry) {
  const normalized = normalizeBatteryChemistry(chemistry)
  return { ...PRESET_RANGES[normalized] }
}

function normalizeBatteryMillivolts(value, fallback) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) {
    return fallback
  }
  return Math.max(MIN_CUSTOM_MV, Math.min(MAX_CUSTOM_MV, Math.round(numeric)))
}

export function normalizeBatteryProfile(profile) {
  const chemistry = normalizeBatteryChemistry(profile?.chemistry)
  const presetRange = batteryVoltageRangeForChemistry(chemistry)
  const mode = String(profile?.mode || '').trim().toLowerCase() === 'custom' ? 'custom' : 'preset'
  if (mode !== 'custom') {
    return {
      mode: 'preset',
      chemistry,
      min_mv: presetRange.min_mv,
      max_mv: presetRange.max_mv,
    }
  }
  let minMv = normalizeBatteryMillivolts(profile?.min_mv, presetRange.min_mv)
  let maxMv = normalizeBatteryMillivolts(profile?.max_mv, presetRange.max_mv)
  if (minMv >= maxMv) {
    minMv = presetRange.min_mv
    maxMv = presetRange.max_mv
  }
  return {
    mode: 'custom',
    chemistry,
    min_mv: minMv,
    max_mv: maxMv,
  }
}

export function normalizeBatteryProfileMap(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {}
  }
  const result = {}
  for (const [rawNodeId, rawProfile] of Object.entries(value)) {
    const nodeId = String(rawNodeId || '').trim().toLowerCase()
    if (!/^[0-9a-f]{64}$/.test(nodeId)) {
      continue
    }
    result[nodeId] = normalizeBatteryProfile(rawProfile)
  }
  return result
}

export function batteryProfileForNode(settings, nodeId) {
  const normalizedNodeId = String(nodeId || '').trim().toLowerCase()
  const profiles = normalizeBatteryProfileMap(settings?.battery_profile_by_node_id)
  return normalizeBatteryProfile(profiles[normalizedNodeId] || null)
}

export function estimateBatteryPercentFromMillivolts(millivolts, profile) {
  if (millivolts == null || Number.isNaN(Number(millivolts))) {
    return null
  }
  const numeric = Math.round(Number(millivolts))
  const normalizedProfile = normalizeBatteryProfile(profile)
  const minMv = normalizedProfile.min_mv
  const maxMv = normalizedProfile.max_mv
  if (numeric <= minMv) {
    return 0
  }
  if (numeric >= maxMv) {
    return 100
  }
  return Math.round(((numeric - minMv) * 100) / (maxMv - minMv))
}

export function resolveDisplayedBatteryPercent({ telemetry, batteryInfo, profile }) {
  const infoBatteryMv = batteryInfo?.battery_mv == null ? null : Number(batteryInfo.battery_mv)
  if (infoBatteryMv != null && Number.isFinite(infoBatteryMv)) {
    return estimateBatteryPercentFromMillivolts(infoBatteryMv, profile)
  }
  const telemetryBatteryMv = telemetry?.battery_mv == null ? null : Number(telemetry.battery_mv)
  if (telemetryBatteryMv != null && Number.isFinite(telemetryBatteryMv)) {
    return estimateBatteryPercentFromMillivolts(telemetryBatteryMv, profile)
  }
  if (telemetry?.battery_percent != null) {
    return Math.max(0, Math.min(100, Number(telemetry.battery_percent)))
  }
  if (batteryInfo?.battery_percent != null) {
    return Math.max(0, Math.min(100, Number(batteryInfo.battery_percent)))
  }
  return null
}
