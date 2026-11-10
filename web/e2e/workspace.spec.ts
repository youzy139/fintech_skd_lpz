import { expect, test } from '@playwright/test'

test('管理员可以复核市场证据并完成真实两日回放', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('初始化凭据').fill('e2e-only-setup-code')
  await page.getByLabel('用户名', { exact: true }).fill('e2e-admin')
  await page.getByLabel('密码', { exact: true }).fill('e2e-only-password-123')
  const timings: Record<string, number> = {}
  const landingStarted = Date.now()
  await page.getByRole('button', { name: '创建并进入' }).click()
  await expect(page.getByText('从一个更清晰的视角，观察市场。')).toBeVisible()
  timings.landing_after_bootstrap_ms = Date.now() - landingStarted
  const workspaceStarted = Date.now()
  await page.getByRole('button', { name: /进入市场工作台/ }).click()
  await expect(page.getByRole('heading', { name: '市场总览' })).toBeVisible()
  timings.workspace_overview_ms = Date.now() - workspaceStarted

  await page.getByRole('button', { name: /状态分析/ }).click()
  await expect(page.getByText('状态特征热力图')).toBeVisible()
  await expect(page.locator('.chart canvas').first()).toBeVisible()

  await page.getByRole('button', { name: /预警中心/ }).click()
  await page.getByRole('button', { name: '查看证据' }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByText('训练数据截至')).toBeVisible()
  await expect(page.getByText(/截至前一状态日的公开背景/)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await page.getByRole('button', { name: '系统监控' }).click()
  await expect(page.getByRole('heading', { name: '系统运行监控' })).toBeVisible()
  await expect(page.getByText('进程内一级缓存')).toHaveCount(0)
  await page.getByRole('button', { name: '审计记录' }).click()
  await expect(page.getByRole('heading', { name: '审计记录' })).toBeVisible()
  await expect(page.getByText('保留与对象归档')).toBeVisible()
  await expect(page.getByRole('cell', { name: '管理员初始化' })).toBeVisible()
  await page.getByRole('button', { name: '返回平台' }).click()
  await page.getByRole('button', { name: /进入市场工作台/ }).click()
  await expect(page.getByRole('heading', { name: '市场总览' })).toBeVisible()

  await page.getByRole('button', { name: /历史回放/ }).click()
  const assets = await page.request.get('/api/assets')
  const code = (await assets.json())[0].code
  const series = await page.request.get(`/api/assets/${code}/series?limit=2`)
  const points = (await series.json()).points
  await page.getByLabel('回放开始日期').fill(points[0].date)
  await page.getByLabel('回放结束日期').fill(points[1].date)
  await page.getByLabel('回放速度').selectOption('10')
  await page.getByRole('button', { name: '开始回放' }).click()
  await expect(page.getByText('已完成', { exact: true })).toBeVisible({ timeout: 120_000 })
  await expect(page.getByText('2 / 2 个交易日')).toBeVisible()
  await expect(page.getByText('结果推送已连接')).toBeVisible()
  await test.info().attach('page-timings', { body: JSON.stringify(timings), contentType: 'application/json' })
  console.log('E2E_PERFORMANCE ' + JSON.stringify(timings))
})
