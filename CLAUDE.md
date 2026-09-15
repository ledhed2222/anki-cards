# anki-cards

A collection of Anki note-type definitions. Each subdirectory is one
self-contained collection: its own fields, templates, shared CSS/JS, build
script, tests, and `CLAUDE.md` with the specifics for that collection.

- **spanish-vocab/** — Spanish vocabulary note types (recognition +
  production). See `spanish-vocab/CLAUDE.md` and `spanish-vocab/README.md`.

## Adding a new collection

Give it its own top-level directory, mirroring `spanish-vocab/`'s shape:
`shared/` for CSS/JS common across its note types, one directory per note
type, a `build.sh` that assembles paste-ready output into a `dist/` (gitignored)
inside that directory, and its own `CLAUDE.md` for anything easy to break.
Don't add cross-collection shared code unless two collections actually need
the same script — collections are independent by default.

## HTML style

Always write void/self-closing tags explicitly closed: `<hr />`, `<br />`,
not the bare `<hr>` / `<br>`. Applies to every collection's templates.

## Repo-wide tooling

`package.json` at the root holds shared dev dependencies (`jsdom` for
`spanish-vocab`'s tests, plus eslint/prettier/stylelint) so collections don't
each need their own `node_modules`. `npm test` runs whichever collection's
suite is wired into the `test` script — check `package.json` for the current
target.

`npm run lint` / `npm run format` apply the `@ledhed2222/eslint-config`,
`@ledhed2222/prettier-config`, and `@ledhed2222/stylelint-config` presets
(configured in `eslint.config.js`, the `prettier` field in `package.json`,
and `.stylelintrc.json`)
to hand-written JS/CSS — currently `spanish-vocab/shared/script.js`,
`spanish-vocab/shared/styling.css`, `spanish-vocab/test/run.js`.

**Never run a formatter/linter `--fix` across the `.front.html` / `.back.html`
template fragments.** They're not full HTML documents — they contain Anki's
`{{Field}}` / `{{#Cond}}...{{/Cond}}` mustache syntax mixed into markup, and
Prettier's HTML printer isn't mustache-aware: it treats `{{...}}` as plain
text and can reflow whitespace around it (confirmed: it merged the blank line
between `{{/Fuente}}` and `{{#Notas}}` onto one line). Harmless in that one
case, but not something to trust blindly on more complex templates. Hand-edit
templates; only run tooling on `shared/script.js` and `shared/styling.css`.

`.stylelintrc.json` overrides `selector-class-pattern` to allow `nightMode`
and `night_mode` alongside kebab-case — those two are Anki's own night-mode
marker classes (desktop Anki adds `.nightMode`, older/AnkiDroid convention
uses `.night_mode`), not ours to rename to satisfy a lint rule.

`htmlhint-config-lint spanish-vocab` (also run as part of `npm run lint`)
lints the `.front.html`/`.back.html` templates with
`@ledhed2222/htmlhint-config`'s bundled CLI — this is a real check on the
templates, not a `--fix`, so the mustache-syntax risk above doesn't apply;
it only reports, never rewrites. It walks the directory recursively and
already skips `dist/` and `node_modules` on its own (see the package's
README for the `--ignore` flag if a future collection needs more).

