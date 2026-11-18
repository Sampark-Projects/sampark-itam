<!--
  - IpamPrefixForm.vue
  - Create or edit a prefix.
-->
<template>
  <Dialog :visible="visible" modal :header="prefix ? t('ipam.prefixes.edit') : t('ipam.prefixes.new')"
          :style="{ width: '40rem', maxWidth: '96vw' }" @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>
    <div class="grid-2">
      <div class="p-field span-2">
        <label>{{ t('ipam.prefixes.fields.prefix') }} *</label>
        <InputText v-model="form.prefix" maxlength="50" placeholder="10.0.0.0/24" class="w-full" />
        <small class="muted">{{ t('ipam.prefixes.prefixHint') }}</small>
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.status') }}</label>
        <Dropdown v-model="form.status" :options="prefixStatusOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.vrf') }}</label>
        <Dropdown v-model="form.vrf_id" :options="vrfs" optionLabel="label" optionValue="value" showClear filter
                  :placeholder="t('ipam.fields.globalTable')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.role') }}</label>
        <Dropdown v-model="form.role_id" :options="roles" optionLabel="label" optionValue="value" showClear class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.vlan') }}</label>
        <Dropdown v-model="form.vlan_id" :options="vlans" optionLabel="label" optionValue="value" showClear filter class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.site') }}</label>
        <Dropdown v-model="form.site_id" :options="sites" optionLabel="label" optionValue="value" showClear filter class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.location') }}</label>
        <Dropdown v-model="form.location_id" :options="siteLocations" optionLabel="label" optionValue="value" showClear filter
                  :placeholder="t('ipam.fields.wholeSite')" class="w-full" />
      </div>
      <div class="p-field span-2 checks">
        <label class="check"><Checkbox v-model="form.is_pool" binary /><span>{{ t('ipam.prefixes.fields.isPool') }}</span></label>
        <label class="check"><Checkbox v-model="form.mark_utilized" binary /><span>{{ t('ipam.prefixes.fields.markUtilized') }}</span></label>
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
import Dropdown from 'primevue/dropdown'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { useIpamChoices, useIpamLookups } from '../../composables/useIpam'
import { apiErrorText } from '../../utils/money'
import IpamComments from '../features/ipam/IpamComments.vue'

const props = defineProps({ visible: Boolean, prefix: { type: Object, default: null }, defaults: { type: Object, default: () => ({}) } })
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()
const { prefixStatusOptions } = useIpamChoices()
const { vrfs, roles, vlans, sites, locations, load } = useIpamLookups()

const empty = () => ({ prefix: '', status: 'active', vrf_id: null, role_id: null, vlan_id: null, site_id: null, location_id: null, is_pool: false, mark_utilized: false, description: '', comments: '' })
const form = ref(empty())
// when a site is chosen, only the locations of that site are offered; a location brings its site
const siteLocations = computed(() => locations.value.filter(l => !form.value.site_id || l.site_id === form.value.site_id))
const error = ref('')
const saving = ref(false)
let loaded = false

watch(() => props.visible, async open => {
  if (!open) return
  error.value = ''
  const p = props.prefix
  form.value = p
    ? { ...empty(), ...Object.fromEntries(Object.keys(empty()).map(k => [k, p[k] ?? empty()[k]])) }
    : { ...empty(), ...props.defaults }
  if (!loaded) { loaded = true; await load({ vlan: true }) }
})

async function save() {
  error.value = ''
  if (!form.value.prefix.trim()) { error.value = t('ipam.prefixes.required'); return }
  const body = { ...form.value }
  for (const key of Object.keys(body)) if (body[key] === '') body[key] = null
  saving.value = true
  try {
    const res = props.prefix ? await api.updateIpamPrefix(props.prefix.id, body) : await api.createIpamPrefix(body)
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
.muted { color: var(--sk-text-muted, #6b7a71); }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
