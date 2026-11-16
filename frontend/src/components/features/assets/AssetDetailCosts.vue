<!--
  - AssetDetailCosts.vue
  - Cost of ownership of one asset: the purchase cost from the lifecycle fields plus costs recorded here
  - (maintenance, upgrade, licence, other). Totals are per currency; currencies are never converted.
-->
<template>
  <section class="dcard">
    <h3 class="dcard-title">
      <span class="dcard-icon"><i class="pi pi-wallet"></i></span>{{ t('lifecycle.assetCost.title') }}
      <span v-for="tot in data.totals" :key="tot.currency" class="dcard-count total-chip">{{ formatMoney(tot.total, tot.currency) }}</span>
    </h3>

    <p v-if="error" class="p-error">{{ error }}</p>

    <table v-if="rows.length" class="cost-table">
      <thead>
        <tr>
          <th>{{ t('lifecycle.assetCost.kind') }}</th>
          <th>{{ t('lifecycle.assetCost.date') }}</th>
          <th>{{ t('lifecycle.assetCost.description') }}</th>
          <th class="num">{{ t('lifecycle.assetCost.amount') }}</th>
          <th v-if="canWrite('lifecycle')"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.key">
          <td>{{ t(`lifecycle.kinds.${row.kind}`) }}</td>
          <td>{{ row.date ? formatDate(row.date) : '' }}</td>
          <td>{{ row.description }}</td>
          <td class="num">{{ formatMoney(row.amount, row.currency) }}</td>
          <td v-if="canWrite('lifecycle')" class="num">
            <Button v-if="row.id && canDelete('lifecycle')" icon="pi pi-trash" text rounded severity="danger" size="small" @click="remove(row.id)" />
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else class="muted">{{ t('lifecycle.assetCost.empty') }}</p>

    <div v-if="canWrite('lifecycle')" class="add-row">
      <Dropdown v-model="form.entry_type" :options="kindOptions" optionLabel="label" optionValue="value" class="f-kind" />
      <InputNumber v-model="form.amount" :min="0" :maxFractionDigits="2" :placeholder="t('lifecycle.assetCost.amount')" class="f-amount" />
      <InputText v-model="form.currency" maxlength="3" :placeholder="t('lifecycle.assetCost.currency')" class="f-currency" />
      <Calendar v-model="form.incurred_on" dateFormat="dd/mm/yy" showIcon :placeholder="t('lifecycle.assetCost.date')" class="f-date" />
      <InputText v-model="form.description" maxlength="255" :placeholder="t('lifecycle.assetCost.description')" class="f-desc" />
      <Button :label="t('lifecycle.assetCost.add')" icon="pi pi-plus" :loading="saving" @click="add" />
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from 'primevue/button'
import Dropdown from 'primevue/dropdown'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import Calendar from 'primevue/calendar'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { formatLocalDate } from '../../../utils/localDate'
import { formatMoney, apiErrorText } from '../../../utils/money'

const props = defineProps({
  asset: { type: Object, required: true }
})

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const { formatDate } = useDateFormatter()

const data = ref({ purchase_cost: null, purchase_currency: null, entries: [], totals: [] })
const error = ref('')
const saving = ref(false)

const kindOptions = computed(() => ['maintenance', 'upgrade', 'licence', 'other'].map(v => ({ value: v, label: t(`lifecycle.kinds.${v}`) })))
const blank = () => ({ entry_type: 'maintenance', amount: null, currency: '', incurred_on: null, description: '' })
const form = ref(blank())

// the purchase cost is edited with the lifecycle fields, so it is listed here read-only
const rows = computed(() => {
  const list = []
  if (data.value.purchase_cost !== null && data.value.purchase_cost !== undefined && data.value.purchase_currency) {
    list.push({
      key: 'purchase', kind: 'purchase', date: props.asset.purchase_date || null,
      description: props.asset.purchase_order_number || '', amount: data.value.purchase_cost, currency: data.value.purchase_currency
    })
  }
  for (const e of data.value.entries) {
    list.push({ key: e.id, id: e.id, kind: e.entry_type, date: e.incurred_on, description: e.description || '', amount: e.amount, currency: e.currency })
  }
  return list
})

async function load() {
  error.value = ''
  if (!props.asset?.id) return
  try {
    const res = await api.getAssetCosts(props.asset.id)
    data.value = { purchase_cost: null, purchase_currency: null, entries: [], totals: [], ...(res.data || {}) }
    if (!form.value.currency && data.value.purchase_currency) form.value.currency = data.value.purchase_currency
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

async function add() {
  error.value = ''
  const f = form.value
  if (!f.amount || !f.currency.trim() || !f.incurred_on) {
    error.value = t('lifecycle.assetCost.required')
    return
  }
  saving.value = true
  try {
    await api.addAssetCost(props.asset.id, {
      entry_type: f.entry_type,
      amount: f.amount,
      currency: f.currency.trim().toUpperCase(),
      incurred_on: formatLocalDate(f.incurred_on),
      description: f.description || null
    })
    form.value = { ...blank(), currency: f.currency }
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

async function remove(entryId) {
  try {
    await api.deleteAssetCost(props.asset.id, entryId)
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

watch(() => [props.asset?.id, props.asset?.purchase_cost, props.asset?.cost_currency], load, { immediate: true })
</script>

<style scoped>
.muted { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.total-chip { margin-left: 0.5rem; }
.cost-table { width: 100%; border-collapse: collapse; margin-bottom: 0.75rem; font-size: 0.9rem; }
.cost-table th { text-align: left; font-size: 0.75rem; letter-spacing: 0.04em; text-transform: uppercase; color: var(--sk-text-muted, #6b7a71); padding: 0.25rem 0.5rem; }
.cost-table td { padding: 0.35rem 0.5rem; border-top: 1px solid var(--sk-border, #e1e7e3); }
.num { text-align: right; }
.add-row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
.f-kind { flex: 0 0 9rem; }
.f-amount { flex: 0 0 8rem; }
.f-currency { flex: 0 0 5rem; text-transform: uppercase; }
.f-date { flex: 0 0 9rem; }
.f-desc { flex: 1 1 10rem; min-width: 0; }
</style>
