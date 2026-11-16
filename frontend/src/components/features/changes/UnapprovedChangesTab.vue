<template>
  <div>
    <p class="hint">{{ t('changes.unapproved.hint') }}</p>
    <div class="toolbar">
      <div class="flex align-items-center gap-3 flex-wrap">
        <div class="flex align-items-center gap-2">
          <label for="un_days">{{ t('changes.unapproved.within') }}</label>
          <Dropdown id="un_days" v-model="days" :options="dayOptions" optionLabel="label" optionValue="value" @change="load" />
        </div>
        <div class="flex align-items-center gap-2">
          <InputSwitch v-model="includeReviewed" inputId="un_rev" @change="load" />
          <label for="un_rev">{{ t('changes.unapproved.showReviewed') }}</label>
        </div>
      </div>
    </div>

    <DataTable :value="items" :loading="loading" size="small" paginator :rows="15" stripedRows>
      <template #empty>{{ t('changes.unapproved.empty') }}</template>
      <Column field="timestamp" :header="t('changes.unapproved.when')" sortable>
        <template #body="{ data }">{{ formatDateTime(data.timestamp) }}</template>
      </Column>
      <Column field="asset_name" :header="t('changes.unapproved.asset')" sortable>
        <template #body="{ data }">
          <router-link :to="`/assets/${data.asset_id}`" class="asset-link">{{ data.asset_name || '-' }}</router-link>
        </template>
      </Column>
      <Column field="changed_by" :header="t('changes.unapproved.by')" sortable />
      <Column :header="t('changes.unapproved.changes')">
        <template #body="{ data }">
          <div v-for="c in data.changes" :key="c.field" class="change-line">
            <strong>{{ fieldLabel(c.field, t) }}:</strong> {{ show(c.old) }} → {{ show(c.new) }}
          </div>
          <small v-if="data.review_note" class="reviewed">
            {{ t('changes.unapproved.reviewedBy', { name: data.reviewed_by || '-' }) }}: “{{ data.review_note }}”
          </small>
        </template>
      </Column>
      <Column v-if="canWrite('changes')">
        <template #body="{ data }">
          <Button :label="t('changes.unapproved.review')" icon="pi pi-check-square" size="small" text @click="openReview(data)" />
        </template>
      </Column>
    </DataTable>

    <Dialog v-model:visible="showReview" :header="t('changes.unapproved.reviewTitle')" modal :style="{ width: '90vw', maxWidth: '32rem' }">
      <label for="un_note">{{ t('changes.unapproved.reviewNote') }}</label>
      <Textarea id="un_note" v-model="reviewNote" rows="3" autoResize class="w-full" />
      <small v-if="reviewError" class="p-error block">{{ reviewError }}</small>
      <template #footer>
        <Button :label="t('common.actions.cancel')" text @click="showReview = false" />
        <Button :label="t('common.actions.save')" :loading="saving" @click="saveReview" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dropdown from 'primevue/dropdown'
import InputSwitch from 'primevue/inputswitch'
import Dialog from 'primevue/dialog'
import Textarea from 'primevue/textarea'
import Button from 'primevue/button'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { apiErrorText } from '../../../utils/money'
import { fieldLabel } from '../../../utils/workflowFields'

const { t } = useI18n()
const { canWrite } = usePermissions()
const { formatDate } = useDateFormatter()

const days = ref(30)
const dayOptions = computed(() => [7, 30, 90, 180, 365].map(n => ({ value: n, label: t('changes.unapproved.days', { n }) })))
const includeReviewed = ref(false)
const items = ref([])
const loading = ref(false)

const formatDateTime = (value) => (value ? `${formatDate(value)} ${new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : '')
const show = (v) => (v === null || v === undefined || v === '' ? t('changes.unapproved.none') : (Array.isArray(v) ? v.join(', ') : String(v)))

async function load() {
  loading.value = true
  try {
    const res = await api.getUnapprovedChanges({ days: days.value, include_reviewed: includeReviewed.value })
    items.value = res.data?.items || []
  } catch (err) {
    items.value = []
  } finally {
    loading.value = false
  }
}

const showReview = ref(false)
const reviewing = ref(null)
const reviewNote = ref('')
const reviewError = ref('')
const saving = ref(false)

function openReview(item) {
  reviewing.value = item
  reviewNote.value = item.review_note || ''
  reviewError.value = ''
  showReview.value = true
}

async function saveReview() {
  reviewError.value = ''
  if (reviewNote.value.trim().length < 3) {
    reviewError.value = t('changes.request.noteRequired')
    return
  }
  saving.value = true
  try {
    await api.reviewUnapprovedChange(reviewing.value.audit_id, { note: reviewNote.value })
    showReview.value = false
    await load()
  } catch (err) {
    reviewError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
label { font-weight: 500; }
.change-line { font-size: 0.9rem; }
.reviewed { display: block; margin-top: 0.25rem; color: var(--sk-text-muted, #6b7a71); font-style: italic; }
.asset-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; }
.asset-link:hover { text-decoration: underline; }
</style>
