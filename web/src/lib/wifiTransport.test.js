import { describe, expect, it } from 'vitest'

import {
  buildWifiTransportId,
  normalizeWifiHost,
  normalizeWifiPort,
  parseWifiEndpoint,
} from './wifiTransport'

describe('wifi transport helpers', () => {
  it('normalizes tcp scheme prefixes', () => {
    expect(normalizeWifiHost('tcp://mesh.local')).toBe('mesh.local')
    expect(normalizeWifiHost(' tcp://192.168.1.5 ')).toBe('192.168.1.5')
  })

  it('parses host-only endpoints with default port', () => {
    expect(parseWifiEndpoint('mesh.local')).toEqual({ host: 'mesh.local', port: '5000' })
  })

  it('parses ipv4 host and port endpoints', () => {
    expect(parseWifiEndpoint('192.168.1.5:7000')).toEqual({ host: '192.168.1.5', port: '7000' })
  })

  it('parses bracketed ipv6 endpoints', () => {
    expect(parseWifiEndpoint('[fe80::1]:6000')).toEqual({ host: 'fe80::1', port: '6000' })
    expect(parseWifiEndpoint('[fe80::1]')).toEqual({ host: 'fe80::1', port: '5000' })
  })

  it('normalizes numeric ports and preserves invalid text for validation', () => {
    expect(normalizeWifiPort('05000')).toBe('5000')
    expect(normalizeWifiPort('70000')).toBe('70000')
    expect(normalizeWifiPort('abc')).toBe('abc')
  })

  it('builds canonical transport ids for ipv4 and ipv6', () => {
    expect(buildWifiTransportId('mesh.local', '5000')).toBe('mesh.local:5000')
    expect(buildWifiTransportId('fe80::1', '5000')).toBe('[fe80::1]:5000')
  })
})

