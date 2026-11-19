<template>
  <div class="audit-tab">
    <p class="hint">{{ t('reports.audit.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div class="p-field">
      <label for="ap_site">{{ t('reports.audit.site') }}</label>
      <Dropdown v-model="siteId" inputId="ap_site" :options="sites" optionLabel="name" optionValue="id" showClear
                :placeholder="t('reports.audit.allSites')" class="w-full" />
    </div>
    <div class="p-field">
      <label for="ap_days">{{ t('reports.audit.days') }}</label>
      <InputNumber v-model="days" inputId="ap_days" :min="1" :max="730" :useGrouping="false" class="w-full" />
      <small class="hint">{{ t('reports.audit.daysHelp') }}</small>
    </div>
    <Button :label="t('reports.audit.download')" icon="pi pi-download" :loading="busy" :disabled="!days" @click="download" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import Dropdown from 'primevue/dropdown'
import InputNumber from 'primevue/inputnumber'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { apiErrorText } from '../../../utils/money'
import { downloadBlob } from '../../../composables/usePrint'

const { t } = useI18n()
const sites = ref([])
const siteId = ref(null)
const days = ref(90)
const busy = ref(false)
const message = ref(null)

async function download() {
  message.value = null
  busy.value = true
  try {
    const params = { days: days.value }
    if (siteId.value) params.site_id = siteId.value
    const res = await api.downloadAuditPack(params)
    const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
    downloadBlob(res.data, `audit-report-${stamp}.xlsx`)
    message.value = { severity: 'success', text: t('reports.audit.done') }
  } catch (err) {
    // a failed blob download carries the error body as a Blob: read it so the code can be translated
    let e = err
    try {
      if (err.response?.data instanceof Blob) {
        e = { response: { data: JSON.parse(await err.response.data.text()) } }
      }
    } catch (parseErr) {
      e = err
    }
    message.value = { severity: 'error', text: apiErrorText(e, t) }
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try {
    const res = await api.getSites()
    sites.value = Array.isArray(res.data) ? res.data : (res.data?.data || [])
  } catch (err) {
    sites.value = []
  }
})
</script>

<style scoped>
.audit-tab { max-width: 36rem; }
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; display: block; }
small.hint { margin: 0.25rem 0 0; font-size: 0.8rem; }
.p-field { margin-bottom: 1rem; }
label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
</style>
