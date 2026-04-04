import { createRouter, createWebHistory } from 'vue-router'

import ConnectedShellLayout from '../components/layout/ConnectedShellLayout.vue'
import ConnectView from '../views/ConnectView.vue'
import ContactsView from '../views/ContactsView.vue'
import MapsView from '../views/MapsView.vue'
import MessagesView from '../views/MessagesView.vue'
import SettingsView from '../views/SettingsView.vue'

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
          path: 'settings/:section?/:subsection?',
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
