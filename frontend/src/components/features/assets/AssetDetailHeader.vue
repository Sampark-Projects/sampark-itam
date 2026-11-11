<template>
  <div class="asset-header-flex-modern dcard">
    <div class="asset-header-main">
      <div class="asset-header-top">
        <Button
          :label="t('common.actions.back')"
          icon="pi pi-arrow-left"
          class="p-button-secondary back-btn"
          @click="$emit('back')"
        />
        <h1 class="asset-title">{{ asset.name }}</h1>
      </div>
      <div class="asset-meta">
        <Tag v-if="asset.status?.name" :value="asset.status.name" :style="{ background: asset.status?.color || 'var(--sk-primary)', color: '#fff' }" />
        <span class="chip"><i class="pi pi-tag"></i>{{ asset.asset_type?.name || t('common.strings.na') }}</span>
        <span class="chip purdue-level" v-if="purdueLevelDisplay">
          {{ t('assets.fields.purdueLevel') }}: <strong>{{ purdueLevelDisplay }}</strong>
        </span>
        <span class="chip"><i class="pi pi-building"></i>{{ asset.site?.name || t('common.strings.na') }}</span>
        <span class="chip" v-if="asset.area_name"><i class="pi pi-map-marker"></i>{{ asset.area_name }}</span>
        <CriticalityBadge
          v-if="asset.business_criticality"
          :value="asset.business_criticality"
          :showText="true"
        />
        <Tag
          v-if="totalRiskScore !== null && totalRiskScore !== undefined"
          :value="`${t('assets.fields.riskScore')}: ${totalRiskScore.toFixed(2)} (${riskLevelLabel(totalRiskScore)})`"
          :severity="riskLevelSeverity(totalRiskScore)"
          class="risk-badge"
          v-tooltip.top="riskBreakdown && riskBreakdown.final_score !== totalRiskScore ? `${t('assets.riskBreakdown.baseRiskScore')}: ${riskBreakdown.final_score?.toFixed(2) || '0.00'} + ${t('assets.riskBreakdown.riskFromDependencies')}: ${(totalRiskScore - (riskBreakdown.final_score || 0)).toFixed(2)}` : ''"
        />
        <Tag
          v-else-if="riskBreakdown && riskBreakdown.final_score !== null"
          :value="`${t('assets.fields.riskScore')}: ${riskBreakdown.final_score} (${riskLevelLabel(riskBreakdown.final_score)})`"
          :severity="riskLevelSeverity(riskBreakdown.final_score)"
          class="risk-badge"
        />
      </div>
    </div>
    <div class="asset-header-actions-modern">
      <Button 
        v-if="canWrite('assets')"
        :label="t('common.actions.edit')" 
        icon="pi pi-pencil" 
        severity="warning"
        @click="$emit('edit')" 
      />
      <Button 
        :label="t('common.actions.print')" 
        icon="pi pi-print" 
        severity="success"
        @click="$emit('print')" 
      />
      <Button 
        v-if="hasFloorplan && canWrite('assets')"
        :label="t('assets.strings.floorplan')" 
        icon="pi pi-map" 
        severity="info"
        @click="showPositioningDialog = true" 
      />
    </div>
  </div>
  
  <!-- Floorplan Positioning Dialog -->
  <FloorplanPositioningDialog
    v-model:visible="showPositioningDialog"
    :assetId="asset.id"
    :locationId="asset.location?.id || null"
    @position-saved="onAssetPositionSaved"
  />
</template>

<script setup>
import { toRefs } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Dialog from 'primevue/dialog'
import CriticalityBadge from '../../common/CriticalityBadge.vue'
import FloorplanPositioningDialog from './widgets/FloorplanPositioningDialog.vue'

import { computed, ref } from 'vue'
import { useRiskLabels } from '@/composables/useRiskLabels'

const props = defineProps({
  asset: { type: Object, required: true },
  riskBreakdown: { type: Object, default: null },
  totalRiskScore: { type: Number, default: null },
  canWrite: { type: Function, required: true }
})

const { t } = useI18n()
const { riskLevelLabel, riskLevelSeverity } = useRiskLabels()
const emit = defineEmits(['back', 'edit', 'print', 'position-saved'])

// State
const showPositioningDialog = ref(false)

// Purdue level dall'asset_type (esplicito in testata)
const purdueLevelDisplay = computed(() => {
  const level = props.asset?.asset_type?.purdue_level
  if (level === null || level === undefined) return null
  const key = level === 1.5 ? 'level1_5' : `level${level}`
  return t('assettypes.' + key)
})

// Computed properties
const hasFloorplan = computed(() => !!(props.asset?.location?.floorplan?.id))

// Methods
function onAssetPositionSaved({ id, map_x, map_y }) {
  // Emetti un evento per aggiornare l'asset nel componente padre
  emit('position-saved', { id, map_x, map_y })
}
</script>

<style scoped>
.asset-header-flex-modern {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 1.5rem;
  margin-bottom: 1.25rem;
  padding: 1.1rem 1.25rem;
  align-items: center;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.2rem 0.7rem;
  border-radius: 999px;
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--sk-text);
  background: var(--sk-table-head);
  border: 1px solid var(--sk-border);
}
.chip i { font-size: 0.8rem; color: var(--sk-primary); }
.asset-header-main {
  flex: 1;
  min-width: 0;
}
.asset-header-top {
  display: flex;
  align-items: center;
  gap: 0.9rem;
}
.asset-title {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 700;
  line-height: 1.2;
  color: var(--sk-heading);
  word-break: break-word;
}
.asset-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin: 0.75rem 0 0;
}
.purdue-level {
  color: var(--sk-text-muted);
}
.purdue-level strong {
  color: var(--p-text-color, inherit);
}
.criticality-badge, .risk-badge {
  font-size: 0.9em;
}
.asset-header-actions-modern {
  display: flex;
  flex-direction: row;
  gap: 0.5rem;
  align-items: flex-end;
  flex-wrap: wrap;
}
.back-btn {
  flex: 0 0 auto;
}
@media (max-width: 700px) {
  .asset-header-flex-modern {
    flex-direction: column;
    align-items: stretch;
    gap: 1rem;
  }
  .asset-header-actions-modern {
    justify-content: flex-start;
    align-items: flex-start;
    flex-direction: column;
  }
}
</style> 