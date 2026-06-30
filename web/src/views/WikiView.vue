<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import ShellPageFrame from '../components/layout/ShellPageFrame.vue'
import ShellPhonebar from '../components/layout/ShellPhonebar.vue'
import MessagesConversationSidebar from '../components/messages/MessagesConversationSidebar.vue'
import { filterStatusTextForTransport } from '../lib/statusText'
import { useSessionStore } from '../stores/session'

const { t } = useI18n()
const route = useRoute()
const session = useSessionStore()

const activeSectionId = computed(() => String(route.params.section || '').trim() || 'getting-started')

const footerStatusText = computed(() => {
  return filterStatusTextForTransport(session.statusText, session.selectedTransportType)
})

const wikiSections = [
  { id: 'getting-started', title: t('wiki.sections.gettingStarted.title'), subtitle: t('wiki.sections.gettingStarted.body') },
  { id: 'hardware', title: t('wiki.sections.hardware.title'), subtitle: t('wiki.sections.hardware.body') },
  { id: 'companion', title: t('wiki.sections.companion.title'), subtitle: t('wiki.sections.companion.body') },
  { id: 'repeater', title: t('wiki.sections.repeater.title'), subtitle: t('wiki.sections.repeater.body') },
  { id: 'faq', title: t('wiki.sections.faq.title'), subtitle: t('wiki.sections.faq.body') },
]

const activeWikiSectionTitle = computed(() => {
  const section = wikiSections.find((s) => s.id === activeSectionId.value)
  return section ? section.title : wikiSections[0].title
})

const activeWikiSectionSubtitle = computed(() => {
  const section = wikiSections.find((s) => s.id === activeSectionId.value)
  return section ? section.subtitle : wikiSections[0].subtitle
})
</script>

<template>
  <ShellPageFrame
    scroller-class="mc-sidebar--wiki"
    scroller-header-class="mc-sidebar-top--wiki"
    workspace-class="mc-content--shell-body mc-content--wiki"
  >
    <template #workspace-top>
      <ShellPhonebar />
    </template>

    <template #scroller-header>
      <div class="mc-scroller-copy mc-scroller-copy--shell-top">
        <h1 class="mc-scroller-title mc-scroller-title--shell-top">{{ t('common.wiki') }}</h1>
      </div>
    </template>

    <template #scroller-body>
      <div class="mc-list-scroll mc-list-scroll--wiki">
      </div>
    </template>

    <template #scroller-footer>
      <MessagesConversationSidebar
        section="footer"
        :status-text="footerStatusText"
        :status-error="session.statusError"
        :connected="session.connected"
      />
    </template>

    <template #workspace-header>
      <header class="mc-workspace-header mc-workspace-header--wiki">
        <div class="mc-workspace-copy">
          <h2 class="mc-workspace-title">{{ activeWikiSectionTitle }}</h2>
          <p class="mc-workspace-subtitle">{{ activeWikiSectionSubtitle }}</p>
        </div>
      </header>
    </template>

    <template #workspace-body>
      <div ref="wikiWorkspaceRef" class="mc-wiki-workspace">
        <template v-if="activeSectionId === 'getting-started'">
          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('wiki.sections.gettingStarted.title') }}</h3>
              <p>{{ t('wiki.sections.gettingStarted.body') }}</p>
            </div>
          </section>
        </template>

        <template v-else-if="activeSectionId === 'hardware'">
          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('wiki.sections.hardware.title') }}</h3>
              <p>{{ t('wiki.sections.hardware.body') }}</p>
            </div>
          </section>
        </template>

        <template v-else-if="activeSectionId === 'companion'">
          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('wiki.sections.companion.title') }}</h3>
              <p>{{ t('wiki.sections.companion.body') }}</p>
            </div>
          </section>
        </template>

        <template v-else-if="activeSectionId === 'repeater'">
          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('wiki.sections.repeater.title') }}</h3>
              <p>{{ t('wiki.sections.repeater.body') }}</p>
            </div>
          </section>
        </template>

        <template v-else-if="activeSectionId === 'faq'">
          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('wiki.sections.faq.title') }}</h3>
              <p>{{ t('wiki.sections.faq.body') }}</p>
            </div>
          </section>
        </template>

        <template v-else>
          <section class="mc-settings-panel">
            <div class="mc-settings-panel-copy">
              <h3>{{ t('wiki.sections.gettingStarted.title') }}</h3>
              <p>{{ t('wiki.sections.gettingStarted.body') }}</p>
            </div>
          </section>
        </template>
      </div>
    </template>
  </ShellPageFrame>
</template>
