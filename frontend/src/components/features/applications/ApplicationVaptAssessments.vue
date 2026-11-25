<!--
  - ApplicationVaptAssessments.vue
  - VAPT engagements of an application: type, method, scope, assessor, status, dates, the signed report,
  - the executive scorecard (open findings counted from the findings list) and the sign-off.
-->
<template>
  <div>
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="toolbar">
      <Button v-if="canWrite('applications')" :label="t('applications.security.addVapt')" icon="pi pi-plus" size="small" @click="openForm(null)" />
    </div>

    <div v-if="loading" class="loading"><i class="pi pi-spin pi-spinner"></i></div>
    <table v-else-if="items.length" class="app-table">
      <thead>
        <tr>
          <th>{{ t('applications.security.vaptId') }}</th><th>{{ t('applications.security.assessmentType') }}</th><th>{{ t('applications.security.assessor') }}</th>
          <th>{{ t('applications.security.status') }}</th><th>{{ t('applications.security.testDate') }}</th>
          <th>{{ t('applications.security.posture') }}</th><th>{{ t('applications.security.openFindings') }}</th><th>{{ t('applications.security.report') }}</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="v in items" :key="v.id">
          <td><strong>{{ v.code }}</strong><small v-if="v.reference" class="muted block">{{ v.reference }}</small></td>
          <td>{{ t(`applications.security.types.${v.assessment_type}`) }}<small v-if="v.methodology" class="muted block">{{ t(`applications.security.methodologies.${v.methodology}`) }}</small></td>
          <td>{{ v.assessor || none }}</td>
          <td><Tag :value="t(`applications.security.assessmentStatuses.${v.status}`)" :severity="statusSeverity(v.status)" /></td>
          <td>{{ v.test_date ? formatDate(v.test_date) : none }}</td>
          <td><Tag v-if="v.overall_posture" :value="t(`applications.security.postures.${v.overall_posture}`)" :severity="postureSeverity(v.overall_posture)" /><template v-else>{{ none }}</template></td>
          <td class="counts">
            <span v-for="s in SEVERITIES" :key="s" :class="['count', `sev-${s}`, { zero: !v.open_findings[s] }]" :title="t(`applications.security.severities.${s}`)">{{ v.open_findings[s] }}</span>
          </td>
          <td>
            <a v-if="v.report_file" href="#" @click.prevent="download(v)">{{ v.report_file.name }}</a>
            <a v-else-if="v.report_url" :href="v.report_url" target="_blank" rel="noopener noreferrer">{{ t('applications.security.openLink') }}</a>
            <template v-else>{{ none }}</template>
          </td>
          <td class="num">
            <Button v-if="canWrite('applications')" icon="pi pi-pencil" text rounded size="small" :aria-label="t('applications.security.editVapt')" @click="openForm(v)" />
            <Button v-if="canDelete('applications')" icon="pi pi-trash" text rounded size="small" severity="danger" @click="remove(v)" />
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else class="muted">{{ t('applications.security.emptyVapt') }}</p>

    <Dialog v-model:visible="formOpen" modal :header="editing ? `${editing.code} · ${t('applications.security.editVapt')}` : t('applications.security.addVapt')"
            :style="{ width: '50rem', maxWidth: '96vw' }">
      <Message v-if="formError" severity="error" :closable="true" @close="formError = ''">{{ formError }}</Message>
      <h4 class="card-title">{{ t('applications.security.cardEngagement') }}</h4>
      <div class="grid-2">
        <div class="p-field">
          <label>{{ t('applications.security.assessmentType') }}</label>
          <Dropdown v-model="form.assessment_type" :options="typeOptions" optionLabel="label" optionValue="value" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.methodology') }}</label>
          <Dropdown v-model="form.methodology" :options="methodologyOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.assessor') }}</label>
          <InputText v-model="form.assessor" maxlength="255" :placeholder="t('applications.security.assessorPlaceholder')" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.reference') }}</label>
          <InputText v-model="form.reference" maxlength="100" class="w-full" />
        </div>
        <div class="p-field span-2">
          <label>{{ t('applications.security.scope') }}</label>
          <Textarea v-model="form.scope" rows="2" autoResize maxlength="5000" :placeholder="t('applications.security.scopePlaceholder')" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.status') }}</label>
          <Dropdown v-model="form.status" :options="statusOptions" optionLabel="label" optionValue="value" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.testDate') }}</label>
          <Calendar v-model="form.test_date" dateFormat="dd/mm/yy" :maxDate="new Date()" showIcon showButtonBar class="w-full" />
          <small class="muted">{{ t('applications.security.testDateHint') }}</small>
        </div>
        <div class="p-field span-2">
          <label>{{ t('applications.security.reportUrl') }}</label>
          <InputText v-model="form.report_url" maxlength="500" placeholder="https://" class="w-full" />
        </div>
      </div>

      <h4 class="card-title">{{ t('applications.security.cardScorecard') }}</h4>
      <div v-if="editing" class="scorecard">
        <span v-for="s in SEVERITIES" :key="s" :class="['count', `sev-${s}`, { zero: !editing.open_findings[s] }]">{{ t(`applications.security.severities.${s}`) }}: {{ editing.open_findings[s] }}</span>
        <small class="muted">{{ t('applications.security.suggested') }}: {{ t(`applications.security.postures.${editing.suggested_posture}`) }}</small>
      </div>
      <p v-else class="muted">{{ t('applications.security.scorecardHint') }}</p>
      <div class="grid-2">
        <div class="p-field">
          <label>{{ t('applications.security.posture') }}</label>
          <Dropdown v-model="form.overall_posture" :options="postureOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
        </div>
        <div class="p-field"></div>
        <div class="p-field">
          <label>{{ t('applications.security.signOffBy') }}</label>
          <InputText v-model="form.sign_off_by" maxlength="255" :placeholder="t('applications.security.signOffPlaceholder')" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.signOffDate') }}</label>
          <Calendar v-model="form.sign_off_date" dateFormat="dd/mm/yy" showIcon showButtonBar class="w-full" />
        </div>
      </div>

      <template v-if="editing">
        <h4 class="card-title">{{ t('applications.security.report') }}</h4>
        <div class="report-box">
          <template v-if="editing.report_file">
            <a href="#" @click.prevent="download(editing)">{{ editing.report_file.name }}</a>
            <small class="muted">({{ formatSize(editing.report_file.size) }})</small>
            <Button v-if="canDelete('applications')" icon="pi pi-trash" text rounded size="small" severity="danger" :loading="uploading" @click="removeReport" />
          </template>
          <span v-else class="muted">{{ t('applications.security.noReport') }}</span>
          <input ref="fileInput" type="file" class="hidden-file" accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv" @change="uploadReport" />
          <Button :label="editing.report_file ? t('applications.security.replaceReport') : t('applications.security.uploadReport')" icon="pi pi-upload"
                  size="small" outlined :loading="uploading" @click="fileInput.click()" />
        </div>
      </template>

      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="formOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="save" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import Textarea from 'primevue/textarea'
