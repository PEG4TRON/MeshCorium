<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'

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

/* --- state --- */
const pages = ref(null)
const activeSectionId = ref('')
const mdContent = ref('')
const expandedSections = ref(new Set())
const loadingPages = ref(true)
const loadingMd = ref(false)

const footerStatusText = computed(() =>
  filterStatusTextForTransport(session.statusText, session.selectedTransportType)
)

/* --- H1 extraction & md rendering --- */
const h1FromMd = computed(() => {
  if (!mdContent.value) return ''
  const match = mdContent.value.match(/^#\s+(.+)$/m)
  return match ? match[1].trim() : ''
})

const mdBody = computed(() =>
  mdContent.value ? mdContent.value.replace(/^#\s+.+(\r?\n|$)/, '') : ''
)

const htmlContent = computed(() => {
  if (!mdBody.value) return ''
  try { return marked.parse(mdBody.value) }
  catch (e) { return `<p class="mc-wiki-md-error">Error: ${e.message}</p>` }
})

/* --- tree flattening with branch context --- */
const treeItems = computed(() => {
  if (!pages.value?.sections) return []
  const items = []

  function walk(list, depth, openDepths) {
    for (let i = 0; i < list.length; i++) {
      const s = list[i]
      const isLast = i === list.length - 1
      const hasKids = Array.isArray(s.children) && s.children.length > 0

      // Build branch info: which depths have a continuing vertical line
      const branches = new Set(openDepths)
      if (!isLast) branches.add(depth)

      items.push({ section: s, depth, hasChildren: hasKids, isLast, branches })

      if (hasKids && expandedSections.value.has(s.id)) {
        walk(s.children, depth + 1, branches)
      }
    }
  }

  walk(pages.value.sections, 0, new Set())
  return items
})

/* --- helpers --- */
function findSectionById(sections, id) {
  for (const s of sections) {
    if (s.id === id) return s
    if (s.children) {
      const found = findSectionById(s.children, id)
      if (found) return found
    }
  }
  return null
}

const activeSection = computed(() => {
  if (!pages.value?.sections) return null
  if (activeSectionId.value) {
    const found = findSectionById(pages.value.sections, activeSectionId.value)
    if (found) return found
  }
  return pages.value.sections[0] || null
})

const activeWikiSectionTitle = computed(() => h1FromMd.value || activeSection.value?.title || '')
const activeWikiSectionSubtitle = computed(() => activeSection.value?.subtitle || '')

function ensureExpandedPath(sections, id) {
  const expanded = new Set(expandedSections.value)
  function walk(list, path) {
    for (const s of list) {
      if (s.id === id) { path.forEach(pid => expanded.add(pid)); return true }
      if (s.children && walk(s.children, [...path, s.id])) return true
    }
    return false
  }
  walk(sections, [])
  expandedSections.value = expanded
}

async function loadMdContent(section) {
  if (!section?.md) { mdContent.value = ''; return }
  loadingMd.value = true
  try {
    const res = await fetch(`/wiki-md/${section.md}`)
    if (!res.ok) { mdContent.value = `*Failed: ${section.md} (HTTP ${res.status})*`; return }
    mdContent.value = await res.text()
  } catch (err) { mdContent.value = `*Error: ${err.message}*` }
  finally { loadingMd.value = false }
}

function selectSection(section) {
  activeSectionId.value = section.id
  ensureExpandedPath(pages.value?.sections || [], section.id)
  loadMdContent(section)
  if (route.params.section !== section.id)
    router.replace({ params: { section: section.id } })
}

function toggleExpand(sectionId) {
  const expanded = new Set(expandedSections.value)
  expanded.has(sectionId) ? expanded.delete(sectionId) : expanded.add(sectionId)
  expandedSections.value = expanded
}

async function loadPages() {
  loadingPages.value = true
  try {
    const res = await fetch(`/wiki-pages.json?locale=${locale.value}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    pages.value = await res.json()
    const routeSection = String(route.params.section || '').trim()
    const first = pages.value.sections?.[0]
    if (routeSection && findSectionById(pages.value.sections, routeSection))
      activeSectionId.value = routeSection
    else if (first)
      activeSectionId.value = first.id
    ensureExpandedPath(pages.value?.sections || [], activeSectionId.value)
    const initial = findSectionById(pages.value?.sections || [], activeSectionId.value)
    if (initial) loadMdContent(initial)
  } catch (err) { console.error('Wiki: failed to load pages.json', err) }
  finally { loadingPages.value = false }
}

onMounted(loadPages)
watch(locale, () => loadPages())
watch(() => route.params.section, (newSection) => {
  if (!pages.value?.sections) return
  const sid = String(newSection || '').trim()
  if (sid && sid !== activeSectionId.value) {
    const section = findSectionById(pages.value.sections, sid)
    if (section) {
      activeSectionId.value = sid
      ensureExpandedPath(pages.value.sections, sid)
      loadMdContent(section)
    }
  }
})

/* --- toggle + select combined --- */
function handleRowClick(item) {
  if (item.hasChildren) toggleExpand(item.section.id)
  selectSection(item.section)
}
</script>

<template>
  <ShellPageFrame
    scroller-class="mc-sidebar--wiki"
    scroller-header-class="mc-sidebar-top--wiki"
    workspace-class="mc-content--shell-body mc-content--wiki"
  >
    <template #workspace-top>
      <ShellPhonebar />
    </template>

    <template #scroller-header>
      <div class="mc-scroller-copy mc-scroller-copy--shell-top">
        <h1 class="mc-scroller-title mc-scroller-title--shell-top">{{ t('common.wiki') }}</h1>
      </div>
    </template>

    <template #scroller-body>
      <div class="mc-list-scroll mc-list-scroll--wiki">
        <div v-if="loadingPages" class="mc-list-scroll-loading">{{ t('wiki.loading') }}</div>
        <template v-else-if="treeItems.length > 0">
          <div
            v-for="item in treeItems"
            :key="item.section.id"
            class="mc-wiki-tree-row"
            :class="{
              'mc-wiki-tree-row--active': activeSectionId === item.section.id,
              'mc-wiki-tree-row--depth-0': item.depth === 0,
            }"
            @click="handleRowClick(item)"
          >
            <!-- branch lines area -->
            <div class="mc-wiki-tree-lines" :style="{ width: item.depth * 16 + 16 + 'px' }">
              <span
                v-for="d in item.depth"
                :key="d"
                class="mc-wiki-tree-line"
                :class="{ 'mc-wiki-tree-line--open': item.branches.has(d - 1) }"
              />
              <!-- toggle or spacer at current depth -->
              <span
                v-if="item.hasChildren"
                class="mc-wiki-tree-toggle"
                :class="{ 'mc-wiki-tree-toggle--expanded': expandedSections.has(item.section.id) }"
              >
                <svg width="8" height="8" viewBox="0 0 8 8" class="mc-wiki-tree-chevron">
                  <path d="M2 1 L6 4 L2 7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </span>
              <span v-else class="mc-wiki-tree-bullet" />
            </div>

            <!-- label -->
            <span class="mc-wiki-tree-label">{{ item.section.title }}</span>
          </div>
        </template>
      </div>
    </template>

    <template #scroller-footer>
      <MessagesConversationSidebar
        section="footer"
        :status-text="footerStatusText"
        :status-error="session.statusError"
        :connected="session.connected"
      />
    </template>

    <template #workspace-header>
      <header class="mc-workspace-header mc-workspace-header--wiki">
        <div class="mc-workspace-copy">
          <h2 class="mc-workspace-title">{{ activeWikiSectionTitle }}</h2>
          <p class="mc-workspace-subtitle">{{ activeWikiSectionSubtitle }}</p>
        </div>
      </header>
    </template>

    <template #workspace-body>
      <div class="mc-wiki-workspace">
        <div v-if="loadingMd" class="mc-wiki-loading">{{ t('wiki.loading') }}</div>
        <div v-else-if="htmlContent" class="mc-wiki-md-body" v-html="htmlContent" />
        <div v-else class="mc-wiki-empty"><p>{{ t('wiki.selectSection') }}</p></div>
      </div>
    </template>
  </ShellPageFrame>
</template>

<style scoped>
.mc-wiki-tree-row {
  display: flex;
  align-items: center;
  min-height: 26px;
  padding: 1px 6px;
  cursor: pointer;
  border-radius: 0;
  transition: background 0.08s;
}
.mc-wiki-tree-row:hover {
  background: rgba(255,255,255,0.03);
}
.mc-wiki-tree-row--active {
  background: rgba(90,116,201,0.12);
}

/* branch lines area - flex container */
.mc-wiki-tree-lines {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  height: 20px;
  position: relative;
}

/* each line segment - occupies 16px vertical */
.mc-wiki-tree-line {
  display: block;
  width: 16px;
  height: 100%;
  position: relative;
  flex-shrink: 0;
}
.mc-wiki-tree-line::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 0;
  border-left: 1px solid rgba(255,255,255,0.07);
}
.mc-wiki-tree-line:not(.mc-wiki-tree-line--open)::before {
  display: none;
}

/* toggle / chevron */
.mc-wiki-tree-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: rgba(255,255,255,0.35);
  transition: color 0.15s, transform 0.15s;
}
.mc-wiki-tree-toggle:hover {
  color: rgba(255,255,255,0.7);
}
.mc-wiki-tree-toggle--expanded .mc-wiki-tree-chevron {
  transform: rotate(90deg);
}
.mc-wiki-tree-chevron {
  transition: transform 0.15s;
}

/* bullet for items without children */
.mc-wiki-tree-bullet {
  display: block;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  position: relative;
}
.mc-wiki-tree-bullet::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 50%;
  width: 6px;
  height: 0;
  border-top: 1px solid rgba(255,255,255,0.07);
  margin-top: -0.5px;
}

/* label text */
.mc-wiki-tree-label {
  font-size: 13px;
  line-height: 1.3;
  color: rgba(255,255,255,0.7);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-left: 2px;
}
.mc-wiki-tree-row:hover .mc-wiki-tree-label {
  color: rgba(255,255,255,0.9);
}
.mc-wiki-tree-row--depth-0 .mc-wiki-tree-label {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  opacity: 0.55;
}
.mc-wiki-tree-row--active .mc-wiki-tree-label {
  color: #8aa8e0;
}

/* loading / empty */
.mc-wiki-loading, .mc-wiki-empty {
  padding: 24px 16px;
  opacity: 0.5;
  font-size: 13px;
}

/* workspace scrolling */
.mc-wiki-workspace {
  height: 100%;
  overflow-y: auto;
}

/* markdown body styles */
.mc-wiki-md-body { padding: 12px 16px 24px; line-height: 1.7; font-size: 14px; overflow-wrap: break-word; }
.mc-wiki-md-body :deep(h1) { font-size: 22px; font-weight: 600; margin: 0 0 12px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.08); line-height: 1.3; }
.mc-wiki-md-body :deep(h2) { font-size: 18px; font-weight: 600; margin: 20px 0 8px; line-height: 1.3; }
.mc-wiki-md-body :deep(h3) { font-size: 15px; font-weight: 600; margin: 16px 0 6px; line-height: 1.3; }
.mc-wiki-md-body :deep(h4), .mc-wiki-md-body :deep(h5), .mc-wiki-md-body :deep(h6) { font-size: 14px; font-weight: 600; margin: 12px 0 4px; }
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
.mc-wiki-md-body :deep(blockquote p:last-child) { margin-bottom: 0; }
.mc-wiki-md-body :deep(table) { border-collapse: collapse; width: 100%; margin: 0 0 12px; font-size: 13px; }
.mc-wiki-md-body :deep(th), .mc-wiki-md-body :deep(td) { padding: 6px 10px; border: 1px solid rgba(255,255,255,0.08); text-align: left; }
.mc-wiki-md-body :deep(th) { font-weight: 600; background: rgba(255,255,255,0.04); }
.mc-wiki-md-body :deep(hr) { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 16px 0; }
.mc-wiki-md-body :deep(img) { max-width: 100%; border-radius: 6px; margin: 8px 0; }
</style>
