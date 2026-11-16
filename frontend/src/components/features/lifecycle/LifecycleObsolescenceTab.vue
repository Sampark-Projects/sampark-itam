<template>
  <div>
    <p class="hint">{{ t('lifecycle.obsolescence.hint') }}</p>

    <div class="toolbar">
      <div class="flex gap-2 flex-wrap">
        <Dropdown v-model="siteId" :options="sites" optionLabel="name" optionValue="id" showClear :placeholder="t('lifecycle.obsolescence.allSites')" @change="load" />
        <Dropdown v-model="criticality" :options="criticalityOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('lifecycle.obsolescence.allCriticality')" @change="load" />
      </div>
      <Button :label="t('lifecycle.obsolescence.export')" icon="pi pi-download" severity="secondary" outlined :disabled="!report.items.length" @click="exportCsv" />
    </div>

    <div class="tiles">
      <div v-for="key in ['obsolete', 'soon', 'later', 'unknown']" :key="key" :class="['tile', `tile-${key}`]">
        <span class="tile-count">{{ report.summary[key] }}</span>
        <span class="tile-label">{{ t(`lifecycle.states.${key}`) }}</span>
      </div>
    </div>

    <div v-if="loading" class="loader-row" role="status" aria-live="polite">
      <ProgressSpinner style="width: 1.5rem; height: 1.5rem" strokeWidth="6" /><span>{{ t('common.loading') }}</span>
    </div>
    <p v-if="!loading && !report.items.length" class="hint">{{ t('lifecycle.obsolescence.empty') }}</p>

    <div v-if="report.by_year.length" class="chart-block">
      <h4>{{ t('lifecycle.obsolescence.byYear') }}</h4>
      <div v-for="row in report.by_year" :key="row.year" class="bar-row">
        <span class="bar-label">{{ row.year }}</span>
        <div class="bar-track"><div class="bar-fill" :style="{ width: barWidth(row.count) }"></div></div>
        <span class="bar-count">{{ row.count }}</span>
      </div>
    </div>

    <div v-if="report.by_site.length || report.by_criticality.length" class="grid">
      <div class="col-12 md:col-6">
        <h4>{{ t('lifecycle.obsolescence.bySite') }}</h4>
        <DataTable :value="report.by_site" size="small">
          <Column field="site" :header="t('lifecycle.obsolescence.site')" />
          <Column field="obsolete" :header="t('lifecycle.states.obsolete')" />
          <Column field="soon" :header="t('lifecycle.states.soon')" />
          <Column field="later" :header="t('lifecycle.states.later')" />
        </DataTable>
      </div>
      <div class="col-12 md:col-6">
        <h4>{{ t('lifecycle.obsolescence.byCriticality') }}</h4>
        <DataTable :value="report.by_criticality" size="small">
          <Column field="criticality" :header="t('lifecycle.obsolescence.criticality')" />
          <Column field="obsolete" :header="t('lifecycle.states.obsolete')" />
          <Column field="soon" :header="t('lifecycle.states.soon')" />
          <Column field="later" :header="t('lifecycle.states.later')" />
        </DataTable>
      </div>
    </div>

    <DataTable v-if="report.items.length" :value="report.items" :loading="loading" size="small" paginator :rows="15" stripedRows class="mt-3">
      <Column field="name" :header="t('lifecycle.obsolescence.assets')" sortable>
        <template #body="{ data }">
          <router-link :to="`/assets/${data.asset_id}`" class="asset-link">{{ data.name }}</router-link>
          <small v-if="data.tag" class="muted"> · {{ data.tag }}</small>
        </template>
      </Column>
      <Column field="site" :header="t('lifecycle.obsolescence.site')" sortable />
      <Column field="manufacturer" :header="t('lifecycle.obsolescence.manufacturer')" sortable />
      <Column field="model" :header="t('lifecycle.obsolescence.model')" sortable />
      <Column field="criticality" :header="t('lifecycle.obsolescence.criticality')" sortable />
      <Column field="obsolescence_date" :header="t('lifecycle.obsolescence.supportEnds')" sortable>
        <template #body="{ data }">{{ formatDate(data.obsolescence_date) }}</template>
      </Column>
      <Column :header="t('common.fields.status')">
        <template #body="{ data }">
          <Tag :value="t(`lifecycle.states.${data.state}`)" :severity="data.state === 'obsolete' ? 'danger' : (data.state === 'soon' ? 'warning' : 'info')" />
        </template>
      </Column>
    </DataTable>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dropdown from 'primevue/dropdown'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import api from '@/api/api'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { toCsv, downloadText } from '../../../utils/money'

const { t } = useI18n()
const { formatDate } = useDateFormatter()

const empty = () => ({ summary: { obsolete: 0, soon: 0, later: 0, unknown: 0 }, by_year: [], by_site: [], by_criticality: [], items: [] })
const report = ref(empty())
import ProgressSpinner from 'primevue/progressspinner'
const loading = ref(false)
const sites = ref([])
const siteId = ref(null)
const criticality = ref(null)
const criticalityOptions = ['low', 'medium', 'high', 'critical'].map(v => ({ value: v, label: v.charAt(0).toUpperCase() + v.slice(1) }))

const maxYear = computed(() => Math.max(1, ...report.value.by_year.map(r => r.count)))
const barWidth = (count) => `${Math.round((count / maxYear.value) * 100)}%`

async function load() {
  loading.value = true
  try {
    const params = {}
    if (siteId.value) params.site_id = siteId.value
    if (criticality.value) params.criticality = criticality.value
    const res = await api.getLifecycleObsolescence(params)
    report.value = { ...empty(), ...(res.data || {}) }
  } catch (err) {
    report.value = empty()
  } finally {
    loading.value = false
  }
}

function exportCsv() {
  const headers = ['Asset', 'Tag', 'Site', 'Manufacturer', 'Model', 'Criticality', 'End of support', 'End of life', 'State', 'Source']
  const rows = report.value.items.map(i => [
    i.name, i.tag, i.site, i.manufacturer, i.model, i.criticality,
    i.end_of_support_date, i.end_of_life_date, i.state, i.source
  ])
  downloadText('obsolescence.csv', toCsv(headers, rows))
}

onMounted(async () => {
  try {
    const res = await api.getSites()
    sites.value = Array.isArray(res.data) ? res.data : (res.data?.data || [])
  } catch (e) {
    sites.value = []
  }
  load()
})
</script>

<style scoped>
.loader-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.75rem 0; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
</style>

<style scoped>
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 0.75rem; margin-bottom: 1rem; }
.tile { border: 1px solid var(--sk-border, #e1e7e3); border-radius: 10px; padding: 0.75rem 1rem; background: #fff; }
.tile-count { display: block; font-size: 1.6rem; font-weight: 700; }
.tile-label { font-size: 0.8rem; color: var(--sk-text-muted, #6b7a71); }
.tile-obsolete .tile-count { color: #b3261e; }
.tile-soon .tile-count { color: #b26a00; }
.tile-later .tile-count { color: #2f6f4f; }
.chart-block { margin-bottom: 1rem; }
h4 { margin: 0 0 0.5rem; }
.bar-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.3rem; }
.bar-label { flex: 0 0 3rem; font-variant-numeric: tabular-nums; }
.bar-track { flex: 1; height: 0.9rem; background: #edf1ee; border-radius: 999px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--sk-primary, #2f6f4f); border-radius: 999px; }
.bar-count { flex: 0 0 2rem; text-align: right; font-variant-numeric: tabular-nums; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.asset-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; }
.asset-link:hover { text-decoration: underline; }
</style>
