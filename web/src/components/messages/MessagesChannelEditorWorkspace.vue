<script setup>
defineProps({
  model: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits([
  'set-type',
  'update:hashtag',
  'update:name',
  'update:psk-hex',
  'close',
  'save',
])
</script>

<template>
  <section class="mc-channel-editor-workspace">
    <div class="mc-channel-editor-card">
      <div class="mc-channel-editor-mode-switch">
        <button
          class="mc-button mc-button--ghost"
          type="button"
          :class="{ active: model.type === 'hashtag' }"
          @click="emit('set-type', 'hashtag')"
        >
          {{ model.hashtagTypeLabel }}
        </button>
        <button
          class="mc-button mc-button--ghost"
          type="button"
          :class="{ active: model.type === 'private' }"
          @click="emit('set-type', 'private')"
        >
          {{ model.privateTypeLabel }}
        </button>
      </div>

      <div class="mc-channel-editor-grid">
        <label class="mc-field">
          <span>{{ model.channelIdxLabel }}</span>
          <input class="mc-console-search-input" type="text" :value="model.channelIdxText" readonly />
        </label>

        <label v-if="model.type === 'hashtag'" class="mc-field">
          <span>{{ model.hashtagNameLabel }}</span>
          <input
            class="mc-console-search-input"
            type="text"
            maxlength="31"
            :value="model.hashtag"
            :placeholder="model.hashtagPlaceholder"
            @input="emit('update:hashtag', $event.target.value)"
          />
        </label>

        <label v-else class="mc-field">
          <span>{{ model.channelNameLabel }}</span>
          <input
            class="mc-console-search-input"
            type="text"
            maxlength="32"
            :value="model.name"
            :placeholder="model.channelNamePlaceholder"
            @input="emit('update:name', $event.target.value)"
          />
        </label>

        <label class="mc-field">
          <span>{{ model.resolvedNameLabel }}</span>
          <input class="mc-console-search-input" type="text" :value="model.resolvedName" readonly />
        </label>

        <label v-if="model.type === 'private'" class="mc-field">
          <span>{{ model.pskHexLabel }}</span>
          <input
            class="mc-console-search-input"
            type="text"
            maxlength="32"
            :value="model.pskHex"
            :placeholder="model.pskHexPlaceholder"
            @input="emit('update:psk-hex', $event.target.value)"
          />
        </label>

        <label class="mc-field">
          <span>{{ model.secretPreviewLabel }}</span>
          <input class="mc-console-search-input" type="text" :value="model.secretPreview" readonly />
        </label>

        <label class="mc-field">
          <span>{{ model.channelHashLabel }}</span>
          <input class="mc-console-search-input" type="text" :value="model.channelHashPreview" readonly />
        </label>
      </div>

      <p class="mc-channel-editor-note">
        {{ model.noteText }}
      </p>

      <div class="mc-channel-editor-actions">
        <button class="mc-button mc-button--ghost" type="button" @click="emit('close')">
          {{ model.cancelLabel }}
        </button>
        <button class="mc-button mc-button--primary" type="button" :disabled="!model.canSave" @click="emit('save')">
          {{ model.saveLabel }}
        </button>
      </div>
    </div>
  </section>
</template>
