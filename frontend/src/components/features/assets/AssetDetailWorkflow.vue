<!--
  - AssetDetailWorkflow.vue
  - Lifecycle workflow of one asset: start onboarding or retirement, see the steps, and complete,
  - approve or reject the current step when the user's role allows it.
-->
<template>
  <section class="dcard">
    <h3 class="dcard-title">
      <span class="dcard-icon"><i class="pi pi-sitemap"></i></span>{{ t('workflows.card.title') }}
      <span v-if="active" class="dcard-count">{{ t(`workflows.kinds.${active.kind}`) }}</span>
    </h3>

    <p v-if="error" class="p-error">{{ error }}</p>

    <!-- nothing running -->
    <div v-if="!active">
      <p class="muted">{{ t('workflows.card.none') }}</p>
      <div v-if="canWrite('lifecycle')" class="flex gap-2 flex-wrap">
        <Button :label="t('workflows.card.startOnboarding')" icon="pi pi-play" severity="secondary" outlined :loading="busy" @click="start('onboarding')" />
        <Button :label="t('workflows.card.startRetirement')" icon="pi pi-power-off" severity="secondary" outlined :loading="busy" @click="start('retirement')" />
      </div>
    </div>

    <!-- open run -->
    <div v-else>
      <p class="muted">{{ active.workflow_name }} · {{ t('workflows.card.startedBy', { name: active.started_by || '-' }) }} · {{ formatDate(active.started_at) }}</p>
      <ol class="steps">
        <li v-for="s in active.steps" :key="s.id" :class="['step', `step-${s.state}`, { current: s.is_current }]">
          <span class="step-marker"><i :class="markerIcon(s)"></i></span>
          <div class="step-body">
            <div class="step-head">
              <strong>{{ s.name }}</strong>
              <Tag :value="t(`workflows.stepTypes.${s.step_type}`)" severity="secondary" class="type-tag" />
              <small v-if="s.role_name" class="muted">{{ s.role_name }}</small>
            </div>
            <small v-if="s.description" class="muted">{{ s.description }}</small>
            <small v-if="s.state !== 'pending'" class="muted block">
              {{ t('workflows.card.actedBy', { name: s.acted_by || '-', date: formatDate(s.acted_at) }) }}
              <span v-if="s.overridden"> · {{ t('workflows.card.override') }}</span>
            </small>
            <small v-if="s.comment" class="comment block">“{{ s.comment }}”</small>

            <!-- what the person can do on the current step -->
            <div v-if="s.is_current" class="current-panel">
              <template v-if="s.can_act">
                <div v-if="s.blockers && s.blockers.length" class="blockers">
                  <span>{{ t('workflows.card.missing') }}</span>
                  <ul><li v-for="b in s.blockers" :key="b">{{ blockerLabel(b, t) }}</li></ul>
                </div>
                <label v-if="s.confirm_statement" class="confirm">
                  <Checkbox v-model="confirmed" binary />
                  <span>{{ s.confirm_statement }}</span>
                </label>
                <Textarea v-model="comment" rows="2" autoResize class="w-full" :placeholder="t('workflows.card.comment') + (s.requires_comment ? ' *' : '')" />
                <div class="flex gap-2 mt-2 flex-wrap">
                  <Button :label="s.step_type === 'approval' ? t('workflows.card.approve') : t('workflows.card.complete')" icon="pi pi-check" :loading="busy" @click="act(s, 'complete')" />
                  <Button v-if="s.step_type === 'approval'" :label="t('workflows.card.reject')" icon="pi pi-times" severity="danger" outlined :loading="busy" @click="act(s, 'reject')" />
                </div>
              </template>
              <p v-else-if="s.self_approval_blocked" class="muted">{{ t('workflows.card.selfApproval') }}</p>
              <p v-else class="muted">{{ t('workflows.card.notYours', { role: s.role_name || t('workflows.card.anyone') }) }}</p>
            </div>
          </div>
        </li>
      </ol>
      <Button v-if="canWrite('lifecycle')" :label="t('workflows.card.cancel')" icon="pi pi-ban" text severity="secondary" size="small" @click="cancel" />
    </div>

    <!-- history -->
    <div v-if="history.length" class="history">
      <h4>{{ t('workflows.card.history') }}</h4>
      <ul>
        <li v-for="r in history" :key="r.id">
          <strong>{{ r.workflow_name }}</strong>
          <Tag :value="t(`workflows.states.${r.status}`)" :severity="r.status === 'completed' ? 'success' : (r.status === 'rejected' ? 'danger' : 'secondary')" class="type-tag" />
          <small class="muted"> {{ t('workflows.card.finished', { result: '', date: formatDate(r.finished_at) }).trim() }}</small>
          <small v-if="r.finish_note" class="muted block">{{ r.finish_note }}</small>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import Textarea from 'primevue/textarea'
