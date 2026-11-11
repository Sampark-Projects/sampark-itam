<template>
  <nav :class="['modern-sidebar', { collapsed }]">
    <div class="sidebar-header">
      <img src="@/static/sampark_logo.png" alt="Sampark" class="logo" v-if="!collapsed" />
      <img src="@/static/sampark_icon.png" alt="Sampark" class="logo-icon" v-else />
      <button class="collapse-btn" @click="collapsed = !collapsed">
        <i :class="collapsed ? 'pi pi-angle-right' : 'pi pi-angle-left'"></i>
      </button>
    </div>
    
    <div class="sidebar-sections">
      <div v-for="section in menuSections" :key="section.label" class="sidebar-section">
        <!-- Same accordion in the narrow sidebar: the group row shrinks to just its chevron
             (hover shows the group name) and only the open group lists its item icons -->
        <button
          type="button"
          :class="['section-title', { open: isOpen(section) }]"
          :aria-expanded="isOpen(section)"
          :title="section.label"
          @click="toggleSection(section.label)"
        >
          <span class="section-label">{{ section.label }}</span>
          <i :class="['pi', 'section-chevron', isOpen(section) ? 'pi-chevron-down' : 'pi-chevron-right']"></i>
        </button>
        <template v-if="isOpen(section)">
          <router-link v-for="item in section.items" :key="item.label" :to="item.to" class="sidebar-link" :title="item.label">
            <i :class="['pi', item.icon, 'sidebar-icon']"></i>
            <span v-if="!collapsed">{{ item.label }}</span>
          </router-link>
        </template>
      </div>
    </div>
    <div class="sidebar-logout">
      <router-link to="/logout" class="sidebar-link logout-link" :title="t('menu.navigation.logout')">
        <i class="pi pi-sign-out sidebar-icon"></i>
        <span v-if="!collapsed">{{ t('menu.navigation.logout') }}</span>
      </router-link>
    </div>
  </nav>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { usePermissions } from '@/composables/usePermissions'
import { useTenantFeatures } from '@/composables/useTenantFeatures'
import { useAuthStore } from '@/store/auth'

const { t } = useI18n()
const router = useRouter()
const collapsed = ref(false)
const { canRead, userPermissions, accessibleSections, refreshUserPermissions } = usePermissions()
const { isIec62443Enabled } = useTenantFeatures()
const authStore = useAuthStore()

