<!--
  - IpamAddressForm.vue
  - Create or edit an IP address, optionally assigned to an asset interface. With `allocateInto` (a prefix) the address
  - is not typed: the next free one of that prefix is taken.
-->
<template>
  <Dialog :visible="visible" modal :header="title" :style="{ width: '40rem', maxWidth: '96vw' }" @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="grid-2">
      <div v-if="!allocateInto" class="p-field span-2">
        <label>{{ t('ipam.addresses.fields.address') }} *</label>
        <InputText v-model="form.address" maxlength="50" placeholder="10.0.0.5/24" class="w-full" />
        <small class="muted">{{ t('ipam.addresses.addressHint') }}</small>
      </div>
      <div v-else class="p-field span-2">
        <small class="muted">{{ t('ipam.addresses.allocateHint', { prefix: allocateInto.prefix }) }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.status') }}</label>
        <Dropdown v-model="form.status" :options="ipStatusOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.role') }}</label>
        <Dropdown v-model="form.role" :options="ipRoleOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <div v-if="!allocateInto" class="p-field">
        <label>{{ t('ipam.fields.vrf') }}</label>
        <Dropdown v-model="form.vrf_id" :options="vrfs" optionLabel="label" optionValue="value" showClear filter
                  :placeholder="t('ipam.fields.globalTable')" class="w-full" />
      </div>
      <div class="p-field" :class="{ 'span-2': allocateInto }">
        <label>{{ t('ipam.addresses.fields.dnsName') }}</label>
        <InputText v-model="form.dns_name" maxlength="255" placeholder="host.example.com" class="w-full" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.addresses.fields.assignedTo') }}</label>
        <Dropdown v-model="form.asset_interface_id" :options="interfaceOptions" optionLabel="label" optionValue="value" showClear filter
                  :disabled="!!form.fhrp_group_id"
                  :filterPlaceholder="t('ipam.addresses.searchInterface')" :placeholder="t('ipam.addresses.notAssigned')" class="w-full"
                  @filter="onInterfaceFilter" />
        <small class="muted">{{ t('ipam.addresses.assignHint') }}</small>
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.addresses.fields.fhrpGroup') }}</label>
        <Dropdown v-model="form.fhrp_group_id" :options="groupOptions" optionLabel="label" optionValue="value" showClear filter
                  :disabled="!!form.asset_interface_id" :placeholder="t('ipam.addresses.noFhrpGroup')" class="w-full" />
        <small class="muted">{{ t('ipam.addresses.fhrpHint') }}</small>
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
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { useIpamChoices, useIpamLookups } from '../../composables/useIpam'
import { apiErrorText } from '../../utils/money'
import IpamComments from '../features/ipam/IpamComments.vue'

const props = defineProps({
  visible: Boolean,
  address: { type: Object, default: null },
  defaults: { type: Object, default: () => ({}) },
  allocateInto: { type: Object, default: null }
})
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()
const { ipStatusOptions, ipRoleOptions } = useIpamChoices()
const { vrfs, load } = useIpamLookups()

const empty = () => ({ address: '', status: 'active', role: null, vrf_id: null, dns_name: '', asset_interface_id: null, fhrp_group_id: null, description: '', comments: '' })
const groups = ref([])
const groupOptions = computed(() => {
  const list = groups.value.map(g => ({ value: g.id, label: g.label }))
  const a = props.address
  if (a?.fhrp_group_id && !list.some(o => o.value === a.fhrp_group_id)) list.unshift({ value: a.fhrp_group_id, label: a.fhrp_group })
  return list
})
const form = ref(empty())
const error = ref('')
const saving = ref(false)
const interfaces = ref([])
let loaded = false

const title = computed(() => props.allocateInto ? t('ipam.addresses.allocate') : props.address ? t('ipam.addresses.edit') : t('ipam.addresses.new'))
const interfaceOptions = computed(() => {
  const list = interfaces.value.map(i => ({ value: i.id, label: i.label }))
  const a = props.address
  if (a?.asset_interface_id && a.assigned_to && !list.some(o => o.value === a.asset_interface_id)) {
    list.unshift({ value: a.asset_interface_id, label: `${a.assigned_to.asset_name} / ${a.assigned_to.interface_name}` })
  }
  return list
})

let timer = null
function onInterfaceFilter(event) {
  clearTimeout(timer)
  timer = setTimeout(async () => {
    try { interfaces.value = (await api.searchIpamInterfaces(event.value || '')).data || [] } catch (e) { interfaces.value = [] }
  }, 250)
}

watch(() => props.visible, async open => {
  if (!open) return
  error.value = ''
  const a = props.address
  form.value = a
    ? { ...empty(), ...Object.fromEntries(Object.keys(empty()).map(k => [k, a[k] ?? empty()[k]])) }
    : { ...empty(), ...props.defaults }
  if (!loaded) { loaded = true; await load() }
  try { interfaces.value = (await api.searchIpamInterfaces('')).data || [] } catch (e) { interfaces.value = [] }
  try { groups.value = (await api.getIpamFhrpGroups({ limit: 200 })).data.items || [] } catch (e) { groups.value = [] }
})

async function save() {
  error.value = ''
  if (!props.allocateInto && !form.value.address.trim()) { error.value = t('ipam.addresses.required'); return }
  const body = { ...form.value }
  for (const key of Object.keys(body)) if (body[key] === '') body[key] = null
  saving.value = true
  try {
    let res
    if (props.allocateInto) {
      const { address, vrf_id, ...rest } = body
      res = await api.allocateIpamAddress(props.allocateInto.id, rest)
    } else {
      res = props.address ? await api.updateIpamAddress(props.address.id, body) : await api.createIpamAddress(body)
    }
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
