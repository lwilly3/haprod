// Serves the website for local work, without building it: site/public as is, the screenshots and the logo
// from their place in the repository (the same mapping as build.mjs). Edit a file, reload the page.
// No dependencies: `node site/serve.mjs [port]`, then open http://localhost:4477.
import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, join, normalize, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = (path) => fileURLToPath(new URL(`../${path}`, import.meta.url))
const port = Number(process.argv[2] ?? process.env.PORT ?? 4477)

/** URL prefix → folder or file, the first match wins */
const MOUNTS = [
  ['/screenshots/', root('media/screenshots/')],
  ['/favicon.svg', root('web/public/favicon.svg')],
  ['/', root('site/public/')],
]

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8',
}

function resolve(pathname) {
  for (const [prefix, target] of MOUNTS) {
    if (pathname === prefix) return target.endsWith(sep) ? join(target, 'index.html') : target
    if (prefix.endsWith('/') && pathname.startsWith(prefix)) {
      const file = normalize(join(target, pathname.slice(prefix.length)))
      return file.startsWith(target) ? file : null // no way out of the mount
    }
  }
  return null
}

createServer(async (req, res) => {
  const { pathname } = new URL(req.url, 'http://localhost')
  let file = resolve(decodeURIComponent(pathname))
  try {
    if (file && (await stat(file)).isDirectory()) file = join(file, 'index.html')
    if (!file || !(await stat(file)).isFile()) throw new Error('not found')
  } catch {
    res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' }).end('Not found')
    return
  }
  res.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream', 'cache-control': 'no-store' })
  createReadStream(file).pipe(res)
}).listen(port, () => console.log(`Site on http://localhost:${port}`))
