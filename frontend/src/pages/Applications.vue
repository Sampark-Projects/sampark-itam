<!--
  - Applications.vue
  - The application register: a paged, searchable list. A row opens the application.
-->
<template>
  <div class="applications-page">
    <div class="page-header">
      <h1>{{ t('applications.title') }}</h1>
      <div class="flex gap-2">
        <Button v-if="canDelete('applications')" :label="t('applications.alerts.button')" icon="pi pi-bell" outlined @click="openAlerts" />
        <Button v-if="canWrite('applications')" :label="t('applications.new')" icon="pi pi-plus" severity="success" @click="openForm" />
      </div>
    </div>
    <p class="hint">{{ t('applications.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div v-if="overview" class="overview">
      <div class="stat"><strong>{{ overview.total }}</strong><span>{{ t('applications.overview.total') }}</span></div>
      <div class="stat"><strong>{{ overview.by_tier.tier1 || 0 }}</strong><span>{{ t('applications.overview.tier1') }}</span></div>
      <div class="stat" :class="{ bad: overview.ssl.expired }"><strong>{{ overview.ssl.expired }}</strong><span>{{ t('applications.overview.sslExpired') }}</span></div>
      <div class="stat" :class="{ warn: overview.ssl.expiring }"><strong>{{ overview.ssl.expiring }}</strong><span>{{ t('applications.overview.sslExpiring') }}</span></div>
      <div class="stat" :class="{ bad: overview.vapt.overdue }"><strong>{{ overview.vapt.overdue }}</strong><span>{{ t('applications.overview.vaptOverdue') }}</span></div>
      <div class="stat" :class="{ warn: overview.vapt.never_tested }"><strong>{{ overview.vapt.never_tested }}</strong><span>{{ t('applications.overview.neverTested') }}</span></div>
      <div class="stat" :class="{ bad: overview.findings.open.critical }"><strong>{{ overview.findings.open.critical }}</strong><span>{{ t('applications.overview.openCritical') }}</span></div>
      <div class="stat" :class="{ warn: overview.findings.open.high }"><strong>{{ overview.findings.open.high }}</strong><span>{{ t('applications.overview.openHigh') }}</span></div>
      <div class="stat" :class="{ bad: overview.findings.overdue }"><strong>{{ overview.findings.overdue }}</strong><span>{{ t('applications.overview.overdueFixes') }}</span></div>
      <div class="stat" :class="{ bad: overview.findings.exceptions_expired }"><strong>{{ overview.findings.exceptions_expired }}</strong><span>{{ t('applications.overview.exceptionsExpired') }}</span></div>
      <div class="stat" :class="{ warn: overview.without_assets }"><strong>{{ overview.without_assets }}</strong><span>{{ t('applications.overview.withoutAssets') }}</span></div>
    </div>

    <div class="toolbar">
      <span class="p-input-icon-left search">
        <i class="pi pi-search" />
        <InputText v-model="search" :placeholder="t('applications.searchPlaceholder')" class="w-full" @input="onSearch" />
      </span>
      <Dropdown v-model="tier" :options="tierOptions" optionLabel="label" optionValue="value" showClear
                :placeholder="t('applications.allTiers')" class="filter" @change="reload" />
      <Dropdown v-model="status" :options="statusOptions" optionLabel="label" optionValue="value" showClear
                :placeholder="t('applications.allStatuses')" class="filter" @change="reload" />
    </div>

    <DataTable :value="items" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
               :rowsPerPageOptions="[25, 50, 100]" selectionMode="single" class="rows" @page="onPage" @row-click="e => open(e.data)">
      <template #empty>{{ t('applications.empty') }}</template>
      <Column field="code" :header="t('applications.columns.code')" style="width: 7rem" />
      <Column field="name" :header="t('applications.columns.name')" />
      <Column :header="t('applications.columns.tier')" style="width: 11rem">
        <template #body="{ data }"><Tag v-if="data.tier" :value="t(`applications.tiers.${data.tier}`).split(' - ')[0]" :severity="tierSeverity(data.tier)" /></template>
      </Column>
      <Column :header="t('applications.columns.status')" style="width: 9rem">
        <template #body="{ data }"><Tag :value="t(`applications.statuses.${data.lifecycle_status}`)" :severity="statusSeverity(data.lifecycle_status)" /></template>
      </Column>
      <Column :header="t('applications.columns.url')">
        <template #body="{ data }">{{ data.primary_url || '' }}</template>
      </Column>
      <Column field="asset_count" :header="t('applications.columns.servers')" style="width: 6rem" />
      <Column field="integration_count" :header="t('applications.columns.integrations')" style="width: 8rem" />
      <Column field="business_owner" :header="t('applications.columns.business')" />
      <Column field="technical_owner" :header="t('applications.columns.technical')" />
      <Column :header="t('applications.columns.ssl')" style="width: 10rem">
        <template #body="{ data }">
          <span v-if="data.ssl_expiry_date">{{ formatDate(data.ssl_expiry_date) }}
            <Tag :value="t(`applications.ssl.${data.ssl_state}`)" :severity="sslSeverity(data.ssl_state)" class="chip" /></span>
        </template>
      </Column>
    </DataTable>

    <Dialog v-model:visible="alertsOpen" modal :header="t('applications.alerts.title')" :style="{ width: '34rem', maxWidth: '96vw' }">
      <p class="hint">{{ t('applications.alerts.hint') }}</p>
      <Message v-if="alertsError" severity="error" :closable="true" @close="alertsError = ''">{{ alertsError }}</Message>
      <Message v-if="alertsResult" severity="success" :closable="true" @close="alertsResult = ''">{{ alertsResult }}</Message>
      <div v-if="alertsLoading" class="loading"><i class="pi pi-spin pi-spinner"></i></div>
      <template v-else>
        <label class="check"><Checkbox v-model="alerts.enabled" binary /><span>{{ t('applications.alerts.enabled') }}</span></label>
        <div class="p-field">
          <label>{{ t('applications.alerts.leadDays') }}</label>
          <InputText v-model="alerts.leadText" placeholder="90, 30, 7" class="w-full" />
          <small class="muted">{{ t('applications.alerts.leadHelp') }}</small>
        </div>
        <div class="p-field">
          <label>{{ t('applications.alerts.warnDays') }}</label>
          <InputNumber v-model="alerts.finding_warn_days" :min="0" :max="90" :useGrouping="false" class="w-full" />
          <small class="muted">{{ t('applications.alerts.warnHelp') }}</small>
        </div>
      </template>
      <template #footer>
        <Button :label="t('applications.alerts.runNow')" icon="pi pi-send" text :loading="alertsRunning" @click="runAlerts" />
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="alertsOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="alertsSaving" :disabled="alertsLoading" @click="saveAlerts" />
      </template>
    </Dialog>

    <ApplicationForm v-model:visible="formOpen" :application="null" @saved="onSaved" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import ApplicationForm from '../components/forms/ApplicationForm.vue'
import Dialog from 'primevue/dialog'
import InputNumber from 'primevue/inputnumber'
import Checkbox from 'primevue/checkbox'
import { usePermissions } from '../composables/usePermissions'
import { useDateFormatter } from '../composables/useDateFormatter'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const router = useRouter()
const { canWrite, canDelete } = usePermissions()
const { formatDate } = useDateFormatter()

const items = ref([])
const total = ref(0)
const loading = ref(false)
const message = ref(null)
const search = ref('')
const tier = ref(null)
const status = ref(null)
const rows = ref(50)
const first = ref(0)
const formOpen = ref(false)

const TIERS = ['tier1', 'tier2', 'tier3', 'tier4']
const STATUSES = ['planned', 'development', 'staging', 'uat', 'production', 'dr', 'deprecated', 'retired']
const tierOptions = computed(() => TIERS.map(v => ({ value: v, label: t(`applications.tiers.${v}`) })))
const statusOptions = computed(() => STATUSES.map(v => ({ value: v, label: t(`applications.statuses.${v}`) })))

const tierSeverity = v => ({ tier1: 'danger', tier2: 'warning', tier3: 'info', tier4: 'secondary' }[v])
const statusSeverity = v => ({ production: 'success', staging: 'info', uat: 'info', deprecated: 'warning', retired: 'secondary' }[v] || 'secondary')
const sslSeverity = v => ({ valid: 'success', expiring: 'warning', expired: 'danger' }[v])

let request = 0  // only the newest answer is shown, so a slow earlier request cannot overwrite it
async function load() {
  const mine = ++request
  loading.value = true
  try {
    const params = { skip: first.value, limit: rows.value }
    if (search.value.trim()) params.search = search.value.trim()
    if (tier.value) params.tier = tier.value
    if (status.value) params.lifecycle_status = status.value
    const res = await api.getApplications(params)
    if (mine !== request) return
    items.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (err) {
    if (mine === request) message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    if (mine === request) loading.value = false
  }
}

function reload() {
  first.value = 0
  load()
}

let timer = null
function onSearch() {
  clearTimeout(timer)
  timer = setTimeout(reload, 300)
}

function onPage(event) {
  first.value = event.first
  rows.value = event.rows
  load()
}

const open = app => router.push(`/applications/${app.id}`)
const openForm = () => { formOpen.value = true }
function onSaved(app) {
  message.value = { severity: 'success', text: t('applications.saved') }
  open(app)
}

// --- overview numbers ---
const overview = ref(null)
async function loadOverview() {
  try {
    overview.value = (await api.getApplicationsOverview()).data
  } catch (e) {
    overview.value = null
  }
}

// --- alerts ---
const alertsOpen = ref(false)
const alertsLoading = ref(false)
const alertsSaving = ref(false)
const alertsRunning = ref(false)
const alertsError = ref('')
const alertsResult = ref('')
const alerts = ref({ enabled: true, leadText: '', finding_warn_days: 3 })

async function openAlerts() {
  alertsOpen.value = true
  alertsLoading.value = true
  alertsError.value = ''
  alertsResult.value = ''
  try {
    const s = (await api.getApplicationAlertSettings()).data
    alerts.value = { enabled: s.enabled, leadText: (s.lead_days || []).join(', '), finding_warn_days: s.finding_warn_days }
  } catch (err) {
    alertsError.value = apiErrorText(err, t)
  } finally {
    alertsLoading.value = false
  }
}

function parseLeadDays(text) {
  return String(text).split(/[,\s;]+/).filter(Boolean).map(Number)
}

async function saveAlerts() {
  alertsError.value = ''
  const lead = parseLeadDays(alerts.value.leadText)
  if (!lead.length || lead.some(n => !Number.isInteger(n) || n < 1)) {
    alertsError.value = t('applications.alerts.leadInvalid')
    return
  }
  alertsSaving.value = true
  try {
    await api.saveApplicationAlertSettings({ enabled: alerts.value.enabled, lead_days: lead, finding_warn_days: alerts.value.finding_warn_days ?? 0 })
    alertsOpen.value = false
    message.value = { severity: 'success', text: t('applications.alerts.saved') }
  } catch (err) {
    alertsError.value = apiErrorText(err, t)
  } finally {
    alertsSaving.value = false
  }
}

async function runAlerts() {
  alertsError.value = ''
  alertsResult.value = ''
  alertsRunning.value = true
  try {
    const r = (await api.runApplicationAlerts()).data
    alertsResult.value = r.skipped_disabled ? t('applications.alerts.disabledResult')
      : t('applications.alerts.runResult', { items: r.items, emails: r.emails, none: r.no_recipients })
  } catch (err) {
    alertsError.value = apiErrorText(err, t)
  } finally {
    alertsRunning.value = false
  }
}

onMounted(() => { load(); loadOverview() })
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.search { flex: 1 1 18rem; max-width: 26rem; }
.filter { min-width: 13rem; }
.rows :deep(tr) { cursor: pointer; }
.chip { margin-left: 0.35rem; }
.overview { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 1rem; }
.stat { min-width: 6.2rem; padding: 0.5rem 0.8rem; border: 1px solid var(--sk-border, #e1e7e3); border-radius: 8px; display: flex; flex-direction: column; background: var(--sk-surface, #fff); }
.stat strong { font-size: 1.3rem; line-height: 1.2; }
.stat span { font-size: 0.78rem; color: var(--sk-text-muted, #6b7a71); }
.stat.bad { border-color: #dc2626; }
.stat.bad strong { color: #dc2626; }
.stat.warn { border-color: #ea580c; }
.stat.warn strong { color: #ea580c; }
.check { display: inline-flex; align-items: center; gap: 0.5rem; cursor: pointer; margin-bottom: 0.75rem; }
.loading { padding: 1.5rem; text-align: center; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.p-field { margin-bottom: 0.75rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
</style>
