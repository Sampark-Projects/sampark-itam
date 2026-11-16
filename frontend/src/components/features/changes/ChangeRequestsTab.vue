<template>
  <div>
    <div class="toolbar">
      <Dropdown v-model="status" :options="statusOptions" optionLabel="label" optionValue="value" @change="load" />
      <Button v-if="canWrite('changes')" :label="t('changes.request.new')" icon="pi pi-plus" @click="openNew" />
    </div>

    <DataTable :value="items" :loading="loading" size="small" paginator :rows="15" stripedRows selectionMode="single" @row-click="openDetail($event.data)">
      <template #empty>{{ t('changes.request.empty') }}</template>
      <Column field="code" :header="t('changes.request.code')" sortable />
      <Column field="title" :header="t('changes.request.title')" sortable />
      <Column field="change_type" :header="t('changes.request.type')">
        <template #body="{ data }">{{ t(`changes.types.${data.change_type}`) }}</template>
      </Column>
      <Column field="risk" :header="t('changes.request.risk')">
        <template #body="{ data }">
          <Tag :value="t(`changes.risk.${data.risk}`)" :severity="data.risk === 'high' ? 'danger' : (data.risk === 'medium' ? 'warning' : 'info')" />
          <Tag v-if="data.urgency === 'emergency'" :value="t('changes.urgency.emergency')" severity="danger" class="ml-1" />
        </template>
      </Column>
      <Column :header="t('changes.request.assets')">
        <template #body="{ data }">{{ assetNames(data) }}</template>
      </Column>
      <Column field="status" :header="t('common.fields.status')" sortable>
        <template #body="{ data }"><Tag :value="t(`changes.status.${data.status}`)" :severity="statusSeverity(data.status)" /></template>
      </Column>
    </DataTable>

    <!-- create / edit -->
    <Dialog v-model:visible="showForm" :header="editingId ? t('changes.request.edit') : t('changes.request.new')" modal :style="{ width: '90vw', maxWidth: '40rem' }">
      <div class="grid">
        <div class="col-12">
          <label for="cr_title">{{ t('changes.request.title') }} *</label>
          <InputText id="cr_title" v-model="form.title" maxlength="150" class="w-full" />
        </div>
        <div class="col-12">
          <label for="cr_desc">{{ t('changes.request.description') }}</label>
          <Textarea id="cr_desc" v-model="form.description" rows="3" autoResize class="w-full" />
        </div>
        <div class="col-12">
          <label for="cr_reason">{{ t('changes.request.reason') }}</label>
          <Textarea id="cr_reason" v-model="form.reason" rows="2" autoResize class="w-full" />
        </div>
        <div class="col-6 md:col-3">
          <label>{{ t('changes.request.type') }}</label>
          <Dropdown v-model="form.change_type" :options="typeOptions" optionLabel="label" optionValue="value" class="w-full" />
        </div>
        <div class="col-6 md:col-3">
          <label>{{ t('changes.request.risk') }}</label>
          <Dropdown v-model="form.risk" :options="riskOptions" optionLabel="label" optionValue="value" class="w-full" />
        </div>
        <div class="col-12 md:col-6">
          <label>{{ t('changes.urgency.label') }}</label>
          <Dropdown v-model="form.urgency" :options="urgencyOptions" optionLabel="label" optionValue="value" class="w-full" />
          <small v-if="form.urgency === 'emergency'" class="muted">{{ t('changes.urgency.help') }}</small>
        </div>
        <div class="col-6 md:col-3">
          <label>{{ t('changes.request.plannedStart') }}</label>
          <Calendar v-model="form.planned_start" dateFormat="dd/mm/yy" showIcon class="w-full" />
        </div>
        <div class="col-6 md:col-3">
          <label>{{ t('changes.request.plannedEnd') }}</label>
          <Calendar v-model="form.planned_end" dateFormat="dd/mm/yy" showIcon class="w-full" />
        </div>
        <div class="col-12">
          <label>{{ t('changes.request.assets') }} *</label>
          <MultiSelect v-model="form.asset_ids" :options="assetOptions" optionLabel="label" optionValue="value" display="chip" filter class="w-full" />
        </div>
      </div>
      <small v-if="formError" class="p-error block">{{ formError }}</small>
      <template #footer>
        <Button :label="t('common.actions.cancel')" text @click="showForm = false" />
        <Button :label="t('common.actions.save')" :loading="saving" @click="save" />
      </template>
    </Dialog>

    <!-- detail and actions -->
    <Dialog v-model:visible="showDetail" :header="detail ? `${detail.code} · ${detail.title}` : ''" modal :style="{ width: '90vw', maxWidth: '40rem' }">
      <div v-if="detail">
        <div class="flex gap-2 flex-wrap mb-2">
          <Tag :value="t(`changes.status.${detail.status}`)" :severity="statusSeverity(detail.status)" />
          <Tag :value="t(`changes.types.${detail.change_type}`)" severity="secondary" />
          <Tag v-if="detail.urgency === 'emergency'" :value="t('changes.urgency.emergency')" severity="danger" />
          <Tag :value="t(`changes.risk.${detail.risk}`)" :severity="detail.risk === 'high' ? 'danger' : (detail.risk === 'medium' ? 'warning' : 'info')" />
        </div>
        <dl class="facts">
          <dt>{{ t('changes.request.requestedBy') }}</dt><dd>{{ detail.requested_by || '-' }}</dd>
          <dt v-if="detail.decided_by">{{ t('changes.request.decidedBy') }}</dt>
          <dd v-if="detail.decided_by">{{ detail.decided_by }} · {{ formatDate(detail.decided_at) }}<span v-if="detail.decision_note"> — “{{ detail.decision_note }}”</span></dd>
          <dt v-if="detail.approvals && detail.approvals.required > 1">{{ t('changes.request.approvals') }}</dt>
          <dd v-if="detail.approvals && detail.approvals.required > 1">{{ detail.approvals.given }} / {{ detail.approvals.required }}<span v-if="detail.approvals.by.length"> ({{ detail.approvals.by.join(', ') }})</span></dd>
          <dt v-if="detail.retro_decision">{{ t('changes.request.retro') }}</dt>
          <dd v-if="detail.retro_decision">{{ t(`changes.retro.${detail.retro_decision}`) }} · {{ formatDate(detail.retro_decided_at) }}</dd>
          <dt v-if="detail.review_outcome">{{ t('changes.review.title') }}</dt>
          <dd v-if="detail.review_outcome">{{ t(`changes.review.${detail.review_outcome}`) }}<span v-if="detail.review_note"> — “{{ detail.review_note }}”</span></dd>
          <dt>{{ t('changes.request.plannedStart') }}</dt><dd>{{ detail.planned_start ? formatDate(detail.planned_start) : '-' }}</dd>
          <dt>{{ t('changes.request.plannedEnd') }}</dt><dd>{{ detail.planned_end ? formatDate(detail.planned_end) : '-' }}</dd>
          <dt>{{ t('changes.request.assets') }}</dt>
          <dd><router-link v-for="a in detail.assets" :key="a.id" :to="`/assets/${a.id}`" class="asset-link">{{ a.name }}</router-link></dd>
        </dl>
        <p v-if="detail.description" class="text"><strong>{{ t('changes.request.description') }}:</strong> {{ detail.description }}</p>
        <p v-if="detail.reason" class="text"><strong>{{ t('changes.request.reason') }}:</strong> {{ detail.reason }}</p>
        <p v-if="detail.implementation_note" class="text"><strong>{{ t('changes.request.implementation') }}:</strong> {{ detail.implementation_note }}</p>
        <p v-if="detail.status === 'approved'" class="muted">{{ t('changes.request.approvedHint') }}</p>
        <p v-if="detail.self_decision_blocked && detail.status === 'submitted'" class="muted">{{ t('changes.request.selfApproval') }}</p>

        <div v-if="canWrite('changes') && (detail.allowed_targets.length || detail.can_retro_decide)" class="actions-box">
          <Textarea v-model="note" rows="2" autoResize class="w-full" :placeholder="t('changes.request.note')" />
          <div v-if="detail.allowed_targets.includes('closed')" class="mt-2">
            <label>{{ t('changes.review.title') }} *</label>
            <Dropdown v-model="reviewOutcome" :options="reviewOptions" optionLabel="label" optionValue="value" class="w-full" :placeholder="t('changes.review.choose')" />
            <small class="muted">{{ t('changes.review.help') }}</small>
          </div>
          <div class="flex gap-2 flex-wrap mt-2">
            <Button
              v-for="target in detail.allowed_targets" :key="target"
              :label="t(`changes.actions.${target}`)"
              :severity="target === 'rejected' || target === 'cancelled' ? 'danger' : 'primary'"
              :outlined="target === 'draft' || target === 'cancelled'"
              size="small" :loading="acting" @click="act(target)"
            />
            <Button v-if="detail.can_retro_decide" :label="t('changes.retro.approve')" size="small" :loading="acting" @click="retro('approved')" />
            <Button v-if="detail.can_retro_decide" :label="t('changes.retro.reject')" severity="danger" size="small" :loading="acting" @click="retro('rejected')" />
            <Button v-if="detail.status === 'draft'" :label="t('common.actions.edit')" icon="pi pi-pencil" size="small" text @click="openEdit(detail)" />
          </div>
        </div>
        <small v-if="detailError" class="p-error block mt-2">{{ detailError }}</small>
      </div>
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
import MultiSelect from 'primevue/multiselect'
import InputText from 'primevue/inputtext'
import Textarea from 'primevue/textarea'
import Calendar from 'primevue/calendar'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { parseLocalDate, formatLocalDate } from '../../../utils/localDate'
import { apiErrorText } from '../../../utils/money'

