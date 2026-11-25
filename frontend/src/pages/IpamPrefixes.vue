<!--
  - IpamPrefixes.vue
  - The prefixes of the address space: a paged, filterable list ordered by routing table and address, indented by depth.
-->
<template>
  <div class="ipam-page">
    <div class="page-header">
      <h1>{{ t('ipam.prefixes.title') }}</h1>
      <div class="flex gap-2">
        <IpamCsvTools kind="prefixes" @imported="onCsvImported" @error="text => message = { severity: 'error', text }" />
        <Button v-if="canWrite('ipam')" :label="t('ipam.prefixes.new')" icon="pi pi-plus" severity="success" @click="openForm(null)" />
      </div>
    </div>
    <p class="hint">{{ t('ipam.prefixes.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div v-if="overview" class="overview">
      <div class="stat"><strong>{{ overview.prefixes.total }}</strong><span>{{ t('ipam.overview.prefixes') }}</span></div>
      <div class="stat"><strong>{{ overview.prefixes.containers }}</strong><span>{{ t('ipam.overview.containers') }}</span></div>
      <div class="stat"><strong>{{ overview.ip_addresses.total }}</strong><span>{{ t('ipam.overview.addresses') }}</span></div>
      <div class="stat"><strong>{{ overview.ip_ranges }}</strong><span>{{ t('ipam.overview.ranges') }}</span></div>
      <div class="stat"><strong>{{ overview.vlans }}</strong><span>{{ t('ipam.overview.vlans') }}</span></div>
      <div class="stat"><strong>{{ overview.vrfs }}</strong><span>{{ t('ipam.overview.vrfs') }}</span></div>
    </div>

    <div class="toolbar">
      <span class="p-input-icon-left search">
        <i class="pi pi-search" />
        <InputText v-model="search" :placeholder="t('ipam.prefixes.searchPlaceholder')" class="w-full" @input="onSearch" />
      </span>
      <Dropdown v-model="vrf" :options="vrfOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.fields.allVrfs')" class="filter" @change="reload" />
      <Dropdown v-model="status" :options="prefixStatusOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.fields.allStatuses')" class="filter" @change="reload" />
      <Dropdown v-model="family" :options="familyOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.fields.allFamilies')" class="filter narrow" @change="reload" />
    </div>

    <DataTable :value="items" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
               :rowsPerPageOptions="[25, 50, 100]" selectionMode="single" class="rows" @page="onPage" @row-click="e => open(e.data)">
      <template #empty>{{ t('ipam.prefixes.empty') }}</template>
      <Column :header="t('ipam.prefixes.fields.prefix')">
        <template #body="{ data }">
          <span class="indent" :style="{ paddingLeft: Math.min(data.depth, 10) * 1.1 + 'rem' }">
            <i v-if="data.status === 'container'" class="pi pi-folder-open muted-icon"></i>
            <strong class="mono">{{ data.prefix }}</strong>
          </span>
        </template>
      </Column>
      <Column :header="t('ipam.fields.status')" style="width: 8rem">
        <template #body="{ data }"><Tag :value="t(`ipam.statuses.${data.status}`)" :severity="statusSeverity(data.status)" /></template>
      </Column>
      <Column :header="t('ipam.fields.vrf')" style="width: 9rem">
        <template #body="{ data }">{{ data.vrf_name || t('ipam.fields.globalTable') }}</template>
      </Column>
      <Column :header="t('ipam.prefixes.utilization')" style="width: 11rem">
        <template #body="{ data }"><IpamUtilization :value="data.utilization" /></template>
      </Column>
      <Column :header="t('ipam.prefixes.availableIps')" style="width: 7rem">
        <template #body="{ data }">{{ data.status === 'container' ? '' : data.available_ips }}</template>
      </Column>
      <Column field="role_name" :header="t('ipam.fields.role')" style="width: 8rem" />
      <Column field="vlan_label" :header="t('ipam.fields.vlan')" style="width: 9rem" />
      <Column field="site_name" :header="t('ipam.fields.site')" style="width: 8rem" />
      <Column field="description" :header="t('ipam.fields.description')" />
      <Column v-if="canWrite('ipam')" style="width: 6rem">
        <template #body="{ data }">
          <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click.stop="openForm(data)" />
          <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click.stop="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <IpamPrefixForm v-model:visible="formOpen" :prefix="editing" @saved="onSaved" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import IpamPrefixForm from '../components/forms/IpamPrefixForm.vue'
import IpamCsvTools from '../components/features/ipam/IpamCsvTools.vue'
import IpamUtilization from '../components/features/ipam/IpamUtilization.vue'
import { usePermissions } from '../composables/usePermissions'
import { useIpamChoices, useIpamLookups, statusSeverity } from '../composables/useIpam'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const router = useRouter()
const { canWrite, canDelete } = usePermissions()
const { prefixStatusOptions, familyOptions } = useIpamChoices()
const { vrfs: vrfOptions, load: loadLookups } = useIpamLookups()

const items = ref([])
const total = ref(0)
const loading = ref(false)
const message = ref(null)
const search = ref('')
const vrf = ref(null)
const status = ref(null)
const family = ref(null)
const rows = ref(50)
const first = ref(0)
const formOpen = ref(false)
const editing = ref(null)
const overview = ref(null)

let request = 0  // only the newest answer is shown
async function load() {
  const mine = ++request
  loading.value = true
  try {
    const params = { skip: first.value, limit: rows.value }
    if (search.value.trim()) params.search = search.value.trim()
    if (vrf.value) params.vrf_id = vrf.value
    if (status.value) params.status = status.value
    if (family.value) params.family = family.value
    const res = await api.getIpamPrefixes(params)
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
function onCsvImported() { load(); loadOverview() }
let timer = null
function onSearch() { clearTimeout(timer); timer = setTimeout(reload, 300) }
function onPage(event) { first.value = event.first; rows.value = event.rows; load() }

const open = row => router.push(`/ipam/prefixes/${row.id}`)
function openForm(row) { editing.value = row; formOpen.value = true }
function onSaved() {
  message.value = { severity: 'success', text: t('ipam.saved') }
  load()
  loadOverview()
}

async function remove(row) {
  if (!window.confirm(t('ipam.prefixes.deleteConfirm', { name: row.prefix }))) return
  try {
    await api.deleteIpamPrefix(row.id)
    load()
    loadOverview()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

async function loadOverview() {
  try { overview.value = (await api.getIpamOverview()).data } catch (e) { overview.value = null }
}

onMounted(() => { load(); loadOverview(); loadLookups() })
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.search { flex: 1 1 18rem; max-width: 26rem; }
.filter { min-width: 12rem; }
.filter.narrow { min-width: 8rem; }
.rows :deep(tr) { cursor: pointer; }
.indent { display: inline-flex; align-items: center; gap: 0.4rem; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.muted-icon { color: var(--sk-text-muted, #6b7a71); }
.overview { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 1rem; }
.stat { min-width: 6.2rem; padding: 0.5rem 0.8rem; border: 1px solid var(--sk-border, #e1e7e3); border-radius: 8px; display: flex; flex-direction: column; background: var(--sk-surface, #fff); }
.stat strong { font-size: 1.3rem; line-height: 1.2; }
.stat span { font-size: 0.78rem; color: var(--sk-text-muted, #6b7a71); }
</style>
