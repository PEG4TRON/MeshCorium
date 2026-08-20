<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  model: {
    type: Object,
    required: true,
  },
})

const { t } = useI18n()
</script>

<template>
  <Teleport to="body">
    <div v-if="model.open" class="mc-overlay" @click.self>
      <section class="mc-message-route-sheet">
        <div class="mc-map-stage mc-map-stage--message-route">
          <div class="mc-map-route-panel mc-map-route-panel--sheet">
            <div class="mc-map-route-panel-head">
              <div>
                <h3>{{ t('maps.messageRoute.title') }}</h3>
                <p>{{ model.preview || t('maps.messageRoute.emptyPreview') }}</p>
              </div>
            </div>
          </div>

          <div class="mc-map-stage-overlay">
            <div class="mc-workspace-empty mc-workspace-empty--maps">
              <h3>{{ t('maps.status.loadingTitle') }}</h3>
              <p>{{ t('maps.status.loadingSubtitle') }}</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  </Teleport>
</template>
