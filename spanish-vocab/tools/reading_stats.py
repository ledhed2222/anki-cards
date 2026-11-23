#!/usr/bin/env python3
"""
Per-book lookup density for the "Spanish Reading Tracker" Google Sheet,
from a USB-mounted Kindle. Read-only against the Kindle.

    mise run reading-stats -- --sheet sheet.json > plan.json

`--sheet` is the Books tab as JSON: {"values": [[row 1], [row 2], ...],
"notes": {"B": ["note on B1", ...], "F": ["note on F1", ...]}}. This script
never talks to Google itself - a Claude Code session reads the sheet with
its Sheets connector, runs this, shows the plan, then writes it. stdout is
the plan (JSON); a human-readable table goes to stderr.

Columns written: E (lookups), F (words), B (status, inferred), C (finished
date, only when empty), plus "[auto]" notes on B (when the status inference
isn't certain) and F (which estimates went into the word count). F is only
written when empty or when its note shows this script wrote it, so a number
typed by hand is never touched. Never D (an ARRAYFORMULA lives in D2).

Word count is a weighted average of up to three estimates (see
_word_estimates), dropping any that disagree with the others by >15%.

Kindle data used:
- system/vocabulary/vocab.db: LOOKUPS joined to BOOK_INFO, grouped by ASIN
  (a re-downloaded book gets a new BOOK_INFO id with the same ASIN).
- documents/Downloads/Items01/*_<ASIN>*.sdr/*.yjr|*.yjf: Amazon's KRDS
  binary format. `fpr` = furthest position read; `book.info.store` and
  `timer.model` each hold (words turned past, fraction of book) - their
  ratio is the book's word count, and the two agree within ~0.3%.
  `EndActions` exists only if you interacted with the end-of-book screen.
- *.sdr/StartActions.data.<ASIN>.asc: Amazon's "typical time to read" and
  series position.

Status is a heuristic, not a fact - see _infer_status. Verified 2026-11-22
against 9 books with known status; the book's real length in positions is
only inside the DRM'd .kfx, so "finished" from position alone is +/-5%.
Goodreads shelf RSS would be the real source (issue #18).

Lookups made in the Kindle iOS app aren't in vocab.db, so books read partly
on the phone undercount.
"""

import argparse
import datetime
import glob
import json
import os
import re
import sqlite3
import struct
import sys
import unicodedata
from dataclasses import dataclass
from typing import cast

# Junk BOOK_INFO entries (lookups from books never actually read).
_IGNORED_ASINS = {"B0196BMYHK"}

# Below this fraction read, words/fraction is dominated by one page's
# density (Piedra filosofal: 222 words / 0.0034 gave 65k, ~27% low).
_MIN_FRACTION_FOR_WORDS = 0.02

# Amazon's reading-time estimate is word count at a fixed rate; calibrated
# against the Kindle's own word counts for 4 books (264-269 wpm), but 13%
# high for Morel.
_AMAZON_WPM = 264

# Positions per word at the end of finished books ranged 5.30-5.73. The max
# errs toward "not finished" for the status heuristic; the mean is the best
# guess for turning a finished book's furthest position into words.
_POSITIONS_PER_WORD = 5.73
_MEAN_POSITIONS_PER_WORD = 5.60

_WEIGHTS = {"kindle": 3, "amazon": 2, "position": 1}
# Just above the largest real disagreement seen (Morel: 13%).
_MAX_DISAGREEMENT = 0.15
_FINISHED_PERCENT = 0.90
_NOT_STARTED_PERCENT = 0.02
_STALE_DAYS = 60

_NOTE_PREFIX = "[auto] "
_COLUMNS = "ABCDEFGHIJ"


@dataclass
class _Book:
    asin: str
    title: str
    author: str
    lookups: int
    first_lookup: datetime.date | None
    last_lookup: datetime.date | None
    fpr: int | None
    end_actions: bool
    kindle_words: int | None
    amazon_minutes: int | None
    series: tuple[str, int] | None
    last_activity: datetime.date | None


class _Args(argparse.Namespace):
    kindle_path: str = "/Volumes/Kindle"
    sheet: str = ""


def _date(ms: int) -> datetime.date:
    return datetime.date.fromtimestamp(ms / 1000)


