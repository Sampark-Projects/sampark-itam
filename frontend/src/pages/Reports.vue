<!--
  - Reports.vue
  - Plant / unit / line dashboard against targets, the audit pack download and outbound webhooks.
-->
<template>
  <div class="reports-page">
    <div class="page-header">
      <h1>{{ t('reports.title') }}</h1>
    </div>

    <TabView lazy class="modern-tabs">
      <TabPanel v-if="canRead('reports')" :header="t('reports.tabs.dashboard')">
        <PlantDashboardTab />
      </TabPanel>
      <TabPanel v-if="canWrite('reports')" :header="t('reports.tabs.audit')">
        <AuditPackTab />
      </TabPanel>
      <TabPanel v-if="canRead('api_keys')" :header="t('reports.tabs.integrations')">
        <WebhooksTab />
      </TabPanel>
    </TabView>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import PlantDashboardTab from '../components/features/reports/PlantDashboardTab.vue'
import AuditPackTab from '../components/features/reports/AuditPackTab.vue'
import WebhooksTab from '../components/features/reports/WebhooksTab.vue'
import { usePermissions } from '../composables/usePermissions'

const { t } = useI18n()
const { canRead, canWrite } = usePermissions()
</script>

<style scoped>
.reports-page { padding: 0; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
.page-header h1 { margin: 0; }
</style>
