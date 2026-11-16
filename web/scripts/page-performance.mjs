import { writeFileSync } from 'node:fs'
import { chromium } from 'playwright'

const routes = [
  { id: 'home', label: '终端首页', hash: '/home' },
  { id: 'overview', label: '市场总览', hash: '/overview', chart: true },
  { id: 'regimes', label: '状态分析', hash: '/regimes', chart: true },
  { id: 'evaluation', label: '评估报告', hash: '/evaluation' },
  { id: 'features', label: '特征分析', hash: '/features', chart: true },
  { id: 'alerts', label: '预警中心', hash: '/alerts' },
  { id: 'replay', label: '历史回放', hash: '/replay' },
  { id: 'data', label: '数据中心', hash: '/data' },
  { id: 'system', label: '系统监控', hash: '/system' },
]

function argumentsOf(argv) {
  const result = { rounds: 3, slowRounds: 1, timeout: 30000 }
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]
    const value = argv[index + 1]
    if (key === '--base-url') result.baseUrl = value
    else if (key === '--output') result.output = value
    else if (key === '--rounds') result.rounds = Number(value)
    else if (key === '--slow-rounds') result.slowRounds = Number(value)
    else if (key === '--timeout') result.timeout = Number(value)
    else throw new Error(`未知参数或缺少参数值: ${key}`)
  }
  if (!result.baseUrl || !result.output || !Number.isInteger(result.rounds) || result.rounds < 1 || !Number.isInteger(result.slowRounds) || result.slowRounds < 0 || !(result.timeout > 0)) {
    throw new Error('base-url、output、rounds、slow-rounds 和 timeout 参数无效')
  }
  return result
}

function thinkTimeMs(route) {
  if (route.id === 'system') return 12000
  if (route.id === 'data') return 5000
  return 1500
}

async function waitUntilUsable(page, route) {
  if (route.id === 'home') {
    await page.getByText('从一个更清晰的视角，观察市场。').waitFor()
    await page.getByRole('button', { name: /进入市场工作台/ }).waitFor()
  } else {
    await page.getByRole('heading', { name: route.label, exact: true }).first().waitFor()
  }
  if (route.chart) await page.locator('.chart canvas').first().waitFor()
  if (route.id === 'evaluation') {
    await page.getByRole('heading', { name: '实验概览' }).waitFor()
    await page.locator('.stability-run-table tbody tr').first().waitFor()
  } else if (route.id === 'features') {
    await page.getByRole('heading', { name: '特征历史走势' }).waitFor()
  } else if (route.id === 'alerts') {
    await page.getByRole('button', { name: '查看证据' }).first().waitFor()
  } else if (route.id === 'replay') {
    await page.getByLabel('回放开始日期').waitFor()
    await page.waitForFunction(() => {
      const button = [...document.querySelectorAll('button')].find(item => item.textContent?.includes('开始回放'))
      return Boolean(button && !button.disabled)
    })
  } else if (route.id === 'data') {
    await page.getByRole('heading', { name: '全部数据', exact: true }).waitFor()
    await page.getByText('来源质量与保留策略', { exact: true }).waitFor()
  } else if (route.id === 'system') {
    await page.getByRole('heading', { name: '系统运行监控' }).waitFor()
    await page.getByText('整体状态：', { exact: false }).waitFor()
    await page.locator('section.panel').filter({ hasText: 'Redis 热特征性能' }).locator('.method-note').first().waitFor()
    await page.locator('section.panel').filter({ hasText: '页面加载性能' }).locator('.method-note').first().waitFor()
  }
}

async function browserMetrics(page) {
  return page.evaluate(() => {
    const navigation = performance.getEntriesByType('navigation')[0]
    const resources = performance.getEntriesByType('resource')
    return {
      dom_content_loaded_ms: navigation ? Math.round(navigation.domContentLoadedEventEnd * 1000) / 1000 : null,
      load_event_ms: navigation ? Math.round(navigation.loadEventEnd * 1000) / 1000 : null,
      resource_count: resources.length,
      resource_transfer_bytes: resources.reduce((total, item) => total + (item.transferSize || 0), 0),
    }
  })
}

