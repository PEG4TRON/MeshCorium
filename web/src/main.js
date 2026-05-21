import { createApp } from 'vue'
import { createPinia } from 'pinia'
import FloatingVue from 'floating-vue'

import AppRoot from './AppRoot.vue'
import { router } from './app/router'
import { i18n } from './i18n'
import { logFrontendDiagnostic } from './lib/frontendDiagnostics'
import { floatingVueOptions } from './plugins/floatingVue'
import 'floating-vue/dist/style.css'
import './styles.css'

function currentRouteName() {
  return String(router.currentRoute.value?.name || '').trim() || 'unknown'
}

function normalizeErrorMessage(error) {
  if (error instanceof Error) {
    return String(error.message || error.name || 'Unknown error')
  }
  return String(error || 'Unknown error')
}

function normalizeErrorStack(error) {
  const stack = String(error?.stack || '').trim()
  return stack || ''
}

function resolveComponentName(instance) {
  return String(
    instance?.type?.name
    || instance?.type?.__name
    || instance?.proxy?.$options?.name
    || '',
  ).trim() || 'anonymous'
}

if (typeof navigator !== 'undefined' && typeof document !== 'undefined') {
  const userAgent = String(navigator.userAgent || '')
  const isFirefox = /firefox/i.test(userAgent) && !/seamonkey/i.test(userAgent)
  document.documentElement.classList.toggle('is-firefox', isFirefox)
}

const app = createApp(AppRoot)
app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(FloatingVue, floatingVueOptions)

app.config.errorHandler = (error, instance, info) => {
  logFrontendDiagnostic('vue-runtime-error', {
    routeName: currentRouteName(),
    componentName: resolveComponentName(instance),
    info: String(info || '').trim(),
    message: normalizeErrorMessage(error),
    stack: normalizeErrorStack(error),
  })
}

if (typeof window !== 'undefined') {
  window.addEventListener('error', (event) => {
    logFrontendDiagnostic('window-error', {
      routeName: currentRouteName(),
      message: normalizeErrorMessage(event.error || event.message),
      filename: String(event.filename || '').trim(),
      lineno: Number(event.lineno || 0),
      colno: Number(event.colno || 0),
      stack: normalizeErrorStack(event.error),
    })
  })

  window.addEventListener('unhandledrejection', (event) => {
    logFrontendDiagnostic('unhandled-rejection', {
      routeName: currentRouteName(),
      message: normalizeErrorMessage(event.reason),
      stack: normalizeErrorStack(event.reason),
    })
  })
}

app.mount('#app')
