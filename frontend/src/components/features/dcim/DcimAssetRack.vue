<!--
  - DcimAssetRack.vue
  - The "Rack" card of the asset page: the device type, the rack, the unit position and the face of the asset, with a dialog to
  - change them. Only shown to users who can read DCIM. The racks offered are those of the asset's site.
-->
<template>
  <section v-if="canRead('dcim')" class="dcard">
    <h3 class="dcard-title">
      <span class="dcard-icon"><i class="pi pi-server"></i></span>{{ t('dcim.asset.title') }}
      <Button v-if="canWrite('dcim') && placement" icon="pi pi-pencil" text rounded size="small" class="edit" :aria-label="t('dcim.asset.edit')" @click="openEdit" />
    </h3>

    <div v-if="loading" class="loader-row" role="status" aria-live="polite">
      <ProgressSpinner style="width: 1.5rem; height: 1.5rem" strokeWidth="6" /><span>{{ t('common.loading') }}</span>
    </div>

    <template v-else-if="placement">
      <div class="row"><span class="label">{{ t('dcim.fields.deviceType') }}</span>
        <span v-if="placement.device_type">{{ placement.device_type.manufacturer }} {{ placement.device_type.model }}
          <small class="muted">({{ placement.device_type.u_height === null ? t('dcim.types.heightUnknown') : formatUnits(placement.device_type.u_height) + 'U' }})</small></span>
        <span v-else class="muted">{{ t('common.strings.na') }}</span>
      </div>
      <div class="row"><span class="label">{{ t('dcim.fields.rack') }}</span>
        <router-link v-if="placement.rack" :to="`/dcim/racks/${placement.rack.id}`">{{ placement.rack.name }}</router-link>
        <span v-else class="muted">{{ t('dcim.asset.notInRack') }}</span>
      </div>
      <div v-if="placement.rack_position !== null" class="row"><span class="label">{{ t('dcim.fields.position') }}</span>
        <span>U{{ formatUnits(placement.rack_position) }} · {{ t(`dcim.faces.${placement.rack_face}`) }}</span>
      </div>
      <div v-if="placement.airflow" class="row"><span class="label">{{ t('dcim.fields.airflow') }}</span><span>{{ t(`dcim.airflows.${keyOf(placement.airflow)}`) }}</span></div>
    </template>

    <Dialog v-model:visible="open" modal :header="t('dcim.asset.edit')" :style="{ width: '34rem', maxWidth: '96vw' }">
      <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
      <div class="p-field">
        <label>{{ t('dcim.fields.deviceType') }}</label>
        <Dropdown v-model="form.device_type_id" :options="typeOptions" optionLabel="label" optionValue="value" filter showClear resetFilterOnHide
                  :placeholder="t('dcim.asset.noType')" :loading="typesLoading" class="w-full" @filter="onTypeFilter" @show="loadTypes('')" />
        <small class="muted">{{ t('dcim.asset.typeHint') }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.rack') }}</label>
        <Dropdown v-model="form.rack_id" :options="racks" optionLabel="label" optionValue="value" filter showClear
                  :placeholder="t('dcim.asset.notInRack')" class="w-full" @change="onRack" />
        <small class="muted">{{ t('dcim.asset.rackHint') }}</small>
      </div>
      <div class="grid-2">
        <div class="p-field">
          <label>{{ t('dcim.fields.position') }}</label>
          <InputNumber v-model="form.rack_position" :disabled="!form.rack_id" :min="0" :max="1100" :step="0.5" :minFractionDigits="0" :maxFractionDigits="1"
                       :useGrouping="false" class="w-full" />
        </div>
        <div class="p-field">
          <label>{{ t('dcim.fields.face') }}</label>
          <Dropdown v-model="form.rack_face" :options="faceOptions" optionLabel="label" optionValue="value" showClear :disabled="!form.rack_id" class="w-full" />
        </div>
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.airflow') }}</label>
        <Dropdown v-model="form.airflow" :options="airflowOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="open = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="save" />
      </template>
    </Dialog>
  </section>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import Dropdown from 'primevue/dropdown'
import InputNumber from 'primevue/inputnumber'
import Button from 'primevue/button'
import Message from 'primevue/message'
import ProgressSpinner from 'primevue/progressspinner'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDcimChoices, formatUnits, keyOf } from '../../../composables/useDcim'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({ asset: { type: Object, required: true } })
const emit = defineEmits(['saved'])
const { t } = useI18n()
const { canRead, canWrite } = usePermissions()
const { faceOptions, airflowOptions } = useDcimChoices()

const placement = ref(null)
const loading = ref(false)
const open = ref(false)
const saving = ref(false)
const error = ref('')
const racks = ref([])
const typeOptions = ref([])
const typesLoading = ref(false)
const form = ref({ device_type_id: null, rack_id: null, rack_position: null, rack_face: null, airflow: null })

async function load(id) {
  placement.value = null
  if (!id || !canRead('dcim')) return
  loading.value = true
  try {
    const res = await api.getDcimPlacement(id)
    if (props.asset?.id === id) placement.value = res.data
  } catch (err) {
    placement.value = null
  } finally {
    if (props.asset?.id === id) loading.value = false
  }
}

watch(() => props.asset?.id, load, { immediate: true })

const label = t_ => `${t_.manufacturer_name} ${t_.model}${t_.u_height === null ? '' : ` (${formatUnits(t_.u_height)}U)`}`

let typeSeq = 0
let typeTimer = null
async function loadTypes(term) {
  const seq = ++typeSeq
  typesLoading.value = true
  try {
    const res = await api.getDcimDeviceTypes({ search: term || undefined, limit: 30 })
    if (seq !== typeSeq) return
    const rows = (res.data.items || []).map(x => ({ value: x.id, label: label(x) }))
    const current = placement.value?.device_type
    // the type the asset has stays in the list, so its name shows even when the search does not return it
    if (current && form.value.device_type_id === current.id && !rows.some(r => r.value === current.id)) {
      rows.unshift({ value: current.id, label: `${current.manufacturer} ${current.model}` })
    }
    typeOptions.value = rows
  } catch (err) {
    if (seq === typeSeq) typeOptions.value = []
  } finally {
    if (seq === typeSeq) typesLoading.value = false
  }
}
function onTypeFilter(event) { clearTimeout(typeTimer); typeTimer = setTimeout(() => loadTypes(event.value), 250) }

function onRack() {
  if (!form.value.rack_id) { form.value.rack_position = null; form.value.rack_face = null }
}

async function openEdit() {
  const p = placement.value
  error.value = ''
  form.value = { device_type_id: p.device_type?.id || null, rack_id: p.rack?.id || null, rack_position: p.rack_position, rack_face: p.rack_face, airflow: p.airflow }
  open.value = true
  loadTypes('')
  try {
    const res = await api.getDcimRacks({ site_id: p.site_id, limit: 200 })
    racks.value = (res.data.items || []).map(r => ({ value: r.id, label: `${r.name} (${r.u_height}U)` }))
  } catch (err) {
    racks.value = []
  }
}

async function save() {
  error.value = ''
  saving.value = true
  try {
    const res = await api.setDcimPlacement(props.asset.id, { ...form.value })
    placement.value = res.data
    open.value = false
    emit('saved', res.data)
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.edit { margin-left: auto; }
.loader-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.5rem 0; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.row { display: flex; gap: 1rem; align-items: baseline; padding: 0.3rem 0; }
.label { flex: 0 0 9rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.muted { color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
.p-field { margin-bottom: 0.75rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem 1rem; }
</style>