async function measure({ browser, baseUrl, storageState, route, mode, round, timeout }) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, storageState })
  const page = await context.newPage()
  page.setDefaultTimeout(timeout)
  const pageErrors = []
  const requestFailures = []
  const abortedRequests = []
  const httpErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    const expectedMissingReport = route.id === 'system' && response.status() === 404 && ['/api/system/api-performance', '/api/system/feature-cache-performance', '/api/system/page-performance'].includes(path)
    if (response.status() >= 400 && !expectedMissingReport) httpErrors.push(`${response.status()} ${response.request().method()} ${response.url()}`)
  })
  page.on('requestfailed', request => {
    const detail = `${request.method()} ${request.url()}: ${request.failure()?.errorText ?? 'failed'}`
    if (request.failure()?.errorText === 'net::ERR_ABORTED') abortedRequests.push(detail)
    else requestFailures.push(detail)
  })
  let cdp
  if (mode === 'slow_4g_reference') {
    cdp = await context.newCDPSession(page)
    await cdp.send('Network.enable')
    await cdp.send('Network.emulateNetworkConditions', {
      offline: false,
      latency: 150,
      downloadThroughput: 1.6 * 1024 * 1024 / 8,
      uploadThroughput: 768 * 1024 / 8,
    })
  }
  let started = performance.now()
  let success = false
  let error = null
  let navigation = null
  try {
    const url = `${baseUrl}/#${route.hash}`
    if (mode === 'hot_repeat_reload') {
      await new Promise(resolve => setTimeout(resolve, thinkTimeMs(route)))
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout })
      await waitUntilUsable(page, route)
      await new Promise(resolve => setTimeout(resolve, thinkTimeMs(route)))
      started = performance.now()
      await page.reload({ waitUntil: 'domcontentloaded', timeout })
    } else {
      await new Promise(resolve => setTimeout(resolve, thinkTimeMs(route)))
      started = performance.now()
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout })
    }
    await waitUntilUsable(page, route)
    navigation = await browserMetrics(page)
  } catch (reason) {
    error = reason instanceof Error ? reason.message.split('\n')[0] : String(reason)
  }
  const readyMs = Math.round((performance.now() - started) * 1000) / 1000
  if (cdp) await cdp.detach()
  await context.close()
  success = error === null && pageErrors.length === 0 && requestFailures.length === 0 && httpErrors.length === 0
  return {
    page: route.id,
    page_label: route.label,
    mode,
    round,
    success,
    ready_ms: readyMs,
    navigation,
    page_errors: pageErrors,
    request_failures: requestFailures,
    aborted_requests: abortedRequests,
    http_errors: httpErrors,
    think_time_ms_excluded: thinkTimeMs(route),
    error,
    warm_up_excluded: mode === 'hot_repeat_reload',
  }
}

const args = argumentsOf(process.argv.slice(2))
const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || (process.env.CI ? 'chromium' : 'chrome'), headless: true })
try {
  const setupContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const setupPage = await setupContext.newPage()
  setupPage.setDefaultTimeout(args.timeout)
  await setupPage.goto(args.baseUrl, { waitUntil: 'domcontentloaded', timeout: args.timeout })
  if (await setupPage.getByRole('heading', { name: '创建首位管理员' }).isVisible()) {
    await setupPage.getByLabel('初始化凭据').fill('e2e-only-setup-code')
    await setupPage.getByLabel('用户名', { exact: true }).fill('e2e-admin')
    await setupPage.getByLabel('密码', { exact: true }).fill('e2e-only-password-123')
    await setupPage.getByRole('button', { name: '创建并进入' }).click()
  }
  await setupPage.getByText('从一个更清晰的视角，观察市场。').waitFor({ timeout: args.timeout })
  const storageState = await setupContext.storageState()
  await setupContext.close()

  const samples = []
  for (const route of routes) {
    for (let round = 1; round <= args.rounds; round += 1) {
      samples.push(await measure({ browser, baseUrl: args.baseUrl, storageState, route, mode: 'cold_empty_context', round, timeout: args.timeout }))
    }
    for (let round = 1; round <= args.rounds; round += 1) {
      samples.push(await measure({ browser, baseUrl: args.baseUrl, storageState, route, mode: 'hot_repeat_reload', round, timeout: args.timeout }))
    }
    for (let round = 1; round <= args.slowRounds; round += 1) {
      samples.push(await measure({ browser, baseUrl: args.baseUrl, storageState, route, mode: 'slow_4g_reference', round, timeout: args.timeout }))
    }
  }
  const result = {
    schema: 'page-performance-browser-v1',
    browser: { name: browser.browserType().name(), version: browser.version(), channel: process.env.E2E_CHANNEL || (process.env.CI ? 'chromium' : 'chrome'), headless: true },
    viewport: { width: 1440, height: 1000 },
    node: process.version,
    routes: routes.map(({ id, label, hash, chart }) => ({ id, label, hash, chart_required: Boolean(chart) })),
    rounds: args.rounds,
    slow_rounds: args.slowRounds,
    setup: { authentication: 'temporary synthetic administrator', bootstrap_excluded: true },
    samples,
  }
  writeFileSync(args.output, JSON.stringify(result, null, 2), 'utf8')
  console.log(JSON.stringify({ output: args.output, browser: result.browser, samples: samples.length, successful: samples.filter(item => item.success).length }))
} finally {
  await browser.close()
}
