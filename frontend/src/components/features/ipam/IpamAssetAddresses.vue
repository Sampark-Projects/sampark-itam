<!--
  - IpamAssetAddresses.vue
  - Choose the primary IPv4, primary IPv6 and out-of-band address of an asset among the IPAM addresses assigned to its
  - interfaces (NetBox: the primary IPs of a device).
-->
<template>
  <Dialog :visible="visible" modal :header="t('ipam.assetAddresses.title')" :style="{ width: '34rem', maxWidth: '96vw' }" @update:visible="v => emit('update:visible', v)">
    <p class="hint">{{ t('ipam.assetAddresses.hint') }}</p>
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <Message v-if="loaded && !candidates.length" severity="info" :closable="false">{{ t('ipam.assetAddresses.none') }}</Message>
    <div class="p-field">
      <label>{{ t('ipam.assetAddresses.primary4') }}</label>
      <Dropdown v-model="form.primary_ip4_id" :options="options(4)" optionLabel="label" optionValue="value" showClear class="w-full" />
    </div>
    <div class="p-field">
      <label>{{ t('ipam.assetAddresses.primary6') }}</label>
      <Dropdown v-model="form.primary_ip6_id" :options="options(6)" optionLabel="label" optionValue="value" showClear class="w-full" />
    </div>
    <div class="p-field">
      <label>{{ t('ipam.assetAddresses.oob') }}</label>
      <Dropdown v-model="form.oob_ip_id" :options="options(null)" optionLabel="label" optionValue="value" showClear class="w-full" />
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
import Dropdown from 'primevue/dropdown'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({ visible: Boolean, assetId: { type: String, default: '' } })
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()

const form = ref({ primary_ip4_id: null, primary_ip6_id: null, oob_ip_id: null })
const candidates = ref([])
const loaded = ref(false)
const error = ref('')
const saving = ref(false)

// a family of null lists every address (the out-of-band one may be of either)
const options = family => candidates.value.filter(c => !family || c.family === family)
  .map(c => ({ value: c.id, label: `${c.address} (${c.interface_name || t('ipam.assetAddresses.natOutside')})` }))

watch(() => props.visible, async open => {
  if (!open || !props.assetId) return
  error.value = ''
  loaded.value = false
  try {
    const d = (await api.getIpamAssetAddresses(props.assetId)).data
    candidates.value = d.candidates || []
    form.value = { primary_ip4_id: d.primary_ip4?.id || null, primary_ip6_id: d.primary_ip6?.id || null, oob_ip_id: d.oob_ip?.id || null }
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    loaded.value = true
  }
})

async function save() {
  error.value = ''
  saving.value = true
  try {
    const res = await api.setIpamAssetAddresses(props.assetId, { ...form.value })
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
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.p-field { margin-bottom: 0.75rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
</style>
