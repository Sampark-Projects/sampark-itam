<!--
  - ChangesMaintenance.vue
  - Change requests, unapproved-change flags, planned maintenance, spare parts and the change settings.
-->
<template>
  <div class="changes-page">
    <div class="page-header">
      <h1>{{ t('changes.title') }}</h1>
    </div>

    <TabView lazy class="modern-tabs">
      <TabPanel v-if="canRead('changes')" :header="t('changes.tabs.changes')">
        <ChangeRequestsTab />
      </TabPanel>
      <TabPanel v-if="canRead('changes')" :header="t('changes.tabs.unapproved')">
        <UnapprovedChangesTab />
      </TabPanel>
      <TabPanel v-if="canRead('maintenance')" :header="t('changes.tabs.maintenance')">
        <MaintenanceDueTab />
      </TabPanel>
      <TabPanel v-if="canRead('maintenance')" :header="t('changes.tabs.parts')">
        <SparePartsTab />
      </TabPanel>
      <TabPanel v-if="canRead('configurations')" :header="t('configmgmt.tab')">
        <ConfigOverviewTab />
      </TabPanel>
      <TabPanel v-if="canRead('changes')" :header="t('changes.tabs.settings')">
        <ChangeSettingsTab />
      </TabPanel>
    </TabView>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import ChangeRequestsTab from '../components/features/changes/ChangeRequestsTab.vue'
import UnapprovedChangesTab from '../components/features/changes/UnapprovedChangesTab.vue'
import MaintenanceDueTab from '../components/features/changes/MaintenanceDueTab.vue'
import SparePartsTab from '../components/features/changes/SparePartsTab.vue'
import ChangeSettingsTab from '../components/features/changes/ChangeSettingsTab.vue'
import ConfigOverviewTab from '../components/features/changes/ConfigOverviewTab.vue'
import { usePermissions } from '../composables/usePermissions'

const { t } = useI18n()
const { canRead } = usePermissions()
</script>

<style scoped>
.changes-page { padding: 0; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
.page-header h1 { margin: 0; }
</style>
