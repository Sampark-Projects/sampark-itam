<!--
  - AssetDetailMaintenance.vue
  - Maintenance of one asset (planned and done, firmware upgrades and patches), its recurring plans,
  - the spare parts that fit it and its change requests.
-->
<template>
  <section class="dcard">
    <h3 class="dcard-title">
      <span class="dcard-icon"><i class="pi pi-wrench"></i></span>{{ t('changes.assetCard.title') }}
      <span v-if="overdueCount" class="dcard-count overdue-chip">{{ overdueCount }} {{ t('changes.maintenance.overdue') }}</span>
    </h3>
    <p v-if="error" class="p-error">{{ error }}</p>

    <table v-if="records.length" class="rec-table">
      <thead>
        <tr>
          <th>{{ t('changes.maintenance.task') }}</th>
          <th>{{ t('changes.maintenance.kind') }}</th>
          <th>{{ t('common.fields.status') }}</th>
          <th>{{ t('changes.maintenance.due') }} / {{ t('changes.maintenance.performedOn') }}</th>
          <th v-if="canWrite('maintenance')"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in records" :key="r.id">
          <td>
            {{ r.title }}
            <small v-if="r.from_version || r.to_version" class="muted block">{{ r.from_version || '?' }} → {{ r.to_version || '?' }}</small>
            <small v-if="r.change_request_id && changeCode(r.change_request_id)" class="muted block">{{ changeCode(r.change_request_id) }}</small>
            <small v-if="r.plan_id" class="muted block"><i class="pi pi-replay"></i> {{ t('changes.plans.fromPlan') }}</small>
            <small v-if="r.parts.length" class="muted block">{{ r.parts.map(p => `${p.quantity}× ${p.name}`).join(', ') }}</small>
          </td>
          <td>{{ t(`changes.maintenance.kinds.${r.kind}`) }}</td>
          <td>
            <Tag :value="r.status === 'done' ? t('changes.maintenance.done') : (r.overdue ? t('changes.maintenance.overdue') : t('changes.maintenance.planned'))" :severity="r.status === 'done' ? 'success' : (r.overdue ? 'danger' : 'info')" />
          </td>
          <td>{{ formatDate(r.status === 'done' ? r.performed_on : r.due_date) }}</td>
          <td v-if="canWrite('maintenance')" class="num">
            <Button v-if="r.status === 'planned'" icon="pi pi-check" text rounded size="small" :aria-label="t('changes.maintenance.complete')" @click="openComplete(r)" />
            <Button v-if="canDelete('maintenance')" icon="pi pi-trash" text rounded size="small" severity="danger" @click="remove(r)" />
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else class="muted">{{ t('changes.assetCard.empty') }}</p>

    <div v-if="canWrite('maintenance') && !asset.archived_at" class="add-row">
      <Dropdown v-model="form.kind" :options="kindOptions" optionLabel="label" optionValue="value" class="f-kind" />
      <InputText v-model="form.title" maxlength="150" :placeholder="t('changes.assetCard.taskTitle')" class="f-title" />
      <Calendar v-model="form.due_date" dateFormat="dd/mm/yy" showIcon :placeholder="t('changes.maintenance.due')" class="f-date" />
      <template v-if="isUpgrade">
        <InputText v-model="form.to_version" maxlength="100" :placeholder="t('changes.upgrade.toVersion')" class="f-ver" />
        <Dropdown v-model="form.change_request_id" :options="approvedChanges" optionLabel="label" optionValue="value" showClear
                  :placeholder="t('changes.upgrade.changeRequest')" class="f-cr" />
      </template>
      <Button :label="t('changes.assetCard.addTask')" icon="pi pi-plus" :loading="saving" @click="add" />
      <small v-if="isUpgrade" class="muted block w-full">{{ t('changes.upgrade.hint') }}</small>
    </div>

    <div class="sub">
      <h4>{{ t('changes.plans.title') }}</h4>
      <p v-if="!plans.length" class="muted">{{ t('changes.plans.none') }}</p>
      <ul v-else class="plain">
        <li v-for="p in plans" :key="p.id" :class="{ inactive: !p.is_active }">
          <strong>{{ p.title }}</strong>
          <span class="muted"> · {{ t('changes.plans.every', { n: p.interval_days }) }} · {{ t('changes.plans.nextDue', { date: formatDate(p.next_due_date) }) }}</span>
          <Tag v-if="!p.is_active" :value="t('changes.plans.paused')" severity="secondary" class="chip" />
          <span v-if="canWrite('maintenance')" class="plan-actions">
            <Button :icon="p.is_active ? 'pi pi-pause' : 'pi pi-play'" text rounded size="small"
                    :aria-label="p.is_active ? t('changes.plans.pause') : t('changes.plans.resume')"
                    v-tooltip.top="p.is_active ? t('changes.plans.pause') : t('changes.plans.resume')" @click="toggle(p)" />
            <Button v-if="canDelete('maintenance')" icon="pi pi-trash" text rounded size="small" severity="danger"
                    :aria-label="t('changes.plans.delete')" @click="removePlan(p)" />
          </span>
        </li>
      </ul>
      <div v-if="canWrite('maintenance') && !asset.archived_at" class="add-row">
        <InputText v-model="planForm.title" maxlength="150" :placeholder="t('changes.plans.planTitle')" class="f-title" />
        <InputNumber v-model="planForm.interval_days" :min="1" :max="3650" :useGrouping="false" suffix=" d"
                     :placeholder="t('changes.plans.interval')" class="f-int" />
        <Calendar v-model="planForm.next_due_date" dateFormat="dd/mm/yy" showIcon :placeholder="t('changes.plans.firstDue')" class="f-date" />
        <Button :label="t('changes.plans.add')" icon="pi pi-replay" :loading="savingPlan" @click="addPlan" />
        <small class="muted block w-full">{{ t('changes.plans.hint') }}</small>
      </div>
    </div>

    <div class="sub">
      <h4>{{ t('changes.assetCard.parts') }}</h4>
      <p v-if="!parts.length" class="muted">{{ t('changes.assetCard.noParts') }}</p>
      <ul v-else class="plain">
        <li v-for="p in parts" :key="p.id">
          {{ p.name }}<span v-if="p.part_number" class="muted"> · {{ p.part_number }}</span>
          <Tag :value="t('changes.assetCard.inStock', { n: p.quantity })" :severity="p.low_stock || p.quantity === 0 ? 'warning' : 'secondary'" class="chip" />
        </li>
      </ul>
    </div>

    <div class="sub">
      <h4>{{ t('changes.assetCard.changes') }}</h4>
      <p v-if="!changes.length" class="muted">{{ t('changes.assetCard.noChanges') }}</p>
      <ul v-else class="plain">
        <li v-for="c in changes" :key="c.id">
          <strong>{{ c.code }}</strong> {{ c.title }}
          <Tag :value="t(`changes.status.${c.status}`)" severity="secondary" class="chip" />
        </li>
      </ul>
    </div>

    <MaintenanceCompleteDialog v-model:visible="showComplete" :record="current" @done="onCompleted" />
  </section>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from 'primevue/button'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Calendar from 'primevue/calendar'
