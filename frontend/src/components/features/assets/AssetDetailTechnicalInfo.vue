<template>
  <div class="detail-stack">
    <section class="dcard">
      <h3 class="dcard-title">
        <span class="dcard-icon"><i class="pi pi-cog"></i></span>{{ t('assets.strings.technicalInfo') }}
      </h3>
      <dl class="dfields">
        <div class="dfield">
          <dt>{{ t('assets.fields.firmwareVersion') }}</dt>
          <dd :class="{ 'is-empty': !asset.firmware_version }">{{ asset.firmware_version || t('common.strings.na') }}</dd>
        </div>
        <div class="dfield">
          <dt>{{ t('assets.fields.installationDate') }}</dt>
          <dd :class="{ 'is-empty': !asset.installation_date }">{{ asset.installation_date ? formatDate(asset.installation_date) : t('common.strings.na') }}</dd>
        </div>
        <div class="dfield">
          <dt>{{ t('assets.fields.lastMaintenanceDate') }}</dt>
          <dd :class="{ 'is-empty': !asset.last_update_date }">{{ asset.last_update_date ? formatDate(asset.last_update_date) : t('common.strings.na') }}</dd>
        </div>
        <div class="dfield">
          <dt>{{ t('assets.fields.remoteAccess') }}</dt>
          <dd>{{ asset.remote_access ? t('common.strings.yes') : t('common.strings.no') }}</dd>
        </div>
        <div class="dfield">
          <dt>{{ t('assets.fields.remoteAccessType') }}</dt>
          <dd :class="{ 'is-empty': !asset.remote_access_type }">{{ asset.remote_access_type ? getRemoteAccessTypeLabel(asset.remote_access_type) : t('common.strings.na') }}</dd>
        </div>
        <div class="dfield">
          <dt>{{ t('assets.fields.physicalAccessEase') }}</dt>
          <dd :class="{ 'is-empty': !asset.physical_access_ease }">{{ asset.physical_access_ease ? getPhysicalAccessLabel(asset.physical_access_ease) : t('common.strings.na') }}</dd>
        </div>
        <div class="dfield">
          <dt>{{ t('assets.fields.businessCriticality') }}</dt>
          <dd><CriticalityBadge v-if="asset.business_criticality" :value="asset.business_criticality" /><span v-else class="is-empty">{{ t('common.strings.na') }}</span></dd>
        </div>
        <div v-if="asset.protocols && asset.protocols.length" class="dfield dfield-wide">
          <dt>{{ t('assets.fields.protocols') }}</dt>
          <dd><span v-for="(protocol, idx) in asset.protocols" :key="protocol + idx" class="dchip">{{ protocol }}</span></dd>
        </div>
      </dl>
    </section>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import CriticalityBadge from '../../common/CriticalityBadge.vue'

defineProps({
  asset: { type: Object, required: true },
  getRemoteAccessTypeLabel: { type: Function, required: true },
  getPhysicalAccessLabel: { type: Function, required: true }
})
const { t } = useI18n()
const { formatDate } = useDateFormatter()
</script>

<style scoped>
.detail-stack { display: flex; flex-direction: column; gap: 1.25rem; }
.is-empty { color: #aab4ae; font-weight: 400; }
</style>
