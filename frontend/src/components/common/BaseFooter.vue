<template>
  <footer class="footer" role="contentinfo" aria-label="Footer dell'applicazione">
    <div class="footer-content">
      <div class="footer-info">
        <span class="version">v{{ version }}</span>
        <span class="separator">•</span>
        <span class="copyright">{{ copyrightText }}</span>
      </div>
    </div>
  </footer>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { appConfig } from '@/config/app'

const { t } = useI18n()

const version = appConfig.version
const currentYear = new Date().getFullYear()

const copyrightText = computed(() =>
  t('footer.copyright', { year: currentYear })
)
</script>

<style scoped>
.footer {
  width: 100%;
  background: #f8f9fa;
  border-top: 1px solid #e9ecef;
  padding: 1rem 0;
  margin-top: auto;
}

.footer-content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 2rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  align-items: center;
}

.footer-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  justify-content: center;
}

.version {
  font-size: 0.7rem;
  color: #6c757d;
  font-weight: 400;
}

.copyright {
  font-size: 0.7rem;
  color: #6c757d;
}

.separator {
  color: #adb5bd;
  font-size: 0.7rem;
}

/* Responsive design */
@media (max-width: 768px) {
  .footer-content {
    padding: 0 1rem;
    gap: 0.5rem;
  }

  .footer-info {
    flex-direction: column;
    gap: 0.25rem;
  }

  .separator {
    display: none;
  }
}

@media (max-width: 480px) {
  .footer {
    padding: 0.75rem 0;
  }
}
</style>
