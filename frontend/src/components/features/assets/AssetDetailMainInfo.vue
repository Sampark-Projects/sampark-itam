<template>
  <div class="detail-stack">
    <section class="dcard">
      <h3 class="dcard-title">
        <span class="dcard-icon"><i class="pi pi-info-circle"></i></span>{{ t('assets.strings.mainInfo') }}
      </h3>
      <dl class="dfields">
        <div class="dfield">
          <dt>{{ t('assets.fields.serialNumber') }}</dt>
          <dd :class="{ 'is-empty': !asset.serial_number }">{{ asset.serial_number || t('common.strings.na') }}</dd>
        </div>
        <div class="dfield">
          <dt>{{ t('assets.fields.model') }}</dt>
          <dd :class="{ 'is-empty': !asset.model }">{{ asset.model || t('common.strings.na') }}</dd>
        </div>
        <div class="dfield">
          <dt>{{ t('assets.fields.manufacturer') }}</dt>
          <dd :class="{ 'is-empty': !asset.manufacturer?.name }">{{ asset.manufacturer?.name || t('common.strings.na') }}</dd>
        </div>
        <div class="dfield">
          <dt>{{ t('common.fields.status') }}</dt>
          <dd :class="{ 'is-empty': !asset.status?.name }">{{ asset.status?.name || t('common.strings.na') }}</dd>
        </div>
      </dl>
    </section>

    <section class="dcard">
      <h3 class="dcard-title">
        <span class="dcard-icon"><i class="pi pi-map-marker"></i></span>{{ t('assets.strings.positionInfo') }}
      </h3>
      <dl class="dfields">
        <div class="dfield">
          <dt>{{ t('assets.fields.site') }}</dt>
          <dd :class="{ 'is-empty': !asset.site?.name }">{{ asset.site?.name || t('common.strings.na') }}</dd>
        </div>
        <div class="dfield">
          <dt>{{ t('assets.fields.area') }}</dt>
          <dd :class="{ 'is-empty': !asset.area_name }">{{ asset.area_name || t('common.strings.na') }}</dd>
        </div>
        <div class="dfield dfield-wide">
          <dt>{{ t('assets.fields.location') }}</dt>
          <dd :class="{ 'is-empty': !asset.location?.name }">{{ asset.location?.name || t('common.strings.na') }}</dd>
        </div>
      </dl>
    </section>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  asset: { type: Object, required: true }
})
const { t } = useI18n()
</script>

<style scoped>
.detail-stack { display: flex; flex-direction: column; gap: 1.25rem; }
</style>
