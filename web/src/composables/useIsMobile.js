import { ref } from 'vue'

const MOBILE_BREAKPOINT = 1024

const isMobile = ref(false)
let mediaQuery = null
let mediaQueryHandler = null

export function useIsMobile() {
  if (typeof window === 'undefined') {
    return { isMobile }
  }

  if (!mediaQuery) {
    mediaQuery = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`)
    mediaQueryHandler = (event) => {
      isMobile.value = event.matches
    }
    isMobile.value = mediaQuery.matches

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', mediaQueryHandler)
    } else if (typeof mediaQuery.addListener === 'function') {
      mediaQuery.addListener(mediaQueryHandler)
    }
  }

  return { isMobile }
}