const { t } = useI18n()
const { canWrite } = usePermissions()
const { formatDate } = useDateFormatter()

const status = ref('open')
const statusOptions = computed(() => ['open', 'all', 'draft', 'submitted', 'approved', 'rejected', 'implemented', 'closed', 'cancelled'].map(v => ({ value: v, label: t(`changes.status.${v}`) })))
const typeOptions = computed(() => ['configuration', 'firmware', 'program', 'hardware', 'network', 'other'].map(v => ({ value: v, label: t(`changes.types.${v}`) })))
const urgencyOptions = computed(() => ['normal', 'emergency'].map(v => ({ value: v, label: t(`changes.urgency.${v}`) })))
const reviewOptions = computed(() => ['successful', 'partial', 'failed', 'rolled_back'].map(v => ({ value: v, label: t(`changes.review.${v}`) })))
const riskOptions = computed(() => ['low', 'medium', 'high'].map(v => ({ value: v, label: t(`changes.risk.${v}`) })))

const items = ref([])
const loading = ref(false)
const assets = ref([])
const assetOptions = computed(() => assets.value.map(a => ({ value: a.id, label: a.tag ? `${a.name} (${a.tag})` : a.name })))

const statusSeverity = (s) => ({ approved: 'success', implemented: 'success', closed: 'secondary', rejected: 'danger', cancelled: 'secondary', submitted: 'info', draft: 'warning' }[s] || 'info')
const assetNames = (cr) => { const n = cr.assets.map(a => a.name); return n.length > 2 ? `${n.slice(0, 2).join(', ')} +${n.length - 2}` : n.join(', ') }

