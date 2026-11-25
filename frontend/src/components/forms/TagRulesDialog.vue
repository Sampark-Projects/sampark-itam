<!--
  - TagRulesDialog.vue
  - Naming standard for asset tags. A rule has a pattern such as DEW-{SITE}-PLC-{SEQ:4} and applies to
  - an asset type and/or a site. New assets get the next free tag automatically; typed tags are checked
  - against the rule and must be unique.
-->
<template>
  <Dialog
    :visible="visible"
    @update:visible="emit('update:visible', $event)"
    :header="t('assettypes.tagRules.title')"
    modal
    :style="{ width: '70vw', maxWidth: '60rem' }"
  >
    <p class="rules-hint">{{ t('assettypes.tagRules.hint') }}</p>
    <ul class="token-list">
      <li><code>{SEQ:4}</code> {{ t('assettypes.tagRules.tokens.seq') }}</li>
      <li><code>{SITE}</code> {{ t('assettypes.tagRules.tokens.site') }}</li>
      <li><code>{YYYY}</code> <code>{YY}</code> {{ t('assettypes.tagRules.tokens.year') }}</li>
    </ul>

    <DataTable :value="rules" :loading="loading" size="small" class="mb-3">
      <template #empty>{{ t('assettypes.tagRules.empty') }}</template>
      <Column field="name" :header="t('common.fields.name')" />
      <Column field="pattern" :header="t('assettypes.tagRules.pattern')">
        <template #body="{ data }"><code>{{ data.pattern }}</code></template>
      </Column>
      <Column :header="t('assettypes.tagRules.appliesTo')">
        <template #body="{ data }">{{ scopeLabel(data) }}</template>
      </Column>
      <Column :header="t('assettypes.tagRules.next')">
        <template #body="{ data }"><code>{{ data.example }}</code></template>
      </Column>
      <Column :header="t('common.fields.status')">
        <template #body="{ data }">
          <Tag :value="data.is_active ? t('assettypes.tagRules.active') : t('assettypes.tagRules.inactive')" :severity="data.is_active ? 'success' : 'secondary'" />
        </template>
      </Column>
      <Column v-if="canWrite" :header="t('common.strings.actions')">
        <template #body="{ data }">
          <Button icon="pi pi-pencil" text rounded severity="info" @click="edit(data)" />
          <Button icon="pi pi-trash" text rounded severity="danger" @click="remove(data)" />
        </template>
      </Column>
    </DataTable>

    <form v-if="canWrite" class="rule-form" @submit.prevent="save">
      <h4>{{ editingId ? t('assettypes.tagRules.edit') : t('assettypes.tagRules.new') }}</h4>
      <div class="grid">
        <div class="col-12 md:col-6">
          <label for="rule_name">{{ t('common.fields.name') }}</label>
          <InputText id="rule_name" v-model="form.name" maxlength="100" class="w-full" />
        </div>
        <div class="col-12 md:col-6">
          <label for="rule_pattern">{{ t('assettypes.tagRules.pattern') }}</label>
          <InputText id="rule_pattern" v-model="form.pattern" maxlength="100" class="w-full" placeholder="DEW-{SITE}-PLC-{SEQ:4}" />
        </div>
        <div class="col-12 md:col-4">
          <label for="rule_type">{{ t('common.fields.type') }}</label>
          <Dropdown id="rule_type" v-model="form.asset_type_id" :options="assetTypes" optionLabel="name" optionValue="id" showClear filter :placeholder="t('assettypes.tagRules.anyType')" class="w-full" />
        </div>
        <div class="col-12 md:col-4">
          <label for="rule_site">{{ t('common.fields.site') }}</label>
          <Dropdown id="rule_site" v-model="form.site_id" :options="sites" optionLabel="name" optionValue="id" showClear filter :placeholder="t('assettypes.tagRules.anySite')" class="w-full" />
        </div>
        <div class="col-12 md:col-2">
          <label for="rule_seq">{{ t('assettypes.tagRules.nextNumber') }}</label>
          <InputNumber id="rule_seq" v-model="form.next_seq" :min="1" :useGrouping="false" class="w-full" />
        </div>
        <div class="col-12 md:col-2 flex align-items-end">
          <div class="flex align-items-center gap-2 pb-2">
            <InputSwitch v-model="form.is_active" inputId="rule_active" />
            <label for="rule_active">{{ t('assettypes.tagRules.active') }}</label>
          </div>
        </div>
      </div>
      <small v-if="formError" class="p-error block mb-2">{{ formError }}</small>
      <div class="flex gap-2 justify-content-end">
        <Button v-if="editingId" type="button" :label="t('common.actions.cancel')" text @click="reset" />
        <Button type="submit" :label="t('common.actions.save')" :loading="saving" />
      </div>
    </form>
  </Dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from 'primevue/usetoast'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import InputSwitch from 'primevue/inputswitch'
