#!/usr/bin/env node

import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { spawn } from 'node:child_process'

const argv = process.argv.slice(2)

function takeArg(name, fallback = '') {
  const index = argv.indexOf(name)
  if (index === -1 || index === argv.length - 1) {
    return fallback
  }
  return String(argv[index + 1] || '')
}

const baseUrl = takeArg('--base-url', 'http://127.0.0.1:8080')
const username = takeArg('--username', '')
const password = takeArg('--password', '')
const runs = Math.max(1, Number.parseInt(takeArg('--runs', '5'), 10) || 5)
const width = Math.max(320, Number.parseInt(takeArg('--width', '1440'), 10) || 1440)
const height = Math.max(320, Number.parseInt(takeArg('--height', '900'), 10) || 900)
const outPath = takeArg('--out', '')
const ensureConnected = argv.includes('--connect')

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function mean(values) {
  if (!values.length) {
    return 0
  }
  return values.reduce((sum, value) => sum + Number(value || 0), 0) / values.length
}

function round(value, digits = 2) {
  const power = 10 ** digits
  return Math.round(Number(value || 0) * power) / power
}

function percentDiff(legacyValue, vueValue) {
  if (!legacyValue) {
    return 0
  }
  return ((vueValue - legacyValue) / legacyValue) * 100
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options)
  if (!response.ok) {
    throw new Error(`Request failed ${response.status}: ${url}`)
  }
  return response.json()
}

async function requestAuthCookie() {
  if (!username || !password) {
    return ''
  }
  const response = await fetch(`${baseUrl}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(String(data?.error || 'Login failed'))
  }
  const setCookieHeader = typeof response.headers.getSetCookie === 'function'
    ? (response.headers.getSetCookie()[0] || '')
    : String(response.headers.get('set-cookie') || '')
  const match = setCookieHeader.match(/meshcorium_auth=([^;]+)/)
  if (!match) {
    throw new Error('meshcorium_auth cookie missing in login response')
  }
  return String(match[1] || '')
}

async function authedJson(pathname, cookieValue, options = {}) {
  const response = await fetch(`${baseUrl}${pathname}`, {
    headers: {
      Cookie: `meshcorium_auth=${cookieValue}`,
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
    ...options,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(String(data?.error || `Request failed ${response.status}: ${pathname}`))
  }
  return data
}

function normalizePort(value) {
  const next = String(value || '').trim()
  return next && next !== '-' ? next : ''
}

async function ensureConnectedSession(cookieValue) {
  const settingsPayload = await authedJson('/api/client-settings', cookieValue)
  const portsPayload = await authedJson('/api/ports', cookieValue)
  const ports = Array.isArray(portsPayload?.ports) ? portsPayload.ports : []
  const startup = settingsPayload?.resolved_startup_connection || {}
  const lastSuccessful = settingsPayload?.last_successful_config || {}
  const firstSaved = Array.isArray(settingsPayload?.saved_connections) ? (settingsPayload.saved_connections[0] || {}) : {}
  const port = normalizePort(startup.port || lastSuccessful.port || firstSaved.port || ports[0]?.device || '')
  const baudrate = Number(startup.baudrate || lastSuccessful.baudrate || firstSaved.baudrate || 115200) || 115200
  if (!port) {
    throw new Error('No serial port available for --connect benchmark mode')
  }
  await authedJson('/api/connect', cookieValue, {
    method: 'POST',
    body: JSON.stringify({
      port,
      baudrate,
      timeout: 4.0,
      light: true,
    }),
  })
  return { port, baudrate }
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl
    this.socket = null
    this.nextId = 1
    this.pending = new Map()
    this.eventWaiters = new Map()
  }

  async connect() {
    await new Promise((resolve, reject) => {
      const socket = new WebSocket(this.wsUrl)
      this.socket = socket
      socket.addEventListener('open', () => resolve())
      socket.addEventListener('message', (event) => {
        const payload = JSON.parse(String(event.data || '{}'))
        if (payload.id) {
          const pending = this.pending.get(payload.id)
          if (!pending) {
            return
          }
          this.pending.delete(payload.id)
          if (payload.error) {
            pending.reject(new Error(payload.error.message || 'CDP request failed'))
            return
          }
          pending.resolve(payload.result || {})
          return
        }
        const waiters = this.eventWaiters.get(payload.method)
        if (waiters && waiters.length) {
          const waiter = waiters.shift()
          waiter(payload.params || {})
        }
      })
      socket.addEventListener('error', (event) => reject(event.error || new Error('WebSocket error')))
      socket.addEventListener('close', () => {
        for (const pending of this.pending.values()) {
          pending.reject(new Error('CDP socket closed'))
        }
        this.pending.clear()
      })
    })
  }

  async send(method, params = {}) {
    const id = this.nextId
    this.nextId += 1
    const payload = JSON.stringify({ id, method, params })
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.socket.send(payload)
    })
  }

  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    })
    if (result.exceptionDetails) {
      throw new Error(
        result.exceptionDetails.exception?.description
        || result.exceptionDetails.text
        || result.result?.description
        || 'Runtime evaluation failed',
      )
    }
    return result.result?.value
  }

  async close() {
    try {
      this.socket?.close()
    } catch {}
  }
}

async function waitForDebugger(port, timeoutMs = 15000) {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    try {
      return await fetchJson(`http://127.0.0.1:${port}/json/list`)
    } catch {
      await sleep(200)
    }
  }
  throw new Error('Chromium DevTools endpoint did not start in time')
}

