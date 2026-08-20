const NODE_PREVIEW_CATALOG = [
  { file: 'heltec_t114.svg', aliases: ['heltec t114', 't114'] },
  { file: 'heltec_v3.svg', aliases: ['heltec v3', 'wireless tracker'] },
  { file: 'heltec_v4.svg', aliases: ['heltec v4'] },
  { file: 'heltec_wt3.svg', aliases: ['wt3', 'wireless tracker v3'] },
  { file: 'heltec_wt2.svg', aliases: ['wt2', 'wireless tracker v2'] },
  { file: 'heltec_meshpocket.svg', aliases: ['meshpocket', 'mesh pocket'] },
  { file: 'heltec_mesh_solar.svg', aliases: ['mesh solar', 'heltec mesh solar'] },
  { file: 'rak_4631.svg', aliases: ['rak 4631', '4631', 'wismesh rak 4631'] },
  { file: 'rak_3112.svg', aliases: ['rak 3112', '3112'] },
  { file: 'rak_wismesh_tag.svg', aliases: ['wismesh tag'] },
  { file: 'lilygo_tdeck.svg', aliases: ['t deck', 'lilygo t deck'] },
  { file: 'lilygo_tdeck_pro.svg', aliases: ['t deck pro', 'lilygo t deck pro'] },
  { file: 'lilygo_tbeam.svg', aliases: ['t beam', 'lilygo t beam'] },
  { file: 'lilygo_techo.svg', aliases: ['t echo', 'lilygo t echo'] },
  { file: 'xiao_nrf52.svg', aliases: ['xiao nrf52'] },
  { file: 'sensecap_t1000e.svg', aliases: ['sensecap t1000e', 'sensecap t1000 e'] },
]

function normalizeLookup(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function compactLookup(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
}

export function matchNodePreviewFile(label) {
  const normalized = normalizeLookup(label)
  const compact = compactLookup(label)
  if (!normalized) {
    return ''
  }
  let bestFile = ''
  let bestScore = 0
  for (const item of NODE_PREVIEW_CATALOG) {
    let score = 0
    const fileStem = String(item.file || '').replace(/\.svg$/i, '')
    const compactFileStem = compactLookup(fileStem)
    for (const alias of item.aliases || []) {
      const normalizedAlias = normalizeLookup(alias)
      const compactAlias = compactLookup(alias)
      if (
        (normalizedAlias && normalized.includes(normalizedAlias))
        || (compactAlias && compact.includes(compactAlias))
      ) {
        score = Math.max(score, 10 + normalizedAlias.split(' ').length)
      }
    }
    if (!score && compactFileStem && compact.includes(compactFileStem)) {
      score = Math.max(score, 8 + Math.min(4, compactFileStem.length))
    }
    if (score > bestScore) {
      bestScore = score
      bestFile = item.file
    }
  }
  return bestScore >= 2 ? bestFile : ''
}

export function resolveNodePreviewUrl(label) {
  const file = matchNodePreviewFile(label)
  return file ? `/icons/nodes/${encodeURIComponent(file)}` : ''
}
