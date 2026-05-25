import { computed, ref } from 'vue'

export const UPDATE_CHECK_POLL_MS = 300_000

export function normalizeUpdateCheckPayload(data) {
  const nextVersion = data?.next_version == null ? '' : String(data.next_version)
  return {
    update_available: Boolean(data?.update_available) && Boolean(nextVersion),
    next_version: nextVersion,
  }
}

export function useUpdateCheck(session, options = {}) {
  const intervalMs = Number(options.intervalMs ?? UPDATE_CHECK_POLL_MS)
  const updateCheck = ref(normalizeUpdateCheckPayload(null))
  const updateCheckTimer = ref(0)
  const updateAvailable = computed(() => Boolean(updateCheck.value.update_available))

  async function loadUpdateCheck() {
    try {
      const data = await session.api('/api/update/check')
      updateCheck.value = normalizeUpdateCheckPayload(data)
    } catch {
      // Update banner is non-critical. Keep the last known value.
    }
    return updateCheck.value
  }

  function stopUpdateCheckPolling() {
    if (updateCheckTimer.value && typeof window !== 'undefined') {
      window.clearInterval(updateCheckTimer.value)
    }
    updateCheckTimer.value = 0
  }

  function startUpdateCheckPolling() {
    stopUpdateCheckPolling()
    void loadUpdateCheck()
    if (typeof window !== 'undefined' && intervalMs > 0) {
      updateCheckTimer.value = window.setInterval(loadUpdateCheck, intervalMs)
    }
  }

  return {
    updateCheck,
    updateAvailable,
    loadUpdateCheck,
    startUpdateCheckPolling,
    stopUpdateCheckPolling,
  }
}
