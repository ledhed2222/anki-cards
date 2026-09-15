# spanish-vocab

Anki note types for Spanish vocabulary. See README.md for the design rationale,
field semantics, and the recognition-vs-production workflow. This file covers
only what's easy to break.

## The output is paste-into-Anki text, not a running app

Nothing here is served, bundled, or imported. Each file's contents get pasted
into a textarea in Anki's card template editor. So:

- No build step beyond `./build.sh`, which only concatenates. Don't introduce
  a bundler or a package manager for runtime deps — there's no compatibility
  gap to transpile for for (WKWebView runs ES2015+ natively), so authoring
  in modern syntax and shipping the same file is strictly better than adding
  a build step whose output you can't easily debug on-device.
- `shared/script.js` must stay self-contained: no imports/ES modules (nothing
  bundles it — it's pasted as one `<script>` block that also runs on desktop
  Anki's Qt WebEngine), no optional chaining, no arrow functions in the hot
  path. `let`/`const` are fine and preferred over `var` — both run natively on
  every Anki target.
- **The IIFE wrapper is load-bearing, not stylistic.** `build.sh` embeds this
  script directly in a `<script>` tag in every front template (and in
  `produccion/2-produccion`'s back, which can't inherit it — see below). A
  recognition-style back uses `{{FrontSide}}`, which carries the front's
  rendered HTML — script tag included — into the back's DOM, so the script
  runs again there too. Same for the next card. None of this is a full page
  reload; the document persists across the whole review session. Confirmed by
  testing real `<script>` re-injection into one live document: a bare
  top-level `let`/`const` throws `SyntaxError: Identifier already declared`
  the second time the script runs, because classic (non-module) top-level
  `let`/`const` bindings live in the page's shared global lexical environment,
  not a per-`<script>`-tag scope. `var` doesn't have this problem (redeclaring
  is a no-op), which is why the file used to be all-`var` — the IIFE is what
  makes `let`/`const` safe here, by giving each execution its own fresh
  function scope. Never flatten the top-level wrapper away.
- Anki does not officially support JavaScript in templates. Prefer boring,
  widely-supported DOM APIs over anything recent.

## Single source of truth

`shared/styling.css` and `shared/script.js` are the only copies.
`./build.sh` copies `styling.css` verbatim into each note type's
`dist/<notetype>.styling.css` (pure CSS, pastes into the Styling tab), and
embeds `script.js` directly into every front template's `dist/*.front.html`
(and into `produccion/2-produccion`'s back — see the IIFE note above for
why). Never edit a file in `dist/` — it's regenerated. Never fork the script
per note type; the mode is passed in from the template via `data-modo`.

## The script's contract with the templates

The script needs exactly three things and looks at nothing else:

1. an element with `id="oracion"` holding the sentence
2. an element with `id="palabra"` holding `{{text:Palabra}}`
3. `data-modo="produccion"` on the sentence div — production FRONT only

Adding fields or markup to a template is safe. Renaming those ids, or dropping
`{{text:` in favor of a bare field reference, is not.

## Hard constraints

- **The production back must not use `{{FrontSide}}`.** It would carry
  `data-modo` and the already-blanked markup across, hiding the answer. It
  renders `{{Oración}}` fresh. The recognition back may use `{{FrontSide}}`.
- **The hand-bold guard must stay conditional on mode.** `if (!oculto &&
  host.querySelector("b, strong")) return;` — dropping the `!oculto` makes a
  hand-bolded sentence render the answer in plain sight on a production card.
  That's the one silent, high-cost failure in this repo.
- **No lookbehind in regexes.** Safari only gained it in 16.4; AnkiMobile runs
  in WKWebView. The leading `(^|[^LETTER])` is a consumed prefix on purpose.
- **No `\b`.** It's ASCII-only in JS and mis-handles `frenó`. Word boundaries
  use the explicit accented Latin range in `LETTER`.
- **No `innerHTML` replacement on the sentence.** The script walks text nodes
  via `TreeWalker` so it cannot corrupt tags or attributes in `Oración`.
- **Field names are accented** (`Oración`, `Definición`). Template references
  must match exactly, with precomposed characters, not combining accents.

## Tests

`npm install && npm test` from the repo root. Any change to `shared/script.js`
should keep all 17 green and usually add a case. jsdom is not WKWebView, so
green tests are necessary but not sufficient — real changes get verified on
iOS before bulk-converting notes.
