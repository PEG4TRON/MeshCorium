#!/usr/bin/env node

import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import { spawn } from 'node:child_process'

const argv = process.argv.slice(2)

function takeArg(name, fallback = '') {
  const index = argv.indexOf(name)
  if (index === -1 || index === argv.length - 1) {
    return fallback
  }
  return String(argv[index + 1] || '')
}

function takeArgs(name) {
  const result = []
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === name && index < argv.length - 1) {
      result.push(String(argv[index + 1] || ''))
    }
  }
  return result
}

function hasFlag(name) {
  return argv.includes(name)
}

const targetUrl = takeArg('--url', 'http://127.0.0.1:8080/')
const screenshotPath = takeArg('--screenshot', path.join(process.cwd(), 'screenshot.png'))
const username = takeArg('--username', '')
const password = takeArg('--password', '')
const width = Math.max(320, Number.parseInt(takeArg('--width', '1920'), 10) || 1920)
const height = Math.max(320, Number.parseInt(takeArg('--height', '1080'), 10) || 1080)
const debugPort = Math.max(1024, Number.parseInt(takeArg('--debug-port', '9222'), 10) || 9222)
const waitMs = Math.max(0, Number.parseInt(takeArg('--wait-ms', '1200'), 10) || 1200)
const postEvalWaitMs = Math.max(0, Number.parseInt(takeArg('--post-eval-wait-ms', '700'), 10) || 700)
const ensureConnected = hasFlag('--ensure-connected')
const evalScripts = takeArgs('--eval')

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
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
  const response = await fetch('http://127.0.0.1:8080/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(String(data && data.error || 'Login failed'))
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

  once(method, timeoutMs = 10000) {
    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        const waiters = this.eventWaiters.get(method) || []
        this.eventWaiters.set(
          method,
          waiters.filter((entry) => entry !== wrappedResolve),
        )
        reject(new Error(`Timed out waiting for event ${method}`))
      }, timeoutMs)

      const wrappedResolve = (params) => {
        clearTimeout(timeoutId)
        resolve(params)
      }
      const waiters = this.eventWaiters.get(method) || []
      waiters.push(wrappedResolve)
      this.eventWaiters.set(method, waiters)
    })
  }

  async evaluate(expression, options = {}) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: options.awaitPromise !== false,
      returnByValue: options.returnByValue !== false,
    })
    if (result.exceptionDetails) {
      const description = result.exceptionDetails.text || result.result?.description || 'Runtime evaluation failed'
      throw new Error(description)
    }
    return result.result?.value
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

async function waitForCondition(cdp, expression, timeoutMs = 15000, intervalMs = 200) {
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
  const loadEvent = cdp.once('Page.loadEventFired', 15000).catch(() => null)
  await cdp.send('Page.navigate', { url })
  await loadEvent
  await waitForCondition(cdp, 'document.readyState === "complete"', 15000)
}

async function loginIfNeeded(cdp) {
  const pathname = await cdp.evaluate('location.pathname')
  if (pathname !== '/login') {
    return
  }
  if (!username || !password) {
    throw new Error('Login page detected but --username/--password not provided')
  }
  const escapedUsername = JSON.stringify(username)
  const escapedPassword = JSON.stringify(password)
  await cdp.evaluate(`
    (async () => {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: ${escapedUsername},
          password: ${escapedPassword}
        })
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(String(data && data.error || 'Login failed'))
      }
      const next = String(data && data.next || '/')
      window.location.href = next
      return next
    })()
  `)
  await waitForCondition(cdp, 'location.pathname !== "/login"', 15000)
  await sleep(700)
}

async function primeAuthCookie(cdp) {
  if (!username || !password) {
    return
  }
  const cookieValue = await requestAuthCookie()
  await cdp.send('Network.setCookie', {
    name: 'meshcorium_auth',
    value: cookieValue,
    domain: '127.0.0.1',
    path: '/',
    httpOnly: true,
    sameSite: 'Lax',
  })
}

