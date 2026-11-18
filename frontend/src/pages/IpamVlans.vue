<!--
  - IpamVlans.vue
  - VLANs and VLAN groups. A group holds ID ranges inside which VLAN IDs and names are unique.
-->
<template>
  <div class="ipam-page">
    <div class="page-header"><h1>{{ t('ipam.vlans.title') }}</h1></div>
    <p class="hint">{{ t('ipam.vlans.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <TabView class="modern-tabs">
      <TabPanel :header="t('ipam.vlans.tabs.vlans')">
        <div class="toolbar">
          <span class="p-input-icon-left search">
            <i class="pi pi-search" />
            <InputText v-model="search" :placeholder="t('ipam.vlans.searchPlaceholder')" class="w-full" @input="onSearch" />
          </span>
          <Dropdown v-model="groupFilter" :options="groupOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.vlans.allGroups')" class="filter" @change="reload" />
          <Dropdown v-model="statusFilter" :options="vlanStatusOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.fields.allStatuses')" class="filter" @change="reload" />
          <span class="spacer"></span>
          <IpamCsvTools kind="vlans" @imported="reload" @error="text => message = { severity: 'error', text }" />
          <Button v-if="canWrite('ipam')" :label="t('ipam.vlans.new')" icon="pi pi-plus" severity="success" @click="openVlan(null)" />
        </div>
        <DataTable :value="items" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
                   :rowsPerPageOptions="[25, 50, 100]" @page="onPage">
          <template #empty>{{ t('ipam.vlans.empty') }}</template>
          <Column field="vid" :header="t('ipam.vlans.fields.vid')" style="width: 6rem" />
          <Column field="name" :header="t('ipam.vlans.fields.name')" />
          <Column field="group_name" :header="t('ipam.vlans.fields.group')" style="width: 10rem" />
          <Column field="site_name" :header="t('ipam.fields.site')" style="width: 9rem" />
          <Column :header="t('ipam.fields.status')" style="width: 8rem">
            <template #body="{ data }"><Tag :value="t(`ipam.statuses.${data.status}`)" :severity="statusSeverity(data.status)" /></template>
          </Column>
          <Column field="role_name" :header="t('ipam.fields.role')" style="width: 8rem" />
          <Column :header="t('ipam.vlans.fields.qinq')" style="width: 10rem">
            <template #body="{ data }">
              <span v-if="data.qinq_role">{{ t(`ipam.vlans.qinqRoles.${data.qinq_role}`) }}<small v-if="data.qinq_svlan_label" class="muted"> / {{ data.qinq_svlan_label }}</small></span>
            </template>
          </Column>
          <Column field="prefix_count" :header="t('ipam.vlans.prefixes')" style="width: 7rem" />
          <Column field="description" :header="t('ipam.fields.description')" />
          <Column v-if="canWrite('ipam')" style="width: 6rem">
            <template #body="{ data }">
              <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openVlan(data)" />
              <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeVlan(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>

      <TabPanel :header="t('ipam.vlans.tabs.groups')">
        <div class="toolbar">
          <span class="spacer"></span>
          <Button v-if="canWrite('ipam')" :label="t('ipam.vlans.newGroup')" icon="pi pi-plus" severity="success" @click="openGroup(null)" />
        </div>
        <DataTable :value="groups" dataKey="id">
          <template #empty>{{ t('ipam.vlans.emptyGroups') }}</template>
          <Column field="name" :header="t('ipam.vlans.fields.name')" />
          <Column field="vid_ranges_text" :header="t('ipam.vlans.fields.ranges')" />
          <Column field="slug" :header="t('ipam.fields.slug')" style="width: 9rem" />
          <Column field="site_name" :header="t('ipam.fields.site')" style="width: 9rem" />
          <Column field="location_name" :header="t('ipam.fields.location')" style="width: 9rem" />
          <Column field="vlan_count" :header="t('ipam.vlans.tabs.vlans')" style="width: 6rem" />
          <Column :header="t('ipam.vlans.available')" style="width: 10rem">
            <template #body="{ data }">{{ data.available_vid_count }}<small v-if="data.next_available_vid" class="muted"> ({{ t('ipam.vlans.next') }} {{ data.next_available_vid }})</small></template>
          </Column>
          <Column field="description" :header="t('ipam.fields.description')" />
          <Column v-if="canWrite('ipam')" style="width: 6rem">
            <template #body="{ data }">
              <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openGroup(data)" />
              <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeGroup(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>
      <TabPanel :header="t('ipam.vlans.tabs.translation')">
        <IpamVlanTranslation />
      </TabPanel>
    </TabView>

    <Dialog v-model:visible="vlanOpen" modal :header="vlanEditing ? t('ipam.vlans.edit') : t('ipam.vlans.new')" :style="{ width: '36rem', maxWidth: '96vw' }">
      <Message v-if="vlanError" severity="error" :closable="true" @close="vlanError = ''">{{ vlanError }}</Message>
      <div class="grid-2">
        <div class="p-field">
          <label>{{ t('ipam.vlans.fields.vid') }} *</label>
          <InputNumber v-model="vlanForm.vid" :min="1" :max="4094" :useGrouping="false" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('ipam.vlans.fields.name') }} *</label>
          <InputText v-model="vlanForm.name" maxlength="64" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('ipam.vlans.fields.group') }}</label>
          <Dropdown v-model="vlanForm.group_id" :options="groupOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('ipam.fields.status') }}</label>
          <Dropdown v-model="vlanForm.status" :options="vlanStatusOptions" optionLabel="label" optionValue="value" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('ipam.fields.site') }}</label>
          <Dropdown v-model="vlanForm.site_id" :options="sites" optionLabel="label" optionValue="value" showClear filter class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('ipam.fields.role') }}</label>
          <Dropdown v-model="vlanForm.role_id" :options="roles" optionLabel="label" optionValue="value" showClear class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('ipam.vlans.fields.qinqRole') }}</label>
          <Dropdown v-model="vlanForm.qinq_role" :options="qinqRoleOptions" optionLabel="label" optionValue="value" showClear
                    :placeholder="t('ipam.vlans.noQinq')" class="w-full" @change="onQinqRole" />
        </div>
        <div v-if="vlanForm.qinq_role === 'cvlan'" class="p-field">
          <label>{{ t('ipam.vlans.fields.svlan') }} *</label>
          <Dropdown v-model="vlanForm.qinq_svlan_id" :options="svlanOptions" optionLabel="label" optionValue="value" showClear filter class="w-full" />
        </div>
        <div class="p-field span-2">
          <label>{{ t('ipam.fields.description') }}</label>
          <InputText v-model="vlanForm.description" maxlength="200" class="w-full" />
        </div>
        <IpamComments v-model="vlanForm.comments" />
      </div>
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="vlanOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="saveVlan" />
      </template>
    </Dialog>

    <Dialog v-model:visible="groupOpen" modal :header="groupEditing ? t('ipam.vlans.editGroup') : t('ipam.vlans.newGroup')" :style="{ width: '36rem', maxWidth: '96vw' }">
      <Message v-if="groupError" severity="error" :closable="true" @close="groupError = ''">{{ groupError }}</Message>
      <div class="grid-2">
        <div class="p-field span-2">
          <label>{{ t('ipam.vlans.fields.name') }} *</label>
          <InputText v-model="groupForm.name" maxlength="100" class="w-full" />
        </div>
        <div class="p-field span-2">
          <label>{{ t('ipam.vlans.fields.ranges') }}</label>
          <InputText v-model="groupForm.vid_ranges" placeholder="1-99, 200-299" class="w-full" />
          <small class="muted">{{ t('ipam.vlans.rangesHint') }}</small>
        </div>
        <div class="p-field span-2">
          <label>{{ t('ipam.fields.slug') }}</label>
          <InputText v-model="groupForm.slug" maxlength="100" :placeholder="t('ipam.fields.slugAuto')" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('ipam.fields.site') }}</label>
          <Dropdown v-model="groupForm.site_id" :options="sites" optionLabel="label" optionValue="value" showClear filter class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('ipam.fields.location') }}</label>
          <Dropdown v-model="groupForm.location_id" :options="groupLocations" optionLabel="label" optionValue="value" showClear filter
                    :placeholder="t('ipam.fields.wholeSite')" class="w-full" />
        </div>
        <div class="p-field span-2">
          <label>{{ t('ipam.fields.description') }}</label>
          <InputText v-model="groupForm.description" maxlength="200" class="w-full" />
        </div>
        <IpamComments v-model="groupForm.comments" />
      </div>
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="groupOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="saveGroup" />
      </template>
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
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import IpamCsvTools from '../components/features/ipam/IpamCsvTools.vue'
import { usePermissions } from '../composables/usePermissions'
import { useIpamChoices, useIpamLookups, statusSeverity } from '../composables/useIpam'
import { apiErrorText } from '../utils/money'
import IpamComments from '../components/features/ipam/IpamComments.vue'
import IpamVlanTranslation from '../components/features/ipam/IpamVlanTranslation.vue'

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const { vlanStatusOptions } = useIpamChoices()
const { roles, sites, locations, load: loadLookups } = useIpamLookups()

