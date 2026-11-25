<template>
  <div class="assettypes-page">
    <div class="page-header">
      <h1>{{ t('assettypes.title') }}</h1>
      <div class="flex gap-2">
        <Button
          :label="t('assettypes.tagRules.button')"
          icon="pi pi-tag"
          severity="secondary"
          outlined
          @click="showTagRules = true"
        />
        <Button
          v-if="canBulkOperate('asset_types')"
          :label="t('common.actions.import')"
          icon="pi pi-upload"
          severity="info"
          @click="showImportDialog = true"
        />
        <Button
          v-if="canWrite('asset_types')"
          :label="t('common.actions.create')"
          icon="pi pi-plus" 
          @click="showDialog = true" 
        />
      </div>
    </div>

    <div class="toolbar">
      <span class="p-input-icon-left search-box">
        <i class="pi pi-search" />
        <InputText v-model="search" :placeholder="t('assettypes.search')" class="w-full" />
      </span>
      <div class="toolbar-right">
        <div v-if="viewMode === 'cards' && levelGroups.length > 1" class="group-buttons">
          <Button :label="t('assettypes.view.expandAll')" icon="pi pi-plus" text size="small" @click="setAllGroups(false)" />
          <Button :label="t('assettypes.view.collapseAll')" icon="pi pi-minus" text size="small" @click="setAllGroups(true)" />
        </div>
        <SelectButton
          class="view-switch"
          v-model="viewMode"
          :options="viewOptions"
          optionLabel="label"
          optionValue="value"
          :allowEmpty="false"
          :aria-label="t('assettypes.view.label')"
        />
      </div>
    </div>

    <!-- cards: every type under its Purdue level, each level can be folded -->
    <div v-if="viewMode === 'cards'" class="cards-view" :class="{ 'is-loading': loading }">
      <p v-if="!loading && !levelGroups.length" class="cards-empty">{{ t('assettypes.view.empty') }}</p>
      <section v-for="group in levelGroups" :key="group.key" class="level-group">
        <button
          type="button"
          class="level-head"
          :aria-expanded="!isCollapsed(group.key)"
          @click="toggleGroup(group.key)"
        >
          <i :class="isCollapsed(group.key) ? 'pi pi-chevron-right' : 'pi pi-chevron-down'" aria-hidden="true"></i>
          <span class="level-title">{{ group.label }}</span>
          <span class="level-meta">{{ t('assettypes.view.groupCount', { types: group.items.length, assets: group.assets }) }}</span>
        </button>
        <div v-show="!isCollapsed(group.key)" class="card-grid">
          <article v-for="item in group.items" :key="item.id" class="type-card">
            <div class="type-card-head">
              <h3 class="type-card-name">{{ item.name }}</h3>
              <div class="type-card-actions">
                <Button
                  v-if="canWrite('asset_types')"
                  icon="pi pi-pencil"
                  class="p-button-rounded p-button-text p-button-info card-icon-btn"
                  :aria-label="t('common.actions.edit')"
                  @click="editAssetType(item)"
                />
                <Button
                  v-if="canDelete('asset_types')"
                  icon="pi pi-trash"
                  class="p-button-rounded p-button-text p-button-danger card-icon-btn"
                  :aria-label="t('common.actions.delete')"
                  @click="deleteAssetType(item.id)"
                />
              </div>
            </div>
            <p class="type-card-desc">{{ item.description || '-' }}</p>
            <div class="type-card-foot">
              <span class="type-card-label">{{ t('assettypes.fields.assets') }}</span>
              <Button
                v-if="item.asset_count > 0 && canRead('assets')"
                :label="String(item.asset_count)"
                icon="pi pi-arrow-right"
                iconPos="right"
                class="p-button-link asset-count-link"
                :aria-label="t('assettypes.showAssets', { type: item.name, count: item.asset_count })"
                @click="showAssets(item)"
              />
              <span v-else class="type-card-zero">{{ item.asset_count ?? 0 }}</span>
            </div>
          </article>
        </div>
      </section>
    </div>

    <!-- lazy: the API cuts the page, sorts and searches; the table only holds the page on screen -->
    <DataTable
      v-else
      :value="assettypes"
      :loading="loading"
      lazy
      paginator
      :first="pageFirst"
      :rows="pageRows"
      :totalRecords="totalRecords"
      :rowsPerPageOptions="[5, 10, 15, 25, 50, 100]"
      :sortField="sortField"
      :sortOrder="sortOrder"
      removableSort
      @page="onPage"
      @sort="onSort"
    >
      <Column field="name" :header="t('common.fields.name')" sortable></Column>
      <Column field="description" :header="t('common.fields.description')" sortable></Column>
      <Column field="purdue_level" :header="t('assettypes.fields.purdueLevel')" sortable>
        <template #body="{ data }">
          <span v-if="data.purdue_level !== null && data.purdue_level !== undefined">
            {{ t('assettypes.level' + (data.purdue_level === 1.5 ? '1_5' : data.purdue_level)) }}
          </span>
          <span v-else>-</span>
        </template>
      </Column>
      <Column field="asset_count" :header="t('assettypes.fields.assets')" style="width: 8rem">
        <template #body="{ data }">
          <!-- the number opens the asset list filtered on this type -->
          <Button
            v-if="data.asset_count > 0 && canRead('assets')"
            :label="String(data.asset_count)"
            class="p-button-link asset-count-link"
            :aria-label="t('assettypes.showAssets', { type: data.name, count: data.asset_count })"
            @click="showAssets(data)"
          />
          <span v-else>{{ data.asset_count ?? 0 }}</span>
        </template>
      </Column>
      <Column v-if="canWrite('asset_types') || canDelete('asset_types')" :header="t('common.strings.actions')">
        <template #body="{ data }">
          <Button 
            v-if="canWrite('asset_types')"
            icon="pi pi-pencil" 
            class="p-button-rounded p-button-text p-button-info" 
            @click="editAssetType(data)" 
          />
          <Button 
            v-if="canDelete('asset_types')"
            icon="pi pi-trash" 
            class="p-button-rounded p-button-text p-button-danger" 
            @click="deleteAssetType(data.id)" 
          />
        </template>
      </Column>
    </DataTable>

    <Dialog 
      v-model:visible="showDialog" 
      :header="t('common.actions.create')" 
      :modal="true" 
      :style="{ width: '55vw', maxWidth: '40rem' }"
    >
      <AssetTypeForm 
        :tenantId="tenantId" 
        @submit="createAssetType" 
        @cancel="showDialog = false" 
      />
    </Dialog>

    <Dialog 
      v-model:visible="editDialog" 
      :header="t('common.actions.edit')" 
      :modal="true" 
      :style="{ width: '55vw', maxWidth: '40rem' }"
    >
      <AssetTypeForm 
        :tenantId="tenantId" 
        :assettype="editingAssetType" 
        @submit="updateAssetType" 
        @cancel="onEditCancel" 
      />
    </Dialog>
    <TagRulesDialog v-model:visible="showTagRules" :can-write="canWrite('asset_types')" />
    <AssetTypeImportDialog :visible="showImportDialog" @close="showImportDialog = false" @imported="onImported" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { useI18n } from 'vue-i18n'
