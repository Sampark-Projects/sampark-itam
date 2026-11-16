<template>
  <section class="dcard">
    <h3 class="dcard-title">
      <span class="dcard-icon"><i class="pi pi-sync"></i></span>{{ t('assets.lifecycle.title') }}
    </h3>

    <div v-if="loadingExtra" class="loader-row" role="status" aria-live="polite">
      <ProgressSpinner style="width: 1.5rem; height: 1.5rem" strokeWidth="6" /><span>{{ t('common.loading') }}</span>
    </div>
    <p v-else-if="!hasAnyData" class="lifecycle-empty">{{ t('assets.lifecycle.empty') }}</p>

    <template v-else>
      <div v-for="group in visibleGroups" :key="group.key" class="lifecycle-group">
        <h4 class="lifecycle-group-title">{{ group.title }}</h4>
        <dl class="dfields">
          <div v-for="row in group.rows" :key="row.field" class="dfield">
            <dt>{{ row.label }}</dt>
            <dd :class="{ 'is-empty': !row.display }">
              {{ row.display || t('common.strings.na') }}
              <span v-if="row.expiry" :class="['expiry-tag', `expiry-${row.expiry}`]">
                {{ t(`assets.lifecycle.expiry.${row.expiry}`) }}
              </span>
            </dd>
          </div>
        </dl>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { expiryState } from '../../../utils/localDate'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'

const props = defineProps({
  asset: { type: Object, required: true }
})

const { t } = useI18n()
const { formatDate } = useDateFormatter()
const { canRead } = usePermissions()

// vendor end-of-life data that matches this asset's manufacturer and model (shown when there is one)
import ProgressSpinner from 'primevue/progressspinner'
const pending = ref(0)
const loadingExtra = computed(() => pending.value > 0)
const vendorMatch = ref(null)
watch(() => [props.asset?.id, props.asset?.model, props.asset?.manufacturer_id], async () => {
  vendorMatch.value = null
  if (!props.asset?.id || !canRead('lifecycle')) return
  pending.value++
  try {
    const res = await api.getAssetVendorLifecycle(props.asset.id)
    vendorMatch.value = res.data?.match || null
  } catch (e) {
    vendorMatch.value = null
  } finally {
    pending.value--
  }
}, { immediate: true })

// the purchase request line this asset was received against
const receipt = ref(null)
watch(() => props.asset?.id, async (id) => {
  receipt.value = null
  if (!id || !canRead('lifecycle')) return
  pending.value++
  try {
    const res = await api.getAssetReceipt(id)
    if (props.asset?.id === id) receipt.value = res.data?.line ? res.data : null
  } catch (e) {
    receipt.value = null
  } finally {
    pending.value--
  }
}, { immediate: true })

const SAFETY_KEYS = { none: 'none', safety_related: 'safetyRelated', safety_critical: 'safetyCritical' }

function money(amount, currency) {
  if (amount === null || amount === undefined || amount === '') return ''
  const value = Number(amount)
  if (currency) {
    try {
      return new Intl.NumberFormat('en-IN', { style: 'currency', currency }).format(value)
    } catch (e) {
      // unknown currency code: fall through to the plain number + code
    }
  }
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value) + (currency ? ` ${currency}` : '')
}

