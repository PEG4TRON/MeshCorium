<script setup>
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

import ShellPageFrame from '../components/layout/ShellPageFrame.vue'
import ShellPhonebar from '../components/layout/ShellPhonebar.vue'
import MessagesConversationSidebar from '../components/messages/MessagesConversationSidebar.vue'
import { filterStatusTextForTransport } from '../lib/statusText'
import { useSessionStore } from '../stores/session'

marked.setOptions({ gfm: true, breaks: true })

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const session = useSessionStore()

const pages = ref(null)
const activeSectionId = ref('')
const mdContent = ref('')
const expandedSections = ref(new Set())
const loadingPages = ref(true)
const loadingMd = ref(false)
const searchQuery = ref('')
const searchResults = ref([])
const searching = ref(false)
const searchActiveId = ref('')
const pageQuery = ref('')
const pageCurrentMatch = ref(1)
const wikiWorkspaceRef = ref(null)

const h1FromMd = computed(() => {
  if (!mdContent.value) return ''
  const m = mdContent.value.match(/^#\s+(.+)$/m)
  return m ? m[1].trim() : ''
})
const mdBody = computed(() =>
  mdContent.value ? mdContent.value.replace(/^#\s+.+(\r?\n|$)/, '') : ''
)

const footerStatusText = computed(() =>
  filterStatusTextForTransport(session.statusText, session.selectedTransportType)
)
const isSearching = computed(() => searchQuery.value.trim().length > 0)

function queryToRegex(query) {
  const q = String(query || '').trim()
  if (!q) return null
  try {
    const pattern = q
      .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      .replace(/\\\*/g, '\\S*')
      .replace(/\\\?/g, '.')
    return new RegExp(pattern, 'gi')
  } catch (_) {
    return null
  }
}

function sanitizeWikiHtml(html) {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    ADD_ATTR: ['target', 'rel'],
  })
}

function renderWikiMarkdown(body) {
  return sanitizeWikiHtml(marked.parse(body))
}

function transformVisibleText(html, regexes, currentMatch = 0) {
  if (!html || typeof document === 'undefined') return { html, matches: 0 }

  const template = document.createElement('template')
  template.innerHTML = html
  let matches = 0
  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement
      if (!parent) return NodeFilter.FILTER_REJECT
      const tag = parent.tagName?.toLowerCase()
      if (['script', 'style', 'textarea'].includes(tag)) return NodeFilter.FILTER_REJECT
      return node.nodeValue ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT
    }
  })

  const textNodes = []
  while (walker.nextNode()) textNodes.push(walker.currentNode)

  for (const node of textNodes) {
    const source = node.nodeValue || ''
    const ranges = []
    for (const regex of regexes) {
      if (!regex) continue
      regex.lastIndex = 0
      let match
      while ((match = regex.exec(source)) !== null) {
        if (!match[0]) { regex.lastIndex += 1; continue }
        ranges.push({ start: match.index, end: match.index + match[0].length })
      }
    }
    if (ranges.length === 0) continue

    ranges.sort((a, b) => a.start - b.start || b.end - a.end)
    const merged = []
    for (const range of ranges) {
      const last = merged[merged.length - 1]
      if (last && range.start <= last.end) last.end = Math.max(last.end, range.end)
      else merged.push({ ...range })
    }

    const fragment = document.createDocumentFragment()
    let cursor = 0
    for (const range of merged) {
      if (range.start > cursor) fragment.appendChild(document.createTextNode(source.slice(cursor, range.start)))
      matches += 1
      const mark = document.createElement('mark')
      mark.className = matches === currentMatch
        ? 'mc-wiki-highlight mc-wiki-highlight--current'
        : 'mc-wiki-highlight'
      if (matches === currentMatch) mark.dataset.pageSearchCurrent = 'true'
      mark.textContent = source.slice(range.start, range.end)
      fragment.appendChild(mark)
      cursor = range.end
    }
    if (cursor < source.length) fragment.appendChild(document.createTextNode(source.slice(cursor)))
    node.parentNode?.replaceChild(fragment, node)
  }

  return { html: template.innerHTML, matches }
}

