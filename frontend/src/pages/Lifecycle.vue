<!--
  - Lifecycle.vue
  - OT lifecycle overview: expiring warranty / AMC / support / licence, vendor obsolescence,
  - the vendor end-of-life table, cost of ownership and the alert settings.
-->
<template>
  <div class="lifecycle-page">
    <div class="page-header">
      <h1>{{ t('lifecycle.title') }}</h1>
    </div>

    <TabView lazy class="modern-tabs">
      <TabPanel :header="t('workflows.tabs.tasks')">
        <LifecycleTasksTab />
      </TabPanel>
      <TabPanel :header="t('workflows.tabs.runs')">
        <LifecycleRunsTab />
      </TabPanel>
      <TabPanel :header="t('procurement.tab')">
        <PurchaseRequestsTab />
      </TabPanel>
      <TabPanel :header="t('lifecycle.tabs.expiring')">
        <LifecycleExpiringTab />
      </TabPanel>
      <TabPanel :header="t('lifecycle.tabs.obsolescence')">
        <LifecycleObsolescenceTab />
      </TabPanel>
      <TabPanel :header="t('lifecycle.tabs.vendor')">
        <LifecycleVendorTab />
      </TabPanel>
      <TabPanel :header="t('lifecycle.tabs.cost')">
        <LifecycleCostTab />
      </TabPanel>
      <TabPanel :header="t('lifecycle.tabs.settings')">
        <LifecycleSettingsTab />
      </TabPanel>
      <TabPanel :header="t('workflows.tabs.setup')">
        <LifecycleWorkflowSetupTab />
      </TabPanel>
    </TabView>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import LifecycleExpiringTab from '../components/features/lifecycle/LifecycleExpiringTab.vue'
import LifecycleObsolescenceTab from '../components/features/lifecycle/LifecycleObsolescenceTab.vue'
import LifecycleVendorTab from '../components/features/lifecycle/LifecycleVendorTab.vue'
import LifecycleCostTab from '../components/features/lifecycle/LifecycleCostTab.vue'
import LifecycleSettingsTab from '../components/features/lifecycle/LifecycleSettingsTab.vue'
import LifecycleTasksTab from '../components/features/lifecycle/LifecycleTasksTab.vue'
import LifecycleRunsTab from '../components/features/lifecycle/LifecycleRunsTab.vue'
import LifecycleWorkflowSetupTab from '../components/features/lifecycle/LifecycleWorkflowSetupTab.vue'
import PurchaseRequestsTab from '../components/features/lifecycle/PurchaseRequestsTab.vue'

const { t } = useI18n()
</script>

<style scoped>
.lifecycle-page { padding: 0; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
.page-header h1 { margin: 0; }
</style>
