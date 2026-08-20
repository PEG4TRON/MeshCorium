import { describe, expect, it } from 'vitest'

import {
  buildCloseShellPanelLocation,
  buildOpenShellPanelLocation,
  buildToggleShellPanelLocation,
  isShellPanelActive,
} from './shellPanels'

describe('shell panel route helpers', () => {
  it('opens notifications on the current route without dropping page query state', () => {
    expect(buildOpenShellPanelLocation({ path: '/contacts', query: { group: 'favorites', q: 'node' } }, 'notifications')).toEqual({
      path: '/contacts',
      query: { group: 'favorites', q: 'node', panel: 'notifications' },
    })
  })

  it('closes a shell panel by removing only the panel query parameter', () => {
    expect(buildCloseShellPanelLocation({ path: '/messages', query: { contact: 'abc123', panel: 'notifications', focus: '42' } })).toEqual({
      path: '/messages',
      query: { contact: 'abc123', focus: '42' },
    })
  })

  it('toggles the same shell panel closed and a different panel open', () => {
    expect(buildToggleShellPanelLocation({ path: '/maps', query: { panel: 'notifications', trace: '1' } }, 'notifications')).toEqual({
      path: '/maps',
      query: { trace: '1' },
    })
    expect(buildToggleShellPanelLocation({ path: '/maps', query: { panel: 'console', trace: '1' } }, 'notifications')).toEqual({
      path: '/maps',
      query: { panel: 'notifications', trace: '1' },
    })
  })

  it('recognizes supported shell panel names only', () => {
    expect(isShellPanelActive({ query: { panel: 'notifications' } }, 'notifications')).toBe(true)
    expect(isShellPanelActive({ query: { panel: 'missing' } }, 'notifications')).toBe(false)
  })
})
