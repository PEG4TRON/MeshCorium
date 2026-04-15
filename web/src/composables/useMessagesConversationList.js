import { computed, nextTick, ref } from 'vue'

export function useMessagesConversationList(options) {
  const {
    session,
    channelsSource,
    contactsSource,
    locale,
    t,
    unreadSummary,
    selectedConversationKind,
    selectedChannelIdx,
    selectedChannelIdentity,
    selectedContactKey,
    chatEditMode,
    channelDialogOrder,
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
    return (Array.isArray(contactsSource?.value) ? contactsSource.value : session.contacts)
      .filter((contact) => Number(contact?.last_message_at || 0) > 0)
      .map((contact) => {
        const prefix = helpers.getContactPrefix(contact)
        const displayName = helpers.contactDisplayName(contact)
        const avatarEmoji = helpers.contactAvatarEmoji(contact)
        return {
          kind: 'contact',
          contact,
          conversationKey: helpers.getContactMuteKey(contact),
          prefix,
          displayName,
          preview: helpers.formatContactPreview(contact),
          avatarText: avatarEmoji || (displayName || '?').slice(0, 2).toUpperCase(),
          avatarSymbol: avatarEmoji || '👤',
          avatarIsEmoji: Boolean(avatarEmoji),
          kindLabel: t(`messages.contactKinds.${helpers.contactKindLabel(contact)}`),
          contactBadge: helpers.contactKindBadgeLabel(contact),
          rawUnreadCount: helpers.resolveContactSummaryCount(
            unreadSummary.value.contact_unread_counts,
            contact,
            contact?.unread_count ?? 0,
          ),
          rawMentionCount: helpers.resolveContactSummaryCount(
            unreadSummary.value.contact_mention_counts,
            contact,
            contact?.mention_count ?? 0,
          ),
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

  const orderedChannelsSource = computed(() => {
    const channels = Array.isArray(channelsSource?.value) ? channelsSource.value : session.channels
    const order = Array.isArray(channelDialogOrder?.value) ? channelDialogOrder.value.map((key) => String(key || '')).filter(Boolean) : []
    if (!order.length) {
      return channels
    }
    const orderIndex = new Map(order.map((key, index) => [key, index]))
    return [...channels].sort((left, right) => {
      const leftKey = helpers.channelDialogOrderKey(left)
      const rightKey = helpers.channelDialogOrderKey(right)
      const leftIndex = orderIndex.has(leftKey) ? orderIndex.get(leftKey) : Number.MAX_SAFE_INTEGER
      const rightIndex = orderIndex.has(rightKey) ? orderIndex.get(rightKey) : Number.MAX_SAFE_INTEGER
      if (leftIndex !== rightIndex) {
        return leftIndex - rightIndex
      }
      return Number(left?.idx ?? 0) - Number(right?.idx ?? 0)
    })
  })

  const channelScrollerRows = computed(() => {
    return orderedChannelsSource.value.map((channel) => {
      const muteMode = helpers.getConversationMuteModeForEntry({ kind: 'channel', channel })
      const isProtectedChannel = helpers.isProtectedPublicChannel(channel)
      const normalizedChannelIdentity = String(channel?.channel_identity ?? '').trim()
      const normalizedChannelIdx = Number(channel?.idx ?? -1)
      return {
        kind: 'channel',
        channel,
        channelKey: helpers.getChannelMuteKey(channel) || normalizedChannelIdentity || (normalizedChannelIdx >= 0 ? String(normalizedChannelIdx) : ''),
        reorderKey: helpers.channelDialogOrderKey(channel),
        title: helpers.displayChannelTitle(channel?.name, normalizedChannelIdx, normalizedChannelIdentity),
        meta: helpers.isPublicChannel(channel) ? t('messages.visibility.public') : t('messages.visibility.private'),
        preview: helpers.formatChannelPreview(channel),
        avatarText: helpers.channelAvatarSymbol(channel),
        avatarSymbol: helpers.channelAvatarSymbol(channel),
        unreadCount: helpers.displayedChannelUnreadCount(channel),
        mentionCount: helpers.displayedChannelMentionCount(channel),
        rawUnreadCount: helpers.resolveChannelSummaryCount(
          unreadSummary.value.channel_unread_counts,
          channel,
          channel?.unread_count ?? 0,
        ),
        rawMentionCount: helpers.resolveChannelSummaryCount(
          unreadSummary.value.channel_mention_counts,
          channel,
          channel?.mention_count ?? 0,
        ),
        muteMode,
        muteLabel: muteMode !== 'none' ? helpers.conversationMuteIndicatorLabel(muteMode) : '',
        isProtectedChannel,
        editLabel: t('messages.editor.actions.editChannel'),
        value: Number(channel?.idx),
      }
    })
  })

  const scrollerEntryModels = computed(() => {
    const channelRows = channelScrollerRows.value.map((row) => ({
      ...row,
      key: `channel:${normalizeConversationRowSuffix(row.channelKey)}`,
      selected: selectedConversationKind.value === 'channel' && (
        (String(row.channel?.channel_identity || '').trim() && String(row.channel?.channel_identity || '').trim() === String(selectedChannelIdentity?.value || '').trim())
        || Number(row.channel?.idx) === Number(selectedChannelIdx.value)
      ),
    }))
    const contactRows = directConversationRows.value.map((row) => ({
      ...row,
      key: `contact:${normalizeConversationRowSuffix(row.conversationKey || row.value)}`,
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

  function getConversationListTotalHeight(items) {
    return items.reduce((sum, entry) => sum + getMeasuredConversationRowHeight(entry), 0)
  }

  const visibleConversationListWindow = computed(() => {
    const items = conversationListItems.value
    const viewportHeight = Math.max(0, Number(conversationListViewportHeight.value || 0))
    if (!items.length || viewportHeight <= 0) {
      return {
        items,
        topPadding: 0,
        bottomPadding: 0,
      }
    }

    const scrollTop = Math.max(0, Number(conversationListScrollTop.value || 0))
    const overscan = Math.max(0, Number(overscanPx || 0))
    const visibleTop = Math.max(0, scrollTop - overscan)
    const visibleBottom = scrollTop + viewportHeight + overscan
    const totalHeight = getConversationListTotalHeight(items)
    let topPadding = 0
    let startIndex = 0

    while (startIndex < items.length) {
      const rowHeight = getMeasuredConversationRowHeight(items[startIndex])
      if (topPadding + rowHeight >= visibleTop) {
        break
      }
      topPadding += rowHeight
      startIndex += 1
    }

    let endIndex = startIndex
    let consumedHeight = topPadding
    while (endIndex < items.length && consumedHeight <= visibleBottom) {
      consumedHeight += getMeasuredConversationRowHeight(items[endIndex])
      endIndex += 1
    }

    if (endIndex < items.length) {
      endIndex += 1
      consumedHeight += getMeasuredConversationRowHeight(items[endIndex - 1])
    }

    return {
      items: items.slice(startIndex, endIndex),
      topPadding,
      bottomPadding: Math.max(0, totalHeight - consumedHeight),
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
    if (element instanceof HTMLElement) {
      nextTick(() => updateConversationListMetrics())
    }
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

  function normalizeConversationRowSuffix(value) {
    return String(value || '').trim() || 'unknown'
  }

  return {
    directConversationRows,
    orderedChannelsSource,
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
