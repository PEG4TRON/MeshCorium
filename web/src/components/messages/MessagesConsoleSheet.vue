<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import PluginDropdown from '../ui/PluginDropdown.vue'

const props = defineProps({
  model: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits([
  'close',
  'save',
  'update:search-term',
  'move-search-match',
  'enable-auto-scroll',
  'update:filter',
  'clear',
  'scroll-log',
])

const { t } = useI18n()

const searchTermModel = computed({
  get: () => props.model.searchTerm,
  set: (value) => emit('update:search-term', value),
})

const filterModel = computed({
  get: () => props.model.filter,
  set: (value) => emit('update:filter', value),
})
</script>

<template>
  <Teleport to="body">
    <div v-if="model.open" class="mc-overlay" @click="emit('close')">
      <section class="mc-console-shell" @click.stop>
        <header class="mc-console-header">
          <div class="mc-console-header-copy">
            <h3>{{ t('console.title') }}</h3>
            <p>{{ t('console.subtitle') }}</p>
          </div>
          <div class="mc-console-header-actions">
            <button
              v-tooltip="{ content: t('common.save'), theme: 'meshcorium-tooltip', placement: 'left' }"
              class="mc-button mc-button--ghost"
              type="button"
              @click="emit('save')"
            >
              {{ t('common.save') }}
            </button>
            <button
              v-tooltip="{ content: t('common.close'), theme: 'meshcorium-tooltip', placement: 'left' }"
              class="mc-icon-button"
              type="button"
              :aria-label="t('common.close')"
              @click="emit('close')"
            >
              ×
            </button>
          </div>
        </header>

        <div class="mc-console-stack">
          <aside class="mc-console-column mc-console-column--left">
            <div class="mc-console-bubble">
              <h4>{{ t('console.tools') }}</h4>
              <div class="mc-console-controls">
                <label class="mc-field">
                  <span>{{ t('console.search') }}</span>
                  <div class="mc-console-search-row">
                    <input v-model="searchTermModel" type="text" class="mc-console-search-input" :placeholder="t('console.searchPlaceholder')" />
                    <div class="mc-console-search-nav">
                      <button
                        v-tooltip="{ content: t('common.previous'), theme: 'meshcorium-tooltip', placement: 'left' }"
                        class="mc-icon-button"
                        type="button"
                        :disabled="model.searchMatchIndex < 0"
                        :aria-label="t('common.previous')"
                        @click="emit('move-search-match', -1)"
                      >
                        ↑
                      </button>
                      <button
                        v-tooltip="{ content: t('common.next'), theme: 'meshcorium-tooltip', placement: 'left' }"
                        class="mc-icon-button"
                        type="button"
                        :disabled="model.searchMatchIndex < 0"
                        :aria-label="t('common.next')"
                        @click="emit('move-search-match', 1)"
                      >
                        ↓
                      </button>
                    </div>
                  </div>
                </label>
                <div class="mc-console-tool-row">
                  <button
                    v-tooltip="{ content: t('console.live'), theme: 'meshcorium-tooltip' }"
                    class="mc-button mc-button--ghost"
                    :class="{ active: model.autoScroll }"
                    type="button"
                    @click="emit('enable-auto-scroll')"
                  >
                    {{ t('console.live') }}
                  </button>
                  <PluginDropdown
                    v-model="filterModel"
                    class="mc-console-filter-dropdown"
                    :options="model.filterOptions"
                    compact
                    :min-width="210"
                  />
                  <button
                    v-tooltip="{ content: t('common.clear'), theme: 'meshcorium-tooltip', placement: 'left' }"
                    class="mc-button mc-button--ghost"
                    type="button"
                    @click="emit('clear')"
                  >
                    {{ t('common.clear') }}
                  </button>
                </div>
              </div>
            </div>
          </aside>

          <main class="mc-console-column mc-console-column--live">
            <div class="mc-console-bubble mc-console-bubble--stretch">
              <h4>{{ t('console.liveEvents') }}</h4>
              <pre :ref="model.bindLogRef" class="mc-console-log" @scroll="emit('scroll-log')" v-html="model.consoleHtml"></pre>
            </div>
          </main>

          <aside class="mc-console-column mc-console-column--right">
            <div class="mc-console-bubble mc-console-bubble--stretch mc-console-bubble--self">
              <h4>{{ t('console.self') }}</h4>
              <pre class="mc-console-side-output">{{ JSON.stringify(model.selfData || {}, null, 2) }}</pre>
            </div>
            <div class="mc-console-bubble mc-console-bubble--device">
              <h4>{{ t('console.device') }}</h4>
              <pre class="mc-console-side-output">{{ JSON.stringify(model.deviceData || {}, null, 2) }}</pre>
            </div>
          </aside>
        </div>
      </section>
    </div>
  </Teleport>
</template>
