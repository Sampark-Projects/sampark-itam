<!--
  - IpamVrfs.vue
  - VRFs (routing tables) and IPAM roles (the function of a prefix, range or VLAN).
-->
<template>
  <div class="ipam-page">
    <div class="page-header"><h1>{{ t('ipam.vrfs.title') }}</h1></div>
    <p class="hint">{{ t('ipam.vrfs.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <TabView class="modern-tabs">
      <TabPanel :header="t('ipam.vrfs.tabs.vrfs')">
        <div class="toolbar">
          <span class="p-input-icon-left search">
            <i class="pi pi-search" />
            <InputText v-model="search" :placeholder="t('ipam.vrfs.searchPlaceholder')" class="w-full" @input="onSearch" />
          </span>
          <span class="spacer"></span>
          <Button v-if="canWrite('ipam')" :label="t('ipam.vrfs.new')" icon="pi pi-plus" severity="success" @click="openVrf(null)" />
        </div>
        <DataTable :value="vrfs" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
                   :rowsPerPageOptions="[25, 50, 100]" @page="onPage">
          <template #empty>{{ t('ipam.vrfs.empty') }}</template>
          <Column field="name" :header="t('ipam.vrfs.fields.name')" />
          <Column field="rd" :header="t('ipam.vrfs.fields.rd')" style="width: 10rem" />
          <Column :header="t('ipam.vrfs.fields.enforceUnique')" style="width: 9rem">
            <template #body="{ data }">{{ data.enforce_unique ? t('ipam.yes') : t('ipam.no') }}</template>
          </Column>
          <Column :header="t('ipam.routeTargets.import')">
            <template #body="{ data }"><span class="mono">{{ (data.import_targets || []).map(x => x.name).join(', ') }}</span></template>
          </Column>
          <Column :header="t('ipam.routeTargets.export')">
            <template #body="{ data }"><span class="mono">{{ (data.export_targets || []).map(x => x.name).join(', ') }}</span></template>
          </Column>
          <Column field="prefix_count" :header="t('ipam.overview.prefixes')" style="width: 7rem" />
          <Column field="ip_count" :header="t('ipam.overview.addresses')" style="width: 7rem" />
          <Column field="range_count" :header="t('ipam.overview.ranges')" style="width: 7rem" />
          <Column field="description" :header="t('ipam.fields.description')" />
          <Column v-if="canWrite('ipam')" style="width: 6rem">
            <template #body="{ data }">
              <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openVrf(data)" />
              <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeVrf(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>

      <TabPanel :header="t('ipam.vrfs.tabs.roles')">
        <div class="toolbar">
          <span class="spacer"></span>
          <Button v-if="canWrite('ipam')" :label="t('ipam.vrfs.newRole')" icon="pi pi-plus" severity="success" @click="openRole(null)" />
        </div>
        <DataTable :value="roles" dataKey="id">
          <template #empty>{{ t('ipam.vrfs.emptyRoles') }}</template>
          <Column field="name" :header="t('ipam.vrfs.fields.name')" />
          <Column field="weight" :header="t('ipam.vrfs.fields.weight')" style="width: 7rem" />
          <Column field="prefix_count" :header="t('ipam.overview.prefixes')" style="width: 7rem" />
          <Column field="range_count" :header="t('ipam.overview.ranges')" style="width: 7rem" />
          <Column field="vlan_count" :header="t('ipam.overview.vlans')" style="width: 7rem" />
          <Column field="description" :header="t('ipam.fields.description')" />
          <Column v-if="canWrite('ipam')" style="width: 6rem">
            <template #body="{ data }">
              <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openRole(data)" />
              <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeRole(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>
      <TabPanel :header="t('ipam.vrfs.tabs.routeTargets')">
        <p class="hint">{{ t('ipam.routeTargets.hint') }}</p>
        <div class="toolbar">
          <span class="spacer"></span>
          <Button v-if="canWrite('ipam')" :label="t('ipam.routeTargets.new')" icon="pi pi-plus" severity="success" @click="openTarget(null)" />
        </div>
        <DataTable :value="targets" dataKey="id">
          <template #empty>{{ t('ipam.routeTargets.empty') }}</template>
          <Column :header="t('ipam.routeTargets.fields.name')">
            <template #body="{ data }"><strong class="mono">{{ data.name }}</strong></template>
          </Column>
          <Column field="importing_vrfs" :header="t('ipam.routeTargets.importedBy')" style="width: 10rem" />
          <Column field="exporting_vrfs" :header="t('ipam.routeTargets.exportedBy')" style="width: 10rem" />
          <Column field="description" :header="t('ipam.fields.description')" />
          <Column v-if="canWrite('ipam')" style="width: 6rem">
            <template #body="{ data }">
              <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openTarget(data)" />
              <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeTarget(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>
    </TabView>

    <Dialog v-model:visible="vrfOpen" modal :header="vrfEditing ? t('ipam.vrfs.edit') : t('ipam.vrfs.new')" :style="{ width: '34rem', maxWidth: '96vw' }">
      <Message v-if="vrfError" severity="error" :closable="true" @close="vrfError = ''">{{ vrfError }}</Message>
      <div class="p-field">
        <label>{{ t('ipam.vrfs.fields.name') }} *</label>
        <InputText v-model="vrfForm.name" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.vrfs.fields.rd') }}</label>
        <InputText v-model="vrfForm.rd" maxlength="21" placeholder="65000:100" class="w-full" />
        <small class="muted">{{ t('ipam.vrfs.rdHint') }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('ipam.routeTargets.import') }}</label>
        <MultiSelect v-model="vrfForm.import_targets" :options="targetOptions" optionLabel="label" optionValue="value" display="chip" filter
                     :placeholder="t('ipam.routeTargets.none')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.routeTargets.export') }}</label>
        <MultiSelect v-model="vrfForm.export_targets" :options="targetOptions" optionLabel="label" optionValue="value" display="chip" filter
                     :placeholder="t('ipam.routeTargets.none')" class="w-full" />
        <small class="muted">{{ t('ipam.routeTargets.vrfHint') }}</small>
      </div>
      <div class="p-field">
        <label class="check"><Checkbox v-model="vrfForm.enforce_unique" binary /><span>{{ t('ipam.vrfs.fields.enforceUnique') }}</span></label>
        <small class="muted">{{ t('ipam.vrfs.enforceHint') }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.description') }}</label>
        <InputText v-model="vrfForm.description" maxlength="200" class="w-full" />
      </div>
      <IpamComments v-model="vrfForm.comments" />
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="vrfOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="saveVrf" />
      </template>
    </Dialog>

    <Dialog v-model:visible="targetOpen" modal :header="targetEditing ? t('ipam.routeTargets.edit') : t('ipam.routeTargets.new')" :style="{ width: '30rem', maxWidth: '96vw' }">
      <Message v-if="targetError" severity="error" :closable="true" @close="targetError = ''">{{ targetError }}</Message>
      <div class="p-field">
        <label>{{ t('ipam.routeTargets.fields.name') }} *</label>
        <InputText v-model="targetForm.name" maxlength="21" placeholder="65000:100" class="w-full" />
        <small class="muted">{{ t('ipam.vrfs.rdHint') }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.description') }}</label>
        <InputText v-model="targetForm.description" maxlength="200" class="w-full" />
      </div>
      <IpamComments v-model="targetForm.comments" />
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="targetOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="saveTarget" />
      </template>
    </Dialog>

    <Dialog v-model:visible="roleOpen" modal :header="roleEditing ? t('ipam.vrfs.editRole') : t('ipam.vrfs.newRole')" :style="{ width: '30rem', maxWidth: '96vw' }">
      <Message v-if="roleError" severity="error" :closable="true" @close="roleError = ''">{{ roleError }}</Message>
      <div class="p-field">
        <label>{{ t('ipam.vrfs.fields.name') }} *</label>
        <InputText v-model="roleForm.name" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.slug') }}</label>
        <InputText v-model="roleForm.slug" maxlength="100" :placeholder="t('ipam.fields.slugAuto')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.vrfs.fields.weight') }}</label>
        <InputNumber v-model="roleForm.weight" :min="0" :max="32767" :useGrouping="false" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.description') }}</label>
        <InputText v-model="roleForm.description" maxlength="200" class="w-full" />
      </div>
      <IpamComments v-model="roleForm.comments" />
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="roleOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="saveRole" />
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
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Checkbox from 'primevue/checkbox'
import MultiSelect from 'primevue/multiselect'
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

// --- VRFs ---
const vrfs = ref([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const rows = ref(50)
const first = ref(0)

async function loadVrfs() {
  loading.value = true
  try {
    const params = { skip: first.value, limit: rows.value }
    if (search.value.trim()) params.search = search.value.trim()
    const res = await api.getIpamVrfs(params)
    vrfs.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    loading.value = false
  }
}
let timer = null
function onSearch() { clearTimeout(timer); timer = setTimeout(() => { first.value = 0; loadVrfs() }, 300) }
function onPage(event) { first.value = event.first; rows.value = event.rows; loadVrfs() }

const vrfOpen = ref(false)
const vrfEditing = ref(null)
const vrfError = ref('')
const vrfForm = ref({ name: '', rd: '', enforce_unique: true, description: '', comments: '', import_targets: [], export_targets: [] })
function openVrf(row) {
  vrfEditing.value = row
  vrfError.value = ''
  vrfForm.value = row
    ? {
        name: row.name, rd: row.rd || '', enforce_unique: row.enforce_unique, description: row.description || '', comments: row.comments || '',
        import_targets: (row.import_targets || []).map(x => x.id), export_targets: (row.export_targets || []).map(x => x.id)
      }
    : { name: '', rd: '', enforce_unique: true, description: '', comments: '', import_targets: [], export_targets: [] }
  vrfOpen.value = true
}
async function saveVrf() {
  vrfError.value = ''
  if (!vrfForm.value.name.trim()) { vrfError.value = t('ipam.vrfs.nameRequired'); return }
  const body = { ...vrfForm.value, rd: vrfForm.value.rd.trim() || null, description: vrfForm.value.description || null, comments: vrfForm.value.comments || null }
  saving.value = true
  try {
    if (vrfEditing.value) await api.updateIpamVrf(vrfEditing.value.id, body)
    else await api.createIpamVrf(body)
    vrfOpen.value = false
    message.value = { severity: 'success', text: t('ipam.saved') }
    await loadVrfs()
  } catch (err) {
    vrfError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
async function removeVrf(row) {
  if (!window.confirm(t('ipam.vrfs.deleteConfirm', { name: row.name }))) return
  try {
    await api.deleteIpamVrf(row.id)
    await loadVrfs()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

// --- route targets ---
const targets = ref([])
const targetOptions = computed(() => targets.value.map(x => ({ value: x.id, label: x.name })))
async function loadTargets() {
  try { targets.value = (await api.getIpamRouteTargets()).data || [] } catch (err) { message.value = { severity: 'error', text: apiErrorText(err, t) } }
}
const targetOpen = ref(false)
const targetEditing = ref(null)
const targetError = ref('')
const targetForm = ref({ name: '', description: '', comments: '' })
function openTarget(row) {
  targetEditing.value = row
  targetError.value = ''
  targetForm.value = row ? { name: row.name, description: row.description || '', comments: row.comments || '' } : { name: '', description: '', comments: '' }
  targetOpen.value = true
}
async function saveTarget() {
  targetError.value = ''
  if (!targetForm.value.name.trim()) { targetError.value = t('ipam.routeTargets.nameRequired'); return }
  const body = { name: targetForm.value.name.trim(), description: targetForm.value.description || null, comments: targetForm.value.comments || null }
  saving.value = true
  try {
    if (targetEditing.value) await api.updateIpamRouteTarget(targetEditing.value.id, body)
    else await api.createIpamRouteTarget(body)
    targetOpen.value = false
    message.value = { severity: 'success', text: t('ipam.saved') }
    await loadTargets()
    await loadVrfs()
  } catch (err) {
    targetError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
async function removeTarget(row) {
  if (!window.confirm(t('ipam.routeTargets.deleteConfirm', { name: row.name }))) return
  try {
    await api.deleteIpamRouteTarget(row.id)
    await loadTargets()
    await loadVrfs()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

// --- roles ---
const roles = ref([])
async function loadRoles() {
  try { roles.value = (await api.getIpamRoles()).data || [] } catch (err) { message.value = { severity: 'error', text: apiErrorText(err, t) } }
}
const roleOpen = ref(false)
const roleEditing = ref(null)
const roleError = ref('')
const roleForm = ref({ name: '', slug: '', weight: 1000, description: '', comments: '' })
function openRole(row) {
  roleEditing.value = row
  roleError.value = ''
  roleForm.value = row ? { name: row.name, slug: row.slug || '', weight: row.weight, description: row.description || '', comments: row.comments || '' } : { name: '', slug: '', weight: 1000, description: '', comments: '' }
  roleOpen.value = true
}
async function saveRole() {
  roleError.value = ''
  if (!roleForm.value.name.trim()) { roleError.value = t('ipam.vrfs.nameRequired'); return }
  const body = { ...roleForm.value, slug: roleForm.value.slug.trim() || null, weight: roleForm.value.weight ?? 1000, description: roleForm.value.description || null, comments: roleForm.value.comments || null }
  saving.value = true
  try {
    if (roleEditing.value) await api.updateIpamRole(roleEditing.value.id, body)
    else await api.createIpamRole(body)
    roleOpen.value = false
    message.value = { severity: 'success', text: t('ipam.saved') }
    await loadRoles()
  } catch (err) {
    roleError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
async function removeRole(row) {
  if (!window.confirm(t('ipam.vrfs.deleteRoleConfirm', { name: row.name }))) return
  try {
    await api.deleteIpamRole(row.id)
    await loadRoles()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

onMounted(() => { loadVrfs(); loadRoles(); loadTargets() })
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
.check { display: inline-flex !important; align-items: center; gap: 0.5rem; cursor: pointer; }
</style>
