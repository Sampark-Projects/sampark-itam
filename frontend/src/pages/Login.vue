<template>
  <div class="login-container">
    <!-- Background con pattern geometrico -->
    <div class="login-background">
      <div class="background-pattern"></div>
      <div class="background-overlay"></div>
    </div>

    <!-- Container principale -->
    <div class="login-content">
      <!-- Logo -->
      <div class="login-brand">
        <div class="logo-container">
          <img src="@/static/sampark_logo.png" alt="Sampark" class="login-logo" />
        </div>
      </div>

      <!-- Form di login -->
      <div class="login-form-container">
        <div class="form-card">
          <div class="form-header">
            <h2>{{ $t('login.strings.signIn') }}</h2>
            <p>{{ $t('login.strings.enterCredentials') }}</p>
          </div>

          <form @submit.prevent="handleSubmit" class="login-form">
            <div class="form-group">
              <label for="email" class="form-label">
                {{ $t('login.strings.email') }}
              </label>
              <div class="input-wrapper">
                <InputText 
                  id="email" 
                  v-model="email" 
                  type="email" 
                  required 
                  class="form-input"
                  :placeholder="$t('login.strings.emailPlaceholder')"
                  :class="{ 'p-invalid': emailError }"
                />
                <div class="input-icon">
                  <i class="pi pi-envelope"></i>
                </div>
              </div>
              <small v-if="emailError" class="error-message">{{ emailError }}</small>
            </div>

            <div class="form-group">
              <label for="password_input" class="form-label">
                {{ $t('login.strings.password') }}
              </label>
              <div class="input-wrapper">
                <Password 
                  id="password" 
                  v-model="password" 
                  :feedback="false" 
                  required 
                  toggleMask
                  :placeholder="$t('login.strings.passwordPlaceholder')"
                  :inputClass="{ 'p-invalid': passwordError }"
                  inputId="password_input"
                />
                <div class="input-icon">
                  <i class="pi pi-lock"></i>
                </div>
              </div>
              <small v-if="passwordError" class="error-message">{{ passwordError }}</small>
            </div>

            <div class="form-options">
              <div class="remember-me">
                <Checkbox 
                  v-model="rememberMe" 
                  :binary="true" 
                  :inputId="'remember'"
                />
                <label for="remember" class="checkbox-label">{{ $t('login.strings.rememberMe') }}</label>
              </div>
            </div>

            <Button 
              type="submit" 
              :label="$t('login.strings.submit')" 
              :loading="loading" 
              class="login-button"
              :disabled="!isFormValid"
            />

            <!-- SSO Login Button -->
            <div v-if="ssoEnabled" class="sso-section">
              <div class="divider">
                <span>{{ $t('login.strings.or') }}</span>
              </div>
              <Button 
                :label="ssoButtonLabel" 
                :icon="ssoProvider.value === 'google' ? 'pi pi-google' : ssoProvider.value === 'okta' ? 'pi pi-key' : 'pi pi-microsoft'"
                @click="handleSSOLogin"
                class="sso-button"
                :loading="ssoLoading"
              />
            </div>

          </form>
        </div>
      </div>
    </div>

    <!-- Toast per notifiche -->
    <Toast position="top-right" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { useAuthStore } from '../store/auth'
import { useI18n } from 'vue-i18n'
import api from '../api/api'

import Card from 'primevue/card'
import InputText from 'primevue/inputtext'
import Password from 'primevue/password'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import Toast from 'primevue/toast'

const email = ref('')
const password = ref('')
const rememberMe = ref(false)
const loading = ref(false)

const emailError = ref('')
const passwordError = ref('')

const ssoEnabled = ref(false)
const ssoProvider = ref(null)
const ssoLoading = ref(false)

const toast = useToast()
const authStore = useAuthStore()
const router = useRouter()
const { t } = useI18n()

// Check SSO availability on mount
onMounted(async () => {
  try {
    const response = await api.checkSSOEnabled()
    ssoEnabled.value = response.data.enabled || false
    ssoProvider.value = response.data.provider || null
  } catch (error) {
    console.error('Error checking SSO availability:', error)
    ssoEnabled.value = false
  }
})

