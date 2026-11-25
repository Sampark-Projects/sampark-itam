<!--
  - DcimInterfaceDetails.vue
  - The port details of one interface: the kind of port, its state, speed, MTU and PoE. The name, IP address and MAC address of the
  - interface are changed on the asset, as before.
-->
<template>
  <Dialog :visible="visible" modal :header="t('dcim.ports.title', { name: title })" :style="{ width: '40rem', maxWidth: '96vw' }"
          @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="grid-2">
      <div class="p-field">
        <label>{{ t('dcim.ports.portType') }}</label>
        <Dropdown v-model="form.port_type" :options="portTypeOptions" optionLabel="label" optionValue="value" filter showClear class="w-full" @change="onPortType" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.ports.duplex') }}</label>
        <Dropdown v-model="form.duplex" :options="duplexOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.ports.speed') }}</label>
        <InputNumber v-model="form.speed_mbps" :min="0" :useGrouping="false" suffix=" Mbit/s" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.ports.mtu') }}</label>
        <InputNumber v-model="form.mtu" :min="1" :max="65536" :useGrouping="false" class="w-full" />
      </div>
      <div class="p-field">
        <label class="check"><Checkbox v-model="form.enabled" binary /><span>{{ t('dcim.ports.enabled') }}</span></label>
      </div>
      <div class="p-field">
        <label class="check"><Checkbox v-model="form.mgmt_only" binary /><span>{{ t('dcim.ports.mgmtOnly') }}</span></label>
      </div>
      <div class="p-field span-2"><h4 class="group">{{ t('dcim.ports.poe') }}</h4></div>
      <div class="p-field">
        <label>{{ t('dcim.ports.poeMode') }}</label>
        <Dropdown v-model="form.poe_mode" :options="poeModeOptions" optionLabel="label" optionValue="value" showClear :disabled="isVirtual" class="w-full" @change="onMode" />
        <small class="muted">{{ t('dcim.ports.poeModeHint') }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('dcim.ports.poeType') }}</label>
        <Dropdown v-model="form.poe_type" :options="poeTypeOptions" optionLabel="label" optionValue="value" showClear :disabled="!form.poe_mode" class="w-full" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('dcim.ports.poeDraw') }}</label>
        <InputNumber v-model="form.poe_power_draw_w" :min="0" :max="999.9" :minFractionDigits="0" :maxFractionDigits="1" suffix=" W" :disabled="!form.poe_mode" class="w-full" />
        <small class="muted">{{ t('dcim.ports.poeDrawHint') }}</small>
      </div>
    </div>

    <section class="macs">
      <h4 class="group">{{ t('dcim.macs.title') }}</h4>
      <p class="muted">{{ t('dcim.macs.hint') }}</p>
      <p v-if="!macs.length" class="muted">{{ t('dcim.macs.none') }}</p>
      <ul v-else class="mac-list">
        <li v-for="m in macs" :key="m.id">
          <span class="mono">{{ m.mac_address }}</span>
          <Tag v-if="m.is_primary" :value="t('dcim.macs.primary')" severity="success" />
          <span class="note">{{ m.description }}</span>
          <Button v-if="canWrite('dcim') && !m.is_primary" :label="t('dcim.macs.makePrimary')" text size="small" @click="makePrimary(m)" />
          <Button v-if="canDelete('dcim')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeMac(m)" />
        </li>
      </ul>
      <div v-if="canWrite('dcim')" class="add-mac">
        <InputText v-model="newMac.mac_address" :placeholder="t('dcim.macs.placeholder')" class="mac-input" @keyup.enter="addMac" />
        <InputText v-model="newMac.description" :placeholder="t('dcim.fields.description')" maxlength="200" class="note-input" @keyup.enter="addMac" />
        <label class="check"><Checkbox v-model="newMac.is_primary" binary /><span>{{ t('dcim.macs.primary') }}</span></label>
        <Button :label="t('dcim.macs.add')" icon="pi pi-plus" outlined :loading="adding" :disabled="!newMac.mac_address.trim()" @click="addMac" />
      </div>
    </section>
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
import InputNumber from 'primevue/inputnumber'
import Checkbox from 'primevue/checkbox'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDcimChoices, VIRTUAL_PORT_TYPES } from '../../../composables/useDcim'
import { apiErrorText } from '../../../utils/money'

