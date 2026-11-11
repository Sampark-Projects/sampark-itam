
import { createApp } from 'vue'
import { createPinia } from 'pinia'

import piniaPersistedState from 'pinia-plugin-persistedstate'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import ToastEventBus from 'primevue/toasteventbus'

import ConfirmDialog from 'primevue/confirmdialog'
import ConfirmationService from 'primevue/confirmationservice'
import Tooltip from 'primevue/tooltip'

import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Dropdown from 'primevue/dropdown'
import Dialog from 'primevue/dialog' 

import App from './App.vue'
import router from './router'

import 'primevue/resources/themes/saga-blue/theme.css'
import 'primevue/resources/primevue.min.css'
import 'primeicons/primeicons.css'
import './static/main.css'
import './static/theme.css'
import '@vueup/vue-quill/dist/vue-quill.snow.css';
import i18n from './locales/loader-final.js'

// PrimeVue keeps a toast on screen forever unless the message has a `life`. Many calls in the
// app omit it, so give every toast a default lifetime (messages that set `life` or `sticky: true` keep theirs).
const DEFAULT_TOAST_LIFE = 5000
const emitToastEvent = ToastEventBus.emit.bind(ToastEventBus)
ToastEventBus.emit = (type, message) => {
  if (type === 'add' && message && message.life == null && !message.sticky) {
    return emitToastEvent(type, { ...message, life: DEFAULT_TOAST_LIFE })
  }
  return emitToastEvent(type, message)
}

const app = createApp(App)
const pinia = createPinia()
pinia.use(piniaPersistedState)

app.use(pinia)
app.use(router)
app.use(PrimeVue)
app.use(i18n)
app.use(ConfirmationService)

app.component('InputText', InputText)
app.component('Button', Button)
app.component('Dropdown', Dropdown)
app.component('ConfirmDialog', ConfirmDialog)
app.component('Dialog', Dialog)
app.directive('tooltip', Tooltip)
app.use(ToastService)

app.mount('#app')
