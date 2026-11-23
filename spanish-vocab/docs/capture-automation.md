# Capturing new vocabulary on the go

Design notes for getting a word + its real sentence into Anki with minimal
friction, from wherever it was actually encountered.

## Physical Kindle → `tools/kindle_vocab_import.py`

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
