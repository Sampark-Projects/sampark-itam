<template>
  <section class="dcard">
    <h3 class="dcard-title">
      <span class="dcard-icon"><i class="pi pi-sitemap"></i></span>{{ t('assets.fields.networkInterfaces') }}
      <span v-if="asset.interfaces?.length" class="dcard-count">{{ asset.interfaces.length }}</span>
    </h3>

    <div v-if="showIpam && (primary.primary_ip4 || primary.primary_ip6 || primary.oob_ip || canWrite('ipam'))" class="ipam-primary">
      <span><b>{{ t('ipam.assetAddresses.primary4') }}:</b> <span class="mono">{{ primary.primary_ip4?.address || t('common.strings.na') }}</span></span>
      <span><b>{{ t('ipam.assetAddresses.primary6') }}:</b> <span class="mono">{{ primary.primary_ip6?.address || t('common.strings.na') }}</span></span>
      <span><b>{{ t('ipam.assetAddresses.oob') }}:</b> <span class="mono">{{ primary.oob_ip?.address || t('common.strings.na') }}</span></span>
      <Button v-if="canWrite('ipam')" icon="pi pi-pencil" text rounded size="small" :aria-label="t('ipam.assetAddresses.title')" @click="addressesOpen = true" />
    </div>

    <div v-if="asset.interfaces && asset.interfaces.length">
      <DataTable v-if="asset.interfaces.length > 4" :value="asset.interfaces" class="p-datatable-sm" :paginator="false" :rows="50">
        <Column field="name" :header="t('common.fields.name')" :filter="true" :filterPlaceholder="t('common.actions.search')" />
        <Column field="type" :header="t('common.fields.type')" />
        <Column field="ip_address" :header="t('assets.fields.ipAddress')" />
        <Column v-if="showIpam" :header="t('assets.interfaces.ipam')">
          <template #body="{ data }">
            <router-link v-for="a in addressesOf(data)" :key="a.id" to="/ipam/ip-addresses" class="ipam-chip mono">{{ a.address }}</router-link>
          </template>
        </Column>
        <Column v-if="showIpam" :header="t('ipam.interfaceSettings.column')">
          <template #body="{ data }">
            <span class="settings">{{ summary(data) }}</span>
            <Button v-if="canWrite('ipam')" icon="pi pi-cog" text rounded size="small" :aria-label="t('ipam.interfaceSettings.edit')" @click="openSettings(data)" />
          </template>
        </Column>
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
            <div v-if="showIpam" class="dfield">
              <dt>{{ t('assets.interfaces.ipam') }}</dt>
              <dd :class="{ 'is-empty': !addressesOf(iface).length }">
                <template v-if="addressesOf(iface).length">
                  <router-link v-for="a in addressesOf(iface)" :key="a.id" to="/ipam/ip-addresses" class="ipam-chip mono"
                               :title="[a.status, a.dns_name, a.vrf_name].filter(Boolean).join(' · ')">{{ a.address }}</router-link>
                </template>
                <template v-else>{{ t('common.strings.na') }}</template>
              </dd>
            </div>
            <div v-if="showIpam" class="dfield">
              <dt>{{ t('ipam.interfaceSettings.column') }}</dt>
              <dd :class="{ 'is-empty': !summary(iface) }">
                {{ summary(iface) || t('common.strings.na') }}
                <Button v-if="canWrite('ipam')" icon="pi pi-cog" text rounded size="small" :aria-label="t('ipam.interfaceSettings.edit')" @click="openSettings(iface)" />
              </dd>
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
    <IpamInterfaceSettings v-if="showIpam" v-model:visible="settingsOpen" :settings="editing" @saved="loadSettings(asset.id)" />
    <IpamAssetAddresses v-if="showIpam" v-model:visible="addressesOpen" :assetId="asset.id" @saved="onAddressesSaved" />
  </section>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import api from '@/api/api'
import IpamInterfaceSettings from '../ipam/IpamInterfaceSettings.vue'
import IpamAssetAddresses from '../ipam/IpamAssetAddresses.vue'
import { usePermissions } from '../../../composables/usePermissions'

const props = defineProps({
  asset: { type: Object, required: true }
})
const { t } = useI18n()
const { canRead, canWrite } = usePermissions()

// The IPAM addresses assigned to the interfaces of this asset (only for users who may read IPAM).
const addresses = ref([])
const showIpam = computed(() => canRead('ipam'))
const byInterface = computed(() => {
  const map = {}
  for (const a of addresses.value) {
    const id = a.assigned_to?.interface_id
    if (id) (map[id] = map[id] || []).push(a)
  }
  return map
})
const addressesOf = iface => byInterface.value[iface.id] || []

async function loadAddresses(id) {
  addresses.value = []
  if (!id || !canRead('ipam')) return
  try {
    const res = await api.getIpamAddresses({ asset_id: id, limit: 500 })
    if (props.asset?.id === id) addresses.value = res.data.items || []
  } catch (err) {
    addresses.value = []
  }
}

// The routing table, VLAN mode and VLANs of each interface, and the primary addresses of the asset.
const settings = ref({})
const primary = ref({})
const editing = ref(null)
const settingsOpen = ref(false)
const addressesOpen = ref(false)

async function loadSettings(id) {
  settings.value = {}
  if (!id || !canRead('ipam')) return
  try {
    const res = await api.getIpamAssetInterfaces(id)
    if (props.asset?.id !== id) return
    settings.value = Object.fromEntries((res.data || []).map(x => [x.interface_id, x]))
  } catch (err) {
    settings.value = {}
  }
}
async function loadPrimary(id) {
  primary.value = {}
  if (!id || !canRead('ipam')) return
  try {
    const res = await api.getIpamAssetAddresses(id)
    if (props.asset?.id === id) primary.value = res.data || {}
  } catch (err) {
    primary.value = {}
  }
}
function summary(iface) {
  const s = settings.value[iface.id]
  if (!s) return ''
  const parts = []
  if (s.vrf_name) parts.push(`VRF ${s.vrf_name}`)
  if (s.vlan_mode) parts.push(t(`ipam.interfaceSettings.modes.${s.vlan_mode.replace(/-/g, '_')}`))
  if (s.untagged_vlan) parts.push(`${t('ipam.interfaceSettings.untaggedShort')} ${s.untagged_vlan.vid}`)
  if (s.tagged_vlans?.length) parts.push(`${t('ipam.interfaceSettings.taggedShort')} ${s.tagged_vlans.map(v => v.vid).join(', ')}`)
  if (s.vlan_translation_policy_name) parts.push(s.vlan_translation_policy_name)
  return parts.join(' · ')
}
function openSettings(iface) {
  editing.value = settings.value[iface.id] || {
    interface_id: iface.id, interface_name: iface.name, asset_id: props.asset.id, asset_name: props.asset.name, site_id: props.asset.site_id,
    vrf_id: null, vlan_mode: null, vlan_translation_policy_id: null, untagged_vlan: null, tagged_vlans: []
  }
  settingsOpen.value = true
}
function onAddressesSaved(data) { primary.value = data }

watch(() => props.asset?.id, id => { loadAddresses(id); loadSettings(id); loadPrimary(id) }, { immediate: true })
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
.ipam-chip { display: inline-block; margin: 0 0.35rem 0.2rem 0; padding: 0.05rem 0.45rem; border: 1px solid var(--sk-border); border-radius: 999px; font-size: 0.82rem; text-decoration: none; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.ipam-primary { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem 1.25rem; margin-bottom: 0.75rem; font-size: 0.9rem; }
.settings { margin-right: 0.25rem; }
</style>
