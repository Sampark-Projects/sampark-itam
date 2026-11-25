<!--
  - ApplicationFindings.vue
  - Vulnerabilities and CVE tracking of an application: details, affected asset, remediation and the fix
  - deadline (SLA), retest and risk acceptance. A paged list, open and most severe first.
-->
<template>
  <div>
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>

    <div class="toolbar">
      <span class="p-input-icon-left search">
        <i class="pi pi-search" />
        <InputText v-model="search" :placeholder="t('applications.security.searchFindings')" class="w-full" @input="onSearch" />
      </span>
      <Dropdown v-model="state" :options="stateOptions" optionLabel="label" optionValue="value" class="filter" @change="reload" />
      <Dropdown v-model="severity" :options="severityOptions" optionLabel="label" optionValue="value" showClear
                :placeholder="t('applications.security.allSeverities')" class="filter" @change="reload" />
      <label class="check"><Checkbox v-model="overdueOnly" binary @change="reload" /><span>{{ t('applications.security.overdueOnly') }}</span></label>
      <span class="spacer"></span>
      <Button v-if="canWrite('applications')" :label="t('applications.security.addFinding')" icon="pi pi-plus" size="small" @click="openForm(null)" />
    </div>

    <DataTable :value="items" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
               :rowsPerPageOptions="[25, 50, 100]" class="rows" @page="onPage">
      <template #empty>{{ t('applications.security.emptyFindings') }}</template>
      <Column :header="t('applications.security.findingId')" style="width: 7rem">
        <template #body="{ data }"><strong>{{ data.code }}</strong><small v-if="data.ticket_ref" class="muted block">{{ data.ticket_ref }}</small></template>
      </Column>
      <Column :header="t('applications.security.title')">
        <template #body="{ data }">
          {{ data.title }}
          <small v-if="data.cve_id" class="muted block">{{ data.cve_id }}<template v-if="data.vulnerability_id"> · {{ t('applications.security.inCatalogue') }}</template></small>
          <small v-if="data.affected_component" class="muted block">{{ data.affected_component }}</small>
        </template>
      </Column>
      <Column :header="t('applications.security.severity')" style="width: 8rem">
        <template #body="{ data }">
          <Tag :value="t(`applications.security.severities.${data.severity}`)" :severity="severitySeverity(data.severity)" />
          <small v-if="data.cvss_score != null" class="muted block">CVSS {{ data.cvss_score }}</small>
        </template>
      </Column>
      <Column :header="t('applications.security.affected')">
        <template #body="{ data }">
          {{ data.affected_asset_name || '' }}<small v-if="data.affected_target" class="muted block mono">{{ data.affected_target }}</small>
          <small v-if="data.discovery_source" class="muted block">{{ data.discovery_source }}</small>
        </template>
      </Column>
      <Column :header="t('applications.security.exploitability')" style="width: 9rem">
        <template #body="{ data }"><span :class="{ hot: data.exploitability !== 'none_known' }">{{ t(`applications.security.exploitabilities.${data.exploitability}`) }}</span></template>
      </Column>
      <Column :header="t('applications.security.remediation')" style="width: 11rem">
        <template #body="{ data }">
          <Tag :value="t(`applications.security.remediationStatuses.${data.remediation_status}`)" :severity="remediationSeverity(data.remediation_status)" />
          <small v-if="data.assigned_owner" class="muted block">{{ data.assigned_owner }}</small>
          <small v-if="data.exception_id" class="muted block">{{ data.exception_id }}<template v-if="data.exception_valid_until"> · {{ formatDate(data.exception_valid_until) }}</template></small>
          <Tag v-if="data.exception_expired" :value="t('applications.security.exceptionExpired')" severity="danger" class="chip" />
        </template>
      </Column>
      <Column :header="t('applications.security.slaDue')" style="width: 9rem">
        <template #body="{ data }">
          <span :class="{ late: data.overdue }">{{ formatDate(data.sla_due_date) }}</span>
          <Tag v-if="data.overdue" :value="t('applications.security.overdueTag')" severity="danger" class="chip" />
          <small v-if="data.retest_date" class="muted block">{{ t('applications.security.retest') }} {{ formatDate(data.retest_date) }}<template v-if="data.retest_result"> · {{ t(`applications.security.retestResults.${data.retest_result}`) }}</template></small>
        </template>
      </Column>
      <Column style="width: 6rem">
        <template #body="{ data }">
          <Button v-if="canWrite('applications')" icon="pi pi-pencil" text rounded size="small" :aria-label="t('applications.security.editFinding')" @click="openForm(data)" />
          <Button v-if="canDelete('applications')" icon="pi pi-trash" text rounded size="small" severity="danger" @click="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <Dialog v-model:visible="formOpen" modal :header="editing ? `${editing.code} · ${t('applications.security.editFinding')}` : t('applications.security.addFinding')"
            :style="{ width: '52rem', maxWidth: '96vw' }">
      <Message v-if="formError" severity="error" :closable="true" @close="formError = ''">{{ formError }}</Message>
      <h4 class="card-title">{{ t('applications.security.cardDetails') }}</h4>
      <div class="grid-2">
        <div class="p-field span-2">
          <label>{{ t('applications.security.title') }} *</label>
          <InputText v-model="form.title" maxlength="300" :placeholder="t('applications.security.titlePlaceholder')" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.cveId') }}</label>
          <InputText v-model="form.cve_id" maxlength="100" placeholder="CVE-2025-49112 / CWE-79" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.ticketRef') }}</label>
          <InputText v-model="form.ticket_ref" maxlength="100" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.severity') }} *</label>
          <Dropdown v-model="form.severity" :options="severityChoices" optionLabel="label" optionValue="value" class="w-full" @change="onSeverityChange" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.cvss') }}</label>
          <InputNumber v-model="form.cvss_score" :min="0" :max="10" :minFractionDigits="1" :maxFractionDigits="1" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.discoverySource') }}</label>
          <InputText v-model="form.discovery_source" maxlength="150" :placeholder="t('applications.security.sourcePlaceholder')" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.vaptAssessment') }}</label>
          <Dropdown v-model="form.vapt_id" :options="vaptOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.affectedAsset') }}</label>
          <Dropdown v-model="form.affected_asset_id" :options="assetOptions" optionLabel="label" optionValue="value" showClear filter class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.affectedTarget') }}</label>
          <InputText v-model="form.affected_target" maxlength="255" placeholder="10.24.112.45:443" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.affectedComponent') }}</label>
          <InputText v-model="form.affected_component" maxlength="255" placeholder="OpenSSL 3.0.11" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.exploitability') }}</label>
          <Dropdown v-model="form.exploitability" :options="exploitabilityOptions" optionLabel="label" optionValue="value" class="w-full" />
        </div>
      </div>

      <h4 class="card-title">{{ t('applications.security.cardRemediation') }}</h4>
      <div class="grid-2">
        <div class="p-field">
          <label>{{ t('applications.security.remediation') }}</label>
          <Dropdown v-model="form.remediation_status" :options="remediationOptions" optionLabel="label" optionValue="value" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.assignedOwner') }}</label>
          <InputText v-model="form.assigned_owner" maxlength="255" :placeholder="t('applications.security.ownerPlaceholder')" class="w-full" />
        </div>
        <div class="p-field span-2">
          <label>{{ t('applications.security.recommendedFix') }}</label>
          <Textarea v-model="form.recommended_fix" rows="2" autoResize maxlength="5000" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.discoveredOn') }}</label>
          <Calendar v-model="form.discovered_on" dateFormat="dd/mm/yy" showIcon class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.slaDue') }}</label>
          <Calendar v-model="form.sla_due_date" dateFormat="dd/mm/yy" showIcon showButtonBar class="w-full" @date-select="slaTouched = true" />
          <small class="muted">{{ t('applications.security.slaHint') }}</small>
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.retestDate') }}</label>
          <Calendar v-model="form.retest_date" dateFormat="dd/mm/yy" showIcon showButtonBar class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.retestResult') }}</label>
          <Dropdown v-model="form.retest_result" :options="retestOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.exceptionId') }}</label>
          <InputText v-model="form.exception_id" maxlength="100" placeholder="EXC-2026-14" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.security.exceptionUntil') }}</label>
          <Calendar v-model="form.exception_valid_until" dateFormat="dd/mm/yy" showIcon showButtonBar class="w-full" />
        </div>
      </div>
      <small class="muted">{{ t('applications.security.rulesHint') }}</small>

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
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dialog from 'primevue/dialog'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Textarea from 'primevue/textarea'
import Calendar from 'primevue/calendar'
import Checkbox from 'primevue/checkbox'
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

