<!--
  - IpamServices.vue
  - Services (name + ports) of assets and FHRP groups, and the service templates that fill them in.
-->
<template>
  <div class="ipam-page">
    <div class="page-header"><h1>{{ t('ipam.services.title') }}</h1></div>
    <p class="hint">{{ t('ipam.services.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <TabView class="modern-tabs">
      <TabPanel :header="t('ipam.services.tabs.services')">
        <div class="toolbar">
          <span class="p-input-icon-left search">
            <i class="pi pi-search" />
            <InputText v-model="search" :placeholder="t('ipam.services.searchPlaceholder')" class="w-full" @input="onSearch" />
          </span>
          <span class="spacer"></span>
          <Button v-if="canWrite('ipam')" :label="t('ipam.services.new')" icon="pi pi-plus" severity="success" @click="openService(null)" />
        </div>
        <DataTable :value="services" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
                   :rowsPerPageOptions="[25, 50, 100]" @page="onPage">
          <template #empty>{{ t('ipam.services.empty') }}</template>
          <Column field="name" :header="t('ipam.services.fields.name')" />
          <Column field="ports_text" :header="t('ipam.services.fields.ports')" />
          <Column :header="t('ipam.services.fields.parent')">
            <template #body="{ data }">
              <router-link v-if="data.asset_id" :to="`/assets/${data.asset_id}`">{{ data.asset_name }}</router-link>
              <router-link v-else :to="`/ipam/fhrp-groups/${data.fhrp_group_id}`">{{ data.fhrp_group }}</router-link>
            </template>
          </Column>
          <Column :header="t('ipam.services.fields.addresses')">
            <template #body="{ data }"><span class="mono">{{ data.ip_addresses.map(a => a.address).join(', ') }}</span></template>
          </Column>
          <Column field="description" :header="t('ipam.fields.description')" />
          <Column v-if="canWrite('ipam')" style="width: 6rem">
            <template #body="{ data }">
              <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openService(data)" />
              <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeService(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>

      <TabPanel :header="t('ipam.services.tabs.templates')">
        <div class="toolbar">
          <span class="spacer"></span>
          <Button v-if="canWrite('ipam')" :label="t('ipam.services.newTemplate')" icon="pi pi-plus" severity="success" @click="openTemplate(null)" />
        </div>
        <DataTable :value="templates" dataKey="id">
          <template #empty>{{ t('ipam.services.emptyTemplates') }}</template>
          <Column field="name" :header="t('ipam.services.fields.name')" />
          <Column field="ports_text" :header="t('ipam.services.fields.ports')" />
          <Column field="description" :header="t('ipam.fields.description')" />
          <Column v-if="canWrite('ipam')" style="width: 6rem">
            <template #body="{ data }">
              <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openTemplate(data)" />
              <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeTemplate(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>
    </TabView>

    <IpamServiceForm v-model:visible="serviceOpen" :service="editingService" @saved="onServiceSaved" />

    <Dialog v-model:visible="templateOpen" modal :header="editingTemplate ? t('ipam.services.editTemplate') : t('ipam.services.newTemplate')" :style="{ width: '34rem', maxWidth: '96vw' }">
      <Message v-if="templateError" severity="error" :closable="true" @close="templateError = ''">{{ templateError }}</Message>
      <div class="p-field">
        <label>{{ t('ipam.services.fields.name') }} *</label>
        <InputText v-model="templateForm.name" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.services.fields.ports') }} *</label>
        <InputText v-model="templateForm.ports" maxlength="500" placeholder="tcp/80, tcp/443" class="w-full" />
        <small class="muted">{{ t('ipam.services.portsHint') }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.description') }}</label>
        <InputText v-model="templateForm.description" maxlength="200" class="w-full" />
      </div>
      <IpamComments v-model="templateForm.comments" />
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="templateOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="saveTemplate" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import IpamServiceForm from '../components/forms/IpamServiceForm.vue'
import { usePermissions } from '../composables/usePermissions'
import { apiErrorText } from '../utils/money'
import IpamComments from '../components/features/ipam/IpamComments.vue'

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const message = ref(null)
const saving = ref(false)

// --- services ---
const services = ref([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const rows = ref(50)
const first = ref(0)
const serviceOpen = ref(false)
const editingService = ref(null)

async function loadServices() {
  loading.value = true
  try {
    const params = { skip: first.value, limit: rows.value }
    if (search.value.trim()) params.search = search.value.trim()
    const res = await api.getIpamServices(params)
    services.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    loading.value = false
  }
}
let timer = null
function onSearch() { clearTimeout(timer); timer = setTimeout(() => { first.value = 0; loadServices() }, 300) }
function onPage(event) { first.value = event.first; rows.value = event.rows; loadServices() }
function openService(row) { editingService.value = row; serviceOpen.value = true }
function onServiceSaved() { message.value = { severity: 'success', text: t('ipam.saved') }; loadServices() }
async function removeService(row) {
  if (!window.confirm(t('ipam.services.deleteConfirm', { name: row.name }))) return
  try {
    await api.deleteIpamService(row.id)
    await loadServices()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

// --- templates ---
const templates = ref([])
const templateOpen = ref(false)
const editingTemplate = ref(null)
const templateError = ref('')
const templateForm = ref({ name: '', ports: '', description: '', comments: '' })

async function loadTemplates() {
  try { templates.value = (await api.getIpamServiceTemplates()).data || [] } catch (err) { message.value = { severity: 'error', text: apiErrorText(err, t) } }
}
function openTemplate(row) {
  editingTemplate.value = row
  templateError.value = ''
  templateForm.value = row ? { name: row.name, ports: row.ports_text, description: row.description || '', comments: row.comments || '' } : { name: '', ports: '', description: '', comments: '' }
  templateOpen.value = true
}
async function saveTemplate() {
  templateError.value = ''
  const f = templateForm.value
  if (!f.name.trim() || !f.ports.trim()) { templateError.value = t('ipam.services.required'); return }
  const body = { name: f.name.trim(), port_mappings: f.ports, description: f.description || null, comments: f.comments || null }
  saving.value = true
  try {
    if (editingTemplate.value) await api.updateIpamServiceTemplate(editingTemplate.value.id, body)
    else await api.createIpamServiceTemplate(body)
    templateOpen.value = false
    message.value = { severity: 'success', text: t('ipam.saved') }
    await loadTemplates()
  } catch (err) {
    templateError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
async function removeTemplate(row) {
  if (!window.confirm(t('ipam.services.deleteTemplateConfirm', { name: row.name }))) return
  try {
    await api.deleteIpamServiceTemplate(row.id)
    await loadTemplates()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

onMounted(() => { loadServices(); loadTemplates() })
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.toolbar .spacer { flex: 1; }
.search { flex: 1 1 16rem; max-width: 24rem; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.p-field { margin-bottom: 0.75rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
</style>
