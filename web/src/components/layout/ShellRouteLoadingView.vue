<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import ShellPageFrame from './ShellPageFrame.vue'
import ShellPhonebar from './ShellPhonebar.vue'

const props = defineProps({
  titleKey: {
    type: String,
    required: true,
  },
  messageKey: {
    type: String,
    required: true,
  },
})

const { t } = useI18n()

const title = computed(() => t(props.titleKey))
const message = computed(() => t(props.messageKey))
</script>

<template>
  <ShellPageFrame workspace-class="mc-content--shell-body">
    <template #scroller-header>
      <div class="mc-scroller-copy">
        <h1 class="mc-scroller-title">{{ title }}</h1>
      </div>
    </template>

    <template #scroller-body>
      <div class="mc-list-scroll mc-list-scroll--ghost">
        <div v-for="index in 6" :key="index" class="mc-list-item mc-list-item--ghost">
          <div class="mc-list-avatar">•</div>
          <div class="mc-list-main">
            <div class="mc-list-title-row">
              <p class="mc-list-title">{{ title }}</p>
            </div>
            <p class="mc-list-preview">{{ message }}</p>
          </div>
        </div>
      </div>
    </template>

    <template #scroller-footer>
      <div class="mc-status">{{ message }}</div>
    </template>

    <template #workspace-top>
      <ShellPhonebar />
    </template>

    <template #workspace-body>
      <section class="mc-workspace-empty mc-workspace-empty--maps">
        <h3>{{ title }}</h3>
        <p>{{ message }}</p>
      </section>
    </template>
  </ShellPageFrame>
</template>
