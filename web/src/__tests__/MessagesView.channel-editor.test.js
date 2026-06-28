import { describe, expect, it } from 'vitest'

// Extract buildChannelSavePayload pattern from the editor
function buildChannelSavePayload({ config, channelIdx, channelIdentity, channelName, channelSecretHex }) {
  const hasExplicitIdx = (
    channelIdx !== null
    && channelIdx !== undefined
    && channelIdx !== ''
  )

  return {
    ...(config || {}),
    channel_idx: hasExplicitIdx ? Number(channelIdx) : null,
    channel_name: String(channelName || '').trim(),
    channel_secret_hex:
      channelSecretHex == null
        ? null
        : String(channelSecretHex).trim().toLowerCase(),
    expected_channel_identity:
      hasExplicitIdx
        ? String(channelIdentity || '').trim()
        : '',
  }
}

function selectSavedChannel(data, nextChannels) {
  const returnedChannel = data?.channel || null
  const returnedIdentity = String(returnedChannel?.channel_identity || '').trim()
  const returnedIdx = Number(returnedChannel?.idx ?? -1)

  const savedChannel = nextChannels.find((channel) => {
    const identity = String(channel?.channel_identity || '').trim()
    if (returnedIdentity && identity === returnedIdentity) return true
    return Number(channel?.idx ?? -1) === returnedIdx
  }) || returnedChannel

  return savedChannel
}

describe('buildChannelSavePayload', () => {
  it('does not send expected identity for create', () => {
    const payload = buildChannelSavePayload({
      config: { port: '/dev/ttyUSB0' },
      channelIdx: null,
      channelIdentity: '',
      channelName: '#test',
      channelSecretHex: null,
    })

    expect(payload.channel_idx).toBeNull()
    expect(payload.expected_channel_identity).toBe('')
    expect(payload.channel_name).toBe('#test')
  })

  it('sends expected identity for edit', () => {
    const payload = buildChannelSavePayload({
      config: { port: '/dev/ttyUSB0' },
      channelIdx: 5,
      channelIdentity: 'identity-old',
      channelName: 'new-name',
      channelSecretHex: 'ab'.repeat(16),
    })

    expect(payload.channel_idx).toBe(5)
    expect(payload.expected_channel_identity).toBe('identity-old')
    expect(payload.channel_name).toBe('new-name')
  })

  it('sends null channel_secret_hex for public channel create', () => {
    const payload = buildChannelSavePayload({
      config: {},
      channelIdx: null,
      channelIdentity: '',
      channelName: '#public',
      channelSecretHex: null,
    })

    expect(payload.channel_secret_hex).toBeNull()
  })

  it('lowercases secret hex', () => {
    const payload = buildChannelSavePayload({
      config: {},
      channelIdx: 3,
      channelIdentity: 'old-id',
      channelName: 'room',
      channelSecretHex: 'AABBCCDD' + '11223344',
    })

    expect(payload.channel_secret_hex).toBe('aabbccdd11223344')
  })
})

describe('selectSavedChannel', () => {
  it('selects by identity first when available', () => {
    const data = { channel: { idx: 7, channel_identity: 'room:abc123' } }
    const channels = [
      { idx: 5, channel_identity: 'other:xyz' },
      { idx: 7, channel_identity: 'room:abc123' },
      { idx: 9, channel_identity: 'room:abc123' },
    ]

    const result = selectSavedChannel(data, channels)
    expect(result.idx).toBe(7)
    expect(result.channel_identity).toBe('room:abc123')
  })

  it('falls back to idx when identity not found', () => {
    const data = { channel: { idx: 3, channel_identity: 'missing:xyz' } }
    const channels = [
      { idx: 1, channel_identity: 'a:1' },
      { idx: 3, channel_identity: 'b:2' },
    ]

    const result = selectSavedChannel(data, channels)
    expect(result.idx).toBe(3)
    expect(result.channel_identity).toBe('b:2')
  })

  it('returns returnedChannel when nothing matches', () => {
    const data = { channel: { idx: 99, channel_identity: 'nowhere:zzz' } }
    const channels = [
      { idx: 1, channel_identity: 'a:1' },
    ]

    const result = selectSavedChannel(data, channels)
    expect(result.idx).toBe(99)
  })

  it('returns null when no channel in response', () => {
    const data = {}
    const channels = [{ idx: 1, channel_identity: 'a:1' }]

    const result = selectSavedChannel(data, channels)
    expect(result).toBeNull()
  })
})
