# anki-cards

Anki note-type definitions, kept as paste-into-Anki HTML/CSS/JS rather than
anything served or bundled. One directory per collection.

## Collections

- [`spanish-vocab/`](spanish-vocab/README.md) — Spanish vocabulary, recognition
  and production note types.

## Adding a collection

Copy the shape of `spanish-vocab/`: a `shared/` for its CSS/JS, one directory
per note type, a `build.sh`, a `test/`, and its own `README.md` and
`CLAUDE.md`. See the root `CLAUDE.md` for the constraints that apply
repo-wide.

## Tooling

```
npm install
npm test
```

`package.json` at the root holds dev dependencies shared across collections.