// port: one item of the DCIM interface lists (id, asset_name, name and the port details)
const props = defineProps({ visible: Boolean, port: { type: Object, default: null } })
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()
const { portTypeOptions, duplexOptions, poeModeOptions, poeTypeOptions } = useDcimChoices()
const { canWrite, canDelete } = usePermissions()

const form = ref({})
const macs = ref([])
const newMac = ref({ mac_address: '', description: '', is_primary: false })
const adding = ref(false)
const error = ref('')
const saving = ref(false)
const title = computed(() => (props.port ? `${props.port.asset_name} / ${props.port.name}` : ''))

// the speed is typed in Mbit/s and kept in kbit/s
watch(() => props.visible, open => {
  if (!open || !props.port) return
  const p = props.port
  error.value = ''
  form.value = {
    port_type: p.port_type, duplex: p.duplex, speed_mbps: p.speed_kbps ? p.speed_kbps / 1000 : null, mtu: p.mtu, enabled: p.enabled !== false,
    mgmt_only: !!p.mgmt_only, poe_mode: p.poe_mode, poe_type: p.poe_type, poe_power_draw_w: p.poe_power_draw_w
  }
  newMac.value = { mac_address: '', description: '', is_primary: false }
  loadMacs()
})

// The MAC addresses of the interface (several, one of them primary). Each change is saved at once and the old MAC field of the asset follows the primary one.
async function loadMacs() {
  const id = props.port?.id
  macs.value = []
  if (!id) return
  try {
    const res = await api.getDcimInterfaceMacs(id)
    if (props.port?.id === id) macs.value = res.data || []
  } catch (err) {
    macs.value = []
  }
}

async function changeMacs(call) {
  error.value = ''
  try {
    await call()
    await loadMacs()
    emit('saved')
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

async function addMac() {
  if (!newMac.value.mac_address.trim()) return
  adding.value = true
  await changeMacs(async () => {
    await api.addDcimInterfaceMac(props.port.id, { ...newMac.value, description: newMac.value.description || null })
    newMac.value = { mac_address: '', description: '', is_primary: false }
  })
  adding.value = false
}
const makePrimary = m => changeMacs(() => api.updateDcimMac(m.id, { mac_address: m.mac_address, description: m.description, is_primary: true }))
function removeMac(m) {
  if (window.confirm(t('dcim.macs.deleteConfirm', { mac: m.mac_address }))) changeMacs(() => api.deleteDcimMac(m.id))
}

// a virtual interface (virtual, LAG, bridge) takes no PoE and no cable (NetBox rules)
const isVirtual = computed(() => VIRTUAL_PORT_TYPES.includes(form.value.port_type))
function onPortType() {
  if (isVirtual.value) { form.value.poe_mode = null; form.value.poe_type = null; form.value.poe_power_draw_w = null }
}

function onMode() {
  if (!form.value.poe_mode) { form.value.poe_type = null; form.value.poe_power_draw_w = null }
}

async function save() {
  error.value = ''
  saving.value = true
  try {
    const { speed_mbps, ...rest } = form.value
    const res = await api.updateDcimInterface(props.port.id, { ...rest, speed_kbps: speed_mbps ? Math.round(speed_mbps * 1000) : null })
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
.check { display: inline-flex !important; align-items: center; gap: 0.5rem; cursor: pointer; }
.group { margin: 0.5rem 0 0; font-size: 0.8rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--sk-text-muted, #6b7a71); }
.muted { display: block; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.macs { margin-top: 1rem; border-top: 1px solid var(--sk-border, #d7e0da); padding-top: 0.25rem; }
.mac-list { list-style: none; margin: 0.5rem 0; padding: 0; display: grid; gap: 0.25rem; }
.mac-list li { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }
.mac-list .note { flex: 1; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.add-mac { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.5rem; }
.mac-input { width: 13rem; }
.note-input { flex: 1; min-width: 9rem; }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
