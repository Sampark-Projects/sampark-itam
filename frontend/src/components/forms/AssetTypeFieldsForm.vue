<!--
  - AssetTypeFieldsForm.vue
  - Renders the fields defined on the asset type (asset_types.fields_schema). Values are kept in
  - form.custom_fields[key]; dates are stored there as "YYYY-MM-DD". Shown only when the type has fields.
-->
<template>
  <Card v-if="fields.length" class="mb-4">
    <template #title>
      <div class="flex align-items-center">
        <i class="pi pi-list mr-2"></i>
        {{ t('assets.typeFields.title', { type: typeName }) }}
      </div>
    </template>
    <template #content>
      <div class="grid">
        <div v-for="field in fields" :key="field.key" class="col-12 md:col-4">
          <div class="p-field">
            <label :for="`cf_${field.key}`">
              {{ field.label }}<span v-if="field.required" class="required"> *</span>
            </label>

            <InputNumber
              v-if="field.type === 'number'"
              :inputId="`cf_${field.key}`"
              :modelValue="numberValue(field.key)"
              @update:modelValue="setValue(field.key, $event)"
              :maxFractionDigits="6"
              class="w-full"
            />
            <Calendar
              v-else-if="field.type === 'date'"
              :inputId="`cf_${field.key}`"
              :modelValue="dateValue(field.key)"
              @update:modelValue="setValue(field.key, formatLocalDate($event))"
              dateFormat="dd/mm/yy"
              showIcon
              class="w-full"
            />
            <Dropdown
              v-else-if="field.type === 'select'"
              :inputId="`cf_${field.key}`"
              :modelValue="values[field.key] ?? null"
              @update:modelValue="setValue(field.key, $event)"
              :options="field.options || []"
              showClear
              class="w-full"
            />
            <div v-else-if="field.type === 'boolean'" class="flex align-items-center gap-2 mt-2">
              <InputSwitch
                :inputId="`cf_${field.key}`"
                :modelValue="values[field.key] === true"
                @update:modelValue="setValue(field.key, $event)"
              />
            </div>
            <InputText
              v-else
              :id="`cf_${field.key}`"
              :modelValue="values[field.key] ?? ''"
              @update:modelValue="setValue(field.key, $event)"
              maxlength="255"
              class="w-full"
            />
            <small v-if="field.help" class="field-help">{{ field.help }}</small>
          </div>
        </div>
      </div>
    </template>
  </Card>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Card from 'primevue/card'
import Calendar from 'primevue/calendar'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import InputSwitch from 'primevue/inputswitch'
import { parseLocalDate, formatLocalDate } from '../../utils/localDate'

const props = defineProps({
  form: { type: Object, required: true },
  assetTypes: { type: Array, default: () => [] }
})

const { t } = useI18n()

const assetType = computed(() => props.assetTypes.find(a => a.id === props.form.asset_type_id) || null)
const typeName = computed(() => assetType.value?.name || '')
const fields = computed(() => (Array.isArray(assetType.value?.fields_schema) ? assetType.value.fields_schema : []))
const values = computed(() => props.form.custom_fields || {})

function setValue(key, value) {
  const next = { ...(props.form.custom_fields || {}) }
  if (value === null || value === undefined || value === '') delete next[key]
  else next[key] = value
  props.form.custom_fields = next
}

function numberValue(key) {
  const v = values.value[key]
  return typeof v === 'number' ? v : (v === undefined || v === null || v === '' ? null : Number(v))
}

function dateValue(key) {
  return parseLocalDate(values.value[key])
}
</script>

<style scoped>
.p-field { margin-bottom: 0.5rem; }
.p-field label { display: block; margin-bottom: 0.5rem; font-weight: 500; }
.required { color: #dc3545; font-weight: bold; }
.field-help { display: block; margin-top: 0.25rem; color: var(--sk-text-muted, #6b7a71); }
</style>
