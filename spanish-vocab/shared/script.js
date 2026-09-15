// Shared highlight/blank script for the ES note types.
//
// Contract with the templates — the script needs exactly three things:
//   1. an element with id="oracion" containing the sentence
//   2. an element with id="palabra" containing {{text:Palabra}}
//   3. data-modo="produccion" on the sentence div, on the production FRONT only
//
// Everything else in the templates is markup the script never looks at.

;(function () {
  const ACCENT_INSENSITIVE = true // fall back to a diacritic-blind match
  const SEPARATOR = '|' // multiple targets: se|dio cuenta
  const HUECO = '[…]'

  const host = document.getElementById('oracion')
  const tEl = document.getElementById('palabra')
  if (!host || !tEl) {
    return
  }

  const oculto = host.dataset && host.dataset.modo === 'produccion'

  const raw = (tEl.textContent || '').trim()
  if (!raw) {
    return
  }

  // recognition: respect hand-bolding and bail.
  // production: must always run, or the answer stays visible.
  if (!oculto && host.querySelector('b, strong')) {
    return
  }
  if (host.querySelector('.acierto, .hueco')) {
    return
  } // already processed

  const LETTER = 'A-Za-zÀ-ÖØ-öø-ÿ'
  const FOLD = {
    a: 'aáàâä',
    e: 'eéèêë',
    i: 'iíìîï',
    o: 'oóòôö',
    u: 'uúùûü',
    n: 'nñ',
    c: 'cç',
    y: 'yýÿ',
  }

  function esc(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  }

  function fold(ch) {
    const lower = ch.toLowerCase()
    for (const base in FOLD) {
      if (FOLD[base].indexOf(lower) !== -1) {
        return `[${FOLD[base]}]`
      }
    }
    return esc(ch)
  }

  function tokenPattern(token, loose) {
    let out = ''
    for (let i = 0; i < token.length; i++) {
      out += loose ? fold(token[i]) : esc(token[i])
    }
    return out.replace(/(\\?\s)+/g, '[\\s\\u00A0]+')
  }

  function build(targets, loose) {
    const alts = targets.map(function (t) {
      return tokenPattern(t, loose)
    })
    return new RegExp(
      `(^|[^${LETTER}])(${alts.join('|')})(?![${LETTER}])`,
      'gi',
    )
  }

  function highlight(root, re) {
    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_TEXT,
      null,
      false,
    )
    const nodes = []
    let hits = 0
    while (walker.nextNode()) {
      nodes.push(walker.currentNode)
    }

    nodes.forEach(function (node) {
      const text = node.nodeValue
      let m,
        last = 0
      re.lastIndex = 0
      if (!re.test(text)) {
        return
      }
      re.lastIndex = 0

      const frag = document.createDocumentFragment()
      while ((m = re.exec(text)) !== null) {
        const start = m.index + m[1].length
        frag.appendChild(document.createTextNode(text.slice(last, start)))

        let el
        if (oculto) {
          el = document.createElement('span')
          el.className = 'hueco'
          el.textContent = HUECO
        } else {
          el = document.createElement('b')
          el.className = 'acierto'
          el.textContent = m[2]
        }
        frag.appendChild(el)

        last = start + m[2].length
        hits++
        if (m[0].length === 0) {
          re.lastIndex++
        } // zero-length guard
      }
      frag.appendChild(document.createTextNode(text.slice(last)))
      node.parentNode.replaceChild(frag, node)
    })
    return hits
  }

  const targets = raw
    .split(SEPARATOR)
    .map(function (s) {
      return s.trim()
    })
    .filter(Boolean)
    .sort(function (a, b) {
      return b.length - a.length
    }) // longest first

  let found = highlight(host, build(targets, false))
  if (!found && ACCENT_INSENSITIVE) {
    found = highlight(host, build(targets, true))
  }
  if (!found) {
    host.classList.add('sin-coincidencia')
  }
})()
