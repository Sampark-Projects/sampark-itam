<!--
  - DcimCables.vue
  - Cables between interfaces (an asset connection is the cable), the port details of every interface (type, speed, PoE) and the PoE of
  - the switches. Cables with an end missing, or on a port that has several cables, are listed so they can be put right.
-->
<template>
  <div class="dcim-page">
    <div class="page-header"><h1>{{ t('dcim.cables.title') }}</h1></div>
    <p class="hint">{{ t('dcim.cables.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <TabView v-model:activeIndex="tab" class="modern-tabs" @tab-change="onTab">
      <!-- cables -->
      <TabPanel :header="t('dcim.cables.tabs.cables')">
        <div v-if="overview" class="stats">
          <span><strong>{{ overview.cables }}</strong> {{ t('dcim.cables.stats.cables') }}</span>
          <a v-if="overview.incomplete" href="#" class="warn" @click.prevent="quickFilter('incomplete')">{{ t('dcim.cables.stats.incomplete', { n: overview.incomplete }) }}</a>
          <a v-if="overview.interfaces_with_several_cables" href="#" class="warn" @click.prevent="quickFilter('conflict')">{{ t('dcim.cables.stats.conflicts', { n: overview.interfaces_with_several_cables }) }}</a>
          <span v-if="overview.planned">{{ t('dcim.cables.stats.planned', { n: overview.planned }) }}</span>
        </div>
        <div class="toolbar">
          <span class="p-input-icon-left search">
            <i class="pi pi-search" />
            <InputText v-model="cableFilters.search" :placeholder="t('dcim.cables.searchPlaceholder')" class="w-full" @input="debounced(cables)" />
          </span>
          <Dropdown v-model="cableFilters.site_id" :options="lookups.sites.value" optionLabel="label" optionValue="value" showClear filter :placeholder="t('dcim.fields.site')" class="filter" @change="cables.reload" />
          <Dropdown v-model="cableFilters.cable_status" :options="cableStatusOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('dcim.cables.status')" class="filter" @change="cables.reload" />
          <Dropdown v-model="cableFilters.cable_type" :options="cableTypeOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('dcim.cables.type')" class="filter" @change="cables.reload" />
          <label class="check"><Checkbox v-model="cableFilters.incomplete" binary @change="cables.reload" /><span>{{ t('dcim.cables.onlyIncomplete') }}</span></label>
          <label class="check"><Checkbox v-model="cableFilters.conflict" binary @change="cables.reload" /><span>{{ t('dcim.cables.onlyConflict') }}</span></label>
          <span class="spacer"></span>
          <DcimCsvTools kind="cables" @imported="onImported" @error="msg => message = { severity: 'error', text: msg }" />
          <Button v-if="canWrite('dcim')" :label="t('dcim.cables.new')" icon="pi pi-plus" severity="success" @click="openCable(null)" />
        </div>
        <DataTable :value="cables.items.value" :loading="cables.loading.value" dataKey="id" lazy paginator :rows="cables.rows.value" :first="cables.first.value"
                   :totalRecords="cables.total.value" :rowsPerPageOptions="[25, 50, 100]" @page="cables.onPage">
          <template #empty>{{ t('dcim.cables.empty') }}</template>
          <Column :header="t('dcim.cables.endA')">
            <template #body="{ data }"><EndLabel :end="data.local" /></template>
          </Column>
          <Column :header="t('dcim.cables.endB')">
            <template #body="{ data }"><EndLabel :end="data.remote" /></template>
          </Column>
          <Column :header="t('dcim.cables.type')" style="width: 9rem">
            <template #body="{ data }"><span v-if="data.cable_type">{{ t(`dcim.cableTypes.${keyOf(data.cable_type)}`) }}</span></template>
          </Column>
          <Column :header="t('dcim.cables.status')" style="width: 9rem">
            <template #body="{ data }"><Tag :value="t(`dcim.cableStatuses.${data.cable_status}`)" :severity="cableStatusSeverity(data.cable_status)" /></template>
          </Column>
          <Column :header="t('dcim.cables.label')" style="width: 9rem">
            <template #body="{ data }">
              <span v-if="data.cable_color" class="swatch" :style="{ background: data.cable_color }"></span>{{ data.cable_label }}
            </template>
          </Column>
          <Column :header="t('dcim.cables.length')" style="width: 6rem">
            <template #body="{ data }"><span v-if="data.cable_length !== null">{{ data.cable_length }} {{ data.cable_length_unit }}</span></template>
          </Column>
          <Column :header="t('dcim.cables.check')" style="width: 11rem">
            <template #body="{ data }">
              <Tag v-if="!data.complete" :value="t('dcim.cables.incomplete')" severity="warning" />
              <Tag v-if="data.conflict" :value="t('dcim.cables.conflict')" severity="danger" class="ml" v-tooltip.top="t('dcim.cables.conflictHint')" />
            </template>
          </Column>
          <Column v-if="canWrite('dcim')" style="width: 6rem">
            <template #body="{ data }">
              <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openCable(data)" />
              <Button v-if="canDelete('dcim')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeCable(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>

      <!-- interfaces -->
      <TabPanel :header="t('dcim.cables.tabs.interfaces')">
        <p class="hint">{{ t('dcim.ports.hint') }}</p>
        <div class="toolbar">
          <span class="p-input-icon-left search">
            <i class="pi pi-search" />
            <InputText v-model="portFilters.search" :placeholder="t('dcim.ports.searchPlaceholder')" class="w-full" @input="debounced(ports)" />
          </span>
          <Dropdown v-model="portFilters.site_id" :options="lookups.sites.value" optionLabel="label" optionValue="value" showClear filter :placeholder="t('dcim.fields.site')" class="filter" @change="ports.reload" />
          <Dropdown v-model="portFilters.port_type" :options="portTypeOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('dcim.ports.portType')" class="filter" @change="ports.reload" />
          <Dropdown v-model="portFilters.poe_mode" :options="poeModeOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('dcim.ports.poeMode')" class="filter" @change="ports.reload" />
          <Dropdown v-model="portFilters.has_cable" :options="cableChoices" optionLabel="label" optionValue="value" showClear :placeholder="t('dcim.ports.cable')" class="filter" @change="ports.reload" />
          <span class="spacer"></span>
          <DcimCsvTools kind="interfaces" @imported="onImported" @error="msg => message = { severity: 'error', text: msg }" />
        </div>
        <DataTable :value="ports.items.value" :loading="ports.loading.value" dataKey="id" lazy paginator :rows="ports.rows.value" :first="ports.first.value"
                   :totalRecords="ports.total.value" :rowsPerPageOptions="[25, 50, 100]" @page="ports.onPage">
          <template #empty>{{ t('dcim.ports.empty') }}</template>
          <Column :header="t('dcim.cables.asset')">
            <template #body="{ data }"><router-link :to="`/assets/${data.asset_id}`" class="link">{{ data.asset_name }}</router-link></template>
          </Column>
          <Column field="name" :header="t('dcim.cables.port')" style="width: 10rem" />
          <Column :header="t('dcim.ports.portType')" style="width: 9rem">
            <template #body="{ data }"><span v-if="data.port_type">{{ t(`dcim.portTypes.${keyOf(data.port_type)}`) }}</span></template>
          </Column>
          <Column :header="t('dcim.ports.state')" style="width: 8rem">
            <template #body="{ data }">
              <Tag :value="data.enabled ? t('dcim.ports.up') : t('dcim.ports.disabled')" :severity="data.enabled ? 'success' : 'secondary'" />
            </template>
          </Column>
          <Column :header="t('dcim.ports.speed')" style="width: 8rem"><template #body="{ data }">{{ formatSpeed(data.speed_kbps) }}</template></Column>
          <Column :header="t('dcim.ports.poe')" style="width: 11rem">
            <template #body="{ data }">
              <span v-if="data.poe_mode">{{ t(`dcim.poeModes.${data.poe_mode}`) }}<span v-if="data.poe_power_draw_w !== null"> · {{ data.poe_power_draw_w }} W</span></span>
            </template>
          </Column>
          <Column :header="t('dcim.ports.cable')">
            <template #body="{ data }">
              <span v-if="data.cable && data.cable.far_end">→ <router-link :to="`/assets/${data.cable.far_end.asset_id}`" class="link">{{ data.cable.far_end.asset_name }}</router-link> / {{ data.cable.far_end.interface_name }}</span>
              <Tag v-if="data.cable && data.cable.count > 1" :value="t('dcim.cables.conflict')" severity="danger" class="ml" />
              <Button v-if="data.cable" icon="pi pi-share-alt" text rounded size="small" :aria-label="t('dcim.trace.open')" v-tooltip.top="t('dcim.trace.open')" @click="openTrace(data)" />
            </template>
          </Column>
          <Column v-if="canWrite('dcim')" style="width: 4rem">
            <template #body="{ data }">
              <Button icon="pi pi-cog" text rounded size="small" :aria-label="t('dcim.ports.edit')" @click="openPort(data)" />
            </template>
          </Column>
        </DataTable>
      </TabPanel>

      <!-- PoE -->
      <TabPanel :header="t('dcim.cables.tabs.poe')">
        <p class="hint">{{ t('dcim.poe.hint') }}</p>
        <div class="toolbar">
          <span class="p-input-icon-left search">
            <i class="pi pi-search" />
            <InputText v-model="poeFilters.search" :placeholder="t('dcim.poe.searchPlaceholder')" class="w-full" @input="debounced(poe)" />
          </span>
          <Dropdown v-model="poeFilters.site_id" :options="lookups.sites.value" optionLabel="label" optionValue="value" showClear filter :placeholder="t('dcim.fields.site')" class="filter" @change="poe.reload" />
        </div>
        <DataTable :value="poe.items.value" :loading="poe.loading.value" dataKey="asset_id" lazy paginator :rows="poe.rows.value" :first="poe.first.value"
                   :totalRecords="poe.total.value" :rowsPerPageOptions="[25, 50, 100]" @page="poe.onPage">
          <template #empty>{{ t('dcim.poe.empty') }}</template>
          <Column :header="t('dcim.poe.switch')">
            <template #body="{ data }"><router-link :to="`/assets/${data.asset_id}`" class="link"><strong>{{ data.asset_name }}</strong></router-link></template>
          </Column>
          <Column field="site_name" :header="t('dcim.fields.site')" style="width: 10rem" />
          <Column field="pse_ports" :header="t('dcim.poe.poweringPorts')" style="width: 9rem" />
          <Column field="powered_ports" :header="t('dcim.poe.poweredPorts')" style="width: 9rem" />
          <Column :header="t('dcim.poe.draw')" style="width: 9rem"><template #body="{ data }"><strong>{{ data.draw_w }} W</strong></template></Column>
          <Column :header="t('dcim.poe.unknown')" style="width: 12rem">
            <template #body="{ data }"><Tag v-if="data.unknown_draw" :value="t('dcim.poe.unknownDraw', { n: data.unknown_draw })" severity="warning" /></template>
          </Column>
        </DataTable>
      </TabPanel>
    </TabView>

    <DcimCableForm v-model:visible="cableOpen" :cable="editingCable" @saved="onCableSaved" />
    <DcimInterfaceDetails v-model:visible="portOpen" :port="editingPort" @saved="onPortSaved" />
    <DcimCableTrace v-model:visible="traceOpen" :port="tracedPort" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, h } from 'vue'
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
import DcimInterfaceDetails from '../components/features/dcim/DcimInterfaceDetails.vue'
import DcimCableTrace from '../components/features/dcim/DcimCableTrace.vue'
import DcimCableForm from '../components/forms/DcimCableForm.vue'
import { RouterLink } from 'vue-router'
import { usePermissions } from '../composables/usePermissions'
import { useDcimChoices, useDcimLookups, pagedList, cableStatusSeverity, formatSpeed, keyOf } from '../composables/useDcim'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const { cableStatusOptions, cableTypeOptions, portTypeOptions, poeModeOptions } = useDcimChoices()
const lookups = useDcimLookups()

// one end of a cable: the asset (a link) and the port name
const EndLabel = (props) => {
  const end = props.end
  if (!end) return h('span', { class: 'missing' }, t('dcim.cables.missingEnd'))
  return h('span', [h(RouterLink, { to: `/assets/${end.asset_id}`, class: 'link' }, () => end.asset_name), ` / ${end.interface_name}`])
}
EndLabel.props = ['end']

const message = ref(null)
const showError = err => { message.value = { severity: 'error', text: apiErrorText(err, t) } }
const tab = ref(0)
const overview = ref(null)

const cableFilters = reactive({ search: '', site_id: null, cable_status: null, cable_type: null, incomplete: false, conflict: false })
const portFilters = reactive({ search: '', site_id: null, port_type: null, poe_mode: null, has_cable: null })
const poeFilters = reactive({ search: '', site_id: null })
const clean = o => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== null && v !== '' && v !== false).map(([k, v]) => [k, typeof v === 'string' ? v.trim() : v]))

