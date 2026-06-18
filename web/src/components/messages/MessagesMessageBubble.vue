<script setup>
import { useI18n } from 'vue-i18n'
import { useIsMobile } from '../../composables/useIsMobile'

const { isMobile } = useIsMobile()

const props = defineProps({
  renderedMessage: {
    type: Object,
    required: true,
  },
  gifCdnUrl: {
    type: Function,
    required: true,
  },
  bindMessageCardElement: {
    type: Function,
    required: true,
  },
})

const emit = defineEmits(['open-context-menu', 'open-contact'])

const { t } = useI18n()

function setCardElement(element) {
  props.bindMessageCardElement(props.renderedMessage.messageId, props.renderedMessage.key, element)
}

function handleContextMenu(event) {
  event.preventDefault()
  event.stopPropagation()
  emit('open-context-menu', {
    event,
    renderedMessage: props.renderedMessage,
  })
}

function openMessageContact(contact) {
  if (!contact?.public_key) {
    return
  }
  emit('open-contact', contact)
}
</script>

<template>
  <div
    class="mc-message-card-frame"
    :class="{
      'is-own': renderedMessage.source?.from_self,
      'has-notification-highlight': Boolean(renderedMessage.highlightTone),
      'has-notification-highlight--unread': renderedMessage.highlightTone === 'unread',
      'has-notification-highlight--direct': renderedMessage.highlightTone === 'direct',
      'has-notification-highlight--mention': renderedMessage.highlightTone === 'mention',
    }"
    :style="{ marginBottom: `${renderedMessage.bottomGap}px` }"
  >
    <span
      v-if="renderedMessage.highlightTone"
      class="mc-message-highlight-ring"
      :class="{
        'is-unread': renderedMessage.highlightTone === 'unread',
        'is-direct': renderedMessage.highlightTone === 'direct',
        'is-mention': renderedMessage.highlightTone === 'mention',
      }"
      aria-hidden="true"
    ></span>
    <article
      :ref="setCardElement"
      class="mc-message-card"
      :class="{
        'is-own': renderedMessage.source?.from_self,
        'has-read-marker': renderedMessage.showReadMarker,
        'is-appearing': renderedMessage.isAnimated,
      }"
      @contextmenu.prevent="handleContextMenu"
    >
      <div v-if="renderedMessage.showReadMarker" class="mc-read-marker">{{ t('messages.readMarker') }}</div>
      <header class="mc-message-head">
        <div class="mc-message-head-copy">
          <div class="mc-message-author-row">
            <button
              v-if="renderedMessage.authorContact?.public_key"
              type="button"
              class="mc-message-author mc-message-contact-link"
              :class="{ 'is-resolved': renderedMessage.authorResolved }"
              @click.stop="openMessageContact(renderedMessage.authorContact)"
            >
              {{ renderedMessage.author }}
            </button>
            <span
              v-else
              class="mc-message-author"
              :class="{ 'is-resolved': renderedMessage.authorResolved }"
            >
              {{ renderedMessage.author }}
            </span>
            <span v-if="renderedMessage.replyTarget" class="mc-message-reply-sep" aria-hidden="true">@</span>
            <button
              v-if="renderedMessage.replyTargetContact?.public_key"
              type="button"
              class="mc-message-reply-target mc-message-contact-link"
              :class="{ 'is-resolved': renderedMessage.replyTargetResolved }"
              @click.stop="openMessageContact(renderedMessage.replyTargetContact)"
            >
              {{ renderedMessage.replyTarget }}
            </button>
            <span
              v-else-if="renderedMessage.replyTarget"
              class="mc-message-reply-target"
              :class="{ 'is-resolved': renderedMessage.replyTargetResolved }"
            >
              {{ renderedMessage.replyTarget }}
            </span>
          </div>
        </div>
        <div class="mc-message-time">{{ renderedMessage.timestampText }}</div>
      </header>
      <div v-if="renderedMessage.gifId" class="mc-message-gif-shell">
        <img
          class="mc-message-gif"
          :src="gifCdnUrl(renderedMessage.gifId)"
          :alt="t('messages.gif.messageLabel')"
          loading="lazy"
        />
      </div>
      <div v-else-if="renderedMessage.textHasLinks" class="mc-message-text" v-html="renderedMessage.textHtml"></div>
      <div v-else class="mc-message-text">{{ renderedMessage.text }}</div>
      <footer class="mc-message-meta">
        <div class="mc-message-meta-row">
          <div class="mc-message-meta-group mc-message-meta-group--primary">
            <span>{{ renderedMessage.signalMeta }}</span>
            <span>{{ renderedMessage.hopsMeta }}</span>
          </div>
          <div
            v-if="renderedMessage.deliveryText"
            class="mc-message-meta-group mc-message-meta-group--delivery"
          >
            <span class="mc-message-delivery">{{ renderedMessage.deliveryText }}</span>
          </div>
        </div>
        <span v-if="renderedMessage.routeMeta" class="mc-message-route">{{ renderedMessage.routeMeta }}</span>
        <div v-if="isMobile" class="mc-message-time mc-message-time--mobile">{{ renderedMessage.timestampText }}</div>
      </footer>
    </article>
  </div>
</template>
