<script setup>
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import NodeConnectPanel from '../components/connect/NodeConnectPanel.vue'
import PhonebarClock from '../components/layout/PhonebarClock.vue'
import ShellPageFrame from '../components/layout/ShellPageFrame.vue'
import { useSessionStore } from '../stores/session'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const session = useSessionStore()
const bellIconUrl = '/icons/bell-icon.svg'
const messagesIconUrl = '/icons/paper-plane.png'
const advertIconUrl = '/icons/mesh_broadcast_icon.svg'

async function bootstrap() {
  try {
    await session.loadClientSettings()
    await session.refreshPorts()
    const snapshot = await session.syncSessionState({ light: true })
    if (snapshot?.active) {
      router.replace('/messages')
      return
    }
    session.setStatus(t('connect.status.pickPort'))
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('connect.status.loadFailed')), true)
  }
}

onMounted(() => {
  if (route.query.reason === 'disconnected' && !session.connectNotice) {
    session.showConnectNotice(t('connect.notice.disconnected'), true)
  }
  bootstrap()
})
</script>

<template>
  <div class="mc-page">
    <div class="mc-shell mc-shell--messages is-blurred">
      <aside class="mc-rail">
        <button v-tooltip="{ content: t('notifications.title'), theme: 'meshcorium-tooltip' }" class="mc-rail-button mc-rail-button--icon-only active" type="button" :aria-label="t('notifications.title')"><img :src="bellIconUrl" :alt="t('notifications.title')" /></button>
        <button v-tooltip="{ content: t('messages.title'), theme: 'meshcorium-tooltip' }" class="mc-rail-button active" type="button" :aria-label="t('messages.title')"><img :src="messagesIconUrl" :alt="t('messages.title')" /></button>
        <button v-tooltip="{ content: t('common.contacts'), theme: 'meshcorium-tooltip' }" class="mc-rail-button" type="button" :aria-label="t('common.contacts')">👥</button>
        <button v-tooltip="{ content: t('common.maps'), theme: 'meshcorium-tooltip' }" class="mc-rail-button" type="button" :aria-label="t('common.maps')">🗺</button>
        <div class="mc-rail-divider"></div>
        <button v-tooltip="{ content: t('console.title'), theme: 'meshcorium-tooltip' }" class="mc-rail-button" type="button" :aria-label="t('console.title')">&gt;_</button>
        <button v-tooltip="{ content: t('advert.send'), theme: 'meshcorium-tooltip' }" class="mc-rail-button" type="button" :aria-label="t('advert.send')"><img :src="advertIconUrl" :alt="t('advert.send')" /></button>
        <div class="mc-rail-spacer"></div>
        <div class="mc-rail-divider"></div>
        <button v-tooltip="{ content: t('common.settings'), theme: 'meshcorium-tooltip' }" class="mc-rail-button" type="button" :aria-label="t('common.settings')" @click="router.push('/settings')">⚙</button>
        <button v-tooltip="{ content: t('common.disconnect'), theme: 'meshcorium-tooltip' }" class="mc-rail-button mc-rail-button--danger" type="button" :aria-label="t('common.disconnect')">⏻</button>
      </aside>

      <ShellPageFrame workspace-class="mc-content--shell-body">
        <template #scroller-header>
          <div class="mc-scroller-copy">
            <h1 class="mc-scroller-title">{{ t('messages.title') }}</h1>
          </div>
        </template>

        <template #scroller-body>
          <div class="mc-list-scroll mc-list-scroll--ghost">
            <div v-for="index in 9" :key="index" class="mc-list-item mc-list-item--ghost">
              <div class="mc-list-avatar">#</div>
              <div class="mc-list-main">
                <div class="mc-list-title-row">
                  <p class="mc-list-title">{{ t('connect.ghost.channel', { index }) }}</p>
                  <span class="mc-list-meta">{{ t('messages.visibility.public') }}</span>
                </div>
                <p class="mc-list-preview">{{ t('connect.ghost.preview') }}</p>
              </div>
            </div>
          </div>
        </template>

        <template #scroller-footer>
          <div class="mc-status">{{ t('connect.ghost.waiting') }}</div>
        </template>

        <template #workspace-top>
          <header class="mc-phonebar">
          <div class="mc-phonebar-row mc-phonebar-row--with-clock">
            <div class="mc-phonebar-left">
              <div class="mc-metric">R <strong>{{ session.recentRepeaterCount }}</strong></div>
              <div class="mc-signal level-0"><span></span><span></span><span></span><span></span></div>
              <div class="mc-metric">{{ t('messages.phonebar.snr') }} <strong>{{ t('common.na') }}</strong></div>
              <div class="mc-metric">{{ t('messages.phonebar.noise') }} <strong>{{ t('common.na') }}</strong></div>
            </div>
            <PhonebarClock />
            <div class="mc-phonebar-right">
              <div class="mc-battery">
                <button
                  v-tooltip="{ content: t('notifications.sound.on'), theme: 'meshcorium-tooltip' }"
                  class="mc-sound-toggle"
                  type="button"
                  :aria-label="t('notifications.sound.on')"
                >
                  🔊
                </button>
              </div>
            </div>
          </div>
          <div class="mc-phonebar-row">
            <div class="mc-phonebar-left">
              <div class="mc-metric">{{ t('messages.phonebar.channels') }} <strong>0/0</strong></div>
              <div class="mc-metric">{{ t('messages.phonebar.contacts') }} <strong>0/0/0</strong></div>
            </div>
            <div class="mc-phonebar-right">
              <div class="mc-node-model"><strong>{{ t('common.offline') }}</strong></div>
              <span class="mc-node-led status-disconnected"></span>
              <div class="mc-node-name"><strong>{{ t('common.offline') }}</strong></div>
            </div>
          </div>
          </header>
        </template>

        <template #workspace-header>
          <header class="mc-workspace-header">
            <div class="mc-workspace-copy">
              <h2 class="mc-workspace-title">{{ t('connect.welcome.title') }}</h2>
              <p class="mc-workspace-subtitle">{{ t('connect.welcome.subtitle') }}</p>
            </div>
          </header>
        </template>

        <template #workspace-body>
          <div class="mc-workspace-empty">
            <h3>{{ t('connect.workspace.title') }}</h3>
            <p>{{ t('connect.workspace.subtitle') }}</p>
          </div>
        </template>
      </ShellPageFrame>
    </div>

    <div class="mc-overlay" @click.self>
      <NodeConnectPanel page-mode @connected="router.replace('/messages')" />
    </div>
  </div>
</template>
