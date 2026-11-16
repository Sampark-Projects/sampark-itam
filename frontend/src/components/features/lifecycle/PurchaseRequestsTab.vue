<!--
  - PurchaseRequestsTab.vue
  - Plan and procure: purchase requests with demand, specification and lines; approval by someone
  - other than the requester; the ERP order number; deliveries booked against the lines and checked.
-->
<template>
  <div class="pr-tab">
    <p class="hint">{{ t('procurement.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div class="toolbar">
      <Dropdown v-model="statusFilter" :options="filterOptions" optionLabel="label" optionValue="value" class="filter" @change="load" />
      <span class="spacer"></span>
      <Button v-if="canWrite('lifecycle')" :label="t('procurement.new')" icon="pi pi-plus" @click="openForm(null)" />
    </div>

    <DataTable :value="orders" :loading="loading" dataKey="id" selectionMode="single" @row-click="e => openDetail(e.data.id)" class="rows">
      <template #empty>{{ t('procurement.empty') }}</template>
      <Column field="code" :header="t('procurement.code')" style="width: 7rem" />
      <Column field="title" :header="t('procurement.title')" />
      <Column :header="t('procurement.status')" style="width: 9rem">
        <template #body="{ data }"><Tag :value="t(`procurement.statuses.${data.status}`)" :severity="statusSeverity(data.status)" /></template>
      </Column>
      <Column field="po_number" :header="t('procurement.poNumber')" style="width: 9rem" />
      <Column :header="t('procurement.received')" style="width: 8rem">
        <template #body="{ data }">{{ data.received_quantity }} / {{ data.ordered_quantity }}</template>
      </Column>
      <Column :header="t('procurement.total')" style="width: 9rem">
        <template #body="{ data }">{{ data.total !== null ? formatMoney(data.total, data.currency) : '' }}</template>
      </Column>
      <Column field="requested_by" :header="t('procurement.requestedBy')" style="width: 10rem" />
    </DataTable>

    <!-- create / edit -->
    <Dialog v-model:visible="formOpen" modal :header="editing ? t('procurement.edit') : t('procurement.new')" :style="{ width: '52rem', maxWidth: '96vw' }">
      <Message v-if="formError" severity="error" :closable="false">{{ formError }}</Message>
      <div class="grid">
        <div class="col-12 p-field">
          <label for="pr_title">{{ t('procurement.title') }}</label>
          <InputText id="pr_title" v-model="form.title" maxlength="150" class="w-full" />
        </div>
        <div class="col-12 md:col-6 p-field">
          <label for="pr_just">{{ t('procurement.justification') }}</label>
          <Textarea id="pr_just" v-model="form.justification" rows="3" class="w-full" />
        </div>
        <div class="col-12 md:col-6 p-field">
          <label for="pr_spec">{{ t('procurement.specification') }}</label>
          <Textarea id="pr_spec" v-model="form.specification" rows="3" class="w-full" />
        </div>
        <div class="col-12 md:col-4 p-field">
          <label>{{ t('procurement.site') }}</label>
          <Dropdown v-model="form.site_id" :options="sites" optionLabel="name" optionValue="id" showClear filter class="w-full" />
        </div>
        <div class="col-12 md:col-4 p-field">
          <label>{{ t('procurement.supplier') }}</label>
          <Dropdown v-model="form.supplier_id" :options="suppliers" optionLabel="name" optionValue="id" showClear filter class="w-full" />
        </div>
        <div class="col-12 md:col-4 p-field">
          <label for="pr_vendor">{{ t('procurement.vendor') }}</label>
          <InputText id="pr_vendor" v-model="form.vendor_name" maxlength="255" class="w-full" />
        </div>
        <div class="col-6 md:col-4 p-field">
          <label for="pr_cur">{{ t('procurement.currency') }}</label>
          <InputText id="pr_cur" v-model="form.currency" maxlength="3" class="w-full" placeholder="INR" />
        </div>
        <div class="col-6 md:col-4 p-field">
          <label>{{ t('procurement.expectedDelivery') }}</label>
          <Calendar v-model="form.expected_delivery_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
        </div>
      </div>

      <h4 class="lines-title">{{ t('procurement.lines') }}</h4>
      <div v-for="(line, i) in form.lines" :key="line._uid" class="line-row">
        <Dropdown v-model="line.asset_type_id" :options="types" optionLabel="name" optionValue="id" showClear filter
                  :placeholder="t('procurement.assetType')" class="l-type" />
        <Dropdown v-model="line.manufacturer_id" :options="makers" optionLabel="name" optionValue="id" showClear filter
                  :placeholder="t('procurement.manufacturer')" class="l-maker" />
        <InputText v-model="line.model" maxlength="255" :placeholder="t('procurement.model')" class="l-model" />
        <InputText v-model="line.description" maxlength="255" :placeholder="t('procurement.description')" class="l-desc" />
        <InputNumber v-model="line.quantity" :min="1" :max="100000" :useGrouping="false" :placeholder="t('procurement.quantity')" class="l-qty" />
        <InputNumber v-model="line.unit_cost" :min="0" :minFractionDigits="0" :maxFractionDigits="2" :placeholder="t('procurement.unitCost')" class="l-cost" />
        <Button icon="pi pi-times" text rounded severity="danger" :aria-label="t('procurement.removeLine')" @click="form.lines.splice(i, 1)" />
      </div>
      <Button :label="t('procurement.addLine')" icon="pi pi-plus" text size="small" @click="form.lines.push(blankLine())" />

      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="formOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="save" />
      </template>
    </Dialog>

    <!-- detail, decisions and deliveries -->
    <Dialog v-model:visible="detailOpen" modal :header="detail ? `${detail.code} · ${detail.title}` : ''" :style="{ width: '56rem', maxWidth: '96vw' }">
      <template v-if="detail">
        <Message v-if="detailError" severity="error" :closable="true" @close="detailError = ''">{{ detailError }}</Message>
        <div class="facts">
          <span><Tag :value="t(`procurement.statuses.${detail.status}`)" :severity="statusSeverity(detail.status)" /></span>
          <span v-if="detail.po_number"><strong>{{ t('procurement.poNumber') }}:</strong> {{ detail.po_number }}</span>
          <span><strong>{{ t('procurement.requestedBy') }}:</strong> {{ detail.requested_by }}</span>
          <span v-if="detail.decided_by"><strong>{{ t('procurement.decidedBy') }}:</strong> {{ detail.decided_by }} ({{ formatDate(detail.decided_at) }})</span>
          <span v-if="detail.expected_delivery_date"><strong>{{ t('procurement.expectedDelivery') }}:</strong> {{ formatDate(detail.expected_delivery_date) }}</span>
          <span v-if="detail.total !== null"><strong>{{ t('procurement.total') }}:</strong> {{ formatMoney(detail.total, detail.currency) }}</span>
        </div>
        <p v-if="detail.justification" class="block-text"><strong>{{ t('procurement.justification') }}:</strong> {{ detail.justification }}</p>
        <p v-if="detail.specification" class="block-text"><strong>{{ t('procurement.specification') }}:</strong> {{ detail.specification }}</p>
        <p v-if="detail.decision_note" class="block-text"><strong>{{ t('procurement.decisionNote') }}:</strong> {{ detail.decision_note }}</p>

        <table class="lines-table">
          <thead>
            <tr>
              <th>#</th><th>{{ t('procurement.model') }} / {{ t('procurement.description') }}</th>
              <th>{{ t('procurement.quantity') }}</th><th>{{ t('procurement.received') }}</th><th>{{ t('procurement.unitCost') }}</th><th></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="l in detail.lines" :key="l.id">
              <tr>
                <td>{{ l.position }}</td>
                <td>{{ [l.model, l.description].filter(Boolean).join(' · ') }}</td>
                <td>{{ l.quantity }}</td>
                <td>{{ l.received }}</td>
                <td>{{ l.unit_cost !== null ? formatMoney(l.unit_cost, detail.currency) : '' }}</td>
                <td class="num">
                  <Button v-if="canReceive && l.received < l.quantity" :label="t('procurement.receive')" icon="pi pi-inbox" size="small" text @click="startReceive(l)" />
                </td>
              </tr>
              <tr v-if="l.assets && l.assets.length" class="sub-row">
                <td></td>
                <td colspan="5">
                  <router-link v-for="a in l.assets" :key="a.id" :to="`/assets/${a.id}`" class="asset-link" @click="detailOpen = false">
                    {{ a.name }}<small v-if="a.mismatch_note"> ({{ t('procurement.accepted') }}: {{ a.mismatch_note }})</small>
                  </router-link>
                </td>
              </tr>
              <tr v-if="receiving && receiving.line.id === l.id" class="sub-row">
                <td></td>
                <td colspan="5">
                  <div class="receive-box">
                    <AssetParentPicker v-model="receiving.assetId" :placeholder="t('procurement.pickAsset')" @update:modelValue="checkReceive" />
                    <div v-if="receiving.mismatches && receiving.mismatches.length" class="mismatch">
                      <p><i class="pi pi-exclamation-triangle"></i> {{ t('procurement.differs') }}
                        {{ receiving.mismatches.map(m => t(`procurement.mismatch.${m}`)).join(', ') }}</p>
                      <div class="flex align-items-center gap-2">
                        <Checkbox v-model="receiving.accept" binary inputId="rc_accept" />
                        <label for="rc_accept" class="inline">{{ t('procurement.acceptAnyway') }}</label>
                      </div>
                      <InputText v-if="receiving.accept" v-model="receiving.note" maxlength="2000" :placeholder="t('procurement.acceptReason')" class="w-full mt-2" />
                    </div>
                    <p v-else-if="receiving.mismatches" class="ok"><i class="pi pi-check"></i> {{ t('procurement.matches') }}</p>
                    <div class="flex gap-2 mt-2">
                      <Button :label="t('procurement.bookDelivery')" icon="pi pi-check" size="small" :disabled="!canBook" :loading="busy" @click="book" />
                      <Button :label="t('common.actions.cancel')" size="small" text severity="secondary" @click="receiving = null" />
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>

        <div v-if="detail.allowed_targets.length || detail.can_edit" class="actions-box">
          <InputText v-if="detail.allowed_targets.includes('ordered')" v-model="action.po_number" maxlength="100"
                     :placeholder="t('procurement.poNumberPlaceholder')" class="w-full mb-2" />
          <Textarea v-model="action.note" rows="2" :placeholder="t('procurement.notePlaceholder')" class="w-full mb-2" />
          <div class="flex gap-2 flex-wrap">
            <Button v-if="detail.can_edit" :label="t('procurement.edit')" icon="pi pi-pencil" size="small" outlined @click="openForm(detail)" />
            <Button v-for="target in detail.allowed_targets" :key="target" :label="t(`procurement.actions.${target}`)" size="small"
                    :severity="target === 'rejected' || target === 'cancelled' ? 'danger' : (target === 'approved' ? 'success' : undefined)"
                    :outlined="target === 'draft' || target === 'cancelled'" :loading="busy" @click="move(target)" />
          </div>
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Textarea from 'primevue/textarea'
import Calendar from 'primevue/calendar'
import Checkbox from 'primevue/checkbox'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import AssetParentPicker from '../../forms/AssetParentPicker.vue'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { formatLocalDate, parseLocalDate } from '../../../utils/localDate'
import { apiErrorText, formatMoney } from '../../../utils/money'

const { t } = useI18n()
const { canWrite } = usePermissions()
const { formatDate } = useDateFormatter()

const STATUSES = ['draft', 'submitted', 'approved', 'rejected', 'ordered', 'received', 'closed', 'cancelled']
const statusFilter = ref('open')
const filterOptions = computed(() => [
  { value: 'open', label: t('procurement.filterOpen') }, { value: null, label: t('procurement.filterAll') },
  ...STATUSES.map(s => ({ value: s, label: t(`procurement.statuses.${s}`) }))
])
const orders = ref([])
const loading = ref(false)
const message = ref(null)
const sites = ref([])
const suppliers = ref([])
const makers = ref([])
const types = ref([])

function statusSeverity(s) {
  return { approved: 'success', ordered: 'info', received: 'info', closed: 'secondary', rejected: 'danger', cancelled: 'secondary', submitted: 'warning' }[s] || undefined
}
const asList = res => (Array.isArray(res?.data) ? res.data : (res?.data?.data || res?.data?.items || []))

async function load() {
  loading.value = true
  try {
    const params = statusFilter.value ? { status: statusFilter.value } : {}
    orders.value = asList(await api.getPurchaseOrders(params))
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    loading.value = false
  }
}

// --- create / edit ---
let uid = 0
const blankLine = () => ({ _uid: ++uid, asset_type_id: null, manufacturer_id: null, model: '', description: '', quantity: 1, unit_cost: null })
const blankForm = () => ({ title: '', justification: '', specification: '', site_id: null, supplier_id: null, vendor_name: '',
  currency: '', expected_delivery_date: null, lines: [blankLine()] })
const form = ref(blankForm())
const formOpen = ref(false)
const editing = ref(null)
const formError = ref('')
const saving = ref(false)

async function loadRefs() {
  if (types.value.length) return
  const [s, sup, m, ty] = await Promise.allSettled([api.getSites(), api.getSuppliers(), api.getManufacturers(), api.getAssetTypes()])
  sites.value = s.status === 'fulfilled' ? asList(s.value) : []
  suppliers.value = sup.status === 'fulfilled' ? asList(sup.value) : []
  makers.value = m.status === 'fulfilled' ? asList(m.value) : []
  types.value = ty.status === 'fulfilled' ? asList(ty.value) : []
}

async function openForm(order) {
  formError.value = ''
  await loadRefs()
  editing.value = order
  form.value = order ? {
    title: order.title, justification: order.justification || '', specification: order.specification || '',
    site_id: order.site_id, supplier_id: order.supplier_id, vendor_name: order.vendor_name || '', currency: order.currency || '',
    expected_delivery_date: parseLocalDate(order.expected_delivery_date),
    lines: order.lines.map(l => ({ _uid: ++uid, asset_type_id: l.asset_type_id, manufacturer_id: l.manufacturer_id, model: l.model || '',
      description: l.description || '', quantity: l.quantity, unit_cost: l.unit_cost }))
  } : blankForm()
  detailOpen.value = false
  await nextTick()
  formOpen.value = true
}

async function save() {
  formError.value = ''
  const f = form.value
  if (!f.title.trim()) {
    formError.value = t('procurement.titleRequired')
    return
  }
  const body = {
    title: f.title, justification: f.justification || null, specification: f.specification || null, site_id: f.site_id || null,
    supplier_id: f.supplier_id || null, vendor_name: f.vendor_name || null, currency: f.currency ? f.currency.trim().toUpperCase() : null,
    expected_delivery_date: formatLocalDate(f.expected_delivery_date),
    lines: f.lines.map(l => ({ asset_type_id: l.asset_type_id || null, manufacturer_id: l.manufacturer_id || null, model: l.model || null,
      description: l.description || null, quantity: l.quantity || 1, unit_cost: l.unit_cost ?? null }))
  }
  saving.value = true
  try {
    const res = editing.value ? await api.updatePurchaseOrder(editing.value.id, body) : await api.createPurchaseOrder(body)
    formOpen.value = false
    await load()
    // let the form dialog finish closing before the detail dialog opens
    await nextTick()
    setTimeout(() => showDetail(res.data), 250)
  } catch (err) {
    formError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

// --- detail ---
const detail = ref(null)
const detailOpen = ref(false)
const detailError = ref('')
const action = ref({ note: '', po_number: '' })
const busy = ref(false)
const canReceive = computed(() => canWrite('lifecycle') && detail.value && ['approved', 'ordered', 'received'].includes(detail.value.status))

function showDetail(data) {
  detail.value = data
  action.value = { note: '', po_number: data.po_number || '' }
  receiving.value = null
  detailError.value = ''
  detailOpen.value = true
}

async function openDetail(id) {
  try {
    showDetail((await api.getPurchaseOrder(id)).data)
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

async function move(target) {
  busy.value = true
  detailError.value = ''
  try {
    const res = await api.transitionPurchaseOrder(detail.value.id, { target, note: action.value.note || null, po_number: action.value.po_number || null })
    showDetail(res.data)
    await load()
  } catch (err) {
    detailError.value = apiErrorText(err, t)
  } finally {
    busy.value = false
  }
}

// --- receiving a delivery ---
const receiving = ref(null)
const canBook = computed(() => {
  const r = receiving.value
  if (!r || !r.assetId || !r.mismatches) return false
  return !r.mismatches.length || (r.accept && (r.note || '').trim().length >= 5)
})

function startReceive(line) {
  receiving.value = { line, assetId: null, mismatches: null, accept: false, note: '' }
}

async function checkReceive(assetId) {
  if (!receiving.value) return
  receiving.value.mismatches = null
  if (!assetId) return
  try {
    receiving.value.mismatches = (await api.checkDelivery(receiving.value.line.id, assetId)).data.mismatches
  } catch (err) {
    detailError.value = apiErrorText(err, t)
  }
}

async function book() {
  const r = receiving.value
  busy.value = true
  detailError.value = ''
  try {
    const res = await api.receiveDelivery(r.line.id, { asset_id: r.assetId, accept_mismatch: !!r.accept, note: r.note || null })
    showDetail(res.data.order)
    message.value = { severity: 'success', text: t('procurement.booked') }
    await load()
  } catch (err) {
    detailError.value = apiErrorText(err, t)
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.toolbar .spacer { flex: 1; }
.filter { min-width: 12rem; }
.rows :deep(tr) { cursor: pointer; }
.p-field label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
.lines-title { margin: 0.5rem 0; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--sk-text-muted, #6b7a71); }
.line-row { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; margin-bottom: 0.5rem; }
.l-type, .l-maker { flex: 1 1 9rem; min-width: 0; }
.l-model, .l-desc { flex: 1 1 9rem; min-width: 0; }
.l-qty { flex: 0 0 6rem; }
.l-cost { flex: 0 0 8rem; }
.l-qty :deep(input), .l-cost :deep(input) { width: 100%; }
.facts { display: flex; flex-wrap: wrap; gap: 0.5rem 1.25rem; align-items: center; margin-bottom: 0.75rem; font-size: 0.9rem; }
.block-text { margin: 0 0 0.5rem; font-size: 0.9rem; white-space: pre-wrap; }
.lines-table { width: 100%; border-collapse: collapse; margin: 0.75rem 0; font-size: 0.9rem; }
.lines-table th { text-align: left; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--sk-text-muted, #6b7a71); padding: 0.25rem 0.5rem; }
.lines-table td { padding: 0.35rem 0.5rem; border-top: 1px solid var(--sk-border, #e1e7e3); vertical-align: top; }
.sub-row td { border-top: none; padding-top: 0; }
.num { text-align: right; }
.asset-link { margin-right: 1rem; color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; }
.asset-link small { color: var(--sk-text-muted, #6b7a71); font-weight: 400; }
.receive-box { padding: 0.5rem 0; max-width: 36rem; }
.mismatch { margin-top: 0.5rem; color: #8a5300; }
.mismatch p { margin: 0 0 0.4rem; }
.ok { margin: 0.5rem 0 0; color: var(--sk-primary, #2f6f4f); }
.actions-box { border-top: 1px solid var(--sk-border, #e1e7e3); padding-top: 0.75rem; }
label.inline { display: inline; margin: 0; }
</style>
