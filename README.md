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

Tool versions and every script live in `mise.toml`. Install
[mise](https://mise.jdx.dev), then from the repo root:

```
mise install       # node, python, basedpyright
mise run install   # npm dev dependencies
mise run test
```

`mise tasks` lists the rest (`lint`, `lint:fix`, `format`, `typecheck`,
`build`, `kindle`). Arguments after `--` pass through, e.g.
`mise run kindle -- --apply`.

`package.json` at the root holds dev dependencies shared across collections.