import Dropdown from 'primevue/dropdown'
import api from '@/api/api'

const props = defineProps({
  visible: { type: Boolean, default: false },
  canWrite: { type: Boolean, default: false }
})
const emit = defineEmits(['update:visible'])

const { t } = useI18n()
const toast = useToast()

const rules = ref([])
const assetTypes = ref([])
const sites = ref([])
const loading = ref(false)
const saving = ref(false)
const editingId = ref(null)
const formError = ref('')

const blankForm = () => ({ name: '', pattern: '', asset_type_id: null, site_id: null, next_seq: 1, is_active: true })
const form = ref(blankForm())

function scopeLabel(rule) {
  const type = rule.asset_type_id ? assetTypes.value.find(a => a.id === rule.asset_type_id)?.name : null
  const site = rule.site_id ? sites.value.find(s => s.id === rule.site_id)?.name : null
  return [type || t('assettypes.tagRules.anyType'), site || t('assettypes.tagRules.anySite')].join(' / ')
}

function errorText(err) {
  const data = err?.response?.data || {}
  const code = data.error_code
  const translated = code ? t(`core.${code}`) : ''
  const base = translated && translated !== `core.${code}` ? translated : t('core.generic')
  const detail = data.message || data.detail
  let extra = ''
  if (Array.isArray(detail)) extra = detail.map(d => d.msg).join('; ')
  else if (typeof detail === 'string' && detail !== code) extra = detail
  return `${base} ${extra}`.trim()
}

async function load() {
  loading.value = true
  try {
    const [r, types, siteList] = await Promise.all([api.getAssetTagRules(), api.getAssetTypes(), api.getSites()])
    rules.value = Array.isArray(r.data) ? r.data : []
    assetTypes.value = Array.isArray(types.data) ? types.data : []
    sites.value = Array.isArray(siteList.data) ? siteList.data : (siteList.data?.data || [])
  } catch (err) {
    toast.add({ severity: 'error', summary: t('common.messages.error'), detail: errorText(err), life: 4000 })
  } finally {
    loading.value = false
  }
}

function reset() {
  editingId.value = null
  form.value = blankForm()
  formError.value = ''
}

function edit(rule) {
  editingId.value = rule.id
  form.value = {
    name: rule.name,
    pattern: rule.pattern,
    asset_type_id: rule.asset_type_id,
    site_id: rule.site_id,
    next_seq: rule.next_seq,
    is_active: rule.is_active
  }
  formError.value = ''
}

async function save() {
  formError.value = ''
  if (!form.value.name.trim() || !form.value.pattern.trim()) {
    formError.value = t('assettypes.tagRules.required')
    return
  }
  saving.value = true
  try {
    if (editingId.value) await api.updateAssetTagRule(editingId.value, form.value)
    else await api.createAssetTagRule(form.value)
    reset()
    await load()
  } catch (err) {
    formError.value = errorText(err)
  } finally {
    saving.value = false
  }
}

async function remove(rule) {
  try {
    await api.deleteAssetTagRule(rule.id)
    if (editingId.value === rule.id) reset()
    await load()
  } catch (err) {
    toast.add({ severity: 'error', summary: t('common.messages.error'), detail: errorText(err), life: 4000 })
  }
}

watch(() => props.visible, (open) => {
  if (open) {
    reset()
    load()
  }
})
</script>

<style scoped>
.rules-hint { margin: 0 0 0.5rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.token-list { margin: 0 0 1rem; padding-left: 1.1rem; font-size: 0.85rem; color: var(--sk-text-muted, #6b7a71); }
.rule-form { border-top: 1px solid var(--sk-border, #e1e7e3); padding-top: 0.75rem; }
.rule-form h4 { margin: 0 0 0.5rem; }
.rule-form label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
</style>
