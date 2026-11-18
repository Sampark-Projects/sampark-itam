<!--
  - IpamAddresses.vue
  - IP addresses: a paged, filterable list. An address may be assigned to an asset interface.
-->
<template>
  <div class="ipam-page">
    <div class="page-header">
      <h1>{{ t('ipam.addresses.title') }}</h1>
      <div class="flex gap-2">
        <IpamCsvTools kind="ip-addresses" @imported="onImported" @error="text => message = { severity: 'error', text }" />
        <Button v-if="canBulkOperate('ipam')" :label="t('ipam.addresses.importButton')" icon="pi pi-download" outlined @click="importOpen = true" />
        <Button v-if="canWrite('ipam')" :label="t('ipam.addresses.new')" icon="pi pi-plus" severity="success" @click="openForm(null)" />
      </div>
    </div>
    <p class="hint">{{ t('ipam.addresses.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div class="toolbar">
      <span class="p-input-icon-left search">
        <i class="pi pi-search" />
        <InputText v-model="search" :placeholder="t('ipam.addresses.searchPlaceholder')" class="w-full" @input="onSearch" />
      </span>
      <InputText v-model="within" :placeholder="t('ipam.addresses.withinPlaceholder')" class="filter" @input="onSearch" />
      <Dropdown v-model="vrf" :options="vrfOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.fields.allVrfs')" class="filter" @change="reload" />
      <Dropdown v-model="status" :options="ipStatusOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.fields.allStatuses')" class="filter" @change="reload" />
      <Dropdown v-model="assigned" :options="assignedOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.addresses.anyAssignment')" class="filter" @change="reload" />
    </div>

    <DataTable :value="items" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
               :rowsPerPageOptions="[25, 50, 100]" @page="onPage">
      <template #empty>{{ t('ipam.addresses.empty') }}</template>
      <Column :header="t('ipam.addresses.fields.address')">
        <template #body="{ data }"><strong class="mono">{{ data.address }}</strong></template>
      </Column>
      <Column :header="t('ipam.fields.vrf')" style="width: 9rem">
        <template #body="{ data }">{{ data.vrf_name || t('ipam.fields.globalTable') }}</template>
      </Column>
      <Column :header="t('ipam.fields.status')" style="width: 8rem">
        <template #body="{ data }"><Tag :value="t(`ipam.statuses.${data.status}`)" :severity="statusSeverity(data.status)" /></template>
      </Column>
      <Column :header="t('ipam.fields.role')" style="width: 8rem">
        <template #body="{ data }">{{ data.role ? t(`ipam.ipRoles.${data.role}`) : '' }}</template>
      </Column>
      <Column field="dns_name" :header="t('ipam.addresses.fields.dnsName')" />
      <Column :header="t('ipam.addresses.fields.assignedTo')">
        <template #body="{ data }">
          <router-link v-if="data.assigned_to" :to="`/assets/${data.assigned_to.asset_id}`">{{ data.assigned_to.asset_name }} / {{ data.assigned_to.interface_name }}</router-link>
          <router-link v-else-if="data.fhrp_group_id" :to="`/ipam/fhrp-groups/${data.fhrp_group_id}`">{{ data.fhrp_group }}</router-link>
        </template>
      </Column>
      <Column :header="t('ipam.addresses.fields.natInside')" style="width: 10rem">
        <template #body="{ data }"><span class="mono">{{ data.nat_inside_address || '' }}</span></template>
      </Column>
      <Column field="description" :header="t('ipam.fields.description')" />
      <Column v-if="canWrite('ipam')" style="width: 6rem">
        <template #body="{ data }">
          <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openForm(data)" />
          <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <IpamAddressForm v-model:visible="formOpen" :address="editing" @saved="onSaved" />
    <IpamInterfaceImport v-model:visible="importOpen" @imported="onImported" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import IpamAddressForm from '../components/forms/IpamAddressForm.vue'
import IpamCsvTools from '../components/features/ipam/IpamCsvTools.vue'
import IpamInterfaceImport from '../components/features/ipam/IpamInterfaceImport.vue'
import { usePermissions } from '../composables/usePermissions'
import { useIpamChoices, useIpamLookups, statusSeverity } from '../composables/useIpam'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const { canWrite, canDelete, canBulkOperate } = usePermissions()
const importOpen = ref(false)
const { ipStatusOptions } = useIpamChoices()
const { vrfs: vrfOptions, load: loadLookups } = useIpamLookups()
const assignedOptions = computed(() => [{ value: true, label: t('ipam.addresses.assigned') }, { value: false, label: t('ipam.addresses.unassigned') }])

const items = ref([])
const total = ref(0)
const loading = ref(false)
const message = ref(null)
const search = ref('')
const within = ref('')
const vrf = ref(null)
const status = ref(null)
const assigned = ref(null)
const rows = ref(50)
const first = ref(0)
const formOpen = ref(false)
const editing = ref(null)

let request = 0
async function load() {
  const mine = ++request
  loading.value = true
  try {
    const params = { skip: first.value, limit: rows.value }
    if (search.value.trim()) params.search = search.value.trim()
    if (within.value.trim()) params.within = within.value.trim()
    if (vrf.value) params.vrf_id = vrf.value
    if (status.value) params.status = status.value
    if (assigned.value !== null) params.assigned = assigned.value
    const res = await api.getIpamAddresses(params)
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
function onSearch() { clearTimeout(timer); timer = setTimeout(reload, 350) }
function onPage(event) { first.value = event.first; rows.value = event.rows; load() }
function openForm(row) { editing.value = row; formOpen.value = true }
function onSaved() { message.value = { severity: 'success', text: t('ipam.saved') }; load() }
function onImported() { load(); loadLookups() }

async function remove(row) {
  if (!window.confirm(t('ipam.addresses.deleteConfirm', { name: row.address }))) return
  try {
    await api.deleteIpamAddress(row.id)
    load()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

onMounted(() => { load(); loadLookups() })
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.search { flex: 1 1 16rem; max-width: 24rem; }
.filter { min-width: 11rem; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
</style>
