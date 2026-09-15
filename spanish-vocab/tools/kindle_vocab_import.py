#!/usr/bin/env python3
"""
Import Spanish word lookups from a physical Kindle's Vocabulary Builder into
Español Reconocimiento notes. Read-only against the Kindle - it only ever
reads vocab.db off the mounted device, never writes to it.

    python3 tools/kindle_vocab_import.py --inspect
    python3 tools/kindle_vocab_import.py                  # dry run
    python3 tools/kindle_vocab_import.py --apply

Schema is the community-documented (unofficial) layout of vocab.db:
  WORDS(id, word, stem, lang, category, timestamp, profileid)
  LOOKUPS(id, word_key, book_key, dict_key, pos, usage, timestamp)
  BOOK_INFO(id, asin, guid, lang, title, authors)
Column names can vary by firmware version - always run --inspect after a
firmware update to confirm before trusting a real run.
"""

import argparse
import json
import os
import sqlite3
import sys
import urllib.request

ANKI_URL = "http://127.0.0.1:8765"
DECK = "Vocabulario español"
MODEL = "Español Reconocimiento"
STATE_DIR = os.path.expanduser("~/.anki-cards")
STATE_FILE = os.path.join(STATE_DIR, "kindle_vocab_state.json")
SKIP_LOG = os.path.join(STATE_DIR, "kindle_vocab_skipped.log")


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


def is_duplicate(stem):
    query = f'deck:"{DECK}" w:{stem}'
    return len(anki("findNotes", query=query)) > 0


def log_skip(word, stem, usage, title):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SKIP_LOG, "a", encoding="utf-8") as f:
        f.write(f"{word}\t{stem}\t{title}\t{usage}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kindle-path", default="/Volumes/Kindle")
    ap.add_argument("--lang", default="es")
    ap.add_argument("--apply", action="store_true", help="actually add notes (default: dry run)")
    ap.add_argument("--inspect", action="store_true", help="print vocab.db schema/sample rows and exit")
    args = ap.parse_args()

    db_path = find_vocab_db(args.kindle_path)

    if args.inspect:
        inspect(db_path)
        return

    fields = anki("modelFieldNames", modelName=MODEL)
    print(f"Target model {MODEL!r} has fields: {fields}")

    state = load_state()
    lookups = fetch_new_lookups(db_path, args.lang, state["last_timestamp"])
    print(f"{len(lookups)} new {args.lang!r} lookups since last sync")

    added, skipped = 0, 0
    max_timestamp = state["last_timestamp"]

    for row in lookups:
        word, stem, usage, ts, title = (
            row["word"], row["stem"], row["usage"], row["timestamp"], row["title"],
        )
        max_timestamp = max(max_timestamp, ts)

        if not usage:
            skipped += 1
            log_skip(word, stem, "(no usage sentence captured)", title or "")
            continue

        if is_duplicate(stem or word):
            skipped += 1
            log_skip(word, stem, usage, title or "")
            continue

        print(f"  + {word}  ({title or 'unknown source'})")
        if args.apply:
            anki(
                "addNote",
                note={
                    "deckName": DECK,
                    "modelName": MODEL,
                    "fields": {
                        "Palabra": word,
                        "Oración": usage,
                        "Definición": "",
                        "Fuente": title or "",
                    },
                    "tags": ["kindle-import"],
                },
            )
        added += 1

    print(f"\n{added} to add, {skipped} skipped as duplicates (see {SKIP_LOG})")
    if not args.apply:
        print("Dry run - re-run with --apply to actually add notes.")
    else:
        state["last_timestamp"] = max_timestamp
        save_state(state)
        print(f"Note: Definición is left blank - fill it in yourself in Anki's browser.")


if __name__ == "__main__":
    main()
