<template>
  <div class="recent-changes-list">
    <div v-if="loading" class="loading">
      <i class="pi pi-spin pi-spinner"></i>
    </div>
    <div v-else-if="changes.length === 0" class="no-data">
      {{ t('dashboard.change.noRecentChanges') }}
    </div>
    <div v-else class="changes-container">
      <!-- Compact rows: about 3 are visible, the rest scrolls -->
      <div class="changes-scroll">
        <div
          v-for="change in changes"
          :key="change.asset_id"
          class="change-item"
        >
          <div class="change-icon">
            <i :class="change.change_type === 'created' ? 'pi pi-plus-circle' : 'pi pi-sync'"></i>
          </div>
          <!-- Updated / duration come first, then the asset name -->
          <div class="change-meta">
            <span class="change-type">
              {{ change.change_type === 'created' ? t('dashboard.change.created') : t('dashboard.change.updated') }}
            </span>
            <span class="change-time">{{ formatTimeAgo(change.timestamp) }}</span>
          </div>
          <router-link :to="`/assets/${change.asset_id}`" class="change-link">
            {{ change.asset_name }}
          </router-link>
        </div>
      </div>
      <div class="view-all">
        <router-link :to="viewAllLink" class="view-all-link">
          {{ t('dashboard.actions.viewAll') }}
          <i class="pi pi-arrow-right"></i>
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  changes: {
    type: Array,
    default: () => []
  },
  loading: {
    type: Boolean,
    default: false
  }
})

const viewAllLink = computed(() => {
  // Link to assets page (sorted by updated_at desc to show recent changes first)
  return '/assets?sort=updated_at&order=desc'
})

const formatTimeAgo = (timestamp) => {
  if (!timestamp) return ''
  
  const now = new Date()
  const time = new Date(timestamp)
  const diffMs = now - time
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)
  
  if (diffMins < 1) {
    return t('dashboard.change.justNow')
  } else if (diffMins < 60) {
    return t('dashboard.change.minutesAgo', { count: diffMins })
  } else if (diffHours < 24) {
    return t('dashboard.change.hoursAgo', { count: diffHours })
  } else {
    return t('dashboard.change.daysAgo', { count: diffDays })
  }
}
</script>

<style scoped>
.recent-changes-list {
  min-height: 0;
}

.loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  color: #6b7a71;
}

.loading i {
  font-size: 1.5rem;
}

.no-data {
  text-align: center;
  padding: 1rem;
  color: #6b7a71;
  font-style: italic;
}

.changes-container {
  display: flex;
  flex-direction: column;
}

/* Height of exactly 3 rows (each row is 2.4rem tall): further rows scroll */
.changes-scroll {
  max-height: 7.2rem;
  overflow-y: auto;
  scrollbar-width: thin;
}

.change-item {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  height: 2.4rem;
  padding: 0 0.5rem;
  border-bottom: 1px solid #e1e7e3;
  transition: background 0.15s ease;
}

.change-item:last-child {
  border-bottom: 0;
}

.change-item:hover {
  background: #f7faf8;
}

.change-icon {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #e8f0eb;
  color: #1d6838;
  font-size: 0.75rem;
  flex-shrink: 0;
}

.change-link {
  flex: 1;
  min-width: 0;
  font-size: 0.85rem;
  font-weight: 500;
  color: #1d6838;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.change-link:hover {
  color: #154f2a;
  text-decoration: underline;
}

.change-meta {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-shrink: 0;
  min-width: 9.5rem;
  font-size: 0.75rem;
  color: #6b7a71;
  white-space: nowrap;
}

.change-type {
  text-transform: capitalize;
  font-weight: 500;
}

.change-time {
  color: #8a988f;
}

.view-all {
  margin-top: 0.25rem;
  padding-top: 0.5rem;
  border-top: 1px solid #e1e7e3;
}

.view-all-link {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: #1d6838;
  text-decoration: none;
  font-weight: 600;
  font-size: 0.875rem;
  transition: gap 0.2s ease;
}

.view-all-link:hover {
  gap: 0.75rem;
  text-decoration: none;
}
</style>

