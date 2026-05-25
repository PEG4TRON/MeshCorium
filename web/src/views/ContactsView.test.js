import { shallowMount } from '@vue/test-utils'
import { computed, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routerPush = vi.fn()
const routerReplace = vi.fn()
const routeMock = { name: 'contacts', query: {}, params: {}, path: '/contacts' }

const sessionMock = {
  connected: false,
  contacts: [],
  channels: [],
  unreadSummary: {
    channel_unread_counts: {},
    contact_unread_counts: {},
  },
  browserUnreadTotals: {
    unread: 0,
  },
  settingsPayload: {
    settings: {},
  },
  activeConnectionKey: '',
  activeConfigBody: {},
  device: null,
  self: null,
  selectedSavedConnection: null,
  statusError: false,
  statusText: '',
  loadingContacts: false,
  loadContacts: vi.fn(),
  api: vi.fn(),
  setStatus: vi.fn(),
}

vi.mock('vue-router', () => ({
  useRoute: () => routeMock,
  useRouter: () => ({ push: routerPush, replace: routerReplace }),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key, params) => (params ? `${key}:${JSON.stringify(params)}` : key) }),
}))

vi.mock('../composables/useIsMobile', () => ({
  useIsMobile: () => ({ isMobile: ref(true) }),
}))

vi.mock('../stores/session', () => ({
  useSessionStore: () => sessionMock,
}))

const { default: ContactsView } = await import('./ContactsView.vue')

function mountContactsView() {
  return shallowMount(ContactsView, {
    global: {
      stubs: {
        MobileContactsShell: {
          template: '<div class="mobile-contacts-shell"><slot name="dock" /></div>',
        },
        MobileDockButton: {
          props: ['label', 'badge', 'active', 'icon'],
          emits: ['click'],
          template: '<button class="mobile-dock-button" :data-label="label" :data-badge="badge" @click="$emit(\'click\')"><slot />{{ label }}</button>',
        },
      },
    },
  })
}

describe('ContactsView mobile dock unread badge', () => {
  beforeEach(() => {
    routerPush.mockClear()
    routerReplace.mockClear()
    routeMock.name = 'contacts'
    routeMock.path = '/contacts'
    routeMock.query = { group: 'favorites', search: 'node' }
    sessionMock.unreadSummary = {
      channel_unread_counts: { 'channel:0': 4 },
      contact_unread_counts: {
        'aaaaaaaaaaaa': 10,
        'bbbbbbbbbbbb': 3,
      },
    }
    sessionMock.browserUnreadTotals = {
      unread: 7,
    }
  })

  it('uses the audible unread total from the session store instead of raw unread maps', () => {
    const wrapper = mountContactsView()

    const notificationsButton = wrapper.find('[data-label="Notif"]')

    expect(notificationsButton.exists()).toBe(true)
    expect(notificationsButton.attributes('data-badge')).toBe('7')
  })

  it('opens notifications as an overlay on the current contacts route instead of navigating to messages', async () => {
    const wrapper = mountContactsView()

    await wrapper.find('[data-label="Notif"]').trigger('click')

    expect(routerPush).not.toHaveBeenCalledWith('/messages')
    expect(routerReplace).toHaveBeenCalledWith({
      path: '/contacts',
      query: { group: 'favorites', search: 'node', panel: 'notifications' },
    })
  })
})