const SEVERITIES = ['critical', 'high', 'medium', 'low', 'info']
const SLA_DAYS = { critical: 7, high: 30, medium: 90, low: 180, info: 365 }
const EXPLOITABILITY = ['none_known', 'poc_available', 'actively_exploited']
const REMEDIATION = ['open', 'patch_assigned', 'retest_pending', 'verified_fixed', 'risk_accepted']
const severityChoices = computed(() => SEVERITIES.map(v => ({ value: v, label: t(`applications.security.severities.${v}`) })))
const severityOptions = severityChoices
const exploitabilityOptions = computed(() => EXPLOITABILITY.map(v => ({ value: v, label: t(`applications.security.exploitabilities.${v}`) })))
const remediationOptions = computed(() => REMEDIATION.map(v => ({ value: v, label: t(`applications.security.remediationStatuses.${v}`) })))
const retestOptions = computed(() => ['passed', 'failed'].map(v => ({ value: v, label: t(`applications.security.retestResults.${v}`) })))
const stateOptions = computed(() => [
  { value: 'open', label: t('applications.security.stateOpen') }, { value: 'closed', label: t('applications.security.stateClosed') }, { value: 'all', label: t('applications.security.stateAll') }])
const severitySeverity = v => ({ critical: 'danger', high: 'warning', medium: 'info', low: 'secondary', info: 'secondary' }[v])
const remediationSeverity = v => ({ open: 'danger', patch_assigned: 'warning', retest_pending: 'info', verified_fixed: 'success', risk_accepted: 'secondary' }[v])

