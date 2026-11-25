<!--
  Free IP address picker for a new asset: the addresses of the IPAM module that are on no interface yet.
  The list is searched on the server (as the user types), so it works with any number of addresses.
  The chosen address id goes to the asset form; saving the asset gives it an interface with that address.
-->
<template>
  <div class="free-ip">
    <small v-if="!canRead('ipam')" class="hint">{{ t('assets.freeIp.needRead') }}</small>
    <template v-else>
      <label for="free_ip" class="block mb-2 font-medium">{{ t('assets.freeIp.label') }}</label>
      <Dropdown
        :modelValue="modelValue"
        inputId="free_ip"
        :options="options"
        optionLabel="label"
        optionValue="id"
        filter
        showClear
        :filterPlaceholder="t('assets.freeIp.search')"
        :placeholder="t('assets.freeIp.placeholder')"
        :emptyMessage="t('assets.freeIp.empty')"
        :emptyFilterMessage="t('assets.freeIp.empty')"
        :loading="loading"
        :disabled="!canWrite('ipam')"
        class="w-full"
        @update:modelValue="v => emit('update:modelValue', v ?? null)"
        @filter="onFilter"
        @show="load('')"
      />
      <small class="hint">{{ canWrite('ipam') ? t(editing ? 'assets.freeIp.hintEdit' : 'assets.freeIp.hint') : t('assets.freeIp.needWrite') }}</small>
      <small v-if="failed" class="p-error block">{{ t('assets.freeIp.loadError') }}</small>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import Dropdown from 'primevue/dropdown'
import api from '@/api/api'
import { usePermissions } from '../../composables/usePermissions'

defineProps({
  modelValue: { type: String, default: null },
  editing: { type: Boolean, default: false } // an existing asset: the address is added as one more interface
})
const emit = defineEmits(['update:modelValue'])

const { t } = useI18n()
const { canRead, canWrite } = usePermissions()

// Statuses that mean the address is in use or kept for use; deprecated, DHCP and SLAAC ones are not offered
const OFFERED = ['active', 'reserved']

const options = ref([])
const loading = ref(false)
const failed = ref(false)
let timer = null
let latest = 0

function labelOf(a) {
  const extra = [a.vrf_name, a.dns_name].filter(Boolean).join(' · ')
  return extra ? `${a.address}  (${extra})` : a.address
}

async function load(search) {
  if (!canRead('ipam')) return
  const ticket = ++latest
  loading.value = true
  failed.value = false
  try {
    const params = { assigned: false, limit: 50 }
    if (search) params.search = search
    const res = await api.getIpamAddresses(params)
    if (ticket !== latest) return // a newer search is on its way
    const items = res.data?.items ?? []
    options.value = items.filter(a => OFFERED.includes(a.status)).map(a => ({ id: a.id, label: labelOf(a) }))
  } catch (err) {
    if (ticket === latest) failed.value = true
  } finally {
    if (ticket === latest) loading.value = false
  }
}

function onFilter(event) {
  clearTimeout(timer)
  timer = setTimeout(() => load((event.value || '').trim()), 250)
}

onMounted(() => load(''))
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.hint {
  display: block;
  margin-top: 0.35rem;
  color: var(--text-color-secondary);
}
</style>
