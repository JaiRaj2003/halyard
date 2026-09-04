import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const API = 'http://127.0.0.1:8000'

/** Internal enum spellings that must never reach the screen. */
const ENUMS = /\b(NEEDS_ENTITY_REVIEW|NEEDS_TRIAGE|PATH_REVIEW|NO_OBSERVABLE_PATH|AWAITING_CONNECTOR|historically_observable|snapshot_only|post_dates_request|fallback_requester|ingest_operationalization|unverified_suggested_route)\b/

async function expectNoEnums(page: Page) {
  const text = await page.locator('main').innerText()
  expect(text).not.toMatch(ENUMS)
}

async function expectNoHorizontalOverflow(page: Page) {
  const [scroll, client] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
  expect(scroll).toBeLessThanOrEqual(client)
}

/** An account whose contacts carry titles in at least two families, so the
 *  coverage strip has something to say. */
async function accountWithTitles(request: APIRequestContext): Promise<number> {
  const queue = await (await request.get(`${API}/api/queue?view=all&limit=200`)).json()
  const seen = new Set<number>()
  for (const item of queue.items) {
    if (!item.account_id || seen.has(item.account_id)) continue
    seen.add(item.account_id)
    const view = await (await request.get(`${API}/api/accounts/${item.account_id}/view`)).json()
    const families = new Set(view.known_people.map((person: { title_family: string | null }) => person.title_family).filter(Boolean))
    if (families.size >= 2 && view.coverage.connector_count > 0) return item.account_id
  }
  throw new Error('no account has titled contacts and connectors')
}

async function requestWithPaths(request: APIRequestContext): Promise<string> {
  const queue = await (await request.get(`${API}/api/queue?view=path_review&limit=200`)).json()
  for (const item of queue.items) {
    const paths = await (await request.get(`${API}/api/requests/${item.request_id}/paths`)).json()
    if (paths.paths.length > 1 && paths.paths.every((path: { review_status?: string }) => path.review_status !== 'selected')) {
      return item.request_id
    }
  }
  throw new Error('no request with multiple unreviewed paths in path review')
}

test('a new ask is saved and owned before anything is routed', async ({ page, request }) => {
  await page.goto('/')
  await page.getByLabel('Introduction request').fill('Can someone introduce us to the VP of Security at Apex Logistics?')
  await page.getByLabel('Requested by').fill('Playwright Operator')
  await page.getByRole('button', { name: 'Save & analyze' }).click()

  await expect(page).toHaveURL(/\/requests\/[A-Za-z0-9-]+\?saved=1$/)
  const requestId = new URL(page.url()).pathname.split('/').pop()!
  await expect(page.getByText(`Request saved as ${requestId}`)).toBeVisible()
  await expect(page.getByText('Owner assigned:')).toBeVisible()
  await expect(page.getByText('Next action:')).toBeVisible()

  const detail = await (await request.get(`${API}/api/requests/${requestId}`)).json()
  expect(detail.origin).toBe('live_intake')
  expect(detail.operational_owner).toBeTruthy()
  expect(detail.next_action).toBeTruthy()
  expect(detail.next_action_due_at).toBeTruthy()
  expect(detail.raw_ask).toBe('Can someone introduce us to the VP of Security at Apex Logistics?')

  await expect(page.getByRole('heading', { level: 1 })).toContainText(/VP of Security|Security/i)
  await expect(page.getByText('Live request').first()).toBeVisible()
  await expectNoEnums(page)
  await expectNoHorizontalOverflow(page)
})

