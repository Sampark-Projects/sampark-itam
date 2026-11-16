<!--
  - AssetTypeFieldsEditor.vue
  - Edits the type-specific field definitions of an asset type (asset_types.fields_schema).
  - The key is generated from the label for a new field and never changes afterwards, so values
  - already saved on assets keep matching their field.
-->
<template>
  <div class="fields-editor">
    <p class="fields-hint">{{ t('assettypes.customFields.hint') }}</p>

    <p v-if="!modelValue.length" class="fields-empty">{{ t('assettypes.customFields.empty') }}</p>

    <div v-for="(field, index) in modelValue" :key="field._uid" class="field-row">
      <div class="field-main">
        <InputText
          v-model="field.label"
          :placeholder="t('assettypes.customFields.label')"
          maxlength="100"
          class="field-label"
          @input="onLabelInput(field)"
        />
        <Dropdown
          v-model="field.type"
          :options="typeOptions"
          optionLabel="label"
          optionValue="value"
          class="field-type"
        />
        <div class="field-required">
          <Checkbox v-model="field.required" :inputId="`req_${field._uid}`" binary />
          <label :for="`req_${field._uid}`">{{ t('assettypes.customFields.required') }}</label>
        </div>
        <Button icon="pi pi-trash" severity="danger" text rounded :aria-label="t('common.actions.delete')" @click="remove(index)" />
      </div>
      <InputText
        v-if="field.type === 'select'"
        :modelValue="field.optionsText"
        @update:modelValue="field.optionsText = $event"
        :placeholder="t('assettypes.customFields.optionsPlaceholder')"
        class="field-options"
      />
      <small class="field-key">{{ t('assettypes.customFields.key') }}: <code>{{ field.key }}</code></small>
    </div>

    <Button
      type="button"
      icon="pi pi-plus"
      :label="t('assettypes.customFields.add')"
      class="p-button-text add-field"
      :disabled="modelValue.length >= MAX_FIELDS"
      @click="add"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import InputText from 'primevue/inputtext'
import Dropdown from 'primevue/dropdown'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import { FIELD_TYPES, slugifyKey } from '../../utils/customFieldDefs'

// v-model is a list of editable rows: { _uid, key, label, type, required, optionsText, saved }
const props = defineProps({
  modelValue: { type: Array, required: true }
})

const MAX_FIELDS = 40
const { t } = useI18n()

const typeOptions = computed(() =>
  FIELD_TYPES.map(value => ({ value, label: t(`assettypes.customFields.types.${value}`) }))
)

let uid = 0
const nextUid = () => `f${Date.now().toString(36)}${uid++}`

function add() {
  props.modelValue.push({
    _uid: nextUid(),
    key: slugifyKey('', props.modelValue.map(f => f.key)),
    label: '',
    type: 'text',
    required: false,
    optionsText: '',
    saved: false
  })
}

function remove(index) {
  props.modelValue.splice(index, 1)
}

// a field that was never saved follows its label; a saved one keeps its key
function onLabelInput(field) {
  if (field.saved) return
  const others = props.modelValue.filter(f => f !== field).map(f => f.key)
  field.key = slugifyKey(field.label, others)
}
</script>

<style scoped>
.fields-hint { margin: 0 0 0.75rem; font-size: 0.85rem; color: var(--sk-text-muted, #6b7a71); }
.fields-empty { margin: 0 0 0.75rem; font-size: 0.9rem; color: var(--sk-text-muted, #6b7a71); }
.field-row {
  padding: 0.6rem 0.75rem;
  margin-bottom: 0.5rem;
  border: 1px solid var(--sk-border, #e1e7e3);
  border-radius: 8px;
}
.field-main { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.field-label { flex: 1 1 12rem; min-width: 0; }
.field-type { flex: 0 0 9rem; }
.field-required { display: flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; }
.field-options { width: 100%; margin-top: 0.5rem; }
.field-key { display: block; margin-top: 0.35rem; color: var(--sk-text-muted, #6b7a71); }
.add-field { width: auto; }
.field-key code { font-size: 0.8rem; }
</style>
