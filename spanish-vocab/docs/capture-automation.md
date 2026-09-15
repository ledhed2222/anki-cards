# Capturing new vocabulary on the go

Design notes for getting a word + its real sentence into Anki with minimal
friction, from wherever it was actually encountered — reading on Kindle,
reading/browsing on phone or Mac. Two separate capture paths feed the same
deck; neither shares infrastructure with the other, and neither needs any
server.

## Source 1: physical Kindle → `tools/kindle_vocab_import.py`

Kindle's own Vocabulary Builder already tracks every dictionary lookup
locally on the device, with exactly the fields needed: the word, the
surrounding sentence, and the book title. `tools/kindle_vocab_import.py`
reads that file over the USB cable when the device is plugged in - read-only
against the Kindle, it never writes anything back to it.

- File: `<mounted Kindle volume>/system/vocabulary/vocab.db`, a SQLite file.
  Schema (community-documented, unofficial — always run `--inspect` after a
  firmware update to confirm before trusting a real run):
  ```
  WORDS(id, word, stem, lang, category, timestamp, profileid)
  LOOKUPS(id, word_key, book_key, dict_key, pos, usage, timestamp)
  BOOK_INFO(id, asin, guid, lang, title, authors)
  ```
- Filters to `lang = 'es'` so English-book lookups don't leak in.
- Tracks a "last synced" timestamp in `~/.anki-cards/kindle_vocab_state.json`
  so replugging the device doesn't reprocess old lookups.
- Adds as **`Español Reconocimiento` only** — no `Pista` needed, since this
  is real personal reading context, not a sense-disambiguation problem the
  way the old leech conversion was. `Fuente` gets the book title for free.
- **Dedup: keyed on Kindle's own `stem` (lemma), not the exact inflected
  form.** Looking up `corrió` shouldn't re-add if the deck already has a card
  for any form of `correr`. Checked via Anki's own search
  (`deck:"Vocabulario español" w:<stem>`) across *all* note types/fields, not
  just the new Reconocimiento/Producción ones — so it also catches words
  still sitting in old-format `Basic` notes.
  - `w:` is Anki's whole-word search modifier — confirmed on this collection
    that `w:empleado` matches and `w:emple` (substring) doesn't, avoiding the
    same class of false-positive collisions the leech-conversion word-boundary
    bug had.
- **Duplicates are silently skipped, not surfaced for review** — logged to
  `~/.anki-cards/kindle_vocab_skipped.log` (word, stem, book, sentence) for
  visibility, but the existing card is left untouched and no action is
  expected. This was a deliberate choice over the alternative (save the new
  example sentence somewhere for possibly adding to the existing note's
  `Notas` field) — simpler, and a second example sentence for a word you
  already know isn't worth the review overhead.
- Run order: `--inspect` first (schema/sample rows, read-only) → dry run
  (default) → `--apply`.

## Source 2: Shortcuts app (iOS / macOS)

Goal: highlight a word while reading (Safari, a book, anywhere with a Share
Sheet), run a Shortcut, get a new note without leaving the app you were
reading in.

### Why there's no backend

The obvious design is "Shortcut POSTs to some server, server calls
AnkiConnect" — this was fully designed at one point (either a NAS or a small
VPS running Anki headless via Docker + Xvfb, reachable through Tailscale so
AnkiConnect's lack of authentication doesn't become a public exposure). Two
things killed it:

- The originally-intended host (a Synology DS418) can't run Docker at all —
  it's ARM (Realtek RTD1296), and Synology's Container Manager only supports
  x86_64. Native Anki on ARM DSM would mean cross-building a full Qt6+Rust
  desktop app by hand — not practical.
- More importantly, it turned out to be solving a problem that doesn't
  exist: **AnkiMobile has a built-in URL scheme for adding notes directly**,
  no companion app or server required:
  ```
  anki://x-callback-url/addnote?profile=<name>&type=<note type>&deck=<deck>&fld<FieldName>=<value>...
  ```
  Confirmed via the official AnkiMobile manual (`docs.ankimobile.net/url-schemes.html`).
  Fields are `fld<FieldName>=<value>` (e.g. `fldPalabra=...`), HTML-interpreted,
  need percent-encoding (Shortcuts' native `URL` action does this
  automatically when fields are added as query parameters — no manual
  encoding needed). `dupes=1` would allow duplicates; **don't pass it** — the
  default behavior blocks an exact duplicate within the same note type, which
  is a free (if partial — see below) safety net.

