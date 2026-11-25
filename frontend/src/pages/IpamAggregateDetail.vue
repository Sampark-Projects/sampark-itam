<!--
  - IpamAggregateDetail.vue
  - One aggregate: details, utilization, and the prefixes inside it (of every routing table) with the free blocks between them.
-->
<template>
  <div class="ipam-detail">
    <div class="page-header">
      <div class="title">
        <Button icon="pi pi-arrow-left" text rounded :aria-label="t('ipam.back')" @click="router.push('/ipam/aggregates')" />
        <h1 v-if="aggregate"><span class="mono">{{ aggregate.prefix }}</span> <Tag :value="aggregate.rir_name" severity="info" /></h1>
      </div>
      <div v-if="aggregate" class="flex gap-2">
        <Button v-if="canWrite('ipam')" :label="t('common.actions.edit')" icon="pi pi-pencil" outlined @click="formOpen = true" />
        <Button v-if="canDelete('ipam')" :label="t('common.actions.delete')" icon="pi pi-trash" severity="danger" outlined @click="remove" />
      </div>
    </div>

    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div v-if="loading && !aggregate" class="loading"><i class="pi pi-spin pi-spinner"></i></div>

    <template v-if="aggregate">
      <div class="cards">
        <section class="card">
          <h3>{{ t('ipam.prefixes.cards.details') }}</h3>
          <dl>
            <dt>{{ t('ipam.aggregates.fields.prefix') }}</dt><dd class="mono">{{ aggregate.prefix }}</dd>
            <dt>{{ t('ipam.aggregates.fields.rir') }}</dt><dd>{{ aggregate.rir_name }} <small v-if="aggregate.rir_is_private" class="muted">({{ t('ipam.rirs.private') }})</small></dd>
            <dt>{{ t('ipam.aggregates.fields.dateAdded') }}</dt><dd>{{ aggregate.date_added ? formatDate(aggregate.date_added) : t('ipam.none') }}</dd>
            <dt>{{ t('ipam.fields.description') }}</dt><dd>{{ aggregate.description || t('ipam.none') }}</dd>
          </dl>
        </section>
        <section class="card">
          <h3>{{ t('ipam.prefixes.cards.usage') }}</h3>
          <IpamUtilization :value="aggregate.utilization" />
          <dl>
            <dt>{{ t('ipam.overview.prefixes') }}</dt><dd>{{ aggregate.prefix_count }}</dd>
          </dl>
        </section>
      </div>

      <div class="toolbar">
        <label class="check"><Checkbox v-model="showAvailable" binary @change="reloadChildren" /><span>{{ t('ipam.prefixes.showAvailable') }}</span></label>
        <span class="spacer"></span>
        <Button v-if="canWrite('ipam')" :label="t('ipam.prefixes.addChild')" icon="pi pi-plus" size="small" @click="addPrefix(null)" />
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
        <Column :header="t('ipam.fields.vrf')" style="width: 9rem">
          <template #body="{ data }">{{ data.available ? '' : (data.vrf_name || t('ipam.fields.globalTable')) }}</template>
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
        <Column field="description" :header="t('ipam.fields.description')" />
        <Column v-if="canWrite('ipam')" style="width: 8rem">
          <template #body="{ data }">
            <Button v-if="data.available" :label="t('ipam.prefixes.addHere')" size="small" text @click="addPrefix(data.prefix)" />
          </template>
        </Column>
      </DataTable>
    </template>

    <IpamAggregateForm v-model:visible="formOpen" :aggregate="aggregate" :rirs="rirOptions" @saved="onEdited" />
    <IpamPrefixForm v-model:visible="prefixOpen" :prefix="null" :defaults="prefixDefaults" @saved="onPrefixSaved" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import IpamAggregateForm from '../components/forms/IpamAggregateForm.vue'
import IpamPrefixForm from '../components/forms/IpamPrefixForm.vue'
import IpamUtilization from '../components/features/ipam/IpamUtilization.vue'
import { usePermissions } from '../composables/usePermissions'
import { useDateFormatter } from '../composables/useDateFormatter'
import { statusSeverity } from '../composables/useIpam'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const { canWrite, canDelete } = usePermissions()
const { formatDate } = useDateFormatter()

const aggregate = ref(null)
const rirs = ref([])
const rirOptions = computed(() => rirs.value.map(r => ({ value: r.id, label: r.name })))
const loading = ref(false)
const error = ref('')
const formOpen = ref(false)
const id = computed(() => route.params.id)

async function load() {
  loading.value = true
  error.value = ''
  try {
    aggregate.value = (await api.getIpamAggregate(id.value)).data
    loadChildren()
    if (!rirs.value.length) rirs.value = (await api.getIpamRirs()).data || []
  } catch (err) {
    aggregate.value = null
    error.value = apiErrorText(err, t)
  } finally {
    loading.value = false
  }
}

async function remove() {
  if (!window.confirm(t('ipam.aggregates.deleteConfirm', { name: aggregate.value.prefix }))) return
  try {
    await api.deleteIpamAggregate(aggregate.value.id)
    router.push('/ipam/aggregates')
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

const onEdited = () => load()

const children = ref([])
const childTotal = ref(0)
const childLoading = ref(false)
const childRows = ref(50)
const childFirst = ref(0)
const showAvailable = ref(true)
const prefixOpen = ref(false)
const prefixDefaults = ref({})

async function loadChildren() {
  childLoading.value = true
  try {
    const res = await api.getIpamAggregatePrefixes(id.value, { show_available: showAvailable.value, skip: childFirst.value, limit: childRows.value })
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
function addPrefix(block) { prefixDefaults.value = { prefix: block || '' }; prefixOpen.value = true }
function onPrefixSaved() { load() }

watch(id, () => { childFirst.value = 0; load() })
onMounted(load)
</script>

<style scoped>
.title { display: flex; align-items: center; gap: 0.5rem; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.loading { padding: 2rem; text-align: center; }
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
:deep(.free-row) { background: #f0fdf4 !important; }
@media (max-width: 640px) { dl { grid-template-columns: 1fr; } }
</style>
