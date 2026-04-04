<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  section: {
    type: String,
    default: 'body',
  },
  chatEditMode: {
    type: Boolean,
    default: false,
  },
  conversationListItems: {
    type: Array,
    default: () => [],
  },
  visibleConversationListWindow: {
    type: Object,
    default: () => ({
      items: [],
      topPadding: 0,
      bottomPadding: 0,
    }),
  },
  scrollerEntriesLength: {
    type: Number,
    default: 0,
  },
  statusText: {
    type: String,
    default: '',
  },
  statusError: {
    type: Boolean,
    default: false,
  },
  connected: {
    type: Boolean,
    default: false,
  },
  bindScrollerRef: {
    type: Function,
    default: null,
  },
  bindRowElement: {
    type: Function,
    default: null,
  },
})

const emit = defineEmits([
  'toggle-edit-mode',
  'update-scroller-metrics',
  'select-channel',
  'select-contact',
  'open-channel-editor',
  'start-new-channel-editor',
])

const { t } = useI18n()
</script>

<template>
  <template v-if="section === 'header'">
    <div class="mc-scroller-copy">
      <h1 class="mc-scroller-title">{{ t('messages.title') }}</h1>
    </div>
    <button
      v-tooltip="{ content: chatEditMode ? t('messages.editor.actions.done') : t('messages.editor.actions.openListEditor'), theme: 'meshcorium-tooltip', placement: 'right' }"
      class="mc-icon-button mc-sidebar-top-action"
      type="button"
      :aria-label="chatEditMode ? t('messages.editor.actions.done') : t('messages.editor.actions.openListEditor')"
      :class="{ active: chatEditMode }"
      @click="emit('toggle-edit-mode')"
    >
      ✎
    </button>
  </template>

  <div v-else-if="section === 'body'" :ref="bindScrollerRef" class="mc-list-scroll" @scroll="emit('update-scroller-metrics')">
    <div v-if="conversationListItems.length > 0" class="mc-list-virtual-track">
      <div class="mc-list-virtual-spacer" :style="{ height: `${visibleConversationListWindow.topPadding}px` }"></div>
      <template v-for="entry in visibleConversationListWindow.items" :key="entry.key">
        <button
          v-if="entry.kind !== 'add-channel'"
          :ref="(element) => bindRowElement?.(entry.key, element)"
          class="mc-list-item"
          :class="{ active: entry.selected }"
          @click="entry.kind === 'channel' ? emit('select-channel', entry.channel.idx) : emit('select-contact', entry.contact.public_key)"
        >
          <div class="mc-list-avatar" :class="{ 'is-contact': entry.kind === 'contact', 'is-emoji': entry.avatarIsEmoji }">
            {{ entry.avatarText }}
            <span v-if="entry.unreadCount" class="mc-list-badge" :class="{ 'mc-list-badge--direct': entry.kind === 'contact' }">
              {{ entry.unreadCount > 99 ? '99+' : entry.unreadCount }}
            </span>
            <span v-if="entry.mentionCount" class="mc-list-badge mc-list-badge--mention">
              {{ entry.mentionCount > 99 ? '99+' : entry.mentionCount }}
            </span>
          </div>
          <div class="mc-list-main">
            <div class="mc-list-title-row">
              <p class="mc-list-title">{{ entry.title }}</p>
              <span class="mc-list-meta">{{ entry.meta }}</span>
            </div>
            <p class="mc-list-preview">{{ entry.preview }}</p>
          </div>
          <div class="mc-list-corner">
            <span
              v-if="entry.muteMode !== 'none'"
              v-tooltip="{ content: entry.muteLabel, theme: 'meshcorium-tooltip', placement: 'left' }"
              class="mc-conversation-mute-indicator"
              :class="`is-${entry.muteMode}`"
              :aria-label="entry.muteLabel"
            >
              🔇
            </span>
            <button
              v-if="chatEditMode && entry.kind === 'channel'"
              v-tooltip="{ content: entry.editLabel, theme: 'meshcorium-tooltip', placement: 'left' }"
              class="mc-list-edit-button"
              type="button"
              :aria-label="entry.editLabel"
              :disabled="entry.isProtectedChannel"
              @click.stop="emit('open-channel-editor', entry.channel)"
            >
              ✎
            </button>
            <span v-if="entry.kind === 'contact'" class="mc-contact-badge">{{ entry.contactBadge }}</span>
          </div>
        </button>
        <button
          v-else
          :ref="(element) => bindRowElement?.(entry.key, element)"
          class="mc-list-item mc-list-item--add"
          type="button"
          @click="emit('start-new-channel-editor')"
        >
          <div class="mc-list-avatar mc-list-avatar--add">+</div>
          <div class="mc-list-main">
            <div class="mc-list-title-row">
              <p class="mc-list-title">{{ t('messages.editor.addTile.title') }}</p>
            </div>
            <p class="mc-list-preview">{{ t('messages.editor.addTile.subtitle') }}</p>
          </div>
        </button>
      </template>
      <div class="mc-list-virtual-spacer" :style="{ height: `${visibleConversationListWindow.bottomPadding}px` }"></div>
    </div>
    <div v-if="!scrollerEntriesLength" class="mc-list-empty">{{ t('messages.empty.connectToSeeChannels') }}</div>
  </div>

  <div v-else class="mc-status" :class="{ 'is-error': statusError }">
    {{ statusText || (connected ? t('messages.status.listenerActive') : t('connect.ghost.waiting')) }}
  </div>
</template>
