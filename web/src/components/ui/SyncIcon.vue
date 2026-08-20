<script setup>
import { computed } from 'vue'

const props = defineProps({
  spinning: {
    type: Boolean,
    default: false,
  },
  size: {
    type: Number,
    default: 18,
  },
  scale: {
    type: Number,
    default: 1.32,
  },
})

const syncIconUrl = '/icons/sync.svg'
const rootStyle = computed(() => ({
  '--mc-sync-icon-size': `${Math.max(1, Number(props.size) || 18)}px`,
  '--mc-sync-icon-scale': String(Math.max(1, Number(props.scale) || 1.32)),
}))
</script>

<template>
  <span class="mc-sync-icon" :class="{ 'is-spinning': spinning }" :style="rootStyle" aria-hidden="true">
    <img class="mc-sync-icon-image" :src="syncIconUrl" alt="" />
  </span>
</template>

<style scoped>
.mc-sync-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--mc-sync-icon-size);
  height: var(--mc-sync-icon-size);
  overflow: hidden;
  line-height: 1;
  flex: 0 0 auto;
  transform-origin: 50% 50%;
}

.mc-sync-icon.is-spinning {
  animation: mc-icon-spin 0.85s linear infinite;
}

.mc-sync-icon-image {
  display: block;
  width: calc(var(--mc-sync-icon-size) * var(--mc-sync-icon-scale));
  height: calc(var(--mc-sync-icon-size) * var(--mc-sync-icon-scale));
  object-fit: contain;
  flex: 0 0 auto;
  pointer-events: none;
  user-select: none;
}
</style>