const menuSections = computed(() => {
  const sections = []

  // Sezione Dashboard (sempre prima)
  sections.push({
    label: 'Dashboard',
    items: [
      { label: t('menu.navigation.dashboard'), icon: 'pi-chart-bar', to: '/' }
    ]
  })

  // Sezione Inventario (prima di Gestione)
  const inventoryItems = []
  if (canRead('sites')) inventoryItems.push({ label: t('menu.navigation.sites'), icon: 'pi-building', to: '/sites' })
  if (canRead('areas')) inventoryItems.push({ label: t('menu.navigation.areas'), icon: 'pi-sitemap', to: '/areas' })
  if (canRead('locations')) inventoryItems.push({ label: t('menu.navigation.locations'), icon: 'pi-map', to: '/locations' })
  if (canRead('suppliers')) inventoryItems.push({ label: t('menu.navigation.suppliers'), icon: 'pi-briefcase', to: '/suppliers' })
  if (canRead('manufacturers')) inventoryItems.push({ label: t('menu.navigation.manufacturers'), icon: 'pi-cog', to: '/manufacturers' })
  if (canRead('contacts')) inventoryItems.push({ label: t('menu.navigation.contacts'), icon: 'pi-id-card', to: '/contacts' })
  if (canRead('assets')) inventoryItems.push({ label: t('menu.navigation.assets'), icon: 'pi-server', to: '/assets' })

  // Network Probes
  if (canRead('network_probes')) {
    inventoryItems.push({
      label: t('menu.navigation.networkProbes'),
      icon: 'pi pi-sitemap',
      to: '/network-probes'
    })
    inventoryItems.push({
      label: t('menu.navigation.discoveredDevices'),
      icon: 'pi pi-search',
      to: '/discovered-devices'
    })
  }
  
  if (inventoryItems.length > 0) {
    sections.push({
      label: t('menu.section.registry'),
      items: inventoryItems
    })
  }

  // Sezione ISA/IEC 62443 (opzionale per tenant)
  const isa62443Items = []
  if (isIec62443Enabled.value) {
    if (canRead('security_zones')) isa62443Items.push({ label: t('menu.navigation.securityZones'), icon: 'pi-shield', to: '/security-zones' })
    if (canRead('compliance')) isa62443Items.push({ label: t('menu.navigation.conduits'), icon: 'pi-link', to: '/conduits' })
    if (canRead('compliance')) isa62443Items.push({ label: t('menu.navigation.compliance'), icon: 'pi-check-circle', to: '/compliance' })
  }
  
  if (isa62443Items.length > 0) {
    sections.push({
      label: t('menu.section.isa62443'),
      items: isa62443Items
    })
  }

  // Sezione Management
  const managementItems = []
  if (canRead('asset_reviews')) managementItems.push({ label: t('menu.navigation.assetReviews'), icon: 'pi-calendar', to: '/asset-reviews' })
  if (canRead('vulnerabilities')) managementItems.push({ label: t('menu.navigation.vulnerabilities'), icon: 'pi-exclamation-triangle', to: '/vulnerabilities' })
  if (canRead('asset_types')) managementItems.push({ label: t('menu.navigation.assettypes'), icon: 'pi-tags', to: '/asset-types' })
  if (canRead('asset_statuses')) managementItems.push({ label: t('menu.navigation.assetstatuses'), icon: 'pi-list', to: '/asset-statuses' })
  
  if (managementItems.length > 0) {
    sections.push({
      label: t('menu.section.management'),
      items: managementItems
    })
  }

  // Sezione Users rimossa - ora accessibile dal Setup

  // Sezione Utility
  const utilityItems = []
  utilityItems.push({ label: t('menu.navigation.networkMap'), icon: 'pi-sitemap', to: '/network-map' }) // Mappa di rete
  utilityItems.push({ label: t('menu.navigation.profile'), icon: 'pi-user', to: '/profile' }) // Profilo sempre visibile
  if (canRead('notifications')) utilityItems.push({ label: t('menu.navigation.notifications'), icon: 'pi-bell', to: '/notifications' })
  if (canRead('utility')) utilityItems.push({ label: t('menu.navigation.pcap'), icon: 'pi-upload', to: '/utility' })
  if (canRead('audit_logs')) utilityItems.push({ label: t('menu.navigation.auditLogs'), icon: 'pi-history', to: '/audit-logs' })
  
  if (utilityItems.length > 0) {
    sections.push({
      label: t('menu.navigation.utility'),
      items: utilityItems
    })
  }

  // Sezione Setup (solo per admin)
  if (canRead('users')) {
    sections.push({
      label: t('menu.navigation.setup'),
      items: [
        { label: t('menu.navigation.setup'), icon: 'pi-wrench', to: '/setup' }
      ]
    })
  }

  return sections
})

// --- Accordion: only one section is expanded at a time ---
const route = useRoute()
// undefined = not decided yet, null = the user collapsed everything, otherwise a section label
const openSection = ref(undefined)

const isRouteActive = (to) =>
  to === '/' ? route.path === '/' : route.path === to || route.path.startsWith(to + '/')
const sectionHasActiveRoute = (section) => section.items.some(item => isRouteActive(item.to))

// Only one group is open at a time, in the wide and in the icon-only sidebar alike
const isOpen = (section) => openSection.value === section.label

function toggleSection(label) {
  // Opening a section replaces the previously open one, which collapses it
  openSection.value = openSection.value === label ? null : label
}

// Navigating (link, dashboard card, browser back...) opens the section of the new page
watch(() => route.path, () => {
  const section = menuSections.value.find(sectionHasActiveRoute)
  if (section) openSection.value = section.label
}, { immediate: true })

// Menu items depend on permissions that load asynchronously: pick the initial section
// once they exist (the current page's section, else the first one)
watch(menuSections, (sections) => {
  const stillExists = sections.some(s => s.label === openSection.value)
  if (openSection.value === undefined || (openSection.value !== null && !stillExists)) {
    const section = sections.find(sectionHasActiveRoute) || sections[0]
    openSection.value = section ? section.label : undefined
  }
}, { immediate: true })
</script>

