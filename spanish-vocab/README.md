# spanish-vocab

Anki note types for Spanish vocabulary, built around sentences rather than bare
word pairs. Edit here, run `./build.sh`, paste into Anki.

## Why two note types

A word lives in **one** of them at a time.

| | ES Reconocimiento | ES Producción |
|---|---|---|
| Cards per note | 1 | 2 |
| Fields | Palabra, Oración, Definición, Fuente, Notas | + Pista |
| For | words you need to understand | words you want to *say* |

Default every new word to **ES Reconocimiento**. Upgrade a word to
**ES Producción** when it passes the production test:

- you reached for it while speaking or writing and didn't have it
- it's high-frequency everyday vocabulary
- you keep producing the wrong word for the meaning

Rough target: ~80% recognition, ~20% production.

Upgrading: Browser → select the note → Actions → Change Note Type →
ES Producción → confirm the field mapping → edit the note to fill in Pista.
The recognition card keeps its full scheduling history.

## Fields

- **Palabra** — the surface form *exactly as it appears in the sentence*
  (`frenó`, not `frenar`). This is what the script finds and bolds or blanks.
  Split phrases use the `|` separator: `se|dio cuenta`.
- **Oración** — the sentence. HTML is preserved, so you can hand-bold or
  italicize. Don't hand-bold notes destined for production.
- **Definición** — short English gloss, or a Spanish definition once that's
  comfortable.
- **Fuente** — optional. Book or source. Hidden when empty.
- **Notas** — optional. Freeform notes on usage, register, etc. Hidden when empty.
- **Pista** — production only. The English hint shown under the blank; this is
  what disambiguates which Spanish word is wanted.

## Layout

```
shared/styling.css     the CSS, identical in both note types
shared/script.js       the highlight/blank script, identical in both
reconocimiento/        front + back for its one card type
produccion/            front + back for both card types
build.sh               glues shared/ into paste-ready blocks in dist/
tools/                 vocabulary-capture scripts (not part of the card build)
docs/                  design notes for the capture tooling
```

The script is mode-aware, so the *same* file serves all four templates. The
templates signal intent to it, and the contract is only three things:

1. an element with `id="oracion"` holding the sentence
2. an element with `id="palabra"` holding `{{text:Palabra}}`
3. `data-modo="produccion"` on the sentence div — **production front only**

Everything else is markup the script never looks at.

## Gotchas

- **The production back must not use `{{FrontSide}}`.** It would carry
  `data-modo` and the already-blanked markup across, hiding the answer. It
  renders `{{Oración}}` fresh instead. The recognition back can use
  `{{FrontSide}}` safely.
- **`{{text:Palabra}}`, not `{{Palabra}}`.** The filter strips HTML, so invisible
  `<span>` wrappers from pasting don't leak into the regex.
- **Accented field names must match exactly.** `{{Oracion}}` will not resolve to
  `{{Oración}}`. If a field renders blank, retype the name from the field list —
  macOS input can produce a combining accent instead of a precomposed character.
- **The red left border** (`.sin-coincidencia`) means Palabra didn't match
  anything in Oración. Fix the note; don't keep reviewing it.
- **Anki does not support JavaScript in templates.** This works, but it's on us
  if a future version changes reviewer internals.

## Tests

```
npm install
npm test
```

17 checks over the regex and DOM walking: word boundaries against accented
Latin, the accent-folding fallback, split phrases, markup preservation, and —
the one that actually matters — that a hand-bolded sentence still gets blanked
in production mode rather than leaking the answer.

jsdom is not WKWebView, so this catches logic regressions only.

## Test in Anki before converting anything in bulk

- a reflexive: Palabra = `se|dio cuenta`
- a word at the start of the sentence
- a word appearing twice in the sentence
- a hand-bolded note
- an accented word (`frenó`) — confirms the folding fallback
- all of the above on iOS, not just desktop

## Vocabulary capture

`tools/kindle_vocab_import.py` reads a physical Kindle's Vocabulary Builder
(over USB, read-only) and adds new lookups as `Español Reconocimiento` notes,
deduped against the whole deck by lemma. See `docs/capture-automation.md` for
the full design, including the iOS/macOS Shortcuts side (not yet built).

## Deck setup

- FSRS on, parameters optimized, desired retention ~0.85–0.90.
- Old deck: Browser → `card:2 deck:"<deck>"` → select all → Suspend. Kills the
  bare EN→ES reverse cards without losing review history. Unsuspend only for
  words with one clear translation (mostly concrete nouns, article included
  for gender).
