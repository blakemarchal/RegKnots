// Tailwind 4 guard. From apps/web: `pnpm test`.
//
// Tailwind 4 reads `bg-[--color-teal]` as a literal value, so the class
// compiles to `background-color: --color-teal`, which browsers drop. In
// September 2026, 246 such classes left the register, sign-in, onboarding and
// invite buttons without their fill. Use the theme utility (`bg-teal`,
// `text-off-white`, `border-teal/30`) or v4's `bg-(--color-teal)` instead.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = fileURLToPath(new URL('..', import.meta.url))
const BROKEN = /-\[--[a-zA-Z0-9-]+\]/g

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) yield* files(path)
    else if (/\.(tsx?|css)$/.test(name)) yield path
  }
}

test('no Tailwind class wraps a CSS variable in square brackets', () => {
  const hits = []
  for (const path of files(SRC)) {
    for (const m of readFileSync(path, 'utf8').matchAll(BROKEN)) {
      hits.push(`${relative(SRC, path)}: ${m[0]}`)
    }
  }
  assert.deepEqual(hits, [], `use the theme utility or (--var) syntax:\n${hits.slice(0, 20).join('\n')}`)
})
