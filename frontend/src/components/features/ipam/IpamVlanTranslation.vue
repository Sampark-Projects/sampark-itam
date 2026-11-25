<!--
  - IpamVlanTranslation.vue
  - VLAN translation policies and their rules (local VLAN ID -> remote VLAN ID). A policy is applied to an asset interface from the
  - interface IPAM settings. Used as a tab of the VLAN page.
-->
<template>
  <div>
    <p class="hint">{{ t('ipam.translation.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>
    <div class="toolbar">
      <span class="spacer"></span>
      <Button v-if="canWrite('ipam')" :label="t('ipam.translation.new')" icon="pi pi-plus" severity="success" @click="openPolicy(null)" />
    </div>
    <DataTable :value="policies" dataKey="id">
      <template #empty>{{ t('ipam.translation.empty') }}</template>
      <Column field="name" :header="t('ipam.vlans.fields.name')" />
      <Column field="rule_count" :header="t('ipam.translation.rules')" style="width: 7rem" />
      <Column field="interface_count" :header="t('ipam.translation.interfaces')" style="width: 8rem" />
      <Column field="description" :header="t('ipam.fields.description')" />
      <Column style="width: 9rem">
        <template #body="{ data }">
          <Button icon="pi pi-list" text rounded size="small" :aria-label="t('ipam.translation.rules')" @click="openRules(data)" />
          <Button v-if="canWrite('ipam')" icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="openPolicy(data)" />
          <Button v-if="canDelete('ipam')" icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removePolicy(data)" />
        </template>
      </Column>
    </DataTable>

    <Dialog v-model:visible="policyOpen" modal :header="policyEditing ? t('ipam.translation.edit') : t('ipam.translation.new')" :style="{ width: '32rem', maxWidth: '96vw' }">
      <Message v-if="policyError" severity="error" :closable="true" @close="policyError = ''">{{ policyError }}</Message>
      <div class="p-field">
        <label>{{ t('ipam.vlans.fields.name') }} *</label>
        <InputText v-model="policyForm.name" maxlength="100" class="w-full" />
      </div>
      <div class="p-field">
        <label>{{ t('ipam.fields.description') }}</label>
        <InputText v-model="policyForm.description" maxlength="200" class="w-full" />
      </div>
      <IpamComments v-model="policyForm.comments" />
      <template #footer>
        <Button :label="t('common.actions.cancel')" text severity="secondary" @click="policyOpen = false" />
        <Button :label="t('common.actions.save')" icon="pi pi-save" :loading="saving" @click="savePolicy" />
      </template>
    </Dialog>

    <Dialog v-model:visible="rulesOpen" modal :header="t('ipam.translation.rulesOf', { name: current?.name || '' })" :style="{ width: '44rem', maxWidth: '96vw' }">
      <Message v-if="ruleError" severity="error" :closable="true" @close="ruleError = ''">{{ ruleError }}</Message>
      <div v-if="canWrite('ipam')" class="rule-form">
        <InputNumber v-model="ruleForm.local_vid" :min="1" :max="4094" :useGrouping="false" :placeholder="t('ipam.translation.local')" />
        <i class="pi pi-arrow-right"></i>
        <InputNumber v-model="ruleForm.remote_vid" :min="1" :max="4094" :useGrouping="false" :placeholder="t('ipam.translation.remote')" />
        <InputText v-model="ruleForm.description" maxlength="200" :placeholder="t('ipam.fields.description')" class="grow" />
        <Button :label="ruleEditing ? t('common.actions.save') : t('ipam.translation.addRule')" icon="pi pi-check" size="small" :loading="saving" @click="saveRule" />
        <Button v-if="ruleEditing" :label="t('common.actions.cancel')" text size="small" severity="secondary" @click="resetRule" />
      </div>
      <DataTable :value="current?.rules || []" dataKey="id" size="small">
        <template #empty>{{ t('ipam.translation.noRules') }}</template>
        <Column field="local_vid" :header="t('ipam.translation.local')" style="width: 9rem" />
        <Column field="remote_vid" :header="t('ipam.translation.remote')" style="width: 9rem" />
        <Column field="description" :header="t('ipam.fields.description')" />
        <Column v-if="canWrite('ipam')" style="width: 6rem">
          <template #body="{ data }">
            <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('common.actions.edit')" @click="editRule(data)" />
            <Button v-if="canDelete('ipam')" icon="pi pi-times" text rounded size="small" severity="danger" :aria-label="t('common.actions.delete')" @click="removeRule(data)" />
          </template>
        </Column>
      </DataTable>
      <template #footer>
        <Button :label="t('common.actions.close')" text severity="secondary" @click="rulesOpen = false" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Button from 'primevue/button'
import Message from 'primevue/message'
import api from '@/api/api'
import IpamComments from './IpamComments.vue'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const message = ref(null)
const saving = ref(false)
const policies = ref([])

async function load() {
  try { policies.value = (await api.getIpamVlanPolicies()).data || [] } catch (err) { message.value = { severity: 'error', text: apiErrorText(err, t) } }
}

// --- policies ---
const policyOpen = ref(false)
const policyEditing = ref(null)
const policyError = ref('')
const policyForm = ref({ name: '', description: '', comments: '' })
function openPolicy(row) {
  policyEditing.value = row
  policyError.value = ''
  policyForm.value = row ? { name: row.name, description: row.description || '', comments: row.comments || '' } : { name: '', description: '', comments: '' }
  policyOpen.value = true
}
async function savePolicy() {
  policyError.value = ''
  if (!policyForm.value.name.trim()) { policyError.value = t('ipam.vlans.nameRequired'); return }
  const f = policyForm.value
  const body = { name: f.name.trim(), description: f.description || null, comments: f.comments || null }
  saving.value = true
  try {
    if (policyEditing.value) await api.updateIpamVlanPolicy(policyEditing.value.id, body)
    else await api.createIpamVlanPolicy(body)
    policyOpen.value = false
    message.value = { severity: 'success', text: t('ipam.saved') }
    await load()
  } catch (err) {
    policyError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
async function removePolicy(row) {
  if (!window.confirm(t('ipam.translation.deleteConfirm', { name: row.name }))) return
  try {
    await api.deleteIpamVlanPolicy(row.id)
    await load()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  }
}

// --- rules ---
const rulesOpen = ref(false)
const current = ref(null)
const ruleError = ref('')
const ruleEditing = ref(null)
const ruleForm = ref({ local_vid: null, remote_vid: null, description: '' })
function resetRule() { ruleEditing.value = null; ruleForm.value = { local_vid: null, remote_vid: null, description: '' } }
async function reloadCurrent() { current.value = (await api.getIpamVlanPolicy(current.value.id)).data }
async function openRules(row) {
  ruleError.value = ''
  resetRule()
  current.value = row
  rulesOpen.value = true
  try { await reloadCurrent() } catch (err) { ruleError.value = apiErrorText(err, t) }
}
function editRule(rule) {
  ruleEditing.value = rule
  ruleForm.value = { local_vid: rule.local_vid, remote_vid: rule.remote_vid, description: rule.description || '' }
}
async function saveRule() {
  ruleError.value = ''
  const f = ruleForm.value
  if (!f.local_vid || !f.remote_vid) { ruleError.value = t('ipam.translation.ruleRequired'); return }
  const body = { local_vid: f.local_vid, remote_vid: f.remote_vid, description: f.description || null }
  saving.value = true
  try {
    if (ruleEditing.value) await api.updateIpamVlanRule(current.value.id, ruleEditing.value.id, body)
    else await api.createIpamVlanRule(current.value.id, body)
    resetRule()
    await reloadCurrent()
    await load()
  } catch (err) {
    ruleError.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}
async function removeRule(rule) {
  try {
    await api.deleteIpamVlanRule(current.value.id, rule.id)
    await reloadCurrent()
    await load()
  } catch (err) {
    ruleError.value = apiErrorText(err, t)
  }
}

onMounted(load)
</script>

<style scoped>
.hint { margin: 0 0 1rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.75rem; }
.toolbar .spacer { flex: 1; }
.p-field { margin-bottom: 0.75rem; }
.p-field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
.rule-form { display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; }
.rule-form .grow { flex: 1 1 10rem; }
:deep(.rule-form .p-inputnumber-input) { width: 7rem; }
</style>