def _krds_tokens(data: bytes) -> list[object]:
    """Flat token stream of a KRDS file: scalars, plus ("BEGIN", name) and
    ("END",) markers around named objects."""
    out: list[object] = []
    i = 8  # signature

    def utf() -> str | None:
        nonlocal i
        is_null = data[i]
        i += 1
        if is_null:
            return None
        n = struct.unpack(">H", data[i:i + 2])[0]
        i += 2
        s = data[i:i + n].decode("utf-8", "replace")
        i += n
        return s

    sizes = {0x01: (">i", 4), 0x02: (">q", 8), 0x04: (">d", 8),
             0x05: (">h", 2), 0x06: (">f", 4)}
    while i < len(data):
        t = data[i]
        i += 1
        if t == 0x00 or t == 0x07:
            out.append(data[i])
            i += 1
        elif t in sizes:
            fmt, n = sizes[t]
            out.append(cast(object, struct.unpack(fmt, data[i:i + n])[0]))
            i += n
        elif t == 0x03:
            out.append(utf())
        elif t == 0xFE:
            out.append(("BEGIN", utf()))
        elif t == 0xFF:
            out.append(("END",))
        else:
            break  # unknown type: stop rather than misread the rest
    return out


def _krds_values(tokens: list[object], name: str) -> list[list[object]]:
    """Scalars directly following each object named `name`."""
    found: list[list[object]] = []
    for i, t in enumerate(tokens):
        if t == ("BEGIN", name):
            vals: list[object] = []
            for u in tokens[i + 1:i + 8]:
                if isinstance(u, tuple):
                    break
                vals.append(u)
            found.append(vals)
    return found


def _position(v: object) -> int | None:
    if isinstance(v, str) and ":" in v:
        return int(v.rsplit(":", 1)[1])
    return None


def _sidecar(items: str, asin: str) -> tuple[int | None, bool, int | None, datetime.date | None]:
    """(fpr, has EndActions, Kindle word count, last page-history date)."""
    fpr: int | None = None
    end_actions = False
    words: list[tuple[float, int]] = []
    history: list[datetime.date] = []
    for path in glob.glob(f"{items}/*_{asin}*.sdr/*.yj[rf]*"):
        with open(path, "rb") as f:
            tokens = _krds_tokens(f.read())
        for vals in _krds_values(tokens, "fpr"):
            pos = _position(vals[0]) if vals else None
            if pos is not None:
                fpr = max(fpr or 0, pos)
        end_actions = end_actions or bool(_krds_values(tokens, "EndActions"))
        for vals in _krds_values(tokens, "book.info.store"):
            if len(vals) >= 2 and isinstance(vals[0], int) and isinstance(vals[1], float):
                words.append((vals[1], vals[0]))
        for vals in _krds_values(tokens, "timer.model"):
            if len(vals) >= 4 and isinstance(vals[2], int) and isinstance(vals[3], float):
                words.append((vals[3], vals[2]))
        for vals in _krds_values(tokens, "page.history.record"):
            if len(vals) >= 2 and isinstance(vals[1], int) and vals[1] > 10**11:
                history.append(_date(vals[1]))
    usable = [(frac, n) for frac, n in words if frac >= _MIN_FRACTION_FOR_WORDS]
    word_count = None
    if usable:
        frac, n = max(usable)
        word_count = round(n / frac)
    return fpr, end_actions, word_count, max(history) if history else None


def _start_actions(items: str, asin: str) -> tuple[int | None, tuple[str, int] | None]:
    for path in glob.glob(f"{items}/*_{asin}*.sdr/StartActions.data.{asin}.asc"):
        with open(path, encoding="utf-8") as f:
            data = cast(dict[str, dict[str, dict[str, object]]], json.load(f))["data"]
        rt = data.get("readingTime", {})
        minutes = cast(int, rt.get("hours", 0)) * 60 + cast(int, rt.get("minutes", 0))
        sp = data.get("seriesPosition", {})
        series = None
        if isinstance(sp.get("seriesName"), str) and isinstance(sp.get("positionInSeries"), int):
            series = (cast(str, sp["seriesName"]), cast(int, sp["positionInSeries"]))
        return minutes or None, series
    return None, None


