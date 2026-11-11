<template>
  <div class="section-header">
    <div class="header-icon">
      <i :class="icon"></i>
    </div>
    <div class="header-content">
      <h2 class="header-title">{{ title }}</h2>
      <p class="header-description">{{ description }}</p>
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: {
    type: String,
    required: true
  },
  description: {
    type: String,
    required: true
  },
  icon: {
    type: String,
    required: true
  }
})
</script>

<style scoped>
/* Section heading like "Recent Activity": dark-green title over a thin divider */
.section-header {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  margin-bottom: 1.25rem;
  padding-bottom: 0.85rem;
  border-bottom: 1px solid #dde4df;
}

/* Solid brand-green disc with a white icon so it stands out on the pale page background */
.header-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  background: #1d6838;
  color: #ffffff;
  box-shadow: 0 2px 6px rgba(29, 104, 56, 0.35);
  flex-shrink: 0;
}

.header-content {
  flex: 1;
}

.header-title {
  margin: 0;
  font-size: 1.3rem;
  font-weight: 600;
  color: #174d2d;
}

.header-description {
  margin: 0.1rem 0 0;
  font-size: 0.82rem;
  color: #6b7a71;
  line-height: 1.5;
}

@media (max-width: 768px) {
  .section-header {
    flex-direction: column;
    gap: 0.75rem;
  }
  
  .header-title {
    font-size: 1.25rem;
  }
}
</style>

