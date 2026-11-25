<!--
  - DcimRackDetail.vue
  - One rack: its details, how full it is, the front and rear elevation with the devices in it, and the assets assigned to the
  - rack without a unit position.
-->
<template>
  <div class="dcim-page">
    <div class="page-header">
      <div>
        <router-link to="/dcim/racks" class="back"><i class="pi pi-arrow-left"></i> {{ t('dcim.racks.title') }}</router-link>
        <h1>{{ rack ? rack.name : '' }}</h1>
      </div>
      <div class="actions">
        <DcimCsvTools kind="rack-positions" @imported="load" @error="msg => error = msg" />
        <Button v-if="rack && canWrite('dcim')" :label="t('common.actions.edit')" icon="pi pi-pencil" outlined @click="formOpen = true" />
      </div>
    </div>
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>

    <div v-if="rack" class="summary">
      <div class="cell"><span class="label">{{ t('dcim.fields.site') }}</span><span>{{ rack.site_name }}</span></div>
      <div v-if="rack.location_name" class="cell"><span class="label">{{ t('dcim.fields.location') }}</span><span>{{ rack.location_name }}</span></div>
      <div v-if="rack.role_name" class="cell"><span class="label">{{ t('dcim.fields.role') }}</span><span>{{ rack.role_name }}</span></div>
      <div class="cell"><span class="label">{{ t('dcim.fields.status') }}</span><Tag :value="t(`dcim.statuses.${rack.status}`)" :severity="rackStatusSeverity(rack.status)" /></div>
      <div class="cell"><span class="label">{{ t('dcim.fields.uHeight') }}</span><span>{{ rack.u_height }}U · {{ rack.width }}"</span></div>
      <div v-if="rack.facility_id" class="cell"><span class="label">{{ t('dcim.fields.facilityId') }}</span><span>{{ rack.facility_id }}</span></div>
      <div class="cell wide">
        <span class="label">{{ t('dcim.racks.space') }}</span>
        <div class="bar"><div class="fill" :style="{ width: Math.min(utilization, 100) + '%', background: utilizationColor(utilization) }"></div></div>
        <small class="muted">{{ utilization }} % · {{ formatUnits(occupied) }}U / {{ rack.u_height }}U</small>
      </div>
    </div>

    <Message v-for="p in problems" :key="p" severity="warn" :closable="false">{{ p }}</Message>

    <div v-if="loading && !rack" class="loader"><ProgressSpinner style="width: 2rem; height: 2rem" strokeWidth="6" /></div>

    <div v-if="rack" class="layout">
      <div v-for="face in FACES" :key="face" class="face">
        <h3>{{ t(`dcim.faces.${face}`) }}</h3>
        <div class="elevation" :style="{ height: rows(face).length * UNIT + 'px' }">
          <div v-for="(cell, i) in rows(face)" :key="cell.unit" class="unit" :style="{ top: i * UNIT + 'px', height: UNIT + 'px' }">
            <span class="num">{{ cell.unit }}</span>
          </div>
          <router-link v-for="b in blocks(face)" :key="b.key" :to="`/assets/${b.device.id}`" class="device"
                       :class="{ unknown: !b.device.height_known, half: !b.device.full_depth }"
                       :style="{ top: b.index * UNIT + 'px', height: b.span * UNIT - 2 + 'px' }"
                       :title="`${b.device.name} · ${b.device.model || t('dcim.racks.noType')} · ${formatUnits(b.device.height)}U @ ${formatUnits(b.device.position)}`">
            <strong>{{ b.device.name }}</strong>
            <small v-if="b.span > 1 || b.device.model">{{ b.device.model || '' }}</small>
          </router-link>
        </div>
      </div>

      <div class="side">
        <h3>{{ t('dcim.racks.unpositioned') }} <span class="count">{{ unpositioned.length }}</span></h3>
        <p class="hint">{{ t('dcim.racks.unpositionedHint') }}</p>
        <ul v-if="unpositioned.length" class="plain">
          <li v-for="a in unpositioned" :key="a.id"><router-link :to="`/assets/${a.id}`">{{ a.name }}</router-link> <small v-if="a.tag" class="muted">{{ a.tag }}</small></li>
        </ul>
        <p v-else class="muted">{{ t('dcim.racks.noneUnpositioned') }}</p>
        <h3>{{ t('dcim.racks.legend') }}</h3>
        <ul class="plain legend">
          <li><span class="chip"></span>{{ t('dcim.racks.legendFull') }}</li>
          <li><span class="chip half"></span>{{ t('dcim.racks.legendHalf') }}</li>
          <li><span class="chip unknown"></span>{{ t('dcim.racks.legendUnknown') }}</li>
        </ul>
      </div>
    </div>

    <DcimRackForm v-model:visible="formOpen" :rack="rack" :sites="lookups.sites.value" :locations="lookups.locations.value" :roles="lookups.roles.value" @saved="load" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import ProgressSpinner from 'primevue/progressspinner'
