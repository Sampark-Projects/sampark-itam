<!--
  - IpamAggregates.vue
  - Aggregates (the top-level address blocks handed out by a registry) and the RIRs that assign them.
-->
<template>
  <div class="ipam-page">
    <div class="page-header"><h1>{{ t('ipam.aggregates.title') }}</h1></div>
    <p class="hint">{{ t('ipam.aggregates.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <TabView class="modern-tabs">
      <TabPanel :header="t('ipam.aggregates.tabs.aggregates')">
        <div class="toolbar">
          <span class="p-input-icon-left search">
            <i class="pi pi-search" />
            <InputText v-model="search" :placeholder="t('ipam.aggregates.searchPlaceholder')" class="w-full" @input="onSearch" />
          </span>
          <Dropdown v-model="rirFilter" :options="rirOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.aggregates.allRirs')" class="filter" @change="reload" />
          <Dropdown v-model="familyFilter" :options="familyOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.fields.allFamilies')" class="filter narrow" @change="reload" />
          <span class="spacer"></span>
          <Button v-if="canWrite('ipam')" :label="t('ipam.aggregates.new')" icon="pi pi-plus" severity="success" @click="openAggregate(null)" />
        </div>
        <DataTable :value="items" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
                   :rowsPerPageOptions="[25, 50, 100]" selectionMode="single" class="rows" @page="onPage" @row-click="e => router.push(`/ipam/aggregates/${e.data.id}`)">
          <template #empty>{{ t('ipam.aggregates.empty') }}</template>
          <Column :header="t('ipam.aggregates.fields.prefix')">
            <template #body="{ data }"><strong class="mono">{{ data.prefix }}</strong></template>
          </Column>
          <Column :header="t('ipam.aggregates.fields.rir')" style="width: 11rem">
            <template #body="{ data }">{{ data.rir_name }}<Tag v-if="data.rir_is_private" :value="t('ipam.rirs.private')" severity="secondary" class="chip" /></template>
          </Column>
          <Column :header="t('ipam.prefixes.utilization')" style="width: 11rem">
            <template #body="{ data }"><IpamUtilization :value="data.utilization" /></template>
          </Column>
          <Column field="prefix_count" :header="t('ipam.overview.prefixes')" style="width: 7rem" />
          <Column :header="t('ipam.aggregates.fields.dateAdded')" style="width: 9rem">
            <template #body="{ data }">{{ data.date_added ? formatDate(data.date_added) : '' }}</template>
          </Column>
          <Column field="description" :header="t('ipam.fields.description')" />
          <Column v-if="canWrite('ipam')" style="width: 6rem">
            <template #body="{ data }">
              <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click.stop="openAggregate(data)" />
              <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click.stop="removeAggregate(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>

      <TabPanel :header="t('ipam.aggregates.tabs.rirs')">
        <div class="toolbar">
          <span class="spacer"></span>
          <Button v-if="canWrite('ipam')" :label="t('ipam.rirs.new')" icon="pi pi-plus" severity="success" @click="openRir(null)" />
        </div>
        <DataTable :value="rirs" dataKey="id">
          <template #empty>{{ t('ipam.rirs.empty') }}</template>
          <Column field="name" :header="t('ipam.rirs.fields.name')" />
          <Column :header="t('ipam.rirs.private')" style="width: 8rem">
            <template #body="{ data }">{{ data.is_private ? t('ipam.yes') : t('ipam.no') }}</template>
          </Column>
          <Column field="aggregate_count" :header="t('ipam.aggregates.tabs.aggregates')" style="width: 8rem" />
          <Column field="asn_count" :header="t('ipam.asns.tabs.asns')" style="width: 7rem" />
          <Column field="asn_range_count" :header="t('ipam.asns.tabs.ranges')" style="width: 9rem" />
          <Column field="description" :header="t('ipam.fields.description')" />
          <Column v-if="canWrite('ipam')" style="width: 6rem">
            <template #body="{ data }">
              <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openRir(data)" />
              <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeRir(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>
    </TabView>

    <IpamAggregateForm v-model:visible="aggregateOpen" :aggregate="editingAggregate" :rirs="rirOptions" @saved="onAggregateSaved" />

    <Dialog v-model:visible="rirOpen" modal :header="rirEditing ? t('ipam.rirs.edit') : t('ipam.rirs.new')" :style="{ width: '32rem', maxWidth: '96vw' }">
      <Message v-if="rirError" severity="error" :closable="true" @close="rirError = ''">{{ rirError }}</Message>
      <div class="p-field">
        <label>{{ t('ipam.rirs.fields.name') }} *</label>
        <InputText v-model="rirForm.name" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.slug') }}</label>
        <InputText v-model="rirForm.slug" maxlength="100" :placeholder="t('ipam.fields.slugAuto')" class="w-full" />
      </div>
      <div class="p-field">
        <label class="check"><Checkbox v-model="rirForm.is_private" binary /><span>{{ t('ipam.rirs.privateHint') }}</span></label>
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.description') }}</label>
        <InputText v-model="rirForm.description" maxlength="200" class="w-full" />
      </div>
      <IpamComments v-model="rirForm.comments" />
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="rirOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="saveRir" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dialog from 'primevue/dialog'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import IpamAggregateForm from '../components/forms/IpamAggregateForm.vue'
import IpamUtilization from '../components/features/ipam/IpamUtilization.vue'
import { usePermissions } from '../composables/usePermissions'
import { useDateFormatter } from '../composables/useDateFormatter'
import { useIpamChoices } from '../composables/useIpam'
import { apiErrorText } from '../utils/money'
import IpamComments from '../components/features/ipam/IpamComments.vue'

const { t } = useI18n()
const router = useRouter()
const { canWrite, canDelete } = usePermissions()
const { formatDate } = useDateFormatter()
const { familyOptions } = useIpamChoices()

const message = ref(null)
const saving = ref(false)

// --- RIRs ---
const rirs = ref([])
const rirOptions = computed(() => rirs.value.map(r => ({ value: r.id, label: r.name })))
async function loadRirs() {
  try { rirs.value = (await api.getIpamRirs()).data || [] } catch (err) { message.value = { severity: 'error', text: apiErrorText(err, t) } }
}
const rirOpen = ref(false)
const rirEditing = ref(null)
const rirError = ref('')
const rirForm = ref({ name: '', slug: '', is_private: false, description: '', comments: '' })
function openRir(row) {
  rirEditing.value = row
  rirError.value = ''
  rirForm.value = row ? { name: row.name, slug: row.slug || '', is_private: row.is_private, description: row.description || '', comments: row.comments || '' } : { name: '', slug: '', is_private: false, description: '', comments: '' }
  rirOpen.value = true
}
async function saveRir() {
  rirError.value = ''
  if (!rirForm.value.name.trim()) { rirError.value = t('ipam.rirs.nameRequired'); return }
  const body = { ...rirForm.value, slug: rirForm.value.slug.trim() || null, description: rirForm.value.description || null, comments: rirForm.value.comments || null }
  saving.value = true
  try {
    if (rirEditing.value) await api.updateIpamRir(rirEditing.value.id, body)
    else await api.createIpamRir(body)
    rirOpen.value = false
    message.value = { severity: 'success', text: t('ipam.saved') }
    await loadRirs()
  } catch (err) {
    rirError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
async function removeRir(row) {
  if (!window.confirm(t('ipam.rirs.deleteConfirm', { name: row.name }))) return
  try {
    await api.deleteIpamRir(row.id)
    await loadRirs()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

// --- aggregates ---
const items = ref([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const rirFilter = ref(null)
const familyFilter = ref(null)
const rows = ref(50)
const first = ref(0)

let request = 0
async function load() {
  const mine = ++request
  loading.value = true
  try {
    const params = { skip: first.value, limit: rows.value }
    if (search.value.trim()) params.search = search.value.trim()
    if (rirFilter.value) params.rir_id = rirFilter.value
    if (familyFilter.value) params.family = familyFilter.value
    const res = await api.getIpamAggregates(params)
    if (mine !== request) return
    items.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (err) {
    if (mine === request) message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    if (mine === request) loading.value = false
  }
}
function reload() { first.value = 0; load() }
let timer = null
function onSearch() { clearTimeout(timer); timer = setTimeout(reload, 300) }
function onPage(event) { first.value = event.first; rows.value = event.rows; load() }

const aggregateOpen = ref(false)
const editingAggregate = ref(null)
function openAggregate(row) { editingAggregate.value = row; aggregateOpen.value = true }
function onAggregateSaved() { message.value = { severity: 'success', text: t('ipam.saved') }; load(); loadRirs() }
async function removeAggregate(row) {
  if (!window.confirm(t('ipam.aggregates.deleteConfirm', { name: row.prefix }))) return
  try {
    await api.deleteIpamAggregate(row.id)
    load()
    loadRirs()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

onMounted(() => { load(); loadRirs() })
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.toolbar .spacer { flex: 1; }
.search { flex: 1 1 16rem; max-width: 24rem; }
.filter { min-width: 11rem; }
.filter.narrow { min-width: 8rem; }
.rows :deep(tr) { cursor: pointer; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.chip { margin-left: 0.4rem; }
.p-field { margin-bottom: 0.75rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
.check { display: inline-flex !important; align-items: center; gap: 0.5rem; cursor: pointer; font-weight: 400 !important; }
</style>
