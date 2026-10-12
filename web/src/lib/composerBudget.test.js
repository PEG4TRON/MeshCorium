import { describe, expect, it } from 'vitest'

import {
  MAX_FRAME_PAYLOAD_BYTES,
  MAX_NAME_BYTES,
  MAX_TEXT_PAYLOAD_BYTES,
  SAFETY_MARGIN_BYTES,
  channelTextBudget,
  composerBreakdown,
  composerDisplayParts,
  composerPacketParts,
  contactTextBudget,
  senderNameBytes,
  utf8Bytes,
} from './composerBudget'

describe('composer packet budget (whole packet, not only typed text)', () => {
  it('counts the command header and recipient prefix for a contact packet', () => {
    const parts = composerPacketParts({ kind: 'contact', text: 'x'.repeat(50) })
    expect(parts.headerBytes).toBe(7) // [code][type][attempt][ts:4]
    expect(parts.recipientBytes).toBe(6) // pub key prefix
    expect(parts.namePrefixBytes).toBe(0) // contact packets carry no "<name>: " prefix
    expect(parts.textBytes).toBe(50)
    expect(parts.totalBytes).toBe(63)
    expect(parts.limit).toBe(MAX_FRAME_PAYLOAD_BYTES) // transport guard: 176
    expect(parts.textBudget).toBe(MAX_TEXT_PAYLOAD_BYTES) // 160, firmware payload limit
  })

  it('counts name prefix and text together for a channel packet', () => {
    const parts = composerPacketParts({ kind: 'channel', senderName: 'test', text: 'x'.repeat(50) })
    expect(parts.headerBytes).toBe(7) // [code][type][idx][ts:4]
    expect(parts.recipientBytes).toBe(0) // channel index is inside the header
    expect(parts.namePrefixBytes).toBe(6) // "test: "
    expect(parts.textBytes).toBe(50)
    expect(parts.totalBytes).toBe(63)
    expect(parts.textBudget).toBe(MAX_TEXT_PAYLOAD_BYTES - 6) // 154
  })

  it('reproduces the observed stand case: 143 fits, 144 does not', () => {
    const name = 'PEG11 \u{1F427} T114'
    const fit = composerPacketParts({ kind: 'channel', senderName: name, text: 'x'.repeat(143) })
    expect(utf8Bytes(name)).toBe(15)
    expect(fit.namePrefixBytes).toBe(17)
    expect(fit.textBudget).toBe(143)
    expect(fit.totalBytes).toBe(7 + 17 + 143) // 167 <= 176
    expect(fit.exceedsTextBudget).toBe(false)

    const over = composerPacketParts({ kind: 'channel', senderName: name, text: 'x'.repeat(144) })
    expect(over.textBytes).toBe(144)
    expect(over.exceedsTextBudget).toBe(true)
    expect(over.exceedsFrameLimit).toBe(false) // the frame still fits; the text is what overflows
  })

  it('flags the frame limit when the packet itself is too large', () => {
    const parts = composerPacketParts({ kind: 'channel', senderName: 'short', text: 'x'.repeat(170) })
    expect(parts.totalBytes).toBe(7 + 7 + 170)
    expect(parts.exceedsFrameLimit).toBe(true)
  })

  it('reserves the attempt marker bytes from attempt 4 for contacts', () => {
    expect(composerPacketParts({ kind: 'contact', text: 'a' }).attemptReserveBytes).toBe(0)
    const parts = composerPacketParts({ kind: 'contact', attempt: 4, text: 'a' })
    expect(parts.attemptReserveBytes).toBe(2)
    expect(parts.textBudget).toBe(MAX_TEXT_PAYLOAD_BYTES - 2) // 158
  })

  it('caps the name contribution at MAX_NAME_SIZE usable bytes', () => {
    expect(senderNameBytes('a'.repeat(40))).toBe(MAX_NAME_BYTES)
    expect(channelTextBudget('a'.repeat(40))).toBe(MAX_TEXT_PAYLOAD_BYTES - MAX_NAME_BYTES - 2)
    expect(contactTextBudget(0)).toBe(MAX_TEXT_PAYLOAD_BYTES)
  })

  it('breaks the packet into named parts for display', () => {
    const name = 'PEG11 \u{1F427} T114'
    const entries = composerBreakdown({ kind: 'channel', senderName: name, text: 'hello' })
    const byKey = Object.fromEntries(entries.map((e) => [e.key, e.bytes]))
    expect(byKey.header).toBe(7)
    expect(byKey.recipient).toBe(0) // channel index is inside the header
    expect(byKey.namePrefix).toBe(17)
    expect(byKey.nullTerminator).toBe(1)
    expect(byKey.attemptReserve).toBe(0)
    expect(byKey.text).toBe(5)

    const contact = composerBreakdown({ kind: 'contact', text: 'hello', attempt: 4 })
    const contactByKey = Object.fromEntries(contact.map((e) => [e.key, e.bytes]))
    expect(contactByKey.recipient).toBe(6)
    expect(contactByKey.attemptReserve).toBe(2)
    expect(contactByKey.namePrefix).toBe(0)
  })

  it('keeps the reference safety margin visible in the breakdown', () => {
    const parts = composerPacketParts({ kind: 'channel', senderName: 'test', text: 'x' })
    expect(parts.safetyMarginBytes).toBe(SAFETY_MARGIN_BYTES)
    expect(SAFETY_MARGIN_BYTES).toBe(2)
  })

  it('shows the counter as the whole packet over the frame limit', () => {
    const name = 'PEG11 \u{1F427} T114'
    const parts = composerDisplayParts({ kind: 'channel', senderName: name, text: 'x'.repeat(120) })
    // 7 header + 17 "<name>: " + 1 null + 120 typed = 145 of 168 (160 payload - 17 prefix + header)
    expect(parts.usedBytes).toBe(7 + 17 + 1 + 120)
    expect(parts.displayLimit).toBe(7 + 17 + 1 + 143)
    expect(parts.bytesLeftOnText).toBe(23)

    const contact = composerDisplayParts({ kind: 'contact', text: 'x'.repeat(150) })
    expect(contact.usedBytes).toBe(7 + 6 + 1 + 150)
    expect(contact.displayLimit).toBe(7 + 6 + 1 + 160)

    const contactLateAttempt = composerDisplayParts({ kind: 'contact', text: 'x', attempt: 4 })
    expect(contactLateAttempt.usedBytes).toBe(7 + 6 + 1 + 2 + 1)
    expect(contactLateAttempt.displayLimit).toBe(7 + 6 + 1 + 2 + 158)
  })

  it('keeps the limit stable while typing (only the used part grows)', () => {
    const name = 'PEG11 \u{1F427} T114'
    const short = composerDisplayParts({ kind: 'channel', senderName: name, text: 'x' })
    const long = composerDisplayParts({ kind: 'channel', senderName: name, text: 'x'.repeat(143) })
    expect(short.displayLimit).toBe(long.displayLimit) // 168 in both cases
    expect(short.usedBytes).toBe(7 + 17 + 1 + 1)
    expect(long.usedBytes).toBe(168)

    const contact = composerDisplayParts({ kind: 'contact', text: 'x' })
    expect(contact.displayLimit).toBe(7 + 6 + 1 + 160) // 174, capped by the frame
  })
})
