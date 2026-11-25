<!--
  - AssetTypeForm.vue
  - Componente per il form di creazione/modifica di un tipo di asset
  - Utilizza i componenti PrimeVue per la gestione del form
-->
<template>
  <form @submit.prevent="handleSubmit">
    <div class="p-fluid">
      <div class="p-field">
        <label for="name">{{ t('common.fields.name') }}</label>
        <InputText id="name" v-model="form.name" required />
      </div>

      <div class="p-field">
        <label for="description">{{ t('common.fields.description') }}</label>
        <Textarea id="description" v-model="form.description" autoResize />
      </div>

      <div class="p-field">
        <label for="purdue_level">{{ t('assettypes.fields.purdueLevel') }}</label>
        <Dropdown id="purdue_level" v-model="form.purdue_level" :options="purdueLevels" optionLabel="label" optionValue="value" :placeholder="t('assettypes.strings.selectPurdueLevel')" />
      </div>

      <div class="p-field">
        <label>{{ t('assettypes.customFields.title') }}</label>
        <AssetTypeFieldsEditor v-model="fieldRows" />
        <small v-if="fieldError" class="p-error">{{ fieldError }}</small>
      </div>

      <div class="flex justify-content-end gap-2 mt-4">
        <Button :label="t('common.actions.cancel')" class="p-button-text" @click="emit('cancel')" />
        <Button :label="t('common.actions.save')" type="submit" />
      </div>
    </div>

  </form>
</template>

<script setup>
import { ref, watch } from 'vue'
import InputText from 'primevue/inputtext'
import Textarea from 'primevue/textarea'
import Button from 'primevue/button'
import Dropdown from 'primevue/dropdown'
import AssetTypeFieldsEditor from './AssetTypeFieldsEditor.vue'

import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  assettype: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['submit', 'cancel'])

const form = ref({
  name: '',
  description: '',
  purdue_level: null
})

// editable rows for the type-specific fields (see AssetTypeFieldsEditor)
const fieldRows = ref([])
const fieldError = ref('')
let rowSeq = 0

function toRows(defs) {
  return (Array.isArray(defs) ? defs : []).map(d => ({
    _uid: `s${rowSeq++}`,
    key: d.key,
    label: d.label || d.key,
    type: d.type || 'text',
    required: !!d.required,
    optionsText: Array.isArray(d.options) ? d.options.join(', ') : '',
    saved: true
  }))
}

function toDefs(rows) {
  return rows.map(r => ({
    key: r.key,
    label: r.label.trim(),
    type: r.type,
    required: !!r.required,
    options: r.type === 'select' ? r.optionsText.split(',').map(o => o.trim()).filter(Boolean) : []
  }))
}

const purdueLevels = [
  { value: 0, label: t('assettypes.level0') },
  { value: 1, label: t('assettypes.level1') },
  { value: 1.5, label: t('assettypes.level1_5') },
  { value: 2, label: t('assettypes.level2') },
  { value: 3, label: t('assettypes.level3') },
  { value: 4, label: t('assettypes.level4') }
]

watch(() => props.assettype, (newVal) => {
  if (newVal) {
    form.value = {
      name: newVal.name || '',
      description: newVal.description || '',
      purdue_level: newVal.purdue_level ?? null
    }
    fieldRows.value = toRows(newVal.fields_schema)
  } else {
    form.value = {
      name: '',
      description: '',
      purdue_level: null
    }
    fieldRows.value = []
  }
  fieldError.value = ''
}, { immediate: true })

function handleSubmit() {
  fieldError.value = ''
  const bad = fieldRows.value.find(r => !r.label.trim() || (r.type === 'select' && !r.optionsText.split(',').some(o => o.trim())))
  if (bad) {
    fieldError.value = t(!bad.label.trim() ? 'assettypes.customFields.errorLabel' : 'assettypes.customFields.errorOptions')
    return
  }
  emit('submit', { ...form.value, fields_schema: toDefs(fieldRows.value) })
}

</script>
