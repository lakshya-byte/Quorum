// Key-flow smoke script (written the way a spec agent would): add a note, find it, search it away.
// Contract: module.exports = async (page, baseUrl) => { ...throw on failure... }
module.exports = async function smoke(page, baseUrl) {
  await page.goto(baseUrl, { waitUntil: 'networkidle' })
  await page.waitForSelector('text=Groceries', { timeout: 5000 })

  await page.fill('input[placeholder="Note title"]', 'Smoke note')
  await page.fill('textarea[placeholder="Write something..."]', 'written by the smoke script')
  await page.click('text=Add note')
  await page.waitForSelector('text=Smoke note', { timeout: 5000 })
  const footer = await page.textContent('text=/\\d+ notes/')
  if (!/4 notes/.test(footer)) throw new Error('expected "4 notes" in the footer, saw: ' + footer)

  await page.fill('input[placeholder="Search notes"]', 'zzzz-no-match')
  await page.waitForSelector('text=No notes yet', { timeout: 5000 })
  if (await page.locator('text=Smoke note').count()) throw new Error('search did not filter the list')
}
