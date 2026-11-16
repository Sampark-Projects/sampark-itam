<template>
  <div>
    <p class="hint">{{ t('workflows.setup.hint') }}</p>
    <Message v-if="message" :severity="message.severity" :closable="true" @close="message = null">{{ message.text }}</Message>

    <div v-if="loading" class="loader-row" role="status" aria-live="polite">
      <ProgressSpinner style="width: 1.5rem; height: 1.5rem" strokeWidth="6" /><span>{{ t('common.loading') }}</span>
    </div>

    <TabView v-else>
      <TabPanel v-for="wf in workflows" :key="wf.kind" :header="t(`workflows.kinds.${wf.kind}`)">
        <div class="grid">
          <div class="col-12 md:col-6">
            <label :for="`wf_name_${wf.kind}`">{{ t('workflows.setup.name') }}</label>
            <InputText :id="`wf_name_${wf.kind}`" v-model="wf.name" maxlength="100" class="w-full" :disabled="!editable" />
          </div>
          <div class="col-12 md:col-6 flex align-items-end">
            <div class="flex align-items-center gap-2 pb-2">
              <InputSwitch v-model="wf.allow_self_approval" :inputId="`wf_self_${wf.kind}`" :disabled="!editable" />
              <label :for="`wf_self_${wf.kind}`">{{ t('workflows.setup.selfApproval') }}</label>
            </div>
          </div>
        </div>

        <div v-for="(step, index) in wf.steps" :key="step._uid" class="step-box">
          <div class="step-top">
            <strong>{{ t('workflows.setup.step') }} {{ index + 1 }}</strong>
            <div v-if="editable" class="step-tools">
              <Button icon="pi pi-arrow-up" text rounded size="small" :disabled="index === 0" :aria-label="t('workflows.setup.moveUp')" @click="move(wf, index, -1)" />
              <Button icon="pi pi-arrow-down" text rounded size="small" :disabled="index === wf.steps.length - 1" :aria-label="t('workflows.setup.moveDown')" @click="move(wf, index, 1)" />
              <Button icon="pi pi-trash" text rounded size="small" severity="danger" :aria-label="t('workflows.setup.remove')" @click="wf.steps.splice(index, 1)" />
            </div>
          </div>
          <div class="grid">
            <div class="col-12 md:col-6">
              <label>{{ t('workflows.setup.stepName') }}</label>
              <InputText v-model="step.name" maxlength="100" class="w-full" :disabled="!editable" />
            </div>
            <div class="col-6 md:col-3">
              <label>{{ t('workflows.setup.type') }}</label>
              <Dropdown v-model="step.step_type" :options="typeOptions" optionLabel="label" optionValue="value" class="w-full" :disabled="!editable" />
            </div>
            <div class="col-6 md:col-3">
              <label>{{ t('workflows.setup.role') }}</label>
              <Dropdown v-model="step.role_id" :options="roles" optionLabel="name" optionValue="id" showClear :placeholder="t('workflows.setup.anyRole')" class="w-full" :disabled="!editable" />
            </div>
            <div class="col-12">
              <label>{{ t('workflows.setup.description') }}</label>
              <InputText v-model="step.description" maxlength="255" class="w-full" :disabled="!editable" />
            </div>
            <div class="col-12 md:col-6">
              <label>{{ t('workflows.setup.requiredFields') }}</label>
              <MultiSelect v-model="step.required_fields" :options="fieldOptions" optionLabel="label" optionValue="value" display="chip" filter class="w-full" :disabled="!editable" />
            </div>
            <div class="col-12 md:col-6">
              <label>{{ t('workflows.setup.setsStatus') }}</label>
              <Dropdown v-model="step.sets_status_id" :options="statuses" optionLabel="name" optionValue="id" showClear :placeholder="t('workflows.setup.noStatus')" class="w-full" :disabled="!editable" />
            </div>
            <div class="col-12 md:col-6">
              <label>{{ t('workflows.setup.confirmStatement') }}</label>
              <InputText v-model="step.confirm_statement" maxlength="255" class="w-full" :disabled="!editable" />
            </div>
            <div class="col-12 md:col-6 flex align-items-end gap-4 flex-wrap">
              <div class="flex align-items-center gap-2 pb-2">
                <Checkbox v-model="step.requires_document" binary :inputId="`doc_${step._uid}`" :disabled="!editable" />
                <label :for="`doc_${step._uid}`" class="inline">{{ t('workflows.setup.requiresDocument') }}</label>
              </div>
              <div v-if="step.requires_document" class="pb-2 doc-cat">
                <Dropdown v-model="step.document_category" :options="categoryOptions" optionLabel="label" optionValue="value"
                          showClear :placeholder="t('workflows.setup.anyDocument')" :disabled="!editable" />
              </div>
              <div class="flex align-items-center gap-2 pb-2">
                <Checkbox v-model="step.requires_comment" binary :inputId="`com_${step._uid}`" :disabled="!editable" />
                <label :for="`com_${step._uid}`" class="inline">{{ t('workflows.setup.requiresComment') }}</label>
              </div>
            </div>
          </div>
        </div>

        <div v-if="editable" class="flex gap-2 mt-3">
          <Button :label="t('workflows.setup.addStep')" icon="pi pi-plus" text :disabled="wf.steps.length >= 15" @click="addStep(wf)" />
          <Button :label="t('workflows.setup.save')" icon="pi pi-save" :loading="saving === wf.kind" @click="save(wf)" />
        </div>
      </TabPanel>
    </TabView>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import InputText from 'primevue/inputtext'