import Tag from 'primevue/tag'
import api from '@/api/api'
import MaintenanceCompleteDialog from '../changes/MaintenanceCompleteDialog.vue'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { formatLocalDate } from '../../../utils/localDate'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({
  asset: { type: Object, required: true }
})
const emit = defineEmits(['changed'])

const { t } = useI18n()
const { canWrite, canDelete, canRead } = usePermissions()
const { formatDate } = useDateFormatter()

const KINDS = ['preventive', 'corrective', 'inspection', 'upgrade', 'patch']
const records = ref([])
const plans = ref([])
const parts = ref([])
const changes = ref([])
const error = ref('')
const saving = ref(false)
const savingPlan = ref(false)
const showComplete = ref(false)
const current = ref(null)

const kindOptions = computed(() => KINDS.map(v => ({ value: v, label: t(`changes.maintenance.kinds.${v}`) })))
const emptyForm = (kind = 'preventive') => ({ kind, title: '', due_date: null, to_version: '', change_request_id: null })
const form = ref(emptyForm())
const planForm = ref({ title: '', interval_days: null, next_due_date: null })
const isUpgrade = computed(() => ['upgrade', 'patch'].includes(form.value.kind))
const overdueCount = computed(() => records.value.filter(r => r.overdue).length)
// an upgrade or patch is done under an approved change request that covers this asset
const approvedChanges = computed(() => changes.value
  .filter(c => ['approved', 'implemented'].includes(c.status))
  .map(c => ({ value: c.id, label: `${c.code} · ${c.title}` })))

