<template>
  <nav class="mc-mobile-dock">
    <MobileDockButton :icon="bellIcon" label="Notif" :badge="badge" @click="$emit('notifications')" />
    <MobileDockButton :icon="messagesIcon" label="Chats" :active="true" />
    <MobileDockButton :icon="contactsIcon" label="Contacts" @click="$emit('contacts')" />
    <MobileDockButton :icon="mapIcon" label="Map" @click="$emit('maps')" />
    <MobileDockButton :icon="settingsIcon" label="Settings" @click="$emit('settings')" />
  </nav>
</template>

<script setup>
import MobileDockButton from './MobileDockButton.vue'

defineProps({
  bellIcon: { type: String, default: '/icons/bell-icon.svg' },
  messagesIcon: { type: String, default: '/icons/paper-plane.png' },
  contactsIcon: { type: String, default: '/icons/contacts-icon.svg' },
  mapIcon: { type: String, default: '/icons/map-icon.svg' },
  settingsIcon: { type: String, default: '/icons/settings-icon.svg' },
  badge: { type: [String, Number], default: '' },
})

defineEmits(['notifications', 'contacts', 'maps', 'settings'])
</script>
