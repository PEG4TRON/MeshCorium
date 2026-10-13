// Keyboard-aware viewport for mobile. The on-screen keyboard does not change 100dvh on its own,
// so the composer stays behind it. We publish --mc-keyboard-height and notify subscribers so the
// focused composer can be pulled back into the visible area.
//
// One source of truth per environment — this is what prevents the keyboard being deducted twice:
//   - plain browser: window.visualViewport really shrinks, so the variable follows that shrinkage;
//     a value reported by the native bridge wins over the measurement when present.
//   - native shell (APK WebView, edge-to-edge): Android pads the WebView by the IME inset itself,
//     so the page already shrinks there and the variable must stay 0; the reported height drives
//     only the reveal logic.

export const KEYBOARD_OPEN_THRESHOLD_PX = 150

// Global name the Android app calls; renaming it requires the same change in MainActivity.kt.
export const NATIVE_KEYBOARD_GLOBAL = '__mcKeyboardHeight'

export function keyboardHeightPx(viewport, layoutHeight) {
  if (!viewport) return 0
  const shrink = layoutHeight - viewport.height
  return shrink >= KEYBOARD_OPEN_THRESHOLD_PX ? shrink : 0
}

export function createKeyboardViewportState({
  target = null,
  viewport = null,
  layoutHeight = 0,
  nativeShell = false,
} = {}) {
  let layout = layoutHeight
  let nativeHeight = 0
  let height = keyboardHeightPx(viewport, layout)
  const listeners = new Set()

  function publish() {
    if (viewport && viewport.height > layout) layout = viewport.height
    height = nativeHeight || keyboardHeightPx(viewport, layout)
    const cssValue = nativeShell ? 0 : height
    if (target?.setProperty) target.setProperty('--mc-keyboard-height', `${cssValue}px`)
    for (const listener of listeners) listener(height)
  }

  function setKeyboardHeight(value) {
    // Only the Android app can call this, so being called proves the native shell: the page is
    // already resized by Android, and the value drives only the composer reveal.
    nativeShell = true
    nativeHeight = Number.isFinite(value) && value > 0 ? value : 0
    publish()
  }

  function subscribe(listener) {
    listeners.add(listener)
    listener(height)
    return () => listeners.delete(listener)
  }

  publish()

  if (viewport?.addEventListener) {
    viewport.addEventListener('resize', publish)
  }

  return {
    height: () => height,
    setKeyboardHeight,
    notify: publish,
    subscribe,
    refresh: publish,
    cleanup() {
      listeners.clear()
      nativeHeight = 0
      viewport?.removeEventListener?.('resize', publish)
    },
  }
}

export function installKeyboardViewportVariable({ target, viewport, layoutHeight }) {
  const state = createKeyboardViewportState({ target, viewport, layoutHeight })
  return state.cleanup
}

// Exposes the global MainActivity.kt calls from its IME inset listener.
export function installNativeKeyboardHeightBridge({
  state,
  targetWindow = typeof window !== 'undefined' ? window : null,
}) {
  if (!targetWindow) return null
  targetWindow[NATIVE_KEYBOARD_GLOBAL] = (value) => state.setKeyboardHeight(value)
  return () => {
    delete targetWindow[NATIVE_KEYBOARD_GLOBAL]
  }
}

let state = null

export function getKeyboardViewportState({
  target = null,
  viewport = null,
  layoutHeight = 0,
  nativeShell = false,
} = {}) {
  if (!state) {
    const isNativeShell = nativeShell || (
      typeof document !== 'undefined' && document.documentElement.classList.contains('mc-native-shell')
    )
    state = createKeyboardViewportState({
      target: target || (typeof document !== 'undefined' ? document.documentElement : null),
      viewport: viewport ?? (typeof window !== 'undefined' ? window.visualViewport ?? null : null),
      layoutHeight: layoutHeight || (typeof window !== 'undefined' ? window.innerHeight : 0),
      nativeShell: isNativeShell,
    })
  }
  return state
}

export function revealElementInView(element, keyboardHeight) {
  if (!keyboardHeight) return
  element?.scrollIntoView?.({ block: 'nearest' })
}

// Both cases must work: focus happens after the keyboard is already open, and the keyboard
// appears while the composer is already focused (the usual mobile case).
export function attachComposerKeyboardReveal({
  elementGetter,
  state,
  activeElementGetter = () => (typeof document !== 'undefined' ? document.activeElement : null),
}) {
  const revealIfKeyboard = () => {
    if (activeElementGetter() !== elementGetter()) return
    revealElementInView(elementGetter(), state.height())
  }

  const onfocus = revealIfKeyboard
  const unsubscribeState = state.subscribe(revealIfKeyboard)
  elementGetter()?.addEventListener?.('focus', onfocus)

  return () => {
    elementGetter()?.removeEventListener?.('focus', onfocus)
    unsubscribeState()
  }
}
