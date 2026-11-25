<!--
  - DcimDeviceTypes.vue
  - The device types: manufacturer + model with the height in rack units. Made from the models found on the assets; the height is
  - filled in here or from a CSV file, and decides how much rack space a device takes.
-->
<template>
  <div class="dcim-page">
    <div class="page-header">
      <h1>{{ t('dcim.types.title') }}</h1>
      <div class="actions">
        <DcimCsvTools kind="device-types" @imported="onImported" @error="msg => message = { severity: 'error', text: msg }" />
        <Button v-if="canWrite('dcim')" :label="t('dcim.types.new')" icon="pi pi-plus" severity="success" @click="openForm(null)" />
      </div>
    </div>
    <p class="hint">{{ t('dcim.types.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div class="toolbar">
      <span class="p-input-icon-left search">
        <i class="pi pi-search" />
        <InputText v-model="search" :placeholder="t('dcim.types.searchPlaceholder')" class="w-full" @input="onSearch" />
      </span>
      <Dropdown v-model="makerFilter" :options="lookups.manufacturers.value" optionLabel="label" optionValue="value" showClear filter
                :placeholder="t('dcim.fields.manufacturer')" class="filter" @change="reload" />
      <label class="check"><Checkbox v-model="heightMissing" binary @change="reload" /><span>{{ t('dcim.types.onlyNoHeight') }}</span></label>
    </div>

    <DataTable :value="types" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
               :rowsPerPageOptions="[25, 50, 100]" @page="onPage">
      <template #empty>{{ t('dcim.types.empty') }}</template>
      <Column field="manufacturer_name" :header="t('dcim.fields.manufacturer')" style="width: 12rem" />
      <Column :header="t('dcim.fields.model')">
        <template #body="{ data }"><strong>{{ data.model }}</strong></template>
      </Column>
      <Column :header="t('dcim.fields.height')" style="width: 8rem">
        <template #body="{ data }">
          <span v-if="data.u_height !== null">{{ formatUnits(data.u_height) }}U</span>
          <Tag v-else :value="t('dcim.types.heightUnknown')" severity="warning" />
        </template>
      </Column>
      <Column :header="t('dcim.fields.fullDepth')" style="width: 8rem"><template #body="{ data }">{{ data.is_full_depth ? t('dcim.yes') : t('dcim.no') }}</template></Column>
      <Column field="part_number" :header="t('dcim.fields.partNumber')" style="width: 10rem" />
      <Column field="asset_count" :header="t('dcim.types.assets')" style="width: 7rem" />
      <Column v-if="canWrite('dcim')" style="width: 6rem">
        <template #body="{ data }">
          <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openForm(data)" />
          <Button v-if="canDelete('dcim')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <DcimDeviceTypeForm v-model:visible="formOpen" :type="editing" :manufacturers="lookups.manufacturers.value" @saved="onSaved" />
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import InputText from 'primevue/inputtext'
import Dropdown from 'primevue/dropdown'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import DcimCsvTools from '../components/features/dcim/DcimCsvTools.vue'
import DcimDeviceTypeForm from '../components/forms/DcimDeviceTypeForm.vue'
import { usePermissions } from '../composables/usePermissions'
import { useDcimLookups, formatUnits } from '../composables/useDcim'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const route = useRoute()
const { canWrite, canDelete } = usePermissions()
const lookups = useDcimLookups()

const types = ref([])
const total = ref(0)
const loading = ref(false)
const message = ref(null)
const search = ref('')
const makerFilter = ref(null)
const heightMissing = ref(route.query.height_missing === '1')
const rows = ref(25)
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
    if (makerFilter.value) params.manufacturer_id = makerFilter.value
    if (heightMissing.value) params.height_missing = true
    const res = await api.getDcimDeviceTypes(params)
    if (mine !== request) return
    types.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (err) {
    if (mine === request) message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    if (mine === request) loading.value = false
  }
}

let timer = null
function reload() { first.value = 0; load() }
function onSearch() { clearTimeout(timer); timer = setTimeout(reload, 300) }
function onPage(event) { first.value = event.first; rows.value = event.rows; load() }

function openForm(row) { editing.value = row; formOpen.value = true }
function onSaved() { message.value = { severity: 'success', text: t('dcim.saved') }; load() }
function onImported(summary) { message.value = { severity: 'success', text: t('dcim.csv.done', { created: summary.create, updated: summary.update, skipped: summary.skipped_duplicate + summary.skipped_invalid }) }; load() }

async function remove(row) {
  if (!window.confirm(t('dcim.types.deleteConfirm', { name: `${row.manufacturer_name} ${row.model}` }))) return
  try {
    await api.deleteDcimDeviceType(row.id)
    message.value = { severity: 'success', text: t('dcim.deleted') }
    load()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

// the list and the manufacturer dropdown start together and fill as their own answers arrive
onMounted(() => { load(); lookups.load({ manufacturers: true }) })
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
.actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.search { flex: 1 1 16rem; max-width: 24rem; }
.filter { min-width: 12rem; }
.check { display: inline-flex; align-items: center; gap: 0.5rem; cursor: pointer; }
</style>
