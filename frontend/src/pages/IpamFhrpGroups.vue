<!--
  - IpamFhrpGroups.vue
  - FHRP groups (VRRP, HSRP, GLBP, CARP ...): a paged list. A group has virtual IP addresses, the interfaces that take part
  - in it and the services it offers; those are managed on the detail page.
-->
<template>
  <div class="ipam-page">
    <div class="page-header">
      <h1>{{ t('ipam.fhrp.title') }}</h1>
      <Button v-if="canWrite('ipam')" :label="t('ipam.fhrp.new')" icon="pi pi-plus" severity="success" @click="formOpen = true" />
    </div>
    <p class="hint">{{ t('ipam.fhrp.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div class="toolbar">
      <span class="p-input-icon-left search">
        <i class="pi pi-search" />
        <InputText v-model="search" :placeholder="t('ipam.fhrp.searchPlaceholder')" class="w-full" @input="onSearch" />
      </span>
      <Dropdown v-model="protocol" :options="protocolOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.fhrp.allProtocols')" class="filter" @change="reload" />
    </div>

    <DataTable :value="items" :loading="loading" dataKey="id" lazy paginator :rows="rows" :first="first" :totalRecords="total"
               :rowsPerPageOptions="[25, 50, 100]" @page="onPage">
      <template #empty>{{ t('ipam.fhrp.empty') }}</template>
      <Column :header="t('ipam.fhrp.fields.protocol')" style="width: 9rem">
        <template #body="{ data }"><Tag :value="data.protocol_label" severity="info" /></template>
      </Column>
      <Column :header="t('ipam.fhrp.fields.groupId')" style="width: 7rem">
        <template #body="{ data }"><router-link :to="`/ipam/fhrp-groups/${data.id}`"><strong>{{ data.group_id }}</strong></router-link></template>
      </Column>
      <Column field="name" :header="t('ipam.fhrp.fields.name')" />
      <Column :header="t('ipam.fhrp.virtualAddresses')">
        <template #body="{ data }"><span class="mono">{{ data.ip_addresses.map(a => a.address).join(', ') }}</span></template>
      </Column>
      <Column :header="t('ipam.fhrp.fields.authType')" style="width: 9rem">
        <template #body="{ data }">{{ data.auth_type ? t(`ipam.fhrp.authTypes.${data.auth_type}`) : '' }}</template>
      </Column>
      <Column field="assignment_count" :header="t('ipam.fhrp.interfaces')" style="width: 8rem" />
      <Column field="service_count" :header="t('ipam.services.title')" style="width: 7rem" />
      <Column v-if="canWrite('ipam')" style="width: 6rem">
        <template #body="{ data }">
          <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openForm(data)" />
          <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <IpamFhrpGroupForm v-model:visible="formOpen" :group="editing" @saved="onSaved" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import InputText from 'primevue/inputtext'
import Dropdown from 'primevue/dropdown'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import IpamFhrpGroupForm from '../components/forms/IpamFhrpGroupForm.vue'
import { usePermissions } from '../composables/usePermissions'
import { FHRP_PROTOCOLS } from '../composables/useIpam'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()

const items = ref([])
const total = ref(0)
const loading = ref(false)
const message = ref(null)
const search = ref('')
const protocol = ref(null)
const rows = ref(50)
const first = ref(0)
const formOpen = ref(false)
const editing = ref(null)
const protocolOptions = computed(() => FHRP_PROTOCOLS.map(v => ({ value: v, label: t(`ipam.fhrp.protocols.${v}`) })))

async function load() {
  loading.value = true
  try {
    const params = { skip: first.value, limit: rows.value }
    if (search.value.trim()) params.search = search.value.trim()
    if (protocol.value) params.protocol = protocol.value
    const res = await api.getIpamFhrpGroups(params)
    items.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    loading.value = false
  }
}
function reload() { first.value = 0; load() }
let timer = null
function onSearch() { clearTimeout(timer); timer = setTimeout(reload, 300) }
function onPage(event) { first.value = event.first; rows.value = event.rows; load() }

function openForm(row) { editing.value = row; formOpen.value = true }
watch(formOpen, open => { if (!open) editing.value = null })
function onSaved() { message.value = { severity: 'success', text: t('ipam.saved') }; load() }

async function remove(row) {
  if (!window.confirm(t('ipam.fhrp.deleteConfirm', { name: row.label }))) return
  try {
    await api.deleteIpamFhrpGroup(row.id)
    await load()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

onMounted(load)
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.search { flex: 1 1 16rem; max-width: 24rem; }
.filter { min-width: 11rem; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
</style>
