# spanish-vocab

Anki note types for Spanish vocabulary, built around sentences rather than bare
word pairs. Edit here, run `./build.sh`, paste into Anki.

## Why two note types

A word lives in **one** of them at a time.

| | ES Reconocimiento | ES Producción |
|---|---|---|
| Cards per note | 1 | 2 |
| Fields | Lema, Palabra, Oración, Definición, Fuente, Notas | + Pista |
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

- **Lema** — the dictionary form (`hechizar` for a lookup of `hechizado`,
  `frenar` for `frenó`). It's the first field, so it's what Anki keys the note
  on: its sort field and its duplicate check. One note per lemma — Lema is what
  stops a second form of the same word (`hechizaba`, `hechizó`) from being
  added as a new note. The Kindle importer fills it from Kindle's own `stem`.
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
mise run test
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
the full design.

## Reading progress: lookups per 10k words

Progress is measured as dictionary lookups per 10,000 words read, per book.
If it falls over time on similar books, comprehension is improving.
`tools/reading_stats.py` (`mise run reading-stats`) works it out from the
Kindle (read-only, over USB) for the "Spanish Reading Tracker" Google Sheet.

The script never talks to Google. A Claude Code session reads the Books tab
with its Sheets connector, saves it as JSON, runs the script, shows the
resulting plan, then writes it:

```
mise run reading-stats -- --sheet sheet.json > plan.json
```

### What it writes

| Column | Written | Rule |
|---|---|---|
| A Book | new rows only | For books with lookups that have no row yet |
| B Status | always | Inferred (see below); an `[auto]` note when unsure |
| C Finished | only if empty | Date of last Kindle activity (last lookup or page-history entry); approximate |
| D Lookups / 10k | never | An ARRAYFORMULA in D2 computes it from E and F |
| E Lookups | always | Count of lookups in `vocab.db` |
| F Words | if empty, or if its note starts `[auto]` | Combined estimate (see below), with an `[auto]` note listing the inputs |
| G–J | never (H on new rows only) | Yours |

Books are matched to rows by title, with accents, "(Spanish Edition)"-style
parentheticals and trailing ": 6" removed. In `vocab.db`, lookups are grouped
by ASIN, because a re-downloaded book gets a new book id with the same ASIN.
Junk entries go in `_IGNORED_ASINS`.

### Word count

There's no exact count: the books are DRM'd. Up to three estimates are
combined:

| Method | Weight | Source | Used when |
|---|---|---|---|
| kindle | 3 | `book.info.store` / `timer.model` in the `.yjr`/`.yjf` sidecar: (words turned past, fraction of book); words ÷ fraction. The two records agree within ~0.3%. | The record covers ≥ 2% of the book. Below that, one page's density skews it: Piedra filosofal at 0.34% came out 27% low. |
| amazon | 2 | Amazon's "typical time to read" (`StartActions.data.<ASIN>.asc`) × 264 wpm. It's per-book, not personal: the same for every reader, and present even for unread books. 264 matched `kindle` within ~2% on 4 books, but was 13% high for Morel. | Always, if Amazon has a reading time |
| position | 1 | Furthest position read ÷ 5.60, the mean positions-per-word at the end of finished books (range 5.30–5.73) | Only when the book is inferred Finished |

Outliers are dropped before averaging. With 3 values, any value more than 15%
from the median is dropped; with 2, the reference is the higher-weight value.
15% sits just above the biggest real disagreement seen (Morel, 13%).

Ruled out:
- Amazon's page count × words per page: words per page depends on the print
  edition's typesetting.
- Goodreads: page counts only.
- Stripping DRM to count the text: not supported.

A DRM-free copy's exact count, typed into F by hand, always wins.

### Status

The Kindle doesn't record "finished" anywhere visible over USB: the book's
length in positions is inside the DRM'd `.kfx`. So status is a heuristic,
checked against 9 books with known status on 2026-11-22:

| Rule | Status | Note? |
|---|---|---|
| An `EndActions` record exists (you used the end-of-book screen) | Finished | no |
| The next book in the series (same series, position + 1) has been started | Finished | no |
| No lookups, and under 2% of the estimated length | Up next | no |
| Furthest position ≥ 90% of the estimated length | Finished | yes |
| Nothing on the Kindle in 60+ days | Reading | yes |
| Otherwise | Reading | no |

Signals that don't work:
- **`lpr` (last page read):** the iOS app overwrites it when it opens a book.
  This made Cáliz de fuego look abandoned at 94%.
- **The `timer.model` fraction:** it undercounts reading done on the phone.
- **Popular highlights:** they don't mark the end of the book.

Goodreads shelf RSS would give the real status and date
([#18](https://github.com/ledhed2222/anki-cards/issues/18)).

### Caveats

- Lookups made in the Kindle iOS app aren't in `vocab.db`, so books read
  partly on the phone undercount.
- A book with no lookups has no `vocab.db` entry at all, so it isn't picked
  up until its first lookup.

## Deck setup

- FSRS on, parameters optimized, desired retention ~0.85–0.90.
- Old deck: Browser → `card:2 deck:"<deck>"` → select all → Suspend. Kills the
  bare EN→ES reverse cards without losing review history. Unsuspend only for
  words with one clear translation (mostly concrete nouns, article included
  for gender).
