<!--
  - IpamServiceForm.vue
  - Create or edit a service (a name and TCP/UDP/SCTP ports) of an asset or of an FHRP group, optionally bound to some of
  - the IP addresses. A template can fill the name, ports and description when creating.
-->
<template>
  <Dialog :visible="visible" modal :header="service ? t('ipam.services.edit') : t('ipam.services.new')" :style="{ width: '40rem', maxWidth: '96vw' }"
          @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="grid-2">
      <div v-if="!service && templates.length" class="p-field span-2">
        <label>{{ t('ipam.services.fromTemplate') }}</label>
        <Dropdown v-model="templateId" :options="templateOptions" optionLabel="label" optionValue="value" showClear
                  :placeholder="t('ipam.services.noTemplate')" class="w-full" @change="applyTemplate" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.services.fields.name') }} *</label>
        <InputText v-model="form.name" maxlength="100" class="w-full" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.services.fields.ports') }} *</label>
        <InputText v-model="form.ports" maxlength="500" placeholder="tcp/80, tcp/443, udp/53, tcp/8000-8010" class="w-full" />
        <small class="muted">{{ t('ipam.services.portsHint') }}</small>
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.services.fields.parent') }} *</label>
        <SelectButton v-model="form.parent_type" :options="parentOptions" optionLabel="label" optionValue="value" :allowEmpty="false" />
      </div>
      <div v-if="form.parent_type === 'asset'" class="p-field span-2">
        <label>{{ t('ipam.services.fields.asset') }}</label>
        <Dropdown v-model="form.asset_id" :options="assetOptions" optionLabel="label" optionValue="value" filter
                  :filterPlaceholder="t('ipam.services.searchAsset')" :placeholder="t('ipam.services.chooseAsset')" class="w-full" @filter="onAssetFilter" />
      </div>
      <div v-else class="p-field span-2">
        <label>{{ t('ipam.services.fields.group') }}</label>
        <Dropdown v-model="form.fhrp_group_id" :options="groupOptions" optionLabel="label" optionValue="value" filter
                  :placeholder="t('ipam.services.chooseGroup')" class="w-full" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.services.fields.addresses') }}</label>
        <MultiSelect v-model="form.ip_address_ids" :options="addressOptions" optionLabel="label" optionValue="value" filter display="chip"
                     :filterPlaceholder="t('ipam.addresses.searchPlaceholder')" :placeholder="t('ipam.services.allAddresses')" class="w-full"
                     @filter="onAddressFilter" />
        <small class="muted">{{ t('ipam.services.addressesHint') }}</small>
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.fields.description') }}</label>
        <InputText v-model="form.description" maxlength="200" class="w-full" />
      </div>
      <IpamComments v-model="form.comments" />
    </div>
    <template #footer>
      <Button :label="t('common.actions.cancel')" text severity="secondary" @click="emit('update:visible', false)" />
      <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="save" />
    </template>
  </Dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Dropdown from 'primevue/dropdown'
import MultiSelect from 'primevue/multiselect'
import SelectButton from 'primevue/selectbutton'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { apiErrorText } from '../../utils/money'
import IpamComments from '../features/ipam/IpamComments.vue'

const props = defineProps({
  visible: Boolean,
  service: { type: Object, default: null },
  defaults: { type: Object, default: () => ({}) }
})
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()

const empty = () => ({ name: '', ports: '', parent_type: 'asset', asset_id: null, fhrp_group_id: null, ip_address_ids: [], description: '', comments: '' })
const form = ref(empty())
const error = ref('')
const saving = ref(false)
const templates = ref([])
const templateId = ref(null)
const groups = ref([])
const assets = ref([])
const addresses = ref([])
const known = ref({}) // id -> label of every address seen, so chosen addresses keep their label when the search changes