test('an ask for an unknown company still persists, owned, and says the target is unresolved', async ({ page, request }) => {
  await page.goto('/')
  await page.getByLabel('Introduction request').fill('Intro to the CFO at Zorblax Quantum Widgets please')
  await page.getByLabel('Requested by').fill('Playwright Operator')
  await page.getByRole('button', { name: 'Save & analyze' }).click()

  await expect(page).toHaveURL(/\/requests\//)
  const requestId = new URL(page.url()).pathname.split('/').pop()!
  const detail = await (await request.get(`${API}/api/requests/${requestId}`)).json()
  expect(detail.operational_owner).toBeTruthy()
  expect(['NEEDS_ENTITY_REVIEW', 'NO_OBSERVABLE_PATH', 'NEEDS_TRIAGE']).toContain(detail.workflow_state)

  await expect(page.getByText('Why this needs attention')).toBeVisible()
  await expect(page.getByText(/not yet identified|ambiguous|No corroborated route/).first()).toBeVisible()
  await expect(page.locator('main')).not.toContainText(/guaranteed|intro probability|relationship strength/i)
  await expectNoEnums(page)
})

test('selecting a route keeps it on top and stops recommending another', async ({ page, request }) => {
  const requestId = await requestWithPaths(request)
  await page.goto(`/requests/${requestId}`)

  const routes = page.locator('#routes')
  await expect(routes.getByText('Recommended to investigate first')).toHaveCount(1)
  const cards = routes.locator('ul > li').filter({ has: page.getByRole('button', { name: 'Select for validation' }) })
  const secondConnector = await cards.nth(1).locator('span.font-semibold').first().innerText()

  await cards.nth(1).getByRole('button', { name: 'Select for validation' }).click()

  await expect(routes.getByText('Selected for validation')).toHaveCount(1)
  await expect(routes.getByText('Recommended to investigate first')).toHaveCount(0)
  await expect(routes.locator('ul > li').first()).toContainText(secondConnector)
  await expect(page.getByText(/Ask .* to confirm whether they can reach/).first()).toBeVisible()

  await page.reload()
  await expect(page.locator('#routes').locator('ul > li').first()).toContainText('Selected for validation')
  await expect(page.locator('main')).toContainText('Waiting on connector')
  await expectNoEnums(page)
})

test('the queue opens on needs attention, searches, and filters cohorts', async ({ page }) => {
  await page.goto('/queue')
  await expect(page).toHaveURL(/view=needs_attention|\/queue$/)
  await expect(page.getByRole('navigation', { name: 'Queue views' }).getByText('Needs attention')).toBeVisible()
  const rows = page.locator('tbody tr')
  await expect(rows.first()).toBeVisible()
  expect(await rows.count()).toBeGreaterThanOrEqual(6)

  await page.getByPlaceholder('Account, person, role, requester, owner or ID').fill('Gravenhurst')
  await expect(page).toHaveURL(/q=Gravenhurst/)
  await expect(page.getByText(/matching “Gravenhurst”/)).toBeVisible()
  await expect(rows.first()).toContainText('Gravenhurst')

  await page.getByRole('button', { name: /^Current workflow/ }).click()
  await expect(page).toHaveURL(/cohort=live/)
  await expect(page.getByText(/in current workflow/)).toBeVisible()

  await page.getByRole('button', { name: /^Imported backlog/ }).click()
  await expect(page.locator('main')).not.toContainText(/\bOverdue\b/)
  await expect(page.getByText('Legacy review target').first()).toBeVisible()
  await expectNoEnums(page)
  await expectNoHorizontalOverflow(page)
})

test('leadership separates imported backlog from current health and drills into the queue', async ({ page, request }) => {
  await page.goto('/leadership')
  await expect(page.getByRole('heading', { name: 'Current operational health' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /Imported backlog · context, not current SLA failure/ })).toBeVisible()
  await expect(page.locator('main')).not.toContainText(/SLA breached|missed follow-up/i)
  await expect(page.locator('main')).not.toContainText(/\b\d+ \/ \d+\b/)
  await expect(page.getByText('Connector goodwill in use')).toBeVisible()
  await expect(page.getByText(/active asks? · stated capacity/).first()).toBeVisible()

  const leadership = await (await request.get(`${API}/api/metrics/leadership`)).json()
  const backlog = leadership.metrics.find((metric: { key: string }) => metric.key === 'legacy_backlog')
  await page.getByRole('link', { name: /Imported backlog awaiting review/ }).click()
  await expect(page).toHaveURL(/view=legacy_backlog/)
  await expect(page.getByText(new RegExp(`${backlog.value} imported backlog`, 'i')).first()).toBeVisible()
  await expectNoEnums(page)
})

test('the account page compresses access into per-function coverage', async ({ page, request }) => {
  const accountId = await accountWithTitles(request)
  await page.goto(`/accounts/${accountId}`)

  const coverage = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Access coverage by function' }) })
  await expect(coverage).toBeVisible()
  for (const family of ['Executive leadership', 'Finance', 'Security', 'Engineering & technology']) {
    await expect(coverage.getByText(family, { exact: true })).toBeVisible()
  }
  await expect(coverage).toContainText(/Several observable routes|One route worth investigating/)
  await expect(coverage).toContainText(/Observable routes into \d+ of \d+ functions/)
  await expect(coverage).toContainText('not an introduction that is available')
  await expect(page.locator('main')).not.toContainText(/relationship strength|intro probability|guaranteed/i)
  await expectNoEnums(page)
  await expectNoHorizontalOverflow(page)
})
