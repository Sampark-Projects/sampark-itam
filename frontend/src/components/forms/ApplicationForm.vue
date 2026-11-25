<!--
  - ApplicationForm.vue
  - Create or edit an application: identity and ownership, access and URLs, data and governance.
-->
<template>
  <Dialog :visible="visible" modal :header="application ? t('applications.edit') : t('applications.new')"
          :style="{ width: '52rem', maxWidth: '96vw' }" @update:visible="v => emit('update:visible', v)">
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>

    <h4 class="card-title">{{ t('applications.cards.identity') }}</h4>
    <div class="grid-2">
      <div class="p-field span-2">
        <label>{{ t('applications.fields.name') }} *</label>
        <InputText v-model="form.name" maxlength="150" :placeholder="t('applications.placeholders.name')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.tier') }}</label>
        <Dropdown v-model="form.tier" :options="tierOptions" optionLabel="label" optionValue="value" showClear
                  :placeholder="t('applications.select')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.lifecycleStatus') }}</label>
        <Dropdown v-model="form.lifecycle_status" :options="statusOptions" optionLabel="label" optionValue="value" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.businessOwner') }}</label>
        <InputText v-model="form.business_owner" maxlength="255" :placeholder="t('applications.placeholders.businessOwner')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.technicalOwner') }}</label>
        <InputText v-model="form.technical_owner" maxlength="255" :placeholder="t('applications.placeholders.technicalOwner')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.site') }}</label>
        <Dropdown v-model="form.site_id" :options="sites" optionLabel="name" optionValue="id" showClear filter
                  :placeholder="t('applications.select')" class="w-full" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('applications.fields.description') }}</label>
        <Textarea v-model="form.description" rows="2" autoResize maxlength="5000" class="w-full" />
      </div>
    </div>

    <h4 class="card-title">{{ t('applications.cards.access') }}</h4>
    <div class="grid-2">
      <div class="p-field">
        <label>{{ t('applications.fields.primaryUrl') }}</label>
        <InputText v-model="form.primary_url" maxlength="500" :placeholder="t('applications.placeholders.primaryUrl')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.secondaryUrl') }}</label>
        <InputText v-model="form.secondary_url" maxlength="500" :placeholder="t('applications.placeholders.secondaryUrl')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.authentication') }}</label>
        <InputText v-model="form.authentication_method" maxlength="255" :placeholder="t('applications.placeholders.authentication')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.sslExpiry') }}</label>
        <Calendar v-model="form.ssl_expiry_date" dateFormat="dd/mm/yy" showIcon showButtonBar class="w-full" />
      </div>
    </div>

    <div class="grid-2">
      <div class="p-field span-2">
        <label>{{ t('applications.fields.dnsRecords') }}</label>
        <Textarea v-model="form.dns_records" rows="2" autoResize maxlength="2000" :placeholder="t('applications.placeholders.dnsRecords')" class="w-full" />
      </div>
    </div>

    <h4 class="card-title">{{ t('applications.cards.governance') }}</h4>
    <div class="grid-2">
      <div class="p-field">
        <label>{{ t('applications.fields.classification') }}</label>
        <Dropdown v-model="form.data_classification" :options="classificationOptions" optionLabel="label" optionValue="value" showClear
                  :placeholder="t('applications.select')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.firewallRules') }}</label>
        <InputText v-model="form.firewall_rule_ids" maxlength="2000" :placeholder="t('applications.placeholders.firewallRules')" class="w-full" />
      </div>
      <div class="p-field span-2">
        <label>{{ t('applications.fields.backupPolicy') }}</label>
        <InputText v-model="form.backup_policy" maxlength="2000" :placeholder="t('applications.placeholders.backupPolicy')" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.rpo') }}</label>
        <InputNumber v-model="form.rpo_hours" :min="0" :max="8760" :useGrouping="false" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.rto') }}</label>
        <InputNumber v-model="form.rto_hours" :min="0" :max="8760" :useGrouping="false" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.lastScanDate') }}</label>
        <Calendar v-model="form.last_scan_date" dateFormat="dd/mm/yy" showIcon showButtonBar class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('applications.fields.lastScanResult') }}</label>
        <InputText v-model="form.last_scan_result" maxlength="255" :placeholder="t('applications.placeholders.lastScanResult')" class="w-full" />
      </div>
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
import Textarea from 'primevue/textarea'
import Dropdown from 'primevue/dropdown'
import Calendar from 'primevue/calendar'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { formatLocalDate, parseLocalDate } from '../../utils/localDate'
import { apiErrorText } from '../../utils/money'

const props = defineProps({ visible: Boolean, application: { type: Object, default: null } })
const emit = defineEmits(['update:visible', 'saved'])
const { t } = useI18n()

const TIERS = ['tier1', 'tier2', 'tier3', 'tier4']
const STATUSES = ['planned', 'development', 'staging', 'uat', 'production', 'dr', 'deprecated', 'retired']
const CLASSIFICATIONS = ['public', 'internal', 'confidential', 'restricted']
const tierOptions = computed(() => TIERS.map(v => ({ value: v, label: t(`applications.tiers.${v}`) })))
const statusOptions = computed(() => STATUSES.map(v => ({ value: v, label: t(`applications.statuses.${v}`) })))
const classificationOptions = computed(() => CLASSIFICATIONS.map(v => ({ value: v, label: t(`applications.classifications.${v}`) })))

const empty = () => ({
  name: '', tier: null, lifecycle_status: 'production', business_owner: '', technical_owner: '', site_id: null, description: '',
  primary_url: '', secondary_url: '', authentication_method: '', ssl_expiry_date: null,
  data_classification: null, firewall_rule_ids: '', backup_policy: '', rpo_hours: null, rto_hours: null,
  last_scan_date: null, last_scan_result: '', dns_records: ''
})
const form = ref(empty())
const sites = ref([])
const error = ref('')
const saving = ref(false)

watch(() => props.visible, async open => {
  if (!open) return
  error.value = ''
  const a = props.application
  form.value = a
    ? { ...empty(), ...Object.fromEntries(Object.keys(empty()).map(k => [k, a[k] ?? empty()[k]])),
        ssl_expiry_date: parseLocalDate(a.ssl_expiry_date), last_scan_date: parseLocalDate(a.last_scan_date) }
    : empty()
  if (!sites.value.length) {
    try {
      const res = await api.getSites()
      sites.value = Array.isArray(res.data) ? res.data : (res.data?.items || [])
    } catch (e) {
      sites.value = []
    }
  }
})

async function save() {
  error.value = ''
  if (!form.value.name.trim()) {
    error.value = t('applications.required')
    return
  }
  const body = { ...form.value, ssl_expiry_date: formatLocalDate(form.value.ssl_expiry_date), last_scan_date: formatLocalDate(form.value.last_scan_date) }
  for (const key of Object.keys(body)) if (body[key] === '') body[key] = null
  saving.value = true
  try {
    const res = props.application ? await api.updateApplication(props.application.id, body) : await api.createApplication(body)
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
.card-title { margin: 1rem 0 0.5rem; font-size: 0.95rem; color: var(--sk-text-muted, #6b7a71); text-transform: uppercase; letter-spacing: 0.03em; }
.card-title:first-of-type { margin-top: 0; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem 1rem; }
.span-2 { grid-column: span 2; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
@media (max-width: 640px) { .grid-2 { grid-template-columns: 1fr; } .span-2 { grid-column: span 1; } }
</style>
