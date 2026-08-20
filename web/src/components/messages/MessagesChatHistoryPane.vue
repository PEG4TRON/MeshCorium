<script setup>
import { useI18n } from 'vue-i18n'

import MessagesMessageBubble from './MessagesMessageBubble.vue'

defineProps({
  loadingOlderMessages: {
    type: Boolean,
    default: false,
  },
  loadingNewerMessages: {
    type: Boolean,
    default: false,
  },
  messagesLength: {
    type: Number,
    default: 0,
  },
  virtualMessageWindow: {
    type: Object,
    default: () => ({
      topPadding: 0,
      bottomPadding: 0,
    }),
  },
  visibleRenderedMessages: {
    type: Array,
    default: () => [],
  },
  loadingMessages: {
    type: Boolean,
    default: false,
  },
  showScrollToBottomButton: {
    type: Boolean,
    default: false,
  },
  gifCdnUrl: {
    type: Function,
    required: true,
  },
  bindScrollerRef: {
    type: Function,
    default: null,
  },
  bindMessageCardElement: {
    type: Function,
    required: true,
  },
  searchHighlight: {
    type: Boolean,
    default: false,
  },
  searchQuery: {
    type: String,
    default: '',
  },
  searchHighlightedMessageId: {
    type: [Number, String],
    default: null,
  },
})

const emit = defineEmits(['scroll', 'scroll-to-bottom', 'message-context-menu', 'open-contact'])

const { t } = useI18n()
</script>

<template>
  <div class="mc-chat-shell">
    <div :ref="bindScrollerRef" class="mc-chat-body" @scroll="emit('scroll')">
      <div v-if="loadingOlderMessages" class="mc-chat-note mc-chat-note--top">{{ t('messages.status.loadingOlderHistory') }}</div>
      <div v-if="messagesLength > 0" class="mc-chat-virtual-track">
        <div class="mc-chat-virtual-spacer" :style="{ height: `${virtualMessageWindow.topPadding}px` }"></div>
        <MessagesMessageBubble
          v-for="renderedMessage in visibleRenderedMessages"
          :key="renderedMessage.key"
          v-memo="renderedMessage.memo"
          :rendered-message="renderedMessage"
          :gif-cdn-url="gifCdnUrl"
          :bind-message-card-element="bindMessageCardElement"
          :search-highlighted-message-id="searchHighlightedMessageId"
          :search-query="searchQuery"
          @open-context-menu="emit('message-context-menu', $event)"
          @open-contact="emit('open-contact', $event)"
        />
        <div class="mc-chat-virtual-spacer" :style="{ height: `${virtualMessageWindow.bottomPadding}px` }"></div>
      </div>
      <div v-if="loadingNewerMessages" class="mc-chat-note mc-chat-note--bottom">{{ t('messages.status.loadingNewerHistory') }}</div>
      <div v-if="loadingMessages" class="mc-chat-note">{{ t('messages.status.loadingHistory') }}</div>
      <div v-else-if="messagesLength === 0" class="mc-chat-note">{{ t('messages.empty.noLocalHistory') }}</div>
    </div>
    <button
      v-if="showScrollToBottomButton"
      v-tooltip="{ content: t('messages.actions.scrollToBottom'), theme: 'meshcorium-tooltip', placement: 'left' }"
      class="mc-scroll-to-bottom"
      type="button"
      :aria-label="t('messages.actions.scrollToBottom')"
      @click="emit('scroll-to-bottom')"
    >
      ↓
    </button>
  </div>
</template>
