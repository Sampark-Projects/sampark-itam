<template>
  <router-link :to="clickAction" class="dashboard-card" :class="severityClass">
    <div class="card-head">
      <i :class="['card-icon', icon]"></i>
      <span class="card-label">{{ label }}</span>
    </div>
    <div class="card-body">
      <div class="card-main">
        <div class="card-value">{{ formattedValue }}</div>
        <div v-if="subtitle" class="card-subtitle">{{ subtitle }}</div>
      </div>
      <i class="pi pi-arrow-right card-arrow"></i>
    </div>
  </router-link>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: {
    type: [Number, String],
    required: true
  },
  label: {
    type: String,
    required: true
  },
  subtitle: {
    type: String,
    default: null
  },
  icon: {
    type: String,
    required: true
  },
  severity: {
    type: String,
    default: 'info', // info, warning, danger, success
    validator: (value) => ['info', 'warning', 'danger', 'success'].includes(value)
  },
  clickAction: {
    type: String,
    required: true
  }
})

const formattedValue = computed(() => {
  if (typeof props.value === 'number') {
    // Format large numbers
    if (props.value >= 1000) {
      return (props.value / 1000).toFixed(1) + 'k'
    }
    return props.value.toString()
  }
  return props.value
})

const severityClass = computed(() => {
  return `severity-${props.severity}`
})
</script>

<style scoped>
/* Stat card: tinted header band (icon + title) over a white body with the number */
.dashboard-card {
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 1px 8px rgba(24, 54, 36, 0.08);
  text-decoration: none;
  color: inherit;
  overflow: hidden;
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}

.dashboard-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(24, 54, 36, 0.14);
  text-decoration: none;
  color: inherit;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.85rem 1.1rem;
  background: var(--head-bg);
}

.card-icon {
  font-size: 1.15rem;
  color: var(--head-icon);
}

.card-label {
  font-size: 0.92rem;
  font-weight: 500;
  color: #25332b;
  line-height: 1.3;
}

.card-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1rem 1.1rem 1.15rem;
  flex: 1;
}

.card-main {
  min-width: 0;
}

.card-value {
  font-size: 2rem;
  font-weight: 500;
  color: #1f2d25;
  line-height: 1.1;
}

.card-subtitle {
  margin-top: 0.4rem;
  font-size: 0.75rem;
  color: #6b7a71;
  line-height: 1.4;
}

.card-arrow {
  color: #8a988f;
  font-size: 1.05rem;
  flex-shrink: 0;
  transition: transform 0.2s ease, color 0.2s ease;
}

.dashboard-card:hover .card-arrow {
  transform: translateX(4px);
  color: #1d6838;
}

/* Pastel header tints (lavender / mint / yellow / peach) */
.severity-info    { --head-bg: #f1f0fb; --head-icon: #5b5bd6; }
.severity-success { --head-bg: #edf9f2; --head-icon: #23a26d; }
.severity-warning { --head-bg: #fbf8e3; --head-icon: #d19a00; }
.severity-danger  { --head-bg: #fdf0ec; --head-icon: #e5484d; }

@media (max-width: 768px) {
  .card-value {
    font-size: 1.6rem;
  }
}
</style>