// --- list ---
const items = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const search = ref('')
const state = ref('open')
const severity = ref(null)
const overdueOnly = ref(false)
const rows = ref(50)
const first = ref(0)

let request = 0
async function load() {
  const mine = ++request
  loading.value = true
  try {
    const params = { skip: first.value, limit: rows.value }
    if (search.value.trim()) params.search = search.value.trim()
    if (state.value && state.value !== 'all') params.state = state.value
    if (severity.value) params.severity = severity.value
    if (overdueOnly.value) params.overdue = true
    const res = await api.getApplicationFindings(props.applicationId, params)
    if (mine !== request) return
    items.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (err) {
    if (mine === request) error.value = apiErrorText(err, t)
  } finally {
    if (mine === request) loading.value = false
  }
}

function reload() { first.value = 0; load() }
let timer = null
function onSearch() { clearTimeout(timer); timer = setTimeout(reload, 300) }
function onPage(event) { first.value = event.first; rows.value = event.rows; load() }

// --- form ---
const formOpen = ref(false)
const editing = ref(null)
const formError = ref('')
const saving = ref(false)
const assetOptions = ref([])
const vaptOptions = ref([])
const slaTouched = ref(false)
const blank = () => ({ title: '', severity: 'medium', cve_id: '', ticket_ref: '', cvss_score: null, discovery_source: '', vapt_id: null, affected_asset_id: null,
  affected_target: '', affected_component: '', exploitability: 'none_known', remediation_status: 'open', recommended_fix: '', assigned_owner: '',
  discovered_on: new Date(), sla_due_date: null, retest_date: null, retest_result: null, exception_id: '', exception_valid_until: null })
const form = ref(blank())

async function loadChoices() {
  try {
    const [infra, vapt] = await Promise.all([api.getApplicationInfrastructure(props.applicationId), api.getApplicationVapt(props.applicationId)])
    assetOptions.value = (infra.data.items || []).map(a => ({ value: a.asset_id, label: a.name }))
    vaptOptions.value = (vapt.data || []).map(v => ({ value: v.id, label: `${v.code}${v.reference ? ' · ' + v.reference : ''}` }))
  } catch (e) {
    assetOptions.value = []
    vaptOptions.value = []
  }
}

function onSeverityChange() {
  // suggest the deadline from the severity until the person sets one
  if (!slaTouched.value && form.value.discovered_on && !editing.value) {
    const d = new Date(form.value.discovered_on)
    d.setDate(d.getDate() + SLA_DAYS[form.value.severity])
    form.value.sla_due_date = d
  }
}

async function openForm(row) {
  editing.value = row
  formError.value = ''
  slaTouched.value = !!row
  if (row) {
    const f = blank()
    for (const key of Object.keys(f)) f[key] = row[key] ?? f[key]
    for (const key of ['discovered_on', 'sla_due_date', 'retest_date', 'exception_valid_until']) f[key] = parseLocalDate(row[key])
    form.value = f
  } else {
    form.value = blank()
    onSeverityChange()
  }
  formOpen.value = true
  await loadChoices()
}

async function save() {
  formError.value = ''
  const f = form.value
  if (!f.title.trim()) { formError.value = t('applications.security.titleRequired'); return }
  const body = { ...f }
  for (const key of ['discovered_on', 'sla_due_date', 'retest_date', 'exception_valid_until']) body[key] = formatLocalDate(f[key])
  for (const key of Object.keys(body)) if (body[key] === '') body[key] = null
  saving.value = true
  try {
    if (editing.value) await api.updateApplicationFinding(props.applicationId, editing.value.id, body)
    else await api.createApplicationFinding(props.applicationId, body)
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
  if (!window.confirm(t('applications.security.deleteFindingConfirm', { code: row.code }))) return
  try {
    await api.deleteApplicationFinding(props.applicationId, row.id)
    await load()
    emit('changed')
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

onMounted(load)
</script>

<style scoped>
.toolbar { display: flex; gap: 0.6rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.toolbar .spacer { flex: 1; }
.search { flex: 1 1 16rem; max-width: 24rem; }
.filter { min-width: 10rem; }
.check { display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.block { display: block; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.late { color: #dc2626; font-weight: 600; }
.hot { color: #c2410c; font-weight: 600; }
.chip { margin-left: 0.35rem; }
.card-title { margin: 1rem 0 0.5rem; font-size: 0.95rem; color: var(--sk-text-muted, #6b7a71); text-transform: uppercase; letter-spacing: 0.03em; }
.card-title:first-of-type { margin-top: 0; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem 1rem; }
.span-2 { grid-column: span 2; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