const message = ref(null)
const saving = ref(false)

// --- groups ---
const groups = ref([])
const groupOptions = computed(() => groups.value.map(g => ({ value: g.id, label: g.name })))
async function loadGroups() {
  try { groups.value = (await api.getIpamVlanGroups()).data || [] } catch (err) { message.value = { severity: 'error', text: apiErrorText(err, t) } }
}

const groupOpen = ref(false)
const groupEditing = ref(null)
const groupError = ref('')
const groupForm = ref({ name: '', slug: '', vid_ranges: '', site_id: null, location_id: null, description: '', comments: '' })
const groupLocations = computed(() => locations.value.filter(l => !groupForm.value.site_id || l.site_id === groupForm.value.site_id))
function openGroup(row) {
  groupEditing.value = row
  groupError.value = ''
  groupForm.value = row
    ? { name: row.name, slug: row.slug || '', vid_ranges: row.vid_ranges_text || '', site_id: row.site_id, location_id: row.location_id, description: row.description || '', comments: row.comments || '' }
    : { name: '', slug: '', vid_ranges: '', site_id: null, location_id: null, description: '', comments: '' }
  groupOpen.value = true
}
async function saveGroup() {
  groupError.value = ''
  if (!groupForm.value.name.trim()) { groupError.value = t('ipam.vlans.nameRequired'); return }
  const body = { ...groupForm.value, slug: groupForm.value.slug.trim() || null, vid_ranges: groupForm.value.vid_ranges.trim() || null, description: groupForm.value.description || null, comments: groupForm.value.comments || null }
  saving.value = true
  try {
    if (groupEditing.value) await api.updateIpamVlanGroup(groupEditing.value.id, body)
    else await api.createIpamVlanGroup(body)
    groupOpen.value = false
    message.value = { severity: 'success', text: t('ipam.saved') }
    await loadGroups()
  } catch (err) {
    groupError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
async function removeGroup(row) {
  if (!window.confirm(t('ipam.vlans.deleteGroupConfirm', { name: row.name }))) return
  try {
    await api.deleteIpamVlanGroup(row.id)
    await loadGroups()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

// --- VLANs ---
const items = ref([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const groupFilter = ref(null)
const statusFilter = ref(null)
const rows = ref(50)
const first = ref(0)

let request = 0
async function load() {
  const mine = ++request
  loading.value = true
  try {
    const params = { skip: first.value, limit: rows.value }
    if (search.value.trim()) params.search = search.value.trim()
    if (groupFilter.value) params.group_id = groupFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await api.getIpamVlans(params)
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

const vlanOpen = ref(false)
const vlanEditing = ref(null)
const vlanError = ref('')
const blankVlan = () => ({ vid: null, name: '', group_id: null, status: 'active', site_id: null, role_id: null, qinq_role: null, qinq_svlan_id: null, description: '', comments: '' })
const qinqRoleOptions = computed(() => ['svlan', 'cvlan'].map(v => ({ value: v, label: t(`ipam.vlans.qinqRoles.${v}`) })))
const svlans = ref([])
const svlanOptions = computed(() => svlans.value.filter(v => !vlanEditing.value || v.id !== vlanEditing.value.id).map(v => ({ value: v.id, label: v.label })))
async function loadSvlans() {
  try { svlans.value = (await api.getIpamVlans({ qinq_role: 'svlan', limit: 500 })).data.items || [] } catch (err) { svlans.value = [] }
}
function onQinqRole() { if (vlanForm.value.qinq_role !== 'cvlan') vlanForm.value.qinq_svlan_id = null }
const vlanForm = ref(blankVlan())
function openVlan(row) {
  vlanEditing.value = row
  vlanError.value = ''
  vlanForm.value = row ? { ...blankVlan(), ...Object.fromEntries(Object.keys(blankVlan()).map(k => [k, row[k] ?? blankVlan()[k]])) } : blankVlan()
  vlanOpen.value = true
  loadSvlans()
}
async function saveVlan() {
  vlanError.value = ''
  if (!vlanForm.value.vid || !vlanForm.value.name.trim()) { vlanError.value = t('ipam.vlans.required'); return }
  if (vlanForm.value.qinq_role === 'cvlan' && !vlanForm.value.qinq_svlan_id) { vlanError.value = t('ipam.vlans.svlanRequired'); return }
  const body = { ...vlanForm.value, description: vlanForm.value.description || null, comments: vlanForm.value.comments || null }
  saving.value = true
  try {
    if (vlanEditing.value) await api.updateIpamVlan(vlanEditing.value.id, body)
    else await api.createIpamVlan(body)
    vlanOpen.value = false
    message.value = { severity: 'success', text: t('ipam.saved') }
    await Promise.all([load(), loadGroups()])
  } catch (err) {
    vlanError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
async function removeVlan(row) {
  if (!window.confirm(t('ipam.vlans.deleteConfirm', { name: row.label }))) return
  try {
    await api.deleteIpamVlan(row.id)
    await Promise.all([load(), loadGroups()])
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

onMounted(() => { load(); loadGroups(); loadLookups() })
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.toolbar .spacer { flex: 1; }
.search { flex: 1 1 16rem; max-width: 24rem; }
.filter { min-width: 11rem; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem 1rem; }
.span-2 { grid-column: span 2; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
