import { describe, it, expect, vi } from 'vitest'
import {
  detectNativeShell,
  markNativeShellDocument,
  sendNativeDockState,
  installNativeActionBridge,
} from '../lib/nativeShell'

describe('detectNativeShell', () => {
  it('returns false when window is undefined', () => {
    // SSR-safe
    const result = detectNativeShell()
    // In jsdom, window IS defined, so this tests normal browser path
    expect(typeof result).toBe('boolean')
  })

  it('returns true when MeshcoriumAndroid.isNativeShell() returns true', () => {
    window.MeshcoriumAndroid = {
      isNativeShell: () => true,
    }
    expect(detectNativeShell()).toBe(true)
    delete window.MeshcoriumAndroid
  })

  it('returns false when MeshcoriumAndroid is absent', () => {
    // Ensure MeshcoriumAndroid is not set
    delete window.MeshcoriumAndroid
    // No User-Agent match either
    expect(detectNativeShell()).toBe(false)
  })

  it('returns true via User-Agent fallback when bridge throws', () => {
    window.MeshcoriumAndroid = {
      isNativeShell: () => { throw new Error('injected') },
    }
    Object.defineProperty(window.navigator, 'userAgent', {
      value: 'Mozilla/5.0 MeshcoriumAndroidWebClient/0.1.0',
      configurable: true,
    })
    expect(detectNativeShell()).toBe(true)
    delete window.MeshcoriumAndroid
    delete window.navigator.userAgent
  })
})

describe('markNativeShellDocument', () => {
  it('adds mc-native-shell class when bridge is present', () => {
    window.MeshcoriumAndroid = {
      isNativeShell: () => true,
    }
    markNativeShellDocument()
    expect(document.documentElement.classList.contains('mc-native-shell')).toBe(true)
    delete window.MeshcoriumAndroid
  })

  it('removes mc-native-shell class when bridge is absent', () => {
    delete window.MeshcoriumAndroid
    document.documentElement.classList.add('mc-native-shell')
    markNativeShellDocument()
    expect(document.documentElement.classList.contains('mc-native-shell')).toBe(false)
  })
})

describe('sendNativeDockState', () => {
  it('does not throw when bridge is absent', () => {
    delete window.MeshcoriumAndroid
    expect(() => sendNativeDockState({ active: 'messages' })).not.toThrow()
  })

  it('calls updateDockState when bridge is present', () => {
    const updateDockState = vi.fn()
    window.MeshcoriumAndroid = { updateDockState, isNativeShell: () => true }
    sendNativeDockState({ active: 'messages' })
    expect(updateDockState).toHaveBeenCalledWith('{"active":"messages"}')
    delete window.MeshcoriumAndroid
  })

  it('does not throw when updateDockState throws', () => {
    window.MeshcoriumAndroid = {
      isNativeShell: () => true,
      updateDockState: () => { throw new Error('bridge error') },
    }
    expect(() => sendNativeDockState({})).not.toThrow()
    delete window.MeshcoriumAndroid
  })
})

describe('installNativeActionBridge', () => {
  it('installs __meshcoriumNativeAction on window', () => {
    const router = {
      currentRoute: { value: { name: 'messages', path: '/messages', query: {} } },
      push: vi.fn().mockResolvedValue(undefined),
    }
    installNativeActionBridge(router)
    expect(typeof window.__meshcoriumNativeAction).toBe('function')
    delete window.__meshcoriumNativeAction
  })

  it('action "messages" pushes /messages', async () => {
    const push = vi.fn().mockResolvedValue(undefined)
    const router = {
      currentRoute: { value: { name: 'home', path: '/', query: {} } },
      push,
    }
    installNativeActionBridge(router)
    await window.__meshcoriumNativeAction('messages')
    expect(push).toHaveBeenCalledWith('/messages')
    delete window.__meshcoriumNativeAction
  })

  it('action "notifications" adds panel=notifications query', async () => {
    const push = vi.fn().mockResolvedValue(undefined)
    const router = {
      currentRoute: { value: { name: 'messages', path: '/messages', query: { tab: 'all' } } },
      push,
    }
    installNativeActionBridge(router)
    await window.__meshcoriumNativeAction('notifications')
    expect(push).toHaveBeenCalledWith({
      path: '/messages',
      query: { tab: 'all', panel: 'notifications' },
    })
    delete window.__meshcoriumNativeAction
  })
})
