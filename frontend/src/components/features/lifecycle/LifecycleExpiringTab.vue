<template>
  <div>
    <div class="toolbar">
      <div class="flex align-items-center gap-2">
        <label for="exp_days">{{ t('lifecycle.expiring.within') }}</label>
        <Dropdown id="exp_days" v-model="days" :options="dayOptions" optionLabel="label" optionValue="value" @change="load" />
      </div>
      <Button
        v-if="canWrite('lifecycle')"
        :label="t('lifecycle.expiring.runNow')"
        icon="pi pi-send"
        severity="secondary"
        outlined
        :loading="running"
        @click="runNow"
      />
    </div>
    <p class="hint">{{ t('lifecycle.expiring.hint') }}</p>
    <Message v-if="runMessage" :severity="runMessage.severity" :closable="true" @close="runMessage = null">{{ runMessage.text }}</Message>

    <DataTable :value="items" :loading="loading" size="small" paginator :rows="15" stripedRows>
      <template #empty>{{ t('lifecycle.expiring.empty') }}</template>
      <Column field="name" :header="t('lifecycle.obsolescence.assets')" sortable>
        <template #body="{ data }">
          <router-link :to="`/assets/${data.asset_id}`" class="asset-link">{{ data.name }}</router-link>
          <small v-if="data.tag" class="muted"> · {{ data.tag }}</small>
        </template>
      </Column>
      <Column field="site" :header="t('lifecycle.obsolescence.site')" sortable />
      <Column field="type" :header="t('lifecycle.expiring.type')" sortable>
        <template #body="{ data }">{{ t(`lifecycle.types.${data.type}`) }}</template>
      </Column>
      <Column field="expiry_date" :header="t('lifecycle.expiring.expiryDate')" sortable>
        <template #body="{ data }">{{ formatDate(data.expiry_date) }}</template>
      </Column>
      <Column field="days_left" :header="t('lifecycle.expiring.daysLeft')" sortable>
        <template #body="{ data }">
          <Tag :value="data.state === 'expired' ? t('lifecycle.states.expired') : String(data.days_left)" :severity="data.state === 'expired' ? 'danger' : (data.days_left <= 30 ? 'warning' : 'info')" />
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

const days = ref(90)
const dayOptions = [30, 60, 90, 180, 365].map(n => ({ value: n, label: t('lifecycle.expiring.days', { n }) }))
const items = ref([])
const loading = ref(false)
const running = ref(false)
const runMessage = ref(null)

async function load() {
  loading.value = true
  try {
    const res = await api.getLifecycleExpiring({ days: days.value })
    items.value = res.data?.items || []
  } catch (err) {
    runMessage.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    loading.value = false
  }
}

async function runNow() {
  running.value = true
  try {
    const res = await api.runLifecycleAlerts()
    const r = res.data || {}
    runMessage.value = r.skipped_disabled
      ? { severity: 'warn', text: t('lifecycle.expiring.runDisabled') }
      : { severity: 'success', text: t('lifecycle.expiring.runResult', { alerts: r.alerts, emails: r.emails, noRecipients: r.no_recipients }) }
  } catch (err) {
    runMessage.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    running.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.asset-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; }
.asset-link:hover { text-decoration: underline; }
</style>
