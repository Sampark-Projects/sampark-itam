<template>
  <div>
    <p class="hint">{{ t('lifecycle.cost.hint') }}</p>
    <p v-if="data.assets_total" class="hint">{{ t('lifecycle.cost.assetsWithCost', { with: data.assets_with_cost, all: data.assets_total }) }}</p>
    <div v-if="loading" class="loader-row" role="status" aria-live="polite">
      <ProgressSpinner style="width: 1.5rem; height: 1.5rem" strokeWidth="6" /><span>{{ t('common.loading') }}</span>
    </div>
    <p v-if="!loading && !data.currencies.length" class="hint">{{ t('lifecycle.cost.empty') }}</p>

    <section v-for="cur in data.currencies" :key="cur.currency" class="currency-block">
      <h3>
        {{ cur.currency }}
        <span class="total">{{ t('lifecycle.cost.total') }}: {{ formatMoney(cur.total, cur.currency) }}</span>
      </h3>

      <div class="tiles">
        <div v-for="(amount, kind) in cur.by_kind" :key="kind" class="tile">
          <span class="tile-count">{{ formatMoney(amount, cur.currency) }}</span>
          <span class="tile-label">{{ t(`lifecycle.kinds.${kind}`) }}</span>
        </div>
      </div>

      <div class="grid">
        <div class="col-12 md:col-4">
          <h4>{{ t('lifecycle.cost.bySite') }}</h4>
          <DataTable :value="cur.by_site" size="small">
            <Column field="site" :header="t('lifecycle.cost.site')" />
            <Column field="total" :header="t('lifecycle.cost.amount')"><template #body="{ data: row }">{{ formatMoney(row.total, cur.currency) }}</template></Column>
          </DataTable>
        </div>
        <div class="col-12 md:col-4">
          <h4>{{ t('lifecycle.cost.byType') }}</h4>
          <DataTable :value="cur.by_type" size="small">
            <Column field="type" :header="t('lifecycle.cost.type')" />
            <Column field="total" :header="t('lifecycle.cost.amount')"><template #body="{ data: row }">{{ formatMoney(row.total, cur.currency) }}</template></Column>
          </DataTable>
        </div>
        <div class="col-12 md:col-4">
          <h4>{{ t('lifecycle.cost.topAssets') }}</h4>
          <DataTable :value="cur.top_assets" size="small">
            <Column field="name" :header="t('lifecycle.cost.asset')">
              <template #body="{ data: row }"><router-link :to="`/assets/${row.asset_id}`" class="asset-link">{{ row.name }}</router-link></template>
            </Column>
            <Column field="total" :header="t('lifecycle.cost.amount')"><template #body="{ data: row }">{{ formatMoney(row.total, cur.currency) }}</template></Column>
          </DataTable>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import api from '@/api/api'
import { formatMoney } from '../../../utils/money'

const { t } = useI18n()
const data = ref({ assets_total: 0, assets_with_cost: 0, currencies: [] })
import ProgressSpinner from 'primevue/progressspinner'
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const res = await api.getLifecycleCostSummary()
    data.value = { assets_total: 0, assets_with_cost: 0, currencies: [], ...(res.data || {}) }
  } catch (err) {
    data.value = { assets_total: 0, assets_with_cost: 0, currencies: [] }
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.loader-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.75rem 0; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
</style>

<style scoped>
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.currency-block { margin-bottom: 1.5rem; }
.currency-block h3 { display: flex; align-items: baseline; gap: 1rem; margin: 0 0 0.75rem; }
.total { font-size: 1rem; font-weight: 500; color: var(--sk-text-muted, #6b7a71); }
h4 { margin: 0 0 0.5rem; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 0.75rem; margin-bottom: 1rem; }
.tile { border: 1px solid var(--sk-border, #e1e7e3); border-radius: 10px; padding: 0.6rem 0.9rem; background: #fff; }
.tile-count { display: block; font-size: 1.1rem; font-weight: 700; }
.tile-label { font-size: 0.8rem; color: var(--sk-text-muted, #6b7a71); }
.asset-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; }
.asset-link:hover { text-decoration: underline; }
</style>
