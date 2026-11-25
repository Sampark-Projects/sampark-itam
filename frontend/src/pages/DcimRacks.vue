<!--
  - DcimRacks.vue
  - The racks: a paged list with the space used in each, create / edit / delete, the rack roles and the CSV import and export.
-->
<template>
  <div class="dcim-page">
    <div class="page-header">
      <h1>{{ t('dcim.racks.title') }}</h1>
      <div class="actions">
        <DcimCsvTools kind="racks" @imported="onImported" @error="msg => message = { severity: 'error', text: msg }" />
        <Button :label="t('dcim.roles.manage')" icon="pi pi-tags" outlined @click="rolesOpen = true" />
        <Button v-if="canWrite('dcim')" :label="t('dcim.racks.new')" icon="pi pi-plus" severity="success" @click="openForm(null)" />
      </div>
    </div>
    <p class="hint">{{ t('dcim.racks.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div v-if="overview" class="stats">
      <span><strong>{{ overview.racks }}</strong> {{ t('dcim.overview.racks') }}</span>
      <span><strong>{{ overview.placed_devices }}</strong> {{ t('dcim.overview.placed') }}</span>
      <span><strong>{{ overview.unpositioned_devices }}</strong> {{ t('dcim.overview.unpositioned') }}</span>
      <span v-if="overview.device_types_without_height" class="warn">
        <router-link to="/dcim/device-types?height_missing=1">{{ t('dcim.overview.noHeight', { n: overview.device_types_without_height }) }}</router-link>
      </span>
    </div>

    <div class="toolbar">
      <span class="p-input-icon-left search">
        <i class="pi pi-search" />
        <InputText v-model="search" :placeholder="t('dcim.racks.searchPlaceholder')" class="w-full" @input="onSearch" />
      </span>
      <Dropdown v-model="siteFilter" :options="lookups.sites.value" optionLabel="label" optionValue="value" showClear filter
                :placeholder="t('dcim.fields.site')" class="filter" @change="reload" />
      <Dropdown v-model="roleFilter" :options="lookups.roles.value" optionLabel="label" optionValue="value" showClear
                :placeholder="t('dcim.fields.role')" class="filter" @change="reload" />
      <Dropdown v-model="statusFilter" :options="statusOptions" optionLabel="label" optionValue="value" showClear
                :placeholder="t('dcim.fields.status')" class="filter" @change="reload" />
    </div>

    <DataTable :value="racks" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
               :rowsPerPageOptions="[15, 25, 50, 100]" @page="onPage">
      <template #empty>{{ t('dcim.racks.empty') }}</template>
      <Column :header="t('dcim.fields.name')">
        <template #body="{ data }"><router-link :to="`/dcim/racks/${data.id}`" class="link"><strong>{{ data.name }}</strong></router-link></template>
      </Column>
      <Column field="site_name" :header="t('dcim.fields.site')" style="width: 10rem" />
      <Column field="location_name" :header="t('dcim.fields.location')" style="width: 10rem" />
      <Column :header="t('dcim.fields.role')" style="width: 9rem">
        <template #body="{ data }">
          <span v-if="data.role_name"><span class="swatch" :style="{ background: data.role_color || '#cbd5e1' }"></span>{{ data.role_name }}</span>
        </template>
      </Column>
      <Column :header="t('dcim.fields.status')" style="width: 8rem">
        <template #body="{ data }"><Tag :value="t(`dcim.statuses.${data.status}`)" :severity="rackStatusSeverity(data.status)" /></template>
      </Column>
      <Column :header="t('dcim.fields.uHeight')" style="width: 6rem"><template #body="{ data }">{{ data.u_height }}U</template></Column>
      <Column field="device_count" :header="t('dcim.racks.devices')" style="width: 7rem" />
      <Column :header="t('dcim.racks.space')" style="width: 12rem">
        <template #body="{ data }">
          <div class="bar" :title="`${data.occupied_u}U / ${data.u_height}U`">
            <div class="fill" :style="{ width: Math.min(data.utilization, 100) + '%', background: utilizationColor(data.utilization) }"></div>
          </div>
          <small class="muted">{{ data.utilization }} % · {{ formatUnits(data.occupied_u) }}U</small>
        </template>
      </Column>
      <Column v-if="canWrite('dcim')" style="width: 6rem">
        <template #body="{ data }">
          <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openForm(data)" />
          <Button v-if="canDelete('dcim')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <DcimRackForm v-model:visible="formOpen" :rack="editing" :sites="lookups.sites.value" :locations="lookups.locations.value"
                  :roles="lookups.roles.value" @saved="onSaved" />
    <DcimRackRoles v-model:visible="rolesOpen" @changed="lookups.load()" />
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import InputText from 'primevue/inputtext'
import Dropdown from 'primevue/dropdown'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import DcimCsvTools from '../components/features/dcim/DcimCsvTools.vue'
import DcimRackRoles from '../components/features/dcim/DcimRackRoles.vue'
import DcimRackForm from '../components/forms/DcimRackForm.vue'
import { usePermissions } from '../composables/usePermissions'
import { useDcimChoices, useDcimLookups, rackStatusSeverity, utilizationColor, formatUnits } from '../composables/useDcim'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const { statusOptions } = useDcimChoices()
const lookups = useDcimLookups()

const racks = ref([])
const total = ref(0)
const loading = ref(false)
const overview = ref(null)
const message = ref(null)
const search = ref('')
const siteFilter = ref(null)
const roleFilter = ref(null)
const statusFilter = ref(null)
const rows = ref(25)
const first = ref(0)
const formOpen = ref(false)
const rolesOpen = ref(false)
const editing = ref(null)

let request = 0
async function load() {
  const mine = ++request
  loading.value = true
  try {
    const params = { skip: first.value, limit: rows.value }
    if (search.value.trim()) params.search = search.value.trim()
    if (siteFilter.value) params.site_id = siteFilter.value
    if (roleFilter.value) params.role_id = roleFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await api.getDcimRacks(params)
    if (mine !== request) return
    racks.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (err) {
    if (mine === request) message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    if (mine === request) loading.value = false
  }
}

async function loadOverview() {
  try { overview.value = (await api.getDcimOverview()).data } catch (err) { overview.value = null }
}

let timer = null
function reload() { first.value = 0; load() }
function onSearch() { clearTimeout(timer); timer = setTimeout(reload, 300) }
function onPage(event) { first.value = event.first; rows.value = event.rows; load() }

function openForm(row) { editing.value = row; formOpen.value = true }
function onSaved() { message.value = { severity: 'success', text: t('dcim.saved') }; load(); loadOverview() }
function onImported(summary) { message.value = { severity: 'success', text: t('dcim.csv.done', { created: summary.create, updated: summary.update, skipped: summary.skipped_duplicate + summary.skipped_invalid }) }; load(); loadOverview() }

async function remove(row) {
  if (!window.confirm(t('dcim.racks.deleteConfirm', { name: row.name }))) return
  try {
    await api.deleteDcimRack(row.id)
    message.value = { severity: 'success', text: t('dcim.deleted') }
    load()
    loadOverview()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

// the list, the totals and each dropdown list start together and fill as their own answers arrive
onMounted(() => { load(); loadOverview(); lookups.load() })
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
.actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.stats { display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 0.75rem; font-size: 0.9rem; }
.stats .warn a { color: #b45309; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.search { flex: 1 1 16rem; max-width: 24rem; }
.filter { min-width: 11rem; }
.link { color: inherit; text-decoration: none; }
.link:hover { text-decoration: underline; }
.swatch { display: inline-block; width: 0.8rem; height: 0.8rem; border-radius: 50%; margin-right: 0.4rem; vertical-align: middle; }
.bar { height: 0.5rem; background: #e5ece8; border-radius: 4px; overflow: hidden; margin-bottom: 0.2rem; }
.fill { height: 100%; }
.muted { color: var(--sk-text-muted, #6b7a71); }
</style>
