<script setup>
defineProps({
  model: {
    type: Object,
    required: true,
  },
  menuOpen: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits([
  'update:menu-open',
  'close-editor',
  'open-clear-dialog',
  'toggle-regular-mute',
  'toggle-all-mute',
  'open-search',
])
</script>

<template>
  <header class="mc-workspace-header">
    <div class="mc-workspace-copy">
      <h2 class="mc-workspace-title">{{ model.title }}</h2>
      <p class="mc-workspace-subtitle">{{ model.subtitle }}</p>
    </div>
    <div class="mc-workspace-actions">
      <button
        v-if="model.showCloseButton"
        class="mc-button mc-button--ghost"
        type="button"
        @click="emit('close-editor')"
      >
        {{ model.closeLabel }}
      </button>
      <VDropdown
        v-else
        :shown="menuOpen"
        theme="meshcorium-dropdown"
        placement="bottom-end"
        :distance="10"
        :disabled="model.chatMenuDisabled"
        @update:shown="emit('update:menu-open', $event)"
      >
        <button
          v-tooltip="{ content: model.chatMenuOpenLabel, theme: 'meshcorium-tooltip', placement: 'left' }"
          class="mc-icon-button mc-chat-actions-toggle"
          type="button"
          :aria-label="model.chatMenuOpenLabel"
          :disabled="model.chatMenuDisabled"
        >
          ⋮
        </button>

        <template #popper>
          <div class="mc-chat-actions-menu">
            <p class="mc-chat-actions-title">{{ model.chatMenuTitle }}</p>
            <button
              class="mc-button mc-button--ghost mc-chat-actions-button"
              type="button"
              @click="emit('open-clear-dialog')"
            >
              {{ model.clearLabel }}
            </button>
            <button
              class="mc-button mc-button--ghost mc-chat-actions-button"
              :class="{ active: model.regularMuteActive }"
              type="button"
              @click="emit('toggle-regular-mute')"
            >
              {{ model.regularMuteLabel }}
            </button>
            <button
              class="mc-button mc-button--ghost mc-chat-actions-button"
              :class="{ active: model.allMuteActive }"
              type="button"
              @click="emit('toggle-all-mute')"
            >
              {{ model.allMuteLabel }}
            </button>
            <button
              class="mc-button mc-button--ghost mc-chat-actions-button"
              type="button"
              @click="emit('open-search')"
            >
              {{ model.chatMenuSearchLabel }}
            </button>
          </div>
        </template>
      </VDropdown>
    </div>
  </header>
</template>
