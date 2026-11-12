// Captures the screens shown in the README and on the site (media/screenshots), from a running studio.
//
//   cd web; node scripts/screenshots.mjs [baseUrl] [--only name,name]
//
// baseUrl defaults to https://localhost:4400 (python -m studio dev). The shots use your own projects:
// change the ids in SHOTS. The interface is forced to English for the capture, without touching your setting.
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const args = process.argv.slice(2)
const base = (args.find((a) => !a.startsWith('--')) ?? 'https://localhost:4400').replace(/\/$/, '')
const onlyArg = args.indexOf('--only')
const only = onlyArg >= 0 ? args[onlyArg + 1].split(',') : null
const out = fileURLToPath(new URL('../../media/screenshots/', import.meta.url))

/** [file name, path, extra wait in ms] */
const SHOTS = [
  ['projects', '/'],
  ['overview', '/p/509402e9a5'],
  ['angle', '/p/f728f85ffb/angle'],
  ['titles', '/p/f728f85ffb/titre'],
  ['thumbnail', '/p/fa848779b9/vignette'],
  ['script', '/p/509402e9a5/script'],
  ['derush', '/p/509402e9a5/derush'],
  ['storyboard', '/p/619afee567/storyboard', 1500],
  ['editing', '/p/509402e9a5/montage', 2500],
  ['details', '/p/f728f85ffb/description'],
]

await mkdir(out, { recursive: true })
const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  ignoreHTTPSErrors: true,
  locale: 'en-US',
})
await context.addInitScript(() => localStorage.setItem('studio.locale', 'en'))
const page = await context.newPage()

for (const [name, path, wait = 0] of SHOTS) {
  if (only && !only.includes(name)) continue
  await page.goto(base + path, { waitUntil: 'networkidle' })
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(800 + wait)
  await page.screenshot({ path: `${out}${name}.png` })
  console.log(`${name}.png  ${path}`)
}

await browser.close()
