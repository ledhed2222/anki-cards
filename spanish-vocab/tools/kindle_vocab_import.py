#!/usr/bin/env python3
"""
Import Spanish word lookups from a physical Kindle's Vocabulary Builder into
Español Reconocimiento notes. Read-only against the Kindle - it only ever
reads vocab.db off the mounted device, never writes to it.

    mise run kindle -- --inspect
    mise run kindle -- --limit 20          # small dry run
    mise run kindle                        # full dry run
    mise run kindle -- --apply

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
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPResponse
from typing import NamedTuple, cast

_LETTER = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
_HTML_TAG = re.compile(r"<[^>]+>")

_ANKI_URL = "http://127.0.0.1:8765"
_DECK = "Vocabulario español"
_MODEL = "Español Reconocimiento"
_STATE_DIR = os.path.expanduser("~/.anki-cards")
_STATE_FILE = os.path.join(_STATE_DIR, "kindle_vocab_state.json")
_SKIP_LOG = os.path.join(_STATE_DIR, "kindle_vocab_skipped.log")

_GLOSS_MODEL = "sonnet"
_BATCH_SIZE = 50
_PARALLEL_CALLS = 4
_GLOSS_PROMPT = """\
You are given a JSON list of Spanish words, each with the sentence it was
read in. For each, give a short English gloss (2-6 words) for the sense used
in that sentence, in the same part of speech as the word as it appears there
(an adjective gets an adjective gloss). Don't label the part of speech.
Reply with ONLY one line per word: its id, a tab, then the gloss. No other
text."""


class _Lookup(NamedTuple):
    word: str
    stem: str | None
    usage: str | None
    timestamp: int
    title: str | None


class _Args(argparse.Namespace):
    kindle_path: str = "/Volumes/Kindle"
    lang: str = "es"
    limit: int = 0
    apply: bool = False
    inspect: bool = False
    no_definitions: bool = False


def _anki(action: str, **params: object) -> object:
    payload = json.dumps({"action": action, "version": 6, "params": params})
    req = urllib.request.Request(
        _ANKI_URL, data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with cast(HTTPResponse, urllib.request.urlopen(req, timeout=30)) as r:
            body = cast(dict[str, object], json.loads(r.read().decode("utf-8")))
    except urllib.error.URLError as e:
        sys.exit(f"Can't reach AnkiConnect at {_ANKI_URL} - is Anki running?\n  {e}")
    if body.get("error"):
        raise RuntimeError(body["error"])
    return body["result"]


def _find_vocab_db(kindle_path: str) -> str:
    path = os.path.join(kindle_path, "system", "vocabulary", "vocab.db")
    if not os.path.exists(path):
        sys.exit(f"No vocab.db at {path} - is the Kindle plugged in and mounted "
                 + f"at {kindle_path}? Use --kindle-path to point elsewhere.")
    return path


def _load_last_timestamp() -> int:
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE, encoding="utf-8") as f:
            return cast(dict[str, int], json.load(f))["last_timestamp"]
    return 0


def _save_last_timestamp(timestamp: int) -> None:
    os.makedirs(_STATE_DIR, exist_ok=True)
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_timestamp": timestamp}, f)


def _inspect(db_path: str) -> None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    for table in ("WORDS", "LOOKUPS", "BOOK_INFO"):
        print(f"\n=== {table} ===")
        info = cast(list[tuple[object, ...]], conn.execute(f"PRAGMA table_info({table})").fetchall())
        print("columns:", [row[1] for row in info])
        sample = cast(list[tuple[object, ...]], conn.execute(f"SELECT * FROM {table} LIMIT 3").fetchall())
        for row in sample:
            print(" ", row)
    conn.close()


def _fetch_new_lookups(db_path: str, lang: str, since_timestamp: int) -> list[_Lookup]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = cast(
        list[tuple[str, str | None, str | None, int, str | None]],
        conn.execute(
            """
            SELECT w.word, w.stem, l.usage, l.timestamp, b.title
            FROM LOOKUPS l
            JOIN WORDS w ON w.id = l.word_key
            LEFT JOIN BOOK_INFO b ON b.id = l.book_key
            WHERE w.lang = ? AND l.timestamp > ?
            ORDER BY l.timestamp ASC
            """,
            (lang, since_timestamp),
        ).fetchall(),
    )
    conn.close()
    return [_Lookup(*row) for row in rows]


def _fetch_deck_words() -> set[str]:
    """Every whole word occurring anywhere in the deck, fetched once (2
    AnkiConnect calls total) rather than one findNotes round-trip per word.
    AnkiConnect can't handle concurrent requests (a single-threaded local
    server - tested directly, concurrent calls get connection-reset), and at
    ~120ms per call that's minutes for a few thousand words sequentially.
    Tokenizing the whole deck's text locally and checking set membership is
    the same "does this whole word appear anywhere in the note" semantics as
    Anki's own `w:` search, just ~1500x faster for a bulk run like this."""
    ids = cast(list[int], _anki("findNotes", query=f'deck:"{_DECK}"'))
    notes = cast(
        list[dict[str, dict[str, dict[str, str | None]]]],
        _anki("notesInfo", notes=ids) if ids else [],
    )
    words: set[str] = set()
    for n in notes:
        for f in n["fields"].values():
            text = _HTML_TAG.sub("", f["value"] or "")
            words.update(w.lower() for w in cast(list[str], _LETTER.findall(text)))
    return words


