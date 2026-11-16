<template>
  <div class="dash-tab">
    <p class="hint">{{ t('reports.dashboard.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div class="toolbar">
      <div class="field">
        <label>{{ t('reports.dashboard.groupBy') }}</label>
        <SelectButton v-model="groupBy" :options="groupOptions" optionLabel="label" optionValue="value" :allowEmpty="false" @change="load" />
      </div>
      <div class="field">
        <label for="pd_site">{{ t('reports.dashboard.scope') }}</label>
        <Dropdown v-model="siteId" inputId="pd_site" :options="sites" optionLabel="name" optionValue="id" showClear
                  :placeholder="t('reports.dashboard.allSites')" @change="load" />
      </div>
      <div class="spacer"></div>
      <Button v-if="canSetTargets" :label="t('reports.dashboard.targets')" icon="pi pi-bullseye" severity="secondary" outlined @click="openTargets" />
      <Button :label="t('reports.dashboard.refresh')" icon="pi pi-refresh" severity="secondary" text :loading="loading" @click="load" />
    </div>

    <DataTable :value="tableRows" :loading="loading" dataKey="key" class="kpi-table" scrollable>
      <template #empty>{{ t('reports.dashboard.empty') }}</template>
      <Column field="name" :header="t('reports.dashboard.name')" frozen style="min-width: 12rem">
        <template #body="{ data }">
          <strong v-if="data.isTotal">{{ t('reports.dashboard.total') }}</strong>
          <span v-else>{{ rowName(data) }}</span>
        </template>
      </Column>
      <Column v-for="m in metricKeys" :key="m" style="min-width: 9rem">
        <template #header>
          <span v-tooltip.top="helpText(m)">{{ t(`reports.metrics.${m}`) }}</span>
        </template>
        <template #body="{ data }">
          <div class="cell" :class="`st-${data.status[m]}`">
            <span class="value">{{ formatValue(m, data.metrics[m]) }}</span>
            <small v-if="data.targets[m] !== undefined && data.targets[m] !== null" class="target">
              {{ t('reports.dashboard.target') }} {{ m === 'baseline_coverage' ? '≥' : '≤' }} {{ formatValue(m, data.targets[m]) }}
            </small>
            <Tag v-if="data.status[m] === 'met' || data.status[m] === 'missed'"
                 :value="t(`reports.status.${data.status[m]}`)" :severity="data.status[m] === 'met' ? 'success' : 'danger'" />
          </div>
        </template>
      </Column>
    </DataTable>
    <small v-if="generatedAt" class="hint">{{ t('reports.dashboard.generated', { time: generatedAt }) }}</small>

    <h3 class="trend-title">{{ t('reports.trend.title') }}</h3>
    <div class="toolbar">
      <SelectButton v-model="trendDays" :options="trendOptions" optionLabel="label" optionValue="value" :allowEmpty="false" @change="loadTrend" />
      <small class="hint trend-hint">{{ t('reports.trend.hint') }}</small>
    </div>
    <div v-if="trendLoading" class="loader-row" role="status" aria-live="polite">
      <ProgressSpinner style="width: 1.5rem; height: 1.5rem" strokeWidth="6" /><span>{{ t('common.loading') }}</span>
    </div>
    <div v-else class="trend-grid">
      <div v-for="card in trendCards" :key="card.metric" class="trend-card">
        <div class="trend-name">{{ t(`reports.metrics.${card.metric}`) }}</div>
        <div class="trend-value">{{ formatValue(card.metric, card.last) }}
          <small v-if="card.delta !== null" :class="deltaClass(card)">{{ card.delta > 0 ? '+' : '' }}{{ card.delta }}</small>
        </div>
        <svg v-if="card.path" class="spark" viewBox="0 0 120 32" preserveAspectRatio="none" role="img"
             :aria-label="t(`reports.metrics.${card.metric}`)">
          <polyline :points="card.path" fill="none" stroke="currentColor" stroke-width="1.6" vector-effect="non-scaling-stroke" />
        </svg>
        <small v-else class="hint">{{ t('reports.trend.notEnough') }}</small>
      </div>
    </div>

    <Dialog v-model:visible="targetsOpen" modal :header="t('reports.targetsDialog.title')" :style="{ width: '34rem', maxWidth: '95vw' }">
      <p class="hint">{{ t('reports.targetsDialog.hint') }}</p>
      <Message v-if="targetMessage" :severity="targetMessage.severity" :closable="true" @close="targetMessage = null">{{ targetMessage.text }}</Message>
      <div class="field wide">
        <label for="tg_scope">{{ t('reports.targetsDialog.scope') }}</label>
        <Dropdown v-model="targetScope" inputId="tg_scope" :options="scopeOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div v-for="m in targetable" :key="m" class="target-row">
        <div class="target-name">
          <span>{{ t(`reports.metrics.${m}`) }}</span>
          <small>{{ m === 'baseline_coverage' ? t('reports.targetsDialog.floor') : t('reports.targetsDialog.ceiling') }}</small>
        </div>
        <InputNumber v-model="draft[m]" @input="draft[m] = $event.value" :min="0" :max="m === 'baseline_coverage' ? 100 : 1000000" :useGrouping="false"
                     :placeholder="t('reports.targetsDialog.noTarget')" :suffix="m === 'baseline_coverage' ? ' %' : ''" class="target-input" />
        <Button :label="t('reports.targetsDialog.save')" size="small" @click="saveTarget(m)" />
        <Button :label="t('reports.targetsDialog.clear')" size="small" severity="secondary" text :disabled="!hasStored(m)" @click="clearTarget(m)" />
      </div>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dropdown from 'primevue/dropdown'
import SelectButton from 'primevue/selectbutton'
import InputNumber from 'primevue/inputnumber'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'

const { t } = useI18n()
const { canDelete } = usePermissions()
// targets are configuration, like workflow definitions
const canSetTargets = computed(() => canDelete('reports'))

const metricKeys = ['assets_total', 'expired_support', 'obsolete_assets', 'baseline_coverage', 'config_drift',
  'overdue_maintenance', 'open_changes', 'unapproved_changes', 'workflows_in_progress']

const groupBy = ref('site')
const siteId = ref(null)
const sites = ref([])
const rows = ref([])
const totals = ref(null)
const unapprovedDays = ref(30)
const generatedAt = ref('')
import ProgressSpinner from 'primevue/progressspinner'
const loading = ref(false)
const message = ref(null)

const groupOptions = computed(() => [
  { value: 'site', label: t('reports.dashboard.bySite') },
  { value: 'area', label: t('reports.dashboard.byArea') }
])

const tableRows = computed(() => {
  const list = rows.value.map(r => ({ ...r, isTotal: false }))
  if (totals.value && list.length) list.push({ ...totals.value, key: '__total', isTotal: true })
  return list
})

function rowName(row) {
  return row.key === '-' && groupBy.value === 'area' ? t('reports.dashboard.noArea') : row.name
}

function formatValue(metric, value) {
  if (value === null || value === undefined) return '-'
  return metric === 'baseline_coverage' ? `${value}%` : String(value)
}

function helpText(metric) {
  return t(`reports.metricHelp.${metric}`, { days: unapprovedDays.value })
}

// --- trend (daily snapshots) ---
const trendDays = ref(90)
const trend = ref(null)
const trendOptions = computed(() => [30, 90, 180].map(d => ({ value: d, label: t('reports.trend.days', { n: d }) })))
// metrics where an increase is bad (all except the ones that are only informational or "higher is better")
const higherIsBetter = ['baseline_coverage']
const neutral = ['assets_total', 'workflows_in_progress']

const trendCards = computed(() => {
  if (!trend.value) return []
  return metricKeys.map(metric => {
    const values = trend.value.series[metric] || []
    const known = values.map((v, i) => ({ v, i })).filter(p => p.v !== null && p.v !== undefined)
    const last = known.length ? known[known.length - 1].v : null
    const delta = known.length > 1 ? Math.round((last - known[0].v) * 10) / 10 : null
    let path = ''
    if (known.length > 1) {
      const min = Math.min(...known.map(p => p.v))
      const max = Math.max(...known.map(p => p.v))
      const span = max - min || 1
      const n = values.length - 1 || 1
      path = known.map(p => `${((p.i / n) * 120).toFixed(1)},${(30 - ((p.v - min) / span) * 28).toFixed(1)}`).join(' ')
    }
    return { metric, last, delta, path }
  })
})

function deltaClass(card) {
  if (!card.delta || neutral.includes(card.metric)) return 'flat'
  const good = higherIsBetter.includes(card.metric) ? card.delta > 0 : card.delta < 0
  return good ? 'good' : 'bad'
}

const trendLoading = ref(false)
async function loadTrend() {
  trendLoading.value = true
  try {
    const params = { days: trendDays.value }
    if (siteId.value) params.site_id = siteId.value
    trend.value = (await api.getKpiTrend(params)).data
  } catch (err) {
    trend.value = null
  } finally {
    trendLoading.value = false
  }
}

async function load() {
  loadTrend()
  loading.value = true
  message.value = null
  try {
    const params = { group_by: groupBy.value }
    if (siteId.value) params.site_id = siteId.value
    const res = await api.getPlantDashboard(params)
    rows.value = res.data.rows || []
    totals.value = res.data.totals || null
    unapprovedDays.value = res.data.unapproved_days || 30
    generatedAt.value = res.data.generated_at ? new Date(res.data.generated_at + 'Z').toLocaleString() : ''
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    loading.value = false
  }
}

// --- targets editor ---
const targetsOpen = ref(false)
const targetable = ref([])
const stored = ref([])
const targetScope = ref('all')
const draft = ref({})
const targetMessage = ref(null)

const scopeOptions = computed(() => [
  { value: 'all', label: t('reports.targetsDialog.allSites') },
  ...sites.value.map(s => ({ value: s.id, label: s.name }))
])

function fillDraft() {
  const scope = targetScope.value === 'all' ? null : targetScope.value
  const next = {}
  for (const m of targetable.value) {
    const hit = stored.value.find(i => i.metric === m && (i.site_id || null) === scope)
    next[m] = hit ? hit.target_value : null
  }
  draft.value = next
}

function hasStored(metric) {
  const scope = targetScope.value === 'all' ? null : targetScope.value
  return stored.value.some(i => i.metric === metric && (i.site_id || null) === scope)
}

async function loadTargets() {
  const res = await api.getKpiTargets()
  targetable.value = Object.keys(res.data.metrics || {})
  stored.value = res.data.items || []
  fillDraft()
}

async function openTargets() {
  targetMessage.value = null
  try {
    await loadTargets()
    targetsOpen.value = true
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

watch(targetScope, fillDraft)

async function saveTarget(metric) {
  targetMessage.value = null
  if (draft.value[metric] === null || draft.value[metric] === undefined) return
  try {
    await api.setKpiTarget({
      metric, site_id: targetScope.value === 'all' ? null : targetScope.value, target_value: draft.value[metric]
    })
    await loadTargets()
    targetMessage.value = { severity: 'success', text: t('reports.targetsDialog.saved') }
    load()
  } catch (err) {
    targetMessage.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

async function clearTarget(metric) {
  targetMessage.value = null
  try {
    const params = { metric }
    if (targetScope.value !== 'all') params.site_id = targetScope.value
    await api.clearKpiTarget(params)
    await loadTargets()
    targetMessage.value = { severity: 'success', text: t('reports.targetsDialog.cleared') }
    load()
  } catch (err) {
    targetMessage.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

onMounted(async () => {
  try {
    const res = await api.getSites()
    sites.value = Array.isArray(res.data) ? res.data : (res.data?.data || [])
  } catch (err) {
    sites.value = []
  }
  load()
})
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; display: block; }
.toolbar { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 1rem; margin-bottom: 1rem; }
.toolbar .spacer { flex: 1; }
.field label, .field.wide label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
.field.wide { margin-bottom: 1rem; }
.cell { display: flex; flex-direction: column; gap: 0.2rem; align-items: flex-start; }
.cell .value { font-size: 1.15rem; font-weight: 600; }
.cell .target { color: var(--sk-text-muted, #6b7a71); }
.loader-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.75rem 0; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.trend-title { margin: 1.75rem 0 0.75rem; }
.trend-hint { margin: 0; }
.trend-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr)); gap: 0.75rem; }
.trend-card { border: 1px solid var(--sk-border, #dfe6e1); border-radius: 8px; padding: 0.75rem; display: flex; flex-direction: column; gap: 0.25rem; }
.trend-name { font-size: 0.85rem; color: var(--sk-text-muted, #6b7a71); }
.trend-value { font-size: 1.25rem; font-weight: 600; }
.trend-value small { font-size: 0.8rem; margin-left: 0.35rem; }
.trend-value .good { color: var(--green-600, #2e7d32); }
.trend-value .bad { color: var(--red-600, #c0392b); }
.trend-value .flat { color: var(--sk-text-muted, #6b7a71); }
.spark { width: 100%; height: 2rem; color: var(--primary-color, #2e7d32); }
.target-row { display: grid; grid-template-columns: 1fr 8rem auto auto; gap: 0.5rem; align-items: center; margin-bottom: 0.6rem; }
.target-name { display: flex; flex-direction: column; }
.target-name small { color: var(--sk-text-muted, #6b7a71); }
.target-input { width: 100%; }
@media (max-width: 600px) {
  .target-row { grid-template-columns: 1fr 1fr; }
  .target-name { grid-column: 1 / -1; }
}
</style>