async function waitForCondition(cdp, expression, timeoutMs = 20000, intervalMs = 200) {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    const ok = await cdp.evaluate(expression).catch(() => false)
    if (ok) {
      return
    }
    await sleep(intervalMs)
  }
  throw new Error(`Timed out waiting for condition: ${expression}`)
}

async function navigate(cdp, url) {
  await cdp.send('Page.navigate', { url })
  await waitForCondition(cdp, 'document.readyState === "complete"', 20000)
}

async function collectMetrics(cdp, routePath) {
  await waitForCondition(
    cdp,
    'location.pathname !== "/login" && !!document.body',
    20000,
  )
  await sleep(1200)
  const pageMetrics = await cdp.send('Performance.getMetrics')
  const domCounters = await cdp.send('Memory.getDOMCounters').catch(() => ({}))
  const pageData = await cdp.evaluate(`
    (() => {
      try {
        const nav = performance.getEntriesByType('navigation')[0]
        const paints = Object.fromEntries(
          performance.getEntriesByType('paint').map((entry) => [entry.name, entry.startTime])
        )
        const lcpEntries = performance.getEntriesByType('largest-contentful-paint')
        const lastLcp = lcpEntries.length ? lcpEntries[lcpEntries.length - 1] : null
        const resources = performance.getEntriesByType('resource')
        const isImageResource = (item) => {
          const name = String(item.name || '')
          return item.initiatorType === 'img'
            || name.includes('.png')
            || name.includes('.svg')
            || name.includes('.jpg')
            || name.includes('.jpeg')
            || name.includes('.gif')
            || name.includes('.webp')
        }
        const aggregate = (predicate, field) => resources
          .filter(predicate)
          .reduce((sum, item) => sum + Number(item[field] || 0), 0)
        const count = (predicate) => resources.filter(predicate).length
        return {
          route: location.pathname,
          title: document.title,
          pageError: '',
          dcl: nav ? nav.domContentLoadedEventEnd : 0,
          load: nav ? nav.loadEventEnd : 0,
          responseEnd: nav ? nav.responseEnd : 0,
          fcp: paints['first-contentful-paint'] || 0,
          lcp: lastLcp ? Number(lastLcp.startTime || 0) : 0,
          resourcesCount: resources.length,
          resourcesTransfer: aggregate(() => true, 'transferSize'),
          jsCount: count((item) => item.initiatorType === 'script' || String(item.name || '').includes('.js')),
          jsTransfer: aggregate((item) => item.initiatorType === 'script' || String(item.name || '').includes('.js'), 'transferSize'),
          cssCount: count((item) => String(item.name || '').includes('.css')),
          cssTransfer: aggregate((item) => String(item.name || '').includes('.css'), 'transferSize'),
          imgCount: count(isImageResource),
          imgTransfer: aggregate(isImageResource, 'transferSize'),
          jsHeapUsed: performance.memory ? performance.memory.usedJSHeapSize : 0,
          jsHeapTotal: performance.memory ? performance.memory.totalJSHeapSize : 0,
          bodyTextLength: String(document.body?.innerText || '').length,
        }
      } catch (error) {
        return {
          route: location.pathname,
          title: document.title,
          pageError: String(error && error.message || error || 'page metric collection failed'),
          dcl: 0,
          load: 0,
          responseEnd: 0,
          fcp: 0,
          lcp: 0,
          resourcesCount: 0,
          resourcesTransfer: 0,
          jsCount: 0,
          jsTransfer: 0,
          cssCount: 0,
          cssTransfer: 0,
          imgCount: 0,
          imgTransfer: 0,
          jsHeapUsed: 0,
          jsHeapTotal: 0,
          bodyTextLength: String(document.body?.innerText || '').length,
        }
      }
    })()
  `)
  const perfMap = Object.fromEntries((pageMetrics.metrics || []).map((entry) => [entry.name, entry.value]))
  return {
    ...pageData,
    taskDurationMs: Number(perfMap.TaskDuration || 0) * 1000,
    scriptDurationMs: Number(perfMap.ScriptDuration || 0) * 1000,
    layoutDurationMs: Number(perfMap.LayoutDuration || 0) * 1000,
    styleDurationMs: Number(perfMap.RecalcStyleDuration || 0) * 1000,
    devtoolsJsHeapUsed: Number(perfMap.JSHeapUsedSize || 0),
    devtoolsNodes: Number(perfMap.Nodes || 0),
    documents: Number(perfMap.Documents || 0),
    domNodes: Number(domCounters.nodes || 0),
  }
}