def _load_books(kindle_path: str) -> list[_Book]:
    db = os.path.join(kindle_path, "system", "vocabulary", "vocab.db")
    items = os.path.join(kindle_path, "documents", "Downloads", "Items01")
    if not os.path.exists(db):
        sys.exit(f"No vocab.db at {db} - is the Kindle mounted?")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = cast(
        list[tuple[str, str, str, int, int | None, int | None]],
        conn.execute(
            """
            SELECT b.asin, MIN(b.title), MIN(b.authors), COUNT(l.id),
                   MIN(l.timestamp), MAX(l.timestamp)
            FROM BOOK_INFO b
            LEFT JOIN LOOKUPS l ON l.book_key = b.id
            WHERE lower(b.lang) LIKE 'es%'
            GROUP BY b.asin
            """
        ).fetchall(),
    )
    conn.close()
    books: list[_Book] = []
    for asin, title, author, n, first, last in rows:
        if asin in _IGNORED_ASINS:
            continue
        fpr, end_actions, words, history = _sidecar(items, asin)
        minutes, series = _start_actions(items, asin)
        last_lookup = _date(last) if last else None
        activity = [d for d in (last_lookup, history) if d]
        books.append(_Book(
            asin=asin, title=title, author=author, lookups=n,
            first_lookup=_date(first) if first else None, last_lookup=last_lookup,
            fpr=fpr, end_actions=end_actions, kindle_words=words,
            amazon_minutes=minutes, series=series,
            last_activity=max(activity) if activity else None,
        ))
    return books


def _percent(book: _Book) -> float | None:
    words = book.kindle_words or (book.amazon_minutes or 0) * _AMAZON_WPM
    if book.fpr is None or not words:
        return None
    return book.fpr / (words * _POSITIONS_PER_WORD)


def _infer_status(book: _Book, books: list[_Book], today: datetime.date) -> tuple[str, str]:
    """(status, note); an empty note means the inference is certain."""
    if book.end_actions:
        return "Finished", ""
    if book.series:
        name, pos = book.series
        for other in books:
            started = other.lookups > 0 or (_percent(other) or 0) >= _NOT_STARTED_PERCENT
            if other.series == (name, pos + 1) and started:
                return "Finished", ""
    pct = _percent(book)
    if book.lookups == 0 and (pct is None or pct < _NOT_STARTED_PERCENT):
        return "Up next", ""
    if pct is not None and pct >= _FINISHED_PERCENT:
        return "Finished", (f"Inferred: furthest position is ~{pct:.0%} of the estimated length "
                            + "(estimate is +/-5%). Fix the status by hand if this is wrong.")
    if book.last_activity and (today - book.last_activity).days > _STALE_DAYS:
        return "Reading", (f"Inferred: no activity on the Kindle since {book.last_activity}; "
                           + "possibly abandoned or finished on another device.")
    return "Reading", ""


def _word_estimates(book: _Book, finished: bool) -> dict[str, int]:
    """kindle: the Kindle's own words/fraction record. amazon: "typical time
    to read" x _AMAZON_WPM. position: furthest position / positions-per-word,
    only meaningful once the book is finished (furthest position ~ the end)."""
    out: dict[str, int] = {}
    if book.kindle_words:
        out["kindle"] = book.kindle_words
    if book.amazon_minutes:
        out["amazon"] = book.amazon_minutes * _AMAZON_WPM
    if finished and book.fpr:
        out["position"] = round(book.fpr / _MEAN_POSITIONS_PER_WORD)
    return out