import Calendar from 'primevue/calendar'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { formatLocalDate, parseLocalDate } from '../../../utils/localDate'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({ applicationId: { type: String, required: true } })
const emit = defineEmits(['changed'])
const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const { formatDate } = useDateFormatter()
const none = computed(() => t('applications.none'))

const SEVERITIES = ['critical', 'high', 'medium', 'low']
const TYPES = ['web_app', 'api', 'network', 'mobile', 'infrastructure', 'cloud', 'code_review', 'other']
const METHODOLOGIES = ['black_box', 'grey_box', 'white_box']
const STATUSES = ['scheduled', 'in_progress', 'remediation', 'closed']
const POSTURES = ['pass', 'conditional_pass', 'fail']
const typeOptions = computed(() => TYPES.map(v => ({ value: v, label: t(`applications.security.types.${v}`) })))
const methodologyOptions = computed(() => METHODOLOGIES.map(v => ({ value: v, label: t(`applications.security.methodologies.${v}`) })))
const statusOptions = computed(() => STATUSES.map(v => ({ value: v, label: t(`applications.security.assessmentStatuses.${v}`) })))
const postureOptions = computed(() => POSTURES.map(v => ({ value: v, label: t(`applications.security.postures.${v}`) })))
const statusSeverity = v => ({ scheduled: 'info', in_progress: 'warning', remediation: 'warning', closed: 'success' }[v])
const postureSeverity = v => ({ pass: 'success', conditional_pass: 'warning', fail: 'danger' }[v])

const items = ref([])
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  try {
    items.value = (await api.getApplicationVapt(props.applicationId)).data || []
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    loading.value = false
  }
}

