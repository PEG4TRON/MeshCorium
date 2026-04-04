<script setup>
defineProps({
  model: {
    type: Object,
    required: true,
  },
})
</script>

<template>
  <div class="mc-workspace-empty">
    <h3>{{ model.title }}</h3>
    <p>{{ model.subtitle }}</p>
  </div>
</template>
