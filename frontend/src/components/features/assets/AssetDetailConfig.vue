<!--
  - AssetDetailConfig.vue
  - Programs, device configurations and firmware of one asset, kept as versions. One version can be
  - the golden baseline; a newer version that differs from it is flagged. Two versions can be compared.
-->
<template>
  <section class="dcard">
    <h3 class="dcard-title">
      <span class="dcard-icon"><i class="pi pi-code"></i></span>{{ t('configmgmt.title') }}
      <span v-if="driftCount" class="dcard-count drift-chip">{{ driftCount }} {{ t('configmgmt.baseline.differs') }}</span>
    </h3>
    <p class="muted">{{ t('configmgmt.card.hint') }}</p>
    <p v-if="error" class="p-error">{{ error }}</p>
    <p v-if="!artifacts.length" class="muted">{{ t('configmgmt.card.empty') }}</p>

    <div v-for="art in artifacts" :key="art.id" class="artifact">
      <div class="art-head">
        <div class="art-title">
          <strong>{{ art.name }}</strong>
          <Tag :value="t(`configmgmt.kinds.${art.kind}`)" severity="secondary" class="chip" />
          <Tag :value="t(`configmgmt.baseline.${art.baseline_state}`)" :severity="baselineSeverity(art.baseline_state)" class="chip" />
          <Tag :value="t(`configmgmt.backup.${art.backup_state}`)" :severity="backupSeverity(art.backup_state)" class="chip" />
        </div>
        <div class="art-tools">
          <Button v-if="canWrite('configurations')" :label="t('configmgmt.card.upload')" icon="pi pi-upload" size="small" @click="openUpload(art)" />
          <Button :label="expanded[art.id] ? t('configmgmt.card.hide') : t('configmgmt.card.show')" :icon="expanded[art.id] ? 'pi pi-chevron-up' : 'pi pi-chevron-down'" size="small" text @click="expanded[art.id] = !expanded[art.id]" />
          <Button v-if="canWrite('configurations')" icon="pi pi-pencil" size="small" text rounded severity="info" :aria-label="t('configmgmt.card.editItem')" @click="openEdit(art)" />
          <Button v-if="canDelete('configurations')" icon="pi pi-trash" size="small" text rounded severity="danger" :aria-label="t('configmgmt.card.delete')" @click="removeItem(art)" />
        </div>
      </div>
      <small v-if="art.description" class="muted block">{{ art.description }}</small>
      <small v-if="art.baseline_set_at" class="muted block">{{ t('configmgmt.card.baselineSince', { name: art.baseline_set_by || '-', date: formatDate(art.baseline_set_at) }) }}</small>

      <div v-if="expanded[art.id]" class="versions">
        <table v-if="art.versions.length" class="ver-table">
          <thead>
            <tr>
              <th></th>
              <th>{{ t('configmgmt.card.version') }}</th>
              <th>{{ t('configmgmt.card.fileName') }}</th>
              <th>{{ t('configmgmt.card.size') }}</th>
              <th>{{ t('configmgmt.card.uploaded') }}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="v in art.versions" :key="v.id" :class="{ baseline: v.is_baseline }">
              <td><Checkbox v-model="picked[art.id]" :value="v.id" :disabled="(picked[art.id] || []).length >= 2 && !(picked[art.id] || []).includes(v.id)" /></td>
              <td>
                <strong>v{{ v.version_number }}</strong><span v-if="v.label"> · {{ v.label }}</span>
                <Tag v-if="v.is_baseline" :value="t('configmgmt.card.baseline')" severity="success" class="chip" />
                <Tag v-if="v.id === art.latest?.id" :value="t('configmgmt.card.latest')" severity="info" class="chip" />
                <small v-if="v.note" class="muted block">{{ v.note }}</small>
                <small class="muted block mono" :title="v.sha256">sha256 {{ v.sha256.slice(0, 12) }}…</small>
              </td>
              <td class="break">{{ v.file_name }}</td>
              <td>{{ formatSize(v.size_bytes) }}</td>
              <td>{{ formatDate(v.uploaded_at) }}<small class="muted block">{{ v.uploaded_by }}</small></td>
              <td class="num">
                <Button icon="pi pi-download" size="small" text rounded :aria-label="t('configmgmt.card.download')" @click="download(v)" />
                <Button v-if="canWrite('configurations') && !v.is_baseline" :label="t('configmgmt.card.setBaseline')" size="small" text @click="setBaseline(v)" />
                <Button v-if="canDelete('configurations') && !v.is_baseline" icon="pi pi-trash" size="small" text rounded severity="danger" :aria-label="t('configmgmt.card.delete')" @click="removeVersion(v)" />
              </td>
            </tr>
          </tbody>
        </table>
        <div class="flex gap-2 align-items-center flex-wrap mt-2">
          <Button :label="t('configmgmt.card.compare')" icon="pi pi-arrows-h" size="small" :disabled="(picked[art.id] || []).length !== 2" @click="openCompare(art)" />
          <small v-if="(picked[art.id] || []).length !== 2" class="muted">{{ t('configmgmt.card.compareHint') }}</small>
          <Button v-if="canWrite('configurations') && art.baseline_version_id" :label="t('configmgmt.card.clearBaseline')" size="small" text severity="secondary" @click="clearBaseline(art)" />
        </div>
      </div>
    </div>

    <Button v-if="canWrite('configurations')" :label="t('configmgmt.card.addItem')" icon="pi pi-plus" text class="mt-2" @click="openNew" />

    <!-- item form -->
    <Dialog v-model:visible="showItem" :header="editing ? t('configmgmt.card.editItem') : t('configmgmt.card.addItem')" modal :style="{ width: '90vw', maxWidth: '30rem' }">
      <div class="p-field">
        <label>{{ t('configmgmt.card.name') }} *</label>
        <InputText v-model="itemForm.name" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('configmgmt.card.kind') }}</label>
        <Dropdown v-model="itemForm.kind" :options="kindOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('configmgmt.card.description') }}</label>
        <InputText v-model="itemForm.description" maxlength="255" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('configmgmt.card.interval') }}</label>
        <InputNumber v-model="itemForm.backup_interval_days" :min="1" :max="3650" :useGrouping="false" class="w-full" />
        <small class="muted">{{ t('configmgmt.card.intervalHint') }}</small>
      </div>
      <small v-if="dialogError" class="p-error block">{{ dialogError }}</small>
      <template #footer>
        <Button :label="t('common.actions.cancel')" text @click="showItem = false" />
        <Button :label="t('common.actions.save')" :loading="saving" @click="saveItem" />
      </template>
    </Dialog>

    <!-- upload -->
    <Dialog v-model:visible="showUpload" :header="t('configmgmt.card.uploadTitle')" modal :style="{ width: '90vw', maxWidth: '30rem' }">
      <p v-if="uploadTarget" class="muted"><strong>{{ uploadTarget.name }}</strong></p>
      <div class="p-field">
        <label>{{ t('configmgmt.card.file') }} *</label>
        <input ref="fileInput" type="file" class="file-input" @change="file = $event.target.files[0] || null" />
        <small v-if="file" class="muted">{{ file.name }} · {{ formatSize(file.size) }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('configmgmt.card.label') }}</label>
        <InputText v-model="uploadForm.label" maxlength="100" class="w-full" placeholder="v2.3" />
      </div>
      <div class="p-field">
        <label>{{ t('configmgmt.card.note') }}</label>
        <Textarea v-model="uploadForm.note" rows="2" autoResize class="w-full" />
      </div>
      <small v-if="dialogError" class="p-error block">{{ dialogError }}</small>
      <template #footer>
        <Button :label="t('common.actions.cancel')" text @click="showUpload = false" />
        <Button :label="t('configmgmt.card.upload')" icon="pi pi-upload" :loading="saving" @click="upload" />
      </template>
    </Dialog>

    <!-- compare -->
    <Dialog v-model:visible="showCompare" :header="t('configmgmt.compare.title')" modal :style="{ width: '90vw', maxWidth: '56rem' }">
      <div v-if="comparison">
        <p>
          <strong>v{{ comparison.a.version_number }}</strong> → <strong>v{{ comparison.b.version_number }}</strong>
          · {{ comparison.identical ? t('configmgmt.compare.identical') : t('configmgmt.compare.different') }}
        </p>
        <template v-if="!comparison.identical && comparison.text">
          <p class="muted">
            {{ t('configmgmt.compare.added', { n: comparison.diff.added }) }} · {{ t('configmgmt.compare.removed', { n: comparison.diff.removed }) }}
            <span v-if="comparison.diff.truncated"> · {{ t('configmgmt.compare.truncated') }}</span>
          </p>
          <pre class="diff"><span v-for="(line, i) in comparison.diff.lines" :key="i" :class="lineClass(line)">{{ line }}
