<template>
  <div class="settings-tab">
    <p class="hint">{{ t('changes.settings.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div class="p-field">
      <label>{{ t('changes.settings.approver') }}</label>
      <Dropdown v-model="form.approver_role_id" :options="roles" optionLabel="name" optionValue="id" showClear :placeholder="t('changes.settings.anyAdmin')" class="w-full" :disabled="!editable" />
    </div>
    <div class="flex align-items-center gap-2 mb-3">
      <InputSwitch v-model="form.allow_self_approval" inputId="cs_self" :disabled="!editable" />
      <label for="cs_self" class="inline">{{ t('changes.settings.selfApproval') }}</label>
    </div>
    <div class="p-field">
      <label for="cs_quorum">{{ t('changes.settings.required') }}</label>
      <InputNumber v-model="form.required_approvals" inputId="cs_quorum" :min="1" :max="maxApprovals" showButtons :useGrouping="false" :disabled="!editable" />
      <small class="hint">{{ t('changes.settings.requiredHelp') }}</small>
    </div>
    <div class="p-field">
      <label>{{ t('changes.settings.fields') }}</label>
      <MultiSelect v-model="form.controlled_fields" :options="fieldOptions" optionLabel="label" optionValue="value" display="chip" filter class="w-full" :disabled="!editable" />
    </div>
    <Button v-if="editable" :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="save" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import Dropdown from 'primevue/dropdown'
import MultiSelect from 'primevue/multiselect'
import InputSwitch from 'primevue/inputswitch'
import InputNumber from 'primevue/inputnumber'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'
import { fieldLabel } from '../../../utils/workflowFields'

const { t } = useI18n()
const { canDelete } = usePermissions()
// like the workflow definitions, this is configuration
const editable = computed(() => canDelete('changes'))

const form = ref({ approver_role_id: null, allow_self_approval: false, controlled_fields: [], required_approvals: 1 })
const maxApprovals = ref(5)
const choices = ref([])
const roles = ref([])
const message = ref(null)
const saving = ref(false)
const fieldOptions = computed(() => choices.value.map(f => ({ value: f, label: fieldLabel(f, t) })))

async function load() {
  try {
    const [s, r] = await Promise.all([api.getChangeSettings(), api.getRoles()])
    form.value = {
      approver_role_id: s.data.approver_role_id || null,
      allow_self_approval: !!s.data.allow_self_approval,
      controlled_fields: s.data.controlled_fields || [],
      required_approvals: s.data.required_approvals || 1
    }
    maxApprovals.value = s.data.max_required_approvals || 5
    choices.value = s.data.field_choices || []
    roles.value = Array.isArray(r.data) ? r.data : (r.data?.data || [])
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

async function save() {
  message.value = null
  saving.value = true
  try {
    await api.updateChangeSettings({ ...form.value, approver_role_id: form.value.approver_role_id || null })
    message.value = { severity: 'success', text: t('changes.settings.saved') }
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.settings-tab { max-width: 40rem; }
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.p-field { margin-bottom: 1rem; }
small.hint { display: block; margin: 0.25rem 0 0; font-size: 0.8rem; }
label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
label.inline { display: inline; margin: 0; }
</style>
