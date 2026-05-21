<script setup>
defineProps({
  scrollerClass: {
    type: [String, Array, Object],
    default: '',
  },
  scrollerHeaderClass: {
    type: [String, Array, Object],
    default: '',
  },
  workspaceClass: {
    type: [String, Array, Object],
    default: '',
  },
})
</script>

<template>
  <aside class="mc-sidebar mc-page-scroller mc-page-frame-scroller" :class="scrollerClass">
    <div
      v-if="$slots['scroller-header']"
      class="mc-sidebar-top mc-page-frame-scroller-header"
      :class="scrollerHeaderClass"
    >
      <slot name="scroller-header" />
    </div>

    <div class="mc-page-frame-scroller-body">
      <slot name="scroller-body" />
    </div>

    <div v-if="$slots['scroller-footer']" class="mc-page-frame-scroller-footer">
      <slot name="scroller-footer" />
    </div>
  </aside>

  <main class="mc-content mc-page-workspace mc-page-frame-workspace" :class="workspaceClass">
    <div class="mc-page-frame-workspace-top">
      <slot name="workspace-top" />
    </div>

    <div v-if="$slots['workspace-header']" class="mc-page-frame-workspace-header">
      <slot name="workspace-header" />
    </div>

    <div class="mc-page-frame-workspace-body">
      <slot name="workspace-body" />
    </div>

    <div v-if="$slots['workspace-footer']" class="mc-page-frame-workspace-footer">
      <slot name="workspace-footer" />
    </div>
  </main>
</template>