import { usePermissions } from '../composables/usePermissions'
import api from '../api/api'

import AssetTypeForm from '../components/forms/AssetTypeForm.vue'
import TagRulesDialog from '../components/forms/TagRulesDialog.vue'
import AssetTypeImportDialog from '../components/dialogs/AssetTypeImportDialog.vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import SelectButton from 'primevue/selectbutton'

const toast = useToast()
const showTagRules = ref(false)
const router = useRouter()
const { t, te } = useI18n()
const { canRead, canWrite, canDelete, canBulkOperate } = usePermissions()
const showImportDialog = ref(false)

const assettypes = ref([])
const loading = ref(false)
const showDialog = ref(false)
const editDialog = ref(false)
const editingAssetType = ref(null)

const tenantId = ref('...') 

const search = ref('')
let searchTimer = null

// Server-side paging state: one API call per page, page-size, sort or search change
const pageFirst = ref(0)
const pageRows = ref(15)
const totalRecords = ref(0)
const sortField = ref(null)
const sortOrder = ref(null)

// Table or cards: the choice is kept in the browser. Cards load every match at once (the API caps a page at 500),
// because the Purdue level groups need the whole list; the table keeps its server-side pages.
const VIEW_KEY = 'assetTypes.viewMode'
// cards are the default until the user picks the table
const viewMode = ref(localStorage.getItem(VIEW_KEY) === 'table' ? 'table' : 'cards')
const viewOptions = computed(() => [
  { value: 'table', label: t('assettypes.view.table') },
  { value: 'cards', label: t('assettypes.view.cards') }
])
const CARD_LIMIT = 500
const collapsed = ref({})

