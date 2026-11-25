<!--
  - DcimMacs.vue
  - The MAC addresses of the interfaces next to their IP addresses (several MACs per interface; a MAC that is on more than one
  - interface is flagged), and the Purdue report: is the address of an asset in a prefix of its own Purdue level.
-->
<template>
  <div class="dcim-page">
    <div class="page-header"><h1>{{ t('dcim.macs.page.title') }}</h1></div>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <TabView v-model:activeIndex="tab" class="modern-tabs" @tab-change="onTab">
      <!-- MAC to IP -->
      <TabPanel :header="t('dcim.macs.page.tabs.bindings')">
        <p class="hint">{{ t('dcim.macs.page.bindingsHint') }}</p>
        <div v-if="overview" class="stats">
          <span><strong>{{ overview.macs }}</strong> {{ t('dcim.macs.page.stats.macs') }}</span>
          <span v-if="overview.interfaces_with_several">{{ t('dcim.macs.page.stats.several', { n: overview.interfaces_with_several }) }}</span>
          <a v-if="overview.duplicate_macs" href="#" class="warn" @click.prevent="quick('duplicate', true)">{{ t('dcim.macs.page.stats.duplicates', { n: overview.duplicate_macs }) }}</a>
          <a v-if="overview.without_address" href="#" class="warn" @click.prevent="quick('has_ip', false)">{{ t('dcim.macs.page.stats.noAddress', { n: overview.without_address }) }}</a>
        </div>
        <div class="toolbar">
          <span class="p-input-icon-left search">
            <i class="pi pi-search" />
            <InputText v-model="bindingFilters.search" :placeholder="t('dcim.macs.page.searchPlaceholder')" class="w-full" @input="debounced(bindings)" />
          </span>
          <Dropdown v-model="bindingFilters.site_id" :options="lookups.sites.value" optionLabel="label" optionValue="value" showClear filter :placeholder="t('dcim.fields.site')" class="filter" @change="bindings.reload" />
          <Dropdown v-model="bindingFilters.has_ip" :options="addressChoices" optionLabel="label" optionValue="value" showClear :placeholder="t('dcim.macs.page.address')" class="filter" @change="bindings.reload" />
          <label class="check"><Checkbox v-model="bindingFilters.duplicate" binary @change="bindings.reload" /><span>{{ t('dcim.macs.page.onlyDuplicates') }}</span></label>
          <label class="check"><Checkbox v-model="bindingFilters.primary_only" binary @change="bindings.reload" /><span>{{ t('dcim.macs.page.onlyPrimary') }}</span></label>
          <span class="spacer"></span>
          <DcimCsvTools kind="mac-bindings" export-only :export-label="t('dcim.macs.page.exportView')" @error="msg => message = { severity: 'error', text: msg }" />
          <DcimCsvTools kind="mac-addresses" :export-label="t('dcim.macs.page.exportMacs')" @imported="onImported" @error="msg => message = { severity: 'error', text: msg }" />
        </div>
        <DataTable :value="bindings.items.value" :loading="bindings.loading.value" dataKey="id" lazy paginator :rows="bindings.rows.value" :first="bindings.first.value"
                   :totalRecords="bindings.total.value" :rowsPerPageOptions="[25, 50, 100]" @page="bindings.onPage">
          <template #empty>{{ t('dcim.macs.page.empty') }}</template>
          <Column :header="t('dcim.macs.mac')" style="width: 15rem">
            <template #body="{ data }">
              <span class="mono">{{ data.mac_address }}</span>
              <Tag v-if="data.is_primary" :value="t('dcim.macs.primary')" severity="success" class="ml" />
              <Tag v-if="data.duplicate" :value="t('dcim.macs.page.duplicate')" severity="danger" class="ml" v-tooltip.top="duplicateText(data)" />
            </template>
          </Column>
          <Column :header="t('dcim.cables.asset')">
            <template #body="{ data }"><router-link :to="`/assets/${data.asset_id}`" class="link">{{ data.asset_name }}</router-link></template>
          </Column>
          <Column field="interface_name" :header="t('dcim.cables.port')" style="width: 9rem" />
          <Column :header="t('dcim.macs.page.addresses')">
            <template #body="{ data }">
              <template v-if="data.addresses.length">
                <router-link v-for="a in data.addresses" :key="a.id" to="/ipam/ip-addresses" class="chip mono" :title="[a.status, a.dns_name].filter(Boolean).join(' · ')">
                  {{ a.address }}<span v-if="a.vrf_name" class="vrf"> · {{ a.vrf_name }}</span>
                </router-link>
              </template>
              <span v-else-if="data.legacy_ip" class="mono legacy" v-tooltip.top="t('dcim.macs.page.legacyHint')">{{ data.legacy_ip }}</span>
              <span v-else class="muted">{{ t('common.strings.na') }}</span>
            </template>
          </Column>
          <Column field="site_name" :header="t('dcim.fields.site')" style="width: 10rem" />
          <Column field="description" :header="t('dcim.fields.description')" />
        </DataTable>
      </TabPanel>

      <!-- Purdue -->
      <TabPanel :header="t('dcim.macs.page.tabs.purdue')">
        <p class="hint">{{ t('dcim.macs.page.purdueHint') }}</p>
        <Message v-if="summary && !summary.prefixes_with_level" severity="info" :closable="false">
          {{ t('dcim.macs.page.noLevels') }}
          <Button v-if="canWrite('dcim') && summary.missing_roles.length" :label="t('dcim.macs.page.createRoles')" icon="pi pi-plus" size="small" class="ml" :loading="creatingRoles" @click="createRoles" />
        </Message>
        <div v-else-if="summary && summary.missing_roles.length && canWrite('dcim')" class="stats">
          <span class="muted">{{ t('dcim.macs.page.missingRoles', { names: summary.missing_roles.join(', ') }) }}</span>
          <Button :label="t('dcim.macs.page.createRoles')" icon="pi pi-plus" size="small" text :loading="creatingRoles" @click="createRoles" />
        </div>
        <div v-if="summary" class="stats">
          <a v-for="r in RESULTS" :key="r" href="#" class="result-count" :class="{ active: purdueFilters.result === r }" @click.prevent="toggleResult(r)">
            <Tag :value="summary[r]" :severity="resultSeverity(r)" /> {{ t(`dcim.macs.results.${r}`) }}
          </a>
        </div>
        <div class="toolbar">
          <span class="p-input-icon-left search">
            <i class="pi pi-search" />
            <InputText v-model="purdueFilters.search" :placeholder="t('dcim.macs.page.purdueSearch')" class="w-full" @input="debounced(purdue)" />
          </span>
          <Dropdown v-model="purdueFilters.site_id" :options="lookups.sites.value" optionLabel="label" optionValue="value" showClear filter :placeholder="t('dcim.fields.site')" class="filter" @change="purdue.reload" />
          <Dropdown v-model="purdueFilters.result" :options="resultOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('dcim.macs.page.result')" class="filter" @change="purdue.reload" />
        </div>
        <DataTable :value="purdue.items.value" :loading="purdue.loading.value" dataKey="key" lazy paginator :rows="purdue.rows.value" :first="purdue.first.value"
                   :totalRecords="purdue.total.value" :rowsPerPageOptions="[25, 50, 100]" @page="purdue.onPage">
          <template #empty>{{ t('dcim.macs.page.purdueEmpty') }}</template>
          <Column :header="t('dcim.cables.asset')">
            <template #body="{ data }">
              <router-link :to="`/assets/${data.asset_id}`" class="link">{{ data.asset_name }}</router-link>
              <small v-if="data.asset_type" class="muted block">{{ data.asset_type }}</small>
            </template>
          </Column>
          <Column field="interface_name" :header="t('dcim.cables.port')" style="width: 8rem" />
          <Column :header="t('dcim.macs.page.address')">
            <template #body="{ data }"><span class="mono">{{ data.address }}</span><small v-if="data.vrf_name" class="muted block">{{ data.vrf_name }}</small></template>
          </Column>
          <Column :header="t('dcim.macs.page.prefix')">
            <template #body="{ data }">
              <span v-if="data.prefix" class="mono">{{ data.prefix }}</span>
              <small v-if="data.prefix_role" class="muted block">{{ data.prefix_role }}</small>
            </template>
          </Column>
          <Column :header="t('dcim.macs.page.assetLevel')" style="width: 8rem"><template #body="{ data }">{{ level(data.asset_level) }}</template></Column>
          <Column :header="t('dcim.macs.page.prefixLevel')" style="width: 8rem"><template #body="{ data }">{{ level(data.prefix_level) }}</template></Column>
          <Column :header="t('dcim.macs.page.result')" style="width: 14rem">
            <template #body="{ data }"><Tag :value="t(`dcim.macs.results.${data.result}`)" :severity="resultSeverity(data.result)" /></template>
          </Column>
          <Column field="site_name" :header="t('dcim.fields.site')" style="width: 9rem" />
        </DataTable>
      </TabPanel>
    </TabView>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import InputText from 'primevue/inputtext'
