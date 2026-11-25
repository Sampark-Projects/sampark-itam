<template>
  <Dialog :visible="visible" @update:visible="$emit('close')" :header="t('assettypes.import.title')" :modal="true" :style="{ width: '60vw' }">
    <div class="mb-3">
      <a :href="templateUrl" download class="p-button p-button-sm p-button-outlined">
        <i class="pi pi-download mr-2" />{{ t('assettypes.import.downloadTemplate') }}
      </a>
    </div>

    <div class="mb-4 p-3 bg-blue-50 border border-blue-200 rounded">
      <h4 class="text-blue-800 mb-2">{{ t('assettypes.import.importantInfo') }}</h4>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
        <div>
          <h5 class="font-semibold text-blue-700 mb-1">{{ t('assettypes.import.requiredFields') }}</h5>
          <ul class="text-blue-600">
            <li>{{ t('assettypes.import.nameRequired') }}</li>
            <li>{{ t('assettypes.import.labelRequired') }}</li>
          </ul>
        </div>
        <div>
          <h5 class="font-semibold text-blue-700 mb-1">{{ t('assettypes.import.validFormats') }}</h5>
          <ul class="text-blue-600">
            <li>{{ t('assettypes.import.purdueFormat') }}</li>
            <li>{{ t('assettypes.import.keyFormat') }}</li>
            <li>{{ t('assettypes.import.typeFormat') }}</li>
            <li>{{ t('assettypes.import.optionsFormat') }}</li>
          </ul>
        </div>
      </div>
      <div class="mt-3 text-blue-600 text-sm">
        <p>{{ t('assettypes.import.rowsNote') }}</p>
        <p class="mt-1">{{ t('assettypes.import.existingNote') }}</p>
        <p class="mt-1">{{ t('assettypes.import.blankNote') }}</p>
      </div>
    </div>

    <div class="mb-3">
      <input type="file" accept=".csv,.xlsx" @change="onFileChange" :aria-label="t('assettypes.import.fileInput')" />
    </div>
    <div v-if="loading" class="mb-3">
      <ProgressSpinner style="width:40px;height:40px" />
    </div>
    <div v-if="error" class="mb-3 text-red-600">
      <pre>{{ error }}</pre>
    </div>
    <div v-if="previewResult">
      <div v-if="previewResult.to_create && previewResult.to_create.length">
        <h4 class="mb-1">{{ t('assettypes.import.toCreate') }}</h4>
        <DataTable :value="previewResult.to_create" scrollable :scrollHeight="'20vh'">
          <Column field="name" :header="t('common.fields.name')" />
          <Column field="description" :header="t('common.fields.description')" />
          <Column field="purdue_level" :header="t('assettypes.fields.purdueLevel')" />
          <Column field="fields" :header="t('assettypes.customFields.title')" />
        </DataTable>
      </div>
      <div v-if="previewResult.to_update && previewResult.to_update.length">
        <h4 class="mt-3 mb-1">{{ t('assettypes.import.toUpdate') }}</h4>
        <DataTable :value="previewResult.to_update" scrollable :scrollHeight="'20vh'">
          <Column field="name" :header="t('common.fields.name')" />
          <Column field="diff" :header="t('assettypes.import.differences')">
            <template #body="{ data }">
              <ul>
                <li v-for="(change, key) in data.diff" :key="key">
                  <b>{{ key }}</b>: <span style="color: #888">{{ change.old ?? '-' }}</span> → <span style="color: #059669">{{ change.new }}</span>
                </li>
              </ul>
            </template>
          </Column>
        </DataTable>
      </div>
      <p v-if="nothingToDo" class="mt-3 text-sm">{{ t('assettypes.import.nothingToDo') }}</p>
      <div v-if="previewResult.errors && previewResult.errors.length">
        <h4 class="mt-3 mb-1 text-red-600">{{ t('assettypes.import.errors') }}</h4>
        <ul>
          <li v-for="(err, i) in previewResult.errors" :key="i">{{ t('assettypes.import.row') }} {{ err.row }}: {{ err.error }}</li>
        </ul>
      </div>
    </div>
    <template #footer>
      <Button :label="t('common.cancel')" class="p-button-text" @click="$emit('close')" />
      <Button :label="t('assettypes.import.confirm')" :disabled="isConfirmDisabled" @click="confirmImport" />
    </template>
  </Dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ProgressSpinner from 'primevue/progressspinner'
import api from '../../api/api'

const { t } = useI18n()
defineProps({
  visible: Boolean
})
const emit = defineEmits(['close', 'imported'])

const templateUrl = '/template_import_asset_type.csv'
const file = ref(null)
const loading = ref(false)
const error = ref('')
const previewResult = ref(null)

const nothingToDo = computed(() => {
  const p = previewResult.value
  return !!p && !p.error && !(p.to_create && p.to_create.length) && !(p.to_update && p.to_update.length) && !(p.errors && p.errors.length)
})

// the file is applied only when it is read, has something to do and has no errors
const isConfirmDisabled = computed(() => {
  const p = previewResult.value
  return !file.value || loading.value || !p || !!p.error || (error.value && error.value.length > 0) || nothingToDo.value ||
    !!(p.errors && p.errors.length)
})

async function onFileChange(e) {
  error.value = ''
  previewResult.value = null
  const f = e.target.files[0]
  if (!f) {
    file.value = null
    return
  }
  file.value = f
  loading.value = true
  try {
    const { data } = await api.previewAssetTypeImportXlsx(f)
    previewResult.value = data
    if (data.error) {
      error.value = data.error
    } else if (data.errors && data.errors.length) {
      error.value = data.errors.map(x => `${t('assettypes.import.row')} ${x.row}: ${x.error}`).join('\n')
    }
  } catch (err) {
    error.value = t('assettypes.import.readError')
  }
  loading.value = false
}

async function confirmImport() {
  if (!file.value) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.confirmAssetTypeImportXlsx(file.value)
    if (data.error) {
      error.value = data.error
    } else {
      emit('imported', data)
    }
  } catch (err) {
    error.value = t('assettypes.import.readError')
  }
  loading.value = false
}
</script>

<style scoped>
.text-red-600 {
  color: #dc2626;
}
</style>
