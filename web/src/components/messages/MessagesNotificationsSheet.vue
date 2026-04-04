<script setup>
import { useI18n } from 'vue-i18n'

const soundOnIconUrl = '/icons/sound-yes.svg'
const soundOffIconUrl = '/icons/sound-no.svg'

defineProps({
  model: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits([
  'close',
  'toggle-sound',
  'update:mentions-collapsed',
  'update:regular-collapsed',
  'update:direct-collapsed',
  'mark-mentions-read',
  'mark-regular-read',
  'mark-direct-read',
  'open-entry',
])

const { t } = useI18n()
</script>

<template>
  <Teleport to="body">
    <div v-if="model.open" class="mc-overlay" @click="emit('close')">
      <section class="mc-notifications-sheet" @click.stop>
        <header class="mc-notifications-header">
          <div class="mc-notifications-copy">
            <h3>{{ t('notifications.title') }}</h3>
            <div class="mc-notifications-meta-row">
              <p>{{ model.notificationsMetaText }}</p>
              <button
                v-tooltip="{ content: model.notificationSoundEnabled ? t('notifications.sound.on') : t('notifications.sound.off'), theme: 'meshcorium-tooltip', placement: 'left' }"
                class="mc-button mc-button--ghost mc-sound-toggle-button"
                type="button"
                :class="{ muted: !model.notificationSoundEnabled }"
                :aria-label="model.notificationSoundEnabled ? t('notifications.sound.on') : t('notifications.sound.off')"
                @click.stop.prevent="emit('toggle-sound')"
              >
                <img
                  class="mc-sound-toggle-icon"
                  :src="model.notificationSoundEnabled ? soundOnIconUrl : soundOffIconUrl"
                  alt=""
                />
              </button>
              <div class="mc-notifications-bell" :class="{ 'is-pulsing': model.totalRegularUnreadCount > 0 || model.totalDirectUnreadCount > 0 || model.totalMentionCount > 0 }" aria-hidden="true">
                <img :src="model.bellIconUrl" alt="" />
                <span v-if="model.totalRegularUnreadCount" class="mc-rail-badge">{{ model.totalRegularUnreadCount > 99 ? '99+' : model.totalRegularUnreadCount }}</span>
                <span v-if="model.totalDirectUnreadCount" class="mc-rail-badge mc-rail-badge--direct">{{ model.totalDirectUnreadCount > 99 ? '99+' : model.totalDirectUnreadCount }}</span>
                <span v-if="model.totalMentionCount" class="mc-rail-badge mc-rail-badge--mention">{{ model.totalMentionCount > 99 ? '99+' : model.totalMentionCount }}</span>
              </div>
            </div>
          </div>
          <button
            v-tooltip="{ content: t('common.close'), theme: 'meshcorium-tooltip', placement: 'left' }"
            class="mc-icon-button"
            type="button"
            :aria-label="t('common.close')"
            @click="emit('close')"
          >
            ×
          </button>
        </header>

        <div class="mc-notifications-list">
          <div v-if="model.mentionEntries.length" class="mc-notifications-section">
            <div class="mc-notifications-divider">
              <button
                v-tooltip="{ content: model.mentionsCollapsed ? t('notifications.actions.expandMentions') : t('notifications.actions.collapseMentions'), theme: 'meshcorium-tooltip' }"
                class="mc-notifications-divider-action"
                type="button"
                :aria-label="model.mentionsCollapsed ? t('notifications.actions.expandMentions') : t('notifications.actions.collapseMentions')"
                @click="emit('update:mentions-collapsed', !model.mentionsCollapsed)"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    v-if="model.mentionsCollapsed"
                    d="m8 5 8 7-8 7"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                  <path
                    v-else
                    d="m5 8 7 8 7-8"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </button>
              <span class="mc-notifications-divider-line"></span>
              <span class="mc-notifications-divider-label">{{ t('notifications.sections.mentions') }}</span>
              <span class="mc-notifications-divider-line"></span>
              <button
                v-tooltip="{ content: t('notifications.actions.markMentionsRead'), theme: 'meshcorium-tooltip', placement: 'left' }"
                class="mc-notifications-divider-action"
                type="button"
                :aria-label="t('notifications.actions.markMentionsRead')"
                @click="emit('mark-mentions-read')"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M2.5 12s3.9-6.5 9.5-6.5S21.5 12 21.5 12s-3.9 6.5-9.5 6.5S2.5 12 2.5 12Z" fill="none" stroke="currentColor" stroke-width="1.8"/>
                  <circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/>
                </svg>
              </button>
            </div>
            <div v-if="!model.mentionsCollapsed" class="mc-notifications-stack">
              <button v-for="entry in model.mentionEntries" :key="entry.key" class="mc-notification-item" @click="emit('open-entry', entry)">
                <div class="mc-list-avatar">{{ entry.avatarSymbol }}</div>
                <div class="mc-list-main">
                  <div class="mc-list-title-row">
                    <p class="mc-list-title">{{ entry.title }}</p>
                    <span class="mc-notification-pill">{{ t('notifications.mentionPill') }}</span>
                  </div>
                  <p class="mc-list-preview">{{ entry.preview }}</p>
                </div>
              </button>
            </div>
          </div>

          <div class="mc-notifications-section">
            <div class="mc-notifications-divider">
              <button
                v-tooltip="{ content: model.regularCollapsed ? t('notifications.actions.expandRegular') : t('notifications.actions.collapseRegular'), theme: 'meshcorium-tooltip' }"
                class="mc-notifications-divider-action"
                type="button"
                :aria-label="model.regularCollapsed ? t('notifications.actions.expandRegular') : t('notifications.actions.collapseRegular')"
                @click="emit('update:regular-collapsed', !model.regularCollapsed)"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    v-if="model.regularCollapsed"
                    d="m8 5 8 7-8 7"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                  <path
                    v-else
                    d="m5 8 7 8 7-8"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </button>
              <span class="mc-notifications-divider-line"></span>
              <span class="mc-notifications-divider-label">{{ t('notifications.sections.chats') }}</span>
              <span class="mc-notifications-divider-line"></span>
              <button
                v-tooltip="{ content: t('notifications.actions.markRegularRead'), theme: 'meshcorium-tooltip', placement: 'left' }"
                class="mc-notifications-divider-action"
                type="button"
                :aria-label="t('notifications.actions.markRegularRead')"
                @click="emit('mark-regular-read')"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M2.5 12s3.9-6.5 9.5-6.5S21.5 12 21.5 12s-3.9 6.5-9.5 6.5S2.5 12 2.5 12Z" fill="none" stroke="currentColor" stroke-width="1.8"/>
                  <circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/>
                </svg>
              </button>
            </div>
            <div v-if="!model.regularCollapsed" class="mc-notifications-stack">
              <button v-for="entry in model.regularEntries" :key="entry.key" class="mc-notification-item" @click="emit('open-entry', entry)">
                <div class="mc-list-avatar">{{ entry.avatarSymbol }}</div>
                <div class="mc-list-main">
                  <div class="mc-list-title-row">
                    <p class="mc-list-title">{{ entry.title }}</p>
                    <span class="mc-list-meta">{{ t('notifications.unreadCount', { count: entry.unreadCount }) }}</span>
                  </div>
                  <p class="mc-list-preview">{{ entry.preview }}</p>
                </div>
              </button>
              <div v-if="!model.regularEntries.length" class="mc-notifications-empty">{{ t('notifications.empty.noneUnread') }}</div>
            </div>
          </div>

          <div class="mc-notifications-section">
            <div class="mc-notifications-divider">
              <button
                v-tooltip="{ content: model.directCollapsed ? t('notifications.actions.expandDirect') : t('notifications.actions.collapseDirect'), theme: 'meshcorium-tooltip' }"
                class="mc-notifications-divider-action"
                type="button"
                :aria-label="model.directCollapsed ? t('notifications.actions.expandDirect') : t('notifications.actions.collapseDirect')"
                @click="emit('update:direct-collapsed', !model.directCollapsed)"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    v-if="model.directCollapsed"
                    d="m8 5 8 7-8 7"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                  <path
                    v-else
                    d="m5 8 7 8 7-8"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </button>
              <span class="mc-notifications-divider-line"></span>
              <span class="mc-notifications-divider-label">{{ t('notifications.sections.directs') }}</span>
              <span class="mc-notifications-divider-line"></span>
              <button
                v-tooltip="{ content: t('notifications.actions.markDirectRead'), theme: 'meshcorium-tooltip', placement: 'left' }"
                class="mc-notifications-divider-action"
                type="button"
                :aria-label="t('notifications.actions.markDirectRead')"
                @click="emit('mark-direct-read')"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M2.5 12s3.9-6.5 9.5-6.5S21.5 12 21.5 12s-3.9 6.5-9.5 6.5S2.5 12 2.5 12Z" fill="none" stroke="currentColor" stroke-width="1.8"/>
                  <circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/>
                </svg>
              </button>
            </div>
            <div v-if="!model.directCollapsed" class="mc-notifications-stack">
              <button v-for="entry in model.directEntries" :key="entry.key" class="mc-notification-item" @click="emit('open-entry', entry)">
                <div class="mc-list-avatar">{{ entry.avatarSymbol }}</div>
                <div class="mc-list-main">
                  <div class="mc-list-title-row">
                    <p class="mc-list-title">{{ entry.title }}</p>
                    <span class="mc-list-meta">{{ t('notifications.unreadCount', { count: entry.unreadCount }) }}</span>
                  </div>
                  <p class="mc-list-preview">{{ entry.preview }}</p>
                </div>
              </button>
              <div v-if="!model.directEntries.length" class="mc-notifications-empty">{{ t('notifications.empty.noneUnread') }}</div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </Teleport>
</template>
