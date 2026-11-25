<!--
  - DcimRackForm.vue
  - Create or edit a rack. A location can only be chosen from the locations of the chosen site.
-->
<template>
  <Dialog :visible="visible" modal :header="rack ? t('dcim.racks.edit') : t('dcim.racks.new')" :style="{ width: '44rem', maxWidth: '96vw' }"
          @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="grid-2">
      <div class="p-field">
        <label>{{ t('dcim.fields.name') }} *</label>
        <InputText v-model="form.name" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.site') }} *</label>
        <Dropdown v-model="form.site_id" :options="sites" optionLabel="label" optionValue="value" filter class="w-full" @change="form.location_id = null" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.location') }}</label>
        <Dropdown v-model="form.location_id" :options="siteLocations" optionLabel="label" optionValue="value" filter showClear
                  :disabled="!form.site_id" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.role') }}</label>
        <Dropdown v-model="form.role_id" :options="roles" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.status') }}</label>
        <Dropdown v-model="form.status" :options="statusOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.facilityId') }}</label>
        <InputText v-model="form.facility_id" maxlength="50" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.uHeight') }}</label>
        <InputNumber v-model="form.u_height" :min="1" :max="100" :useGrouping="false" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.startingUnit') }}</label>
        <InputNumber v-model="form.starting_unit" :min="1" :max="1000" :useGrouping="false" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.width') }}</label>
        <Dropdown v-model="form.width" :options="widthOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.airflow') }}</label>
        <Dropdown v-model="form.airflow" :options="rackAirflowOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.formFactor') }}</label>
        <Dropdown v-model="form.form_factor" :options="formFactorOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.serial') }}</label>
        <InputText v-model="form.serial" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.assetTag') }}</label>
        <InputText v-model="form.asset_tag" maxlength="100" class="w-full" />
      </div>
      <div class="p-field span-2">
        <label class="check"><Checkbox v-model="form.desc_units" binary /><span>{{ t('dcim.fields.descUnits') }}</span></label>
        <small class="muted">{{ t('dcim.racks.descUnitsHint') }}</small>
      </div>
      <div class="p-field span-2">
        <label>{{ t('dcim.fields.description') }}</label>
        <InputText v-model="form.description" maxlength="200" class="w-full" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('dcim.fields.comments') }}</label>
        <Textarea v-model="form.comments" rows="3" autoResize class="w-full" />
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
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Textarea from 'primevue/textarea'
import Dropdown from 'primevue/dropdown'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { useDcimChoices } from '../../composables/useDcim'
import { apiErrorText } from '../../utils/money'

// rack: the row being edited (null for a new rack); sites, locations ({value, label, site_id}) and roles are the dropdown lists
const props = defineProps({
  visible: Boolean,
  rack: { type: Object, default: null },
  sites: { type: Array, default: () => [] },
  locations: { type: Array, default: () => [] },
  roles: { type: Array, default: () => [] }
})
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()
const { statusOptions, rackAirflowOptions, formFactorOptions, widthOptions } = useDcimChoices()

const empty = () => ({ name: '', site_id: null, location_id: null, role_id: null, status: 'active', facility_id: '', serial: '', asset_tag: '',
                       width: 19, u_height: 42, starting_unit: 1, desc_units: false, airflow: null, form_factor: null, description: '', comments: '' })
const form = ref(empty())
const error = ref('')
const saving = ref(false)
const siteLocations = computed(() => props.locations.filter(l => l.site_id === form.value.site_id))

watch(() => props.visible, open => {
  if (!open) return
  error.value = ''
  const r = props.rack
  form.value = r
    ? { ...empty(), ...Object.fromEntries(Object.keys(empty()).map(k => [k, r[k] ?? empty()[k]])), airflow: r.airflow || null, form_factor: r.form_factor || null }
    : { ...empty(), site_id: props.sites.length === 1 ? props.sites[0].value : null }
})

async function save() {
  error.value = ''
  saving.value = true
  try {
    const payload = { ...form.value }
    const res = props.rack ? await api.updateDcimRack(props.rack.id, payload) : await api.createDcimRack(payload)
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
.muted { display: block; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
