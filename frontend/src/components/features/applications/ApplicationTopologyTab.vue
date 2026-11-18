<!--
  - ApplicationTopologyTab.vue
  - Connection diagram of one application: end users, URL, load balancer, servers, databases and connected
  - systems, drawn top to bottom. Recorded asset connections are solid; role-based links are dashed.
-->
<template>
  <div>
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="toolbar">
      <label class="check">
        <Checkbox v-model="showInferred" binary @change="load" />
        <span>{{ t('applications.topology.showInferred') }}</span>
      </label>
      <span class="spacer"></span>
      <Button icon="pi pi-search-plus" text rounded size="small" :aria-label="t('applications.topology.zoomIn')" @click="zoom(1.2)" />
      <Button icon="pi pi-search-minus" text rounded size="small" :aria-label="t('applications.topology.zoomOut')" @click="zoom(1 / 1.2)" />
      <Button icon="pi pi-window-maximize" text rounded size="small" :aria-label="t('applications.topology.fit')" @click="fit" />
      <Button icon="pi pi-refresh" text rounded size="small" :loading="loading" :aria-label="t('applications.topology.refresh')" @click="load" />
      <Button icon="pi pi-image" :label="t('applications.topology.export')" size="small" outlined :disabled="!graph || !graph.nodes.length" @click="exportImage" />
    </div>

    <div v-if="loading && !graph" class="loading"><i class="pi pi-spin pi-spinner"></i></div>
    <p v-else-if="graph && !graph.nodes.length" class="muted">{{ t('applications.topology.empty') }}</p>
    <template v-else-if="graph">
      <div ref="container" class="canvas"></div>
      <div class="legend">
        <span><i class="swatch solid"></i>{{ t('applications.topology.legendRecorded') }} ({{ graph.summary.recorded_connections }})</span>
        <span v-if="showInferred"><i class="swatch dashed"></i>{{ t('applications.topology.legendInferred') }} ({{ graph.summary.inferred_links }})</span>
        <span><i class="swatch warn"></i>{{ t('applications.topology.legendVulns') }}</span>
      </div>
      <p v-if="!graph.summary.recorded_connections" class="muted">{{ t('applications.topology.noRecorded') }}</p>
    </template>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { Network } from 'vis-network/standalone/esm/vis-network'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import Message from 'primevue/message'
import api from '@/api/api'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({ applicationId: { type: String, required: true } })
const { t } = useI18n()
const router = useRouter()

const graph = ref(null)
const loading = ref(false)
const error = ref('')
const showInferred = ref(true)
const container = ref(null)
let network = null

const STYLE = {  // fill, border
  users: ['#eef2f7', '#94a3b8'], url: ['#e0f2fe', '#0284c7'], integration: ['#f3e8ff', '#9333ea'],
  load_balancer: ['#dcfce7', '#16a34a'], web: ['#dbeafe', '#2563eb'], application: ['#dbeafe', '#2563eb'],
  database: ['#fef3c7', '#d97706'], cache: ['#fef3c7', '#d97706'], queue: ['#fef3c7', '#d97706'], storage: ['#fef3c7', '#d97706'], other: ['#f1f5f9', '#64748b']
}
const EDGE_COLOR = { connection: '#334155', inferred: '#94a3b8', derived: '#0284c7', integration: '#9333ea' }

function nodeLabel(n) {
  const lines = [n.label, ...(n.lines || [])]
  if (n.vulns && (n.vulns.critical || n.vulns.high)) {
    const parts = []
    if (n.vulns.critical) parts.push(t('applications.topology.critical', { n: n.vulns.critical }))
    if (n.vulns.high) parts.push(t('applications.topology.high', { n: n.vulns.high }))
    lines.push(`[!] ${parts.join(', ')}`)
  }
  return lines.join('\n')
}

