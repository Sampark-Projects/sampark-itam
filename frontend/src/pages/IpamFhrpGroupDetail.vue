<!--
  - IpamFhrpGroupDetail.vue
  - One FHRP group: its details, the virtual IP addresses, the asset interfaces that take part (with their priority) and
  - the services the group offers.
-->
<template>
  <div class="ipam-detail">
    <div class="page-header">
      <div class="title">
        <Button icon="pi pi-arrow-left" text rounded :aria-label="t('ipam.back')" @click="router.push('/ipam/fhrp-groups')" />
        <h1 v-if="group">{{ group.label }}</h1>
      </div>
      <div v-if="group" class="flex gap-2">
        <Button v-if="canWrite('ipam')" :label="t('common.actions.edit')" icon="pi pi-pencil" outlined @click="formOpen = true" />
        <Button v-if="canDelete('ipam')" :label="t('common.actions.delete')" icon="pi pi-trash" severity="danger" outlined @click="remove" />
      </div>
    </div>

    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div v-if="loading && !group" class="loading"><i class="pi pi-spin pi-spinner"></i></div>

    <template v-if="group">
      <div class="cards">
        <section class="card">
          <h3>{{ t('ipam.prefixes.cards.details') }}</h3>
          <dl>
            <dt>{{ t('ipam.fhrp.fields.protocol') }}</dt><dd>{{ group.protocol_label }}</dd>
            <dt>{{ t('ipam.fhrp.fields.groupId') }}</dt><dd>{{ group.group_id }}</dd>
            <dt>{{ t('ipam.fhrp.fields.name') }}</dt><dd>{{ group.name || t('ipam.none') }}</dd>
            <dt>{{ t('ipam.fhrp.fields.authType') }}</dt>
            <dd>{{ group.auth_type ? t(`ipam.fhrp.authTypes.${group.auth_type}`) : t('ipam.none') }}<small v-if="group.has_auth_key" class="muted"> ({{ t('ipam.fhrp.keyStored') }})</small></dd>
            <dt>{{ t('ipam.fields.description') }}</dt><dd>{{ group.description || t('ipam.none') }}</dd>
          </dl>
        </section>
        <section class="card">
          <h3>{{ t('ipam.fhrp.virtualAddresses') }}</h3>
          <p v-if="!group.ip_addresses.length" class="muted">{{ t('ipam.fhrp.noAddresses') }}</p>
          <ul v-else class="plain">
            <li v-for="a in group.ip_addresses" :key="a.id"><span class="mono">{{ a.address }}</span></li>
          </ul>
          <small class="muted">{{ t('ipam.fhrp.addressHint') }}</small>
        </section>
      </div>

      <h3 class="section">{{ t('ipam.fhrp.interfaces') }}</h3>
      <div v-if="canWrite('ipam')" class="toolbar">
        <Dropdown v-model="newInterface" :options="interfaceOptions" optionLabel="label" optionValue="value" filter showClear
                  :filterPlaceholder="t('ipam.addresses.searchInterface')" :placeholder="t('ipam.fhrp.chooseInterface')" class="interface-pick"
                  @filter="onInterfaceFilter" />
        <InputNumber v-model="newPriority" :min="0" :max="255" :useGrouping="false" showButtons class="priority" />
        <Button :label="t('ipam.fhrp.addInterface')" icon="pi pi-plus" size="small" :disabled="!newInterface" :loading="adding" @click="addInterface" />
      </div>
      <DataTable :value="group.assignments" dataKey="id">
        <template #empty>{{ t('ipam.fhrp.noInterfaces') }}</template>
        <Column :header="t('ipam.fhrp.fields.asset')">
          <template #body="{ data }"><router-link :to="`/assets/${data.asset_id}`">{{ data.asset_name }}</router-link></template>
        </Column>
        <Column field="interface_name" :header="t('ipam.fhrp.fields.interface')" />
        <Column :header="t('ipam.fhrp.fields.priority')" style="width: 10rem">
          <template #body="{ data }">
            <InputNumber v-if="canWrite('ipam')" v-model="data.priority" :min="0" :max="255" :useGrouping="false" inputClass="priority-input" @blur="savePriority(data)" @keydown.enter="savePriority(data)" />
            <span v-else>{{ data.priority }}</span>
          </template>
        </Column>
        <Column v-if="canWrite('ipam')" style="width: 4rem">
          <template #body="{ data }">
            <Button icon="pi pi-times" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeInterface(data)" />
          </template>
        </Column>
      </DataTable>

      <h3 class="section">{{ t('ipam.services.title') }}</h3>
      <div v-if="canWrite('ipam')" class="toolbar">
        <Button :label="t('ipam.services.new')" icon="pi pi-plus" size="small" @click="serviceOpen = true" />
      </div>
      <DataTable :value="group.services" dataKey="id">
        <template #empty>{{ t('ipam.services.empty') }}</template>
        <Column field="name" :header="t('ipam.services.fields.name')" />
        <Column field="ports_text" :header="t('ipam.services.fields.ports')" />
        <Column :header="t('ipam.services.fields.addresses')">
          <template #body="{ data }"><span class="mono">{{ data.ip_addresses.map(a => a.address).join(', ') }}</span></template>
        </Column>
        <Column field="description" :header="t('ipam.fields.description')" />
        <Column v-if="canDelete('ipam')" style="width: 4rem">
          <template #body="{ data }">
            <Button icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeService(data)" />
          </template>
        </Column>
      </DataTable>
    </template>

    <IpamFhrpGroupForm v-model:visible="formOpen" :group="group" @saved="load" />
    <IpamServiceForm v-if="group" v-model:visible="serviceOpen" :service="null" :defaults="{ fhrp_group_id: group.id }" @saved="load" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dropdown from 'primevue/dropdown'
