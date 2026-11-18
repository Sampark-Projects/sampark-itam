<!--
  - IpamAggregateForm.vue
  - Create or edit an aggregate. The RIR choices are passed in by the page.
-->
<template>
  <Dialog :visible="visible" modal :header="aggregate ? t('ipam.aggregates.edit') : t('ipam.aggregates.new')"
          :style="{ width: '34rem', maxWidth: '96vw' }" @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="p-field">
      <label>{{ t('ipam.aggregates.fields.prefix') }} *</label>
      <InputText v-model="form.prefix" maxlength="50" placeholder="10.0.0.0/8" class="w-full" />
      <small class="muted">{{ t('ipam.aggregates.prefixHint') }}</small>
    </div>
    <div class="p-field">
      <label>{{ t('ipam.aggregates.fields.rir') }} *</label>
      <Dropdown v-model="form.rir_id" :options="rirs" optionLabel="label" optionValue="value" filter class="w-full" />
    </div>
    <div class="p-field">
      <label>{{ t('ipam.aggregates.fields.dateAdded') }}</label>
      <Calendar v-model="form.date_added" dateFormat="dd/mm/yy" showIcon showButtonBar class="w-full" />
    </div>
    <div class="p-field">
      <label>{{ t('ipam.fields.description') }}</label>
      <InputText v-model="form.description" maxlength="200" class="w-full" />
    </div>
    <IpamComments v-model="form.comments" />
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
import Dropdown from 'primevue/dropdown'
import Calendar from 'primevue/calendar'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { formatLocalDate, parseLocalDate } from '../../utils/localDate'
import { apiErrorText } from '../../utils/money'
import IpamComments from '../features/ipam/IpamComments.vue'

const props = defineProps({ visible: Boolean, aggregate: { type: Object, default: null }, rirs: { type: Array, default: () => [] } })
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()

const empty = () => ({ prefix: '', rir_id: null, date_added: null, description: '', comments: '' })
const form = ref(empty())
const error = ref('')
const saving = ref(false)

watch(() => props.visible, open => {
  if (!open) return
  error.value = ''
  const a = props.aggregate
  form.value = a ? { prefix: a.prefix, rir_id: a.rir_id, date_added: parseLocalDate(a.date_added), description: a.description || '', comments: a.comments || '' } : empty()
})

async function save() {
  error.value = ''
  if (!form.value.prefix.trim() || !form.value.rir_id) { error.value = t('ipam.aggregates.required'); return }
  const body = { ...form.value, date_added: formatLocalDate(form.value.date_added), description: form.value.description || null, comments: form.value.comments || null }
  saving.value = true
  try {
    const res = props.aggregate ? await api.updateIpamAggregate(props.aggregate.id, body) : await api.createIpamAggregate(body)
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
.p-field { margin-bottom: 0.75rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
.muted { color: var(--sk-text-muted, #6b7a71); }
</style>
