<script setup>
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'

const props = defineProps({
  model: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['search', 'prev', 'next', 'close'])

const panelRef = ref(null)
const gripRef = ref(null)
const inputRef = ref(null)
const searchText = ref('')

const panelLeft = ref(undefined)
const panelTop = ref(undefined)

function onDragStart(e) {
  const panel = panelRef.value
  if (!panel) return
  gripRef.value?.setPointerCapture(e.pointerId)
  const rect = panel.getBoundingClientRect()
  const startX = e.clientX
  const startY = e.clientY
  const startLeft = rect.left
  const startTop = rect.top

  function onMove(ev) {
    panelLeft.value = Math.max(0, startLeft + ev.clientX - startX)
    panelTop.value = Math.max(0, startTop + ev.clientY - startY)
  }
  function onUp() {
    gripRef.value?.releasePointerCapture(e.pointerId)
    document.removeEventListener('pointermove', onMove)
    document.removeEventListener('pointerup', onUp)
  }
  document.addEventListener('pointermove', onMove)
  document.addEventListener('pointerup', onUp)
}

const panelStyle = computed(() => {
  if (panelLeft.value == null) {
    return { position: 'fixed', right: '16px', top: '80px', zIndex: 300 }
  }
  return { position: 'fixed', left: panelLeft.value + 'px', top: panelTop.value + 'px', zIndex: 300 }
})

watch(() => props.model.visible, async (visible) => {
  if (visible) {
    panelLeft.value = undefined
    panelTop.value = undefined
    await nextTick()
    inputRef.value?.focus()
  }
})

onBeforeUnmount(() => {
  // cleanup in case component unmounts mid-drag
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="model.visible"
      ref="panelRef"
      class="mc-search-panel"
      :style="panelStyle"
    >
      <div
        ref="gripRef"
        class="mc-search-grip"
        @pointerdown="onDragStart"
      >⠿</div>
      <div class="mc-search-body">
        <input
          ref="inputRef"
          v-model="searchText"
          class="mc-search-input"
          placeholder="Поиск..."
          @keydown.enter="emit('search', searchText)"
          @keydown.escape="emit('close')"
        />
        <div class="mc-search-nav">
          <button
            class="mc-search-nav-btn"
            :disabled="!model.hasPrev"
            @click="emit('prev')"
          >↑</button>
          <span class="mc-search-counter">{{ model.currentIndex + 1 }} / {{ model.totalResults }}</span>
          <button
            class="mc-search-nav-btn"
            :disabled="!model.hasNext"
            @click="emit('next')"
          >↓</button>
        </div>
        <button
          class="mc-search-close"
          @click="emit('close')"
        >✕</button>
      </div>
    </div>
  </Teleport>
</template>