const cables = pagedList(api.getDcimCables, () => clean(cableFilters), showError)
const ports = pagedList(api.getDcimInterfaces, () => ({ ...clean(portFilters), ...(portFilters.has_cable === false ? { has_cable: false } : {}) }), showError)
const poe = pagedList(api.getDcimPoe, () => clean(poeFilters), showError)
const loadedTabs = new Set([0])

const cableChoices = computed(() => [{ value: true, label: t('dcim.ports.withCable') }, { value: false, label: t('dcim.ports.withoutCable') }])

let timer = null
function debounced(list) { clearTimeout(timer); timer = setTimeout(list.reload, 300) }

function onTab(event) {
  const lists = [cables, ports, poe]
  if (!loadedTabs.has(event.index)) { loadedTabs.add(event.index); lists[event.index].load() }
}

function quickFilter(which) {
  cableFilters.incomplete = which === 'incomplete'
  cableFilters.conflict = which === 'conflict'
  cables.reload()
}

async function loadOverview() {
  try { overview.value = (await api.getDcimCableOverview()).data } catch (err) { overview.value = null }
}

const cableOpen = ref(false)
const editingCable = ref(null)
const portOpen = ref(false)
const editingPort = ref(null)

const traceOpen = ref(false)
const tracedPort = ref(null)
function openTrace(row) { tracedPort.value = row; traceOpen.value = true }
function openCable(row) { editingCable.value = row; cableOpen.value = true }
function openPort(row) { editingPort.value = row; portOpen.value = true }
function refreshAll() { cables.load(); loadOverview(); if (loadedTabs.has(1)) ports.load(); if (loadedTabs.has(2)) poe.load() }
function onCableSaved() { message.value = { severity: 'success', text: t('dcim.saved') }; refreshAll() }
function onPortSaved() { message.value = { severity: 'success', text: t('dcim.saved') }; ports.load(); if (loadedTabs.has(2)) poe.load() }
function onImported(summary) { message.value = { severity: 'success', text: t('dcim.csv.done', { created: summary.create, updated: summary.update, skipped: summary.skipped_duplicate + summary.skipped_invalid }) }; refreshAll() }

async function removeCable(row) {
  if (!window.confirm(t('dcim.cables.deleteConfirm'))) return
  try {
    await api.deleteDcimCable(row.id)
    message.value = { severity: 'success', text: t('dcim.deleted') }
    refreshAll()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

// the cable list, its totals and the site dropdown start together and fill as their own answers arrive
onMounted(() => { cables.load(); loadOverview(); lookups.load() })
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.page-header { margin-bottom: 0.5rem; }
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.stats { display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 0.75rem; font-size: 0.9rem; }
.stats .warn { color: #b45309; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.toolbar .spacer { flex: 1; }
.search { flex: 1 1 16rem; max-width: 24rem; }
.filter { min-width: 10rem; }
.check { display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer; font-size: 0.9rem; }
.swatch { display: inline-block; width: 0.8rem; height: 0.8rem; border-radius: 50%; margin-right: 0.4rem; vertical-align: middle; border: 1px solid #cbd5e1; }
.ml { margin-left: 0.3rem; }
.link { color: inherit; }
:deep(.missing) { color: #b45309; font-style: italic; }
</style>
