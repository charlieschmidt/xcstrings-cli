# xcstringstool.py

**Use this tool, not ad-hoc Python, to inspect or edit an `.xcstrings` file.** It's already executable with the interpreter in its shebang — run `xcstringstool.py ...`, not `python3 xcstringstool.py ...`.

CLI for reading/editing an Xcode String Catalog (`Canopy/Localizable.xcstrings` in this project) without Xcode. Stdlib-only Python 3.9+.

```
xcstringstool.py <command> [args] [--file PATH]
```

`--file` is optional: omitted, it recursively searches the cwd for the first `*.xcstrings` file, skipping dot-directories (`.git`, `.claude`, etc.) so stale worktree/cache copies aren't picked up. Errors out if none found. `list`/`get`/`find-key`/`find-value`/`total-key-count` are read-only. `add`/`update`/`delete` rewrite the whole file in Xcode's own format (alphabetical keys, 2-space indent) so diffs stay clean.

## Commands

| Command | Purpose | Key flags | Example |
|---|---|---|---|
| `list` | List keys | `--lang LANG` (has localization), `--missing LANG` (lacks one), `--state {new,needs_review,translated}` | `list --missing fr` |
| `get KEY` | Show one entry | `--lang LANG` (one language only), `--json` (raw JSON) | `get cancelButton --lang fr` |
| `find-key TEXT` | Case-insensitive substring search over keys, printing one match per line; if `TEXT` contains `* ? [`, it's a glob pattern matched against the whole key instead (e.g. `shared*lant*`) | `--case-sensitive` | `find-key 'shared*lant*'` |
| `find-value TEXT` | Same search, over localization values instead of keys; prints `key  (lang/category: 'value')` per match | `--lang LANG`, `--case-sensitive` | `find-value Annuler --lang fr` |
| `total-key-count` | Print number of keys in catalog | — | `total-key-count` |
| `add KEY` | Create a new entry (errors if key exists) | `--value STR` (simple string) *or* `--plural CATEGORY=VALUE` (repeatable, mutually exclusive with `--value`), `--lang` (default `en`), `--state {new,needs_review,translated}` (default `translated`), `--extraction-state` (default `manual`), `--comment` | `add cancelButton --value 'Cancel'` |
| `update KEY` | Modify an existing entry (errors if key missing); pass only the fields you want to change | `--value STR` *or* `--plural CATEGORY=VALUE` (repeatable), `--lang` (default `en`), `--state {new,needs_review,translated}` (no default — omit to leave state unchanged), `--comment` (no `--extraction-state`) | `update cancelButton --lang fr --value 'Annuler'` |
| `delete KEY` | Remove an entry, or one language from it | `--lang LANG` (omit to delete the whole entry) | `delete cancelButton --lang fr` |

Plural categories are CLDR: `zero one two few many other` (not all apply to every language); pass one `--plural cat=value` per category. `update --plural other='...'` touches only that category, leaving others untouched.

## Format notes

Each entry's `localizations[lang]` is either `{"stringUnit": {"state", "value"}}` (plain string) or `{"variations": {"plural": {category: {"stringUnit": {...}}}}}`. `state` progresses `new` → `needs_review` → `translated`. Entries also carry `extractionState` (always `manual` in this project) and an optional translator `comment`.

## Testing

```
python3 -m unittest test_xcstringstool.py -v
```
Covers every subcommand against a fixture catalog plus a byte-for-byte round-trip check against `Canopy/Localizable.xcstrings` to confirm output formatting matches Xcode's own.