const ssoButtonLabel = computed(() => {
  if (ssoProvider.value === 'azure_ad') {
    return t('login.strings.loginWithMicrosoft')
  } else if (ssoProvider.value === 'google') {
    return t('login.strings.loginWithGoogle')
  } else if (ssoProvider.value === 'okta') {
    return t('login.strings.loginWithOkta')
  }
  return t('login.strings.loginWithSSO')
})

const handleSSOLogin = () => {
  ssoLoading.value = true
  try {
    // Redirect directly to SSO authorization endpoint
    // The backend will handle tenant detection and redirect to provider
    const provider = ssoProvider.value || 'azure_ad'
    window.location.href = `/api/auth/sso/${provider}/authorize`
  } catch (error) {
    console.error('SSO login error:', error)
    toast.add({
      severity: 'error',
      summary: t('common.messages.error'),
      detail: error.response?.data?.detail || t('login.messages.ssoError'),
      life: 5000
    })
    ssoLoading.value = false
  }
}


// Validazione form
const isFormValid = computed(() => {
  return email.value.trim() !== '' && password.value.trim() !== ''
})

// Validazione email
const validateEmail = (email) => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  return emailRegex.test(email)
}

const handleSubmit = async () => {
  // Reset errori
  emailError.value = ''
  passwordError.value = ''

  // Validazione
  if (!email.value.trim()) {
    emailError.value = t('login.messages.emailRequired')
    return
  }

  if (!validateEmail(email.value)) {
    emailError.value = t('login.messages.emailInvalid')
    return
  }

  if (!password.value.trim()) {
    passwordError.value = t('login.messages.passwordRequired')
    return
  }

  loading.value = true
  try {
    const result = await authStore.login(email.value, password.value)
    if (result?.mfaRequired) {
      router.push('/mfa/verify')
      return
    }
    if (result?.mfaSetupRequired) {
      toast.add({
        severity: 'warn',
        summary: t('mfa.setupRequired'),
        detail: t('mfa.setupRequired'),
        life: 6000
      })
      router.push('/mfa/setup')
      return
    }
    toast.add({
      severity: 'success',
      summary: t('common.messages.success'),
      detail: t('login.messages.success'),
      life: 3000
    })
    router.push('/')
  } catch (error) {
    const errorCode = error.response?.data?.error_code
    const errorDetail = error.response?.data?.detail
    let message = t('login.messages.error')

    // Gestione specifica per SSO_REQUIRED
    if (errorCode === 'SSO_REQUIRED') {
      message = errorDetail || t('login.messages.ssoRequired')
      toast.add({
        severity: 'warn',
        summary: t('login.messages.ssoRequiredTitle'),
        detail: message,
        life: 7000
      })
      // Opzionalmente, potresti reindirizzare al login SSO qui
      // router.push('/auth/sso/azure_ad/authorize')
      return
    }

    if (errorCode === 'MFA_SETUP_REQUIRED' || error.response?.data?.mfa_setup_required) {
      if (error.response?.data?.mfa_setup_token) {
        sessionStorage.setItem('mfa_setup_token', error.response.data.mfa_setup_token)
      }
      toast.add({
        severity: 'warn',
        summary: t('mfa.setupRequired'),
        detail: t('mfa.setupRequired'),
        life: 6000
      })
      router.push('/mfa/setup')
      return
    }

    // Prova a ottenere la traduzione specifica per il codice di errore
    if (errorCode) {
      const translatedError = t(`core.${errorCode}`)
      // Se la traduzione esiste e non è uguale alla chiave, usala
      if (translatedError && translatedError !== `core.${errorCode}`) {
        message = translatedError
      } else if (errorDetail) {
        message = errorDetail
      }
    }

    toast.add({
      severity: 'error',
      summary: t('common.messages.error'),
      detail: message,
      life: 5000
    })
  } finally {
    loading.value = false
  }
}


</script>

<style scoped>
/* Login: same look as the app (sage page, white rounded card, themed fields and buttons) */
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  background: #eef2ef;
}

/* Soft background decoration */
.login-background {
  position: absolute;
  inset: 0;
  z-index: 1;
}

.background-pattern {
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(circle at 12% 18%, rgba(29, 104, 56, 0.10) 0%, transparent 38%),
    radial-gradient(circle at 88% 82%, rgba(29, 104, 56, 0.12) 0%, transparent 42%);
}

.background-overlay {
  position: absolute;
  inset: 0;
  background: transparent;
}

