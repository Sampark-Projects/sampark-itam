<template>
  <div class="settings-tab">
    <p class="hint">{{ t('lifecycle.settings.hint') }}</p>

    <div class="flex align-items-center gap-2 mb-3">
      <InputSwitch v-model="enabled" inputId="alerts_enabled" :disabled="!canDelete('lifecycle')" />
      <label for="alerts_enabled">{{ t('lifecycle.settings.enabled') }}</label>
    </div>

    <div class="p-field">
      <label for="lead_days">{{ t('lifecycle.settings.leadDays') }}</label>
      <InputText id="lead_days" v-model="leadText" class="w-full" :disabled="!canDelete('lifecycle')" placeholder="90, 30, 7" />
      <small v-if="error" class="p-error">{{ error }}</small>
    </div>

    <Message v-if="saved" severity="success" :closable="true" @close="saved = false">{{ t('lifecycle.settings.saved') }}</Message>

    <Button v-if="canDelete('lifecycle')" :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="save" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import InputSwitch from 'primevue/inputswitch'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'

const { t } = useI18n()
const { canDelete } = usePermissions()

const enabled = ref(true)
const leadText = ref('')
const error = ref('')
const saved = ref(false)
const saving = ref(false)

// "90, 30 7" -> [90, 30, 7]; anything that is not a whole number gives null
function parseDays(text) {
  const parts = text.split(/[\s,;]+/).filter(Boolean)
  if (!parts.length) return null
  const out = parts.map(p => (/^\d+$/.test(p) ? Number(p) : NaN))
  return out.some(Number.isNaN) ? null : out
}

async function load() {
  try {
    const res = await api.getLifecycleSettings()
    enabled.value = !!res.data.enabled
    leadText.value = (res.data.lead_days || []).join(', ')
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

async function save() {
  error.value = ''
  saved.value = false
  const days = parseDays(leadText.value)
  if (!days) {
    error.value = t('lifecycle.settings.invalid')
    return
  }
  saving.value = true
  try {
    const res = await api.updateLifecycleSettings({ enabled: enabled.value, lead_days: days })
    leadText.value = (res.data.lead_days || []).join(', ')
    saved.value = true
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.settings-tab { max-width: 36rem; }
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.p-field { margin-bottom: 1rem; }
.p-field label { display: block; margin-bottom: 0.4rem; font-weight: 500; }
</style>
