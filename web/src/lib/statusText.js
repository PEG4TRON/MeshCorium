export function isSerialOnlyStatusMessage(message) {
  const normalized = String(message || '').trim().toLowerCase()
  if (!normalized) {
    return false
  }
  return (
    normalized === 'порт не выбран'
    || normalized === 'выбери serial-порт.'
    || normalized === 'нет видимых serial-портов. проверь подключение ноды.'
    || normalized === 'port not selected'
    || normalized === 'choose a serial port.'
    || normalized === 'no visible serial ports. check the node connection.'
    || normalized.includes('serial-порт')
    || normalized.includes('serial-портов')
    || normalized.includes('serial port')
    || normalized.includes('visible serial ports')
  )
}

export function filterStatusTextForTransport(message, transportType) {
  const normalizedTransport = String(transportType || '').trim().toLowerCase()
  const text = String(message || '').trim()
  if (!text) {
    return ''
  }
  if (normalizedTransport === 'ble' && isSerialOnlyStatusMessage(text)) {
    return ''
  }
  return text
}
