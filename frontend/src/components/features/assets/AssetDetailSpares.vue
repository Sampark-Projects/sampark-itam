<!--
  - AssetDetailSpares.vue
  - Spare assets kept for this installed asset, and the installed assets this one is a spare for.
-->
<template>
  <section v-if="spares.length || spareFor.length || editable" class="dcard">
    <h3 class="dcard-title">
      <span class="dcard-icon"><i class="pi pi-box"></i></span>{{ t('assets.spares.title') }}
      <span v-if="spares.length" class="dcard-count">{{ spares.length }}</span>
    </h3>
    <p v-if="error" class="err">{{ error }}</p>

    <div class="spare-row">
      <span class="spare-label">{{ t('assets.spares.keptFor') }}</span>
      <span v-if="!editing" class="spare-list">
        <router-link v-for="s in spares" :key="s.id" :to="`/assets/${s.id}`" class="spare-link">
          {{ s.name }}<small v-if="s.status"> · {{ s.status }}</small>
        </router-link>
        <span v-if="!spares.length" class="muted">{{ t('assets.spares.none') }}</span>
        <Button v-if="editable" icon="pi pi-pencil" text rounded size="small" :aria-label="t('assets.spares.edit')"
                v-tooltip.top="t('assets.spares.edit')" @click="startEdit" />
      </span>
      <span v-else class="spare-edit">
        <AssetParentPicker v-model="adding" :exclude-id="asset.id" :placeholder="t('assets.spares.pick')" />
        <Button :label="t('assets.spares.add')" icon="pi pi-plus" size="small" text :disabled="!adding" @click="addPicked" />
        <span class="chips">
          <span v-for="s in draft" :key="s.id" class="chip">
            {{ s.name }}
            <button type="button" class="chip-x" :aria-label="t('common.actions.delete')" @click="draft = draft.filter(d => d.id !== s.id)">×</button>
          </span>
        </span>
        <span class="actions">
          <Button :label="t('common.actions.save')" icon="pi pi-save" size="small" :loading="saving" @click="save" />
          <Button :label="t('common.actions.cancel')" size="small" text severity="secondary" @click="editing = false" />
        </span>
      </span>
    </div>

    <div v-if="spareFor.length" class="spare-row">
      <span class="spare-label">{{ t('assets.spares.spareFor') }}</span>
      <span class="spare-list">
        <router-link v-for="s in spareFor" :key="s.id" :to="`/assets/${s.id}`" class="spare-link">{{ s.name }}</router-link>
      </span>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from 'primevue/button'
import api from '@/api/api'
import AssetParentPicker from '../../forms/AssetParentPicker.vue'
import { usePermissions } from '../../../composables/usePermissions'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({
  asset: { type: Object, required: true }
})

const { t } = useI18n()
const { canWrite } = usePermissions()
const editable = computed(() => canWrite('lifecycle') && !props.asset.archived_at)

const spares = ref([])
const spareFor = ref([])
const error = ref('')
const editing = ref(false)
const draft = ref([])
const adding = ref(null)
const saving = ref(false)

async function load(id) {
  error.value = ''
  try {
    const res = await api.getAssetSpares(id)
    if (props.asset?.id !== id) return
    spares.value = res.data.spares || []
    spareFor.value = res.data.spare_for || []
  } catch (err) {
    spares.value = []
    spareFor.value = []
  }
}

function startEdit() {
  draft.value = spares.value.map(s => ({ id: s.id, name: s.name }))
  adding.value = null
  editing.value = true
}

async function addPicked() {
  const id = adding.value
  if (!id || draft.value.some(d => d.id === id)) {
    adding.value = null
    return
  }
  let name = id
  try {
    name = (await api.getAsset(id)).data.name || id
  } catch (e) {
    // keep the id as the label
  }
  draft.value = [...draft.value, { id, name }]
  adding.value = null
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    const res = await api.setAssetSpares(props.asset.id, draft.value.map(d => d.id))
    spares.value = res.data.spares || []
    spareFor.value = res.data.spare_for || []
    editing.value = false
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    saving.value = false
  }
}

watch(() => props.asset?.id, (id) => { if (id) load(id) }, { immediate: true })
</script>

<style scoped>
.spare-row { display: flex; gap: 1rem; align-items: baseline; padding: 0.35rem 0; flex-wrap: wrap; }
.spare-label {
  flex: 0 0 9rem;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--sk-text-muted, #6b7a71);
}
.spare-list { display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; align-items: center; }
.spare-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; }
.spare-link:hover { text-decoration: underline; }
.spare-link small { color: var(--sk-text-muted, #6b7a71); font-weight: 400; }
.spare-edit { display: flex; flex-direction: column; gap: 0.5rem; flex: 1; min-width: 16rem; }
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.chip { background: var(--sk-surface-2, #eef3f0); border-radius: 1rem; padding: 0.15rem 0.6rem; font-size: 0.85rem; }
.chip-x { border: 0; background: none; cursor: pointer; margin-left: 0.25rem; font-size: 1rem; line-height: 1; }
.actions { display: flex; gap: 0.5rem; }
.muted { color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.err { color: var(--red-600, #c0392b); margin: 0 0 0.5rem; }
</style>
