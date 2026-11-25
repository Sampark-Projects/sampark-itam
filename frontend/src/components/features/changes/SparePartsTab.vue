<template>
  <div>
    <p class="hint">{{ t('changes.parts.hint') }}</p>
    <div v-if="canWrite('maintenance')" class="toolbar">
      <Button :label="t('changes.parts.new')" icon="pi pi-plus" @click="openNew" />
    </div>
    <Message v-if="message" severity="error" :closable="true" @close="message = null">{{ message }}</Message>

    <DataTable :value="items" :loading="loading" size="small" paginator :rows="15" stripedRows>
      <template #empty>{{ t('changes.parts.empty') }}</template>
      <Column field="name" :header="t('changes.parts.name')" sortable />
      <Column field="part_number" :header="t('changes.parts.partNumber')" sortable />
      <Column field="manufacturer_name" :header="t('changes.parts.manufacturer')" />
      <Column field="quantity" :header="t('changes.parts.quantity')" sortable>
        <template #body="{ data }">
          {{ data.quantity }}
          <Tag v-if="data.low_stock" :value="t('changes.parts.lowStock')" severity="warning" />
        </template>
      </Column>
      <Column field="storage_location" :header="t('changes.parts.location')" />
      <Column :header="t('changes.parts.assets')">
        <template #body="{ data }">
          <router-link v-for="a in data.assets.slice(0, 3)" :key="a.id" :to="`/assets/${a.id}`" class="asset-link">{{ a.name }}</router-link>
          <small v-if="data.assets.length > 3" class="muted">+{{ data.assets.length - 3 }}</small>
        </template>
      </Column>
      <Column v-if="canWrite('maintenance')">
        <template #body="{ data }">
          <Button icon="pi pi-pencil" text rounded severity="info" @click="openEdit(data)" />
          <Button v-if="canDelete('maintenance')" icon="pi pi-trash" text rounded severity="danger" @click="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <Dialog v-model:visible="showForm" :header="editingId ? t('changes.parts.edit') : t('changes.parts.new')" modal :style="{ width: '90vw', maxWidth: '38rem' }">
      <div class="grid">
        <div class="col-12 md:col-6">
          <label>{{ t('changes.parts.name') }} *</label>
          <InputText v-model="form.name" maxlength="150" class="w-full" />
        </div>
        <div class="col-12 md:col-6">
          <label>{{ t('changes.parts.partNumber') }}</label>
          <InputText v-model="form.part_number" maxlength="100" class="w-full" />
        </div>
        <div class="col-12 md:col-6">
          <label>{{ t('changes.parts.manufacturer') }}</label>
          <InputText v-model="form.manufacturer_name" maxlength="255" class="w-full" />
        </div>
        <div class="col-12 md:col-6">
          <label>{{ t('changes.parts.location') }}</label>
          <InputText v-model="form.storage_location" maxlength="255" class="w-full" />
        </div>
        <div class="col-6">
          <label>{{ t('changes.parts.quantity') }}</label>
          <InputNumber v-model="form.quantity" :min="0" :useGrouping="false" class="w-full" />
        </div>
        <div class="col-6">
          <label>{{ t('changes.parts.minQuantity') }}</label>
          <InputNumber v-model="form.min_quantity" :min="0" :useGrouping="false" class="w-full" />
        </div>
        <div class="col-12">
          <label>{{ t('changes.parts.assets') }}</label>
          <MultiSelect v-model="form.asset_ids" :options="assetOptions" optionLabel="label" optionValue="value" display="chip" filter class="w-full" />
        </div>
        <div class="col-12">
          <label>{{ t('changes.parts.notes') }}</label>
          <Textarea v-model="form.notes" rows="2" autoResize class="w-full" />
        </div>
      </div>
      <small v-if="formError" class="p-error block">{{ formError }}</small>
      <template #footer>
        <Button :label="t('common.actions.cancel')" text @click="showForm = false" />
        <Button :label="t('common.actions.save')" :loading="saving" @click="save" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Textarea from 'primevue/textarea'
import MultiSelect from 'primevue/multiselect'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()

const items = ref([])
const loading = ref(false)
const message = ref(null)
const assets = ref([])
const assetOptions = computed(() => assets.value.map(a => ({ value: a.id, label: a.tag ? `${a.name} (${a.tag})` : a.name })))

const showForm = ref(false)
const editingId = ref(null)
const saving = ref(false)
const formError = ref('')
const blank = () => ({ name: '', part_number: '', manufacturer_name: '', quantity: 0, min_quantity: 0, storage_location: '', notes: '', asset_ids: [] })
const form = ref(blank())

async function load() {
  loading.value = true
  try {
    const res = await api.getSpareParts()
    items.value = Array.isArray(res.data) ? res.data : []
  } catch (err) {
    message.value = apiErrorText(err, t)
  } finally {
    loading.value = false
  }
}

function openNew() {
  editingId.value = null
  form.value = blank()
  formError.value = ''
  showForm.value = true
}

function openEdit(part) {
  editingId.value = part.id
  form.value = {
    name: part.name, part_number: part.part_number || '', manufacturer_name: part.manufacturer_name || '',
    quantity: part.quantity, min_quantity: part.min_quantity, storage_location: part.storage_location || '',
    notes: part.notes || '', asset_ids: part.assets.map(a => a.id)
  }
  formError.value = ''
  showForm.value = true
}

async function save() {
  formError.value = ''
  const f = form.value
  if (!f.name.trim()) {
    formError.value = t('changes.parts.required')
    return
  }
  saving.value = true
  try {
    const payload = {
      ...f, part_number: f.part_number || null, manufacturer_name: f.manufacturer_name || null,
      storage_location: f.storage_location || null, notes: f.notes || null,
      quantity: f.quantity || 0, min_quantity: f.min_quantity || 0
    }
    if (editingId.value) await api.updateSparePart(editingId.value, payload)
    else await api.createSparePart(payload)
    showForm.value = false
    await load()
  } catch (err) {
    formError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

async function remove(part) {
  if (!window.confirm(t('changes.parts.deleteConfirm'))) return
  try {
    await api.deleteSparePart(part.id)
    await load()
  } catch (err) {
    message.value = apiErrorText(err, t)
  }
}

onMounted(async () => {
  load()
  try {
    const res = await api.getAssets({ limit: 500 })
    assets.value = res.data && Array.isArray(res.data.data) ? res.data.data : []
  } catch (e) {
    assets.value = []
  }
})
</script>

<style scoped>
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.toolbar { margin-bottom: 0.75rem; }
label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.asset-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; margin-right: 0.5rem; }
.asset-link:hover { text-decoration: underline; }
</style>
