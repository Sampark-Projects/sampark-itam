<!--
  - IpamFhrpGroupForm.vue
  - Create or edit an FHRP group (a first hop redundancy group such as VRRP or HSRP). The authentication key is never
  - shown: leaving it empty keeps the stored key, and the "remove" tick clears it.
-->
<template>
  <Dialog :visible="visible" modal :header="group ? t('ipam.fhrp.edit') : t('ipam.fhrp.new')" :style="{ width: '36rem', maxWidth: '96vw' }"
          @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="grid-2">
      <div class="p-field">
        <label>{{ t('ipam.fhrp.fields.protocol') }} *</label>
        <Dropdown v-model="form.protocol" :options="protocolOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fhrp.fields.groupId') }} *</label>
        <InputNumber v-model="form.group_id" :min="0" :max="32767" :useGrouping="false" class="w-full" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('ipam.fhrp.fields.name') }}</label>
        <InputText v-model="form.name" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fhrp.fields.authType') }}</label>
        <Dropdown v-model="form.auth_type" :options="authOptions" optionLabel="label" optionValue="value" showClear :placeholder="t('ipam.fhrp.noAuth')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fhrp.fields.authKey') }}</label>
        <InputText v-model="form.auth_key" type="password" autocomplete="new-password" maxlength="100" :disabled="clearKey"
                   :placeholder="group?.has_auth_key ? t('ipam.fhrp.keyStored') : ''" class="w-full" />
        <label v-if="group?.has_auth_key" class="check"><Checkbox v-model="clearKey" binary /><span>{{ t('ipam.fhrp.removeKey') }}</span></label>
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
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Dropdown from 'primevue/dropdown'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { FHRP_PROTOCOLS, FHRP_AUTH_TYPES } from '../../composables/useIpam'
import { apiErrorText } from '../../utils/money'
import IpamComments from '../features/ipam/IpamComments.vue'

const props = defineProps({ visible: Boolean, group: { type: Object, default: null } })
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()

const protocolOptions = computed(() => FHRP_PROTOCOLS.map(v => ({ value: v, label: t(`ipam.fhrp.protocols.${v}`) })))
const authOptions = computed(() => FHRP_AUTH_TYPES.map(v => ({ value: v, label: t(`ipam.fhrp.authTypes.${v}`) })))

const empty = () => ({ protocol: 'vrrp3', group_id: 1, name: '', auth_type: null, auth_key: '', description: '', comments: '' })
const form = ref(empty())
const clearKey = ref(false)
const error = ref('')
const saving = ref(false)

watch(() => props.visible, open => {
  if (!open) return
  error.value = ''
  clearKey.value = false
  const g = props.group
  form.value = g
    ? { protocol: g.protocol, group_id: g.group_id, name: g.name || '', auth_type: g.auth_type || null, auth_key: '', description: g.description || '', comments: g.comments || '' }
    : empty()
})

async function save() {
  error.value = ''
  if (form.value.group_id === null || form.value.group_id === undefined) { error.value = t('ipam.fhrp.required'); return }
  const body = {
    protocol: form.value.protocol, group_id: form.value.group_id, name: form.value.name.trim() || null,
    auth_type: form.value.auth_type || null, description: form.value.description || null, comments: form.value.comments || null
  }
  // not sent keeps the stored key, an empty text removes it
  if (clearKey.value) body.auth_key = ''
  else if (form.value.auth_key) body.auth_key = form.value.auth_key
  saving.value = true
  try {
    const res = props.group ? await api.updateIpamFhrpGroup(props.group.id, body) : await api.createIpamFhrpGroup(body)
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
.p-field label.check { display: flex; align-items: center; gap: 0.4rem; margin-top: 0.4rem; font-weight: 400; cursor: pointer; }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
