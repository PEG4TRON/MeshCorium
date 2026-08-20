<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  model: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['close', 'submit'])

const { t } = useI18n()
</script>

<template>
  <Teleport to="body">
    <div v-if="model.open" class="mc-overlay" @click="emit('close')">
      <section class="mc-mini-sheet mc-mini-sheet--confirm" @click.stop>
        <header class="mc-mini-header">
          <h3>{{ model.title }}</h3>
          <p>{{ model.message }}</p>
          <p v-if="model.note" class="mc-mini-note">{{ model.note }}</p>
        </header>
        <div class="mc-mini-actions">
          <button
            class="mc-button mc-button--ghost"
            type="button"
            @click="emit('close')"
          >
            {{ t('common.cancel') }}
          </button>
          <button
            class="mc-button mc-button--primary"
            type="button"
            :disabled="Boolean(model.confirmDisabled)"
            @click="emit('submit')"
          >
            {{ model.confirmLabel }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
