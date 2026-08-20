<template>
  <div class="mc-phonebar-row">
    <div class="mc-phonebar-left">
      <div class="mc-metric">ch: <strong>{{ channels }}</strong></div>
      <div class="mc-metric">cont: <strong>{{ contacts }}</strong></div>
    </div>
    <div class="mc-phonebar-right">
      <div class="mc-node-model">
        <img v-if="nodePreviewUrl" :src="nodePreviewUrl" alt="" class="mc-node-model-preview" />
        <strong>{{ deviceModel }}</strong>
      </div>
      <span class="mc-node-led" :class="connected ? 'status-connected' : 'status-disconnected'"></span>
      <div class="mc-node-name"><strong>{{ nodeName }}</strong></div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  channels: { type: String, default: '' },
  contacts: { type: String, default: '' },
  connected: { type: Boolean, default: false },
  deviceModel: { type: String, default: '' },
  nodeName: { type: String, default: '' },
  nodePreviewUrl: { type: String, default: '' },
})
</script>
