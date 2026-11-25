<!--
  - MaintenanceCompleteDialog.vue
  - Completes a planned maintenance task: when, by whom, cost, spare parts used, next due date.
  - Shared by the Maintenance tab and the asset page.
-->
<template>
  <Dialog :visible="visible" @update:visible="emit('update:visible', $event)" :header="t('changes.maintenance.completeTitle')" modal :style="{ width: '90vw', maxWidth: '38rem' }">
    <p v-if="record" class="muted"><strong>{{ record.title }}</strong> · {{ t(`changes.maintenance.kinds.${record.kind}`) }}</p>
    <div class="grid">
      <div class="col-12 md:col-6">
        <label for="mc_date">{{ t('changes.maintenance.performedOn') }} *</label>
        <Calendar id="mc_date" v-model="form.performed_on" dateFormat="dd/mm/yy" showIcon class="w-full" :maxDate="maxDate" />
      </div>
      <div class="col-12 md:col-6">
        <label for="mc_by">{{ t('changes.maintenance.performedBy') }}</label>
        <InputText id="mc_by" v-model="form.performed_by" maxlength="255" class="w-full" />
      </div>
      <div class="col-12 md:col-6">
        <label for="mc_vendor">{{ t('changes.maintenance.vendor') }}</label>
        <InputText id="mc_vendor" v-model="form.vendor" maxlength="255" class="w-full" />
      </div>
      <div class="col-6 md:col-3">
        <label for="mc_cost">{{ t('changes.maintenance.cost') }}</label>
        <InputNumber id="mc_cost" v-model="form.cost_amount" :min="0" :maxFractionDigits="2" class="w-full" />
      </div>
      <div class="col-6 md:col-3">
        <label for="mc_cur">{{ t('changes.maintenance.currency') }}</label>
        <InputText id="mc_cur" v-model="form.cost_currency" maxlength="3" class="w-full currency" />
      </div>
      <div class="col-12">
        <label for="mc_notes">{{ t('changes.maintenance.notes') }}</label>
        <Textarea id="mc_notes" v-model="form.notes" rows="2" autoResize class="w-full" />
      </div>
      <div class="col-12">
        <label>{{ t('changes.maintenance.parts') }}</label>
        <div v-for="(p, i) in form.parts" :key="i" class="part-row">
          <Dropdown v-model="p.spare_part_id" :options="partOptions" optionLabel="label" optionValue="value" filter class="part-select" />
          <InputNumber v-model="p.quantity" :min="1" showButtons class="part-qty" />
          <Button icon="pi pi-trash" text rounded severity="danger" size="small" @click="form.parts.splice(i, 1)" />
        </div>
        <Button :label="t('changes.maintenance.addPart')" icon="pi pi-plus" text size="small" :disabled="!partOptions.length" @click="form.parts.push({ spare_part_id: null, quantity: 1 })" />
      </div>
      <div v-if="record && ['upgrade', 'patch'].includes(record.kind)" class="col-12 md:col-6">
        <label for="mc_ver">{{ t('changes.upgrade.installedVersion') }}</label>
        <InputText id="mc_ver" v-model="form.to_version" maxlength="100" class="w-full" />
        <small class="muted">{{ t('changes.upgrade.completeHint') }}</small>
      </div>
      <div v-if="record && record.kind === 'preventive' && !record.plan_id" class="col-12 md:col-6">
        <label for="mc_next">{{ t('changes.maintenance.nextDue') }}</label>
        <Calendar id="mc_next" v-model="form.next_due_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
      </div>
    </div>
    <small v-if="error" class="p-error block">{{ error }}</small>
    <template #footer>
      <Button :label="t('common.actions.cancel')" text @click="emit('update:visible', false)" />
      <Button :label="t('changes.maintenance.complete')" icon="pi pi-check" :loading="saving" @click="save" />
    </template>
  </Dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import Calendar from 'primevue/calendar'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Textarea from 'primevue/textarea'
import Dropdown from 'primevue/dropdown'
import Button from 'primevue/button'
import api from '@/api/api'
import { formatLocalDate } from '../../../utils/localDate'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({
  visible: { type: Boolean, default: false },
  record: { type: Object, default: null }
})
const emit = defineEmits(['update:visible', 'done'])

const { t } = useI18n()
const blank = () => ({ performed_on: new Date(), performed_by: '', vendor: '', notes: '', cost_amount: null, cost_currency: '', parts: [], next_due_date: null })
const form = ref(blank())
const parts = ref([])
const saving = ref(false)
const error = ref('')
const maxDate = new Date()

const partOptions = computed(() => parts.value.map(p => ({ value: p.id, label: `${p.name}${p.part_number ? ' (' + p.part_number + ')' : ''} · ${t('changes.assetCard.inStock', { n: p.quantity })}` })))

watch(() => props.visible, async (open) => {
  if (!open) return
  form.value = { ...blank(), to_version: props.record?.to_version || '' }
  error.value = ''
  try {
    const res = await api.getSpareParts()
    parts.value = Array.isArray(res.data) ? res.data : []
  } catch (e) {
    parts.value = []
  }
})

async function save() {
  error.value = ''
  const f = form.value
  if (!f.performed_on) {
    error.value = t('changes.maintenance.required')
    return
  }
  saving.value = true
  try {
    await api.completeMaintenanceTask(props.record.id, {
      performed_on: formatLocalDate(f.performed_on),
      performed_by: f.performed_by || null,
      vendor: f.vendor || null,
      notes: f.notes || null,
      cost_amount: f.cost_amount || null,
      cost_currency: f.cost_currency ? f.cost_currency.trim().toUpperCase() : null,
      parts: f.parts.filter(p => p.spare_part_id).map(p => ({ spare_part_id: p.spare_part_id, quantity: p.quantity || 1 })),
      next_due_date: formatLocalDate(f.next_due_date),
      to_version: f.to_version ? f.to_version.trim() : null
    })
    emit('update:visible', false)
    emit('done')
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
.muted { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); }
.currency { text-transform: uppercase; }
.part-row { display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.4rem; }
.part-select { flex: 1; min-width: 0; }
.part-qty { flex: 0 0 8rem; }
</style>
