<!--
  - IpamInterfaceSettings.vue
  - The IPAM settings of one asset interface: routing table (VRF), VLAN mode, untagged and tagged VLANs and the VLAN translation
  - policy. The IP, mask and VLAN text typed on the interface itself are not changed here.
-->
<template>
  <Dialog :visible="visible" modal :header="t('ipam.interfaceSettings.title', { name: title })" :style="{ width: '38rem', maxWidth: '96vw' }"
          @update:visible="v => emit('update:visible', v)">
    <p class="hint">{{ t('ipam.interfaceSettings.hint') }}</p>
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="grid-2">
      <div class="p-field">
        <label>{{ t('ipam.fields.vrf') }}</label>
        <Dropdown v-model="form.vrf_id" :options="vrfs" optionLabel="label" optionValue="value" showClear filter
                  :placeholder="t('ipam.fields.globalTable')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.interfaceSettings.mode') }}</label>
        <Dropdown v-model="form.vlan_mode" :options="modeOptions" optionLabel="label" optionValue="value" showClear
                  :placeholder="t('ipam.interfaceSettings.noMode')" class="w-full" @change="onMode" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.interfaceSettings.untagged') }}</label>
        <Dropdown v-model="form.untagged_vlan_id" :options="vlanOptions" optionLabel="label" optionValue="value" showClear filter
                  :disabled="!form.vlan_mode" :placeholder="t('ipam.interfaceSettings.noVlan')" class="w-full" />
      </div>
      <div v-if="form.vlan_mode === 'tagged'" class="p-field span-2">
        <label>{{ t('ipam.interfaceSettings.tagged') }}</label>
        <MultiSelect v-model="form.tagged_vlan_ids" :options="taggedOptions" optionLabel="label" optionValue="value" display="chip" filter class="w-full" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.interfaceSettings.policy') }}</label>
        <Dropdown v-model="form.vlan_translation_policy_id" :options="policies" optionLabel="label" optionValue="value" showClear
                  :placeholder="t('ipam.interfaceSettings.noPolicy')" class="w-full" />
      </div>
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
import Dropdown from 'primevue/dropdown'
import MultiSelect from 'primevue/multiselect'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { INTERFACE_VLAN_MODES } from '../../../composables/useIpam'
import { apiErrorText } from '../../../utils/money'

// settings: one item of GET /ipam/assets/{id}/interfaces
const props = defineProps({ visible: Boolean, settings: { type: Object, default: null } })
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()

const form = ref({ vrf_id: null, vlan_mode: null, untagged_vlan_id: null, tagged_vlan_ids: [], vlan_translation_policy_id: null })
const error = ref('')
const saving = ref(false)
const vrfs = ref([])
const vlans = ref([])
const policies = ref([])
const title = computed(() => (props.settings ? `${props.settings.asset_name} / ${props.settings.interface_name}` : ''))
const modeOptions = computed(() => INTERFACE_VLAN_MODES.map(v => ({ value: v, label: t(`ipam.interfaceSettings.modes.${v.replace(/-/g, '_')}`) })))
const vlanOptions = computed(() => vlans.value.filter(v => !form.value.tagged_vlan_ids.includes(v.value)))
const taggedOptions = computed(() => vlans.value.filter(v => v.value !== form.value.untagged_vlan_id))

function onMode() {
  if (!form.value.vlan_mode) form.value.untagged_vlan_id = null
  if (form.value.vlan_mode !== 'tagged') form.value.tagged_vlan_ids = []
}

watch(() => props.visible, async open => {
  if (!open || !props.settings) return
  error.value = ''
  const s = props.settings
  form.value = {
    vrf_id: s.vrf_id, vlan_mode: s.vlan_mode, untagged_vlan_id: s.untagged_vlan?.id || null,
    tagged_vlan_ids: (s.tagged_vlans || []).map(v => v.id), vlan_translation_policy_id: s.vlan_translation_policy_id
  }
  await Promise.allSettled([
    api.getIpamVrfs({ limit: 500 }).then(r => { vrfs.value = (r.data.items || []).map(v => ({ value: v.id, label: v.rd ? `${v.name} (${v.rd})` : v.name })) }),
    // the VLANs of the asset's site, of groups scoped to it, and the global ones
    api.getIpamVlans({ available_at_site: s.site_id, limit: 500 }).then(r => { vlans.value = (r.data.items || []).map(v => ({ value: v.id, label: v.label })) }),
    api.getIpamVlanPolicies().then(r => { policies.value = (r.data || []).map(p => ({ value: p.id, label: p.name })) })
  ])
})

async function save() {
  error.value = ''
  saving.value = true
  try {
    const res = await api.updateIpamInterface(props.settings.interface_id, { ...form.value })
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
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem 1rem; }
.span-2 { grid-column: span 2; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
