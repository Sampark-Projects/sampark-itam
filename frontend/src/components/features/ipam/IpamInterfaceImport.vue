<!--
  - IpamInterfaceImport.vue
  - Create IPAM addresses from the IP addresses typed on asset interfaces: choose the options, preview what would
  - happen, then import. Needs full administration of IPAM.
-->
<template>
  <Dialog :visible="visible" modal :header="t('ipam.import.title')" :style="{ width: '62rem', maxWidth: '96vw' }" @update:visible="v => emit('update:visible', v)">
    <p class="hint">{{ t('ipam.import.hint') }}</p>
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <Message v-if="done" severity="success" :closable="false">{{ t('ipam.import.done', { created: done.create, linked: done.link, prefixes: done.prefixes_to_create }) }}</Message>

    <div class="options">
      <div class="p-field">
        <label>{{ t('ipam.fields.vrf') }}</label>
        <Dropdown v-model="options.vrf_id" :options="vrfs" optionLabel="label" optionValue="value" showClear filter
                  :placeholder="t('ipam.fields.globalTable')" class="w-full" @change="changed" />
      </div>
      <label class="check"><Checkbox v-model="options.per_site" binary @change="changed" /><span>{{ t('ipam.import.perSite') }}</span></label>
      <small class="muted">{{ t('ipam.import.perSiteHint') }}</small>
      <label class="check"><Checkbox v-model="options.create_prefixes" binary @change="changed" /><span>{{ t('ipam.import.createPrefixes') }}</span></label>
    </div>

    <div v-if="result" class="summary">
      <Tag :value="`${t('ipam.import.actions.create')}: ${result.summary.create}`" severity="success" />
      <Tag :value="`${t('ipam.import.actions.link')}: ${result.summary.link}`" severity="info" />
      <Tag :value="`${t('ipam.import.actions.already_imported')}: ${result.summary.already_imported}`" severity="secondary" />
      <Tag :value="`${t('ipam.import.actions.skipped_duplicate')}: ${result.summary.skipped_duplicate}`" severity="warning" />
      <Tag :value="`${t('ipam.import.actions.skipped_invalid')}: ${result.summary.skipped_invalid}`" severity="danger" />
      <span class="muted">{{ t('ipam.import.found', { interfaces: result.summary.interfaces, addresses: result.summary.addresses }) }}</span>
      <span v-if="result.summary.prefixes_to_create" class="muted">· {{ t('ipam.import.prefixes', { n: result.summary.prefixes_to_create }) }}</span>
      <span v-if="result.summary.vrfs_to_create.length" class="muted">· {{ t('ipam.import.vrfs', { names: result.summary.vrfs_to_create.join(', ') }) }}</span>
    </div>

    <DataTable v-if="result" :value="result.items" size="small" scrollable scrollHeight="18rem" class="items">
      <template #empty>{{ t('ipam.import.nothing') }}</template>
      <Column :header="t('ipam.import.columns.action')" style="width: 9rem">
        <template #body="{ data }"><Tag :value="t(`ipam.import.actions.${data.action}`)" :severity="severity(data.action)" /></template>
      </Column>
      <Column field="asset" :header="t('ipam.import.columns.asset')" />
      <Column field="interface" :header="t('ipam.import.columns.interface')" style="width: 8rem" />
      <Column :header="t('ipam.addresses.fields.address')" style="width: 11rem"><template #body="{ data }"><span class="mono">{{ data.address }}</span></template></Column>
      <Column field="vrf" :header="t('ipam.fields.vrf')" style="width: 9rem" />
      <Column field="reason" :header="t('ipam.import.columns.reason')" />
    </DataTable>
    <small v-if="result && result.truncated" class="muted">{{ t('ipam.import.truncated') }}</small>

    <template #footer>
      <Button :label="t('common.actions.cancel')" text severity="secondary" @click="emit('update:visible', false)" />
      <Button :label="t('ipam.import.preview')" icon="pi pi-eye" outlined :loading="loading" @click="preview" />
      <Button :label="t('ipam.import.run')" icon="pi pi-download" severity="success" :loading="running"
              :disabled="!result || !(result.summary.create || result.summary.link)" @click="run" />
    </template>
  </Dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import Dropdown from 'primevue/dropdown'
import Checkbox from 'primevue/checkbox'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import { useIpamLookups } from '../../../composables/useIpam'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['update:visible', 'imported'])
const { t } = useI18n()
const { vrfs, load } = useIpamLookups()

const options = ref({ vrf_id: null, per_site: false, create_prefixes: true })
const result = ref(null)
const done = ref(null)
const error = ref('')
const loading = ref(false)
const running = ref(false)

const severity = action => ({ create: 'success', link: 'info', already_imported: 'secondary', skipped_duplicate: 'warning', skipped_invalid: 'danger' }[action])

watch(() => props.visible, open => {
  if (!open) return
  result.value = null
  done.value = null
  error.value = ''
  load()
})

// a result belongs to the options it was made with
function changed() { result.value = null; done.value = null }

async function call(dryRun) {
  error.value = ''
  return (await api.importIpamAssetInterfaces({ ...options.value, dry_run: dryRun })).data
}

async function preview() {
  loading.value = true
  done.value = null
  try { result.value = await call(true) } catch (err) { error.value = apiErrorText(err, t) } finally { loading.value = false }
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
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.options { display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 1rem; max-width: 26rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
.check { display: inline-flex; align-items: center; gap: 0.5rem; cursor: pointer; }
.summary { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.75rem; }
.muted { color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
</style>