/* Container principale */
.login-content {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1.5rem;
  max-width: 1200px;
  width: 100%;
  padding: 2rem;
}

/* Brand section */
.login-brand {
  text-align: center;
}

.logo-container {
  display: inline-block;
}

.login-logo {
  width: 170px;
  height: auto;
}

/* Form container */
.login-form-container {
  width: 100%;
  max-width: 420px;
}

.form-card {
  background: #fff;
  border-radius: 14px;
  padding: 2rem 2.25rem 2.25rem;
  box-shadow: 0 8px 30px rgba(24, 54, 36, 0.10);
  border: 1px solid #e1e7e3;
  animation: fadeInUp 0.4s ease-out;
}

.form-header {
  text-align: center;
  margin-bottom: 1.75rem;
}

.form-header h2 {
  font-size: 1.5rem;
  font-weight: 600;
  color: #174d2d;
  margin: 0 0 0.35rem 0;
}

.form-header p {
  color: #6b7a71;
  margin: 0;
  font-size: 0.88rem;
}

/* Form groups */
.form-group {
  margin-bottom: 1.15rem;
}

.form-label {
  display: block;
  font-weight: 500;
  color: #25332b;
  margin-bottom: 0.4rem;
  font-size: 0.85rem;
}

.input-wrapper {
  position: relative;
}

.form-input {
  width: 100%;
  padding: 0.7rem 0.9rem 0.7rem 2.6rem;
  font-size: 0.9rem;
}

.input-icon {
  position: absolute;
  left: 0.9rem;
  top: 50%;
  transform: translateY(-50%);
  color: #1d6838;
  font-size: 0.95rem;
  z-index: 2;
  pointer-events: none;
}

.error-message {
  color: #d92d20;
  font-size: 0.78rem;
  margin-top: 0.3rem;
  display: block;
}

/* Form options */
.form-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.25rem;
  font-size: 0.85rem;
}

.remember-me {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.checkbox-label {
  color: #6b7a71;
  cursor: pointer;
}

/* Buttons */
.login-button {
  width: 100%;
  padding: 0.75rem;
  background: #1d6838;
  border: 1px solid #1d6838;
  border-radius: 6px;
  color: #fff;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease, box-shadow 0.2s ease;
  justify-content: center;
}

.login-button:hover:not(:disabled) {
  background: #154f2a;
  border-color: #154f2a;
  box-shadow: 0 4px 14px rgba(29, 104, 56, 0.28);
}

.login-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* Divider */
.divider {
  text-align: center;
  margin: 1.4rem 0 1.1rem;
  position: relative;
}

.divider::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 1px;
  background: #e1e7e3;
}

.divider span {
  position: relative;
  background: #fff;
  padding: 0 0.9rem;
  color: #6b7a71;
  font-size: 0.82rem;
}

/* SSO button: outlined, like the other secondary buttons in the app */
.sso-section {
  margin-top: 0.25rem;
}

.sso-button {
  width: 100%;
  padding: 0.7rem;
  background: #fff;
  border: 1px solid #1d6838;
  border-radius: 6px;
  color: #1d6838;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.sso-button:hover:not(:disabled) {
  background: #e8f0eb;
  color: #154f2a;
}

.sso-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* Responsive */
@media (max-width: 768px) {
  .login-content {
    padding: 1rem;
  }

  .form-card {
    padding: 1.5rem;
  }
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(16px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* PrimeVue components */
:deep(.p-password) {
  width: 100%;
}

:deep(.p-password-input) {
  width: 100%;
  padding: 0.7rem 2.6rem 0.7rem 2.6rem;
  font-size: 0.9rem;
}

:deep(.p-password .p-icon),
:deep(.p-password i) {
  color: #6b7a71;
}

:deep(.form-input.p-invalid),
:deep(.p-password-input.p-invalid) {
  border-color: #d92d20;
  box-shadow: 0 0 0 2px rgba(217, 45, 32, 0.12);
}

:deep(.p-checkbox) {
  margin-right: 0.5rem;
}

:deep(.p-checkbox .p-checkbox-box) {
  border-radius: 4px;
  border-color: #1d6838;
}

:deep(.p-checkbox .p-checkbox-box.p-highlight) {
  background: #1d6838;
  border-color: #1d6838;
}
</style>
