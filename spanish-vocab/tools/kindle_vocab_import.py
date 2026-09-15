#!/usr/bin/env python3
"""
Import Spanish word lookups from a physical Kindle's Vocabulary Builder into
Español Reconocimiento notes. Read-only against the Kindle - it only ever
reads vocab.db off the mounted device, never writes to it.

    python3 tools/kindle_vocab_import.py --inspect
    python3 tools/kindle_vocab_import.py --limit 20          # small dry run
    python3 tools/kindle_vocab_import.py                     # full dry run
    python3 tools/kindle_vocab_import.py --apply

Schema is the community-documented (unofficial) layout of vocab.db:
  WORDS(id, word, stem, lang, category, timestamp, profileid)
  LOOKUPS(id, word_key, book_key, dict_key, pos, usage, timestamp)
  BOOK_INFO(id, asin, guid, lang, title, authors)
Column names can vary by firmware version - always run --inspect after a
firmware update to confirm before trusting a real run.

`lang` on WORDS is per-word (which dictionary Kindle used for that specific
lookup), not the book's language - `--lang es` (the default) filters on
that, so it already reflects what Kindle itself considered the word to be.
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request

LETTER = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
HTML_TAG = re.compile(r"<[^>]+>")
FORM_OF = re.compile(
    r"^(plural|feminine|masculine|diminutive|augmentative|superlative|"
    r"first-person|second-person|third-person|past participle|"
    r"present participle|gerund|imperative) ", re.IGNORECASE,
)

ANKI_URL = "http://127.0.0.1:8765"
DECK = "Vocabulario español"
MODEL = "Español Reconocimiento"
STATE_DIR = os.path.expanduser("~/.anki-cards")
STATE_FILE = os.path.join(STATE_DIR, "kindle_vocab_state.json")
SKIP_LOG = os.path.join(STATE_DIR, "kindle_vocab_skipped.log")
WIKTIONARY_URL = "https://en.wiktionary.org/api/rest_v1/page/definition/"


def anki(action, **params):
    payload = json.dumps({"action": action, "version": 6, "params": params})
    req = urllib.request.Request(
        ANKI_URL, data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as e:
        sys.exit(f"Can't reach AnkiConnect at {ANKI_URL} - is Anki running?\n  {e}")
    if body.get("error"):
        raise RuntimeError(body["error"])
    return body["result"]


def find_vocab_db(kindle_path):
    path = os.path.join(kindle_path, "system", "vocabulary", "vocab.db")
    if not os.path.exists(path):
        sys.exit(f"No vocab.db at {path} - is the Kindle plugged in and mounted "
                 f"at {kindle_path}? Use --kindle-path to point elsewhere.")
    return path


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"last_timestamp": 0}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def inspect(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()
    for table in ("WORDS", "LOOKUPS", "BOOK_INFO"):
        print(f"\n=== {table} ===")
        cur.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in cur.fetchall()]
        print("columns:", cols)
        cur.execute(f"SELECT * FROM {table} LIMIT 3")
        for row in cur.fetchall():
            print(" ", row)
    conn.close()


def fetch_new_lookups(db_path, lang, since_timestamp):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT w.word, w.stem, l.usage, l.timestamp, b.title
        FROM LOOKUPS l
        JOIN WORDS w ON w.id = l.word_key
        LEFT JOIN BOOK_INFO b ON b.id = l.book_key
        WHERE w.lang = ? AND l.timestamp > ?
        ORDER BY l.timestamp ASC
        """,
        (lang, since_timestamp),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_deck_words():
    """Every whole word occurring anywhere in the deck, fetched once (2
    AnkiConnect calls total) rather than one findNotes round-trip per word.
    AnkiConnect can't handle concurrent requests (a single-threaded local
    server - tested directly, concurrent calls get connection-reset), and at
    ~120ms per call that's minutes for a few thousand words sequentially.
    Tokenizing the whole deck's text locally and checking set membership is
    the same "does this whole word appear anywhere in the note" semantics as
    Anki's own `w:` search, just ~1500x faster for a bulk run like this."""
    ids = anki("findNotes", query=f'deck:"{DECK}"')
    notes = anki("notesInfo", notes=ids) if ids else []
    words = set()
    for n in notes:
        for f in n["fields"].values():
            text = HTML_TAG.sub("", f["value"] or "")
            words.update(w.lower() for w in LETTER.findall(text))
    return words


