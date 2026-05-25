<script setup>
import { computed, defineAsyncComponent } from 'vue'

const EmojiPicker = defineAsyncComponent(() => import('vue3-emoji-picker'))

const props = defineProps({
  model: {
    type: Object,
    required: true,
  },
  emojiPickerOpen: {
    type: Boolean,
    default: false,
  },
  draftText: {
    type: String,
    default: '',
  },
  gifCdnUrl: {
    type: Function,
    required: true,
  },
  bindTextareaRef: {
    type: Function,
    default: null,
  },
  onTextareaKeydown: {
    type: Function,
    default: null,
  },
})

const emit = defineEmits([
  'open-gif-picker',
  'update:emoji-picker-open',
  'select-emoji',
  'clear-reply',
  'clear-draft-gif',
  'update:draft-text',
  'send-message',
])

const emojiPickerShown = computed({
  get: () => props.emojiPickerOpen,
  set: (value) => emit('update:emoji-picker-open', value),
})

const draftTextModel = computed({
  get: () => props.draftText,
  set: (value) => emit('update:draft-text', value),
})

function handleTextareaKeydown(event) {
  if (typeof props.onTextareaKeydown === 'function') {
    props.onTextareaKeydown(event)
  }
}
</script>

<template>
  <footer class="mc-composer">
    <div v-if="model.replyActive" class="mc-composer-reply-bar">
      <div class="mc-composer-reply-copy">
        <span class="mc-composer-reply-overline">{{ model.replyOverline }}</span>
        <strong class="mc-composer-reply-target">{{ model.replyTarget }}</strong>
        <p class="mc-composer-reply-preview">{{ model.replyPreview }}</p>
      </div>
      <button
        class="mc-icon-button mc-composer-reply-clear"
        type="button"
        :aria-label="model.clearReplyLabel"
        @click="emit('clear-reply')"
      >
        ×
      </button>
    </div>
    <div class="mc-composer-row">
      <div class="mc-composer-tools">
        <div class="mc-composer-tools-top">
          <button
            class="mc-button mc-button--ghost mc-gif-button"
            type="button"
            :aria-label="model.gifButtonLabel"
            @click="emit('open-gif-picker')"
          >
            GIF
          </button>
          <span class="mc-composer-meta-chip">{{ model.conversationLoadedMeta }}</span>
        </div>
        <VDropdown
          v-model:shown="emojiPickerShown"
          theme="meshcorium-dropdown"
          placement="top-start"
          :distance="12"
          :disabled="model.emojiPickerDisabled"
        >
          <button
            class="mc-icon-button mc-emoji-button"
            type="button"
            :aria-label="model.emojiButtonLabel"
            :disabled="model.emojiPickerDisabled"
          >
            ☺
          </button>

          <template #popper>
            <div class="mc-emoji-picker-shell">
              <EmojiPicker
                :native="true"
                :display-recent="true"
                :hide-search="false"
                :hide-group-names="false"
                :hide-group-icons="false"
                theme="auto"
                :static-texts="model.emojiStaticTexts"
                :group-names="model.emojiGroupNames"
                @select="emit('select-emoji', $event)"
              />
            </div>
          </template>
        </VDropdown>
      </div>
      <div v-if="model.draftGifId" class="mc-composer-gif-preview">
        <img
          class="mc-composer-gif-image"
          :src="gifCdnUrl(model.draftGifId)"
          :alt="model.gifMessageLabel"
          loading="lazy"
        />
        <button
          class="mc-icon-button mc-composer-gif-clear"
          type="button"
          :aria-label="model.removeGifLabel"
          @click="emit('clear-draft-gif')"
        >
          ×
        </button>
      </div>
      <textarea
        v-else
        v-model="draftTextModel"
        :ref="bindTextareaRef"
        class="mc-composer-input"
        rows="2"
        :placeholder="model.composerPlaceholder"
        @keydown="handleTextareaKeydown"
        @keydown.enter.exact.prevent="emit('send-message')"
      ></textarea>
      <div class="mc-composer-send-stack">
        <span class="mc-composer-bytes" :class="{ 'is-over': model.draftIsOverflow }">{{ model.composerByteCounterText }}</span>
        <button class="mc-button mc-button--primary" type="button" :disabled="!model.canSendCurrentDraft" @click="emit('send-message')">
          {{ model.sendLabel }}
        </button>
      </div>
    </div>
  </footer>
</template>