This is iOS/iPadOS-only. **Anki Desktop on macOS does *not* implement this
scheme** (confirmed: it's an AnkiMobile-specific feature, unrelated codebase
to Desktop) — so the two platforms need different final delivery steps, even
though the capture/translate steps are identical.

### Shared capture steps (both platforms)

1. Share Sheet gives the selected sentence as input → `Oración`.
2. **Ask for Input** (text) — "Which word?" (select the *sentence*, not just
   the word, when sharing — the word gets typed in this step instead. Faster
   and more reliable than trying to get the OS to auto-expand a word
   selection to sentence scope, which isn't a thing Share Sheets do.)
3. **Translate Text** (native Shortcuts action, on-device) on just the word →
   `Definición`.
4. **Ask for Input** (optional) — "Source?" → `Fuente`.
5. Default note type to **`Español Reconocimiento`**, matching the deck's own
   documented policy in `spanish-vocab/README.md` (new words default to
   Reconocimiento, get upgraded to Producción once they pass the production
   test) — not Producción. Also means no `Pista` field needed most of the
   time, one fewer prompt.

### iOS: `anki://x-callback-url/addnote`

Build the URL via Shortcuts' `URL` action with query parameters as a
dictionary (`type`, `deck=Vocabulario español`, `fldPalabra`, `fldOración`,
`fldDefinición`, `fldFuente`, `profile=<AnkiMobile profile name>`), then
**Open URLs** on it. That's the whole delivery step — launches AnkiMobile,
adds the note, done. No network dependency at all.

Dedup here is *only* Anki's built-in same-note-type exact-duplicate block —
weaker than the Kindle importer's cross-note-type stem check, since Shortcuts
has no way to query Anki's state first (no read/search URL scheme exists,
only `addnote`). Accepted as good-enough for this path: actively
reading-and-capturing a word right now is less likely to hit an accidental
re-lookup than the bulk historical-lookup case Kindle represents.

### macOS: AnkiConnect directly

Anki Desktop + AnkiConnect is already running locally on the Mac used for
this whole project (`127.0.0.1:8765`), so no networking concerns — same
machine, always reachable. This path can actually do the *full* dedup check,
entirely in native Shortcuts actions, no Python needed:

1. **Get Contents of URL** (POST, `http://127.0.0.1:8765`, JSON body):
   ```json
   {"action":"findNotes","version":6,"params":{"query":"deck:\"Vocabulario español\" w:<word>"}}
   ```
2. **If** the result list is empty → **Get Contents of URL** again:
   ```json
   {"action":"addNote","version":6,"params":{"note":{
     "deckName":"Vocabulario español",
     "modelName":"Español Reconocimiento",
     "fields":{"Palabra":"...","Oración":"...","Definición":"...","Fuente":"..."},
     "tags":["shortcut-import"]
   }}}
   ```
3. **Otherwise** → notify that it's a duplicate, skip.

Since Shortcuts supports branching on `Device Type`, one shortcut (shared via
iCloud) could plausibly hold both branches — same capture logic, diverging
only at the final delivery step.

### Status

Designed, not yet built — the actual `.shortcut` has to be authored in the
Shortcuts app itself (Claude Code has no way to generate that file directly).
The spec above is what to build from. Not yet tested end-to-end on a real
device.

## Things ruled out along the way

- **AnkiWeb (the website) can add notes to an existing note type when
  logged in** — confirmed directly by testing, contrary to an initial (wrong)
  assumption. But there's no documented API for it, so it doesn't help with
  Shortcut automation specifically; it's a manual fallback at most.
- **A NAS/VPS running Anki headless** — see "why there's no backend" above.
  Not needed given AnkiMobile's native scheme, but the Docker+Xvfb approach
  remains the right one *if* a headless always-on Anki host is ever actually
  needed for something else (an x86_64 host would work; the DS418 specifically
  cannot).
