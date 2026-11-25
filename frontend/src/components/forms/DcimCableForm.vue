<!--
  - DcimCableForm.vue
  - Create or edit a cable: the two ends (an asset and one of its interfaces each) and the cable details. A port that already has a
  - cable is marked and cannot be chosen.
-->
<template>
  <Dialog :visible="visible" modal :header="cable ? t('dcim.cables.edit') : t('dcim.cables.new')" :style="{ width: '46rem', maxWidth: '96vw' }"
          @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>

    <div class="ends">
      <div v-for="end in ENDS" :key="end.key" class="end">
        <h4>{{ t(`dcim.cables.${end.key}`) }}</h4>
        <div class="p-field">
          <label>{{ t('dcim.cables.asset') }} *</label>
          <AssetParentPicker v-model="ends[end.key].asset_id" :initial="ends[end.key].asset" :placeholder="t('dcim.cables.pickAsset')" @update:modelValue="() => onAsset(end.key)" />
        </div>
        <div class="p-field">
          <label>{{ t('dcim.cables.port') }} *</label>
          <Dropdown v-model="form[end.field]" :options="ends[end.key].options" optionLabel="label" optionValue="value" optionDisabled="disabled" filter
                    :disabled="!ends[end.key].asset_id" :loading="ends[end.key].loading" :placeholder="t('dcim.cables.pickPort')" class="w-full" />
        </div>
      </div>
    </div>

    <div class="grid-2">
      <div class="p-field">
        <label>{{ t('dcim.cables.type') }}</label>
        <Dropdown v-model="form.cable_type" :options="cableTypeOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.cables.status') }}</label>
        <Dropdown v-model="form.cable_status" :options="cableStatusOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.cables.label') }}</label>
        <InputText v-model="form.cable_label" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.color') }}</label>
        <div class="row">
          <input v-model="form.cable_color" type="color" class="color" :aria-label="t('dcim.fields.color')" />
          <Button v-if="form.cable_color" icon="pi pi-times" text rounded size="small" :aria-label="t('common.actions.clear')" @click="form.cable_color = null" />
        </div>
      </div>
      <div class="p-field">
        <label>{{ t('dcim.cables.length') }}</label>
        <InputNumber v-model="form.cable_length" :min="0" :minFractionDigits="0" :maxFractionDigits="2" :useGrouping="false" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.cables.lengthUnit') }}</label>
        <Dropdown v-model="form.cable_length_unit" :options="lengthUnitOptions" optionLabel="label" optionValue="value" showClear :disabled="form.cable_length === null" class="w-full" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('dcim.fields.description') }}</label>
        <InputText v-model="form.description" class="w-full" />
      </div>
    </div>

    <template #footer>
      <Button :label="t('common.actions.cancel')" text severity="secondary" @click="emit('update:visible', false)" />
      <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="save" />
    </template>
  </Dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Dropdown from 'primevue/dropdown'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import AssetParentPicker from './AssetParentPicker.vue'
import { useDcimChoices, NONCONNECTABLE_PORT_TYPES } from '../../composables/useDcim'
import { apiErrorText } from '../../utils/money'

// cable: an item of the DCIM cable list (null for a new cable)
const props = defineProps({ visible: Boolean, cable: { type: Object, default: null } })
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()
const { cableTypeOptions, cableStatusOptions, lengthUnitOptions } = useDcimChoices()

const ENDS = [{ key: 'local', field: 'local_interface_id' }, { key: 'remote', field: 'remote_interface_id' }]
const blankEnd = () => ({ asset_id: null, asset: null, options: [], loading: false })
const ends = ref({ local: blankEnd(), remote: blankEnd() })
const form = ref({})
const error = ref('')
const saving = ref(false)

async function loadPorts(key) {
  const end = ends.value[key]
  end.options = []
  if (!end.asset_id) return
  end.loading = true
  const asked = end.asset_id
  try {
    const rows = (await api.getDcimAssetInterfaces(asked)).data || []
    if (ends.value[key].asset_id !== asked) return
    // a port with a cable is shown but cannot be chosen, unless it is the cable being edited
    // a virtual, wireless or channel port cannot take a cable (NetBox rule)
    end.options = rows.map(r => {
      const inUse = !!(r.cable && r.cable.id !== props.cable?.id)
      const noCable = NONCONNECTABLE_PORT_TYPES.includes(r.port_type)
      return { value: r.id, label: inUse ? `${r.name} (${t('dcim.cables.inUse')})` : noCable ? `${r.name} (${t('dcim.cables.noCablePort')})` : r.name, disabled: inUse || noCable }
    })
  } catch (err) {
    end.options = []
  } finally {
    if (ends.value[key].asset_id === asked) end.loading = false
  }
}

function onAsset(key) {
  form.value[ENDS.find(e => e.key === key).field] = null
  loadPorts(key)
}

watch(() => props.visible, open => {
  if (!open) return
  error.value = ''
  const c = props.cable
  ends.value = { local: blankEnd(), remote: blankEnd() }
  form.value = {
    local_interface_id: c?.local?.interface_id || null, remote_interface_id: c?.remote?.interface_id || null,
    cable_type: c?.cable_type || null, cable_status: c?.cable_status || 'connected', cable_label: c?.cable_label || '',
    cable_color: c?.cable_color || null, cable_length: c?.cable_length ?? null, cable_length_unit: c?.cable_length_unit || null, description: c?.description || ''
  }
  if (c) {
    for (const [key, end] of [['local', c.local], ['remote', c.remote]]) {
      if (end) { ends.value[key].asset_id = end.asset_id; ends.value[key].asset = { id: end.asset_id, name: end.asset_name }; loadPorts(key) }
    }
  }
})

// a length needs a unit (as in NetBox): metres are filled in when a length is typed
watch(() => form.value.cable_length, length => {
  if (length !== null && length !== undefined && !form.value.cable_length_unit) form.value.cable_length_unit = 'm'
  if (length === null || length === undefined) form.value.cable_length_unit = null
})

async function save() {
  error.value = ''
  if (!form.value.local_interface_id || !form.value.remote_interface_id) { error.value = t('dcim.cables.bothEnds'); return }
  saving.value = true
  try {
    const payload = { ...form.value, cable_label: form.value.cable_label || null, description: form.value.description || null }
    const res = props.cable ? await api.updateDcimCable(props.cable.id, payload) : await api.createDcimCable(payload)
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
.ends { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem 1.5rem; margin-bottom: 0.5rem; }
.end h4 { margin: 0 0 0.5rem; font-size: 0.8rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--sk-text-muted, #6b7a71); }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem 1rem; }
.span-2 { grid-column: span 2; }
.row { display: flex; align-items: center; gap: 0.5rem; }
.color { width: 3rem; height: 2.2rem; border: 1px solid var(--sk-border, #d7e0da); border-radius: 6px; padding: 0.1rem; background: transparent; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
@media (max-width: 640px) { .ends, .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
