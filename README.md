# xcstrings-cli

A command-line tool for inspecting and editing Xcode String Catalog (`.xcstrings`) files without opening Xcode. Stdlib-only Python 3.9+.

## Usage

```
./xcstrings-cli <command> [args] [--file PATH]
```

`--file` is optional — if omitted, the tool searches the current directory recursively for the first `*.xcstrings` file.

Commands: `list`, `get`, `find-key`, `find-value`, `total-key-count`, `total-language-count` (read-only), and `add`, `update`, `delete` (which rewrite the file in Xcode's own format so diffs stay clean).

```
./xcstrings-cli list --missing fr
./xcstrings-cli get cancelButton
./xcstrings-cli add cancelButton --value 'Cancel'
./xcstrings-cli update cancelButton --lang fr --value 'Annuler'
```

Run `./xcstrings-cli --full-help` for the full command reference and format notes.

## Testing

```
python3 -m unittest test_xcstrings_cli.py -v
```
