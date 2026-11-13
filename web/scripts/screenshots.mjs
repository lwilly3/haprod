// Captures the images of the README and the site's share image (media/screenshots) from the website's mockups:
// the app's screens redrawn in code on a made-up project, so no real project shows up anywhere.
//
//   cd web; node scripts/screenshots.mjs [--only name,name]
//
// No server needed: the site is opened from site/public. The mockups are captured finished (reduced motion).
import { mkdir } from 'node:fs/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { chromium } from 'playwright'

const args = process.argv.slice(2)
const onlyArg = args.indexOf('--only')
const only = onlyArg >= 0 ? args[onlyArg + 1].split(',') : null
const site = pathToFileURL(fileURLToPath(new URL('../../site/public/index.html', import.meta.url))).href
const out = fileURLToPath(new URL('../../media/screenshots/', import.meta.url))

/** [file name, tab of the tour, viewport]: the README shows the first two, `og` is the share image */
const SHOTS = [
  ['editing', 'editing', { width: 1600, height: 1000 }],
  ['storyboard', 'storyboard', { width: 1600, height: 1000 }],
  ['og', 'editing', { width: 1200, height: 630 }],
]

await mkdir(out, { recursive: true })
const browser = await chromium.launch()

for (const [name, tab, viewport] of SHOTS) {
  if (only && !only.includes(name)) continue
  const page = await browser.newPage({ viewport, deviceScaleFactor: name === 'og' ? 1 : 2, reducedMotion: 'reduce' })
  await page.goto(site)
  await page.click(`#tab-${tab}`)
  // the mockup alone, over the whole viewport
  await page.addStyleTag({
    content: `#shot-${tab} { position: fixed; inset: 0; z-index: 100; aspect-ratio: auto; border-radius: 0; box-shadow: none; }`
      // the share image is wider than the frame: no room left for the chat's input
      + (name === 'og' ? '.m-input { display: none; }' : ''),
  })
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: `${out}${name}.png` })
  console.log(`${name}.png  #tab-${tab}`)
  await page.close()
}

await browser.close()