import api from '@/api/api'
import DcimCsvTools from '../components/features/dcim/DcimCsvTools.vue'
import DcimRackForm from '../components/forms/DcimRackForm.vue'
import { usePermissions } from '../composables/usePermissions'
import { useDcimLookups, FACES, rackStatusSeverity, utilizationColor, formatUnits } from '../composables/useDcim'
import { apiErrorText } from '../utils/money'

const UNIT = 24 // pixels of one rack unit in the picture

const { t } = useI18n()
const route = useRoute()
const { canWrite } = usePermissions()
const lookups = useDcimLookups()

const data = ref(null)
const loading = ref(false)
const error = ref('')
const formOpen = ref(false)

const rack = computed(() => data.value?.rack || null)
const utilization = computed(() => data.value?.utilization ?? 0)
const occupied = computed(() => data.value?.occupied_u ?? 0)
const problems = computed(() => data.value?.problems || [])
const unpositioned = computed(() => data.value?.unpositioned || [])

const rows = face => data.value?.faces?.[face] || []

// the devices of one face as blocks: the first unit drawn, how many units it spans, and the device
function blocks(face) {
  const cells = rows(face)
  const out = []
  let i = 0
  while (i < cells.length) {
    const id = cells[i].device
    if (!id) { i++; continue }
    let span = 1
    while (i + span < cells.length && cells[i + span].device === id) span++
    out.push({ key: `${face}-${id}-${i}`, index: i, span, device: data.value.devices[id] })
    i += span
  }
  return out
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = (await api.getDcimRackElevation(route.params.id)).data
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    loading.value = false
  }
}

watch(() => route.params.id, id => { if (id) load() })
onMounted(() => { load(); lookups.load() })
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
.page-header h1 { margin: 0.25rem 0 0; }
.back { color: var(--sk-text-muted, #6b7a71); text-decoration: none; font-size: 0.9rem; }
.actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.summary { display: flex; flex-wrap: wrap; gap: 1.25rem 2rem; padding: 0.9rem 1rem; background: #fff; border-radius: 12px; box-shadow: 0 1px 6px rgba(24, 54, 36, 0.08); margin-bottom: 1rem; }
.cell { display: flex; flex-direction: column; gap: 0.2rem; min-width: 6rem; }
.cell.wide { min-width: 14rem; }
.label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--sk-text-muted, #6b7a71); }
.bar { height: 0.5rem; background: #e5ece8; border-radius: 4px; overflow: hidden; }
.fill { height: 100%; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.hint { margin: 0 0 0.5rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.loader { display: flex; justify-content: center; padding: 3rem; }
.layout { display: flex; gap: 1.5rem; flex-wrap: wrap; align-items: flex-start; margin-top: 1rem; }
.face { flex: 0 0 18rem; }
.face h3, .side h3 { margin: 0 0 0.5rem; font-size: 1rem; }
.elevation { position: relative; width: 18rem; background: #f4f7f5; border: 2px solid #4b5d52; border-radius: 4px; }
.unit { position: absolute; left: 0; right: 0; border-bottom: 1px solid #dbe4de; box-sizing: border-box; }
.num { position: absolute; left: 0.3rem; top: 50%; transform: translateY(-50%); font-size: 0.7rem; color: #8a9a90; font-family: ui-monospace, Menlo, Consolas, monospace; }
.device { position: absolute; left: 2rem; right: 0.25rem; margin-top: 1px; padding: 0.15rem 0.5rem; box-sizing: border-box; overflow: hidden; display: flex; flex-direction: column; justify-content: center;
          background: #cfe8d8; border: 1px solid #5d9b78; border-radius: 3px; color: #1f3a2b; text-decoration: none; font-size: 0.8rem; line-height: 1.15; }
.device:hover { background: #b9dcc7; }
.device small { color: #4f6b5a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.device strong { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.device.half { background: #dbe6f5; border-color: #6f8fc4; border-style: dashed; }
.device.unknown { background: #fdf0d5; border-color: #d9a441; }
.side { flex: 1 1 14rem; min-width: 14rem; }
.count { background: #e5ece8; border-radius: 10px; padding: 0 0.5rem; font-size: 0.8rem; margin-left: 0.3rem; }
.plain { list-style: none; margin: 0 0 1rem; padding: 0; display: flex; flex-direction: column; gap: 0.3rem; }
.legend li { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; }
.chip { display: inline-block; width: 1.4rem; height: 0.8rem; background: #cfe8d8; border: 1px solid #5d9b78; border-radius: 2px; }
.chip.half { background: #dbe6f5; border: 1px dashed #6f8fc4; }
.chip.unknown { background: #fdf0d5; border-color: #d9a441; }
</style>
