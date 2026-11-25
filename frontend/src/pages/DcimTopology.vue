<!--
  - DcimTopology.vue
  - The physical topology drawn from the cables: every complete cable joins two assets (a switch port to a PLC, camera or server
  - port). Edges show both port names, the PoE they carry and the cable status; nodes say how many ports have no cable.
-->
<template>
  <div class="dcim-page">
    <div class="page-header"><h1>{{ t('dcim.topology.title') }}</h1></div>
    <p class="hint">{{ t('dcim.topology.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>
    <Message v-if="data && data.truncated" severity="warn" :closable="false">{{ t('dcim.topology.truncated') }}</Message>

    <div class="toolbar">
      <Dropdown v-model="siteId" :options="lookups.sites.value" optionLabel="label" optionValue="value" showClear filter :placeholder="t('dcim.fields.site')" class="filter" @change="load" />
      <label class="check"><Checkbox v-model="poeOnly" binary @change="render" /><span>{{ t('dcim.topology.poeOnly') }}</span></label>
      <label class="check"><Checkbox v-model="showPlanned" binary @change="render" /><span>{{ t('dcim.topology.showPlanned') }}</span></label>
      <Button icon="pi pi-expand" text rounded :aria-label="t('dcim.topology.fit')" @click="fit" />
      <span class="spacer"></span>
      <span v-if="data" class="stats">
        <span><strong>{{ data.summary.assets }}</strong> {{ t('dcim.topology.assets') }}</span>
        <span><strong>{{ data.summary.cables }}</strong> {{ t('dcim.topology.cables') }}</span>
        <span v-if="data.summary.poe_cables">⚡ <strong>{{ data.summary.poe_draw_w }} W</strong> · {{ t('dcim.topology.poeCables', { n: data.summary.poe_cables }) }}<span v-if="data.summary.poe_unknown_draw"> · {{ t('dcim.topology.poeUnknown', { n: data.summary.poe_unknown_draw }) }}</span></span>
      </span>
    </div>

    <div class="legend">
      <span><i class="line connected"></i>{{ t('dcim.cableStatuses.connected') }}</span>
      <span><i class="line planned"></i>{{ t('dcim.cableStatuses.planned') }}</span>
      <span><i class="line decommissioning"></i>{{ t('dcim.cableStatuses.decommissioning') }}</span>
      <span><i class="line poe"></i>PoE</span>
    </div>

    <ProgressSpinner v-if="loading" class="spinner" />
    <p v-else-if="data && !data.nodes.length" class="empty">{{ t('dcim.topology.empty') }}</p>
    <div v-show="data && data.nodes.length" ref="container" class="topology"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Network } from 'vis-network/standalone/esm/vis-network'
import Dropdown from 'primevue/dropdown'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import Message from 'primevue/message'
import ProgressSpinner from 'primevue/progressspinner'
import api from '@/api/api'
import { useDcimLookups, formatUnits } from '../composables/useDcim'
import { apiErrorText } from '../utils/money'

const { t } = useI18n()
const router = useRouter()
const lookups = useDcimLookups()

const container = ref(null)
const data = ref(null)
const loading = ref(false)
const message = ref(null)
const siteId = ref(null)
const poeOnly = ref(false)
const showPlanned = ref(true)
let network = null
let request = 0

const EDGE_STYLE = {
  connected: { color: '#2196f3', dashes: false },
  planned: { color: '#9e9e9e', dashes: true },
  decommissioning: { color: '#fb8c00', dashes: [4, 4] }
}
const POE_COLOR = '#f59e0b'

async function load() {
  const mine = ++request
  loading.value = true
  try {
    const res = await api.getDcimTopology(siteId.value ? { site_id: siteId.value } : {})
    if (mine !== request) return
    data.value = res.data
    loading.value = false
    // the container is hidden while loading: draw after it is shown
    setTimeout(render, 0)
  } catch (err) {
    if (mine === request) { message.value = { severity: 'error', text: apiErrorText(err, t) }; loading.value = false }
  }
}

function nodeTitle(n) {
  const lines = [n.name, n.asset_type, n.site_name, n.rack_name ? `${t('dcim.fields.rack')} ${n.rack_name}${n.rack_position != null ? ` · U${formatUnits(n.rack_position)}` : ''}` : '']
  lines.push(t('dcim.topology.ports', { total: n.ports, free: n.free_ports }))
  if (n.free_port_names.length) lines.push(`${t('dcim.topology.freePorts')}: ${n.free_port_names.join(', ')}${n.free_ports > n.free_port_names.length ? ' …' : ''}`)
  return lines.filter(Boolean).join('\n')
}

function render() {
  if (!container.value || !data.value) return
  const nameOf = Object.fromEntries(data.value.nodes.map(n => [n.id, n.name]))
  const edges = data.value.edges.filter(e => (!poeOnly.value || e.poe) && (showPlanned.value || e.cable_status !== 'planned'))
  const used = new Set(edges.flatMap(e => [e.a.asset_id, e.b.asset_id]))
  const nodes = data.value.nodes.filter(n => used.has(n.id) || (!poeOnly.value && showPlanned.value)).map(n => ({
    id: n.id,
    label: [n.name, n.rack_name ? `${n.rack_name}${n.rack_position != null ? ` U${formatUnits(n.rack_position)}` : ''}` : '', n.free_ports ? `+${n.free_ports} ${t('dcim.topology.free')}` : ''].filter(Boolean).join('\n'),
    title: nodeTitle(n), shape: 'box', margin: 8,
    color: n.outside_site ? { background: '#f3f4f6', border: '#9ca3af' } : /switch/i.test(n.asset_type || '') ? { background: '#d1fae5', border: '#10b981' } : { background: '#e3eaff', border: '#6b8cff' },
    font: { size: 13 }
  }))
  const visEdges = edges.map(e => {
    const style = EDGE_STYLE[e.cable_status] || EDGE_STYLE.connected
    const label = `${e.a.interface_name} ↔ ${e.b.interface_name}${e.poe ? `\n⚡ ${e.poe.draw_w != null ? `${e.poe.draw_w} W` : 'PoE'}` : ''}`
    const detail = [e.cable_type, e.cable_label, e.cable_length != null ? `${e.cable_length} ${e.cable_length_unit || ''}`.trim() : '', e.cable_status !== 'connected' ? t(`dcim.cableStatuses.${e.cable_status}`) : '']
    return {
      id: e.id, from: e.a.asset_id, to: e.b.asset_id, label,
      title: [`${nameOf[e.a.asset_id]} / ${e.a.interface_name}  ↔  ${nameOf[e.b.asset_id]} / ${e.b.interface_name}`, detail.filter(Boolean).join(' · ')].filter(Boolean).join('\n'),
      color: { color: e.cable_color || (e.poe ? POE_COLOR : style.color) }, dashes: style.dashes, width: e.poe ? 3 : 2,
      font: { size: 10, align: 'middle', multi: false }, smooth: { type: 'dynamic' }
    }
  })
  if (network) network.destroy()
  network = new Network(container.value, { nodes, edges: visEdges }, {
    nodes: { shape: 'box' },
    physics: { enabled: true, barnesHut: { gravitationalConstant: -25000, springLength: 180, springConstant: 0.04 }, stabilization: { iterations: 600 } },
    interaction: { hover: true, tooltipDelay: 200 }, manipulation: { enabled: false }
  })
  network.on('doubleClick', params => { if (params.nodes.length) router.push(`/assets/${params.nodes[0]}`) })
  setTimeout(fit, 400)
}

function fit() { if (network) network.fit() }

onMounted(() => { load(); lookups.load() })
onBeforeUnmount(() => { request++; if (network) { network.destroy(); network = null } })
</script>

<style scoped>
.page-header { margin-bottom: 0.5rem; }
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.5rem; flex-wrap: wrap; }
.toolbar .spacer { flex: 1; }
.filter { min-width: 12rem; }
.check { display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer; font-size: 0.9rem; }
.stats { display: inline-flex; gap: 1.25rem; font-size: 0.9rem; flex-wrap: wrap; }
.legend { display: flex; gap: 1.25rem; font-size: 0.82rem; margin-bottom: 0.5rem; color: var(--sk-text-muted, #6b7a71); }
.legend .line { display: inline-block; width: 1.6rem; height: 0; border-top: 3px solid #2196f3; margin-right: 0.4rem; vertical-align: middle; }
.legend .planned { border-top: 3px dashed #9e9e9e; }
.legend .decommissioning { border-top: 3px dashed #fb8c00; }
.legend .poe { border-top-color: #f59e0b; }
.topology { height: 68vh; min-height: 24rem; border: 1px solid var(--sk-border, #d7e0da); border-radius: 8px; background: var(--sk-surface, #fff); }
.empty { color: var(--sk-text-muted, #6b7a71); padding: 1rem 0; }
.spinner { display: block; margin: 2rem auto; }
</style>