/* pageMatchesNum: count matches in visible rendered text only */
const pageMatchesNum = computed(() => {
  const q = pageQuery.value.trim()
  const body = mdBody.value
  if (!q || !body) return 0
  try {
    const regex = queryToRegex(q)
    if (!regex) return 0
    return transformVisibleText(renderWikiMarkdown(body), [regex], 0).matches
  } catch (_) { return 0 }
})

const pageCurrentMatchDisplay = computed(() => {
  if (pageMatchesNum.value === 0) return 0
  return Math.min(pageCurrentMatch.value, pageMatchesNum.value)
})

/* htmlContent: render + highlight visible text only */
const htmlContent = computed(() => {
  const body = mdBody.value
  if (!body) return ''
  try {
    let html = renderWikiMarkdown(body)
    // scroller search
    if (searchActiveId.value && searchQuery.value.trim()) {
      const regexes = searchQuery.value.trim().split(/\s+/)
        .filter(term => term.length >= 2)
        .map(queryToRegex)
        .filter(Boolean)
      if (regexes.length > 0) html = transformVisibleText(html, regexes, 0).html
    }
    // page search
    const q = pageQuery.value.trim()
    if (q && pageCurrentMatch.value > 0) {
      const regex = queryToRegex(q)
      if (regex) html = transformVisibleText(html, [regex], pageCurrentMatchDisplay.value).html
    }
    return html
  } catch (e) { return `<p class="mc-wiki-md-error">Error: ${e.message}</p>` }
})

/* tree */
const treeItems = computed(() => {
  if (!pages.value?.sections) return []
  const items = []
  function walk(list, depth, openDepths) {
    for (let i = 0; i < list.length; i++) {
      const s = list[i]; const isLast = i === list.length - 1
      const hasKids = Array.isArray(s.children) && s.children.length > 0
      const branches = new Set(openDepths); if (!isLast) branches.add(depth)
      items.push({ section: s, depth, hasChildren: hasKids, isLast, branches })
      if (hasKids && expandedSections.value.has(s.id)) walk(s.children, depth + 1, branches)
    }
  }
  walk(pages.value.sections, 0, new Set()); return items
})

function findSectionById(sections, id) {
  for (const s of sections) { if (s.id === id) return s; if (s.children) { const f = findSectionById(s.children, id); if (f) return f } }
  return null
}