<style scoped>
.modern-sidebar {
  width: 260px;
  position: sticky;
  top: 0;
  align-self: flex-start;
  flex-shrink: 0;
  height: 100vh;
  overflow: hidden;
  z-index: 900; /* above the full-page loader (800), below dialogs and toasts (1000+) */
  background: #ffffff;
  color: #374151;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: width 0.2s;
  border-right: 1px solid #e5e7eb;
}
.modern-sidebar.collapsed {
  width: 70px;
}
.sidebar-header {
  display: flex;
  align-items: center;
  padding: 1rem 1.2rem;
  gap: 0.7rem;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}
.logo {
  width: 150px;
  height: auto;
}
.logo-icon {
  width: 28px;
  height: 28px;
}
.modern-sidebar.collapsed .sidebar-header {
  flex-direction: column;
  padding: 1rem 0;
  gap: 0.5rem;
}
.modern-sidebar.collapsed .collapse-btn {
  margin-left: 0;
}
.app-title {
  font-size: 1.3rem;
  font-weight: bold;
  letter-spacing: 1px;
}
.collapse-btn {
  background: none;
  border: none;
  color: #4b5563;
  margin-left: auto;
  font-size: 1.2rem;
  cursor: pointer;
}
.collapse-btn:hover {
  color: #1d6838;
}
.sidebar-sections {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0;
  margin-top: 0.5rem;
  padding-bottom: 1rem;
  min-height: 0;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #cbd5e1 transparent;
}
.sidebar-section {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}
/* Group row: plain label (no icon) with a chevron on the right */
.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  background: none;
  border: none;
  text-align: left;
  cursor: pointer;
  font-family: inherit;
  font-size: 0.95rem;
  font-weight: 500;
  color: #2d4a3b;
  margin: 0;
  padding: 0.9rem 1.25rem;
  text-transform: none;
  letter-spacing: 0;
  transition: background 0.15s, color 0.15s;
}
.section-title:hover {
  background: #f3f6f4;
}
.section-title.open {
  color: #1d6838;
  font-weight: 600;
}
.section-chevron {
  font-size: 0.8rem;
  color: #6b7d73;
}
.sidebar-link {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  margin: 0 0.75rem;
  padding: 0.6rem 0.9rem 0.6rem 1.1rem;
  color: #3a4f43;
  text-decoration: none;
  border-radius: 8px;
  transition: background 0.15s, color 0.15s;
  font-size: 0.9rem;
}
.sidebar-link:hover {
  background: #f1f5f3;
  color: #1d6838;
}
.sidebar-link.router-link-exact-active {
  background: #e8f0eb;
  color: #1d6838;
  font-weight: 600;
}
.sidebar-icon {
  font-size: 1.1rem;
  min-width: 1.1rem;
  text-align: center;
  color: #6b7d73;
}
.sidebar-link:hover .sidebar-icon,
.sidebar-link.router-link-exact-active .sidebar-icon {
  color: #1d6838;
}
.sidebar-logout {
  flex-shrink: 0;
  padding: 0.75rem 0;
  border-top: 1px solid #e5e7eb;
}
.logout-link {
  color: #dc2626;
}
.logout-link:hover {
  background: #fef2f2;
  color: #b91c1c;
}

/* Screen reader only class */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.modern-sidebar.collapsed .app-title,
.modern-sidebar.collapsed .section-label,
.modern-sidebar.collapsed .sidebar-link span {
  display: none;
}
/* Narrow sidebar: each group is a thin row with only its chevron, centred */
.modern-sidebar.collapsed .section-title {
  justify-content: center;
  padding: 0.7rem 0;
  border-top: 1px solid #eef2ef;
}
.modern-sidebar.collapsed .sidebar-section:first-child .section-title {
  border-top: 0;
}
.modern-sidebar.collapsed .sidebar-link {
  justify-content: center;
  margin: 0 0.4rem;
  padding-left: 0.5rem;
  padding-right: 0.5rem;
}
</style> 