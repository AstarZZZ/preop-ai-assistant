<script setup>
import { computed, provide, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import AppHeader from './components/AppHeader.vue'
import AppFooter from './components/AppFooter.vue'
import SettingsDrawer from './components/SettingsDrawer.vue'

const route = useRoute()
const settingsOpen = ref(false)
const toast = ref(null)
let toastTimer

function notify(message, tone = 'success') {
  toast.value = { message, tone }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 3200)
}

provide('openSettings', () => { settingsOpen.value = true })
provide('notify', notify)

const immersive = computed(() => route.name === 'record')
</script>

<template>
  <div class="app-shell" :class="{ 'is-recording-view': immersive }">
    <AppSidebar />
    <main class="app-main">
      <AppHeader v-if="route.name !== 'meeting'" />
      <div v-if="toast" class="toast" :class="toast.tone" role="status">{{ toast.message }}</div>
      <RouterView />
      <AppFooter />
    </main>
    <SettingsDrawer v-model:open="settingsOpen" />
  </div>
</template>