async function ensureConnectedToRadio(cdp) {
  const currentPath = await cdp.evaluate('location.pathname')
  if (currentPath === '/messages') {
    const disconnectedText = await cdp.evaluate(`
      (() => {
        const empty = document.querySelector('.empty-chat-title, .status-note, .workspace-empty-title')
        return empty ? String(empty.textContent || '') : ''
      })()
    `).catch(() => '')
    if (!/Подключ/i.test(disconnectedText || '')) {
      return
    }
  }

  await navigate(cdp, targetUrl)
  await loginIfNeeded(cdp)
  await waitForCondition(
    cdp,
    'Boolean(document.body && (document.body.innerText || "").includes("Подключиться")) || location.pathname === "/messages"',
    20000,
  )

  const connectResult = await cdp.evaluate(`
    (async () => {
      const portsResponse = await fetch('/api/ports', { credentials: 'same-origin' })
      const portsData = await portsResponse.json()
      const ports = Array.isArray(portsData.ports) ? portsData.ports : []
      if (!ports.length) {
        throw new Error('No ports available')
      }
      const firstPort = ports[0]
      const port = typeof firstPort === 'object' && firstPort !== null
        ? String(firstPort.device || '')
        : String(firstPort || '')
      if (!port) {
        throw new Error('Port device missing')
      }
      const response = await fetch('/api/connect', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          port,
          baudrate: 115200,
          timeout: 4.0,
          notifications_enabled: true
        })
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(String(data && data.error || 'Connect failed'))
      }
      return { port, next: '/messages' }
    })()
  `)
  if (!connectResult || !connectResult.next) {
    throw new Error('Connect flow did not return next route')
  }
  await navigate(cdp, `http://127.0.0.1:8080${connectResult.next}`)
  await waitForCondition(
    cdp,
    'location.pathname === "/messages" && document.readyState === "complete"',
    20000,
  )
  await sleep(1500)
}

async function main() {
  const profileDir = await fs.mkdtemp(path.join(os.tmpdir(), 'meshcorium-chromium-'))
  const chromium = spawn(
    'chromium',
    [
      '--headless',
      '--no-sandbox',
      '--disable-gpu',
      '--hide-scrollbars',
      '--disable-dev-shm-usage',
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profileDir}`,
      `--window-size=${width},${height}`,
      'about:blank',
    ],
    {
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  )

  let chromiumLogs = ''
  chromium.stdout.on('data', (chunk) => {
    chromiumLogs += String(chunk || '')
  })
  chromium.stderr.on('data', (chunk) => {
    chromiumLogs += String(chunk || '')
  })

  try {
    const targets = await waitForDebugger(debugPort, 15000)
    const pageTarget = targets.find((target) => target.type === 'page' && target.webSocketDebuggerUrl)
    if (!pageTarget) {
      throw new Error('No page target found in Chromium DevTools')
    }

    const cdp = new CdpClient(pageTarget.webSocketDebuggerUrl)
    await cdp.connect()
    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    await cdp.send('Network.enable')
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
    })

    await primeAuthCookie(cdp)
    await navigate(cdp, targetUrl)
    await loginIfNeeded(cdp)
    if (ensureConnected) {
      await ensureConnectedToRadio(cdp)
    }
    await sleep(waitMs)

    for (const expression of evalScripts) {
      await cdp.evaluate(expression, { awaitPromise: true, returnByValue: true })
      await sleep(postEvalWaitMs)
    }

    const screenshot = await cdp.send('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true,
    })
    const buffer = Buffer.from(String(screenshot.data || ''), 'base64')
    await fs.mkdir(path.dirname(screenshotPath), { recursive: true })
    await fs.writeFile(screenshotPath, buffer)
    process.stdout.write(`${screenshotPath}\n`)
  } finally {
    chromium.kill('SIGTERM')
    await sleep(300)
    await fs.rm(profileDir, { recursive: true, force: true }).catch(() => {})
  }
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error))
  process.exitCode = 1
})
