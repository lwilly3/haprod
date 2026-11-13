// Builds the website into site/dist: the static files of site/public, plus the share image (media/screenshots)
// and the logo, taken from the repository so they have a single source.
// No dependencies: `node site/build.mjs`, then open site/dist/index.html or serve the folder.
import { cpSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const root = (path) => fileURLToPath(new URL(`../${path}`, import.meta.url))
const dist = root('site/dist')

rmSync(dist, { recursive: true, force: true })
cpSync(root('site/public'), dist, { recursive: true })
cpSync(root('media/screenshots'), `${dist}/screenshots`, { recursive: true })
cpSync(root('web/public/favicon.svg'), `${dist}/favicon.svg`)

console.log(`Site built in ${dist}`)