import Checkbox from 'primevue/checkbox'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { apiErrorText } from '../../../utils/money'
import { blockerLabel, blockersFromDetail } from '../../../utils/workflowFields'

const props = defineProps({
  asset: { type: Object, required: true }
})
// the page reloads the asset after a step so statuses and fields shown elsewhere stay current
const emit = defineEmits(['changed'])

const { t } = useI18n()
const { canWrite } = usePermissions()
const { formatDate } = useDateFormatter()

const runs = ref([])
const error = ref('')
const busy = ref(false)
const comment = ref('')
const confirmed = ref(false)

const active = computed(() => runs.value.find(r => r.status === 'in_progress') || null)
const history = computed(() => runs.value.filter(r => r.status !== 'in_progress'))

function markerIcon(step) {
  if (step.state === 'done') return 'pi pi-check-circle'
  if (step.state === 'rejected') return 'pi pi-times-circle'
  return step.is_current ? 'pi pi-circle-fill' : 'pi pi-circle'
}

async function load() {
  if (!props.asset?.id) return
  try {
    const res = await api.getAssetWorkflowRuns(props.asset.id)
    runs.value = Array.isArray(res.data) ? res.data : []
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

function resetInputs() {
  comment.value = ''
  confirmed.value = false
}

async function start(kind) {
  error.value = ''
  busy.value = true
  try {
    await api.startWorkflowRun(props.asset.id, { kind })
    resetInputs()
    await load()
    emit('changed')
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    busy.value = false
  }
}

async function act(step, action) {
  error.value = ''
  if (action === 'reject' && !comment.value.trim()) {
    error.value = t('workflows.card.rejectNeedsComment')
    return
  }
  busy.value = true
  try {
    const payload = { comment: comment.value || null, confirmed: confirmed.value }
    if (action === 'reject') await api.rejectWorkflowStep(active.value.id, step.id, payload)
    else await api.completeWorkflowStep(active.value.id, step.id, payload)
    resetInputs()
    await load()
    emit('changed')
  } catch (err) {
    const blockers = blockersFromDetail(err?.response?.data?.message || err?.response?.data?.detail)
    error.value = blockers.length
      ? `${t('workflows.card.missing')} ${blockers.map(b => blockerLabel(b, t)).join(', ')}`
      : apiErrorText(err, t)
    await load()
  } finally {
    busy.value = false
  }
}

async function cancel() {
  if (!window.confirm(t('workflows.card.cancelConfirm'))) return
  error.value = ''
  busy.value = true
  try {
    await api.cancelWorkflowRun(active.value.id, {})
    resetInputs()
    await load()
    emit('changed')
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    busy.value = false
  }
}

// reload when the asset changes (the blockers depend on its fields and documents)
watch(
  () => [props.asset?.id, props.asset?.updated_at, props.asset?.status_id],
  load,
  { immediate: true }
)
</script>

<style scoped>
.muted { color: var(--sk-text-muted, #6b7a71); font-size: 0.85rem; margin: 0 0 0.5rem; }
.block { display: block; }
.steps { list-style: none; margin: 0 0 0.75rem; padding: 0; }
.step { display: flex; gap: 0.75rem; padding: 0.5rem 0; border-top: 1px solid var(--sk-border, #e1e7e3); }
.step:first-child { border-top: 0; }
.step-marker { flex: 0 0 1.25rem; padding-top: 0.15rem; color: #aab4ae; }
.step-done .step-marker { color: #2f6f4f; }
.step-rejected .step-marker { color: #b3261e; }
.step.current .step-marker { color: var(--sk-primary, #2f6f4f); }
.step-body { flex: 1; min-width: 0; }
.step-head { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.type-tag { font-size: 0.7rem; }
.comment { font-style: italic; color: var(--sk-text-muted, #6b7a71); margin-top: 0.2rem; }
.current-panel { margin-top: 0.6rem; padding: 0.75rem; border-radius: 8px; background: #f4f8f5; }
.blockers { margin-bottom: 0.6rem; font-size: 0.85rem; color: #b26a00; }
.blockers ul { margin: 0.25rem 0 0; padding-left: 1.1rem; }
.confirm { display: flex; align-items: flex-start; gap: 0.5rem; margin-bottom: 0.6rem; font-size: 0.9rem; }
.history { margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--sk-border, #e1e7e3); }
.history h4 { margin: 0 0 0.4rem; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--sk-text-muted, #6b7a71); }
.history ul { list-style: none; margin: 0; padding: 0; }
.history li { margin-bottom: 0.4rem; }
</style>
