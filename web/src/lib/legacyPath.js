export function toLegacyPath(path) {
  const normalized = String(path || '').trim()
  const absolutePath = normalized.startsWith('/') ? normalized : `/${normalized}`
  if (absolutePath === '/legacy' || absolutePath.startsWith('/legacy/')) {
    return absolutePath
  }
  return `/legacy${absolutePath}`
}
