<!--
  - ApplicationInfrastructureTab.vue
  - Infrastructure and hosting of an application: the assets it runs on (compute and servers) and their
  - network interfaces. Host and network details are read from the linked assets; only the role,
  - environment and listening ports belong to the link.
-->
<template>
  <div>
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <p class="hint">{{ t('applications.infra.readFromAssets') }}</p>

    <TabView lazy class="sub-tabs">
      <!-- compute -->
      <TabPanel :header="t('applications.subtabs.compute')">
        <div class="toolbar">
          <Button v-if="canWrite('applications')" :label="t('applications.infra.link')" icon="pi pi-link" size="small" @click="openLink(null)" />
        </div>
        <div v-if="loading" class="loading"><i class="pi pi-spin pi-spinner"></i></div>
        <table v-else-if="items.length" class="app-table">
          <thead>
            <tr>
              <th>{{ t('applications.infra.hostname') }}</th><th>{{ t('applications.infra.role') }}</th><th>{{ t('applications.infra.assetType') }}</th>
              <th>{{ t('applications.infra.os') }}</th><th>{{ t('applications.infra.environment') }}</th><th>{{ t('applications.infra.status') }}</th>
              <th>{{ t('applications.infra.site') }}</th><th v-if="canWrite('applications')"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in items" :key="row.id">
              <td>
                <router-link :to="`/assets/${row.asset_id}`" :title="t('applications.infra.openAsset')">{{ row.name }}</router-link>
                <Tag v-if="row.archived" :value="t('applications.infra.archived')" severity="secondary" class="chip" />
                <small v-if="row.tag" class="muted block">{{ row.tag }}</small>
                <small v-if="row.notes" class="muted block">{{ row.notes }}</small>
              </td>
              <td>{{ t(`applications.roles.${row.role}`) }}</td>
              <td>{{ row.asset_type || none }}</td>
              <td>{{ row.operating_system || none }}</td>
              <td>{{ row.environment ? t(`applications.environments.${row.environment}`) : none }}</td>
              <td>{{ row.status || none }}</td>
              <td>{{ row.site || none }}</td>
              <td v-if="canWrite('applications')" class="num">
                <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('applications.infra.editLink')" @click="openLink(row)" />
                <Button v-if="canDelete('applications')" icon="pi pi-times" text rounded size="small" severity="danger"
                        :aria-label="t('applications.infra.unlink')" @click="unlink(row)" />
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">{{ t('applications.infra.emptyCompute') }}</p>
      </TabPanel>

      <!-- network -->
      <TabPanel :header="t('applications.subtabs.network')">
        <div v-if="loading" class="loading"><i class="pi pi-spin pi-spinner"></i></div>
        <template v-else>
          <table v-if="interfaceRows.length" class="app-table">
            <thead>
              <tr>
                <th>{{ t('applications.infra.hostname') }}</th><th>{{ t('applications.infra.interface') }}</th><th>{{ t('applications.infra.ip') }}</th>
                <th>{{ t('applications.infra.vlan') }}</th><th>{{ t('applications.infra.subnet') }}</th><th>{{ t('applications.infra.gateway') }}</th>
                <th>{{ t('applications.infra.ports') }}</th><th>{{ t('applications.infra.protocols') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in interfaceRows" :key="r.key">
                <td>{{ r.host }}<Tag v-if="r.role === 'load_balancer'" :value="t('applications.infra.vip')" severity="info" class="chip" /></td>
                <td>{{ r.name || none }}</td>
                <td class="mono">{{ r.ip_address || none }}</td>
                <td>{{ r.vlan || none }}</td>
                <td class="mono">{{ r.subnet_mask || none }}</td>
                <td class="mono">{{ r.default_gateway || none }}</td>
                <td>{{ r.ports || none }}</td>
                <td>{{ (r.protocols || []).join(', ') || none }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted">{{ t('applications.infra.emptyNetwork') }}</p>
          <div v-if="dnsRecords" class="dns">
            <strong>{{ t('applications.infra.dns') }}</strong>
            <pre>{{ dnsRecords }}</pre>
          </div>
        </template>
      </TabPanel>
    </TabView>

    <!-- link dialog -->
    <Dialog v-model:visible="linkOpen" modal :header="editing ? t('applications.infra.editLink') : t('applications.infra.linkTitle')"
            :style="{ width: '36rem', maxWidth: '96vw' }">
      <Message v-if="linkError" severity="error" :closable="true" @close="linkError = ''">{{ linkError }}</Message>
      <div v-if="!editing" class="p-field">
        <label>{{ t('applications.infra.pick') }}</label>
        <InputText v-model="query" :placeholder="t('applications.infra.searchAsset')" class="w-full" @input="onSearch" />
        <ul class="results">
          <li v-for="a in results" :key="a.id" :class="{ picked: picked && picked.id === a.id }" @click="picked = a">
            <strong>{{ a.name }}</strong>
            <small class="muted"> {{ a.tag || '' }} {{ a.asset_type ? '· ' + a.asset_type : '' }}</small>
          </li>
          <li v-if="searched && !results.length" class="muted">{{ t('applications.infra.noMatch') }}</li>
        </ul>
      </div>
      <p v-else class="picked-name"><strong>{{ editing.name }}</strong></p>
      <div class="p-field">
        <label>{{ t('applications.infra.role') }}</label>
        <Dropdown v-model="link.role" :options="roleOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.infra.environment') }}</label>
        <Dropdown v-model="link.environment" :options="environmentOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.infra.ports') }}</label>
        <InputText v-model="link.listening_ports" maxlength="255" :placeholder="t('applications.infra.portsPlaceholder')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.infra.notes') }}</label>
        <Textarea v-model="link.notes" rows="2" autoResize maxlength="2000" class="w-full" />
      </div>
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="linkOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" :disabled="!editing && !picked" @click="saveLink" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import Dialog from 'primevue/dialog'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import Textarea from 'primevue/textarea'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({ applicationId: { type: String, required: true } })
const emit = defineEmits(['changed'])
const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()

const ROLES = ['web', 'application', 'database', 'load_balancer', 'cache', 'queue', 'storage', 'other']
const ENVIRONMENTS = ['production', 'dr', 'uat', 'staging', 'development']
const roleOptions = computed(() => ROLES.map(v => ({ value: v, label: t(`applications.roles.${v}`) })))
const environmentOptions = computed(() => ENVIRONMENTS.map(v => ({ value: v, label: t(`applications.environments.${v}`) })))
const none = computed(() => t('applications.none'))

const items = ref([])
const dnsRecords = ref('')
const loading = ref(false)
const error = ref('')

const interfaceRows = computed(() => items.value.flatMap(row =>
  row.interfaces.map(i => ({ ...i, key: `${row.id}-${i.id}`, host: row.name, role: row.role, ports: row.listening_ports }))))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.getApplicationInfrastructure(props.applicationId)
    items.value = res.data.items || []
    dnsRecords.value = res.data.dns_records || ''
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    loading.value = false
  }
}

// --- link dialog ---
const linkOpen = ref(false)
const editing = ref(null)
const link = ref({ role: 'other', environment: null, listening_ports: '', notes: '' })
const query = ref('')
const results = ref([])
const picked = ref(null)
const searched = ref(false)
const linkError = ref('')
const saving = ref(false)

let searchRequest = 0
async function runSearch() {
  const mine = ++searchRequest
  try {
    const res = await api.searchApplicationAssets(props.applicationId, query.value)
    if (mine === searchRequest) { results.value = res.data || []; searched.value = true }
  } catch (err) {
    if (mine === searchRequest) linkError.value = apiErrorText(err, t)
  }
}
let timer = null
function onSearch() {
  clearTimeout(timer)
  timer = setTimeout(runSearch, 300)
}

function openLink(row) {
  editing.value = row
  picked.value = null
  linkError.value = ''
  query.value = ''
  results.value = []
  searched.value = false
  link.value = row
    ? { role: row.role, environment: row.environment, listening_ports: row.listening_ports || '', notes: row.notes || '' }
    : { role: 'other', environment: null, listening_ports: '', notes: '' }
  linkOpen.value = true
  if (!row) runSearch()
}

async function saveLink() {
  linkError.value = ''
  saving.value = true
  const body = { ...link.value, listening_ports: link.value.listening_ports || null, notes: link.value.notes || null }
  try {
    if (editing.value) await api.updateApplicationAssetLink(props.applicationId, editing.value.id, body)
    else await api.linkApplicationAsset(props.applicationId, { ...body, asset_id: picked.value.id })
    linkOpen.value = false
    await load()
    emit('changed')
  } catch (err) {
    linkError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

async function unlink(row) {
  if (!window.confirm(t('applications.infra.unlinkConfirm', { name: row.name }))) return
  try {
    await api.unlinkApplicationAsset(props.applicationId, row.id)
    await load()
    emit('changed')
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

onMounted(load)
</script>

<style scoped>
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { margin-bottom: 0.75rem; }
.loading { padding: 1.5rem; text-align: center; }
.app-table { width: 100%; border-collapse: collapse; }
.app-table th, .app-table td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--sk-border, #e1e7e3); vertical-align: top; }
.app-table th { font-weight: 600; font-size: 0.85rem; color: var(--sk-text-muted, #6b7a71); white-space: nowrap; }
.num { white-space: nowrap; text-align: right; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.9rem; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.block { display: block; }
.chip { margin-left: 0.4rem; }
.dns { margin-top: 1rem; }
.dns pre { margin: 0.25rem 0 0; white-space: pre-wrap; font-family: ui-monospace, Menlo, Consolas, monospace; }
.results { list-style: none; margin: 0.5rem 0 0; padding: 0; max-height: 14rem; overflow: auto; border: 1px solid var(--sk-border, #e1e7e3); border-radius: 6px; }
.results li { padding: 0.45rem 0.7rem; cursor: pointer; }
.results li:hover { background: var(--sk-hover, #f3f6f4); }
.results li.picked { background: var(--sk-selected, #e4efe8); }
.picked-name { margin: 0 0 0.75rem; }
.p-field { margin-bottom: 0.75rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
</style>
