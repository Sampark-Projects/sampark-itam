<!--
  - AssetDetailSoftware.vue
  - Software and firmware components installed on the asset (OS, runtimes, applications, modules).
-->
<template>
  <section class="dcard">
    <h3 class="dcard-title">
      <span class="dcard-icon"><i class="pi pi-desktop"></i></span>{{ t('assets.software.title') }}
      <span v-if="items.length" class="dcard-count">{{ items.length }}</span>
    </h3>
    <p v-if="error" class="p-error">{{ error }}</p>

    <div v-if="items.length" ref="scrollBox" class="sw-scroll" :style="boxHeight ? { maxHeight: boxHeight + 'px' } : null">
    <table class="sw-table">
      <thead>
        <tr>
          <th>{{ t('assets.software.name') }}</th>
          <th>{{ t('assets.software.kind') }}</th>
          <th>{{ t('assets.software.version') }}</th>
          <th>{{ t('assets.software.installed') }}</th>
          <th>{{ t('assets.software.licenceExpiry') }}</th>
          <th v-if="editable"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in items" :key="s.id">
          <td>{{ s.name }}<small v-if="s.vendor" class="muted block">{{ s.vendor }}</small></td>
          <td>{{ t(`assets.software.kinds.${s.kind}`) }}</td>
          <td>{{ s.version }}</td>
          <td>{{ formatDate(s.install_date) }}</td>
          <td :class="{ expired: isExpired(s.licence_expiry_date) }">{{ formatDate(s.licence_expiry_date) }}</td>
          <td v-if="editable" class="num">
            <Button icon="pi pi-pencil" text rounded size="small" :aria-label="t('assets.software.edit')" @click="edit(s)" />
            <Button v-if="canDelete('assets')" icon="pi pi-trash" text rounded size="small" severity="danger"
                    :aria-label="t('assets.software.delete')" @click="remove(s)" />
          </td>
        </tr>
      </tbody>
    </table>
    </div>
    <p v-else class="muted">{{ t('assets.software.empty') }}</p>

    <div v-if="editable" class="add-row">
      <Dropdown v-model="form.kind" :options="kindOptions" optionLabel="label" optionValue="value" class="f-kind" />
      <InputText v-model="form.name" maxlength="150" :placeholder="t('assets.software.name')" class="f-name" />
      <InputText v-model="form.vendor" maxlength="150" :placeholder="t('assets.software.vendor')" class="f-vendor" />
      <InputText v-model="form.version" maxlength="100" :placeholder="t('assets.software.version')" class="f-ver" />
      <Calendar v-model="form.install_date" dateFormat="dd/mm/yy" showIcon :placeholder="t('assets.software.installed')" class="f-date" />
      <Calendar v-model="form.licence_expiry_date" dateFormat="dd/mm/yy" showIcon :placeholder="t('assets.software.licenceExpiry')" class="f-date" />
      <Button :label="editingId ? t('common.actions.save') : t('assets.software.add')" :icon="editingId ? 'pi pi-save' : 'pi pi-plus'" :loading="saving" @click="save" />
      <Button v-if="editingId" :label="t('common.actions.cancel')" text severity="secondary" @click="reset" />
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from 'primevue/button'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import Calendar from 'primevue/calendar'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { formatLocalDate, parseLocalDate } from '../../../utils/localDate'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({
  asset: { type: Object, required: true }
})

const { t } = useI18n()
const { canWrite, canDelete } = usePermissions()
const { formatDate } = useDateFormatter()
const editable = computed(() => canWrite('assets') && !props.asset.archived_at)

const KINDS = ['os', 'application', 'runtime', 'firmware_module', 'library', 'other']
const kindOptions = computed(() => KINDS.map(k => ({ value: k, label: t(`assets.software.kinds.${k}`) })))
const blank = () => ({ kind: 'application', name: '', vendor: '', version: '', install_date: null, licence_expiry_date: null })
const items = ref([])
const form = ref(blank())
const editingId = ref(null)
const error = ref('')
const saving = ref(false)

// The table shows at most 5 entries; the rest scrolls. The height is measured (rows with a vendor line are taller).
const VISIBLE_ROWS = 5
const scrollBox = ref(null)
const boxHeight = ref(0)

function fitHeight() {
  const box = scrollBox.value
  if (!box) { boxHeight.value = 0; return }
  const rows = box.querySelectorAll('tbody tr')
  if (rows.length <= VISIBLE_ROWS) { boxHeight.value = 0; return }
  const head = box.querySelector('thead')
  let h = head ? head.offsetHeight : 0
  for (let i = 0; i < VISIBLE_ROWS; i++) h += rows[i].offsetHeight
  boxHeight.value = h + 1
}

watch(items, () => nextTick(fitHeight), { flush: 'post' })
onMounted(() => window.addEventListener('resize', fitHeight))
onBeforeUnmount(() => window.removeEventListener('resize', fitHeight))

function isExpired(value) {
  const d = parseLocalDate(value)
  return d ? d < new Date(new Date().toDateString()) : false
}

async function load(id) {
  error.value = ''
  try {
    const res = await api.getAssetSoftware(id)
    if (props.asset?.id === id) items.value = Array.isArray(res.data) ? res.data : []
  } catch (err) {
    items.value = []
  }
}

function edit(item) {
  editingId.value = item.id
  form.value = { kind: item.kind, name: item.name, vendor: item.vendor || '', version: item.version || '',
    install_date: parseLocalDate(item.install_date), licence_expiry_date: parseLocalDate(item.licence_expiry_date) }
}

function reset() {
  editingId.value = null
  form.value = blank()
}

async function save() {
  error.value = ''
  if (!form.value.name.trim()) {
    error.value = t('assets.software.required')
    return
  }
  const body = { ...form.value, vendor: form.value.vendor || null, version: form.value.version || null,
    install_date: formatLocalDate(form.value.install_date), licence_expiry_date: formatLocalDate(form.value.licence_expiry_date) }
  saving.value = true
  try {
    if (editingId.value) await api.updateAssetSoftware(props.asset.id, editingId.value, body)
    else await api.addAssetSoftware(props.asset.id, body)
    reset()
    await load(props.asset.id)
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

async function remove(item) {
  if (!window.confirm(t('assets.software.deleteConfirm', { name: item.name }))) return
  try {
    await api.deleteAssetSoftware(props.asset.id, item.id)
    await load(props.asset.id)
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

watch(() => props.asset?.id, (id) => { if (id) { reset(); load(id) } }, { immediate: true })
</script>

<style scoped>
.muted { color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; margin: 0 0 0.5rem; }
.block { display: block; }
.sw-scroll { overflow-y: auto; margin-bottom: 0.75rem; border-bottom: 1px solid var(--sk-border, #e1e7e3); }
.sw-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.sw-table th { position: sticky; top: 0; z-index: 1; background: var(--sk-table-head, #f4f7f5); text-align: left; font-size: 0.75rem; letter-spacing: 0.04em; text-transform: uppercase; color: var(--sk-text-muted, #6b7a71); padding: 0.25rem 0.5rem; }
.sw-table td { padding: 0.35rem 0.5rem; border-top: 1px solid var(--sk-border, #e1e7e3); vertical-align: top; }
.num { text-align: right; white-space: nowrap; }
.expired { color: var(--red-600, #c0392b); font-weight: 600; }
.add-row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
.f-kind { flex: 0 0 10rem; }
.f-name, .f-vendor { flex: 1 1 10rem; min-width: 0; }
.f-ver { flex: 0 0 7rem; }
.f-date { flex: 0 0 9rem; }
</style>
