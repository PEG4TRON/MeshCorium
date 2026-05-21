<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  model: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits([
  'close',
  'update:search-term',
  'search',
  'clear-search',
  'retry',
  'load-more',
  'select-gif',
])

const { t } = useI18n()

const searchTermModel = computed({
  get: () => props.model.searchTerm,
  set: (value) => emit('update:search-term', value),
})

function handleBodyScroll(event) {
  const element = event?.target
  if (!element) {
    return
  }
  const scrollTop = Number(element.scrollTop || 0)
  const clientHeight = Number(element.clientHeight || 0)
  const scrollHeight = Number(element.scrollHeight || 0)
  if ((scrollTop + clientHeight) >= (scrollHeight - 180)) {
    emit('load-more')
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="model.open" class="mc-overlay" @click="emit('close')">
      <section class="mc-gif-sheet" @click.stop>
        <header class="mc-gif-sheet-header">
          <div class="mc-gif-sheet-copy">
            <h3>{{ t('messages.gif.title') }}</h3>
          </div>
          <button
            class="mc-icon-button"
            type="button"
            :aria-label="t('common.close')"
            @click="emit('close')"
          >
            ×
          </button>
        </header>
        <div class="mc-gif-search-row">
          <input
            v-model="searchTermModel"
            class="mc-console-search-input"
            type="text"
            :placeholder="t('messages.gif.searchPlaceholder')"
            @keydown.enter.prevent="emit('search')"
          />
          <button class="mc-button mc-button--ghost" type="button" @click="emit('search')">
            {{ t('console.search') }}
          </button>
          <button
            v-if="model.searchTerm"
            class="mc-button mc-button--ghost"
            type="button"
            @click="emit('clear-search')"
          >
            {{ t('common.clear') }}
          </button>
        </div>
        <div class="mc-gif-sheet-body" @scroll.passive="handleBodyScroll">
          <div v-if="model.busy" class="mc-gif-empty">{{ t('messages.gif.loading') }}</div>
          <div v-else-if="model.errorText" class="mc-gif-empty">
            <p>{{ model.errorText }}</p>
            <button class="mc-button mc-button--ghost" type="button" @click="emit('retry')">
              {{ t('common.retry') }}
            </button>
          </div>
          <div v-else-if="!model.hasResults" class="mc-gif-empty">{{ t('messages.gif.empty') }}</div>
          <div v-else class="mc-gif-grid">
            <button
              v-for="gif in model.items"
              :key="String(gif?.id || '')"
              class="mc-gif-tile"
              type="button"
              @click="emit('select-gif', gif?.id)"
            >
              <img
                v-if="model.gifPreviewUrl(gif)"
                class="mc-gif-tile-image"
                :src="model.gifPreviewUrl(gif)"
                :alt="String(gif?.title || t('messages.gif.messageLabel'))"
                loading="lazy"
              />
              <span v-else class="mc-gif-tile-fallback">GIF</span>
            </button>
          </div>
          <div v-if="model.loadingMore" class="mc-gif-more-status">{{ t('messages.gif.loading') }}</div>
        </div>
        <footer class="mc-gif-sheet-footer">{{ t('messages.gif.poweredBy') }}</footer>
      </section>
    </div>
  </Teleport>
</template>
