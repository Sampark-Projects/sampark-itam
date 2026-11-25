<!--
  - DcimRackRoles.vue
  - The rack roles (what a rack is used for), in a dialog: a short list with add, edit and delete.
-->
<template>
  <Dialog :visible="visible" modal :header="t('dcim.roles.title')" :style="{ width: '44rem', maxWidth: '96vw' }" @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>

    <DataTable :value="roles" :loading="loading" dataKey="id" size="small">
      <template #empty>{{ t('dcim.roles.empty') }}</template>
      <Column :header="t('dcim.fields.name')">
        <template #body="{ data }">
          <span class="swatch" :style="{ background: data.color || '#cbd5e1' }"></span>
          <strong>{{ data.name }}</strong>
        </template>
      </Column>
      <Column field="rack_count" :header="t('dcim.roles.racks')" style="width: 6rem" />
      <Column field="description" :header="t('dcim.fields.description')" />
      <Column v-if="canWrite('dcim')" style="width: 6rem">
        <template #body="{ data }">
          <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="edit(data)" />
          <Button v-if="canDelete('dcim')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <form v-if="canWrite('dcim')" class="role-form" @submit.prevent="save">
      <h4>{{ editing ? t('dcim.roles.edit') : t('dcim.roles.new') }}</h4>
      <div class="row">
        <InputText v-model="form.name" maxlength="100" :placeholder="t('dcim.fields.name')" />
        <input v-model="form.color" type="color" class="color" :aria-label="t('dcim.fields.color')" />
        <InputText v-model="form.description" maxlength="200" :placeholder="t('dcim.fields.description')" class="grow" />
        <Button type="submit" :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" :disabled="!form.name.trim()" />
        <Button v-if="editing" type="button" :label="t('common.actions.cancel')" text severity="secondary" @click="reset" />
      </div>
    </form>
  </Dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'changed'])
const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()

const roles = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const editing = ref(null)
const form = ref({ name: '', color: '#6366f1', description: '' })

async function load() {
  loading.value = true
  try { roles.value = (await api.getDcimRackRoles()).data || [] } catch (err) { error.value = apiErrorText(err, t) } finally { loading.value = false }
}

function reset() { editing.value = null; form.value = { name: '', color: '#6366f1', description: '' } }
function edit(row) { editing.value = row; form.value = { name: row.name, color: row.color || '#6366f1', description: row.description || '' } }

watch(() => props.visible, open => { if (open) { error.value = ''; reset(); load() } })

async function save() {
  error.value = ''
  saving.value = true
  try {
    if (editing.value) await api.updateDcimRackRole(editing.value.id, { ...form.value, slug: null })
    else await api.createDcimRackRole({ ...form.value })
    reset()
    await load()
    emit('changed')
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  if (!window.confirm(t('dcim.roles.deleteConfirm', { name: row.name }))) return
  error.value = ''
  try {
    await api.deleteDcimRackRole(row.id)
    await load()
    emit('changed')
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}
</script>

<style scoped>
.swatch { display: inline-block; width: 0.9rem; height: 0.9rem; border-radius: 50%; margin-right: 0.5rem; vertical-align: middle; }
.role-form { margin-top: 1rem; }
.role-form h4 { margin: 0 0 0.5rem; font-size: 0.95rem; }
.row { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
.row .grow { flex: 1 1 10rem; }
.color { width: 2.4rem; height: 2.2rem; border: 1px solid var(--sk-border, #d7e0da); border-radius: 6px; padding: 0.1rem; background: transparent; }
</style>
