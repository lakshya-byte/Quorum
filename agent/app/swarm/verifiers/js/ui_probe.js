// Headless UI probe used by the ui_* verifiers. Input: path to a JSON config. Output: result.json in cfg.outDir.
// Trusted harness code: it loads a page served from 127.0.0.1 and aborts every other network request.
const fs = require('fs')
const path = require('path')
const { chromium } = require('playwright')

async function newContext(browser, width, result) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 } })
  await ctx.route('**/*', (route) => {
    const u = route.request().url()
    if (u.startsWith('http://127.0.0.1') || u.startsWith('data:') || u.startsWith('blob:') || u === 'about:blank') return route.continue()
    result.blocked_requests.push(u.slice(0, 120))
    return route.abort('blockedbyclient')
  })
  return ctx
}

function wire(page, result) {
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    const t = m.text()
    if (/ERR_BLOCKED_BY_CLIENT|favicon/i.test(t)) return
    result.console_errors.push(t.slice(0, 300))
  })
  page.on('pageerror', (e) => result.page_errors.push(String(e && e.message ? e.message : e).slice(0, 300)))
}

;(async () => {
  const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
  const result = { ok: true, console_errors: [], page_errors: [], blocked_requests: [], viewports: {}, axe: null, smoke: null, error: null }
  let browser
  try {
    browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })
    if (cfg.mode !== 'smoke') {
      const ctx = await newContext(browser, 1280, result)
      const page = await ctx.newPage()
      wire(page, result)
      await page.goto(cfg.url, { waitUntil: 'networkidle', timeout: 25000 })
      for (const vp of cfg.viewports || [375, 768, 1280]) {
        await page.setViewportSize({ width: vp, height: 800 })
        await page.waitForTimeout(150)
        const m = await page.evaluate(() => {
          const de = document.documentElement
          const sw = Math.max(de.scrollWidth, document.body ? document.body.scrollWidth : 0)
          const cw = de.clientWidth
          const bad = Array.from(document.querySelectorAll('body *'))
            .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.right > cw + 1 })
            .slice(0, 5)
            .map((el) => el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className ? '.' + el.className.split(' ')[0] : ''))
          return { scrollWidth: sw, clientWidth: cw, overflow: sw > cw + 1, overflowPx: Math.max(0, sw - cw), offenders: bad }
        })
        const shot = path.join(cfg.outDir, `shot-${vp}.png`)
        await page.screenshot({ path: shot, fullPage: true })
        m.screenshot = path.basename(shot)
        result.viewports[String(vp)] = m
      }
      if (cfg.axePath && fs.existsSync(cfg.axePath)) {
        await page.setViewportSize({ width: 1280, height: 800 })
        await page.addScriptTag({ path: cfg.axePath })
        const axe = await page.evaluate(async () => {
          const r = await window.axe.run(document)
          return r.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help.slice(0, 120) }))
        })
        result.axe = { violations: axe, rules: axe.length, nodes: axe.reduce((a, v) => a + v.nodes, 0) }
      }
      await ctx.close()
    }
    if (cfg.smoke) {
      const ctx = await newContext(browser, 1280, result)
      const page = await ctx.newPage()
      wire(page, result)
      try {
        const fn = require(path.resolve(cfg.smoke))
        await Promise.race([
          fn(page, cfg.url),
          new Promise((_, rej) => setTimeout(() => rej(new Error('smoke script timed out after 30s')), 30000)),
        ])
        result.smoke = { ok: true }
      } catch (e) {
        result.smoke = { ok: false, error: String(e && e.message ? e.message : e).slice(0, 400) }
      }
      await ctx.close()
    }
  } catch (e) {
    result.ok = false
    result.error = String(e && e.message ? e.message : e).slice(0, 500)
  } finally {
    if (browser) await browser.close().catch(() => {})
  }
  fs.writeFileSync(path.join(cfg.outDir, 'result.json'), JSON.stringify(result))
  process.exit(0)
})()
