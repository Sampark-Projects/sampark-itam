<template>
  <div>
    <p class="hint">{{ t('configmgmt.overview.hint') }}</p>
    <div class="toolbar">
      <div class="flex align-items-center gap-2">
        <label for="co_state">{{ t('configmgmt.overview.show') }}</label>
        <Dropdown id="co_state" v-model="state" :options="stateOptions" optionLabel="label" optionValue="value" @change="load" />
      </div>
      <Button v-if="canWrite('configurations')" :label="t('configmgmt.overview.runAlerts')" icon="pi pi-send" severity="secondary" outlined :loading="running" @click="runAlerts" />
    </div>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <DataTable :value="items" :loading="loading" size="small" paginator :rows="15" stripedRows>
      <template #empty>{{ t('configmgmt.overview.empty') }}</template>
      <Column field="asset_name" :header="t('configmgmt.overview.asset')" sortable>
        <template #body="{ data }">
          <router-link :to="`/assets/${data.asset_id}`" class="asset-link">{{ data.asset_name }}</router-link>
        </template>
      </Column>
      <Column field="name" :header="t('configmgmt.overview.item')" sortable>
        <template #body="{ data }">
          {{ data.name }} <small class="muted">· {{ t(`configmgmt.kinds.${data.kind}`) }}</small>
        </template>
      </Column>
      <Column :header="t('configmgmt.overview.latest')">
        <template #body="{ data }">
          <span v-if="data.latest">v{{ data.latest.version_number }}<span v-if="data.latest.label"> · {{ data.latest.label }}</span> · {{ formatDate(data.latest.uploaded_at) }}</span>
          <span v-else>-</span>
        </template>
      </Column>
      <Column :header="t('configmgmt.card.baseline')">
        <template #body="{ data }">
          <Tag :value="t(`configmgmt.baseline.${data.baseline_state}`)" :severity="baselineSeverity(data.baseline_state)" />
        </template>
      </Column>
      <Column :header="t('configmgmt.overview.backup')">
        <template #body="{ data }">
          <Tag :value="t(`configmgmt.backup.${data.backup_state}`)" :severity="backupSeverity(data.backup_state)" />
        </template>
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
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { apiErrorText } from '../../../utils/money'

const { t } = useI18n()
const { canWrite } = usePermissions()
const { formatDate } = useDateFormatter()

const state = ref('attention')
const stateOptions = computed(() => ['attention', 'drift', 'stale', 'all'].map(v => ({ value: v, label: t(`configmgmt.overview.${v}`) })))
const items = ref([])
const loading = ref(false)
const running = ref(false)
const message = ref(null)

const baselineSeverity = (s) => ({ matches: 'success', differs: 'danger', no_baseline: 'warning', no_versions: 'secondary' }[s] || 'info')
const backupSeverity = (s) => ({ ok: 'success', stale: 'danger', none: 'warning', unmanaged: 'secondary' }[s] || 'info')

async function load() {
  loading.value = true
  try {
    const res = await api.getConfigOverview({ state: state.value })
    items.value = res.data?.items || []
  } catch (err) {
    items.value = []
  } finally {
    loading.value = false
  }
}

async function runAlerts() {
  running.value = true
  try {
    const res = await api.runConfigAlerts()
    message.value = { severity: 'success', text: t('configmgmt.overview.runResult', { alerts: res.data?.alerts ?? 0 }) }
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    running.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
label { font-weight: 500; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.asset-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; }
.asset-link:hover { text-decoration: underline; }
</style>
