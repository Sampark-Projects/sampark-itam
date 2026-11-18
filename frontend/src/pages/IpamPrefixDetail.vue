<!--
  - IpamPrefixDetail.vue
  - One prefix: details, usage, parents, and tabs for the prefixes, IP addresses and IP ranges inside it.
-->
<template>
  <div class="ipam-detail">
    <div class="page-header">
      <div class="title">
        <Button icon="pi pi-arrow-left" text rounded :aria-label="t('ipam.back')" @click="router.push('/ipam/prefixes')" />
        <h1 v-if="prefix"><span class="mono">{{ prefix.prefix }}</span> <Tag :value="t(`ipam.statuses.${prefix.status}`)" :severity="statusSeverity(prefix.status)" /></h1>
      </div>
      <div v-if="prefix" class="flex gap-2">
        <Button v-if="canWrite('ipam')" :label="t('common.actions.edit')" icon="pi pi-pencil" outlined @click="formOpen = true" />
        <Button v-if="canDelete('ipam')" :label="t('common.actions.delete')" icon="pi pi-trash" severity="danger" outlined @click="remove" />
      </div>
    </div>

    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div v-if="loading && !prefix" class="loading"><i class="pi pi-spin pi-spinner"></i></div>

    <template v-if="prefix">
      <nav v-if="prefix.parents.length" class="crumbs">
        <router-link v-for="p in prefix.parents" :key="p.id" :to="`/ipam/prefixes/${p.id}`" class="mono">{{ p.prefix }}</router-link>
        <span class="mono current">{{ prefix.prefix }}</span>
      </nav>

      <div class="cards">
        <section class="card">
          <h3>{{ t('ipam.prefixes.cards.details') }}</h3>
          <dl>
            <dt>{{ t('ipam.prefixes.fields.prefix') }}</dt><dd class="mono">{{ prefix.prefix }}</dd>
            <dt>{{ t('ipam.fields.vrf') }}</dt><dd>{{ prefix.vrf_name || t('ipam.fields.globalTable') }}</dd>
            <dt>{{ t('ipam.aggregates.aggregate') }}</dt>
            <dd>
              <router-link v-if="prefix.aggregate" :to="`/ipam/aggregates/${prefix.aggregate.id}`" class="mono">{{ prefix.aggregate.prefix }}</router-link>
              <small v-if="prefix.aggregate" class="muted"> ({{ prefix.aggregate.rir_name }})</small>
              <template v-else>{{ none }}</template>
            </dd>
            <dt>{{ t('ipam.fields.role') }}</dt><dd>{{ prefix.role_name || none }}</dd>
            <dt>{{ t('ipam.fields.vlan') }}</dt><dd>{{ prefix.vlan_label || none }}</dd>
            <dt>{{ t('ipam.fields.site') }}</dt><dd>{{ prefix.site_name || none }}</dd>
            <dt>{{ t('ipam.prefixes.fields.isPool') }}</dt><dd>{{ prefix.is_pool ? t('ipam.yes') : t('ipam.no') }}</dd>
            <dt>{{ t('ipam.prefixes.fields.markUtilized') }}</dt><dd>{{ prefix.mark_utilized ? t('ipam.yes') : t('ipam.no') }}</dd>
            <dt>{{ t('ipam.fields.description') }}</dt><dd>{{ prefix.description || none }}</dd>
          </dl>
        </section>
        <section class="card">
          <h3>{{ t('ipam.prefixes.cards.usage') }}</h3>
          <IpamUtilization :value="prefix.utilization" />
          <dl>
            <dt>{{ t('ipam.prefixes.availableIps') }}</dt><dd>{{ prefix.status === 'container' ? none : prefix.available_ips }}</dd>
            <dt>{{ t('ipam.prefixes.childPrefixes') }}</dt><dd>{{ prefix.child_prefix_count }}</dd>
            <dt>{{ t('ipam.prefixes.addresses') }}</dt><dd>{{ prefix.ip_address_count }}</dd>
            <dt>{{ t('ipam.prefixes.ranges') }}</dt><dd>{{ prefix.child_range_count }}</dd>
          </dl>
        </section>
      </div>

      <TabView lazy class="modern-tabs">
        <TabPanel :header="`${t('ipam.prefixes.tabs.prefixes')} (${prefix.child_prefix_count})`">
          <div class="toolbar">
            <label class="check"><Checkbox v-model="showAvailable" binary @change="reloadChildren" /><span>{{ t('ipam.prefixes.showAvailable') }}</span></label>
            <span class="spacer"></span>
            <Button v-if="canWrite('ipam')" :label="t('ipam.prefixes.addChild')" icon="pi pi-plus" size="small" @click="addChild(null)" />
          </div>
          <DataTable :value="children" :loading="childLoading" dataKey="prefix" lazy paginator :rows="childRows" :first="childFirst" :totalRecords="childTotal"
                     :rowsPerPageOptions="[25, 50, 100]" :rowClass="r => (r.available ? 'free-row' : '')" @page="onChildPage">
            <template #empty>{{ t('ipam.prefixes.noChildren') }}</template>
            <Column :header="t('ipam.prefixes.fields.prefix')">
              <template #body="{ data }">
                <router-link v-if="!data.available" :to="`/ipam/prefixes/${data.id}`" class="mono">{{ data.prefix }}</router-link>
                <span v-else class="mono">{{ data.prefix }}</span>
              </template>
            </Column>
            <Column :header="t('ipam.fields.status')" style="width: 9rem">
              <template #body="{ data }">
                <Tag v-if="!data.available" :value="t(`ipam.statuses.${data.status}`)" :severity="statusSeverity(data.status)" />
                <Tag v-else :value="t('ipam.prefixes.available')" severity="success" />
              </template>
            </Column>
            <Column :header="t('ipam.prefixes.utilization')" style="width: 11rem">
              <template #body="{ data }"><IpamUtilization v-if="!data.available" :value="data.utilization" /></template>
            </Column>
            <Column field="role_name" :header="t('ipam.fields.role')" style="width: 8rem" />
            <Column field="vlan_label" :header="t('ipam.fields.vlan')" style="width: 9rem" />
            <Column field="description" :header="t('ipam.fields.description')" />
            <Column v-if="canWrite('ipam')" style="width: 8rem">
              <template #body="{ data }">
                <Button v-if="data.available" :label="t('ipam.prefixes.addHere')" size="small" text @click="addChild(data.prefix)" />
              </template>
            </Column>
          </DataTable>
        </TabPanel>

        <TabPanel :header="`${t('ipam.prefixes.tabs.addresses')} (${prefix.ip_address_count})`">
          <div class="toolbar">
            <span v-if="free.length" class="free-note">{{ t('ipam.prefixes.nextFree') }}: <span class="mono">{{ free.join(', ') }}</span></span>
            <span class="spacer"></span>
            <Button v-if="canWrite('ipam') && prefix.status !== 'container'" :label="t('ipam.addresses.allocate')" icon="pi pi-bolt" size="small" outlined @click="allocateOpen = true" />
            <Button v-if="canWrite('ipam')" :label="t('ipam.addresses.new')" icon="pi pi-plus" size="small" @click="openAddress(null)" />
          </div>
          <DataTable :value="addresses" :loading="addressLoading" dataKey="id" lazy paginator :rows="addressRows" :first="addressFirst" :totalRecords="addressTotal"
                     :rowsPerPageOptions="[25, 50, 100]" @page="onAddressPage">
            <template #empty>{{ t('ipam.addresses.empty') }}</template>
            <Column :header="t('ipam.addresses.fields.address')">
              <template #body="{ data }"><strong class="mono">{{ data.address }}</strong></template>
            </Column>
            <Column :header="t('ipam.fields.status')" style="width: 8rem">
              <template #body="{ data }"><Tag :value="t(`ipam.statuses.${data.status}`)" :severity="statusSeverity(data.status)" /></template>
            </Column>
            <Column field="dns_name" :header="t('ipam.addresses.fields.dnsName')" />
            <Column :header="t('ipam.addresses.fields.assignedTo')">
              <template #body="{ data }">
                <router-link v-if="data.assigned_to" :to="`/assets/${data.assigned_to.asset_id}`">{{ data.assigned_to.asset_name }} / {{ data.assigned_to.interface_name }}</router-link>
              </template>
            </Column>
            <Column field="description" :header="t('ipam.fields.description')" />
            <Column v-if="canWrite('ipam')" style="width: 6rem">
              <template #body="{ data }">
                <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openAddress(data)" />
                <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeAddress(data)" />
              </template>
            </Column>
          </DataTable>
        </TabPanel>

        <TabPanel :header="`${t('ipam.prefixes.tabs.ranges')} (${prefix.child_range_count})`">
          <DataTable :value="ranges" :loading="rangeLoading" dataKey="id">
            <template #empty>{{ t('ipam.ranges.empty') }}</template>
            <Column :header="t('ipam.ranges.fields.range')">
              <template #body="{ data }"><strong class="mono">{{ data.label }}</strong></template>
            </Column>
            <Column :header="t('ipam.fields.status')" style="width: 8rem">
              <template #body="{ data }"><Tag :value="t(`ipam.statuses.${data.status}`)" :severity="statusSeverity(data.status)" /></template>
            </Column>
            <Column field="size" :header="t('ipam.ranges.fields.size')" style="width: 6rem" />
            <Column :header="t('ipam.prefixes.utilization')" style="width: 11rem">
              <template #body="{ data }"><IpamUtilization :value="data.utilization" /></template>
            </Column>
            <Column field="description" :header="t('ipam.fields.description')" />
          </DataTable>
        </TabPanel>
      </TabView>
    </template>

    <IpamPrefixForm v-model:visible="formOpen" :prefix="prefix" @saved="onEdited" />
    <IpamPrefixForm v-model:visible="childFormOpen" :prefix="null" :defaults="childDefaults" @saved="onChildSaved" />
    <IpamAddressForm v-model:visible="addressFormOpen" :address="editingAddress" :defaults="addressDefaults" @saved="onAddressSaved" />
    <IpamAddressForm v-if="prefix" v-model:visible="allocateOpen" :allocateInto="prefix" @saved="onAddressSaved" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import IpamPrefixForm from '../components/forms/IpamPrefixForm.vue'