async function load() {
  loading.value = true
  try {
    const params = status.value === 'all' ? {} : { status: status.value }
    const res = await api.getChangeRequests(params)
    items.value = Array.isArray(res.data) ? res.data : []
  } catch (err) {
    items.value = []
  } finally {
    loading.value = false
  }
}

async function loadAssets() {
  try {
    const res = await api.getAssets({ limit: 500 })
    assets.value = res.data && Array.isArray(res.data.data) ? res.data.data : []
  } catch (e) {
    assets.value = []
  }
}

// --- form ---
const showForm = ref(false)
const editingId = ref(null)
const saving = ref(false)
const formError = ref('')
const blank = () => ({ title: '', description: '', reason: '', change_type: 'configuration', risk: 'low', urgency: 'normal', planned_start: null, planned_end: null, asset_ids: [] })
const form = ref(blank())

function openNew() {
  editingId.value = null
  form.value = blank()
  formError.value = ''
  showForm.value = true
}

function openEdit(cr) {
  editingId.value = cr.id
  form.value = {
    title: cr.title, description: cr.description || '', reason: cr.reason || '', change_type: cr.change_type, risk: cr.risk, urgency: cr.urgency || 'normal',
    planned_start: parseLocalDate(cr.planned_start), planned_end: parseLocalDate(cr.planned_end), asset_ids: cr.assets.map(a => a.id)
  }
  formError.value = ''
  showDetail.value = false
  showForm.value = true
}