function toVis(g) {
  const nodes = g.nodes.map(n => {
    const [fill, border] = STYLE[n.kind === 'asset' ? n.role : n.kind] || STYLE.other
    const critical = n.vulns && n.vulns.critical
    const high = n.vulns && n.vulns.high
    return {
      id: n.id, label: nodeLabel(n), level: n.level, shape: n.kind === 'users' ? 'ellipse' : 'box',
      color: { background: fill, border: critical ? '#dc2626' : high ? '#ea580c' : border, highlight: { background: fill, border } },
      borderWidth: critical || high ? 3 : 1.5, margin: 10, font: { size: 13, color: '#0f172a', multi: false },
      title: n.kind === 'asset' ? `${t(`applications.roles.${n.role}`)}${n.environment ? ' · ' + t(`applications.environments.${n.environment}`) : ''}` : undefined,
      assetId: n.asset_id
    }
  })
  const edges = g.edges.map(e => ({
    id: e.id, from: e.from, to: e.to, label: e.label || '', arrows: e.both ? 'to, from' : 'to', dashes: e.kind === 'inferred',
    color: { color: EDGE_COLOR[e.kind] || '#64748b' }, width: e.kind === 'connection' ? 2 : 1.5,
    font: { size: 11, align: 'horizontal', background: '#ffffff', strokeWidth: 0 }, smooth: { type: 'cubicBezier', forceDirection: 'vertical', roundness: 0.4 }
  }))
  return { nodes, edges }
}

async function draw() {
  await nextTick()
  if (network) { network.destroy(); network = null }
  if (!container.value || !graph.value || !graph.value.nodes.length) return
  network = new Network(container.value, toVis(graph.value), {
    layout: { hierarchical: { enabled: true, direction: 'UD', sortMethod: 'directed', levelSeparation: 120, nodeSpacing: 220, treeSpacing: 240 } },
    physics: { enabled: false },
    interaction: { hover: true, tooltipDelay: 200, zoomView: true, dragView: true, dragNodes: true },
    nodes: { shape: 'box' }
  })
  network.on('doubleClick', params => {
    const node = params.nodes.length ? graph.value.nodes.find(n => n.id === params.nodes[0]) : null
    if (node && node.asset_id) router.push(`/assets/${node.asset_id}`)
  })
  setTimeout(() => network && network.fit(), 100)
}

let request = 0
async function load() {
  const mine = ++request
  loading.value = true
  error.value = ''
  try {
    const res = await api.getApplicationTopology(props.applicationId, showInferred.value)
    if (mine !== request) return
    graph.value = res.data
    await draw()
  } catch (err) {
    if (mine === request) error.value = apiErrorText(err, t)
  } finally {
    if (mine === request) loading.value = false
  }
}

function zoom(factor) {
  if (network) network.moveTo({ scale: network.getScale() * factor })
}

function fit() {
  if (network) network.fit()
}

function exportImage() {
  const canvas = container.value && container.value.querySelector('canvas')
  if (!canvas) return
  const out = document.createElement('canvas')
  out.width = canvas.width
  out.height = canvas.height
  const ctx = out.getContext('2d')
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, out.width, out.height)
  ctx.drawImage(canvas, 0, 0)
  const a = document.createElement('a')
  a.href = out.toDataURL('image/png')
  a.download = 'application-topology.png'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

onMounted(load)
onBeforeUnmount(() => { if (network) { network.destroy(); network = null } })
</script>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
.toolbar .spacer { flex: 1; }
.check { display: inline-flex; align-items: center; gap: 0.5rem; cursor: pointer; }
.loading { padding: 2rem; text-align: center; }
.canvas { height: clamp(34rem, 72vh, 56rem); border: 1px solid var(--sk-border, #e1e7e3); border-radius: 8px; background: #fff; }
.legend { display: flex; gap: 1.25rem; flex-wrap: wrap; margin-top: 0.6rem; font-size: 0.85rem; color: var(--sk-text-muted, #6b7a71); }
.swatch { display: inline-block; width: 1.6rem; height: 0; border-top: 2px solid #334155; margin-right: 0.4rem; vertical-align: middle; }
.swatch.dashed { border-top: 2px dashed #94a3b8; }
.swatch.warn { width: 0.8rem; height: 0.8rem; border: 3px solid #ea580c; border-radius: 2px; }
.muted { color: var(--sk-text-muted, #6b7a71); }
</style>
