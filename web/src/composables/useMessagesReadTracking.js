import { computed, ref } from 'vue'

export function useMessagesReadTracking(options) {
  const {
    session,
    messages,
    currentConversationKey,
    selectedConversationKind,
    selectedContactKey,
    selectedChannelIdx,
    selectedChannelIdentity,
    activeConversationTotalMessages,
    visibleMessageIds,
    messageScroller,
    isMessageScrollerNearBottom,
    scheduleConversationCacheWrite,
    queueUnreadRefresh,
    getOwnerPort,
  } = options

  const pendingMentionReadKeys = ref({})

  const readMarkerMessageId = computed(() => {
    if (!Array.isArray(messages.value) || !messages.value.length) {
      return null
    }
    const firstUnread = messages.value.find((message) => !message?.from_self && !message?.is_read && Number(message?.id || 0) > 0)
    if (firstUnread) {
      return Math.max(0, Number(firstUnread.id || 0) - 1) || null
    }
    let lastReadId = 0
    for (const message of messages.value) {
      const messageId = Number(message?.id || 0)
      if (!messageId) {
        continue
      }
      if (message?.from_self || message?.is_read) {
        lastReadId = Math.max(lastReadId, messageId)
      }
    }
    return lastReadId > 0 ? lastReadId : null
  })

  function setReadMarker(messageId) {
    const conversationKey = currentConversationKey.value
    const nextValue = Number(messageId || 0)
    if (!conversationKey || nextValue <= 0) {
      return
    }
    const currentValue = Number(readMarkerMessageId.value || 0)
    if (currentValue >= nextValue) {
      queueUnreadRefresh()
      return
    }
    let changed = false
    for (const message of messages.value) {
      const messageIdValue = Number(message?.id || 0)
      if (messageIdValue > nextValue) {
        break
      }
      if (messageIdValue > 0 && !message?.is_read) {
        message.is_read = true
        changed = true
      }
    }
    if (changed) {
      scheduleConversationCacheWrite(conversationKey, messages.value, activeConversationTotalMessages.value, 180)
    }
    const conversationKind = selectedConversationKind.value === 'contact' ? 'contact' : 'channel'
    const conversationValue = conversationKind === 'contact'
      ? String(selectedContactKey.value || '').trim().toLowerCase()
      : String(selectedChannelIdx.value)
    void session.api('/api/messages/read-up-to', {
      method: 'POST',
      body: JSON.stringify({
        port: getOwnerPort(),
        conversation_kind: conversationKind,
        conversation_value: conversationValue,
        channel_identity: conversationKind === 'channel' ? String(selectedChannelIdentity?.value || '').trim() : '',
        message_id: nextValue,
      }),
    })
      .then(() => {
        const latestMessageId = Number(messages.value[messages.value.length - 1]?.id || 0)
        if (latestMessageId > 0 && nextValue >= latestMessageId) {
          if (conversationKind === 'contact') {
            const prefix = String(selectedContactKey.value || '').trim().toLowerCase().slice(0, 12)
            if (prefix) {
              session.patchUnreadSummary((summary) => {
                summary.contact_unread_counts = { ...(summary.contact_unread_counts || {}), [prefix]: 0 }
                summary.contact_first_unread_ids = { ...(summary.contact_first_unread_ids || {}), [prefix]: 0 }
                summary.contact_last_unread_ids = { ...(summary.contact_last_unread_ids || {}), [prefix]: 0 }
              })
            }
          } else {
            const channelKey = String(selectedChannelIdentity?.value || '').trim() || String(selectedChannelIdx.value ?? '')
            if (channelKey) {
              session.patchUnreadSummary((summary) => {
                summary.channel_unread_counts = { ...(summary.channel_unread_counts || {}), [channelKey]: 0 }
                summary.channel_first_unread_ids = { ...(summary.channel_first_unread_ids || {}), [channelKey]: 0 }
                summary.channel_last_unread_ids = { ...(summary.channel_last_unread_ids || {}), [channelKey]: 0 }
              })
            }
          }
        }
        queueUnreadRefresh()
      })
      .catch(() => {})
    queueUnreadRefresh()
  }

  function shouldMarkIncomingMessageMentionRead(message) {
    if (!message || message.from_self) {
      return true
    }
    const mentionNeedle = String(session.selfName || '').trim().toLowerCase()
    if (!mentionNeedle) {
      return Boolean(message?.is_mention_read)
    }
    return !String(message?.text || '').toLowerCase().includes(mentionNeedle)
  }

  function markVisibleMessagesRead() {
    if (!messages.value.length) {
      return
    }
    const host = messageScroller.value
    if (!(host instanceof HTMLElement)) {
      return
    }
    if (isMessageScrollerNearBottom(Math.max(40, Math.round(host.clientHeight * 0.04)))) {
      const lastMessageId = Number(messages.value[messages.value.length - 1]?.id || 0)
      if (lastMessageId > 0) {
        setReadMarker(lastMessageId)
      }
    }
    if (!visibleMessageIds.size) {
      return
    }
    let maxVisibleId = 0
    for (const message of messages.value) {
      const messageId = Number(message?.id || 0)
      if (!messageId || !visibleMessageIds.has(messageId)) {
        continue
      }
      if (messageId > maxVisibleId) {
        maxVisibleId = messageId
      }
    }
    if (maxVisibleId > 0) {
      setReadMarker(maxVisibleId)
    }
    const mentionNeedle = String(session.selfName || '').trim().toLowerCase()
    const messageTable = selectedConversationKind.value === 'contact' ? 'contact' : 'channel'
    if (!mentionNeedle || !visibleMessageIds.size) {
      return
    }
    const visibleMentionIds = messages.value
      .filter((message) => (
        !message?.from_self
        && visibleMessageIds.has(Number(message?.id || 0))
        && String(message?.text || '').toLowerCase().includes(mentionNeedle)
      ))
      .map((message) => Number(message?.id || 0))
      .filter((messageId) => messageId > 0)
    if (!visibleMentionIds.length) {
      return
    }
    const pendingIds = visibleMentionIds.filter((messageId) => !pendingMentionReadKeys.value[`${messageTable}:${messageId}`])
    if (!pendingIds.length) {
      return
    }
    for (const messageId of pendingIds) {
      pendingMentionReadKeys.value[`${messageTable}:${messageId}`] = true
    }
    void Promise.all(pendingIds.map((messageId) => session.api('/api/messages/mention-read-state', {
      method: 'POST',
      body: JSON.stringify({
        port: getOwnerPort(),
        message_table: messageTable,
        message_id: messageId,
        is_read: true,
      }),
    })))
      .then(() => {
        queueUnreadRefresh()
      })
      .catch(() => {})
      .finally(() => {
        const nextPending = { ...pendingMentionReadKeys.value }
        for (const messageId of pendingIds) {
          delete nextPending[`${messageTable}:${messageId}`]
        }
        pendingMentionReadKeys.value = nextPending
      })
  }

  return {
    readMarkerMessageId,
    shouldMarkIncomingMessageMentionRead,
    markVisibleMessagesRead,
  }
}