let searchTimer = null
let pageSearchScrollTimer = null
let searchRequestId = 0
let mdRequestId = 0
function onSearchInput() {
  clearTimeout(searchTimer)
  if (!searchQuery.value.trim()) {
    searchRequestId += 1
    searchResults.value = []
    searching.value = false
    return
  }
  searchTimer = setTimeout(() => performSearch(), 250)
}
async function performSearch() {
  const requestId = ++searchRequestId
  const q = searchQuery.value.trim()
  if (!q) return
  searching.value = true
  try {
    const res = await fetch(`/api/wiki/search?q=${encodeURIComponent(q)}&locale=${locale.value}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    if (requestId !== searchRequestId) return
    searchResults.value = data.results || []
  } catch (err) {
    if (requestId === searchRequestId) {
      console.error('Wiki search failed:', err)
      searchResults.value = []
    }
  } finally {
    if (requestId === searchRequestId) searching.value = false
  }
}
function selectSearchResult(result) {
  const q = searchQuery.value.trim()
  searchActiveId.value = q
  pageQuery.value = q
  pageCurrentMatch.value = 1

  if (pages.value?.sections) {
    const section = findSectionById(pages.value.sections, result.id)
    if (section) {
      selectSection(section, { preservePageSearch: true, preserveScrollerHighlight: true })
      return
    }
  }

  activeSectionId.value = result.id
  router.replace({ params: { section: result.id } })
  loadMdContent({ id: result.id, md: result.path })
}
function clearSearch() { searchQuery.value = ''; searchResults.value = []; searchActiveId.value = '' }

function scrollToCurrentPageMatch() {
  if (!pageQuery.value.trim() || pageMatchesNum.value === 0) return

  clearTimeout(pageSearchScrollTimer)
  pageSearchScrollTimer = setTimeout(async () => {
    await nextTick()
    const container = wikiWorkspaceRef.value
    const current = container?.querySelector?.('mark[data-page-search-current="true"]')
    if (!container || !current) return

    const containerRect = container.getBoundingClientRect()
    const currentRect = current.getBoundingClientRect()
    const targetTop = container.scrollTop
      + (currentRect.top - containerRect.top)
      - (container.clientHeight / 2)
      + (currentRect.height / 2)

    container.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' })
  }, 0)
}

function pageSearchPrev() {
  if (pageMatchesNum.value === 0) return
  pageCurrentMatch.value = pageCurrentMatch.value <= 1 ? pageMatchesNum.value : pageCurrentMatch.value - 1
}
function pageSearchNext() {
  if (pageMatchesNum.value === 0) return
  pageCurrentMatch.value = pageCurrentMatch.value >= pageMatchesNum.value ? 1 : pageCurrentMatch.value + 1
}
function clearPageSearch() { pageQuery.value = ''; pageCurrentMatch.value = 1 }

const activeSection = computed(() => {
  if (!pages.value?.sections) return null
  if (activeSectionId.value) { const f = findSectionById(pages.value.sections, activeSectionId.value); if (f) return f }
  return pages.value.sections?.[0] || null
})
const activeWikiSectionTitle = computed(() => h1FromMd.value || activeSection.value?.title || '')
const activeWikiSectionSubtitle = computed(() => activeSection.value?.subtitle || '')

function ensureExpandedPath(sections, id) {
  const expanded = new Set(expandedSections.value)
  function walk(list, path) {
    for (const s of list) { if (s.id === id) { path.forEach(pid => expanded.add(pid)); return true }; if (s.children && walk(s.children, [...path, s.id])) return true }
    return false
  }; walk(sections, []); expandedSections.value = expanded
}

async function loadMdContent(section) {
  const requestId = ++mdRequestId
  if (!section?.md) {
    mdContent.value = ''
    return
  }
  loadingMd.value = true
  try {
    const res = await fetch(`/wiki-md/${section.md}`)
    if (requestId !== mdRequestId) return
    if (!res.ok) {
      mdContent.value = `*Failed: ${section.md} (HTTP ${res.status})*`
      return
    }
    mdContent.value = await res.text()
  } catch (err) {
    if (requestId === mdRequestId) mdContent.value = `*Error: ${err.message}*`
  } finally {
    if (requestId === mdRequestId) loadingMd.value = false
  }
}

function selectSection(section, options = {}) {
  if (!options.preservePageSearch) clearPageSearch()
  if (!options.preserveScrollerHighlight) searchActiveId.value = ''

  activeSectionId.value = section.id
  ensureExpandedPath(pages.value?.sections || [], section.id)
  loadMdContent(section)
  if (route.params.section !== section.id) router.replace({ params: { section: section.id } })
}

function toggleExpand(id) {
  const e = new Set(expandedSections.value); e.has(id) ? e.delete(id) : e.add(id); expandedSections.value = e
}

async function loadPages() {
  loadingPages.value = true
  try {
    const res = await fetch(`/wiki-pages.json?locale=${locale.value}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`); pages.value = await res.json()
    const routeSection = String(route.params.section || '').trim(); const first = pages.value.sections?.[0]
    if (routeSection && findSectionById(pages.value.sections, routeSection)) activeSectionId.value = routeSection
    else if (first) activeSectionId.value = first.id
    ensureExpandedPath(pages.value?.sections || [], activeSectionId.value)
    const initial = findSectionById(pages.value?.sections || [], activeSectionId.value)
    if (initial) loadMdContent(initial)
  } catch (err) { console.error('Wiki: failed to load pages.json', err) }
  finally { loadingPages.value = false }
}

onMounted(loadPages)
watch(locale, () => { clearSearch(); loadPages() })
watch(pageQuery, () => { pageCurrentMatch.value = 1 })
watch([pageQuery, pageCurrentMatchDisplay, pageMatchesNum, mdBody], () => scrollToCurrentPageMatch(), { flush: 'post' })
watch(() => route.params.section, (ns) => {
  if (!pages.value?.sections) return; const sid = String(ns || '').trim()
  if (sid && sid !== activeSectionId.value) {
    const section = findSectionById(pages.value.sections, sid)
    if (section) { activeSectionId.value = sid; ensureExpandedPath(pages.value.sections, sid); loadMdContent(section) }
  }
})

function handleRowClick(item) {
  if (item.hasChildren) toggleExpand(item.section.id); selectSection(item.section)
}
</script>

<template>
  <ShellPageFrame scroller-class="mc-sidebar--wiki" scroller-header-class="mc-sidebar-top--wiki" workspace-class="mc-content--shell-body mc-content--wiki">
    <template #workspace-top><ShellPhonebar /></template>
    <template #scroller-header>
      <div class="mc-scroller-copy mc-scroller-copy--shell-top mc-scroller-copy--wiki">
        <h1 class="mc-scroller-title mc-scroller-title--shell-top">{{ t('common.wiki') }}</h1>
        <div class="mc-wiki-search-box">
          <svg class="mc-wiki-search-icon" width="12" height="12" viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="4.5" stroke="currentColor" stroke-width="1.5"/><path d="M9.5 9.5L13 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <input class="mc-wiki-search-input" type="text" :placeholder="t('wiki.searchPlaceholder')" v-model="searchQuery" @input="onSearchInput" @keydown.escape="clearSearch" />
          <button v-if="isSearching" class="mc-wiki-search-clear" @click="clearSearch">&times;</button>
        </div>
      </div>
    </template>
    <template #scroller-body>
      <div class="mc-list-scroll mc-list-scroll--wiki">
        <template v-if="isSearching">
          <div v-if="searching" class="mc-wiki-search-status">{{ t('wiki.loading') }}</div>
          <div v-else-if="searchResults.length === 0" class="mc-wiki-search-status">{{ t('wiki.searchNoResults') }}</div>
          <div v-else class="mc-wiki-search-results">
            <div class="mc-wiki-search-count">{{ searchResults.length }} {{ t('wiki.searchResults') }}</div>
            <div v-for="r in searchResults" :key="r.id" class="mc-wiki-search-item" :class="{ 'mc-wiki-search-item--active': activeSectionId === r.id }" @click="selectSearchResult(r)">
              <div class="mc-wiki-search-item-title"><span v-if="r.parent" class="mc-wiki-search-item-parent">{{ r.parent }}/</span><span class="mc-wiki-search-item-name">{{ r.title }}</span></div>
              <div class="mc-wiki-search-item-snippet">{{ r.snippet }}</div>
              <div class="mc-wiki-search-item-meta">{{ r.matches }} {{ t('wiki.searchMatches') }}</div>
            </div>
          </div>
        </template>
        <template v-else>
          <div v-if="loadingPages" class="mc-list-scroll-loading">{{ t('wiki.loading') }}</div>
          <template v-else-if="treeItems.length > 0">
            <div v-for="item in treeItems" :key="item.section.id" class="mc-wiki-tree-row" :class="{ 'mc-wiki-tree-row--active': activeSectionId === item.section.id, 'mc-wiki-tree-row--depth-0': item.depth === 0 }" @click="handleRowClick(item)">
              <div class="mc-wiki-tree-lines" :style="{ width: item.depth * 16 + 16 + 'px' }">
                <span v-for="d in item.depth" :key="d" class="mc-wiki-tree-line" :class="{ 'mc-wiki-tree-line--open': item.branches.has(d - 1) }" /><span v-if="item.hasChildren" class="mc-wiki-tree-toggle" :class="{ 'mc-wiki-tree-toggle--expanded': expandedSections.has(item.section.id) }"><svg width="8" height="8" viewBox="0 0 8 8" class="mc-wiki-tree-chevron"><path d="M2 1 L6 4 L2 7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span v-else class="mc-wiki-tree-bullet" />
              </div>
              <span class="mc-wiki-tree-label">{{ item.section.title }}</span>
            </div>
          </template>
        </template>
      </div>
    </template>
    <template #scroller-footer>
      <MessagesConversationSidebar section="footer" :status-text="footerStatusText" :status-error="session.statusError" :connected="session.connected" />
    </template>
    <template #workspace-header>
      <header class="mc-workspace-header mc-workspace-header--wiki">
        <div class="mc-workspace-copy">
          <div class="mc-workspace-title-row">
            <h2 class="mc-workspace-title">{{ activeWikiSectionTitle }}</h2>
            <div class="mc-page-search-box">
              <svg class="mc-page-search-icon" width="11" height="11" viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="4.5" stroke="currentColor" stroke-width="1.5"/><path d="M9.5 9.5L13 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
              <input class="mc-page-search-input" type="text" :placeholder="t('wiki.searchPlaceholder')" v-model="pageQuery" @keydown.escape="clearPageSearch" />
              <template v-if="pageQuery.trim()">
                <div class="mc-page-search-meta"><span v-if="pageMatchesNum > 0">{{ pageCurrentMatchDisplay }}/{{ pageMatchesNum }}</span><span v-else>0/0</span></div>
                <button class="mc-page-search-btn" @click="pageSearchPrev" :disabled="pageMatchesNum === 0">&#9650;</button>
                <button class="mc-page-search-btn" @click="pageSearchNext" :disabled="pageMatchesNum === 0">&#9660;</button>
                <button class="mc-page-search-clear" @click="clearPageSearch">&times;</button>
              </template>
            </div>
          </div>
          <p class="mc-workspace-subtitle">{{ activeWikiSectionSubtitle }}</p>
        </div>
      </header>
    </template>
    <template #workspace-body>
      <div ref="wikiWorkspaceRef" class="mc-wiki-workspace">
        <div v-if="loadingMd" class="mc-wiki-loading">{{ t('wiki.loading') }}</div>
        <div v-else-if="htmlContent" class="mc-wiki-md-body" v-html="htmlContent" />
        <div v-else class="mc-wiki-empty"><p>{{ t('wiki.selectSection') }}</p></div>
      </div>
    </template>
  </ShellPageFrame>
</template>

<style scoped>
.mc-scroller-copy--wiki { display: flex; flex-direction: row; align-items: center; gap: 8px; }
.mc-scroller-copy--wiki .mc-scroller-title { flex-shrink: 0; font-size: 30px; font-weight: 700; letter-spacing: -0.02em; }
.mc-wiki-search-box { position: relative; display: flex; align-items: center; flex: 1; min-width: 0; }
.mc-wiki-search-icon { position: absolute; left: 6px; color: rgba(255,255,255,0.3); pointer-events: none; }
.mc-wiki-search-input { width: 100%; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08); border-radius: 5px; padding: 5px 22px 5px 24px; font-size: 13px; color: rgba(255,255,255,0.8); outline: none; transition: border-color 0.15s, background 0.15s; }
.mc-wiki-search-input::placeholder { color: rgba(255,255,255,0.25); }
.mc-wiki-search-input:focus { border-color: rgba(90,116,201,0.5); background: rgba(255,255,255,0.08); }
.mc-wiki-search-clear { position: absolute; right: 4px; background: none; border: none; color: rgba(255,255,255,0.3); cursor: pointer; font-size: 14px; line-height: 1; padding: 0 2px; }
.mc-wiki-search-clear:hover { color: rgba(255,255,255,0.7); }
.mc-wiki-search-status { padding: 16px; font-size: 12px; color: rgba(255,255,255,0.4); text-align: center; }
.mc-wiki-search-results { padding: 4px 0; }
.mc-wiki-search-count { padding: 6px 10px; font-size: 11px; color: rgba(255,255,255,0.3); text-transform: uppercase; letter-spacing: 0.05em; }
.mc-wiki-search-item { padding: 6px 10px; cursor: pointer; border-left: 2px solid transparent; transition: background 0.08s, border-color 0.08s; }
.mc-wiki-search-item:hover { background: rgba(255,255,255,0.03); border-left-color: rgba(90,116,201,0.3); }
.mc-wiki-search-item--active { background: rgba(90,116,201,0.1); border-left-color: #5A74C9; }
.mc-wiki-search-item-title { font-size: 13px; color: rgba(255,255,255,0.8); line-height: 1.3; margin-bottom: 2px; }
.mc-wiki-search-item-parent { opacity: 0.45; font-size: 11px; }
.mc-wiki-search-item-name { font-weight: 500; }
.mc-wiki-search-item-snippet { font-size: 11px; color: rgba(255,255,255,0.35); line-height: 1.4; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mc-wiki-search-item-meta { font-size: 10px; color: rgba(255,255,255,0.2); margin-top: 1px; }
.mc-wiki-tree-row { display: flex; align-items: center; min-height: 26px; padding: 1px 6px; cursor: pointer; border-radius: 0; transition: background 0.08s; }
.mc-wiki-tree-row:hover { background: rgba(255,255,255,0.03); }
.mc-wiki-tree-row--active { background: rgba(90,116,201,0.12); }
.mc-wiki-tree-lines { display: flex; align-items: center; flex-shrink: 0; height: 20px; position: relative; }
.mc-wiki-tree-line { display: block; width: 16px; height: 100%; position: relative; flex-shrink: 0; }
.mc-wiki-tree-line::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; border-left: 1px solid rgba(255,255,255,0.07); }
.mc-wiki-tree-line:not(.mc-wiki-tree-line--open)::before { display: none; }
.mc-wiki-tree-toggle { display: flex; align-items: center; justify-content: center; width: 16px; height: 16px; flex-shrink: 0; color: rgba(255,255,255,0.35); transition: color 0.15s, transform 0.15s; }
.mc-wiki-tree-toggle:hover { color: rgba(255,255,255,0.7); }
.mc-wiki-tree-toggle--expanded .mc-wiki-tree-chevron { transform: rotate(90deg); }
.mc-wiki-tree-chevron { transition: transform 0.15s; }
.mc-wiki-tree-bullet { display: block; width: 16px; height: 16px; flex-shrink: 0; position: relative; }
.mc-wiki-tree-bullet::before { content: ''; position: absolute; left: 3px; top: 50%; width: 6px; border-top: 1px solid rgba(255,255,255,0.07); margin-top: -0.5px; }
.mc-wiki-tree-label { font-size: 13px; line-height: 1.3; color: rgba(255,255,255,0.7); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-left: 2px; }
.mc-wiki-tree-row:hover .mc-wiki-tree-label { color: rgba(255,255,255,0.9); }
.mc-wiki-tree-row--depth-0 .mc-wiki-tree-label { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.55; }
.mc-wiki-tree-row--active .mc-wiki-tree-label { color: #8aa8e0; }
.mc-wiki-loading, .mc-wiki-empty { padding: 24px 16px; opacity: 0.5; font-size: 13px; }
.mc-wiki-workspace { height: 100%; overflow-y: auto; }
.mc-workspace-title-row { display: flex; flex-direction: row; align-items: center; gap: 10px; }
.mc-workspace-title-row .mc-workspace-title { flex-shrink: 0; flex-grow: 0; }
.mc-page-search-box { position: relative; display: flex; align-items: center; gap: 3px; margin-left: auto; max-width: 280px; flex-shrink: 1; min-width: 0; }
.mc-page-search-icon { position: absolute; left: 8px; color: rgba(255,255,255,0.25); pointer-events: none; }
.mc-page-search-input { width: 120px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); border-radius: 4px; padding: 3px 6px 3px 24px; font-size: 12px; color: rgba(255,255,255,0.6); outline: none; transition: width 0.2s, border-color 0.15s, background 0.15s; }
.mc-page-search-input:focus { width: 200px; border-color: rgba(90,116,201,0.4); background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.9); }
.mc-page-search-input::placeholder { color: rgba(255,255,255,0.2); }
.mc-page-search-meta { font-size: 11px; white-space: nowrap; color: rgba(255,255,255,0.35); padding: 0 2px; }
.mc-page-search-btn { background: none; border: none; color: rgba(255,255,255,0.3); cursor: pointer; font-size: 9px; line-height: 1; padding: 2px; }
.mc-page-search-btn:hover:not(:disabled) { color: rgba(255,255,255,0.7); }
.mc-page-search-btn:disabled { opacity: 0.2; cursor: default; }
.mc-page-search-clear { background: none; border: none; color: rgba(255,255,255,0.3); cursor: pointer; font-size: 13px; line-height: 1; padding: 0 2px; }
.mc-page-search-clear:hover { color: rgba(255,255,255,0.7); }
.mc-wiki-md-body { padding: 12px 16px 24px; line-height: 1.7; font-size: 14px; overflow-wrap: break-word; }
.mc-wiki-md-body :deep(mark.mc-wiki-highlight) { background: rgba(255,213,0,0.3); color: inherit; border-radius: 2px; padding: 0 1px; }
.mc-wiki-md-body :deep(mark.mc-wiki-highlight--current) { background: rgba(255,180,0,0.55); color: inherit; border-radius: 2px; padding: 0 1px; }
.mc-wiki-md-body :deep(h1) { font-size: 22px; font-weight: 600; margin: 0 0 12px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.08); line-height: 1.3; }
.mc-wiki-md-body :deep(h2) { font-size: 18px; font-weight: 600; margin: 20px 0 8px; line-height: 1.3; }
.mc-wiki-md-body :deep(h3) { font-size: 15px; font-weight: 600; margin: 16px 0 6px; line-height: 1.3; }
.mc-wiki-md-body :deep(p) { margin: 0 0 10px; }
.mc-wiki-md-body :deep(strong) { font-weight: 600; }
.mc-wiki-md-body :deep(em) { font-style: italic; }
.mc-wiki-md-body :deep(a) { color: #5A74C9; text-decoration: none; }
.mc-wiki-md-body :deep(a:hover) { text-decoration: underline; }
.mc-wiki-md-body :deep(ul), .mc-wiki-md-body :deep(ol) { margin: 0 0 10px; padding-left: 22px; }
.mc-wiki-md-body :deep(li) { margin-bottom: 3px; }
.mc-wiki-md-body :deep(li > ul), .mc-wiki-md-body :deep(li > ol) { margin-bottom: 0; }
.mc-wiki-md-body :deep(pre) { background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; padding: 10px 12px; overflow-x: auto; margin: 0 0 12px; font-size: 13px; line-height: 1.5; }
.mc-wiki-md-body :deep(code) { font-family: 'Geist Mono','JetBrains Mono','Cascadia Code','Fira Code',monospace; font-size: 13px; background: rgba(0,0,0,0.2); padding: 1px 5px; border-radius: 3px; }
.mc-wiki-md-body :deep(pre code) { background: none; padding: 0; border-radius: 0; }
.mc-wiki-md-body :deep(blockquote) { margin: 0 0 12px; padding: 4px 12px; border-left: 3px solid #5A74C9; opacity: 0.85; }
.mc-wiki-md-body :deep(table) { border-collapse: collapse; width: 100%; margin: 0 0 12px; font-size: 13px; }
.mc-wiki-md-body :deep(th), .mc-wiki-md-body :deep(td) { padding: 6px 10px; border: 1px solid rgba(255,255,255,0.08); text-align: left; }
.mc-wiki-md-body :deep(th) { font-weight: 600; background: rgba(255,255,255,0.04); }
.mc-wiki-md-body :deep(hr) { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 16px 0; }
.mc-wiki-md-body :deep(img) { max-width: 100%; border-radius: 6px; margin: 8px 0; }
</style>
