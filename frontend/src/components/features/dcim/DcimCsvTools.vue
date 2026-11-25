<!--
  - DcimCsvTools.vue
  - The "Export CSV" and "Import CSV" buttons of the DCIM pages (racks, device types, rack positions). The export is for everyone
  - who reads DCIM; the import (full administration) opens a dialog: choose the file, preview what would happen, then import.
-->
<template>
  <span class="csv-tools">
    <Button :label="exportLabel || t('dcim.csv.export')" icon="pi pi-file-export" outlined :loading="exporting" @click="download" />
    <Button v-if="!exportOnly && canBulkOperate('dcim')" :label="t('dcim.csv.import')" icon="pi pi-file-import" outlined @click="open = true" />

    <Dialog v-model:visible="open" modal :header="t(`dcim.csv.title.${kind}`)" :style="{ width: '58rem', maxWidth: '96vw' }">
      <p class="hint">{{ t('dcim.csv.hint') }}</p>
      <p class="hint"><strong>{{ t('dcim.csv.columnsLabel') }}</strong> <span class="mono">{{ t(`dcim.csv.columns.${kind}`) }}</span></p>
      <p v-if="kind === 'rack-positions'" class="hint">{{ t('dcim.csv.positionsHint') }}</p>
      <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
      <Message v-if="done" severity="success" :closable="false">{{ t('dcim.csv.done', { created: done.create, updated: done.update, skipped: done.skipped_duplicate + done.skipped_invalid }) }}</Message>

      <div class="options">
        <input ref="picker" type="file" accept=".csv,text/csv,text/plain" @change="onFile" />
        <label class="check"><Checkbox v-model="options.update_existing" binary @change="changed" /><span>{{ t('dcim.csv.updateExisting') }}</span></label>
        <small class="muted">{{ t('dcim.csv.updateHint') }}</small>
        <label class="check"><Checkbox v-model="options.skip_invalid" binary @change="changed" /><span>{{ t('dcim.csv.skipInvalid') }}</span></label>
      </div>

      <div v-if="result" class="summary">
        <Tag :value="`${t('dcim.csv.actions.create')}: ${result.summary.create}`" severity="success" />
        <Tag :value="`${t('dcim.csv.actions.update')}: ${result.summary.update}`" severity="info" />
        <Tag :value="`${t('dcim.csv.actions.skipped_duplicate')}: ${result.summary.skipped_duplicate}`" severity="warning" />
        <Tag :value="`${t('dcim.csv.actions.skipped_invalid')}: ${result.summary.skipped_invalid}`" severity="danger" />
        <span class="muted">{{ t('dcim.csv.rows', { n: result.summary.rows }) }}</span>
        <span v-if="result.summary.ignored_columns.length" class="muted">· {{ t('dcim.csv.ignored', { names: result.summary.ignored_columns.join(', ') }) }}</span>
      </div>
      <Message v-if="result && result.summary.skipped_invalid && !options.skip_invalid" severity="warn" :closable="false">{{ t('dcim.csv.invalidBlocks') }}</Message>

      <DataTable v-if="result" :value="result.items" size="small" scrollable scrollHeight="18rem">
        <template #empty>{{ t('dcim.csv.nothing') }}</template>
        <Column field="row" :header="t('dcim.csv.line')" style="width: 5rem" />
        <Column :header="t('dcim.csv.action')" style="width: 9rem">
          <template #body="{ data }"><Tag :value="t(`dcim.csv.actions.${data.action}`)" :severity="severity(data.action)" /></template>
        </Column>
        <Column :header="t('dcim.csv.item')" style="width: 14rem"><template #body="{ data }"><span class="mono">{{ data.label }}</span></template></Column>
        <Column field="reason" :header="t('dcim.csv.reason')" />
      </DataTable>
      <small v-if="result && result.truncated" class="muted">{{ t('dcim.csv.truncated') }}</small>

      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="open = false" />
        <Button :label="t('dcim.csv.preview')" icon="pi pi-eye" outlined :loading="loading" :disabled="!file" @click="preview" />
        <Button :label="t('dcim.csv.run')" icon="pi pi-upload" severity="success" :loading="running"
                :disabled="!result || !(result.summary.create || result.summary.update) || (result.summary.skipped_invalid && !options.skip_invalid)" @click="run" />
      </template>
    </Dialog>
  </span>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import Checkbox from 'primevue/checkbox'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'

// kind: a name of the API (racks, device-types, rack-positions, cables, interfaces, mac-addresses, mac-bindings);
// exportOnly: a view that can only be exported (mac-bindings); exportLabel: a button text for pages with two files
const props = defineProps({ kind: { type: String, required: true }, exportOnly: { type: Boolean, default: false }, exportLabel: { type: String, default: '' } })
const emit = defineEmits(['imported', 'error'])
const { t } = useI18n()
const { canBulkOperate } = usePermissions()

const open = ref(false)
const picker = ref(null)
const file = ref(null)
const options = ref({ update_existing: false, skip_invalid: false })
const result = ref(null)
const done = ref(null)
const error = ref('')
const exporting = ref(false)
const loading = ref(false)
const running = ref(false)

const severity = action => ({ create: 'success', update: 'info', skipped_duplicate: 'warning', skipped_invalid: 'danger' }[action])

watch(open, isOpen => {
  if (!isOpen) return
  file.value = null
  result.value = null
  done.value = null
  error.value = ''
  options.value = { update_existing: false, skip_invalid: false }
  if (picker.value) picker.value.value = ''
})

function changed() { result.value = null; done.value = null }
function onFile(event) { file.value = event.target.files?.[0] || null; changed() }

async function download() {
  exporting.value = true
  try {
    const res = await api.exportDcimCsv(props.kind)
    const url = URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `dcim-${props.kind}-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (err) {
    emit('error', apiErrorText(err, t))
  } finally {
    exporting.value = false
  }
}

async function call(dryRun) {
  error.value = ''
  return (await api.importDcimCsv(props.kind, file.value, { dry_run: dryRun, ...options.value })).data
}

async function preview() {
  loading.value = true
  done.value = null
  try { result.value = await call(true) } catch (err) { result.value = null; error.value = apiErrorText(err, t) } finally { loading.value = false }
}

async function run() {
  running.value = true
  try {
    const res = await call(false)
    done.value = res.summary
    result.value = null
    emit('imported', res.summary)
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    running.value = false
  }
}
</script>

<style scoped>
.csv-tools { display: inline-flex; gap: 0.5rem; }
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.options { display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 1rem; }
.check { display: inline-flex; align-items: center; gap: 0.5rem; cursor: pointer; }
.summary { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.75rem; }
.muted { color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
</style>
