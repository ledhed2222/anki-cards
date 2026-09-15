import baseConfig from '@ledhed2222/eslint-config'
import globals from 'globals'

export default [
  { ignores: ['**/node_modules/**', '**/dist/**'] },
  ...baseConfig,
  // This repo never publishes ES modules — the named-export discipline the
  // base config enforces for the shared package ecosystem doesn't apply
  // here. Off for every implementation file, not per-file.
  {
    files: ['**/*.js'],
    rules: {
      'import/no-default-export': 'off',
    },
  },
  // Source: pasted into Anki's WKWebView as a plain <script> tag, never
  // bundled or run through Node — browser globals, classic (non-module)
  // parsing. Applies to every collection's shared/*.js, not just this one.
  {
    files: ['**/shared/**/*.js'],
    languageOptions: {
      sourceType: 'script',
      globals: globals.browser,
    },
  },
  // Tests: run directly under Node.
  {
    files: ['**/test/**/*.js'],
    languageOptions: {
      globals: globals.node,
    },
  },
]
