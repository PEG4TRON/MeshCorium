// Composer byte budget — mirrors the MeshCore firmware text limits.
//
// Firmware facts (read-only reference clone, HEAD a366955c):
//   MAX_TEXT_LEN = 10 * CIPHER_BLOCK_SIZE = 160 bytes (`src/helpers/BaseChatMesh.h:8`).
//   Contact plain text: `composeMsgPacket` rejects `strlen(text) > MAX_TEXT_LEN` and, from
//     attempt 4 on, `text_len > MAX_TEXT_LEN - 2` because the firmware appends [0][attempt]
//     to the datagram payload — `BaseChatMesh.cpp:420-434`.
//   Channel/group plain text: `sendGroupMessage` builds "<sender>: <text>" inside the same
//     160-byte payload and silently truncates when `text_len + prefix_len > MAX_TEXT_LEN`
//     (`BaseChatMesh.cpp:486-498`). So the sender name IS part of the budget; the client
//     must refuse over-budget text instead of letting the device truncate it.
//   MAX_NAME_SIZE = 32 (C string → at most 31 usable UTF-8 bytes), matching the official
//     app (`meshcore-open/lib/connector/meshcore_protocol.dart:362`, `maxChannelMessageBytes`
//     at L388-394).
//   Wire frame ceiling: MAX_FRAME_SIZE = 176 (`BaseSerialInterface.h:5`, enforced by our
//     transport guard in meshcorium_serial_transport.py / meshcorium_wifi_transport.py).
//   Official overhead formula (`meshcore_protocol.dart:378-381`), including the reference's
//     2-byte safety margin:
//       contact:  1 code + 1 type + 1 attempt + 4 ts + 6 key prefix + 1 null + 2 safety = 15
//       channel:  1 code + 1 type + 1 idx    + 4 ts               + 1 null + 2 safety = 9

export const MAX_TEXT_PAYLOAD_BYTES = 160
export const MAX_NAME_BYTES = 31
export const NAME_SEPARATOR_BYTES = 2 // ": " in "<sender>: "
export const REPLY_ATTEMPT_RESERVE_BYTES = 2 // [0][attempt] appended from attempt 4
export const FULL_LENGTH_ATTEMPT_THRESHOLD = 3
export const MAX_FRAME_PAYLOAD_BYTES = 176
export const NULL_TERMINATOR_BYTES = 1 // firmware writes text_len + 1 into the payload
export const SAFETY_MARGIN_BYTES = 2

export function utf8Bytes(value) {
  return new TextEncoder().encode(String(value || '')).length
}

export function senderNameBytes(name) {
  return Math.min(utf8Bytes(name), MAX_NAME_BYTES)
}

export function composerPacketParts({ kind, senderName = '', text = '', attempt = 0 }) {
  const textBytes = utf8Bytes(text)
  const namePrefixBytes = kind === 'channel' ? senderNameBytes(senderName) + NAME_SEPARATOR_BYTES : 0
  const headerBytes = 7 // [code][type][attempt|idx][ts:4]
  const recipientBytes = kind === 'contact' ? 6 : 0 // pub key prefix (channel idx is in the header)
  const attemptReserveBytes = kind === 'contact' && Number(attempt) > FULL_LENGTH_ATTEMPT_THRESHOLD
    ? REPLY_ATTEMPT_RESERVE_BYTES
    : 0

  const totalBytes = headerBytes + recipientBytes + namePrefixBytes + textBytes
  // Firmware rule for channels: text_len + prefix_len must fit in MAX_TEXT_LEN
  // (`BaseChatMesh.cpp:495`), so the name prefix reduces the text budget, not only the frame.
  // The frame rule caps it as well: header + recipient + prefix + text + null + margin <= 176.
  const payloadBudget = MAX_TEXT_PAYLOAD_BYTES - attemptReserveBytes - namePrefixBytes
  const frameBudget = MAX_FRAME_PAYLOAD_BYTES - headerBytes - recipientBytes - namePrefixBytes - NULL_TERMINATOR_BYTES - SAFETY_MARGIN_BYTES
  const textBudget = Math.min(payloadBudget, frameBudget)

  return {
    kind,
    headerBytes,
    recipientBytes,
    namePrefixBytes,
    textBytes,
    safetyMarginBytes: SAFETY_MARGIN_BYTES,
    nullTerminatorBytes: NULL_TERMINATOR_BYTES,
    attemptReserveBytes,
    totalBytes,
    limit: MAX_FRAME_PAYLOAD_BYTES,
    textBudget,
    bytesLeftOnFrame: MAX_FRAME_PAYLOAD_BYTES - totalBytes - SAFETY_MARGIN_BYTES,
    bytesLeftOnText: textBudget - textBytes,
    exceedsTextBudget: textBytes > textBudget,
    exceedsFrameLimit: totalBytes + SAFETY_MARGIN_BYTES > MAX_FRAME_PAYLOAD_BYTES,
  }
}

// Client-side guards kept in parity with these numbers.
export function contactTextBudget(attempt = 0) {
  return composerPacketParts({ kind: 'contact', attempt, text: '' }).textBudget
}

export function channelTextBudget(senderName) {
  return composerPacketParts({ kind: 'channel', senderName, text: '' }).textBudget
}

export function composerTextBudget({ kind, senderName, attempt = 0 }) {
  return composerPacketParts({ kind, senderName, attempt, text: '' }).textBudget
}

// What the composer counter shows: the whole packet the device receives — command header,
// recipient reference, the "<sender>: " prefix, the null terminator, the attempt reserve and
// the typed text (the reply marker "@[target] " is typed text, so it is already inside).
export function composerDisplayParts({ kind, senderName = '', text = '', attempt = 0 }) {
  const parts = composerPacketParts({ kind, senderName, text, attempt })
  const usedBytes =
    parts.headerBytes +
    parts.recipientBytes +
    parts.namePrefixBytes +
    parts.nullTerminatorBytes +
    parts.attemptReserveBytes +
    parts.textBytes
  return {
    ...parts,
    usedBytes,
    displayLimit: usedBytes + (parts.textBudget - parts.textBytes),
  }
}
