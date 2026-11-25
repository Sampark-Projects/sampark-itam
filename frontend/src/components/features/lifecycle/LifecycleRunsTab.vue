<template>
  <div>
    <div class="toolbar">
      <Dropdown v-model="status" :options="statusOptions" optionLabel="label" optionValue="value" @change="load" />
    </div>
    <DataTable :value="rows" :loading="loading" size="small" paginator :rows="15" stripedRows>
      <template #empty>{{ t('workflows.runs.empty') }}</template>
      <Column field="asset_name" :header="t('workflows.runs.asset')" sortable>
        <template #body="{ data }">
          <router-link :to="`/assets/${data.asset_id}`" class="asset-link">{{ data.asset_name }}</router-link>
          <small v-if="data.asset_tag" class="muted"> · {{ data.asset_tag }}</small>
        </template>
      </Column>
      <Column field="kind" :header="t('workflows.runs.workflow')" sortable>
        <template #body="{ data }">{{ t(`workflows.kinds.${data.kind}`) }}</template>
      </Column>
      <Column :header="t('workflows.runs.current')">
        <template #body="{ data }">{{ data.current_step || (data.status === 'completed' ? t('workflows.runs.finishedAll') : '-') }}</template>
      </Column>
      <Column field="status" :header="t('workflows.runs.status')" sortable>
        <template #body="{ data }">
          <Tag :value="t(`workflows.states.${data.status}`)" :severity="data.status === 'completed' ? 'success' : (data.status === 'rejected' ? 'danger' : (data.status === 'in_progress' ? 'info' : 'secondary'))" />
        </template>
      </Column>
      <Column field="started_at" :header="t('workflows.runs.started')" sortable>
        <template #body="{ data }">{{ formatDate(data.started_at) }}</template>
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
import Tag from 'primevue/tag'
import api from '@/api/api'
import { useDateFormatter } from '../../../composables/useDateFormatter'

const { t } = useI18n()
const { formatDate } = useDateFormatter()

const status = ref('in_progress')
const statusOptions = computed(() => ['in_progress', 'completed', 'rejected', 'cancelled', 'all'].map(v => ({ value: v, label: t(`workflows.states.${v}`) })))
const runs = ref([])
const loading = ref(false)

const rows = computed(() => runs.value.map(r => {
  const current = r.steps.find(s => s.is_current)
  return { ...r, current_step: current ? current.name : null }
}))

async function load() {
  loading.value = true
  try {
    const res = await api.getWorkflowRuns({ status: status.value })
    runs.value = Array.isArray(res.data) ? res.data : []
  } catch (err) {
    runs.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.toolbar { margin-bottom: 0.75rem; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.asset-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; }
.asset-link:hover { text-decoration: underline; }
</style>
