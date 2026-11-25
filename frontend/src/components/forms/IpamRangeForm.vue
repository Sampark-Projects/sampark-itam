<!--
  - IpamRangeForm.vue
  - Create or edit an IP range.
-->
<template>
  <Dialog :visible="visible" modal :header="range ? t('ipam.ranges.edit') : t('ipam.ranges.new')"
          :style="{ width: '40rem', maxWidth: '96vw' }" @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="grid-2">
      <div class="p-field">
        <label>{{ t('ipam.ranges.fields.start') }} *</label>
        <InputText v-model="form.start_address" maxlength="50" placeholder="10.0.0.10/24" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.ranges.fields.end') }} *</label>
        <InputText v-model="form.end_address" maxlength="50" placeholder="10.0.0.50/24" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.status') }}</label>
        <Dropdown v-model="form.status" :options="rangeStatusOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.vrf') }}</label>
        <Dropdown v-model="form.vrf_id" :options="vrfs" optionLabel="label" optionValue="value" showClear filter
                  :placeholder="t('ipam.fields.globalTable')" class="w-full" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.fields.role') }}</label>
        <Dropdown v-model="form.role_id" :options="roles" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <div class="p-field span-2 checks">
        <label class="check"><Checkbox v-model="form.mark_populated" binary /><span>{{ t('ipam.ranges.fields.markPopulated') }}</span></label>
        <label class="check"><Checkbox v-model="form.mark_utilized" binary /><span>{{ t('ipam.ranges.fields.markUtilized') }}</span></label>
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.fields.description') }}</label>
        <InputText v-model="form.description" maxlength="200" class="w-full" />
      </div>
      <IpamComments v-model="form.comments" />
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
import Dropdown from 'primevue/dropdown'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { useIpamChoices, useIpamLookups } from '../../composables/useIpam'
import { apiErrorText } from '../../utils/money'
import IpamComments from '../features/ipam/IpamComments.vue'

const props = defineProps({ visible: Boolean, range: { type: Object, default: null }, defaults: { type: Object, default: () => ({}) } })
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()
const { rangeStatusOptions } = useIpamChoices()
const { vrfs, roles, load } = useIpamLookups()

const empty = () => ({ start_address: '', end_address: '', status: 'active', vrf_id: null, role_id: null, mark_populated: false, mark_utilized: false, description: '', comments: '' })
const form = ref(empty())
const error = ref('')
const saving = ref(false)
let loaded = false

watch(() => props.visible, async open => {
  if (!open) return
  error.value = ''
  const r = props.range
  form.value = r
    ? { ...empty(), ...Object.fromEntries(Object.keys(empty()).map(k => [k, r[k] ?? empty()[k]])) }
    : { ...empty(), ...props.defaults }
  if (!loaded) { loaded = true; await load() }
})

async function save() {
  error.value = ''
  if (!form.value.start_address.trim() || !form.value.end_address.trim()) { error.value = t('ipam.ranges.required'); return }
  const body = { ...form.value }
  for (const key of Object.keys(body)) if (body[key] === '') body[key] = null
  saving.value = true
  try {
    const res = props.range ? await api.updateIpamRange(props.range.id, body) : await api.createIpamRange(body)
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
.checks { display: flex; gap: 1.5rem; flex-wrap: wrap; }
.check { display: inline-flex !important; align-items: center; gap: 0.5rem; cursor: pointer; font-weight: 400 !important; }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