const parentOptions = computed(() => [{ value: 'asset', label: t('ipam.services.parentAsset') }, { value: 'fhrp_group', label: t('ipam.services.parentGroup') }])
const templateOptions = computed(() => templates.value.map(x => ({ value: x.id, label: `${x.name} (${x.ports_text})` })))
const groupOptions = computed(() => groups.value.map(g => ({ value: g.id, label: g.label })))
const assetOptions = computed(() => {
  const list = assets.value.map(a => ({ value: a.id, label: a.tag ? `${a.name} (${a.tag})` : a.name }))
  const s = props.service
  if (s?.asset_id && !list.some(o => o.value === s.asset_id)) list.unshift({ value: s.asset_id, label: s.asset_name })
  return list
})
const addressOptions = computed(() => {
  const seen = new Set(addresses.value.map(a => a.value))
  const chosen = form.value.ip_address_ids.filter(id => !seen.has(id)).map(id => ({ value: id, label: known.value[id] || id }))
  return [...chosen, ...addresses.value]
})

const addressLabel = a => (a.dns_name ? `${a.address} - ${a.dns_name}` : a.address)
function remember(list) {
  for (const a of list) known.value[a.id] = addressLabel(a)
}

async function searchAddresses(q) {
  try {
    const res = await api.getIpamAddresses({ search: q || undefined, limit: 50 })
    const list = res.data.items || []
    remember(list)
    addresses.value = list.map(a => ({ value: a.id, label: addressLabel(a) }))
  } catch (e) { addresses.value = [] }
}
async function searchAssets(q) {
  try {
    const res = await api.getAssets({ global_search: q || undefined, limit: 30 })
    const body = res.data
    assets.value = Array.isArray(body) ? body : (body?.data || body?.items || [])
  } catch (e) { assets.value = [] }
}
let addressTimer = null
let assetTimer = null
function onAddressFilter(event) { clearTimeout(addressTimer); addressTimer = setTimeout(() => searchAddresses(event.value), 250) }
function onAssetFilter(event) { clearTimeout(assetTimer); assetTimer = setTimeout(() => searchAssets(event.value), 250) }

function applyTemplate() {
  const x = templates.value.find(v => v.id === templateId.value)
  if (!x) return
  form.value.name = form.value.name || x.name
  form.value.ports = x.ports_text
  form.value.description = form.value.description || x.description || ''
}

watch(() => props.visible, async open => {
  if (!open) return
  error.value = ''
  templateId.value = null
  const s = props.service
  if (s) {
    remember(s.ip_addresses.map(a => ({ id: a.id, address: a.address })))
    form.value = {
      name: s.name, ports: s.ports_text, parent_type: s.parent_type, asset_id: s.asset_id, fhrp_group_id: s.fhrp_group_id,
      ip_address_ids: s.ip_addresses.map(a => a.id), description: s.description || '', comments: s.comments || ''
    }
  } else {
    const d = props.defaults
    form.value = { ...empty(), ...d, parent_type: d.fhrp_group_id ? 'fhrp_group' : 'asset' }
  }
  const calls = [searchAddresses(''), searchAssets('')]
  calls.push(api.getIpamServiceTemplates().then(r => { templates.value = r.data || [] }).catch(() => { templates.value = [] }))
  calls.push(api.getIpamFhrpGroups({ limit: 200 }).then(r => { groups.value = r.data.items || [] }).catch(() => { groups.value = [] }))
  await Promise.allSettled(calls)
})

async function save() {
  error.value = ''
  const f = form.value
  if (!f.name.trim() || !f.ports.trim()) { error.value = t('ipam.services.required'); return }
  const asset = f.parent_type === 'asset'
  if (asset ? !f.asset_id : !f.fhrp_group_id) { error.value = t('ipam.services.parentRequired'); return }
  const body = {
    name: f.name.trim(), port_mappings: f.ports, asset_id: asset ? f.asset_id : null, fhrp_group_id: asset ? null : f.fhrp_group_id,
    ip_address_ids: f.ip_address_ids, description: f.description || null, comments: f.comments || null
  }
  saving.value = true
  try {
    const res = props.service ? await api.updateIpamService(props.service.id, body) : await api.createIpamService(body)
    emit('saved', res.data)
    emit('update:visible', false)
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem 1rem; }
.span-2 { grid-column: span 2; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
.muted { color: var(--sk-text-muted, #6b7a71); }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
