<!--
  - AssetArchivedBanner.vue
  - Shown on a retired asset whose record was archived by the retirement workflow. The record is
  - read-only; a person with lifecycle level 3 can reopen it with a reason (written to the audit log).
-->
<template>
  <Message v-if="asset.archived_at" severity="info" :closable="false" class="archived-banner">
    <div class="banner-body">
      <span>{{ t('assets.archived.text', { date: formatDate(asset.archived_at) }) }}</span>
      <Button v-if="canDelete('lifecycle')" :label="t('assets.archived.reopen')" icon="pi pi-unlock" size="small" text @click="open = true" />
    </div>
  </Message>

  <Dialog v-model:visible="open" modal :header="t('assets.archived.reopenTitle')" :style="{ width: '30rem', maxWidth: '95vw' }">
    <p class="hint">{{ t('assets.archived.reopenHint') }}</p>
    <Message v-if="error" severity="error" :closable="false">{{ error }}</Message>
    <label for="reopen_reason">{{ t('assets.archived.reason') }}</label>
    <Textarea id="reopen_reason" v-model="reason" rows="3" maxlength="2000" class="w-full" />
    <template #footer>
      <Button :label="t('common.actions.cancel')" text severity="secondary" @click="open = false" />
      <Button :label="t('assets.archived.reopen')" icon="pi pi-unlock" :loading="busy" :disabled="reason.trim().length < 5" @click="reopen" />
    </template>
  </Dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Message from 'primevue/message'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import Textarea from 'primevue/textarea'
import api from '@/api/api'
import { usePermissions } from '../../../composables/usePermissions'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({
  asset: { type: Object, required: true }
})
const emit = defineEmits(['changed'])

const { t } = useI18n()
const { canDelete } = usePermissions()
const { formatDate } = useDateFormatter()
const open = ref(false)
const reason = ref('')
const busy = ref(false)
const error = ref('')

async function reopen() {
  busy.value = true
  error.value = ''
  try {
    await api.reopenArchivedAsset(props.asset.id, reason.value.trim())
    open.value = false
    reason.value = ''
    emit('changed')
  } catch (err) {
    error.value = apiErrorText(err, t)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.archived-banner { margin: 0 0 1rem; }
.banner-body { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; width: 100%; }
.hint { margin: 0 0 0.75rem; color: var(--sk-text-muted, #6b7a71); font-size: 0.9rem; }
label { display: block; margin-bottom: 0.35rem; font-weight: 500; }
</style>