async function save() {
  formError.value = ''
  const f = form.value
  if (!f.title.trim() || !f.asset_ids.length) {
    formError.value = t('changes.request.required')
    return
  }
  saving.value = true
  try {
    const payload = {
      ...f, description: f.description || null, reason: f.reason || null,
      planned_start: formatLocalDate(f.planned_start), planned_end: formatLocalDate(f.planned_end)
    }
    if (editingId.value) await api.updateChangeRequest(editingId.value, payload)
    else await api.createChangeRequest(payload)
    showForm.value = false
    await load()
  } catch (err) {
    formError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

// --- detail ---
const showDetail = ref(false)
const detail = ref(null)
const note = ref('')
const acting = ref(false)
const detailError = ref('')
const reviewOutcome = ref(null)

function openDetail(cr) {
  detail.value = cr
  note.value = ''
  reviewOutcome.value = null
  detailError.value = ''
  showDetail.value = true
}

async function act(target) {
  detailError.value = ''
  if ((target === 'rejected') && !note.value.trim()) {
    detailError.value = t('changes.request.noteRequired')
    return
  }
  if (target === 'closed' && !reviewOutcome.value) {
    detailError.value = t('changes.review.required')
    return
  }
  acting.value = true
  try {
    const res = await api.transitionChangeRequest(detail.value.id, {
      target, note: note.value || null, review_outcome: target === 'closed' ? reviewOutcome.value : null
    })
    detail.value = res.data
    note.value = ''
    await load()
  } catch (err) {
    detailError.value = apiErrorText(err, t)
  } finally {
    acting.value = false
  }
}

async function retro(decision) {
  detailError.value = ''
  if (decision === 'rejected' && !note.value.trim()) {
    detailError.value = t('changes.request.noteRequired')
    return
  }
  acting.value = true
  try {
    const res = await api.retroDecideChangeRequest(detail.value.id, { decision, note: note.value || null })
    detail.value = res.data
    note.value = ''
    await load()
  } catch (err) {
    detailError.value = apiErrorText(err, t)
  } finally {
    acting.value = false
  }
}

onMounted(() => {
  load()
  loadAssets()
})
</script>

<style scoped>
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
.facts { display: grid; grid-template-columns: 10rem 1fr; gap: 0.35rem 1rem; margin: 0 0 0.75rem; }
.facts dt { color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.facts dd { margin: 0; }
.text { margin: 0 0 0.5rem; white-space: pre-wrap; }
.muted { color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.actions-box { margin-top: 1rem; padding: 0.75rem; border-radius: 8px; background: #f4f8f5; }
.asset-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; margin-right: 0.75rem; }
.asset-link:hover { text-decoration: underline; }
</style>
