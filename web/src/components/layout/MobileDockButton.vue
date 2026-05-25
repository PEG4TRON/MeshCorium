<script setup>
defineProps({
  icon: { type: String, default: '' },
  label: { type: String, default: '' },
  active: { type: Boolean, default: false },
  badge: { type: [String, Number], default: '' },
  badgeClass: { type: String, default: '' },
})

const emit = defineEmits(['click'])
</script>

<template>
  <button
    class="mc-dock-btn"
    :class="{ active }"
    @click="emit('click')"
  >
    <span class="mc-dock-icon">{{ icon }}</span>
    <span v-if="label" class="mc-dock-label">{{ label }}</span>
    <span v-if="badge" class="mc-dock-badge" :class="badgeClass">{{ badge }}</span>
  </button>
</template>

<style scoped>
.mc-dock-btn {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  width: 56px;
  height: 56px;
  padding: 4px;
  border: none;
  border-radius: 14px;
  background: transparent;
  color: rgba(215,232,251,0.55);
  cursor: pointer;
  transition: color 150ms, background 150ms;
  -webkit-tap-highlight-color: transparent;
  font-family: inherit;
}

.mc-dock-btn.active {
  color: #d7e8fb;
  background: rgba(215,232,251,0.1);
}

.mc-dock-icon {
  font-size: 22px;
  line-height: 1;
}

.mc-dock-label {
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 48px;
}

.mc-dock-badge {
  position: absolute;
  top: 4px;
  right: 2px;
  min-width: 16px;
  height: 16px;
  padding: 0 5px;
  display: inline-grid;
  place-items: center;
  border-radius: 999px;
  font-size: 9px;
  font-weight: 700;
  line-height: 1;
  color: #fff;
  background: #f07178;
}

.mc-dock-badge.mention {
  background: #d6a84f;
  color: #fff9ec;
}

.mc-dock-badge.update {
  background: #228b22;
  color: #fff;
}
</style>
