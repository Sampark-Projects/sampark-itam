<!--
  - ApplicationDetail.vue
  - One application: overview (identity, ownership, access) and security, compliance and backup.
  - Infrastructure (assets and network), software and integrations, topology, VAPT and findings, security governance.
-->
<template>
  <div class="application-detail">
    <div class="page-header">
      <div class="title">
        <Button icon="pi pi-arrow-left" text rounded :aria-label="t('applications.back')" @click="router.push('/applications')" />
        <h1>
          <template v-if="app">{{ app.name }} <small class="code">{{ app.code }}</small></template>
        </h1>
      </div>
      <div v-if="app" class="flex gap-2">
        <Button v-if="canWrite('applications')" :label="t('applications.edit')" icon="pi pi-pencil" outlined @click="formOpen = true" />
        <Button v-if="canDelete('applications')" :label="t('applications.delete')" icon="pi pi-trash" severity="danger" outlined @click="remove" />
      </div>
    </div>

    <Message v-if="error" severity="error" :closable="false">{{ error }}</Message>
    <div v-if="loading" class="loading"><i class="pi pi-spin pi-spinner"></i></div>

    <TabView v-if="app" lazy class="modern-tabs">
      <TabPanel :header="t('applications.tabs.overview')">
        <div class="cards">
          <section class="card">
            <h3>{{ t('applications.cards.identity') }}</h3>
            <dl>
              <dt>{{ t('applications.fields.code') }}</dt><dd>{{ app.code }}</dd>
              <dt>{{ t('applications.fields.name') }}</dt><dd>{{ app.name }}</dd>
              <dt>{{ t('applications.fields.tier') }}</dt>
              <dd><Tag v-if="app.tier" :value="t(`applications.tiers.${app.tier}`)" :severity="tierSeverity(app.tier)" /><template v-else>{{ none }}</template></dd>
              <dt>{{ t('applications.fields.lifecycleStatus') }}</dt><dd>{{ t(`applications.statuses.${app.lifecycle_status}`) }}</dd>
              <dt>{{ t('applications.fields.businessOwner') }}</dt><dd>{{ app.business_owner || none }}</dd>
              <dt>{{ t('applications.fields.technicalOwner') }}</dt><dd>{{ app.technical_owner || none }}</dd>
              <dt>{{ t('applications.fields.site') }}</dt><dd>{{ app.site_name || none }}</dd>
              <dt v-if="app.description">{{ t('applications.fields.description') }}</dt><dd v-if="app.description" class="pre">{{ app.description }}</dd>
            </dl>
          </section>
          <section class="card">
            <h3>{{ t('applications.cards.access') }}</h3>
            <dl>
              <dt>{{ t('applications.fields.primaryUrl') }}</dt>
              <dd><a v-if="app.primary_url" :href="app.primary_url" target="_blank" rel="noopener noreferrer">{{ app.primary_url }}</a><template v-else>{{ none }}</template></dd>
              <dt>{{ t('applications.fields.secondaryUrl') }}</dt>
              <dd><a v-if="app.secondary_url" :href="app.secondary_url" target="_blank" rel="noopener noreferrer">{{ app.secondary_url }}</a><template v-else>{{ none }}</template></dd>
              <dt>{{ t('applications.fields.authentication') }}</dt><dd>{{ app.authentication_method || none }}</dd>
              <dt>{{ t('applications.fields.dnsRecords') }}</dt><dd class="pre">{{ app.dns_records || none }}</dd>
              <dt>{{ t('applications.fields.sslExpiry') }}</dt>
              <dd>
                <template v-if="app.ssl_expiry_date">{{ formatDate(app.ssl_expiry_date) }}
                  <Tag :value="t(`applications.ssl.${app.ssl_state}`)" :severity="sslSeverity(app.ssl_state)" class="chip" /></template>
                <template v-else>{{ none }}</template>
              </dd>
            </dl>
          </section>
        </div>
      </TabPanel>
      <TabPanel :header="t('applications.tabs.infrastructure')">
        <ApplicationInfrastructureTab :application-id="app.id" />
      </TabPanel>
      <TabPanel :header="t('applications.tabs.software')">
        <ApplicationSoftwareTab :application-id="app.id" />
      </TabPanel>
      <TabPanel :header="t('applications.tabs.topology')">
        <ApplicationTopologyTab :application-id="app.id" />
      </TabPanel>
      <TabPanel :header="t('applications.tabs.vapt')">
        <ApplicationSecurityTab :application-id="app.id" />
      </TabPanel>
      <TabPanel :header="t('applications.tabs.security')">
        <section class="card">
          <h3>{{ t('applications.cards.governance') }}</h3>
          <dl>
            <dt>{{ t('applications.fields.classification') }}</dt>
            <dd>{{ app.data_classification ? t(`applications.classifications.${app.data_classification}`) : none }}</dd>
            <dt>{{ t('applications.fields.firewallRules') }}</dt><dd class="pre">{{ app.firewall_rule_ids || none }}</dd>
            <dt>{{ t('applications.fields.backupPolicy') }}</dt><dd class="pre">{{ app.backup_policy || none }}</dd>
            <dt>{{ t('applications.fields.rpo') }}</dt><dd>{{ app.rpo_hours ?? none }}</dd>
            <dt>{{ t('applications.fields.rto') }}</dt><dd>{{ app.rto_hours ?? none }}</dd>
            <dt>{{ t('applications.fields.lastScanDate') }}</dt><dd>{{ app.last_scan_date ? formatDate(app.last_scan_date) : none }}</dd>
            <dt>{{ t('applications.fields.lastScanResult') }}</dt><dd>{{ app.last_scan_result || none }}</dd>
          </dl>
        </section>
      </TabPanel>
    </TabView>

    <p v-if="app" class="meta">
      {{ t('applications.fields.createdBy') }}: {{ app.created_by || none }} · {{ t('applications.fields.updated') }}: {{ formatDate(app.updated_at) }}
    </p>

    <ApplicationForm v-model:visible="formOpen" :application="app" @saved="onSaved" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import ApplicationForm from '../components/forms/ApplicationForm.vue'