import Dropdown from 'primevue/dropdown'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import DcimCsvTools from '../components/features/dcim/DcimCsvTools.vue'
import { usePermissions } from '../composables/usePermissions'
import { useDcimLookups, pagedList } from '../composables/useDcim'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const { canWrite } = usePermissions()
const lookups = useDcimLookups()

const RESULTS = ['mismatch', 'match', 'asset_no_level', 'prefix_no_level', 'no_prefix']
const message = ref(null)
const showError = err => { message.value = { severity: 'error', text: apiErrorText(err, t) } }
const tab = ref(0)
const overview = ref(null)

const bindingFilters = reactive({ search: '', site_id: null, has_ip: null, duplicate: false, primary_only: false })
const purdueFilters = reactive({ search: '', site_id: null, result: null })
// false and empty values are not sent, except "without an address", which is a real choice
const clean = o => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== null && v !== '' && v !== false).map(([k, v]) => [k, typeof v === 'string' ? v.trim() : v]))

const bindings = pagedList(api.getDcimMacBindings, () => ({ ...clean(bindingFilters), ...(bindingFilters.has_ip === false ? { has_ip: false } : {}) }), showError)
// the Purdue report keys its rows by asset, port and address (an address can sit on several ports)
const purdue = pagedList(params => api.getDcimPurdueReport(params).then(res => ({ data: { ...res.data, items: (res.data.items || []).map((i, n) => ({ ...i, key: `${i.asset_id}|${i.interface_name}|${i.address}|${n}` })) } })),
  () => clean(purdueFilters), showError)