function changeCode(id) {
  const c = changes.value.find(x => x.id === id)
  return c ? `${c.code} · ${c.title}` : ''
}

async function load() {
  error.value = ''
  const id = props.asset?.id
  if (!id) return
  try {
    const [m, pl, p, c] = await Promise.all([
      api.getAssetMaintenance(id), api.getMaintenancePlans(id), api.getSpareParts({ asset_id: id }),
      canRead('changes') ? api.getChangeRequests({ asset_id: id }) : Promise.resolve({ data: [] })
    ])
    records.value = Array.isArray(m.data) ? m.data : []
    plans.value = Array.isArray(pl.data) ? pl.data : []
    parts.value = Array.isArray(p.data) ? p.data : []
    changes.value = Array.isArray(c.data) ? c.data : []
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

async function add() {
  error.value = ''
  if (!form.value.title.trim() || !form.value.due_date) {
    error.value = t('changes.assetCard.required')
    return
  }
  saving.value = true
  try {
    const body = { kind: form.value.kind, title: form.value.title, due_date: formatLocalDate(form.value.due_date) }
    if (isUpgrade.value) {
      body.to_version = form.value.to_version || null
      body.change_request_id = form.value.change_request_id || null
    }
    await api.createMaintenanceTask(props.asset.id, body)
    form.value = emptyForm(form.value.kind)
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

async function addPlan() {
  error.value = ''
  const f = planForm.value
  if (!f.title.trim() || !f.interval_days || !f.next_due_date) {
    error.value = t('changes.plans.required')
    return
  }
  savingPlan.value = true
  try {
    await api.createMaintenancePlan(props.asset.id, {
      kind: 'preventive', title: f.title, interval_days: f.interval_days, lead_days: 14,
      next_due_date: formatLocalDate(f.next_due_date), is_active: true
    })
    planForm.value = { title: '', interval_days: null, next_due_date: null }
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    savingPlan.value = false
  }
}

async function toggle(plan) {
  try {
    await api.updateMaintenancePlan(plan.id, { ...plan, is_active: !plan.is_active })
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

async function removePlan(plan) {
  if (!window.confirm(t('changes.plans.deleteConfirm', { title: plan.title }))) return
  try {
    await api.deleteMaintenancePlan(plan.id)
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

function openComplete(record) {
  current.value = record
  showComplete.value = true
}

async function onCompleted() {
  await load()
  // an upgrade changes the asset's firmware version
  if (current.value?.kind === 'upgrade') emit('changed')
}

async function remove(record) {
  if (!window.confirm(t('changes.assetCard.delete'))) return
  try {
    await api.deleteMaintenanceRecord(record.id)
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

watch(() => props.asset?.id, load, { immediate: true })
</script>

<style scoped>
.muted { color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; margin: 0 0 0.5rem; }
.block { display: block; }
.w-full { width: 100%; }
.overdue-chip { margin-left: 0.5rem; }
.rec-table { width: 100%; border-collapse: collapse; margin-bottom: 0.75rem; font-size: 0.9rem; }
.rec-table th { text-align: left; font-size: 0.75rem; letter-spacing: 0.04em; text-transform: uppercase; color: var(--sk-text-muted, #6b7a71); padding: 0.25rem 0.5rem; }
.rec-table td { padding: 0.35rem 0.5rem; border-top: 1px solid var(--sk-border, #e1e7e3); vertical-align: top; }
.num { text-align: right; white-space: nowrap; }
.add-row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
.f-kind { flex: 0 0 10rem; }
.f-title { flex: 1 1 12rem; min-width: 0; }
.f-date { flex: 0 0 9rem; }
.f-ver { flex: 0 0 8rem; }
.f-cr { flex: 1 1 12rem; min-width: 0; }
.f-int { flex: 0 0 7rem; }
.sub { margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--sk-border, #e1e7e3); }
.sub h4 { margin: 0 0 0.4rem; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--sk-text-muted, #6b7a71); }
.plain { list-style: none; margin: 0 0 0.5rem; padding: 0; font-size: 0.9rem; }
.plain li { margin-bottom: 0.3rem; }
.plain li.inactive { opacity: 0.6; }
.plan-actions { margin-left: 0.25rem; }
.chip { margin-left: 0.5rem; font-size: 0.7rem; }
</style>
