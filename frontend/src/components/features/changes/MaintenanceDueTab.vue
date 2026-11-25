<template>
  <div>
    <p class="hint">{{ t('changes.maintenance.hint') }}</p>
    <div class="toolbar">
      <div class="flex align-items-center gap-2">
        <label for="md_days">{{ t('changes.maintenance.within') }}</label>
        <Dropdown id="md_days" v-model="days" :options="dayOptions" optionLabel="label" optionValue="value" @change="load" />
      </div>
    </div>

    <DataTable :value="items" :loading="loading" size="small" paginator :rows="15" stripedRows>
      <template #empty>{{ t('changes.maintenance.empty') }}</template>
      <Column field="asset_name" :header="t('changes.maintenance.asset')" sortable>
        <template #body="{ data }">
          <router-link :to="`/assets/${data.asset_id}`" class="asset-link">{{ data.asset_name }}</router-link>
        </template>
      </Column>
      <Column field="title" :header="t('changes.maintenance.task')" sortable />
      <Column field="kind" :header="t('changes.maintenance.kind')">
        <template #body="{ data }">{{ t(`changes.maintenance.kinds.${data.kind}`) }}</template>
      </Column>
      <Column field="due_date" :header="t('changes.maintenance.due')" sortable>
        <template #body="{ data }">
          {{ formatDate(data.due_date) }}
          <Tag v-if="data.overdue" :value="t('changes.maintenance.overdue')" severity="danger" />
        </template>
      </Column>
      <Column v-if="canWrite('maintenance')">
        <template #body="{ data }">
          <Button :label="t('changes.maintenance.complete')" icon="pi pi-check" size="small" text @click="openComplete(data)" />
        </template>
      </Column>
    </DataTable>

    <MaintenanceCompleteDialog v-model:visible="showComplete" :record="current" @done="load" />
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
import MaintenanceCompleteDialog from './MaintenanceCompleteDialog.vue'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'

const { t } = useI18n()
const { canWrite } = usePermissions()
const { formatDate } = useDateFormatter()

const days = ref(30)
const dayOptions = computed(() => [7, 30, 90, 180, 365].map(n => ({ value: n, label: t('lifecycle.expiring.days', { n }) })))
const items = ref([])
const loading = ref(false)
const showComplete = ref(false)
const current = ref(null)

async function load() {
  loading.value = true
  try {
    const res = await api.getMaintenanceDue({ days: days.value })
    items.value = res.data?.items || []
  } catch (err) {
    items.value = []
  } finally {
    loading.value = false
  }
}

function openComplete(record) {
  current.value = record
  showComplete.value = true
}

onMounted(load)
</script>

<style scoped>
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.toolbar { display: flex; align-items: center; gap: 1rem; margin-bottom: 0.75rem; }
label { font-weight: 500; }
.asset-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; }
.asset-link:hover { text-decoration: underline; }
</style>
