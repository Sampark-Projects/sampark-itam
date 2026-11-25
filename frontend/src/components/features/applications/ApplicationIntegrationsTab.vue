<!--
  - ApplicationIntegrationsTab.vue
  - Upstream and downstream systems an application is connected to: name, direction, protocol and port.
-->
<template>
  <div>
    <p class="hint">{{ t('applications.integrationsTab.hint') }}</p>
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="toolbar">
      <Button v-if="canWrite('applications')" :label="t('applications.integrationsTab.add')" icon="pi pi-plus" size="small" @click="openForm(null)" />
    </div>
    <div v-if="loading" class="loading"><i class="pi pi-spin pi-spinner"></i></div>
    <table v-else-if="items.length" class="app-table">
      <thead>
        <tr>
          <th>{{ t('applications.integrationsTab.name') }}</th><th>{{ t('applications.integrationsTab.direction') }}</th>
          <th>{{ t('applications.integrationsTab.protocol') }}</th><th>{{ t('applications.integrationsTab.port') }}</th><th v-if="canWrite('applications')"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="i in items" :key="i.id">
          <td>
            {{ i.name }}
            <small v-if="i.peer_asset_name" class="muted block">{{ i.peer_asset_name }}</small>
            <small v-if="i.notes" class="muted block">{{ i.notes }}</small>
          </td>
          <td>{{ t(`applications.directions.${i.direction}`) }}</td>
          <td>{{ i.protocol || none }}</td>
          <td>{{ i.port || none }}</td>
          <td v-if="canWrite('applications')" class="num">
            <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('applications.integrationsTab.edit')" @click="openForm(i)" />
            <Button v-if="canDelete('applications')" icon="pi pi-trash" text rounded size="small" severity="danger" @click="remove(i)" />
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else class="muted">{{ t('applications.integrationsTab.empty') }}</p>

    <Dialog v-model:visible="formOpen" modal :header="editing ? t('applications.integrationsTab.edit') : t('applications.integrationsTab.add')"
            :style="{ width: '34rem', maxWidth: '96vw' }">
      <Message v-if="formError" severity="error" :closable="true" @close="formError = ''">{{ formError }}</Message>
      <div class="p-field">
        <label>{{ t('applications.integrationsTab.name') }} *</label>
        <InputText v-model="form.name" maxlength="150" :placeholder="t('applications.integrationsTab.namePlaceholder')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.integrationsTab.direction') }}</label>
        <Dropdown v-model="form.direction" :options="directionOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="two">
        <div class="p-field">
          <label>{{ t('applications.integrationsTab.protocol') }}</label>
          <InputText v-model="form.protocol" maxlength="100" :placeholder="t('applications.integrationsTab.protocolPlaceholder')" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('applications.integrationsTab.port') }}</label>
          <InputText v-model="form.port" maxlength="50" class="w-full" />
        </div>
      </div>
      <div class="p-field">
        <label>{{ t('applications.integrationsTab.peer') }}</label>
        <Dropdown v-model="form.peer_asset_id" :options="peerOptions" optionLabel="label" optionValue="value" showClear filter
                  :loading="peersLoading" class="w-full" @filter="onPeerFilter" @show="loadPeers('')" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.integrationsTab.notes') }}</label>
        <Textarea v-model="form.notes" rows="2" autoResize maxlength="2000" class="w-full" />
      </div>
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="formOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="save" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import Textarea from 'primevue/textarea'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({ applicationId: { type: String, required: true } })
const emit = defineEmits(['changed'])
const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const none = computed(() => t('applications.none'))

const DIRECTIONS = ['outbound', 'inbound', 'bidirectional']
const directionOptions = computed(() => DIRECTIONS.map(v => ({ value: v, label: t(`applications.directions.${v}`) })))

const items = ref([])
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  try {
    items.value = (await api.getApplicationIntegrations(props.applicationId)).data || []
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    loading.value = false
  }
}

// --- form ---
const formOpen = ref(false)
const editing = ref(null)
const form = ref({})
const formError = ref('')
const saving = ref(false)
const peerOptions = ref([])
const peersLoading = ref(false)
const blank = () => ({ name: '', direction: 'outbound', protocol: '', port: '', peer_asset_id: null, notes: '' })

let peerRequest = 0
async function loadPeers(q) {
  const mine = ++peerRequest
  peersLoading.value = true
  try {
    const res = await api.searchApplicationAssets(props.applicationId, q, true)
    const list = Array.isArray(res.data) ? res.data : []
    if (mine === peerRequest) peerOptions.value = withCurrent(list.map(a => ({ value: a.id, label: a.name })))
  } catch (e) {
    if (mine === peerRequest) peerOptions.value = withCurrent([])
  } finally {
    if (mine === peerRequest) peersLoading.value = false
  }
}

function withCurrent(options) {
  const current = editing.value?.peer_asset_id
  if (current && !options.some(o => o.value === current)) options.unshift({ value: current, label: editing.value.peer_asset_name || current })
  return options
}

let timer = null
function onPeerFilter(event) {
  clearTimeout(timer)
  timer = setTimeout(() => loadPeers(event.value || ''), 300)
}

function openForm(item) {
  editing.value = item
  formError.value = ''
  form.value = item
    ? { name: item.name, direction: item.direction, protocol: item.protocol || '', port: item.port || '', peer_asset_id: item.peer_asset_id, notes: item.notes || '' }
    : blank()
  peerOptions.value = withCurrent([])
  formOpen.value = true
}

async function save() {
  formError.value = ''
  if (!form.value.name.trim()) {
    formError.value = t('applications.integrationsTab.required')
    return
  }
  const body = { ...form.value }
  for (const key of ['protocol', 'port', 'notes']) if (body[key] === '') body[key] = null
  saving.value = true
  try {
    if (editing.value) await api.updateApplicationIntegration(props.applicationId, editing.value.id, body)
    else await api.addApplicationIntegration(props.applicationId, body)
    formOpen.value = false
    await load()
    emit('changed')
  } catch (err) {
    formError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

async function remove(item) {
  if (!window.confirm(t('applications.integrationsTab.deleteConfirm', { name: item.name }))) return
  try {
    await api.deleteApplicationIntegration(props.applicationId, item.id)
    await load()
    emit('changed')
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

onMounted(load)
</script>

<style scoped>
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { margin-bottom: 0.75rem; }
.loading { padding: 1.5rem; text-align: center; }
.app-table { width: 100%; border-collapse: collapse; }
.app-table th, .app-table td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--sk-border, #e1e7e3); vertical-align: top; }
.app-table th { font-weight: 600; font-size: 0.85rem; color: var(--sk-text-muted, #6b7a71); white-space: nowrap; }
.num { white-space: nowrap; text-align: right; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.block { display: block; }
.two { display: grid; grid-template-columns: 2fr 1fr; gap: 0.75rem; }
.p-field { margin-bottom: 0.75rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
</style>