def _claude_glosses(batch: list[_Lookup]) -> tuple[list[str], float]:
    """One `claude -p` call for a batch of (word, sentence) pairs. The
    sentence is what makes the gloss right: a context-blind lookup picks the
    first dictionary sense ('bochorno' -> 'hot summer wind' where the book
    meant 'embarrassment'). A bare `claude -p` loads the full Claude Code
    context (~44k tokens of CLAUDE.md, hooks, plugins, MCP tools) on the
    default model, ~$0.29 per call; these flags strip all of that.

    Fails the whole run on any error, before anything is added: skipping
    the batch would still advance last_timestamp past its words, losing
    them. Returns glosses aligned with `batch`, "" where one is missing."""
    items = [{"id": str(i), "word": r.word, "sentence": r.usage}
             for i, r in enumerate(batch)]
    try:
        result = subprocess.run(
            ["claude", "-p", json.dumps(items, ensure_ascii=False),
             "--model", _GLOSS_MODEL,
             "--setting-sources", "",
             "--strict-mcp-config",
             "--disable-slash-commands",
             "--tools", "",
             "--no-session-persistence",
             "--output-format", "json",
             "--system-prompt", _GLOSS_PROMPT],
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired as e:
        sys.exit(f"claude batch failed, nothing added: {e}")
    try:
        envelope = cast(dict[str, object], json.loads(result.stdout, strict=False))
        reply = cast(str, envelope["result"])
    except (ValueError, KeyError) as e:
        sys.exit(f"claude batch failed, nothing added: {e}\n"
                 + (result.stdout + result.stderr)[:2000])
    # Tab-separated, not JSON: a gloss with a quote in it broke the JSON
    # reply and failed a whole run.
    by_id: dict[str, str] = {}
    for line in reply.splitlines():
        if "\t" in line:
            key, gloss = line.strip().split("\t", 1)
            by_id[key] = gloss.strip()
    cost = cast(float | None, envelope.get("total_cost_usd")) or 0.0
    return [by_id.get(str(i), "") for i in range(len(batch))], cost


def _fetch_glosses(rows: list[_Lookup]) -> list[str]:
    batches = [rows[i:i + _BATCH_SIZE] for i in range(0, len(rows), _BATCH_SIZE)]
    glosses: list[str] = []
    cost = 0.0
    with ThreadPoolExecutor(_PARALLEL_CALLS) as pool:
        for got, c in pool.map(_claude_glosses, batches):
            glosses.extend(got)
            cost += c
    print(f"{len(batches)} claude call(s), ${cost:.4f}")
    return glosses


def _log_skip(reason: str, row: _Lookup) -> None:
    os.makedirs(_STATE_DIR, exist_ok=True)
    usage = row.usage or "(no usage sentence captured)"
    with open(_SKIP_LOG, "a", encoding="utf-8") as f:
        _ = f.write(f"{reason}\t{row.word}\t{row.stem}\t{row.title or ''}\t{usage}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    _ = ap.add_argument("--kindle-path")
    _ = ap.add_argument("--lang")
    _ = ap.add_argument("--limit", type=int, help="max lookups to process (0 = all)")
    _ = ap.add_argument("--apply", action="store_true", help="actually add notes (default: dry run)")
    _ = ap.add_argument("--inspect", action="store_true", help="print vocab.db schema/sample rows and exit")
    _ = ap.add_argument("--no-definitions", action="store_true",
                        help="skip claude, leave Definición blank (free dry runs)")
    args = ap.parse_args(namespace=_Args())

    db_path = _find_vocab_db(args.kindle_path)

    if args.inspect:
        _inspect(db_path)
        return

    fields = _anki("modelFieldNames", modelName=_MODEL)
    print(f"Target model {_MODEL!r} has fields: {fields}")

    deck_words = _fetch_deck_words()
    print(f"{len(deck_words)} distinct words already in {_DECK!r}")

    last_timestamp = _load_last_timestamp()
    lookups = _fetch_new_lookups(db_path, args.lang, last_timestamp)
    print(f"{len(lookups)} new {args.lang!r} lookups since last sync")
    if args.limit:
        lookups = lookups[:args.limit]
        print(f"(limited to first {len(lookups)})")

    added = 0
    skip_counts = {"no_usage": 0, "duplicate": 0, "no_definition": 0}
    max_timestamp = last_timestamp

    seen_this_run: set[str] = set()
    candidates: list[_Lookup] = []

    for row in lookups:
        max_timestamp = max(max_timestamp, row.timestamp)

        if not row.usage:
            skip_counts["no_usage"] += 1
            _log_skip("no_usage", row)
            continue

        key = (row.stem or row.word).lower()

        if key in seen_this_run:
            skip_counts["duplicate"] += 1
            _log_skip("duplicate_in_batch", row)
            continue

        if key in deck_words:
            skip_counts["duplicate"] += 1
            _log_skip("duplicate_in_anki", row)
            continue

        seen_this_run.add(key)
        candidates.append(row)

    if args.no_definitions:
        glosses = [""] * len(candidates)
    else:
        glosses = _fetch_glosses(candidates)

    for row, definicion in zip(candidates, glosses):
        if not args.no_definitions and not definicion:
            skip_counts["no_definition"] += 1
            _log_skip("no_definition", row)
            continue

        print(f"  + {row.word} = {definicion or '(skipped)'}  ({row.title or 'unknown source'})")
        if args.apply:
            try:
                _ = _anki(
                    "addNote",
                    note={
                        "deckName": _DECK,
                        "modelName": _MODEL,
                        "fields": {
                            "Lema": row.stem or row.word,
                            "Palabra": row.word,
                            "Oración": row.usage,
                            "Definición": definicion,
                            "Fuente": row.title or "",
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
                _log_skip("duplicate_in_anki", row)
                continue
        added += 1

    total_skipped = sum(skip_counts.values())
    print(f"\n{added} to add, {total_skipped} skipped "
          + f"({skip_counts['duplicate']} duplicate, {skip_counts['no_usage']} no usage sentence, "
          + f"{skip_counts['no_definition']} no definition found) "
          + f"- see {_SKIP_LOG}")
    if args.apply:
        _save_last_timestamp(max_timestamp)
        if args.no_definitions:
            print("Note: Definición is left blank - fill it in yourself in Anki's browser.")
    else:
        print("Dry run - re-run with --apply to actually add notes.")


if __name__ == "__main__":
    main()