async function runSingle(routePath, index) {
  const debugPort = 9400 + index
  const profileDir = await fs.mkdtemp(path.join(os.tmpdir(), 'meshcorium-bench-'))
  const browser = spawn('env', [
    '-u', 'DISPLAY',
    'chromium',
    '--headless=new',
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${profileDir}`,
    '--disable-gpu',
    '--hide-scrollbars',
    '--no-first-run',
    '--no-default-browser-check',
    `--window-size=${width},${height}`,
    'about:blank',
  ], {
    stdio: 'ignore',
  })

  let cdp = null
  try {
    const cookieValue = username && password ? await requestAuthCookie() : ''
    if (ensureConnected && cookieValue) {
      await ensureConnectedSession(cookieValue)
    }
    const targets = await waitForDebugger(debugPort)
    const target = targets.find((entry) => entry.type === 'page') || targets[0]
    if (!target?.webSocketDebuggerUrl) {
      throw new Error('Failed to obtain Chromium page debugger URL')
    }
    cdp = new CdpClient(target.webSocketDebuggerUrl)
    await cdp.connect()
    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    await cdp.send('Network.enable')
    await cdp.send('Performance.enable')
    await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
    if (cookieValue) {
      await cdp.send('Network.setCookie', {
        name: 'meshcorium_auth',
        value: cookieValue,
        domain: '127.0.0.1',
        path: '/',
        httpOnly: true,
        sameSite: 'Lax',
      })
    }
    await navigate(cdp, `${baseUrl}${routePath}`)
    return await collectMetrics(cdp, routePath)
  } finally {
    await cdp?.close().catch(() => {})
    browser.kill('SIGTERM')
    await fs.rm(profileDir, { recursive: true, force: true }).catch(() => {})
  }
}

function summarize(label, samples) {
  return {
    label,
    runs: samples.length,
    dclMs: round(mean(samples.map((item) => item.dcl))),
    loadMs: round(mean(samples.map((item) => item.load))),
    fcpMs: round(mean(samples.map((item) => item.fcp))),
    lcpMs: round(mean(samples.map((item) => item.lcp))),
    resourcesCount: round(mean(samples.map((item) => item.resourcesCount))),
    resourcesTransferKb: round(mean(samples.map((item) => item.resourcesTransfer / 1024))),
    jsTransferKb: round(mean(samples.map((item) => item.jsTransfer / 1024))),
    cssTransferKb: round(mean(samples.map((item) => item.cssTransfer / 1024))),
    imgTransferKb: round(mean(samples.map((item) => item.imgTransfer / 1024))),
    taskDurationMs: round(mean(samples.map((item) => item.taskDurationMs))),
    scriptDurationMs: round(mean(samples.map((item) => item.scriptDurationMs))),
    layoutDurationMs: round(mean(samples.map((item) => item.layoutDurationMs))),
    styleDurationMs: round(mean(samples.map((item) => item.styleDurationMs))),
    jsHeapUsedMb: round(mean(samples.map((item) => item.jsHeapUsed / (1024 * 1024)))),
    domNodes: round(mean(samples.map((item) => item.domNodes))),
  }
}

function compare(legacy, vue) {
  return {
    dclPct: round(percentDiff(legacy.dclMs, vue.dclMs)),
    loadPct: round(percentDiff(legacy.loadMs, vue.loadMs)),
    fcpPct: round(percentDiff(legacy.fcpMs, vue.fcpMs)),
    lcpPct: round(percentDiff(legacy.lcpMs, vue.lcpMs)),
    resourcesCountPct: round(percentDiff(legacy.resourcesCount, vue.resourcesCount)),
    resourcesTransferPct: round(percentDiff(legacy.resourcesTransferKb, vue.resourcesTransferKb)),
    jsTransferPct: round(percentDiff(legacy.jsTransferKb, vue.jsTransferKb)),
    cssTransferPct: round(percentDiff(legacy.cssTransferKb, vue.cssTransferKb)),
    imgTransferPct: round(percentDiff(legacy.imgTransferKb, vue.imgTransferKb)),
    taskDurationPct: round(percentDiff(legacy.taskDurationMs, vue.taskDurationMs)),
    scriptDurationPct: round(percentDiff(legacy.scriptDurationMs, vue.scriptDurationMs)),
    layoutDurationPct: round(percentDiff(legacy.layoutDurationMs, vue.layoutDurationMs)),
    styleDurationPct: round(percentDiff(legacy.styleDurationMs, vue.styleDurationMs)),
    jsHeapUsedPct: round(percentDiff(legacy.jsHeapUsedMb, vue.jsHeapUsedMb)),
    domNodesPct: round(percentDiff(legacy.domNodes, vue.domNodes)),
  }
}

const legacySamples = []
for (let index = 0; index < runs; index += 1) {
  legacySamples.push(await runSingle('/legacy/messages', index))
}

const vueSamples = []
for (let index = 0; index < runs; index += 1) {
  vueSamples.push(await runSingle('/messages', runs + index))
}

const legacySummary = summarize('legacy', legacySamples)
const vueSummary = summarize('vue', vueSamples)
const comparison = compare(legacySummary, vueSummary)

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  runs,
  legacy: legacySummary,
  vue: vueSummary,
  comparison,
  raw: {
    legacy: legacySamples,
    vue: vueSamples,
  },
}

const serialized = JSON.stringify(report, null, 2)
if (outPath) {
  await fs.writeFile(outPath, serialized)
}
console.log(serialized)
