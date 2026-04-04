import { computed, ref } from 'vue'

export function useMessagesConversationList(options) {
  const {
    session,
    locale,
    t,
    unreadSummary,
    selectedConversationKind,
    selectedChannelIdx,
    selectedContactKey,
    chatEditMode,
    estimatedRowHeight,
    overscanPx,
    helpers,
  } = options

  const conversationListScroller = ref(null)
  const conversationListScrollTop = ref(0)
  const conversationListViewportHeight = ref(0)
  const conversationRowHeightByKey = ref({})
  const conversationRowElements = new Map()
  let conversationRowResizeObserver = null

  const directConversationRows = computed(() => {
    return session.contacts
      .filter((contact) => Number(contact?.last_message_at || 0) > 0)
      .map((contact) => {
        const prefix = helpers.getContactPrefix(contact)
        const displayName = helpers.contactDisplayName(contact)
        const avatarEmoji = helpers.contactAvatarEmoji(contact)
        return {
          kind: 'contact',
          contact,
          prefix,
          displayName,
          preview: helpers.formatContactPreview(contact),
          avatarText: avatarEmoji || (displayName || '?').slice(0, 2).toUpperCase(),
          avatarSymbol: avatarEmoji || '👤',
          avatarIsEmoji: Boolean(avatarEmoji),
          kindLabel: t(`messages.contactKinds.${helpers.contactKindLabel(contact)}`),
          contactBadge: helpers.contactKindBadgeLabel(contact),
          rawUnreadCount: Number(unreadSummary.value.contact_unread_counts[prefix] || 0),
          rawMentionCount: Number(unreadSummary.value.contact_mention_counts[prefix] || 0),
          unreadCount: helpers.displayedContactUnreadCount(contact),
          mentionCount: helpers.displayedContactMentionCount(contact),
          value: helpers.normalizePublicKey(contact?.public_key),
        }
      })
      .sort((left, right) => {
        if (left.rawUnreadCount !== right.rawUnreadCount) {
          return right.rawUnreadCount - left.rawUnreadCount
        }
        const leftTs = Number(left.contact?.last_message_at || 0)
        const rightTs = Number(right.contact?.last_message_at || 0)
        if (leftTs !== rightTs) {
          return rightTs - leftTs
        }
        return left.displayName.localeCompare(right.displayName, locale.value === 'en' ? 'en' : 'ru')
      })
  })

  const channelScrollerRows = computed(() => {
    return session.channels.map((channel) => {
      const muteMode = helpers.getConversationMuteModeForEntry({ kind: 'channel', channel })
      const isProtectedChannel = helpers.isProtectedPublicChannel(channel)
      return {
        kind: 'channel',
        channel,
        channelKey: String(channel?.idx || ''),
        title: channel?.name || '',
        meta: helpers.isPublicChannel(channel) ? t('messages.visibility.public') : t('messages.visibility.private'),
        preview: helpers.formatChannelPreview(channel),
        avatarText: helpers.channelAvatarSymbol(channel),
        avatarSymbol: helpers.isOfficialPublicChannelName(channel?.name) ? '📣' : '#',
        unreadCount: helpers.displayedChannelUnreadCount(channel),
        mentionCount: helpers.displayedChannelMentionCount(channel),
        rawUnreadCount: Number(unreadSummary.value.channel_unread_counts[String(channel?.idx || '')] || 0),
        rawMentionCount: Number(unreadSummary.value.channel_mention_counts[String(channel?.idx || '')] || 0),
        muteMode,
        muteLabel: muteMode !== 'none' ? helpers.conversationMuteIndicatorLabel(muteMode) : '',
        isProtectedChannel,
        editLabel: isProtectedChannel ? t('messages.editor.status.publicReadOnly') : t('messages.editor.actions.editChannel'),
        value: Number(channel?.idx),
      }
    })
  })

  const scrollerEntryModels = computed(() => {
    const channelRows = channelScrollerRows.value.map((row) => ({
      ...row,
      key: `channel:${Number(row.channel?.idx)}`,
      selected: selectedConversationKind.value === 'channel' && Number(row.channel?.idx) === Number(selectedChannelIdx.value),
    }))
    const contactRows = directConversationRows.value.map((row) => ({
      ...row,
      key: `contact:${row.value}`,
      selected: selectedConversationKind.value === 'contact' && row.value === helpers.normalizePublicKey(selectedContactKey.value),
    }))
    return [...channelRows, ...contactRows]
  })

  const conversationHasEntries = computed(() => {
    return scrollerEntryModels.value.length > 0
  })

  const conversationListItems = computed(() => {
    const items = [...scrollerEntryModels.value]
    if (chatEditMode.value && session.connected) {
      items.push({
        kind: 'add-channel',
        key: 'add-channel',
      })
    }
    return items
  })

  function getMeasuredConversationRowHeight(entry) {
    return Math.max(56, Number(conversationRowHeightByKey.value[String(entry?.key || '')] || 0) || estimatedRowHeight)
  }

  const visibleConversationListWindow = computed(() => {
    const items = conversationListItems.value
    return {
      items,
      topPadding: 0,
      bottomPadding: 0,
    }
  })

  function updateConversationListMetrics() {
    const host = conversationListScroller.value
    if (!(host instanceof HTMLElement)) {
      return
    }
    conversationListScrollTop.value = host.scrollTop
    conversationListViewportHeight.value = host.clientHeight
  }

  function setConversationListScroller(element) {
    conversationListScroller.value = element
  }

  function ensureConversationRowResizeObserver() {
    if (conversationRowResizeObserver || typeof ResizeObserver !== 'function') {
      return
    }
    conversationRowResizeObserver = new ResizeObserver((entries) => {
      let changed = false
      for (const entry of entries) {
        const key = String(entry.target?.getAttribute?.('data-conversation-key') || '').trim()
        if (!key) {
          continue
        }
        const nextHeight = Math.max(56, Math.ceil(entry.contentRect?.height || 0))
        if (!nextHeight || conversationRowHeightByKey.value[key] === nextHeight) {
          continue
        }
        conversationRowHeightByKey.value[key] = nextHeight
        changed = true
      }
      if (changed) {
        updateConversationListMetrics()
      }
    })
  }

  function disconnectConversationRowResizeObserver() {
    if (conversationRowResizeObserver) {
      conversationRowResizeObserver.disconnect()
      conversationRowResizeObserver = null
    }
  }

  function bindConversationRowElement(entryKey, element) {
    const normalizedKey = String(entryKey || '').trim()
    if (!normalizedKey) {
      return
    }
    const previous = conversationRowElements.get(normalizedKey) || null
    if (previous && previous !== element) {
      conversationRowResizeObserver?.unobserve(previous)
    }
    if (!(element instanceof HTMLElement)) {
      conversationRowElements.delete(normalizedKey)
      return
    }
    element.setAttribute('data-conversation-key', normalizedKey)
    conversationRowElements.set(normalizedKey, element)
    ensureConversationRowResizeObserver()
    conversationRowResizeObserver?.observe(element)
  }

  return {
    directConversationRows,
    channelScrollerRows,
    scrollerEntryModels,
    conversationHasEntries,
    conversationListItems,
    visibleConversationListWindow,
    updateConversationListMetrics,
    setConversationListScroller,
    ensureConversationRowResizeObserver,
    disconnectConversationRowResizeObserver,
    bindConversationRowElement,
  }
}