import InputSwitch from 'primevue/inputswitch'
import Dropdown from 'primevue/dropdown'
import MultiSelect from 'primevue/multiselect'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import Message from 'primevue/message'
import ProgressSpinner from 'primevue/progressspinner'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'
import { fieldLabel, DOCUMENT_CATEGORIES, categoryLabel } from '../../../utils/workflowFields'

const { t } = useI18n()
const { canDelete } = usePermissions()
// definitions are configuration: they follow the asset statuses permission
const editable = computed(() => canDelete('lifecycle'))
const categoryOptions = computed(() => DOCUMENT_CATEGORIES.map(c => ({ value: c, label: categoryLabel(c, t) })))

const workflows = ref([])
const roles = ref([])
const statuses = ref([])
const fieldNames = ref([])
const message = ref(null)
const saving = ref(null)
const loading = ref(false)

const typeOptions = computed(() => ['task', 'approval'].map(v => ({ value: v, label: t(`workflows.stepTypes.${v}`) })))
const fieldOptions = computed(() => fieldNames.value.map(f => ({ value: f, label: fieldLabel(f, t) })))

let uid = 0
const nextUid = () => `s${uid++}`
const toRow = (s) => ({
  _uid: nextUid(), name: s.name, description: s.description || '', step_type: s.step_type,
  role_id: s.role_id || null, required_fields: [...(s.required_fields || [])],
  requires_document: !!s.requires_document, document_category: s.document_category || null, requires_comment: !!s.requires_comment,
  confirm_statement: s.confirm_statement || '', sets_status_id: s.sets_status_id || null
})

async function load() {
  loading.value = true
  try {
    const [defs, choices, roleRes, statusRes] = await Promise.all([
      api.getWorkflowDefinitions(), api.getWorkflowFieldChoices(), api.getRoles(), api.getAssetStatuses()
    ])
    fieldNames.value = choices.data?.fields || []
    roles.value = Array.isArray(roleRes.data) ? roleRes.data : (roleRes.data?.data || [])
    statuses.value = Array.isArray(statusRes.data) ? statusRes.data : (statusRes.data?.data || [])
    workflows.value = (defs.data || []).map(w => ({
      kind: w.kind, name: w.name, allow_self_approval: !!w.allow_self_approval, steps: (w.steps || []).map(toRow)
    }))
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    loading.value = false
  }
}

function addStep(wf) {
  wf.steps.push(toRow({ name: '', step_type: 'task' }))
}

function move(wf, index, delta) {
  const target = index + delta
  if (target < 0 || target >= wf.steps.length) return
  const [item] = wf.steps.splice(index, 1)
  wf.steps.splice(target, 0, item)
}

async function save(wf) {
  message.value = null
  if (wf.steps.some(s => !s.name.trim())) {
    message.value = { severity: 'warn', text: t('workflows.setup.nameRequired') }
    return
  }
  saving.value = wf.kind
  try {
    await api.updateWorkflowDefinition(wf.kind, {
      name: wf.name,
      allow_self_approval: wf.allow_self_approval,
      steps: wf.steps.map(s => ({
        name: s.name, description: s.description || null, step_type: s.step_type, role_id: s.role_id || null,
        required_fields: s.required_fields, requires_document: s.requires_document,
        document_category: s.requires_document ? (s.document_category || null) : null, requires_comment: s.requires_comment,
        confirm_statement: s.confirm_statement || null, sets_status_id: s.sets_status_id || null
      }))
    })
    message.value = { severity: 'success', text: t('workflows.setup.saved') }
    await load()
  } catch (err) {
    message.value = { severity: 'error', text: apiErrorText(err, t) }
  } finally {
    saving.value = null
  }
}

onMounted(load)
</script>

<style scoped>
.loader-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.75rem 0; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; }
label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
label.inline { display: inline; margin: 0; }
.step-box { border: 1px solid var(--sk-border, #e1e7e3); border-radius: 10px; padding: 0.75rem 1rem; margin-top: 0.75rem; }
.step-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.25rem; }
</style>
