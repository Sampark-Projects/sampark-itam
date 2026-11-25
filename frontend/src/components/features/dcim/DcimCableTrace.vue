<!--
  - DcimCableTrace.vue
  - Where the cable of a port leads: this port, the cable (type, status, label, length) and the port at the other end. A port with
  - more than one cable (an older record) lists each of them.
-->
<template>
  <Dialog :visible="visible" modal :header="t('dcim.trace.title', { name: title })" :style="{ width: '44rem', maxWidth: '96vw' }"
          @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="false">{{ error }}</Message>
    <ProgressSpinner v-if="loading" class="spinner" />
    <template v-else-if="trace">
      <p v-if="!trace.cables.length" class="muted">{{ t('dcim.trace.noCable') }}</p>
      <div v-for="(cable, i) in trace.cables" :key="cable.id" class="path">
        <div class="end near">
          <small>{{ t('dcim.trace.near') }}</small>
          <router-link :to="`/assets/${trace.near.asset_id}`" @click="close">{{ trace.near.asset_name }}</router-link>
          <span class="port">{{ trace.near.interface_name }}</span>
        </div>
        <div class="cable">
          <span class="wire" :style="{ borderTopColor: cable.cable_color || undefined }"></span>
          <Tag :value="t(`dcim.cableStatuses.${cable.cable_status}`)" :severity="cableStatusSeverity(cable.cable_status)" />
          <span class="detail">{{ detail(cable) }}</span>
          <Tag v-if="cable.conflict" :value="t('dcim.cables.conflict')" severity="danger" />
        </div>
        <div class="end far">
          <small>{{ t('dcim.trace.far') }}</small>
          <template v-if="trace.far_ends[i]">
            <router-link :to="`/assets/${trace.far_ends[i].asset_id}`" @click="close">{{ trace.far_ends[i].asset_name }}</router-link>
            <span class="port">{{ trace.far_ends[i].interface_name }}</span>
          </template>
          <span v-else class="missing">{{ t('dcim.cables.missingEnd') }}</span>
        </div>
      </div>
    </template>
    <template #footer>
      <Button :label="t('common.actions.close')" text severity="secondary" @click="close" />
    </template>
  </Dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import ProgressSpinner from 'primevue/progressspinner'
import api from '@/api/api'
import { cableStatusSeverity, keyOf } from '../../../composables/useDcim'
import { apiErrorText } from '../../../utils/money'

// port: an item of the DCIM interface lists (id, asset_name, name)
const props = defineProps({ visible: Boolean, port: { type: Object, default: null } })
const emit = defineEmits(['update:visible'])
const { t } = useI18n()

const trace = ref(null)
const loading = ref(false)
const error = ref('')
const title = computed(() => (props.port ? `${props.port.asset_name} / ${props.port.name}` : ''))

const close = () => emit('update:visible', false)
const detail = c => [c.cable_type ? t(`dcim.cableTypes.${keyOf(c.cable_type)}`) : '', c.cable_label, c.cable_length != null ? `${c.cable_length} ${c.cable_length_unit || ''}`.trim() : ''].filter(Boolean).join(' · ')

watch(() => props.visible, async open => {
  if (!open || !props.port) return
  trace.value = null
  error.value = ''
  loading.value = true
  const id = props.port.id
  try {
    const res = await api.traceDcimInterface(id)
    if (props.port?.id === id) trace.value = res.data
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.path { display: grid; grid-template-columns: 1fr auto 1fr; gap: 0.75rem; align-items: center; padding: 0.75rem 0; border-bottom: 1px solid var(--sk-border, #d7e0da); }
.path:last-child { border-bottom: 0; }
.end { display: grid; gap: 0.15rem; }
.end small { text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.7rem; color: var(--sk-text-muted, #6b7a71); }
.far { text-align: right; }
.port { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.9rem; }
.cable { display: grid; gap: 0.3rem; justify-items: center; }
.wire { display: block; width: 6rem; border-top: 3px solid #2196f3; }
.detail { font-size: 0.8rem; color: var(--sk-text-muted, #6b7a71); text-align: center; }
.missing { color: #b45309; font-style: italic; }
.muted { color: var(--sk-text-muted, #6b7a71); }
.spinner { display: block; margin: 1rem auto; }
@media (max-width: 600px) { .path { grid-template-columns: 1fr; } .far { text-align: left; } }
</style>
