<template>
  <div class="app-container">
    <Toast />
    <SetupDetector />
    <div v-if="auth.isAuthenticated && !isPublicPage" class="layout">
      <SidebarMenu />
      <div class="main-content">
        <router-view />
      </div>
    </div>
    <div v-else>
      <router-view />
    </div>
    <GlobalSearchSpotlight />
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from './store/auth'

import Toast from 'primevue/toast'
import SidebarMenu from './components/common/SidebarMenu.vue'
import GlobalSearchSpotlight from './components/common/GlobalSearchSpotlight.vue'
import SetupDetector from './components/SetupDetector.vue'

const auth = useAuthStore()
const route = useRoute()

// Pages shown before sign-in never get the sidebar, even if a stale saved login flag says otherwise.
const PUBLIC_PAGES = ['Login', 'MfaVerify', 'MfaSetup', 'SSOSuccess', 'SSOError']
const isPublicPage = computed(() => PUBLIC_PAGES.includes(route.name))

onMounted(async () => {
  // The saved flag survives an expired session, so always confirm it with the server.
  await auth.fetchUser()
  if (auth.isAuthenticated) {
    auth.startTokenRefresh()
  }
})
</script>

<style scoped>
.app-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.layout {
  display: flex;
  flex: 1;
  min-height: 0;
}
.main-content {
  flex: 1;
  min-width: 0;
  padding: 0.75rem 1.5rem 1.5rem;
  overflow-y: auto;
}
</style>
