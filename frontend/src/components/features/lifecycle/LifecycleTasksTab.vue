<template>
  <div>
    <p class="hint">{{ t('workflows.tasks.hint') }}</p>
    <DataTable :value="items" :loading="loading" size="small" paginator :rows="15" stripedRows>
      <template #empty>{{ t('workflows.tasks.empty') }}</template>
      <Column field="asset_name" :header="t('workflows.tasks.asset')" sortable>
        <template #body="{ data }">
          <router-link :to="`/assets/${data.asset_id}`" class="asset-link">{{ data.asset_name }}</router-link>
          <small v-if="data.asset_tag" class="muted"> · {{ data.asset_tag }}</small>
        </template>
      </Column>
      <Column field="workflow_name" :header="t('workflows.tasks.workflow')" sortable>
        <template #body="{ data }">{{ t(`workflows.kinds.${data.kind}`) }}</template>
      </Column>
      <Column field="step_name" :header="t('workflows.tasks.step')">
        <template #body="{ data }">
          {{ data.step_name }}
          <Tag :value="t(`workflows.stepTypes.${data.step_type}`)" severity="secondary" />
        </template>
      </Column>
      <Column field="role_name" :header="t('workflows.tasks.role')">
        <template #body="{ data }">{{ data.role_name || '-' }}</template>
      </Column>
      <Column field="started_at" :header="t('workflows.tasks.since')" sortable>
        <template #body="{ data }">{{ formatDate(data.started_at) }}</template>
      </Column>
      <Column>
        <template #body="{ data }">
          <router-link :to="`/assets/${data.asset_id}`"><Button :label="t('workflows.tasks.open')" icon="pi pi-arrow-right" size="small" text /></router-link>
        </template>
      </Column>
    </DataTable>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import api from '@/api/api'
import { useDateFormatter } from '../../../composables/useDateFormatter'

const { t } = useI18n()
const { formatDate } = useDateFormatter()
const items = ref([])
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const res = await api.getWorkflowTasks()
    items.value = res.data?.items || []
  } catch (err) {
    items.value = []
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.asset-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; }
.asset-link:hover { text-decoration: underline; }
</style>
