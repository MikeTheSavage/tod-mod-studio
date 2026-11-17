# Translations

Every word of the interface is in `en.json`: one flat list, `"key": "English text"`. The code asks for a word with `t('key')`
(`tr('key')` in files that already use the name `t` for something else). `{name}` in a text is filled in by the code (`t('key', { name: 'Ram' })`).

## Adding a language

1. Copy `en.json` to `<code>.json` (for example `es.json`).
2. Translate the values. Never change a key. Keep every `{name}` exactly as it is. A key you leave out shows the English text.
3. In `src/i18n.js` import the file, add it to `CATALOGUES` and add `{ code: 'es', name: 'Español' }` to `LANGUAGES`.
   The language list in Settings then offers it. Nothing is machine-translated: a language is only added once a person has translated and read it.
4. Run `npm test` from `frontend`: it checks that every key used by the code exists.

## Keeping the list up to date

New screens are written with plain English first. Then run

    node tools/i18n_extract.mjs            # shows what would move
    node tools/i18n_extract.mjs --apply    # moves it into en.json and puts t('key') in the screen

The tool only touches text between tags, plain-string titles, labels and placeholders, and the plain-string arguments of `say()` and `confirm()`.
Text that is built from variables stays in the code and is listed in the report. After a merge conflict in a screen, take the other side and run the tool again.
The guide (`guide/TOD Mod Studio Guide.html`) is a separate document and is translated as its own file.
