<!--
  - AssetParentPicker.vue
  - Picks the asset this one is a component of. Searches on the server as the user types,
  - so it works with any number of assets. The asset itself is never offered.
-->
<template>
  <Dropdown
    id="parent_asset_id"
    :modelValue="modelValue"
    @update:modelValue="emit('update:modelValue', $event || null)"
    :options="options"
    optionLabel="name"
    optionValue="id"
    filter
    :filterPlaceholder="t('assets.lifecycle.fields.componentOfSearch')"
    resetFilterOnHide
    showClear
    :placeholder="placeholder || t('assets.lifecycle.fields.componentOfNone')"
    :loading="loading"
    class="w-full"
    @filter="onFilter"
    @show="onShow"
  >
    <template #empty>{{ t('assets.lifecycle.fields.componentOfEmpty') }}</template>
  </Dropdown>
</template>

<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import Dropdown from 'primevue/dropdown'
import api from '@/api/api'

const props = defineProps({
  modelValue: { type: String, default: null },
  // {id, name} of the current parent, when the asset already has one
  initial: { type: Object, default: null },
  excludeId: { type: String, default: null },
  placeholder: { type: String, default: null }
})
const emit = defineEmits(['update:modelValue'])

const { t } = useI18n()
const options = ref([])
const loading = ref(false)
let timer = null
let requestSeq = 0

function withCurrent(list) {
  // keep the selected parent in the list so its name shows even when it is not in the search result
  const current = props.initial && props.initial.id === props.modelValue ? props.initial : null
  const rows = list.filter(a => a.id !== props.excludeId)
  if (current && !rows.some(a => a.id === current.id)) rows.unshift({ id: current.id, name: current.name })
  return rows
}

async function search(term) {
  const seq = ++requestSeq
  loading.value = true
  try {
    const res = await api.getAssets({ global_search: term || undefined, limit: 30 })
    if (seq !== requestSeq) return
    const rows = res.data && Array.isArray(res.data.data) ? res.data.data : []
    options.value = withCurrent(rows.map(a => ({ id: a.id, name: a.name })))
  } catch (e) {
    if (seq === requestSeq) options.value = withCurrent([])
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function onFilter(event) {
  clearTimeout(timer)
  timer = setTimeout(() => search(event.value), 250)
}

function onShow() {
  if (options.value.length <= 1) search('')
}

watch(
  () => [props.modelValue, props.initial],
  () => { options.value = withCurrent(options.value) },
  { immediate: true }
)

onBeforeUnmount(() => clearTimeout(timer))
</script>
