<template>
  <section class="dcard">
    <h3 class="dcard-title">
      <span class="dcard-icon"><i class="pi pi-sitemap"></i></span>{{ t('assets.fields.networkInterfaces') }}
      <span v-if="asset.interfaces?.length" class="dcard-count">{{ asset.interfaces.length }}</span>
    </h3>

    <div v-if="asset.interfaces && asset.interfaces.length">
      <DataTable v-if="asset.interfaces.length > 4" :value="asset.interfaces" class="p-datatable-sm" :paginator="false" :rows="50">
        <Column field="name" :header="t('common.fields.name')" :filter="true" :filterPlaceholder="t('common.actions.search')" />
        <Column field="type" :header="t('common.fields.type')" />
        <Column field="ip_address" :header="t('assets.fields.ipAddress')" />
        <Column field="mac_address" :header="t('assets.fields.macAddress')" />
        <Column field="vlan" :header="t('assets.fields.vlan')" :filter="true" :filterPlaceholder="t('common.actions.search')" />
        <Column field="status" :header="t('common.fields.status')" />
      </DataTable>

      <div v-else class="iface-list">
        <div v-for="(iface, idx) in asset.interfaces" :key="iface.id || idx" class="iface">
          <div class="iface-head">
            <b>{{ iface.name }}</b>
            <Tag v-if="iface.type" :value="iface.type" severity="info" />
            <Button
              v-if="iface.details && Object.keys(iface.details).length"
              icon="pi pi-info-circle"
              class="p-button-text p-button-sm iface-info"
              v-tooltip="JSON.stringify(iface.details, null, 2)"
            />
          </div>
          <dl class="dfields">
            <div class="dfield">
              <dt>{{ t('assets.interfaces.ipAddress') }}</dt>
              <dd :class="{ 'is-empty': !iface.ip_address }">{{ iface.ip_address || t('common.strings.na') }}</dd>
            </div>
            <div class="dfield">
              <dt>{{ t('assets.interfaces.macAddress') }}</dt>
              <dd :class="{ 'is-empty': !iface.mac_address }">{{ iface.mac_address || t('common.strings.na') }}</dd>
            </div>
            <div class="dfield">
              <dt>{{ t('assets.interfaces.vlan') }}</dt>
              <dd :class="{ 'is-empty': !iface.vlan }">{{ iface.vlan || t('common.strings.na') }}</dd>
            </div>
            <div class="dfield">
              <dt>{{ t('assets.interfaces.gateway') }}</dt>
              <dd :class="{ 'is-empty': !iface.default_gateway }">{{ iface.default_gateway || t('common.strings.na') }}</dd>
            </div>
            <div class="dfield">
              <dt>{{ t('assets.interfaces.subnet') }}</dt>
              <dd :class="{ 'is-empty': !iface.subnet_mask }">{{ iface.subnet_mask || t('common.strings.na') }}</dd>
            </div>
            <div class="dfield">
              <dt>{{ t('assets.interfaces.logicalPort') }}</dt>
              <dd :class="{ 'is-empty': !iface.logical_port }">{{ iface.logical_port || t('common.strings.na') }}</dd>
            </div>
            <div class="dfield">
              <dt>{{ t('assets.interfaces.plugLabel') }}</dt>
              <dd :class="{ 'is-empty': !iface.physical_plug_label }">{{ iface.physical_plug_label || t('common.strings.na') }}</dd>
            </div>
            <div v-if="iface.other" class="dfield">
              <dt>{{ t('assets.interfaces.other') }}</dt>
              <dd>{{ iface.other }}</dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
    <div v-else class="iface-empty">{{ t('assets.messages.noInterfaces') }}</div>
  </section>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'

defineProps({
  asset: { type: Object, required: true }
})
const { t } = useI18n()
</script>

<style scoped>
.iface-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 0.85rem; }
.iface {
  padding: 0.85rem 1rem 1rem;
  background: var(--sk-table-head);
  border: 1px solid var(--sk-border);
  border-radius: 10px;
}
.iface-head { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.8rem; color: var(--sk-heading); }
.iface-info { margin-left: auto; width: 1.8rem; height: 1.8rem; padding: 0; }
.iface-empty { color: #aab4ae; font-size: 0.9rem; padding: 0.25rem 0; }
</style>