def fetch_wiktionary_gloss(term):
    """English Wiktionary's REST API, keyed on the Spanish-language section
    of the word's page. Open content (CC BY-SA), explicitly built for this
    kind of reuse - unlike WordReference (see docs/leech-conversion.md),
    there's no ToS concern here. Look up the stem/lemma, not the raw
    inflected word: an inflected form's own page often just says "plural of
    X" rather than a real definition (confirmed: 'cantos' -> 'plural of
    canto', but 'canto' -> 'singing, song'). Returns None on 404 or if
    every definition found is itself a bare inflection cross-reference."""
    url = WIKTIONARY_URL + urllib.parse.quote(term)
    req = urllib.request.Request(
        url, headers={"User-Agent": "anki-cards/1.0 (personal study script)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None
    except Exception:
        return None

    for entry in data.get("es", []):
        for d in entry.get("definitions", []):
            text = HTML_TAG.sub("", d.get("definition", "")).strip()
            if text and not FORM_OF.match(text):
                return text
    return None


def fetch_claude_gloss(word):
    """Fallback for words Wiktionary doesn't have. Same reasoning as the
    leech-conversion sense-judgment: this is a translation task, not
    something that needs a separate API relationship - `claude -p` runs it
    directly."""
    prompt = (
        f"Give a short English gloss (2-6 words) for the Spanish word "
        f"'{word}'. Respond with ONLY the gloss, nothing else."
    )
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return None
    text = result.stdout.strip()
    return text or None


def fetch_gloss(word, stem):
    return fetch_wiktionary_gloss(stem or word) or fetch_claude_gloss(word)


def log_skip(reason, word, stem, usage, title):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SKIP_LOG, "a", encoding="utf-8") as f:
        f.write(f"{reason}\t{word}\t{stem}\t{title}\t{usage}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kindle-path", default="/Volumes/Kindle")
    ap.add_argument("--lang", default="es")
    ap.add_argument("--limit", type=int, default=0, help="max lookups to process (0 = all)")
    ap.add_argument("--apply", action="store_true", help="actually add notes (default: dry run)")
    ap.add_argument("--inspect", action="store_true", help="print vocab.db schema/sample rows and exit")
    ap.add_argument("--no-definitions", action="store_true",
                    help="skip Wiktionary/claude lookups, leave Definición blank (faster dry runs)")
    args = ap.parse_args()

    db_path = find_vocab_db(args.kindle_path)

    if args.inspect:
        inspect(db_path)
        return

    fields = anki("modelFieldNames", modelName=MODEL)
    print(f"Target model {MODEL!r} has fields: {fields}")

    deck_words = fetch_deck_words()
    print(f"{len(deck_words)} distinct words already in {DECK!r}")

    state = load_state()
    lookups = fetch_new_lookups(db_path, args.lang, state["last_timestamp"])
    print(f"{len(lookups)} new {args.lang!r} lookups since last sync")
    if args.limit:
        lookups = lookups[:args.limit]
        print(f"(limited to first {len(lookups)})")

    added = 0
    skip_counts = {"no_usage": 0, "duplicate": 0, "no_definition": 0}
    max_timestamp = state["last_timestamp"]

    seen_this_run = set()

    for row in lookups:
        word, stem, usage, ts, title = (
            row["word"], row["stem"], row["usage"], row["timestamp"], row["title"],
        )
        max_timestamp = max(max_timestamp, ts)

        if not usage:
            skip_counts["no_usage"] += 1
            log_skip("no_usage", word, stem, "(no usage sentence captured)", title or "")
            continue

        key = (stem or word).lower()

        if key in seen_this_run:
            skip_counts["duplicate"] += 1
            log_skip("duplicate_in_batch", word, stem, usage, title or "")
            continue

        if key in deck_words:
            skip_counts["duplicate"] += 1
            log_skip("duplicate_in_anki", word, stem, usage, title or "")
            continue

        seen_this_run.add(key)

        definicion = ""
        if not args.no_definitions:
            definicion = fetch_gloss(word, stem) or ""
            if not definicion:
                # Neither Wiktionary nor the claude fallback found anything -
                # an error state, not something to silently add blank.
                skip_counts["no_definition"] += 1
                log_skip("no_definition", word, stem, usage, title or "")
                continue

        print(f"  + {word} = {definicion or '(skipped)'}  ({title or 'unknown source'})")
        if args.apply:
            try:
                anki(
                    "addNote",
                    note={
                        "deckName": DECK,
                        "modelName": MODEL,
                        "fields": {
                            "Palabra": word,
                            "Oración": usage,
                            "Definición": definicion,
                            "Fuente": title or "",
                        },
                        "tags": ["kindle-import"],
                    },
                )
            except RuntimeError as e:
                if "duplicate" not in str(e):
                    raise
                # Our stem-based dedup missed this one (surface form matches an
                # existing note under a different stem key) - Anki's own exact-
                # match check caught it. Log and move on rather than crash.
                skip_counts["duplicate"] += 1
                log_skip("duplicate_in_anki", word, stem, usage, title or "")
                continue
        added += 1

    total_skipped = sum(skip_counts.values())
    print(f"\n{added} to add, {total_skipped} skipped "
          f"({skip_counts['duplicate']} duplicate, {skip_counts['no_usage']} no usage sentence, "
          f"{skip_counts['no_definition']} no definition found) "
          f"- see {SKIP_LOG}")
    if not args.apply:
        print("Dry run - re-run with --apply to actually add notes.")
    else:
        state["last_timestamp"] = max_timestamp
        save_state(state)
        if args.no_definitions:
            print("Note: Definición is left blank - fill it in yourself in Anki's browser.")


if __name__ == "__main__":
    main()