watch(viewMode, (mode) => {
  localStorage.setItem(VIEW_KEY, mode)
  pageFirst.value = 0
  fetchAssetTypes()
})

function levelText(level) {
  const key = 'assettypes.level' + (level === 1.5 ? '1_5' : level)
  return te(key) ? t(key) : String(level)
}

// Cards per Purdue level, lowest level first; types without a level come last. Within a level the API order (name) is kept.
const levelGroups = computed(() => {
  const byLevel = new Map()
  for (const item of assettypes.value) {
    const key = item.purdue_level === null || item.purdue_level === undefined ? 'none' : String(item.purdue_level)
    if (!byLevel.has(key)) byLevel.set(key, [])
    byLevel.get(key).push(item)
  }
  return [...byLevel.entries()]
    .sort(([a], [b]) => (a === 'none') - (b === 'none') || Number(a) - Number(b))
    .map(([key, items]) => ({
      key,
      label: key === 'none' ? t('assettypes.view.noLevel') : t('assettypes.view.levelHeading', { level: levelText(Number(key)) }),
      items,
      assets: items.reduce((sum, i) => sum + (i.asset_count || 0), 0)
    }))
})

const isCollapsed = (key) => !!collapsed.value[key]
function toggleGroup(key) {
  collapsed.value = { ...collapsed.value, [key]: !collapsed.value[key] }
}
function setAllGroups(value) {
  collapsed.value = Object.fromEntries(levelGroups.value.map(g => [g.key, value]))
}

onMounted(() => {
  fetchAssetTypes()
})

// the search runs on the server: ask again shortly after the user stops typing, from the first page
watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    pageFirst.value = 0
    fetchAssetTypes()
  }, 300)
})
onBeforeUnmount(() => clearTimeout(searchTimer))

function onPage(event) {
  pageFirst.value = event.first
  pageRows.value = event.rows
  fetchAssetTypes()
}

function onSort(event) {
  sortField.value = event.sortField || null
  sortOrder.value = event.sortField ? event.sortOrder : null
  pageFirst.value = 0
  fetchAssetTypes()
}

let fetchRequestId = 0

async function fetchAssetTypes() {
  // a response that is no longer the newest request (search, page or sort moved on) is ignored
  const requestId = ++fetchRequestId
  loading.value = true
  const cards = viewMode.value === 'cards'
  const params = cards ? { skip: 0, limit: CARD_LIMIT } : { skip: pageFirst.value, limit: pageRows.value }
  const asked = search.value.trim()
  if (asked) params.search = asked
  if (!cards && sortField.value) {
    params.sort_by = sortField.value
    params.sort_order = sortOrder.value === -1 ? 'desc' : 'asc'
  }
  try {
    const response = await api.getAssetTypesPaged(params)
    if (requestId !== fetchRequestId) return
    const body = response.data || {}
    const rows = Array.isArray(body.data) ? body.data : []
    const total = body.total ?? rows.length
    // the current page no longer exists (the last row of the last page was deleted): go back to the last one
    if (rows.length === 0 && total > 0 && pageFirst.value > 0) {
      pageFirst.value = Math.floor((total - 1) / pageRows.value) * pageRows.value
      fetchAssetTypes()
      return
    }
    assettypes.value = rows
    totalRecords.value = total
  } catch (error) {
    if (requestId !== fetchRequestId) return
    toast.add({ severity: 'error', summary: t('common.messages.error'), detail: t('assettypes.messages.fetchError'), life: 3000 })
  } finally {
    if (requestId === fetchRequestId) loading.value = false
  }
}

// The asset list already reads asset_type_id from the address, so this opens it filtered on the type
function showAssets(assettype) {
  router.push({ path: '/assets', query: { asset_type_id: assettype.id } })
}