const groups = computed(() => {
  const a = props.asset
  const label = (key) => t(`assets.lifecycle.fields.${key}`)
  const date = (field, key, { expiry = false } = {}) => ({
    field,
    label: label(key),
    display: a[field] ? formatDate(a[field]) : '',
    expiry: expiry ? expiryState(a[field]) : null
  })
  const text = (field, key) => ({ field, label: label(key), display: a[field] || '', expiry: null })

  return [
    {
      key: 'classification',
      title: t('assets.lifecycle.classification'),
      rows: [
        {
          field: 'safety_relevance',
          label: label('safetyRelevance'),
          display: a.safety_relevance ? t(`assets.lifecycle.safety.${SAFETY_KEYS[a.safety_relevance] || 'none'}`) : '',
          expiry: null
        },
        text('plant_owner', 'plantOwner'),
        text('amc_partner', 'amcPartner')
      ]
    },
    {
      key: 'procurement',
      title: t('assets.lifecycle.procurement'),
      rows: [
        text('requisition_number', 'requisitionNumber'),
        text('purchase_order_number', 'purchaseOrderNumber'),
        date('purchase_date', 'purchaseDate'),
        date('expected_delivery_date', 'expectedDeliveryDate'),
        date('received_date', 'receivedDate'),
        { field: 'purchase_cost', label: label('purchaseCost'), display: money(a.purchase_cost, a.cost_currency), expiry: null },
        {
          field: 'order_line',
          label: t('procurement.asset.receivedAgainst'),
          display: receipt.value?.order
            ? `${receipt.value.order.code} · ${receipt.value.order.title} (${t('procurement.asset.line', { n: receipt.value.line.position })})` +
              (receipt.value.mismatch_note ? ` — ${t('procurement.asset.accepted')}: ${receipt.value.mismatch_note}` : '')
            : '',
          expiry: null
        }
      ]
    },
    {
      key: 'commissioning',
      title: t('assets.lifecycle.commissioning'),
      rows: [
        date('commissioned_date', 'commissionedDate'),
        date('acceptance_date', 'acceptanceDate'),
        text('acceptance_signed_by', 'acceptanceSignedBy')
      ]
    },
    {
      key: 'vendor',
      title: t('lifecycle.vendor.matchedFor'),
      rows: vendorMatch.value ? [
        { field: 'vendor_eos', label: t('lifecycle.vendor.endOfSale'), display: vendorMatch.value.end_of_sale_date ? formatDate(vendorMatch.value.end_of_sale_date) : '', expiry: null },
        { field: 'vendor_eosl', label: t('lifecycle.vendor.endOfSupport'), display: vendorMatch.value.end_of_support_date ? formatDate(vendorMatch.value.end_of_support_date) : '', expiry: expiryState(vendorMatch.value.end_of_support_date) },
        { field: 'vendor_eol', label: t('lifecycle.vendor.endOfLife'), display: vendorMatch.value.end_of_life_date ? formatDate(vendorMatch.value.end_of_life_date) : '', expiry: expiryState(vendorMatch.value.end_of_life_date) }
      ] : []
    },
    {
      key: 'support',
      title: t('assets.lifecycle.support'),
      rows: [
        date('warranty_expiry_date', 'warrantyExpiryDate', { expiry: true }),
        date('amc_expiry_date', 'amcExpiryDate', { expiry: true }),
        date('support_expiry_date', 'supportExpiryDate', { expiry: true }),
        date('licence_expiry_date', 'licenceExpiryDate', { expiry: true })
      ]
    },
    {
      key: 'disposal',
      title: t('assets.lifecycle.disposal'),
      rows: [
        {
          field: 'disposal_method',
          label: label('disposalMethod'),
          display: a.disposal_method ? t(`assets.lifecycle.disposalMethods.${a.disposal_method}`) : '',
          expiry: null
        },
        date('disposal_date', 'disposalDate'),
        text('disposal_reference', 'disposalReference')
      ]
    }
  ]
})

// Only groups that have at least one value are shown
const visibleGroups = computed(() => groups.value.filter(g => g.rows.some(r => r.display)))
const hasAnyData = computed(() => visibleGroups.value.length > 0)
</script>

<style scoped>
.loader-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.75rem 0; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.lifecycle-empty { margin: 0; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.lifecycle-group + .lifecycle-group { margin-top: 1.1rem; padding-top: 1rem; border-top: 1px solid var(--sk-border, #e1e7e3); }
.lifecycle-group-title {
  margin: 0 0 0.75rem;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--sk-text-muted, #6b7a71);
}
.is-empty { color: #aab4ae; font-weight: 400; }
.expiry-tag {
  display: inline-block;
  margin-left: 0.5rem;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
}
.expiry-expired { background: #fdecec; color: #b42318; }
.expiry-soon { background: #fff6dc; color: #946200; }
.expiry-ok { background: #e8f7ee; color: #1b7f4b; }
</style>