import IpamAddressForm from '../components/forms/IpamAddressForm.vue'
import IpamUtilization from '../components/features/ipam/IpamUtilization.vue'
import { usePermissions } from '../composables/usePermissions'
import { statusSeverity } from '../composables/useIpam'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const { canWrite, canDelete } = usePermissions()

const prefix = ref(null)
const loading = ref(false)
const error = ref('')
const formOpen = ref(false)
const none = computed(() => t('ipam.none'))
const id = computed(() => route.params.id)

async function load() {
  loading.value = true
  error.value = ''
  try {
    prefix.value = (await api.getIpamPrefix(id.value)).data
    loadFree()
    loadChildren()
    loadAddresses()
    loadRanges()
  } catch (err) {
    prefix.value = null
    error.value = apiErrorText(err, t)
  } finally {
    loading.value = false
  }
}

async function remove() {
  if (!window.confirm(t('ipam.prefixes.deleteConfirm', { name: prefix.value.prefix }))) return
  try {
    await api.deleteIpamPrefix(prefix.value.id)
    router.push('/ipam/prefixes')
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

const onEdited = updated => { prefix.value = { ...prefix.value, ...updated }; load() }

// --- child prefixes (with the free blocks between them) ---
const children = ref([])
const childTotal = ref(0)
const childLoading = ref(false)
const childRows = ref(50)
const childFirst = ref(0)
const showAvailable = ref(true)
const childFormOpen = ref(false)
const childDefaults = ref({})

async function loadChildren() {
  childLoading.value = true
  try {
    const res = await api.getIpamChildPrefixes(id.value, { show_available: showAvailable.value, skip: childFirst.value, limit: childRows.value })
    children.value = res.data.items || []
    childTotal.value = res.data.total || 0
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    childLoading.value = false
  }
}
function reloadChildren() { childFirst.value = 0; loadChildren() }
function onChildPage(event) { childFirst.value = event.first; childRows.value = event.rows; loadChildren() }
function addChild(block) {
  childDefaults.value = { prefix: block || '', vrf_id: prefix.value.vrf_id }
  childFormOpen.value = true
}
function onChildSaved() { load() }

// --- addresses ---
const addresses = ref([])
const addressTotal = ref(0)
const addressLoading = ref(false)
const addressRows = ref(50)
const addressFirst = ref(0)
const free = ref([])
const addressFormOpen = ref(false)
const editingAddress = ref(null)
const addressDefaults = ref({})
const allocateOpen = ref(false)

async function loadAddresses() {
  addressLoading.value = true
  try {
    const res = await api.getIpamPrefixAddresses(id.value, { skip: addressFirst.value, limit: addressRows.value })
    addresses.value = res.data.items || []
    addressTotal.value = res.data.total || 0
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    addressLoading.value = false
  }
}
async function loadFree() {
  try { free.value = (await api.getIpamAvailableIps(id.value, 3)).data.addresses || [] } catch (e) { free.value = [] }
}
function onAddressPage(event) { addressFirst.value = event.first; addressRows.value = event.rows; loadAddresses() }
function openAddress(row) {
  editingAddress.value = row
  addressDefaults.value = { vrf_id: prefix.value.vrf_id, address: free.value[0] || '' }
  addressFormOpen.value = true
}
function onAddressSaved() { load() }
async function removeAddress(row) {
  if (!window.confirm(t('ipam.addresses.deleteConfirm', { name: row.address }))) return
  try {
    await api.deleteIpamAddress(row.id)
    load()
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

// --- ranges ---
const ranges = ref([])
const rangeLoading = ref(false)
async function loadRanges() {
  rangeLoading.value = true
  try { ranges.value = (await api.getIpamPrefixRanges(id.value)).data || [] } catch (e) { ranges.value = [] } finally { rangeLoading.value = false }
}

watch(id, () => { childFirst.value = 0; addressFirst.value = 0; load() })
onMounted(load)
</script>

<style scoped>
.title { display: flex; align-items: center; gap: 0.5rem; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.loading { padding: 2rem; text-align: center; }
.crumbs { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.75rem; font-size: 0.9rem; }
.crumbs a::after { content: '›'; margin-left: 0.5rem; color: var(--sk-text-muted, #6b7a71); }
.crumbs .current { font-weight: 600; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(22rem, 1fr)); gap: 1rem; margin-bottom: 1rem; }
.card { border: 1px solid var(--sk-border, #e1e7e3); border-radius: 8px; padding: 1rem 1.25rem; background: var(--sk-surface, #fff); }
.card h3 { margin: 0 0 0.75rem; font-size: 1rem; }
dl { display: grid; grid-template-columns: 11rem 1fr; gap: 0.5rem 1rem; margin: 0.75rem 0 0; }
dt { color: var(--sk-text-muted, #6b7a71); }
dd { margin: 0; overflow-wrap: anywhere; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.toolbar { display: flex; gap: 0.6rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.toolbar .spacer { flex: 1; }
.check { display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer; }
.free-note { font-size: 0.85rem; color: var(--sk-text-muted, #6b7a71); }
:deep(.free-row) { background: #f0fdf4 !important; }
@media (max-width: 640px) { dl { grid-template-columns: 1fr; } }
</style>