// --- form ---
const formOpen = ref(false)
const editing = ref(null)
const formError = ref('')
const saving = ref(false)
const uploading = ref(false)
const fileInput = ref(null)
const blank = () => ({ assessment_type: 'web_app', methodology: null, assessor: '', reference: '', scope: '', status: 'scheduled', test_date: null,
  report_url: '', overall_posture: null, sign_off_by: '', sign_off_date: null })
const form = ref(blank())

function openForm(row) {
  editing.value = row
  formError.value = ''
  form.value = row
    ? { assessment_type: row.assessment_type, methodology: row.methodology, assessor: row.assessor || '', reference: row.reference || '', scope: row.scope || '',
        status: row.status, test_date: parseLocalDate(row.test_date),
        report_url: row.report_url || '',
        overall_posture: row.overall_posture, sign_off_by: row.sign_off_by || '', sign_off_date: parseLocalDate(row.sign_off_date) }
    : blank()
  formOpen.value = true
}

async function save() {
  formError.value = ''
  const f = form.value
  const body = { ...f, test_date: formatLocalDate(f.test_date), sign_off_date: formatLocalDate(f.sign_off_date) }
  for (const key of Object.keys(body)) if (body[key] === '') body[key] = null
  saving.value = true
  try {
    if (editing.value) await api.updateApplicationVapt(props.applicationId, editing.value.id, body)
    else await api.createApplicationVapt(props.applicationId, body)
    formOpen.value = false
    await load()
    emit('changed')
  } catch (err) {
    formError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  if (!window.confirm(t('applications.security.deleteVaptConfirm', { code: row.code }))) return
  try {
    await api.deleteApplicationVapt(props.applicationId, row.id)
    await load()
    emit('changed')
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

// --- report ---
const MAX_BYTES = 10 * 1024 * 1024
function formatSize(bytes) {
  if (bytes == null) return ''
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function uploadReport(event) {
  const file = event.target.files && event.target.files[0]
  event.target.value = ''
  if (!file) return
  formError.value = ''
  if (file.size > MAX_BYTES) { formError.value = t('applications.security.tooLarge'); return }
  uploading.value = true
  try {
    editing.value = (await api.uploadApplicationVaptReport(props.applicationId, editing.value.id, file)).data
    await load()
  } catch (err) {
    formError.value = apiErrorText(err, t)
  } finally {
    uploading.value = false
  }
}

async function removeReport() {
  if (!window.confirm(t('applications.security.removeReportConfirm'))) return
  uploading.value = true
  try {
    editing.value = (await api.deleteApplicationVaptReport(props.applicationId, editing.value.id)).data
    await load()
  } catch (err) {
    formError.value = apiErrorText(err, t)
  } finally {
    uploading.value = false
  }
}

async function download(row) {
  try {
    const res = await api.downloadApplicationVaptReport(props.applicationId, row.id)
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = row.report_file.name
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

onMounted(load)
</script>

<style scoped>
.toolbar { margin-bottom: 0.75rem; }
.loading { padding: 1.5rem; text-align: center; }
.app-table { width: 100%; border-collapse: collapse; }
.app-table th, .app-table td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--sk-border, #e1e7e3); vertical-align: top; }
.app-table th { font-weight: 600; font-size: 0.85rem; color: var(--sk-text-muted, #6b7a71); white-space: nowrap; }
.num { white-space: nowrap; text-align: right; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.block { display: block; }
.late { color: #dc2626; font-weight: 600; }
.counts { white-space: nowrap; }
.count { display: inline-block; min-width: 1.5rem; text-align: center; padding: 0.1rem 0.35rem; margin-right: 0.2rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600; background: #f1f5f9; }
.count.zero { color: #94a3b8; font-weight: 400; }
.count.sev-critical:not(.zero) { background: #fee2e2; color: #b91c1c; }
.count.sev-high:not(.zero) { background: #ffedd5; color: #c2410c; }
.count.sev-medium:not(.zero) { background: #fef9c3; color: #a16207; }
.card-title { margin: 1rem 0 0.5rem; font-size: 0.95rem; color: var(--sk-text-muted, #6b7a71); text-transform: uppercase; letter-spacing: 0.03em; }
.card-title:first-of-type { margin-top: 0; }
.app-table-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem 1rem; }
.span-2 { grid-column: span 2; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
.scorecard { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.75rem; }
.report-box { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }
.hidden-file { display: none; }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
