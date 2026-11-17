// Moves the interface words out of the screens and into src/locales/en.json.
//
//   node tools/i18n_extract.mjs            report what would change
//   node tools/i18n_extract.mjs --apply    rewrite the screens and merge the new words into en.json
//
// What it moves: plain text between tags, and these attributes when they are plain strings: title, aria-label, placeholder, alt, label, tip,
// help, note, action, kept, ok, cancel, body, removeLabel; and the plain-string first argument of say(), the plain-string title/body/kept/ok/cancel
// of confirm(). Anything built from variables (template strings, `{n} changes`) is left alone and counted in the report.
// The English shown in the app does not change: every replacement is `t('key')` and en.json holds the exact text.
// Safe to run again after new screens are merged: words that already use t() are skipped, and a text that is already in en.json reuses its key.
import fs from 'node:fs'
import path from 'node:path'
import { makeKeyer } from './i18n_keys.mjs'
import { fileURLToPath } from 'node:url'
import { parse } from '@babel/parser'

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src')
const EN = path.join(SRC, 'locales', 'en.json')
const APPLY = process.argv.includes('--apply')
const ATTRS = new Set(['title', 'aria-label', 'placeholder', 'alt', 'label', 'tip', 'help', 'note', 'action', 'kept', 'ok', 'cancel', 'body', 'removeLabel'])
const CALL_PROPS = new Set(['title', 'body', 'kept', 'ok', 'cancel'])
const SKIP_PARENTS = new Set(['kbd', 'code', 'pre', 'style', 'script', 'title'])
const SKIP_FILES = new Set(['i18n.js', 'uiprefs.js', 'uistore.js'])
const PROP_KEYS = new Set(['label', 'title', 'text', 'hint', 'tip', 'summary', 'term', 'def'])

const en = JSON.parse(fs.readFileSync(EN, 'utf8'))
const keyFor = makeKeyer(en)

const hasWords = s => /[A-Za-zÀ-ɏ]{2,}/.test(s) || /^[A-Za-z]$/.test(s.trim())

// React's rule for the text between tags: lines are trimmed, blank lines dropped, the rest joined with one space
function cleanJsxText(raw) {
  const lines = raw.split(/\r\n|\n|\r/)
  let last = 0
  lines.forEach((l, i) => { if (/[^ \t]/.test(l)) last = i })
  let s = ''
  lines.forEach((line, i) => {
    let t = line.replace(/\t/g, ' ')
    if (i !== 0) t = t.replace(/^[ ]+/, '')
    if (i !== lines.length - 1) t = t.replace(/[ ]+$/, '')
    if (t) { if (i !== last) t += ' '; s += t }
  })
  return s
}

function children(node) {
  const out = []
  for (const k of Object.keys(node)) {
    if (k === 'loc' || k === 'start' || k === 'end' || k === 'extra' || k === 'leadingComments' || k === 'trailingComments' || k === 'innerComments') continue
    const v = node[k]
    if (Array.isArray(v)) v.forEach(x => x && typeof x.type === 'string' && out.push([x, k]))
    else if (v && typeof v.type === 'string') out.push([v, k])
  }
  return out
}
function walk(node, parent, key, fn) { fn(node, parent, key); for (const [c, k] of children(node)) walk(c, node, k, fn) }

