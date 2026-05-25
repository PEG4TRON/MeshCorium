<script setup>
defineProps({
  model: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits([
  'close',
  'reply',
  'route-map',
  'toggle-contact-route',
  'resend',
  'copy',
])
</script>

<template>
  <Teleport to="body">
    <div v-if="model.open" class="mc-message-context-layer" @click="emit('close')">
      <section
        class="mc-message-context-menu"
        :style="{ left: `${model.x}px`, top: `${model.y}px` }"
        @click.stop
      >
        <p class="mc-message-context-title">{{ model.title }}</p>
        <button
          v-if="model.canReply"
          class="mc-button mc-button--ghost mc-message-context-action"
          type="button"
          @click="emit('reply')"
        >
          {{ model.replyLabel }}
        </button>
        <button
          v-if="model.canRouteMap"
          class="mc-button mc-button--ghost mc-message-context-action"
          type="button"
          @click="emit('route-map')"
        >
          {{ model.routeMapLabel }}
        </button>
        <button
          v-if="model.canToggleContactRoute"
          class="mc-button mc-button--ghost mc-message-context-action"
          type="button"
          @click="emit('toggle-contact-route')"
        >
          {{ model.toggleContactRouteLabel }}
        </button>
        <button
          v-if="model.canResend"
          class="mc-button mc-button--ghost mc-message-context-action"
          type="button"
          @click="emit('resend')"
        >
          {{ model.resendLabel }}
        </button>
        <button
          v-if="model.canCopy"
          class="mc-button mc-button--ghost mc-message-context-action"
          type="button"
          @click="emit('copy')"
        >
          {{ model.copyLabel }}
        </button>
      </section>
    </div>
  </Teleport>
</template>