import InputNumber from 'primevue/inputnumber'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import IpamFhrpGroupForm from '../components/forms/IpamFhrpGroupForm.vue'
import IpamServiceForm from '../components/forms/IpamServiceForm.vue'
import { usePermissions } from '../composables/usePermissions'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const { canWrite, canDelete } = usePermissions()

const group = ref(null)
const loading = ref(false)
const error = ref('')
const formOpen = ref(false)
const serviceOpen = ref(false)
const id = computed(() => route.params.id)

async function load() {
  loading.value = true
  error.value = ''
  try {
    group.value = (await api.getIpamFhrpGroup(id.value)).data
  } catch (err) {
    group.value = null
    error.value = apiErrorText(err, t)
  } finally {
    loading.value = false
  }
}

async function remove() {
  if (!window.confirm(t('ipam.fhrp.deleteConfirm', { name: group.value.label }))) return
  try {
    await api.deleteIpamFhrpGroup(group.value.id)
    router.push('/ipam/fhrp-groups')
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

// --- interfaces that take part in the group ---
const interfaces = ref([])
const newInterface = ref(null)
const newPriority = ref(100)
const adding = ref(false)
const interfaceOptions = computed(() => {
  const taken = new Set((group.value?.assignments || []).map(a => a.asset_interface_id))
  return interfaces.value.filter(i => !taken.has(i.id)).map(i => ({ value: i.id, label: i.label }))
})
let timer = null
async function searchInterfaces(q) {
  try { interfaces.value = (await api.searchIpamInterfaces(q || '')).data || [] } catch (e) { interfaces.value = [] }
}
function onInterfaceFilter(event) { clearTimeout(timer); timer = setTimeout(() => searchInterfaces(event.value), 250) }

async function addInterface() {
  adding.value = true
  try {
    await api.addIpamFhrpAssignment(group.value.id, { asset_interface_id: newInterface.value, priority: newPriority.value ?? 100 })
    newInterface.value = null
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    adding.value = false
  }
}
async function savePriority(row) {
  try {
    await api.updateIpamFhrpAssignment(group.value.id, row.id, { priority: row.priority ?? 0 })
  } catch (err) {
    error.value = apiErrorText(err, t)
    await load()
  }
}
async function removeInterface(row) {
  if (!window.confirm(t('ipam.fhrp.removeInterfaceConfirm', { name: `${row.asset_name} / ${row.interface_name}` }))) return
  try {
    await api.deleteIpamFhrpAssignment(group.value.id, row.id)
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

async function removeService(row) {
  if (!window.confirm(t('ipam.services.deleteConfirm', { name: row.name }))) return
  try {
    await api.deleteIpamService(row.id)
    await load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

watch(id, load)
onMounted(() => { load(); searchInterfaces('') })
</script>

<style scoped>
.title { display: flex; align-items: center; gap: 0.5rem; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.loading { padding: 2rem; text-align: center; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(22rem, 1fr)); gap: 1rem; margin-bottom: 1rem; }
.card { border: 1px solid var(--sk-border, #e1e7e3); border-radius: 8px; padding: 1rem 1.25rem; background: var(--sk-surface, #fff); }
.card h3 { margin: 0 0 0.75rem; font-size: 1rem; }
.section { margin: 1.25rem 0 0.5rem; font-size: 1.05rem; }
dl { display: grid; grid-template-columns: 11rem 1fr; gap: 0.5rem 1rem; margin: 0; }
dt { color: var(--sk-text-muted, #6b7a71); }
dd { margin: 0; overflow-wrap: anywhere; }
.plain { list-style: none; margin: 0 0 0.5rem; padding: 0; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.toolbar { display: flex; gap: 0.6rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.interface-pick { min-width: 20rem; }
.priority { width: 9rem; }
:deep(.priority-input) { width: 6rem; }
@media (max-width: 640px) { dl { grid-template-columns: 1fr; } .interface-pick { min-width: 100%; } }
</style>
