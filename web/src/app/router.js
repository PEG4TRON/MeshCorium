import { createRouter, createWebHistory } from 'vue-router'
import { defineAsyncComponent, defineComponent, h } from 'vue'

import ConnectedShellLayout from '../components/layout/ConnectedShellLayout.vue'
import ShellRouteLoadingView from '../components/layout/ShellRouteLoadingView.vue'
import ConnectView from '../views/ConnectView.vue'
function createRouteLoadingComponent(titleKey, messageKey) {
  return defineComponent({
    name: `RouteLoading${titleKey.replace(/[^a-z0-9]+/gi, '')}`,
    render() {
      return h(ShellRouteLoadingView, { titleKey, messageKey })
    },
  })
}

function createLazyRoute(loader, { titleKey, messageKey }) {
  return defineAsyncComponent({
    loader,
    delay: 0,
    suspensible: false,
    loadingComponent: createRouteLoadingComponent(titleKey, messageKey),
  })
}

const ContactsView = createLazyRoute(() => import('../views/ContactsView.vue'), {
  titleKey: 'routes.contacts',
  messageKey: 'contactsView.loading',
})
const MapsView = createLazyRoute(() => import('../views/MapsView.vue'), {
  titleKey: 'routes.maps',
  messageKey: 'maps.status.loadingSubtitle',
})
const MessagesView = createLazyRoute(() => import('../views/MessagesView.vue'), {
  titleKey: 'routes.messages',
  messageKey: 'messages.loading',
})
const SettingsView = createLazyRoute(() => import('../views/SettingsView.vue'), {
  titleKey: 'routes.settings',
  messageKey: 'settings.loading',
})

export const router = createRouter({
  history: createWebHistory('/'),
  scrollBehavior() {
    return { left: 0, top: 0 }
  },
  routes: [
    {
      path: '/',
      name: 'connect',
      component: ConnectView,
      meta: {
        titleKey: 'routes.connect',
      },
    },
    {
      path: '/connect',
      redirect: { name: 'connect' },
    },
    {
      path: '/',
      component: ConnectedShellLayout,
      children: [
        {
          path: 'contacts',
          name: 'contacts',
          component: ContactsView,
          meta: {
            titleKey: 'routes.contacts',
          },
        },
        {
          path: 'contacts/groups',
          name: 'contacts-groups',
          component: ContactsView,
          meta: {
            titleKey: 'routes.contacts',
          },
        },
        {
          path: 'contacts/repeater-login/:publicKey',
          name: 'contacts-repeater-login',
          component: ContactsView,
          meta: {
            titleKey: 'routes.contacts',
          },
        },
        {
          path: 'contacts/repeater/:publicKey/:category?',
          name: 'contacts-repeater',
          component: ContactsView,
          meta: {
            titleKey: 'routes.contacts',
          },
        },
        {
          path: 'messages',
          name: 'messages',
          component: MessagesView,
          meta: {
            titleKey: 'routes.messages',
          },
        },
        {
          path: 'maps',
          name: 'maps',
          component: MapsView,
          meta: {
            titleKey: 'routes.maps',
          },
        },
        {
          path: 'maps/route-checks',
          name: 'maps-route-checks',
          component: MapsView,
          meta: {
            titleKey: 'routes.maps',
          },
        },
        {
          path: 'settings/:section?/:subsection?/:detail?',
          name: 'settings',
          component: SettingsView,
          meta: {
            titleKey: 'routes.settings',
          },
        },
      ],
    },
  ],
})