const summary = computed(() => purdue.extra.value?.summary || null)
const loadedTabs = new Set([0])

const addressChoices = computed(() => [{ value: true, label: t('dcim.macs.page.withAddress') }, { value: false, label: t('dcim.macs.page.withoutAddress') }])
const resultOptions = computed(() => RESULTS.map(r => ({ value: r, label: t(`dcim.macs.results.${r}`) })))
const resultSeverity = r => ({ mismatch: 'danger', match: 'success', asset_no_level: 'warning', prefix_no_level: 'warning', no_prefix: 'secondary' }[r] || 'secondary')
const level = v => (v === null || v === undefined ? '—' : `L${Number(v)}`)
const duplicateText = row => t('dcim.macs.page.duplicateWith', { list: row.duplicate_with.map(d => `${d.asset_name} / ${d.interface_name}`).join(', ') })

let timer = null
function debounced(list) { clearTimeout(timer); timer = setTimeout(list.reload, 300) }

function onTab(event) {
  if (!loadedTabs.has(event.index)) { loadedTabs.add(event.index); [bindings, purdue][event.index].load() }
}

function quick(key, value) {
  bindingFilters.duplicate = key === 'duplicate' && value
  bindingFilters.has_ip = key === 'has_ip' ? value : null
  bindings.reload()
}

function toggleResult(r) {
  purdueFilters.result = purdueFilters.result === r ? null : r
  purdue.reload()
}

async function loadOverview() {
  try { overview.value = (await api.getDcimMacOverview()).data } catch (err) { overview.value = null }
}

function onImported(s) {
  message.value = { severity: 'success', text: t('dcim.csv.done', { created: s.create, updated: s.update, skipped: s.skipped_duplicate + s.skipped_invalid }) }
  bindings.load()
  loadOverview()
}

const creatingRoles = ref(false)
async function createRoles() {
  creatingRoles.value = true
  try {
    const res = await api.createDcimPurdueRoles()
    message.value = { severity: 'success', text: t('dcim.macs.page.rolesCreated', { n: res.data.created.length }) }
    purdue.load()
  } catch (err) {
    showError(err)
  } finally {
    creatingRoles.value = false
  }
}

onMounted(() => { bindings.load(); loadOverview(); lookups.load() })
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.page-header { margin-bottom: 0.5rem; }
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.stats { display: flex; gap: 1.5rem; flex-wrap: wrap; align-items: center; margin-bottom: 0.75rem; font-size: 0.9rem; }
.stats .warn { color: #b45309; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.toolbar .spacer { flex: 1; }
.search { flex: 1 1 16rem; max-width: 24rem; }
.filter { min-width: 10rem; }
.check { display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer; font-size: 0.9rem; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.ml { margin-left: 0.4rem; }
.link { color: inherit; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.block { display: block; }
.chip { display: inline-block; margin: 0 0.35rem 0.2rem 0; padding: 0.05rem 0.45rem; border: 1px solid var(--sk-border, #d7e0da); border-radius: 999px; font-size: 0.82rem; text-decoration: none; color: inherit; }
.vrf { color: var(--sk-text-muted, #6b7a71); }
.legacy { font-size: 0.85rem; }
.result-count { display: inline-flex; align-items: center; gap: 0.4rem; text-decoration: none; color: inherit; padding: 0.15rem 0.5rem; border-radius: 6px; }
.result-count.active { background: var(--sk-table-head, #eef3ef); font-weight: 600; }
</style>
