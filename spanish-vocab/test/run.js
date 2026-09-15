// Sanity tests for shared/script.js. Requires jsdom: npm install jsdom
//
//   node test/run.js
//
// Not a substitute for testing in Anki itself, especially on iOS — jsdom is
// not WKWebView. This just catches regex and DOM-walking regressions.

import fs from 'node:fs'
import path from 'node:path'
import { JSDOM } from 'jsdom'

const SCRIPT = fs.readFileSync(
  path.join(import.meta.dirname, '..', 'shared', 'script.js'),
  'utf8',
)

function render({ oracion, palabra, modo }) {
  const modoAttr = modo ? ` data-modo="${modo}"` : ''
  const dom = new JSDOM(
    `<!doctype html><body class="card">
    <div id="oracion" class="oracion"${modoAttr}>${oracion}</div>
    <div id="palabra" style="display:none">${palabra}</div>
  </body>`,
    { runScripts: 'outside-only' },
  )
  dom.window.eval(SCRIPT)
  return dom.window.document.getElementById('oracion')
}

let pass = 0,
  fail = 0

function check(name, fn) {
  try {
    fn()
    pass++
    console.log(`  ok   ${name}`)
  } catch (e) {
    fail++
    console.log(`  FAIL ${name}\n       ${e.message}`)
  }
}

function assert(cond, msg) {
  if (!cond) {
    throw new Error(msg)
  }
}

console.log('\nrecognition mode')

check('bolds a simple match', () => {
  const el = render({ oracion: 'El taxista frenó de golpe.', palabra: 'frenó' })
  assert(el.querySelectorAll('b.acierto').length === 1, el.innerHTML)
  assert(el.querySelector('b.acierto').textContent === 'frenó', el.innerHTML)
})

check('matches at the start of the sentence', () => {
  const el = render({ oracion: 'Frenó de golpe el taxista.', palabra: 'Frenó' })
  assert(el.querySelectorAll('b.acierto').length === 1, el.innerHTML)
})

check('matches every occurrence', () => {
  const el = render({ oracion: 'Frenó, y frenó otra vez.', palabra: 'frenó' })
  assert(el.querySelectorAll('b.acierto').length === 2, el.innerHTML)
})

check('does not match inside a longer word', () => {
  const el = render({
    oracion: 'El ciudadano quiso dar un paseo.',
    palabra: 'dar',
  })
  const hits = [...el.querySelectorAll('b.acierto')].map((n) => n.textContent)
  assert(hits.length === 1 && hits[0] === 'dar', JSON.stringify(hits))
})

check('accent-insensitive fallback', () => {
  // Palabra written without the accent, sentence has it
  const el = render({ oracion: 'El taxista frenó de golpe.', palabra: 'freno' })
  assert(el.querySelectorAll('b.acierto').length === 1, el.innerHTML)
})

check('multi-word target', () => {
  const el = render({
    oracion: 'No se dio cuenta del error.',
    palabra: 'dio cuenta',
  })
  assert(
    el.querySelector('b.acierto').textContent === 'dio cuenta',
    el.innerHTML,
  )
})

check('split phrase via separator', () => {
  const el = render({
    oracion: 'No se dio cuenta del error.',
    palabra: 'se|dio cuenta',
  })
  assert(el.querySelectorAll('b.acierto').length === 2, el.innerHTML)
})

check('longest target wins over overlapping short one', () => {
  const el = render({ oracion: 'No se dio cuenta.', palabra: 'dio|dio cuenta' })
  assert(
    el.querySelector('b.acierto').textContent === 'dio cuenta',
    el.innerHTML,
  )
})

check('no match flags the card', () => {
  const el = render({ oracion: 'El taxista frenó.', palabra: 'correr' })
  assert(el.classList.contains('sin-coincidencia'), el.outerHTML)
})

check('hand-bolded sentence is left alone', () => {
  const el = render({
    oracion: 'El taxista <b>frenó</b> de golpe.',
    palabra: 'frenó',
  })
  assert(el.querySelectorAll('b.acierto').length === 0, el.innerHTML)
  assert(el.querySelectorAll('b').length === 1, el.innerHTML)
})

check('does not corrupt surrounding markup', () => {
  const el = render({
    oracion: 'En <i>Ficciones</i> el taxista frenó.',
    palabra: 'frenó',
  })
  assert(el.querySelector('i').textContent === 'Ficciones', el.innerHTML)
  assert(el.querySelectorAll('b.acierto').length === 1, el.innerHTML)
})

check('apostrophe in target does not break the regex', () => {
  const el = render({
    oracion: "Dijo qu'est-ce y se fue.",
    palabra: "qu'est-ce",
  })
  assert(el.querySelectorAll('b.acierto').length === 1, el.innerHTML)
})

check('empty Palabra is a no-op', () => {
  const el = render({ oracion: 'El taxista frenó.', palabra: '' })
  assert(el.querySelectorAll('b, span.hueco').length === 0, el.innerHTML)
  assert(!el.classList.contains('sin-coincidencia'), el.outerHTML)
})

console.log('\nproduction mode')

check('blanks the target', () => {
  const el = render({
    oracion: 'El taxista frenó de golpe.',
    palabra: 'frenó',
    modo: 'produccion',
  })
  assert(el.querySelectorAll('span.hueco').length === 1, el.innerHTML)
  assert(!el.textContent.includes('frenó'), el.textContent)
})

check('blanks every occurrence', () => {
  const el = render({
    oracion: 'Frenó, y frenó otra vez.',
    palabra: 'frenó',
    modo: 'produccion',
  })
  assert(el.querySelectorAll('span.hueco').length === 2, el.innerHTML)
  assert(!el.textContent.toLowerCase().includes('frenó'), el.textContent)
})

check('hand-bolded sentence still gets blanked (no answer leak)', () => {
  const el = render({
    oracion: 'El taxista <b>frenó</b> de golpe.',
    palabra: 'frenó',
    modo: 'produccion',
  })
  assert(!el.textContent.includes('frenó'), `ANSWER LEAKED: ${el.innerHTML}`)
})

check('blanks a split phrase', () => {
  const el = render({
    oracion: 'No se dio cuenta del error.',
    palabra: 'se|dio cuenta',
    modo: 'produccion',
  })
  assert(el.querySelectorAll('span.hueco').length === 2, el.innerHTML)
  assert(!el.textContent.includes('dio cuenta'), el.textContent)
})

console.log(`\n${pass} passed, ${fail} failed\n`)
process.exit(fail ? 1 : 0)