</span></pre>
        </template>
        <div v-else-if="!comparison.identical" class="muted">
          <p>{{ t('configmgmt.compare.binary') }}</p>
          <p class="mono">{{ t('configmgmt.compare.checksum') }} v{{ comparison.a.version_number }}: {{ comparison.a.sha256 }}<br>{{ t('configmgmt.compare.checksum') }} v{{ comparison.b.version_number }}: {{ comparison.b.sha256 }}</p>
        </div>
      </div>
    </Dialog>
  </section>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Textarea from 'primevue/textarea'
import Dropdown from 'primevue/dropdown'
import Checkbox from 'primevue/checkbox'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({
  asset: { type: Object, required: true }
})

const { t } = useI18n()
const { canWrite, canDelete, canRead } = usePermissions()
const { formatDate } = useDateFormatter()

const artifacts = ref([])
const error = ref('')
const dialogError = ref('')
const saving = ref(false)
const expanded = reactive({})
const picked = reactive({})

const kindOptions = computed(() => ['program', 'configuration', 'firmware', 'other'].map(v => ({ value: v, label: t(`configmgmt.kinds.${v}`) })))
const driftCount = computed(() => artifacts.value.filter(a => a.baseline_state === 'differs').length)
const baselineSeverity = (s) => ({ matches: 'success', differs: 'danger', no_baseline: 'warning', no_versions: 'secondary' }[s] || 'info')
const backupSeverity = (s) => ({ ok: 'success', stale: 'danger', none: 'warning', unmanaged: 'secondary' }[s] || 'info')

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const lineClass = (line) => (line.startsWith('+++') || line.startsWith('---') ? 'd-head' : (line.startsWith('+') ? 'd-add' : (line.startsWith('-') ? 'd-del' : (line.startsWith('@@') ? 'd-hunk' : ''))))

