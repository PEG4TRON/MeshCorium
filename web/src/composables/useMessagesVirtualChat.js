import { computed, ref } from 'vue'

export function useMessagesVirtualChat(options) {
  const {
    messages,
    workspaceMode,
    currentConversation,
    buildRenderedMessage,
    messageRenderKey,
    estimatedMessageHeight,
    overscanPx,
    messageGap,
    onVisibleReadTracking,
  } = options

  const messageScroller = ref(null)
  const messageScrollTop = ref(0)
  const messageViewportHeight = ref(0)
  const messageHeightByKey = ref({})
  const showScrollToBottomButton = ref(false)
  const suppressReadTrackingUntil = ref(0)

  let messageScrollFrameId = 0
  let messageReadTimerId = 0
  let messageVisibilityObserver = null
  let messageResizeObserver = null

  const visibleMessageIds = new Set()
  const messageCardElements = new Map()

  function getMeasuredMessageHeight(message) {
    const key = messageRenderKey(message)
    return Math.max(56, Number(messageHeightByKey.value[key] || 0) || estimatedMessageHeight)
  }

  const virtualMessageWindow = computed(() => {
    const source = Array.isArray(messages.value) ? messages.value : []
    return {
      items: source,
      topPadding: 0,
      bottomPadding: 0,
      totalHeight: 0,
    }
  })

  const visibleRenderedMessages = computed(() => {
    return virtualMessageWindow.value.items
      .filter((message) => Boolean(message) && typeof message === 'object' && !Array.isArray(message))
      .map((message, index, array) => buildRenderedMessage(message, index === array.length - 1))
  })

  function getMessageScrollerBottomGap() {
    const host = messageScroller.value
    if (!host) {
      return Number.POSITIVE_INFINITY
    }
    return Math.max(0, host.scrollHeight - host.scrollTop - host.clientHeight)
  }

  function getMessageScrollerStickThreshold() {
    const host = messageScroller.value
    if (!host) {
      return 48
    }
    return Math.max(96, Math.round(host.clientHeight * 0.12))
  }

  function isMessageScrollerNearBottom(threshold = getMessageScrollerStickThreshold()) {
    return getMessageScrollerBottomGap() <= Math.max(0, Number(threshold) || 0)
  }

  function updateScrollToBottomButtonVisibility() {
    showScrollToBottomButton.value = Boolean(
      workspaceMode.value === 'chat'
      && currentConversation.value
      && messages.value.length
      && !isMessageScrollerNearBottom(),
    )
  }

  function resetVisibleMessageTracking() {
    visibleMessageIds.clear()
  }

  function resetVirtualMessageLayout() {
    messageHeightByKey.value = {}
    messageCardElements.clear()
    resetVisibleMessageTracking()
  }

  function updateMessageScrollerMetrics() {
    const host = messageScroller.value
    if (!(host instanceof HTMLElement)) {
      return
    }
    messageScrollTop.value = host.scrollTop
    messageViewportHeight.value = host.clientHeight
  }

  function setMessageScroller(element) {
    messageScroller.value = element
  }

  function ensureMessageVisibilityObserver() {
    const host = messageScroller.value
    if (!(host instanceof HTMLElement) || typeof IntersectionObserver !== 'function') {
      return
    }
    if (messageVisibilityObserver) {
      messageVisibilityObserver.disconnect()
    }
    messageVisibilityObserver = new IntersectionObserver((entries) => {
      let changed = false
      for (const entry of entries) {
        const messageId = Number(entry.target?.getAttribute?.('data-message-id') || 0)
        if (!messageId) {
          continue
        }
        if (entry.isIntersecting) {
          if (!visibleMessageIds.has(messageId)) {
            visibleMessageIds.add(messageId)
            changed = true
          }
        } else if (visibleMessageIds.delete(messageId)) {
          changed = true
        }
      }
      if (changed) {
        scheduleVisibleReadTracking(40)
      }
    }, {
      root: host,
      threshold: 0.01,
    })
    for (const element of messageCardElements.values()) {
      messageVisibilityObserver.observe(element)
    }
  }

  function ensureMessageResizeObserver() {
    if (messageResizeObserver || typeof ResizeObserver !== 'function') {
      return
    }
    messageResizeObserver = new ResizeObserver((entries) => {
      let changed = false
      for (const entry of entries) {
        const key = String(entry.target?.getAttribute?.('data-message-key') || '').trim()
        if (!key) {
          continue
        }
        const nextHeight = Math.max(56, Math.ceil(entry.contentRect?.height || 0))
        if (!nextHeight || messageHeightByKey.value[key] === nextHeight) {
          continue
        }
        messageHeightByKey.value[key] = nextHeight
        changed = true
      }
      if (changed) {
        scheduleMessageScrollUiRefresh()
      }
    })
  }

  function disconnectMessageResizeObserver() {
    if (messageResizeObserver) {
      messageResizeObserver.disconnect()
      messageResizeObserver = null
    }
  }

  function disconnectMessageVisibilityObserver() {
    if (messageVisibilityObserver) {
      messageVisibilityObserver.disconnect()
      messageVisibilityObserver = null
    }
    resetVisibleMessageTracking()
  }

  function bindMessageCardElement(messageId, messageKey, element) {
    const normalizedId = Number(messageId || 0)
    const normalizedKey = String(messageKey || '').trim()
    if (!normalizedKey) {
      return
    }
    const previous = messageCardElements.get(normalizedKey) || null
    if (previous && previous !== element) {
      messageVisibilityObserver?.unobserve(previous)
      messageResizeObserver?.unobserve(previous)
    }
    if (!(element instanceof HTMLElement)) {
      messageCardElements.delete(normalizedKey)
      visibleMessageIds.delete(normalizedId)
      return
    }
    element.setAttribute('data-message-id', normalizedId > 0 ? String(normalizedId) : '')
    element.setAttribute('data-message-key', normalizedKey)
    messageCardElements.set(normalizedKey, element)
    ensureMessageResizeObserver()
    ensureMessageVisibilityObserver()
    messageResizeObserver?.observe(element)
    messageVisibilityObserver?.observe(element)
  }

  function cancelScheduledMessageScrollWork() {
    if (messageScrollFrameId) {
      window.cancelAnimationFrame(messageScrollFrameId)
      messageScrollFrameId = 0
    }
    if (messageReadTimerId) {
      window.clearTimeout(messageReadTimerId)
      messageReadTimerId = 0
    }
  }

  function scheduleMessageScrollUiRefresh() {
    if (messageScrollFrameId) {
      return
    }
    messageScrollFrameId = window.requestAnimationFrame(() => {
      messageScrollFrameId = 0
      updateScrollToBottomButtonVisibility()
    })
  }

  function runVisibleReadTracking() {
    messageReadTimerId = 0
    const remainingSuppressionMs = Number(suppressReadTrackingUntil.value || 0) - Date.now()
    if (remainingSuppressionMs > 0) {
      scheduleVisibleReadTracking(Math.max(40, remainingSuppressionMs + 20))
      return
    }
    onVisibleReadTracking?.()
  }

  function scheduleVisibleReadTracking(delayMs = 90) {
    if (messageReadTimerId) {
      window.clearTimeout(messageReadTimerId)
    }
    messageReadTimerId = window.setTimeout(runVisibleReadTracking, Math.max(0, Number(delayMs) || 0))
  }

  function estimateMessageOffsetById(messageId) {
    const targetId = Number(messageId || 0)
    if (targetId <= 0) {
      return null
    }
    let offset = 0
    for (let index = 0; index < messages.value.length; index += 1) {
      const message = messages.value[index]
      if (Number(message?.id || 0) === targetId) {
        return offset
      }
      offset += getMeasuredMessageHeight(message)
      if (index < messages.value.length - 1) {
        offset += messageGap
      }
    }
    return null
  }

  function scrollMessageIntoView(messageId, align = 'center') {
    const host = messageScroller.value
    const targetId = Number(messageId || 0)
    if (!(host instanceof HTMLElement) || targetId <= 0) {
      return
    }
    const targetNode = host.querySelector(`[data-message-id="${String(targetId)}"]`)
    if (targetNode instanceof HTMLElement) {
      targetNode.scrollIntoView({ block: align, behavior: 'instant' })
      updateMessageScrollerMetrics()
      return
    }
    const estimatedOffset = estimateMessageOffsetById(targetId)
    if (estimatedOffset == null) {
      return
    }
    const nextTop = align === 'center'
      ? Math.max(0, estimatedOffset - Math.round(host.clientHeight * 0.5))
      : Math.max(0, estimatedOffset)
    host.scrollTop = nextTop
    updateMessageScrollerMetrics()
  }

  function suspendProgrammaticReadTracking(delayMs = 900) {
    suppressReadTrackingUntil.value = Date.now() + Math.max(120, Number(delayMs || 0))
  }

  function scrollMessagesToBottom(behavior = 'auto') {
    const host = messageScroller.value
    if (!host) {
      return
    }
    host.scrollTo({
      top: host.scrollHeight,
      behavior,
    })
  }

  function handleMessageScroll() {
    const host = messageScroller.value
    if (!host) {
      return
    }
    messageScrollTop.value = host.scrollTop
    messageViewportHeight.value = host.clientHeight
    scheduleMessageScrollUiRefresh()
    scheduleVisibleReadTracking()
  }

  function scrollToNewestMessage() {
    suspendProgrammaticReadTracking(520)
    scrollMessagesToBottom('smooth')
    updateMessageScrollerMetrics()
    updateScrollToBottomButtonVisibility()
    scheduleVisibleReadTracking(40)
  }

  return {
    messageScroller,
    messageHeightByKey,
    visibleMessageIds,
    virtualMessageWindow,
    visibleRenderedMessages,
    showScrollToBottomButton,
    getMessageScrollerStickThreshold,
    isMessageScrollerNearBottom,
    updateScrollToBottomButtonVisibility,
    resetVirtualMessageLayout,
    updateMessageScrollerMetrics,
    setMessageScroller,
    ensureMessageVisibilityObserver,
    ensureMessageResizeObserver,
    disconnectMessageResizeObserver,
    disconnectMessageVisibilityObserver,
    bindMessageCardElement,
    cancelScheduledMessageScrollWork,
    scheduleVisibleReadTracking,
    scrollMessageIntoView,
    suspendProgrammaticReadTracking,
    scrollMessagesToBottom,
    handleMessageScroll,
    scrollToNewestMessage,
  }
}