import ApplicationInfrastructureTab from '../components/features/applications/ApplicationInfrastructureTab.vue'
import ApplicationSoftwareTab from '../components/features/applications/ApplicationSoftwareTab.vue'
import ApplicationTopologyTab from '../components/features/applications/ApplicationTopologyTab.vue'
import ApplicationSecurityTab from '../components/features/applications/ApplicationSecurityTab.vue'
import { usePermissions } from '../composables/usePermissions'
import { useDateFormatter } from '../composables/useDateFormatter'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const { canWrite, canDelete } = usePermissions()
const { formatDate } = useDateFormatter()

const app = ref(null)
const loading = ref(false)
const error = ref('')
const formOpen = ref(false)
const none = computed(() => t('applications.none'))

const tierSeverity = v => ({ tier1: 'danger', tier2: 'warning', tier3: 'info', tier4: 'secondary' }[v])
const sslSeverity = v => ({ valid: 'success', expiring: 'warning', expired: 'danger' }[v])

async function load() {
  loading.value = true
  error.value = ''
  try {
    app.value = (await api.getApplication(route.params.id)).data
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    loading.value = false
  }
}

function onSaved(updated) {
  app.value = updated
}

async function remove() {
  if (!window.confirm(t('applications.deleteConfirm', { name: app.value.name }))) return
  try {
    await api.deleteApplication(app.value.id)
    router.push('/applications')
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

onMounted(load)
</script>

<style scoped>
.title { display: flex; align-items: center; gap: 0.5rem; }
.code { color: var(--sk-text-muted, #6b7a71); font-weight: 400; font-size: 0.9rem; margin-left: 0.5rem; }
.loading { padding: 2rem; text-align: center; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(22rem, 1fr)); gap: 1rem; }
.card { border: 1px solid var(--sk-border, #e1e7e3); border-radius: 8px; padding: 1rem 1.25rem; background: var(--sk-surface, #fff); }
.card h3 { margin: 0 0 0.75rem; font-size: 1rem; }
dl { display: grid; grid-template-columns: 11rem 1fr; gap: 0.5rem 1rem; margin: 0; }
dt { color: var(--sk-text-muted, #6b7a71); }
dd { margin: 0; overflow-wrap: anywhere; }
dd.pre { white-space: pre-line; }
.pre { white-space: pre-wrap; }
.chip { margin-left: 0.4rem; }
.meta { margin-top: 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
@media (max-width: 640px) { dl { grid-template-columns: 1fr; } }
</style>
