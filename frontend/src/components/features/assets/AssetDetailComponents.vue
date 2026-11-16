<!--
  - AssetDetailComponents.vue
  - Parent-child view: the asset this one is a component of, and the assets that are components of it.
  - Hidden when the asset has neither.
-->
<template>
  <section v-if="asset.parent || components.length || loading" class="dcard">
    <h3 class="dcard-title">
      <span class="dcard-icon"><i class="pi pi-share-alt"></i></span>{{ t('assets.lifecycle.components.title') }}
      <span v-if="components.length" class="dcard-count">{{ components.length }}</span>
    </h3>

    <div v-if="loading" class="loader-row" role="status" aria-live="polite">
      <ProgressSpinner style="width: 1.5rem; height: 1.5rem" strokeWidth="6" /><span>{{ t('common.loading') }}</span>
    </div>

    <div v-if="asset.parent" class="component-row">
      <span class="component-label">{{ t('assets.lifecycle.components.partOf') }}</span>
      <router-link :to="`/assets/${asset.parent.id}`" class="component-link">{{ asset.parent.name }}</router-link>
    </div>

    <div v-if="components.length" class="component-row">
      <span class="component-label">{{ t('assets.lifecycle.components.hasComponents') }}</span>
      <span class="component-list">
        <router-link v-for="c in components" :key="c.id" :to="`/assets/${c.id}`" class="component-link">{{ c.name }}</router-link>
      </span>
    </div>
  </section>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/api/api'
import ProgressSpinner from 'primevue/progressspinner'

const props = defineProps({
  asset: { type: Object, required: true }
})

const { t } = useI18n()
const components = ref([])
const loading = ref(false)

watch(
  () => props.asset?.id,
  async (id) => {
    components.value = []
    if (!id) return
    loading.value = true
    try {
      const res = await api.getAssetComponents(id)
      if (props.asset?.id === id) components.value = Array.isArray(res.data) ? res.data : []
    } catch (e) {
      components.value = []
    } finally {
      if (props.asset?.id === id) loading.value = false
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.loader-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.75rem 0; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
.component-row { display: flex; gap: 1rem; align-items: baseline; padding: 0.35rem 0; }
.component-label {
  flex: 0 0 9rem;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--sk-text-muted, #6b7a71);
}
.component-list { display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; }
.component-link { color: var(--sk-primary, #2f6f4f); font-weight: 500; text-decoration: none; }
.component-link:hover { text-decoration: underline; }
</style>
