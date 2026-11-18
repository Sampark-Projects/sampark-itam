<!--
  - IpamRanges.vue
  - IP ranges: a paged, filterable list with utilization.
-->
<template>
  <div class="ipam-page">
    <div class="page-header">
      <h1>{{ t('ipam.ranges.title') }}</h1>
      <Button v-if="canWrite('ipam')" :label="t('ipam.ranges.new')" icon="pi pi-plus" severity="success" @click="openForm(null)" />
    </div>
    <p class="hint">{{ t('ipam.ranges.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div class="toolbar">
      <span class="p-input-icon-left search">
        <i class="pi pi-search" />
        <InputText v-model="search" :placeholder="t('ipam.ranges.searchPlaceholder')" class="w-full" @input="onSearch" />
      </span>
      <Dropdown v-model="vrf" :options="vrfOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.fields.allVrfs')" class="filter" @change="reload" />
      <Dropdown v-model="status" :options="rangeStatusOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.fields.allStatuses')" class="filter" @change="reload" />
    </div>

    <DataTable :value="items" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
               :rowsPerPageOptions="[25, 50, 100]" @page="onPage">
      <template #empty>{{ t('ipam.ranges.empty') }}</template>
      <Column :header="t('ipam.ranges.fields.range')">
        <template #body="{ data }"><strong class="mono">{{ data.label }}</strong></template>
      </Column>
      <Column :header="t('ipam.fields.vrf')" style="width: 9rem">
        <template #body="{ data }">{{ data.vrf_name || t('ipam.fields.globalTable') }}</template>
      </Column>
      <Column :header="t('ipam.fields.status')" style="width: 8rem">
        <template #body="{ data }"><Tag :value="t(`ipam.statuses.${data.status}`)" :severity="statusSeverity(data.status)" /></template>
      </Column>
      <Column field="size" :header="t('ipam.ranges.fields.size')" style="width: 6rem" />
      <Column :header="t('ipam.prefixes.utilization')" style="width: 11rem">
        <template #body="{ data }"><IpamUtilization :value="data.utilization" /></template>
      </Column>
      <Column field="available_ips" :header="t('ipam.prefixes.availableIps')" style="width: 7rem" />
      <Column :header="t('ipam.ranges.flags')" style="width: 10rem">
        <template #body="{ data }">
          <Tag v-if="data.mark_populated" :value="t('ipam.ranges.populated')" severity="warning" class="chip" />
          <Tag v-if="data.mark_utilized" :value="t('ipam.ranges.utilized')" severity="info" class="chip" />
        </template>
      </Column>
      <Column field="role_name" :header="t('ipam.fields.role')" style="width: 8rem" />
      <Column field="description" :header="t('ipam.fields.description')" />
      <Column v-if="canWrite('ipam')" style="width: 6rem">
        <template #body="{ data }">
          <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openForm(data)" />
          <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <IpamRangeForm v-model:visible="formOpen" :range="editing" @saved="onSaved" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import IpamRangeForm from '../components/forms/IpamRangeForm.vue'
import IpamUtilization from '../components/features/ipam/IpamUtilization.vue'
import { usePermissions } from '../composables/usePermissions'
import { useIpamChoices, useIpamLookups, statusSeverity } from '../composables/useIpam'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const { rangeStatusOptions } = useIpamChoices()
const { vrfs: vrfOptions, load: loadLookups } = useIpamLookups()

const items = ref([])
const total = ref(0)
const loading = ref(false)
const message = ref(null)
const search = ref('')
const vrf = ref(null)
const status = ref(null)
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
    if (vrf.value) params.vrf_id = vrf.value
    if (status.value) params.status = status.value
    const res = await api.getIpamRanges(params)
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
function openForm(row) { editing.value = row; formOpen.value = true }
function onSaved() { message.value = { severity: 'success', text: t('ipam.saved') }; load() }

async function remove(row) {
  if (!window.confirm(t('ipam.ranges.deleteConfirm', { name: row.label }))) return
  try {
    await api.deleteIpamRange(row.id)
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
.chip { margin-right: 0.3rem; }
</style>