function onImported(result) {
  showImportDialog.value = false
  const created = result?.created?.length || 0
  const updated = result?.updated?.length || 0
  const errors = result?.errors?.length || 0
  if (created || updated) {
    toast.add({ severity: 'success', summary: t('common.messages.success'), detail: t('assettypes.import.done', { created, updated, errors }), life: 4000 })
    fetchAssetTypes()
  } else if (errors) {
    toast.add({ severity: 'warn', summary: t('common.messages.warning'), detail: t('assettypes.import.failed', { errors }), life: 4000 })
  } else {
    toast.add({ severity: 'info', summary: t('common.actions.import'), detail: t('assettypes.import.nothingToDo'), life: 4000 })
  }
}

function editAssetType(assettype) {
  editingAssetType.value = { ...assettype }
  nextTick(() => editDialog.value = true)
}

function onEditCancel() {
  editDialog.value = false
  editingAssetType.value = null
}

async function createAssetType(data) {
  try {
    await api.createAssetType(data)
    toast.add({ severity: 'success', summary: t('common.messages.success'), detail: t('assettypes.messages.created'), life: 3000 })
    showDialog.value = false
    fetchAssetTypes()
  } catch (err) {
    toast.add({ severity: 'error', summary: t('common.messages.error'), detail: t('assettypes.messages.createError'), life: 3000 })
  }
}

async function updateAssetType(data) {
  try {
    await api.updateAssetType(editingAssetType.value.id, data)
    toast.add({ severity: 'success', summary: t('common.messages.updated'), detail: t('assetTypes.messages.updated'), life: 3000 })
    editDialog.value = false
    fetchAssetTypes()
  } catch (err) {
    toast.add({ severity: 'error', summary: t('common.messages.updateError'), detail: t('assetTypes.messages.updateError'), life: 3000 })
  }
}

async function deleteAssetType(id) {
  if (!confirm(t('assetTypes.deleteConfirm'))) return
  try {
    await api.deleteAssetType(id)
    toast.add({ severity: 'success', summary: t('common.messages.deleted'), detail: t('assetTypes.messages.deleted'), life: 3000 })
    fetchAssetTypes()
  } catch (err) {
    toast.add({ severity: 'error', summary: t('common.messages.deleteError'), detail: t('assetTypes.messages.deleteError'), life: 3000 })
  }
}

</script>

<style scoped>
.assettypes-page {
  padding: 0;
}
.asset-count-link {
  padding: 0;
  font-weight: 600;
}
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}
.search-box {
  display: block;
  flex: 1 1 14rem;
  max-width: 24rem;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: auto;
}
.cards-view.is-loading {
  opacity: 0.6;
}
.cards-empty {
  color: var(--text-color-secondary);
  padding: 1rem 0;
}
.level-group {
  margin-bottom: 1rem;
}
.level-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.5rem 0.25rem;
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  background: color-mix(in srgb, var(--primary-color) 8%, transparent);
  border-radius: 0 6px 6px 0;
  color: var(--text-color);
  font: inherit;
  cursor: pointer;
  text-align: left;
}
.level-head:hover {
  background: color-mix(in srgb, var(--primary-color) 14%, transparent);
}
.level-title {
  font-weight: 600;
}
.level-meta {
  margin-left: auto;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
  gap: 0.75rem;
  margin-top: 0.75rem;
}
.type-card {
  display: flex;
  flex-direction: column;
  padding: 0.75rem 1rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 0 8px 8px 0;
}
.group-buttons {
  display: flex;
  align-items: center;
  gap: 0;
}
.toolbar-right .view-switch.p-selectbutton :deep(.p-button:first-child) {
  border-radius: 6px 0 0 6px !important;
}
.toolbar-right .view-switch.p-selectbutton :deep(.p-button:last-child) {
  border-radius: 0 6px 6px 0 !important;
}
.group-buttons :deep(.p-button) {
  padding: 0.4rem 0.5rem;
}
.type-card-actions :deep(.card-icon-btn) {
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
}
.type-card-actions :deep(.card-icon-btn .p-button-icon) {
  font-size: 0.65rem;
}
.type-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}
.type-card-name {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.type-card-actions {
  display: flex;
  gap: 0.5rem;
  flex-shrink: 0;
}
.type-card-desc {
  flex: 1;
  margin: 0.25rem 0 0.75rem;
  color: var(--text-color-secondary);
  font-size: 0.9rem;
}
.type-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 0.5rem;
  border-top: 1px solid var(--surface-border);
}
.type-card-label {
  color: var(--text-color-secondary);
  font-size: 0.9rem;
}
.type-card-zero {
  font-weight: 600;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}
</style>
