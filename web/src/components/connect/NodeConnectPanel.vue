<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import LocaleSwitch from '../ui/LocaleSwitch.vue'
import PluginDropdown from '../ui/PluginDropdown.vue'
import { resolveNodePreviewUrl } from '../../lib/nodePreview'
import { useSessionStore } from '../../stores/session'

const props = defineProps({
  pageMode: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['connected'])

const { t } = useI18n()
const session = useSessionStore()

const baudrateOptions = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
const brandLogoUrl = '/icons/Meshcorium3.png'

const selectedPortLabel = computed(() => {
  const match = session.ports.find((entry) => String(entry?.transport_id || entry?.device || '') === String(session.selectedPort || ''))
  return match
    ? `${match.transport_id || match.device} | ${match.description || t('common.unknown')}`
    : t('connect.status.portNotSelected')
})

const portOptions = computed(() => {
  return session.ports.map((entry) => ({
    value: String(entry?.transport_id || entry?.device || ''),
    label: String(entry?.transport_id || entry?.device || ''),
    meta: String(entry?.description || t('common.unknown')),
    triggerLabel: `${entry?.transport_id || entry?.device || ''} | ${entry?.description || t('common.unknown')}`,
  }))
})

const baudrateDropdownOptions = computed(() => {
  return baudrateOptions.map((baudrate) => ({
    value: baudrate,
    label: String(baudrate),
  }))
})

function resolveSavedConnectionDisplayName(profile) {
  const nodeName = String(profile?.node_name || '').trim()
  if (nodeName) {
    return nodeName
  }
  const manufacturerModel = String(profile?.manufacturer_model || '').trim()
  if (manufacturerModel) {
    return manufacturerModel
  }
  return resolveSavedConnectionPort(profile)
}

function resolveSavedConnectionModelName(profile) {
  const manufacturerModel = String(profile?.manufacturer_model || '').trim()
  if (manufacturerModel) {
    return manufacturerModel
  }
  const nodeName = String(profile?.node_name || '').trim()
  if (nodeName) {
    return nodeName
  }
  return t('common.unknownNode')
}

function resolveSavedConnectionPreviewLabel(profile) {
  return String(
    profile?.manufacturer_model
    || profile?.node_name
    || profile?.port
    || ''
  ).trim()
}

function resolveSavedConnectionPort(profile) {
  return String(profile?.connection?.transport_id || profile?.transport_id || profile?.port || '').trim()
}

async function connectNode() {
  try {
    const payload = await session.connectNode({ light: true })
    emit('connected', payload)
  } catch (error) {
    session.setStatus(error instanceof Error ? error.message : String(error || t('connect.status.connectFailed')), true)
  }
}

function pickSavedConnection(profile) {
  session.selectedPort = resolveSavedConnectionPort(profile)
  session.selectedBaudrate = Number(profile?.connection?.baudrate || profile?.baudrate || session.DEFAULT_BAUDRATE) || session.DEFAULT_BAUDRATE
}
</script>

<template>
  <section class="mc-connect-float" :class="{ 'mc-connect-float--page': pageMode }">
    <div class="mc-connect-float-hero">
      <img :src="brandLogoUrl" alt="Meshcorium" />
      <div>
        <p class="mc-overline">{{ t('connect.welcome.title') }}</p>
        <h2>{{ t('connect.workspace.title') }}</h2>
        <p>{{ t('connect.float.subtitle') }}</p>
      </div>
      <div class="mc-connect-float-locale">
        <LocaleSwitch compact vertical />
      </div>
    </div>

    <div v-if="session.connectNotice" class="mc-connect-alert" :class="{ 'is-error': session.connectNotice.isError }">
      {{ session.connectNotice.message }}
    </div>

    <div class="mc-connect-float-layout">
      <div class="mc-connect-float-stack">
        <div class="mc-connect-float-card">
          <div class="mc-connect-float-primary">
            <button class="mc-button mc-button--primary mc-button--wide" type="button" :disabled="session.connecting" @click="connectNode">
              {{ session.connecting ? t('connect.actions.connecting') : t('connect.actions.connect') }}
            </button>
            <button
              v-tooltip="{ content: t('common.refreshPorts'), theme: 'meshcorium-tooltip' }"
              class="mc-icon-button"
              type="button"
              :aria-label="t('common.refreshPorts')"
              @click="session.refreshPorts()"
            >
              ↻
            </button>
          </div>

          <label class="mc-field">
            <span>{{ t('connect.fields.port') }}</span>
            <PluginDropdown
              v-model="session.selectedPort"
              :options="portOptions"
              :placeholder="t('connect.fields.selectPort')"
              :disabled="!portOptions.length"
              :min-width="280"
            />
          </label>

          <label class="mc-field">
            <span>{{ t('connect.fields.baudrate') }}</span>
            <PluginDropdown
              v-model="session.selectedBaudrate"
              :options="baudrateDropdownOptions"
              :min-width="180"
            />
          </label>

          <div class="mc-connect-meta">
            <p>{{ selectedPortLabel }}</p>
          </div>
        </div>

        <div class="mc-connect-float-note" :class="{ 'is-error': session.statusError }">{{ session.statusText }}</div>
      </div>

      <aside class="mc-connect-history-shell">
        <div class="mc-connect-history-header">
          <p class="mc-overline">{{ t('connect.history.overline') }}</p>
          <h3>{{ t('connect.history.title') }}</h3>
          <p>{{ t('connect.history.subtitle') }}</p>
        </div>
        <div class="mc-connect-history-list">
          <button
            v-for="profile in session.savedConnections"
            :key="profile.key || `${resolveSavedConnectionPort(profile)}-${profile.baudrate}-${profile.public_key || profile.node_name}`"
            class="mc-connect-history-card"
            @click="pickSavedConnection(profile)"
          >
            <div class="mc-connect-history-preview">
              <img
                v-if="resolveNodePreviewUrl(resolveSavedConnectionPreviewLabel(profile))"
                :src="resolveNodePreviewUrl(resolveSavedConnectionPreviewLabel(profile))"
                alt=""
              />
              <span v-else>◈</span>
            </div>
            <div class="mc-connect-history-main">
              <div class="mc-connect-history-top">
                <strong>{{ resolveSavedConnectionDisplayName(profile) }}</strong>
                <span class="mc-connect-history-kind">{{ profile.connection_type || t('common.usb') }}</span>
              </div>
              <div class="mc-connect-history-bottom">
                <span>{{ resolveSavedConnectionModelName(profile) }}</span>
                <span>{{ resolveSavedConnectionPort(profile) }}</span>
                <span>{{ profile.connection?.baudrate || profile.baudrate }}</span>
              </div>
            </div>
          </button>
          <div v-if="!session.savedConnections.length" class="mc-connect-history-empty">{{ t('connect.history.empty') }}</div>
        </div>
      </aside>
    </div>
  </section>
</template>
