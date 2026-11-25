<!--
  - ApplicationSecurityTab.vue
  - VAPT and vulnerabilities of an application: a summary strip, the VAPT assessments, and the findings
  - with remediation and deadlines.
-->
<template>
  <div>
    <Message v-if="error" severity="error" :closable="true" @close="error = ''">{{ error }}</Message>

    <div class="summary">
      <div v-for="s in SEVERITIES" :key="s" class="stat" :class="`sev-${s}`">
        <strong>{{ summary ? summary.open[s] : '-' }}</strong>
        <span>{{ t(`applications.security.severities.${s}`) }}</span>
      </div>
      <div class="stat" :class="{ bad: summary && summary.overdue }">
        <strong>{{ summary ? summary.overdue : '-' }}</strong><span>{{ t('applications.security.overdue') }}</span>
      </div>
      <div class="stat" :class="{ bad: summary && summary.exceptions_expired }">
        <strong>{{ summary ? summary.exceptions_expired : '-' }}</strong><span>{{ t('applications.security.exceptionsExpired') }}</span>
      </div>
      <div class="stat wide">
        <strong>{{ summary && summary.last_vapt_date ? formatDate(summary.last_vapt_date) : t('applications.none') }}</strong>
        <span>{{ t('applications.security.lastVapt') }}</span>
      </div>
      <div class="stat wide" :class="{ bad: summary && summary.next_vapt_overdue }">
        <strong>{{ summary && summary.next_vapt_due ? formatDate(summary.next_vapt_due) : t('applications.none') }}</strong>
        <span>{{ t('applications.security.nextVapt') }}</span>
      </div>
    </div>

    <TabView lazy class="sub-tabs">
      <TabPanel :header="t('applications.security.tabVapt')">
        <ApplicationVaptAssessments :application-id="applicationId" @changed="reload" />
      </TabPanel>
      <TabPanel :header="t('applications.security.tabFindings')">
        <ApplicationFindings :application-id="applicationId" @changed="loadSummary" />
      </TabPanel>
    </TabView>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import TabView from 'primevue/tabview'
import TabPanel from 'primevue/tabpanel'
import Message from 'primevue/message'
import api from '@/api/api'
import ApplicationVaptAssessments from './ApplicationVaptAssessments.vue'
import ApplicationFindings from './ApplicationFindings.vue'
import { useDateFormatter } from '../../../composables/useDateFormatter'
import { apiErrorText } from '../../../utils/money'

const props = defineProps({ applicationId: { type: String, required: true } })
const { t } = useI18n()
const { formatDate } = useDateFormatter()

const SEVERITIES = ['critical', 'high', 'medium', 'low']
const summary = ref(null)
const error = ref('')

async function loadSummary() {
  try {
    summary.value = (await api.getApplicationSecuritySummary(props.applicationId)).data
  } catch (err) {
    error.value = apiErrorText(err, t)
  }
}

const reload = loadSummary
onMounted(loadSummary)
</script>

<style scoped>
.summary { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 1rem; }
.stat { min-width: 5.5rem; padding: 0.55rem 0.8rem; border: 1px solid var(--sk-border, #e1e7e3); border-radius: 8px; display: flex; flex-direction: column; background: var(--sk-surface, #fff); }
.stat strong { font-size: 1.3rem; line-height: 1.2; }
.stat span { font-size: 0.78rem; color: var(--sk-text-muted, #6b7a71); }
.stat.wide { min-width: 9rem; }
.stat.bad { border-color: #dc2626; }
.stat.bad strong { color: #dc2626; }
.sev-critical strong { color: #b91c1c; }
.sev-high strong { color: #ea580c; }
.sev-medium strong { color: #ca8a04; }
</style>