def _combine(estimates: dict[str, int]) -> tuple[int | None, dict[str, int]]:
    """Weighted average after dropping outliers; returns (words, kept)."""
    if not estimates:
        return None, {}
    if len(estimates) >= 3:
        ref = sorted(estimates.values())[len(estimates) // 2]
    else:
        ref = estimates[max(estimates, key=lambda k: _WEIGHTS[k])]
    kept = {k: v for k, v in estimates.items() if abs(v - ref) / ref <= _MAX_DISAGREEMENT}
    total = sum(_WEIGHTS[k] for k in kept)
    return round(sum(v * _WEIGHTS[k] for k, v in kept.items()) / total), kept


def _estimate_note(estimates: dict[str, int], kept: dict[str, int], words: int) -> str:
    parts = [f"{k} {v:,}" + ("" if k in kept else " (dropped)") for k, v in estimates.items()]
    return f"Estimated word count {words:,} from: " + "; ".join(parts) + ". Weights kindle 3, amazon 2, position 1."


def _as_int(text: str) -> int | None:
    digits = text.replace(",", "").strip()
    return int(digits) if digits.isdigit() else None


def _normalize(title: str) -> str:
    title = re.sub(r"\([^)]*\)", "", title)
    title = re.sub(r":\s*\d+\s*$", "", title.strip())
    folded = unicodedata.normalize("NFKD", title.casefold())
    return re.sub(r"\s+", " ", "".join(c for c in folded if not unicodedata.combining(c))).strip()


def _clean_title(title: str) -> str:
    return re.sub(r":\s*\d+\s*$", "", re.sub(r"\s*\([^)]*\)", "", title)).strip()


def _author_name(authors: str) -> str:
    if "," in authors:
        last, first = authors.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return authors


def _cell(row: list[str], col: str) -> str:
    i = _COLUMNS.index(col)
    return row[i] if i < len(row) else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    _ = ap.add_argument("--kindle-path")
    _ = ap.add_argument("--sheet", required=True, help="Books tab as JSON (see module docstring)")
    args = ap.parse_args(namespace=_Args())

    with open(args.sheet, encoding="utf-8") as f:
        sheet = cast(dict[str, object], json.load(f))
    values = cast(list[list[str]], sheet["values"])
    sheet_notes = cast(dict[str, list[str]], sheet["notes"]) if "notes" in sheet else {}

    def existing_note(col: str, row_num: int) -> str:
        col_notes = sheet_notes.get(col, [])
        return col_notes[row_num - 1] if row_num - 1 < len(col_notes) else ""
    by_title = {_normalize(r[0]): i + 1 for i, r in enumerate(values) if i > 0 and r}

    today = datetime.date.today()
    books = _load_books(args.kindle_path)
    cells: list[dict[str, object]] = []
    notes: list[dict[str, str]] = []
    append: list[list[object]] = []

    for book in sorted(books, key=lambda b: b.first_lookup or datetime.date.max):
        row_num = by_title.get(_normalize(book.title))
        if row_num is None and book.lookups == 0:
            continue
        status, note = _infer_status(book, books, today)
        finished = str(book.last_activity) if status == "Finished" and book.last_activity else ""
        estimates = _word_estimates(book, status == "Finished")
        words, kept = _combine(estimates)
        words_note = _NOTE_PREFIX + _estimate_note(estimates, kept, words) if words else ""
        pct = _percent(book)
        print(f"{_clean_title(book.title)[:42]:42} lookups={book.lookups:4} "
              + f"{book.first_lookup or '-'}..{book.last_lookup or '-'} "
              + f"words={words or '-'} {estimates} ~{pct or 0:.0%} -> {status}"
              + (" (unsure)" if note else "")
              + ("" if row_num else "  [new row]"), file=sys.stderr)

        if row_num is None:
            append.append([_clean_title(book.title), status, finished, "", book.lookups,
                           words or "", "", _author_name(book.author)])
            new_row = len(values) + len(append)
            if note:
                notes.append({"a1": f"B{new_row}", "note": _NOTE_PREFIX + note})
            if words_note:
                notes.append({"a1": f"F{new_row}", "note": words_note})
            continue

        row = values[row_num - 1]
        if book.lookups and _as_int(_cell(row, "E")) != book.lookups:
            cells.append({"a1": f"E{row_num}", "value": book.lookups})
        f_ours = not _cell(row, "F") or existing_note("F", row_num).startswith(_NOTE_PREFIX)
        if words and f_ours:
            if _as_int(_cell(row, "F")) != words:
                cells.append({"a1": f"F{row_num}", "value": words})
            if existing_note("F", row_num) != words_note:
                notes.append({"a1": f"F{row_num}", "note": words_note})
        if _cell(row, "B") != status:
            cells.append({"a1": f"B{row_num}", "value": status})
        if finished and not _cell(row, "C"):
            cells.append({"a1": f"C{row_num}", "value": finished})
        existing = existing_note("B", row_num)
        if note:
            if existing != _NOTE_PREFIX + note:
                notes.append({"a1": f"B{row_num}", "note": _NOTE_PREFIX + note})
        elif existing.startswith(_NOTE_PREFIX):
            notes.append({"a1": f"B{row_num}", "note": ""})

    print("Lookups made in the Kindle iOS app aren't in vocab.db - books read "
          + "partly on the phone undercount.", file=sys.stderr)
    json.dump({"cells": cells, "notes": notes, "append": append}, sys.stdout,
              ensure_ascii=False, indent=1)
    print()


if __name__ == "__main__":
    main()
