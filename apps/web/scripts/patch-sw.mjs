#!/usr/bin/env node
/**
 * Post-build service worker patcher.
 *
 * Injects a workbox `setCatchHandler` into the generated `public/sw.js`
 * so navigation requests that fail ALL runtime caching strategies (cache
 * miss + network fail) fall back to the precached /offline.html page
 * instead of throwing `no-response` and showing the browser's default
 * ERR_INTERNET_DISCONNECTED error.
 *
 * Why not use @ducanh2912/next-pwa's built-in `fallbacks` option?
 * That option makes next-pwa v10 inject an SWC-transpiled
 * `handlerDidError` plugin onto every route, referencing
 * `_async_to_generator` / `_ts_generator` runtime helpers that never get
 * bundled into the SW. Result: `ReferenceError: _async_to_generator is
 * not defined` at runtime (see regknots-v7 postmortem).
 *
 * This script side-steps the broken codegen entirely by writing the
 * catch handler in plain ES5 (no async/await, no arrow functions) and
 * splicing it in right before the end of the workbox define() callback.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const SW_PATH = path.resolve(__dirname, '..', 'public', 'sw.js')

if (!fs.existsSync(SW_PATH)) {
  // PWA likely disabled (e.g. `next dev`) — nothing to patch.
  console.log('[patch-sw] no sw.js at', SW_PATH, '— skipping')
  process.exit(0)
}

let sw = fs.readFileSync(SW_PATH, 'utf8')

if (sw.includes('setCatchHandler')) {
  console.log('[patch-sw] setCatchHandler already present — skipping')
  process.exit(0)
}

// Plain ES5 body — no async/await, no arrow functions. `e` is the
// workbox module imported via define() at the top of sw.js.
const CATCH_HANDLER =
  'e.setCatchHandler(function(o){' +
    'if(o.request&&o.request.mode==="navigate"){' +
      'return caches.match("/offline.html",{ignoreSearch:true}).then(function(r){' +
        'return r||Response.error()' +
      '})' +
    '}' +
    'return Response.error()' +
  '});'

// Splice right before the final __WB_DISABLE_DEV_LOGS assignment (the
// last statement inside the workbox define callback). This keeps us
// inside the closure where `e` is in scope.
const MARKER = 'self.__WB_DISABLE_DEV_LOGS'
if (!sw.includes(MARKER)) {
  console.error(
    '[patch-sw] injection marker not found — next-pwa output format may have changed.\n' +
    '           Looked for:', MARKER,
  )
  process.exit(1)
}

sw = sw.replace(MARKER, CATCH_HANDLER + MARKER)
fs.writeFileSync(SW_PATH, sw, 'utf8')
console.log('[patch-sw] injected setCatchHandler into', path.relative(process.cwd(), SW_PATH))
