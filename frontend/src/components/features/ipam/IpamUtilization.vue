<!--
  - IpamUtilization.vue
  - A small bar with the percent used.
-->
<template>
  <div class="util" :title="`${value}%`">
    <div class="track"><div class="fill" :style="{ width: Math.min(value, 100) + '%', background: utilizationColor(value) }"></div></div>
    <span class="num">{{ value }}%</span>
  </div>
</template>

<script setup>
import { utilizationColor } from '../../../composables/useIpam'

defineProps({ value: { type: Number, default: 0 } })
</script>

<style scoped>
.util { display: flex; align-items: center; gap: 0.5rem; min-width: 7rem; }
.track { flex: 1; height: 0.55rem; background: var(--sk-border, #e1e7e3); border-radius: 4px; overflow: hidden; }
.fill { height: 100%; border-radius: 4px; }
.num { font-size: 0.8rem; min-width: 2.6rem; text-align: right; }
</style>
