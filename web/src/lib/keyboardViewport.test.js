import { describe, expect, it } from 'vitest'
import {
  KEYBOARD_OPEN_CLASS,
  KEYBOARD_OPEN_THRESHOLD_PX,
  NATIVE_KEYBOARD_GLOBAL,
  attachComposerKeyboardReveal,
  attachKeyboardOpenFlag,
  createKeyboardViewportState,
  getKeyboardViewportState,
  installKeyboardViewportVariable,
  installNativeKeyboardHeightBridge,
  keyboardHeightPx,
  revealElementInView,
} from './keyboardViewport'

function fakeViewport(height) {
  const listeners = {}
  return {
    height,
    addEventListener(type, fn) {
      listeners[type] = fn
    },
    removeEventListener(type) {
      delete listeners[type]
    },
    fire(type) {
      listeners[type]?.()
    },
    hasListener(type) {
      return Boolean(listeners[type])
    },
  }
}

function fakeTarget() {
  const props = {}
  return {
    setProperty(name, value) {
      props[name] = value
    },
    props,
  }
}

describe('keyboardViewport', () => {
  it('reports zero keyboard height when no visualViewport exists', () => {
    expect(keyboardHeightPx(undefined, 800)).toBe(0)
  })

  it('reports the shrinkage between full window height and visible viewport as keyboard height', () => {
    expect(keyboardHeightPx({ height: 400 }, 800)).toBe(400)
  })

  it('ignores tiny shrinkages below the keyboard-open threshold', () => {
    expect(keyboardHeightPx({ height: 800 - (KEYBOARD_OPEN_THRESHOLD_PX - 1) }, 800)).toBe(0)
    expect(keyboardHeightPx({ height: 800 - KEYBOARD_OPEN_THRESHOLD_PX }, 800)).toBe(KEYBOARD_OPEN_THRESHOLD_PX)
  })

  it('publishes the keyboard height as a CSS variable and updates it on viewport resize', () => {
    const target = fakeTarget()
    const viewport = fakeViewport(500)
    const cleanup = installKeyboardViewportVariable({ target, viewport, layoutHeight: 800 })
    expect(target.props['--mc-keyboard-height']).toBe('300px')

    viewport.fire('resize')
    expect(target.props['--mc-keyboard-height']).toBe('300px')

    viewport.height = 800
    viewport.fire('resize')
    expect(target.props['--mc-keyboard-height']).toBe('0px')

    cleanup()
    expect(viewport.hasListener('resize')).toBe(false)
  })

  it('does nothing without a viewport but keeps the variable pinned to zero', () => {
    const target = fakeTarget()
    const cleanup = installKeyboardViewportVariable({ target, viewport: undefined, layoutHeight: 800 })
    expect(target.props['--mc-keyboard-height']).toBe('0px')
    expect(() => cleanup()).not.toThrow()
  })

  it('creates the singleton state against the injected target and pins the variable to zero when no viewport exists', () => {
    const target = fakeTarget()
    const state = getKeyboardViewportState({ target, viewport: undefined, layoutHeight: 800 })
    expect(target.props['--mc-keyboard-height']).toBe('0px')
    expect(state.height()).toBe(0)
    const seen = []
    const unsubscribe = state.subscribe((value) => seen.push(value))
    expect(seen).toEqual([0])
    unsubscribe()
    expect(getKeyboardViewportState({ target, viewport: undefined, layoutHeight: 800 })).toBe(state)
  })

  it('in a plain browser the variable follows the measured shrinkage (no native bridge exists there)', () => {
    const target = fakeTarget()
    const viewport = fakeViewport(450)
    const state = createKeyboardViewportState({ target, viewport, layoutHeight: 800 })
    expect(state.height()).toBe(350)
    expect(target.props['--mc-keyboard-height']).toBe('350px')

    viewport.height = 800
    viewport.fire('resize')
    expect(state.height()).toBe(0)
    expect(target.props['--mc-keyboard-height']).toBe('0px')
  })

  it('in the native shell the variable stays zero so the keyboard is never deducted twice', () => {
    // The Android layer pads the WebView by the IME inset, so the page already shrinks;
    // the reported height drives only the reveal logic.
    const target = fakeTarget()
    const state = createKeyboardViewportState({ target, viewport: undefined, layoutHeight: 800, nativeShell: true })
    expect(target.props['--mc-keyboard-height']).toBe('0px')

    state.setKeyboardHeight(300)
    expect(state.height()).toBe(300)
    expect(target.props['--mc-keyboard-height']).toBe('0px')
  })

  it('a native report also proves native shell, so the height is never deducted twice even when detection failed', () => {
    // Plain browsers never call the bridge, so being called is itself proof of the APK.
    const target = fakeTarget()
    const state = createKeyboardViewportState({ target, layoutHeight: 800 })
    state.setKeyboardHeight(300)
    expect(target.props['--mc-keyboard-height']).toBe('0px')
    expect(state.height()).toBe(300)
  })

  it('flags the open keyboard on the document root so the bottom bar can be hidden while typing', () => {
    const target = fakeTarget()
    const root = {
      classList: { list: [], add(name) { this.list.push(name) }, remove(name) { this.list = this.list.filter((n) => n !== name) } },
    }
    const state = createKeyboardViewportState({ target, layoutHeight: 800, nativeShell: true })
    const cleanup = attachKeyboardOpenFlag({ state, rootGetter: () => root })
    expect(root.classList.list).toEqual([])

    state.setKeyboardHeight(300)
    expect(root.classList.list).toEqual(['mc-keyboard-open'])

    state.setKeyboardHeight(0)
    expect(root.classList.list).toEqual([])

    cleanup()
  })

  it('hides the bottom bar while the keyboard is open', async () => {
    const fs = await import('node:fs')
    const css = fs.readFileSync('/opt/meshcorium/.release/dev/web/src/styles.css', 'utf8')
    expect(css).toContain('.mc-keyboard-open .mc-mobile-dock')
    expect(css).toContain('display: none')
    const shell = fs.readFileSync('/opt/meshcorium/.release/dev/web/src/main.js', 'utf8')
    expect(shell).toContain('attachKeyboardOpenFlag({ state: getKeyboardViewportState() })')
  })

  it('installs the global the Android app calls, under the name the Kotlin side uses', () => {
    const target = fakeTarget()
    const state = createKeyboardViewportState({ target, layoutHeight: 800 })
    const win = { [NATIVE_KEYBOARD_GLOBAL]: null }
    const cleanup = installNativeKeyboardHeightBridge({ state, targetWindow: win })
    expect(typeof win[NATIVE_KEYBOARD_GLOBAL]).toBe('function')
    // Only the Android app can call it, so the call itself marks the environment as native:
    // CSS stays 0 (Android already resized the WebView) and the value drives only the reveal.
    win[NATIVE_KEYBOARD_GLOBAL](300)
    expect(target.props['--mc-keyboard-height']).toBe('0px')
    expect(state.height()).toBe(300)
    cleanup()
    expect(win[NATIVE_KEYBOARD_GLOBAL]).toBeUndefined()
  })

  it('the Android app feeds that value: IME inset padding, adjustResize, same global name', async () => {
    const fs = await import('node:fs')
    const base = '/opt/meshcorium/.release/dev/AndroidApp/app/src/main'
    const main = fs.readFileSync(`${base}/java/com/meshcorium/webclient/MainActivity.kt`, 'utf8')
    const manifest = fs.readFileSync(`${base}/AndroidManifest.xml`, 'utf8')
    expect(main).toContain('WindowInsetsCompat.Type.ime()')
    expect(main).toContain('evaluateJavascript')
    expect(main).toContain(NATIVE_KEYBOARD_GLOBAL)
    expect(manifest).toContain('android:windowSoftInputMode="adjustResize"')
    // the native dock must disappear while typing, otherwise there is no room for the chat
    expect(main).toContain('View.GONE')
    expect(main).toContain('nativeBottomNavigation')
    // the hairline above the dock must disappear with it
    expect(main).toContain('dockBorder')
    // the dock owns the nav-bar inset (as before); the root gets only the keyboard inset,
    // otherwise the nav-bar padding is applied twice
    expect(main).toContain('bottom = if (keyboardOpen) ime.bottom else 0')
    expect(main).toContain('bottom = systemBars.bottom')
    // deterministic hide: a vertical LinearLayout removes a GONE view from the chain, so the
    // WebView gets the whole remaining space (in ConstraintLayout the point position is ambiguous)
    const layout = fs.readFileSync('/opt/meshcorium/.release/dev/AndroidApp/app/src/main/res/layout/activity_main.xml', 'utf8')
    expect(layout).toContain('<LinearLayout')
    expect(layout).toContain('android:orientation="vertical"')
    expect(layout).toContain('android:layout_weight="1"')
  })

  it('keeps the default interactive-widget so the page is not resized twice by browser and Android', async () => {
    const fs = await import('node:fs')
    const html = fs.readFileSync('/opt/meshcorium/.release/dev/web/index.html', 'utf8')
    // resizes-content would make 100dvh shrink on its own, so subtracting again would deduct twice.
    expect(html).not.toContain('interactive-widget=resizes-content')
  })

  it('drives the mobile shell height from the keyboard variable', async () => {
    const fs = await import('node:fs')
    const css = fs.readFileSync('/opt/meshcorium/.release/dev/web/src/components/layout/MobileMessagesShell.vue', 'utf8')
    expect(css).toContain('calc(100dvh - var(--mc-keyboard-height, 0px))')
    const overlay = fs.readFileSync('/opt/meshcorium/.release/dev/web/src/styles.css', 'utf8')
    expect(overlay).toContain('inset: 0 0 var(--mc-keyboard-height, 0px) 0')
  })

  it('wires the singleton and the native bridge at app start, attaches focus reveal in the composer', async () => {
    const fs = await import('node:fs')
    const main = fs.readFileSync('/opt/meshcorium/.release/dev/web/src/main.js', 'utf8')
    const view = fs.readFileSync('/opt/meshcorium/.release/dev/web/src/views/MessagesView.vue', 'utf8')
    expect(main).toContain('import { getKeyboardViewportState, installNativeKeyboardHeightBridge, attachKeyboardOpenFlag } from \'./lib/keyboardViewport\'')
    expect(main).toContain('getKeyboardViewportState()')
    expect(main).toContain('attachKeyboardOpenFlag({ state: getKeyboardViewportState() })')
    expect(main).toContain('installNativeKeyboardHeightBridge({ state: getKeyboardViewportState() })')
    expect(view).toContain('attachComposerKeyboardReveal({ elementGetter: () => composerTextarea.value, state: getKeyboardViewportState() })')
    expect(view).toContain('keyboardRevealUnsubscribe?.()')
  })

  it('scrolls the element into view only when the keyboard is open', () => {
    const calls = []
    const element = { scrollIntoView: (opts) => calls.push(opts) }
    revealElementInView(element, 0)
    expect(calls).toHaveLength(0)
    revealElementInView(element, 300)
    expect(calls).toEqual([{ block: 'nearest' }])
  })

  it('attaches focus-time reveal and detaches on cleanup', () => {
    const calls = []
    const handlers = {}
    const element = {
      addEventListener(type, fn) { handlers[type] = fn },
      removeEventListener(type) { delete handlers[type] },
      scrollIntoView: (opts) => calls.push(opts),
    }
    const active = { element: null }
    const state = {
      height: () => 300,
      subscribe(listener) {
        listener(300)
        return () => {}
      },
    }
    const unsubscribe = attachComposerKeyboardReveal({
      elementGetter: () => element,
      state,
      activeElementGetter: () => active.element,
    })
    expect(calls).toHaveLength(0)

    active.element = element
    handlers.focus()
    expect(calls).toEqual([{ block: 'nearest' }])

    unsubscribe()
    expect(handlers.focus).toBeUndefined()
  })

  it('reveals the composer when the keyboard appears while it is already focused', () => {
    const calls = []
    const element = { scrollIntoView: (opts) => calls.push(opts) }
    const target = fakeTarget()
    const state = createKeyboardViewportState({ target, layoutHeight: 800, nativeShell: true })
    attachComposerKeyboardReveal({
      elementGetter: () => element,
      state,
      activeElementGetter: () => element,
    })
    expect(calls).toHaveLength(0)

    // no focus event here: the keyboard appeared while the composer was already focused
    state.setKeyboardHeight(300)
    expect(calls).toEqual([{ block: 'nearest' }])
  })
})
