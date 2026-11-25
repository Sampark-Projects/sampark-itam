<!--
  - DcimDeviceTypeForm.vue
  - Create or edit a device type: a manufacturer + model with its height in rack units.
-->
<template>
  <Dialog :visible="visible" modal :header="type ? t('dcim.types.edit') : t('dcim.types.new')" :style="{ width: '40rem', maxWidth: '96vw' }"
          @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="grid-2">
      <div class="p-field">
        <label>{{ t('dcim.fields.manufacturer') }} *</label>
        <Dropdown v-model="form.manufacturer_id" :options="manufacturers" optionLabel="label" optionValue="value" filter class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.model') }} *</label>
        <InputText v-model="form.model" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.height') }}</label>
        <InputNumber v-model="form.u_height" :min="0" :max="100" :step="0.5" :minFractionDigits="0" :maxFractionDigits="1" :useGrouping="false" class="w-full" />
        <small class="muted">{{ t('dcim.types.heightHint') }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.partNumber') }}</label>
        <InputText v-model="form.part_number" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('dcim.fields.airflow') }}</label>
        <Dropdown v-model="form.airflow" :options="airflowOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <div class="p-field">
        <label class="check"><Checkbox v-model="form.is_full_depth" binary /><span>{{ t('dcim.fields.fullDepth') }}</span></label>
        <small class="muted">{{ t('dcim.types.fullDepthHint') }}</small>
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
import { ref, watch } from 'vue'
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

// type: the row being edited (null for a new type); manufacturers: [{value, label}]
const props = defineProps({ visible: Boolean, type: { type: Object, default: null }, manufacturers: { type: Array, default: () => [] } })
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()
const { airflowOptions } = useDcimChoices()

const empty = () => ({ manufacturer_id: null, model: '', u_height: null, is_full_depth: true, airflow: null, part_number: '', description: '', comments: '' })
const form = ref(empty())
const error = ref('')
const saving = ref(false)

watch(() => props.visible, open => {
  if (!open) return
  error.value = ''
  const r = props.type
  form.value = r ? Object.fromEntries(Object.keys(empty()).map(k => [k, r[k] ?? empty()[k]])) : empty()
})

async function save() {
  error.value = ''
  saving.value = true
  try {
    const res = props.type ? await api.updateDcimDeviceType(props.type.id, form.value) : await api.createDcimDeviceType(form.value)
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
