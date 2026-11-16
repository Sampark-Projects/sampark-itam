<template>
  <div class="hooks-tab">
    <p class="hint">{{ t('reports.integrations.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div class="bar">
      <Button v-if="editable" :label="t('reports.integrations.add')" icon="pi pi-plus" @click="openForm(null)" />
    </div>

    <DataTable :value="endpoints" :loading="loading" dataKey="id">
      <template #empty>{{ t('reports.integrations.empty') }}</template>
      <Column field="name" :header="t('reports.integrations.name')" style="min-width: 10rem" />
      <Column field="url" :header="t('reports.integrations.url')" style="min-width: 14rem">
        <template #body="{ data }"><span class="url">{{ data.url }}</span></template>
      </Column>
      <Column :header="t('reports.integrations.events')" style="min-width: 12rem">
        <template #body="{ data }">
          <div class="chips">
            <Tag v-for="e in data.events" :key="e" :value="eventLabel(e)" severity="secondary" />
          </div>
        </template>
      </Column>
      <Column :header="t('reports.integrations.active')" style="min-width: 8rem">
        <template #body="{ data }">
          <Tag :value="data.is_active ? t('reports.integrations.active') : '-'" :severity="data.is_active ? 'success' : 'secondary'" />
          <small v-if="data.disabled_reason" class="err" :title="data.disabled_reason">{{ t('reports.integrations.disabledTitle') }}</small>
          <small v-else-if="data.consecutive_failures" class="err">{{ t('reports.integrations.failures', { n: data.consecutive_failures }) }}</small>
          <small v-if="data.previous_secret_expires_at" class="when">{{ t('reports.integrations.graceUntil', { when: when(data.previous_secret_expires_at) }) }}</small>
        </template>
      </Column>
      <Column :header="t('reports.integrations.lastDelivery')" style="min-width: 11rem">
        <template #body="{ data }">
          <span v-if="!data.last_delivery">{{ t('reports.integrations.never') }}</span>
          <span v-else>
            <Tag :value="statusLabel(data.last_delivery.status)" :severity="statusSeverity(data.last_delivery.status)" />
            <small class="when">{{ when(data.last_delivery.at) }}</small>
          </span>
        </template>
      </Column>
      <Column v-if="editable" style="width: 13rem">
        <template #body="{ data }">
          <div class="actions">
            <Button icon="pi pi-send" text rounded size="small" :aria-label="t('reports.integrations.test')" v-tooltip.top="t('reports.integrations.test')" :loading="testing === data.id" @click="test(data)" />
            <Button icon="pi pi-key" text rounded size="small" :aria-label="t('reports.integrations.rotate')" v-tooltip.top="t('reports.integrations.rotate')" @click="rotate(data)" />
            <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('reports.integrations.edit')" v-tooltip.top="t('reports.integrations.edit')" @click="openForm(data)" />
            <Button icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('reports.integrations.delete')" v-tooltip.top="t('reports.integrations.delete')" @click="remove(data)" />
          </div>
        </template>
      </Column>
    </DataTable>

    <h3 class="section">{{ t('reports.integrations.deliveries') }}</h3>
    <div class="bar">
      <Dropdown v-model="deliveryFilter" :options="filterOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('reports.integrations.allEndpoints')" class="filter" @change="loadDeliveries" />
      <Button icon="pi pi-refresh" text rounded severity="secondary" :aria-label="t('reports.dashboard.refresh')" @click="loadDeliveries" />
    </div>
    <DataTable :value="deliveries" :loading="deliveriesLoading" dataKey="id" size="small">
      <template #empty>{{ t('reports.integrations.noDeliveries') }}</template>
      <Column :header="t('reports.integrations.event')" style="min-width: 10rem">
        <template #body="{ data }">{{ eventLabel(data.event) }}</template>
      </Column>
      <Column :header="t('reports.integrations.status')" style="width: 8rem">
        <template #body="{ data }"><Tag :value="statusLabel(data.status)" :severity="statusSeverity(data.status)" /></template>
      </Column>
      <Column field="attempts" :header="t('reports.integrations.attempts')" style="width: 6rem" />
      <Column :header="t('reports.integrations.response')" style="min-width: 10rem">
        <template #body="{ data }">
          <span v-if="data.response_code">HTTP {{ data.response_code }}</span>
          <span v-else-if="data.error" class="err">{{ data.error }}</span>
        </template>
      </Column>
      <Column :header="t('reports.integrations.when')" style="min-width: 10rem">
        <template #body="{ data }">{{ when(data.delivered_at || data.created_at) }}</template>
      </Column>
      <Column :header="t('reports.integrations.nextTry')" style="min-width: 10rem">
        <template #body="{ data }">{{ data.status === 'pending' && data.next_attempt_at ? when(data.next_attempt_at) : '' }}</template>
      </Column>
      <Column v-if="editable" style="width: 5rem">
        <template #body="{ data }">
          <Button v-if="data.status === 'failed'" icon="pi pi-replay" text rounded size="small" :aria-label="t('reports.integrations.redeliver')" v-tooltip.top="t('reports.integrations.redeliver')" @click="redeliver(data)" />
        </template>
      </Column>
    </DataTable>

    <h3 class="section">{{ t('reports.integrations.verifyTitle') }}</h3>
    <p class="note">{{ t('reports.integrations.verify') }}</p>
    <p class="note">{{ t('reports.integrations.apiKeysNote') }}</p>

    <Dialog v-model:visible="formOpen" modal :header="editing ? t('reports.integrations.edit') : t('reports.integrations.add')" :style="{ width: '36rem', maxWidth: '95vw' }">
      <Message v-if="formError" severity="error" :closable="false">{{ formError }}</Message>
      <div class="p-field">
        <label for="wh_name">{{ t('reports.integrations.name') }}</label>
        <InputText id="wh_name" v-model="form.name" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label for="wh_url">{{ t('reports.integrations.url') }}</label>
        <InputText id="wh_url" v-model="form.url" maxlength="500" class="w-full" placeholder="https://" />
        <small class="hint">{{ t('reports.integrations.urlHelp') }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('reports.integrations.events') }}</label>
        <MultiSelect v-model="form.events" :options="eventOptions" optionLabel="label" optionValue="value" display="chip" filter class="w-full"
                       @show="eventsOpen = true" @hide="eventsOpen = false"
                       @keydown.capture="escWasOpen = $event.key === 'Escape' && eventsOpen"
                       @keydown="escWasOpen && $event.stopPropagation()" />
      </div>
      <div class="flex align-items-center gap-2 mb-3">
        <InputSwitch v-model="form.is_active" inputId="wh_active" />
        <label for="wh_active" class="inline">{{ t('reports.integrations.active') }}</label>
      </div>
      <template #footer>
        <Button :label="t('common.actions.cancel')" severity="secondary" text @click="formOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" :disabled="!formValid" @click="save" />
      </template>
    </Dialog>

    <Dialog v-model:visible="secretOpen" modal :header="t('reports.integrations.secretTitle')" :style="{ width: '34rem', maxWidth: '95vw' }">
      <p class="hint">{{ t('reports.integrations.secretHint') }}</p>
      <div class="secret-row">
        <InputText :modelValue="secret" readonly class="w-full secret" @focus="$event.target.select()" />
        <Button :label="t('reports.integrations.copy')" icon="pi pi-copy" @click="copySecret" />
      </div>
      <small v-if="copied" class="hint">{{ t('reports.integrations.copied') }}</small>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dropdown from 'primevue/dropdown'
import MultiSelect from 'primevue/multiselect'
import InputText from 'primevue/inputtext'
import InputSwitch from 'primevue/inputswitch'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'

const { t } = useI18n()
const { canWrite } = usePermissions()
const editable = computed(() => canWrite('api_keys'))

const endpoints = ref([])
const deliveries = ref([])
const events = ref([])
const loading = ref(false)
const message = ref(null)
const testing = ref(null)
const deliveryFilter = ref(null)

function eventLabel(e) {
  const key = `reports.events.${e}`
  const text = t(key)
  return text === key ? e : text
}
function statusLabel(s) {
  const key = `reports.integrations.deliveryStatus.${s}`
  const text = t(key)
  return text === key ? s : text
}
function statusSeverity(s) {
  return s === 'success' ? 'success' : s === 'failed' ? 'danger' : 'warning'
}
// the API sends naive UTC timestamps
function when(value) {
  if (!value) return ''
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : value + 'Z'
  return new Date(iso).toLocaleString()
}

const eventOptions = computed(() => events.value.map(e => ({ value: e, label: eventLabel(e) })))
const filterOptions = computed(() => endpoints.value.map(e => ({ value: e.id, label: e.name })))

async function loadEndpoints() {
  loading.value = true
  try {
    const [list, ev] = await Promise.all([api.getWebhooks(), api.getWebhookEvents()])
    endpoints.value = list.data
    events.value = ev.data.events || []
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    loading.value = false
  }
}

const deliveriesLoading = ref(false)
async function loadDeliveries() {
  deliveriesLoading.value = true
  try {
    const params = { limit: 50 }
    if (deliveryFilter.value) params.endpoint_id = deliveryFilter.value
    deliveries.value = (await api.getWebhookDeliveries(params)).data
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    deliveriesLoading.value = false
  }
}

// --- add / edit ---
const formOpen = ref(false)
const eventsOpen = ref(false)
let escWasOpen = false
const editing = ref(null)
const form = ref({ name: '', url: '', events: [], is_active: true })
const formError = ref('')
const saving = ref(false)
const formValid = computed(() => form.value.name.trim() && form.value.url.trim() && form.value.events.length)

function openForm(endpoint) {
  editing.value = endpoint
  formError.value = ''
  form.value = endpoint
    ? { name: endpoint.name, url: endpoint.url, events: [...endpoint.events], is_active: endpoint.is_active }
    : { name: '', url: '', events: [], is_active: true }
  formOpen.value = true
}

// shown once after creating a webhook or rotating its secret
const secretOpen = ref(false)
const secret = ref('')
const copied = ref(false)

async function save() {
  formError.value = ''
  saving.value = true
  try {
    const body = { ...form.value, name: form.value.name.trim(), url: form.value.url.trim() }
    if (editing.value) {
      await api.updateWebhook(editing.value.id, body)
    } else {
      const res = await api.createWebhook(body)
      secret.value = res.data.secret
      copied.value = false
      secretOpen.value = true
    }
    formOpen.value = false
    message.value = { severity: 'success', text: t('reports.integrations.saved') }
    await loadEndpoints()
  } catch (err) {
    formError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

async function copySecret() {
  try {
    await navigator.clipboard.writeText(secret.value)
    copied.value = true
  } catch (err) {
    copied.value = false
  }
}

async function rotate(endpoint) {
  if (!window.confirm(t('reports.integrations.rotateConfirm', { name: endpoint.name }))) return
  try {
    secret.value = (await api.rotateWebhookSecret(endpoint.id)).data.secret
    copied.value = false
    secretOpen.value = true
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

async function redeliver(delivery) {
  try {
    const res = await api.redeliverWebhook(delivery.id)
    message.value = { severity: res.data.status === 'success' ? 'success' : 'warn', text: t('reports.integrations.redelivered', { status: statusLabel(res.data.status) }) }
    await Promise.all([loadEndpoints(), loadDeliveries()])
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

async function remove(endpoint) {
  if (!window.confirm(t('reports.integrations.deleteConfirm', { name: endpoint.name }))) return
  try {
    await api.deleteWebhook(endpoint.id)
    message.value = { severity: 'success', text: t('reports.integrations.deleted') }
    if (deliveryFilter.value === endpoint.id) deliveryFilter.value = null
    await loadEndpoints()
    await loadDeliveries()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

async function test(endpoint) {
  testing.value = endpoint.id
  message.value = null
  try {
    const res = await api.testWebhook(endpoint.id)
    message.value = res.data.status === 'success'
      ? { severity: 'success', text: t('reports.integrations.testOk', { code: res.data.response_code }) }
      : { severity: 'warn', text: t('reports.integrations.testFailed', { error: res.data.error || (res.data.response_code ? `HTTP ${res.data.response_code}` : '') }) }
    await Promise.all([loadEndpoints(), loadDeliveries()])
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    testing.value = null
  }
}

onMounted(async () => {
  await loadEndpoints()
  await loadDeliveries()
})
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; display: block; }
small.hint { margin: 0.25rem 0 0; font-size: 0.8rem; }
.bar { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; }
.section { margin: 1.75rem 0 0.75rem; }
.filter { min-width: 14rem; }
.note { color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; max-width: 60rem; }
.url { word-break: break-all; font-family: monospace; font-size: 0.85rem; }
.chips { display: flex; flex-wrap: wrap; gap: 0.25rem; }
.actions { display: flex; gap: 0.1rem; }
.when { display: block; color: var(--sk-text-muted, #6b7a71); }
.err { color: var(--red-600, #c0392b); word-break: break-word; }
.p-field { margin-bottom: 1rem; }
label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
label.inline { display: inline; margin: 0; }
.secret-row { display: flex; gap: 0.5rem; }
.secret { font-family: monospace; }
</style>
