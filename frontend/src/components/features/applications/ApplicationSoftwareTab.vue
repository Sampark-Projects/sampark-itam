<!--
  - ApplicationSoftwareTab.vue
  - Software and dependencies: the software inventory of the linked assets (read only here) and the
  - systems the application is connected to (upstream and downstream integrations).
-->
<template>
  <TabView lazy class="sub-tabs">
    <TabPanel :header="t('applications.subtabs.installed')">
      <p class="hint">{{ t('applications.software.hint') }}</p>
      <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
      <div v-if="loading" class="loading"><i class="pi pi-spin pi-spinner"></i></div>
      <table v-else-if="rows.length" class="app-table">
        <thead>
          <tr>
            <th>{{ t('applications.software.host') }}</th><th>{{ t('applications.software.name') }}</th><th>{{ t('applications.software.kind') }}</th>
            <th>{{ t('applications.software.version') }}</th><th>{{ t('applications.software.installPath') }}</th>
            <th>{{ t('applications.software.licenseType') }}</th><th>{{ t('applications.software.licenceExpiry') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in rows" :key="s.id">
            <td>{{ s.host }}<small class="muted block">{{ t(`applications.roles.${s.role}`) }}</small></td>
            <td>{{ s.name }}<small v-if="s.vendor" class="muted block">{{ s.vendor }}</small></td>
            <td>{{ t(`assets.software.kinds.${s.kind}`) }}</td>
            <td>{{ s.version || none }}</td>
            <td class="mono">{{ s.install_path || none }}</td>
            <td>{{ s.license_type || none }}</td>
            <td>{{ s.licence_expiry_date ? formatDate(s.licence_expiry_date) : none }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">{{ t('applications.software.empty') }} {{ t('applications.software.noAssets') }}</p>
    </TabPanel>

    <TabPanel :header="t('applications.subtabs.integrations')">
      <ApplicationIntegrationsTab :application-id="applicationId" @changed="emit('changed')" />
    </TabPanel>
  </TabView>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import Message from 'primevue/message'
import api from '@/api/api'
import ApplicationIntegrationsTab from './ApplicationIntegrationsTab.vue'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({ applicationId: { type: String, required: true } })
const emit = defineEmits(['changed'])
const { t } = useI18n()
const { formatDate } = useDateFormatter()
const none = computed(() => t('applications.none'))

const rows = ref([])
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  try {
    rows.value = (await api.getApplicationSoftware(props.applicationId)).data || []
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.loading { padding: 1.5rem; text-align: center; }
.app-table { width: 100%; border-collapse: collapse; }
.app-table th, .app-table td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--sk-border, #e1e7e3); vertical-align: top; }
.app-table th { font-weight: 600; font-size: 0.85rem; color: var(--sk-text-muted, #6b7a71); white-space: nowrap; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.9rem; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.block { display: block; }
</style>
