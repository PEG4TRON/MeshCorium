<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  model: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['close', 'send-flood', 'send-direct'])

const { t } = useI18n()
</script>

<template>
  <Teleport to="body">
    <div v-if="model.open" class="mc-overlay" @click="emit('close')">
      <section class="mc-mini-sheet" @click.stop>
        <header class="mc-mini-header">
          <h3>{{ t('advert.typeTitle') }}</h3>
        </header>
        <div class="mc-mini-actions">
          <button
            class="mc-button mc-button--ghost"
            :disabled="model.busy"
            :class="{ active: model.mode === 'flood' }"
            @click="emit('send-flood')"
          >
            {{ model.busy && model.mode === 'flood' ? t('advert.actions.floodBusy') : t('advert.actions.flood') }}
          </button>
          <button
            class="mc-button mc-button--primary"
            :disabled="model.busy"
            :class="{ active: model.mode === 'direct' }"
            @click="emit('send-direct')"
          >
            {{ model.busy && model.mode === 'direct' ? t('advert.actions.directBusy') : t('advert.actions.direct') }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
