<template>
  <div>
    <p class="hint">{{ t('lifecycle.vendor.hint') }}</p>

    <div v-if="canWrite('lifecycle')" class="toolbar">
      <div class="flex gap-2 flex-wrap">
        <Button :label="t('lifecycle.vendor.add')" icon="pi pi-plus" @click="openNew" />
        <Button :label="t('lifecycle.vendor.import')" icon="pi pi-upload" severity="secondary" outlined :loading="importing" @click="fileInput.click()" />
        <Button :label="t('lifecycle.vendor.template')" icon="pi pi-download" text @click="downloadTemplate" />
      </div>
      <input ref="fileInput" type="file" accept=".csv,text/csv" class="hidden-input" @change="onFile" />
    </div>

    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <DataTable :value="entries" :loading="loading" size="small" paginator :rows="15" stripedRows>
      <template #empty>{{ t('lifecycle.vendor.empty') }}</template>
      <Column field="manufacturer_name" :header="t('lifecycle.vendor.manufacturer')" sortable />
      <Column field="model_pattern" :header="t('lifecycle.vendor.model')" sortable>
        <template #body="{ data }"><code>{{ data.model_pattern }}</code></template>
      </Column>
      <Column field="end_of_sale_date" :header="t('lifecycle.vendor.endOfSale')" sortable>
        <template #body="{ data }">{{ data.end_of_sale_date ? formatDate(data.end_of_sale_date) : '-' }}</template>
      </Column>
      <Column field="end_of_support_date" :header="t('lifecycle.vendor.endOfSupport')" sortable>
        <template #body="{ data }">{{ data.end_of_support_date ? formatDate(data.end_of_support_date) : '-' }}</template>
      </Column>
      <Column field="end_of_life_date" :header="t('lifecycle.vendor.endOfLife')" sortable>
        <template #body="{ data }">{{ data.end_of_life_date ? formatDate(data.end_of_life_date) : '-' }}</template>
      </Column>
      <Column field="source" :header="t('lifecycle.vendor.source')" />
      <Column v-if="canWrite('lifecycle')" :header="t('common.strings.actions')">
        <template #body="{ data }">
          <Button icon="pi pi-pencil" text rounded severity="info" @click="openEdit(data)" />
          <Button v-if="canDelete('lifecycle')" icon="pi pi-trash" text rounded severity="danger" @click="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <Dialog v-model:visible="showDialog" :header="editingId ? t('lifecycle.vendor.edit') : t('lifecycle.vendor.add')" modal :style="{ width: '90vw', maxWidth: '36rem' }">
      <div class="grid">
        <div class="col-12 md:col-6">
          <label for="v_maker">{{ t('lifecycle.vendor.manufacturer') }}</label>
          <Dropdown id="v_maker" v-model="form.manufacturer_name" :options="manufacturerOptions" filter showClear
                    :placeholder="t('lifecycle.vendor.selectManufacturer')" class="w-full" />
        </div>
        <div class="col-12 md:col-6">
          <label for="v_model">{{ t('lifecycle.vendor.model') }}</label>
          <InputText id="v_model" v-model="form.model_pattern" maxlength="100" class="w-full" placeholder="S7-12*" />
        </div>
        <div class="col-12 md:col-4">
          <label for="v_eos">{{ t('lifecycle.vendor.endOfSale') }}</label>
          <Calendar id="v_eos" v-model="form.end_of_sale_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
        </div>
        <div class="col-12 md:col-4">
          <label for="v_eosl">{{ t('lifecycle.vendor.endOfSupport') }}</label>
          <Calendar id="v_eosl" v-model="form.end_of_support_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
        </div>
        <div class="col-12 md:col-4">
          <label for="v_eol">{{ t('lifecycle.vendor.endOfLife') }}</label>
          <Calendar id="v_eol" v-model="form.end_of_life_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
        </div>
        <div class="col-12">
          <label for="v_source">{{ t('lifecycle.vendor.source') }}</label>
          <InputText id="v_source" v-model="form.source" maxlength="255" class="w-full" />
        </div>
        <div class="col-12">
          <label for="v_notes">{{ t('lifecycle.vendor.notes') }}</label>
          <Textarea id="v_notes" v-model="form.notes" rows="2" autoResize class="w-full" />
        </div>
      </div>
      <small v-if="formError" class="p-error block">{{ formError }}</small>
      <template #footer>
        <Button :label="t('common.actions.cancel')" text @click="showDialog = false" />
        <Button :label="t('common.actions.save')" :loading="saving" @click="save" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import Dropdown from 'primevue/dropdown'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Textarea from 'primevue/textarea'
