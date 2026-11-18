<!--
  - IpamAsns.vue
  - Autonomous system numbers and the ranges of AS numbers handed out by a registry.
-->
<template>
  <div class="ipam-page">
    <div class="page-header"><h1>{{ t('ipam.asns.title') }}</h1></div>
    <p class="hint">{{ t('ipam.asns.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <TabView class="modern-tabs">
      <TabPanel :header="t('ipam.asns.tabs.asns')">
        <div class="toolbar">
          <span class="p-input-icon-left search">
            <i class="pi pi-search" />
            <InputText v-model="search" :placeholder="t('ipam.asns.searchPlaceholder')" class="w-full" @input="onSearch" />
          </span>
          <Dropdown v-model="rirFilter" :options="rirOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.aggregates.allRirs')" class="filter" @change="reload" />
          <Dropdown v-model="roleFilter" :options="roles" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.asns.allRoles')" class="filter" @change="reload" />
          <span class="spacer"></span>
          <Button v-if="canWrite('ipam')" :label="t('ipam.asns.new')" icon="pi pi-plus" severity="success" @click="openAsn(null)" />
        </div>
        <DataTable :value="items" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
                   :rowsPerPageOptions="[25, 50, 100]" @page="onPage">
          <template #empty>{{ t('ipam.asns.empty') }}</template>
          <Column :header="t('ipam.asns.fields.asn')" style="width: 14rem">
            <template #body="{ data }"><strong class="mono">{{ data.label }}</strong></template>
          </Column>
          <Column field="rir_name" :header="t('ipam.aggregates.fields.rir')" style="width: 11rem" />
          <Column field="role_name" :header="t('ipam.fields.role')" style="width: 9rem" />
          <Column :header="t('ipam.asns.fields.sites')" style="width: 14rem">
            <template #body="{ data }">{{ (data.sites || []).map(s => s.name).join(', ') }}</template>
          </Column>
          <Column field="description" :header="t('ipam.fields.description')" />
          <Column v-if="canWrite('ipam')" style="width: 6rem">
            <template #body="{ data }">
              <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openAsn(data)" />
              <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeAsn(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>

      <TabPanel :header="t('ipam.asns.tabs.ranges')">
        <div class="toolbar">
          <span class="spacer"></span>
          <Button v-if="canWrite('ipam')" :label="t('ipam.asns.newRange')" icon="pi pi-plus" severity="success" @click="openRange(null)" />
        </div>
        <DataTable :value="ranges" dataKey="id">
          <template #empty>{{ t('ipam.asns.emptyRanges') }}</template>
          <Column field="name" :header="t('ipam.asns.fields.name')" />
          <Column :header="t('ipam.asns.fields.range')" style="width: 16rem">
            <template #body="{ data }"><span class="mono">{{ data.label }}</span><small v-if="data.start_asdot" class="muted"> ({{ data.start_asdot }}-{{ data.end_asdot }})</small></template>
          </Column>
          <Column field="rir_name" :header="t('ipam.aggregates.fields.rir')" style="width: 10rem" />
          <Column field="size" :header="t('ipam.ranges.fields.size')" style="width: 8rem" />
          <Column field="asn_count" :header="t('ipam.asns.used')" style="width: 7rem" />
          <Column field="available_count" :header="t('ipam.asns.free')" style="width: 8rem" />
          <Column field="description" :header="t('ipam.fields.description')" />
          <Column style="width: 9rem">
            <template #body="{ data }">
              <Button icon="pi pi-list" text rounded size="small" :aria-label="t('ipam.asns.showFree')" @click="showFree(data)" />
              <Button v-if="canWrite('ipam')" icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openRange(data)" />
              <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeRange(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>
    </TabView>

    <Dialog v-model:visible="asnOpen" modal :header="asnEditing ? t('ipam.asns.edit') : t('ipam.asns.new')" :style="{ width: '32rem', maxWidth: '96vw' }">
      <Message v-if="asnError" severity="error" :closable="true" @close="asnError = ''">{{ asnError }}</Message>
      <div class="p-field">
        <label>{{ t('ipam.asns.fields.asn') }} *</label>
        <InputText v-model="asnForm.asn" maxlength="20" placeholder="65000 / 1.10" class="w-full" />
        <small class="muted">{{ t('ipam.asns.asnHint') }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('ipam.aggregates.fields.rir') }} *</label>
        <Dropdown v-model="asnForm.rir_id" :options="rirOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.role') }}</label>
        <Dropdown v-model="asnForm.role_id" :options="roles" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.asns.fields.sites') }}</label>
        <MultiSelect v-model="asnForm.site_ids" :options="sites" optionLabel="label" optionValue="value" display="chip" filter
                     :placeholder="t('ipam.asns.noSites')" class="w-full" />
        <small class="muted">{{ t('ipam.asns.sitesHint') }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.description') }}</label>
        <InputText v-model="asnForm.description" maxlength="200" class="w-full" />
      </div>
      <IpamComments v-model="asnForm.comments" />
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="asnOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="saveAsn" />
      </template>
    </Dialog>

    <Dialog v-model:visible="rangeOpen" modal :header="rangeEditing ? t('ipam.asns.editRange') : t('ipam.asns.newRange')" :style="{ width: '34rem', maxWidth: '96vw' }">
      <Message v-if="rangeError" severity="error" :closable="true" @close="rangeError = ''">{{ rangeError }}</Message>
      <div class="p-field">
        <label>{{ t('ipam.asns.fields.name') }} *</label>
        <InputText v-model="rangeForm.name" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.slug') }}</label>
        <InputText v-model="rangeForm.slug" maxlength="100" :placeholder="t('ipam.fields.slugAuto')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.aggregates.fields.rir') }} *</label>
        <Dropdown v-model="rangeForm.rir_id" :options="rirOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="grid-2">
        <div class="p-field">
          <label>{{ t('ipam.asns.fields.start') }} *</label>
          <InputText v-model="rangeForm.start" maxlength="20" placeholder="64512" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('ipam.asns.fields.end') }} *</label>
          <InputText v-model="rangeForm.end" maxlength="20" placeholder="65534" class="w-full" />
        </div>
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.description') }}</label>
        <InputText v-model="rangeForm.description" maxlength="200" class="w-full" />
      </div>
      <IpamComments v-model="rangeForm.comments" />
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="rangeOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="saveRange" />
      </template>
    </Dialog>

    <Dialog v-model:visible="freeOpen" modal :header="freeRange ? `${freeRange.name} · ${t('ipam.asns.free')}` : ''" :style="{ width: '30rem', maxWidth: '96vw' }">
      <p class="muted">{{ t('ipam.asns.freeCount', { n: freeCount }) }}</p>
      <div class="free-list"><span v-for="n in freeAsns" :key="n" class="chip mono">{{ n }}</span></div>
      <template #footer><Button :label="t('common.actions.cancel')" text severity="secondary" @click="freeOpen = false" /></template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dialog from 'primevue/dialog'
import Dropdown from 'primevue/dropdown'
import MultiSelect from 'primevue/multiselect'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../composables/usePermissions'
import { apiErrorText } from '../utils/money'
import IpamComments from '../components/features/ipam/IpamComments.vue'

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const message = ref(null)
const saving = ref(false)

// --- lookups ---
const rirs = ref([])
const roles = ref([])
const sites = ref([])
const rirOptions = computed(() => rirs.value.map(r => ({ value: r.id, label: r.name })))
async function loadLookups() {
  await Promise.allSettled([
    api.getIpamRirs().then(r => { rirs.value = r.data || [] }),
    api.getIpamRoles().then(r => { roles.value = (r.data || []).map(x => ({ value: x.id, label: x.name })) }),
    api.getSites().then(r => {
      const list = Array.isArray(r.data) ? r.data : (r.data?.items || [])
      sites.value = list.map(s => ({ value: s.id, label: s.name }))
    })
  ])
}

// --- ASNs ---
const items = ref([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const rirFilter = ref(null)
const roleFilter = ref(null)
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
    if (roleFilter.value) params.role_id = roleFilter.value
    const res = await api.getIpamAsns(params)
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

const asnOpen = ref(false)
const asnEditing = ref(null)
const asnError = ref('')
const blankAsn = () => ({ asn: '', rir_id: null, role_id: null, site_ids: [], description: '', comments: '' })
const asnForm = ref(blankAsn())
function openAsn(row) {
  asnEditing.value = row
  asnError.value = ''
  asnForm.value = row ? { asn: String(row.asn), rir_id: row.rir_id, role_id: row.role_id, site_ids: (row.sites || []).map(x => x.id), description: row.description || '', comments: row.comments || '' } : blankAsn()
  asnOpen.value = true
}
async function saveAsn() {
  asnError.value = ''
  if (!String(asnForm.value.asn).trim() || !asnForm.value.rir_id) { asnError.value = t('ipam.asns.required'); return }
  const body = { ...asnForm.value, asn: String(asnForm.value.asn).trim(), description: asnForm.value.description || null, comments: asnForm.value.comments || null }
  saving.value = true
  try {
    if (asnEditing.value) await api.updateIpamAsn(asnEditing.value.id, body)
    else await api.createIpamAsn(body)
    asnOpen.value = false
    message.value = { severity: 'success', text: t('ipam.saved') }
    await Promise.all([load(), loadRanges()])
  } catch (err) {
    asnError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
async function removeAsn(row) {
  if (!window.confirm(t('ipam.asns.deleteConfirm', { name: row.label }))) return
  try {
    await api.deleteIpamAsn(row.id)
    await Promise.all([load(), loadRanges()])
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

// --- ranges ---
const ranges = ref([])
async function loadRanges() {
  try { ranges.value = (await api.getIpamAsnRanges()).data || [] } catch (err) { message.value = { severity: 'error', text: apiErrorText(err, t) } }
}
const rangeOpen = ref(false)
const rangeEditing = ref(null)
const rangeError = ref('')
const blankRange = () => ({ name: '', slug: '', rir_id: null, start: '', end: '', description: '', comments: '' })
const rangeForm = ref(blankRange())
function openRange(row) {
  rangeEditing.value = row
  rangeError.value = ''
  rangeForm.value = row ? { name: row.name, slug: row.slug || '', rir_id: row.rir_id, start: String(row.start), end: String(row.end), description: row.description || '', comments: row.comments || '' } : blankRange()
  rangeOpen.value = true
}
async function saveRange() {
  rangeError.value = ''
  const f = rangeForm.value
  if (!f.name.trim() || !f.rir_id || !String(f.start).trim() || !String(f.end).trim()) { rangeError.value = t('ipam.asns.rangeRequired'); return }
  const body = { ...f, slug: f.slug.trim() || null, start: String(f.start).trim(), end: String(f.end).trim(), description: f.description || null, comments: f.comments || null }
  saving.value = true
  try {
    if (rangeEditing.value) await api.updateIpamAsnRange(rangeEditing.value.id, body)
    else await api.createIpamAsnRange(body)
    rangeOpen.value = false
    message.value = { severity: 'success', text: t('ipam.saved') }
    await loadRanges()
  } catch (err) {
    rangeError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
async function removeRange(row) {
  if (!window.confirm(t('ipam.asns.deleteRangeConfirm', { name: row.name }))) return
  try {
    await api.deleteIpamAsnRange(row.id)
    await loadRanges()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

const freeOpen = ref(false)
const freeRange = ref(null)
const freeAsns = ref([])
const freeCount = ref(0)
async function showFree(row) {
  freeRange.value = row
  freeAsns.value = []
  freeOpen.value = true
  try {
    const res = (await api.getIpamAsnRangeAvailable(row.id, 60)).data
    freeAsns.value = res.asns || []
    freeCount.value = res.available_count
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

onMounted(() => { load(); loadRanges(); loadLookups() })
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.toolbar .spacer { flex: 1; }
.search { flex: 1 1 16rem; max-width: 24rem; }
.filter { min-width: 11rem; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.p-field { margin-bottom: 0.75rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 1rem; }
.free-list { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.chip { padding: 0.05rem 0.5rem; border: 1px solid var(--sk-border, #e1e7e3); border-radius: 999px; font-size: 0.85rem; }
</style>
