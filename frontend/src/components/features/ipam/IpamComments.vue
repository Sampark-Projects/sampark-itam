<!--
  - IpamComments.vue
  - The "Comments" field (a few lines of free text) shared by the IPAM forms.
-->
<template>
  <div class="p-field span-2">
    <label>{{ t('ipam.fields.comments') }}</label>
    <Textarea :modelValue="modelValue" rows="3" autoResize maxlength="5000" class="w-full" @update:modelValue="v => emit('update:modelValue', v)" />
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import Textarea from 'primevue/textarea'

defineProps({ modelValue: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()
</script>

<style scoped>
.p-field { margin-bottom: 0.75rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
.span-2 { grid-column: span 2; }
@media (max-width: 640px) { .span-2 { grid-column: span 1; } }
</style>