import Calendar from 'primevue/calendar'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { parseLocalDate, formatLocalDate } from '../../../utils/localDate'
import { apiErrorText, downloadText } from '../../../utils/money'

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const { formatDate } = useDateFormatter()

const entries = ref([])
const loading = ref(false)
const message = ref(null)
const importing = ref(false)
const fileInput = ref(null)

const showDialog = ref(false)
const saving = ref(false)
const editingId = ref(null)
const formError = ref('')
const blank = () => ({ manufacturer_name: null, model_pattern: '', end_of_sale_date: null, end_of_support_date: null, end_of_life_date: null, source: '', notes: '' })
const form = ref(blank())

// The manufacturers come from the manufacturer master. An entry whose manufacturer is not in the master
// (for example from a CSV import) keeps its name in the list, so editing it does not lose the value.
const masterNames = ref([])
const manufacturerOptions = computed(() => {
  const names = new Set(masterNames.value)
  const current = (form.value.manufacturer_name || '').trim()
  if (current) names.add(current)
  return [...names].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
})

async function loadManufacturers() {
  try {
    const res = await api.getManufacturers()
    masterNames.value = (Array.isArray(res.data) ? res.data : []).map(m => m.name).filter(Boolean)
  } catch (err) {
    masterNames.value = []
  }
}

async function load() {
  loading.value = true
  try {
    const res = await api.getVendorLifecycleEntries()
    entries.value = Array.isArray(res.data) ? res.data : []
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    loading.value = false
  }
}

function openNew() {
  editingId.value = null
  form.value = blank()
  formError.value = ''
  showDialog.value = true
}

function openEdit(entry) {
  editingId.value = entry.id
  form.value = {
    manufacturer_name: entry.manufacturer_name,
    model_pattern: entry.model_pattern,
    end_of_sale_date: parseLocalDate(entry.end_of_sale_date),
    end_of_support_date: parseLocalDate(entry.end_of_support_date),
    end_of_life_date: parseLocalDate(entry.end_of_life_date),
    source: entry.source || '',
    notes: entry.notes || ''
  }
  formError.value = ''
  showDialog.value = true
}

async function save() {
  formError.value = ''
  const f = form.value
  if (!(f.manufacturer_name || '').trim() || !f.model_pattern.trim()) {
    formError.value = t('lifecycle.vendor.required')
    return
  }
  if (!f.end_of_sale_date && !f.end_of_support_date && !f.end_of_life_date) {
    formError.value = t('lifecycle.vendor.dateRequired')
    return
  }
  const payload = {
    manufacturer_name: f.manufacturer_name,
    model_pattern: f.model_pattern,
    end_of_sale_date: formatLocalDate(f.end_of_sale_date),
    end_of_support_date: formatLocalDate(f.end_of_support_date),
    end_of_life_date: formatLocalDate(f.end_of_life_date),
    source: f.source || null,
    notes: f.notes || null
  }
  saving.value = true
  try {
    if (editingId.value) await api.updateVendorLifecycleEntry(editingId.value, payload)
    else await api.createVendorLifecycleEntry(payload)
    showDialog.value = false
    await load()
  } catch (err) {
    formError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

async function remove(entry) {
  if (!window.confirm(t('lifecycle.vendor.deleteConfirm'))) return
  try {
    await api.deleteVendorLifecycleEntry(entry.id)
    await load()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

async function onFile(event) {
  const file = event.target.files && event.target.files[0]
  event.target.value = ''
  if (!file) return
  importing.value = true
  try {
    const res = await api.importVendorLifecycleCsv(file)
    const r = res.data || {}
    let text = t('lifecycle.vendor.importResult', { created: r.created, updated: r.updated })
    if (r.errors && r.errors.length) {
      const details = r.errors.slice(0, 5).map(e => `#${e.line} ${e.error}`).join('; ')
      text += ' ' + t('lifecycle.vendor.importErrors', { count: r.errors.length, details })
    }
    message.value = { severity: r.errors && r.errors.length ? 'warn' : 'success', text }
    await load()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    importing.value = false
  }
}

function downloadTemplate() {
  const csv = 'manufacturer,model,end_of_sale,end_of_support,end_of_life,source,notes\r\n' +
    'Siemens,S7-12*,2024-01-31,2027-12-31,2030-12-31,Vendor lifecycle page,\r\n'
  downloadText('vendor-lifecycle-template.csv', csv)
}

onMounted(() => { load(); loadManufacturers() })
</script>

<style scoped>
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
.hidden-input { display: none; }
label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
</style>