async function load() {
  error.value = ''
  if (!props.asset?.id) return
  try {
    const res = await api.getAssetConfigArtifacts(props.asset.id)
    artifacts.value = Array.isArray(res.data) ? res.data : []
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

// --- item ---
const showItem = ref(false)
const editing = ref(null)
const itemForm = ref({ name: '', kind: 'program', description: '', backup_interval_days: null })

function openNew() {
  editing.value = null
  itemForm.value = { name: '', kind: 'program', description: '', backup_interval_days: null }
  dialogError.value = ''
  showItem.value = true
}

function openEdit(art) {
  editing.value = art
  itemForm.value = { name: art.name, kind: art.kind, description: art.description || '', backup_interval_days: art.backup_interval_days }
  dialogError.value = ''
  showItem.value = true
}

async function saveItem() {
  dialogError.value = ''
  if (!itemForm.value.name.trim()) {
    dialogError.value = t('configmgmt.card.required')
    return
  }
  saving.value = true
  try {
    const payload = { ...itemForm.value, description: itemForm.value.description || null, backup_interval_days: itemForm.value.backup_interval_days || null }
    if (editing.value) await api.updateConfigArtifact(editing.value.id, payload)
    else await api.createConfigArtifact(props.asset.id, payload)
    showItem.value = false
    await load()
  } catch (err) {
    dialogError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

async function removeItem(art) {
  if (!window.confirm(t('configmgmt.card.deleteItem'))) return
  try {
    await api.deleteConfigArtifact(art.id)
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

// --- upload ---
const showUpload = ref(false)
const uploadTarget = ref(null)
const file = ref(null)
const fileInput = ref(null)
const uploadForm = ref({ label: '', note: '' })

async function openUpload(art) {
  uploadTarget.value = art
  file.value = null
  uploadForm.value = { label: '', note: '' }
  dialogError.value = ''
  showUpload.value = true
}

async function upload() {
  dialogError.value = ''
  if (!file.value) {
    dialogError.value = t('configmgmt.card.fileRequired')
    return
  }
  saving.value = true
  try {
    await api.uploadConfigVersion(uploadTarget.value.id, file.value, uploadForm.value)
    showUpload.value = false
    expanded[uploadTarget.value.id] = true
    await load()
  } catch (err) {
    dialogError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

// --- versions ---
async function download(version) {
  try {
    const res = await api.downloadConfigVersion(version.id)
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = version.file_name
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

async function setBaseline(version) {
  try {
    await api.setConfigBaseline(version.id)
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

async function clearBaseline(art) {
  try {
    await api.clearConfigBaseline(art.id)
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

async function removeVersion(version) {
  if (!window.confirm(t('configmgmt.card.deleteVersion'))) return
  try {
    await api.deleteConfigVersion(version.id)
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

// --- compare ---
const showCompare = ref(false)
const comparison = ref(null)

async function openCompare(art) {
  const ids = picked[art.id] || []
  if (ids.length !== 2) return
  // older version first
  const byId = Object.fromEntries(art.versions.map(v => [v.id, v.version_number]))
  const [a, b] = [...ids].sort((x, y) => byId[x] - byId[y])
  try {
    const res = await api.compareConfigVersions(a, b)
    comparison.value = res.data
    showCompare.value = true
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

watch(() => props.asset?.id, load, { immediate: true })
</script>

<style scoped>
.muted { color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; margin: 0 0 0.5rem; }
.block { display: block; }
.mono { font-family: ui-monospace, Consolas, monospace; font-size: 0.75rem; word-break: break-all; }
.break { word-break: break-all; }
.chip { margin-left: 0.4rem; font-size: 0.7rem; }
.drift-chip { margin-left: 0.5rem; }
.artifact { padding: 0.75rem 0; border-top: 1px solid var(--sk-border, #e1e7e3); }
.art-head { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
.art-tools { display: flex; align-items: center; gap: 0.25rem; flex-wrap: wrap; }
.versions { margin-top: 0.75rem; }
.ver-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.ver-table th { text-align: left; font-size: 0.75rem; letter-spacing: 0.04em; text-transform: uppercase; color: var(--sk-text-muted, #6b7a71); padding: 0.25rem 0.5rem; }
.ver-table td { padding: 0.4rem 0.5rem; border-top: 1px solid var(--sk-border, #e1e7e3); vertical-align: top; }
.ver-table tr.baseline td { background: #f1f8f3; }
.num { text-align: right; white-space: nowrap; }
.p-field { margin-bottom: 0.9rem; }
.p-field label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
.file-input { display: block; width: 100%; }
.diff { max-height: 26rem; overflow: auto; background: #0f1a14; color: #dfe8e2; border-radius: 8px; padding: 0.75rem; font-size: 0.8rem; line-height: 1.4; }
.diff span { display: block; white-space: pre-wrap; word-break: break-all; }
.d-add { color: #7ee2a8; }
.d-del { color: #ff9d96; }
.d-hunk { color: #8ab4ff; }
.d-head { color: #b8c4bc; font-weight: 600; }
</style>