const stats = { files: 0, replaced: 0, left: 0 }
function processFile(file) {
  const rel = path.relative(SRC, file).replace(/\\/g, '/')
  const code = fs.readFileSync(file, 'utf8')
  let ast
  try { ast = parse(code, { sourceType: 'module', plugins: ['jsx'] }) } catch (e) { console.log('SKIP (parse)', rel, e.message); return }
  // does the file already use a name `t`? then the import is called `tr`
  let tUsed = false
  walk(ast.program, null, null, (n, p, k) => {
    if (n.type === 'Identifier' && n.name === 't') {
      if (p && p.type === 'MemberExpression' && k === 'property' && !p.computed) return
      if (p && (p.type === 'ObjectProperty' || p.type === 'ObjectMethod') && k === 'key' && !p.computed && !p.shorthand) return
      if (p && p.type === 'JSXAttribute') return
      tUsed = true
    }
  })
  const fn = tUsed ? 'tr' : 't'
  const edits = []
  let leftHere = 0
  const call = text => `${fn}('${keyFor(text)}')`
  walk(ast.program, null, null, (n, p, k) => {
    if (n.type === 'JSXText') {
      if (p.type === 'JSXElement' && p.openingElement.name.type === 'JSXIdentifier' && SKIP_PARENTS.has(p.openingElement.name.name)) return
      const s = cleanJsxText(n.value)
      if (!s || !hasWords(s)) return
      const lead = /^ /.test(s), trail = / $/.test(s)
      const core = s.trim()
      if (!core) return
      edits.push({ start: n.start, end: n.end, text: (lead ? "{' '}" : '') + `{${call(core)}}` + (trail ? "{' '}" : '') })
    } else if (n.type === 'JSXAttribute' && n.name.type === 'JSXIdentifier' && ATTRS.has(n.name.name) && n.value) {
      let lit = null
      if (n.value.type === 'StringLiteral') lit = n.value
      else if (n.value.type === 'JSXExpressionContainer' && n.value.expression.type === 'StringLiteral') lit = n.value.expression
      else if (n.value.type === 'JSXExpressionContainer' && n.value.expression.type === 'TemplateLiteral') {
        const tl = n.value.expression
        if (tl.expressions.length) leftHere++
        else lit = { value: tl.quasis[0].value.cooked }
      }
      if (lit && typeof lit.value === 'string' && hasWords(lit.value) && lit.value === lit.value.trim()) edits.push({ start: n.value.start, end: n.value.end, text: `{${call(lit.value)}}` })
    } else if (n.type === 'ObjectProperty' && !n.computed && n.key.type === 'Identifier' && PROP_KEYS.has(n.key.name) && n.value.type === 'StringLiteral' && p.type === 'ObjectExpression'
      && hasWords(n.value.value) && n.value.value === n.value.value.trim() && n.value.value.length < 160 && (/^[A-Z]/.test(n.value.value) || n.value.value.includes(' '))) {
      edits.push({ start: n.value.start, end: n.value.end, text: call(n.value.value) })
    } else if (n.type === 'CallExpression') {
      const c = n.callee
      const name = c.type === 'Identifier' ? c.name : c.type === 'MemberExpression' && !c.computed ? c.property.name : ''
      if (name === 'say' && n.arguments[0] && n.arguments[0].type === 'StringLiteral' && hasWords(n.arguments[0].value))
        edits.push({ start: n.arguments[0].start, end: n.arguments[0].end, text: call(n.arguments[0].value) })
      if (name === 'confirm' && n.arguments[0] && n.arguments[0].type === 'ObjectExpression') {
        for (const pr of n.arguments[0].properties) {
          if (pr.type === 'ObjectProperty' && !pr.computed && pr.key.type === 'Identifier' && CALL_PROPS.has(pr.key.name) && pr.value.type === 'StringLiteral' && hasWords(pr.value.value))
            edits.push({ start: pr.value.start, end: pr.value.end, text: call(pr.value.value) })
          else if (pr.type === 'ObjectProperty' && !pr.computed && pr.key.type === 'Identifier' && CALL_PROPS.has(pr.key.name) && pr.value.type === 'TemplateLiteral') leftHere++
        }
      }
    }
  })
  stats.left += leftHere
  if (!edits.length) return
  // a nested edit (a text inside an attribute expression that we also replace) cannot happen: attribute values and text nodes never overlap
  const seen = new Set()
  for (let i = edits.length - 1; i >= 0; i--) { if (seen.has(edits[i].start)) edits.splice(i, 1); else seen.add(edits[i].start) }
  edits.sort((a, b) => b.start - a.start)
  let out = code
  for (const e of edits) out = out.slice(0, e.start) + e.text + out.slice(e.end)
  if (!new RegExp(`import \\{[^}]*\\b${fn}\\b[^}]*\\} from '[./]*i18n.js'`).test(out)) {
    const spec = (tUsed ? 't as tr' : 't')
    const imp = `import { ${spec} } from '${rel.includes('/') ? '../' : './'}i18n.js'`
    let lastEnd = 0
    for (const d of ast.program.body) if (d.type === 'ImportDeclaration') lastEnd = d.end
    // positions are from the original text; edits only change text after the imports (JSX), so they still hold
    lastEnd = out.indexOf(String.fromCharCode(10), lastEnd) + 1
    out = out.slice(0, lastEnd) + imp + '\n' + out.slice(lastEnd)
  }
  stats.files++; stats.replaced += edits.length
  console.log(`${APPLY ? 'rewrote' : 'would rewrite'} ${rel}: ${edits.length}${tUsed ? ' (uses tr)' : ''}`)
  if (APPLY) fs.writeFileSync(file, out)
}

function* files(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) { if (!['locales', 'fonts', 'vendor'].includes(e.name)) yield* files(p) }
    else if ((/\.jsx$/.test(e.name) || e.name === 'lessons.js' || e.name === 'helpdata.js') && !SKIP_FILES.has(e.name)) yield p
  }
}
for (const f of files(SRC)) processFile(f)
// keys no screen uses any more (a screen was rewritten or removed) are dropped, so en.json never carries dead words
if (APPLY) {
  const all = [...files(SRC)].map(f => fs.readFileSync(f, 'utf8')).join(' ')
  for (const k of Object.keys(en)) if (!new RegExp(`(^|[^A-Za-z0-9_.])(?:t|tr)\\(\\s*'${k}'`).test(all)) delete en[k]
}
const sorted = Object.fromEntries(Object.entries(en).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
if (APPLY) fs.writeFileSync(EN, JSON.stringify(sorted, null, 1) + '\n')
console.log(`${stats.replaced} words in ${stats.files} files, ${Object.keys(en).length} keys; ${stats.left} built from variables stay in the code`)
