function formatDurationCompact(seconds, locale = 'ru') {
  const totalSeconds = Math.max(0, Math.ceil(Number(seconds || 0)))
  if (totalSeconds <= 0) {
    return locale === 'en' ? '0s' : '0с'
  }
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const secs = totalSeconds % 60
  const parts = []
  if (hours > 0) {
    parts.push(locale === 'en' ? `${hours}h` : `${hours}ч`)
  }
  if (minutes > 0) {
    parts.push(locale === 'en' ? `${minutes}m` : `${minutes}м`)
  }
  if (secs > 0 || !parts.length) {
    parts.push(locale === 'en' ? `${secs}s` : `${secs}с`)
  }
  return parts.join(' ')
}

export function normalizeStopState(raw) {
  const source = raw && typeof raw === 'object' ? raw : {}
  return {
    port: String(source.port || ''),
    intentional: Boolean(source.intentional),
    stop_reason: String(source.stop_reason || source.stopReason || ''),
    last_stop_kind: String(source.last_stop_kind || source.lastStopKind || ''),
    last_stop_reason: String(source.last_stop_reason || source.lastStopReason || ''),
    last_failure_kind: String(source.last_failure_kind || source.lastFailureKind || ''),
    last_reconnect_reason: String(source.last_reconnect_reason || source.lastReconnectReason || ''),
    reconnect_scheduled_at: Number(source.reconnect_scheduled_at || source.reconnectScheduledAt || 0) || 0,
    reconnect_delay_secs: Number(source.reconnect_delay_secs || source.reconnectDelaySecs || 0) || 0,
    next_reconnect_at: Number(source.next_reconnect_at || source.nextReconnectAt || 0) || 0,
    reconnect_attempts: Number(source.reconnect_attempts || source.reconnectAttempts || 0) || 0,
    last_connected_at: Number(source.last_connected_at || source.lastConnectedAt || 0) || 0,
    last_failure_at: Number(source.last_failure_at || source.lastFailureAt || 0) || 0,
  }
}

export function describeReconnectEta(stopState, { locale = 'ru' } = {}) {
  const nextReconnectAt = Number(stopState?.next_reconnect_at || stopState?.nextReconnectAt || 0) || 0
  const reconnectDelaySecs = Number(stopState?.reconnect_delay_secs || stopState?.reconnectDelaySecs || 0) || 0
  let remainingSecs = 0
  if (nextReconnectAt > 0) {
    remainingSecs = Math.max(0, Math.ceil(nextReconnectAt - (Date.now() / 1000)))
  } else if (reconnectDelaySecs > 0) {
    remainingSecs = Math.max(0, Math.ceil(reconnectDelaySecs))
  }
  if (remainingSecs <= 0) {
    return ''
  }
  return formatDurationCompact(remainingSecs, locale)
}

export function describeRestorePendingStatus(stopState, { t, locale = 'ru' } = {}) {
  const reconnectAttempts = Math.max(0, Number(stopState?.reconnect_attempts || stopState?.reconnectAttempts || 0) || 0)
  if (reconnectAttempts <= 0) {
    return ''
  }
  const eta = describeReconnectEta(stopState, { locale })
  return eta
    ? t('messages.status.restorePendingEta', { attempt: reconnectAttempts, eta })
    : t('messages.status.restorePending', { attempt: reconnectAttempts })
}

export function describeActiveQueueStateSummary(queueState, { t } = {}) {
  const stateValue = queueState && typeof queueState === 'object' ? queueState : null
  if (!stateValue) {
    return ''
  }
  const lastReason = String(stateValue.last_reason || '')
  const cycles = Math.max(0, Number(stateValue.last_drain_cycles || 0) || 0)
  if (stateValue.drain_in_progress) {
    return cycles > 0
      ? t('messages.status.queueDrainInProgressPass', { cycle: cycles })
      : t('messages.status.queueDrainInProgress')
  }
  if (stateValue.drain_requested || lastReason === 'deferred' || lastReason === 'batched-continue' || lastReason === 'interactive-wait') {
    return t('messages.status.queueDrainScheduled')
  }
  return ''
}

export function describeQueueDrainStatus(reason, queueState, { t } = {}) {
  const stateValue = queueState && typeof queueState === 'object' ? queueState : null
  const effectiveReason = String(reason || stateValue?.last_reason || '')
  if (!stateValue || effectiveReason !== 'finished') {
    return ''
  }
  const drained = Math.max(0, Number(stateValue.last_drain_message_count || 0) || 0)
  const cycles = Math.max(0, Number(stateValue.last_drain_cycles || 0) || 0)
  if (drained <= 0) {
    return ''
  }
  return cycles > 1
    ? t('messages.status.queueDrainFinishedBatched', { count: drained, cycles })
    : t('messages.status.queueDrainFinished', { count: drained })
}

export function appendQueueStateStatus(baseLabel, queueState, { t } = {}) {
  const activeSummary = describeActiveQueueStateSummary(queueState, { t })
  if (!activeSummary) {
    return baseLabel
  }
  return baseLabel ? `${baseLabel} ${activeSummary}` : activeSummary
}

export function buildConnectedSessionStatus({ t, targetName, collectionsReady, queueState } = {}) {
  const baseLabel = collectionsReady
    ? t('connect.status.connectedTo', { target: targetName || 'meshcore' })
    : t('messages.status.connectedToHydrating', { target: targetName || 'meshcore' })
  return appendQueueStateStatus(baseLabel, queueState, { t })
}

export function packetTypeLabel(kind, { t } = {}) {
  if (kind === 'direct') {
    return t('messages.packetKinds.directMessage')
  }
  if (kind === 'advert-direct') {
    return t('messages.packetKinds.directAdvert')
  }
  if (kind === 'advert-flood') {
    return t('messages.packetKinds.floodAdvert')
  }
  return t('messages.packetKinds.channelMessage')
}
