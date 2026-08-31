# xcstrings-cli

A command-line tool for inspecting and editing Xcode String Catalog (`.xcstrings`) files without opening Xcode. Stdlib-only Python 3.9+.

## Install

```
brew tap charlieschmidt/tap
brew install xcstrings-cli
```

## Usage

```
xcstrings-cli <command> [args] [--file PATH]
```

`--file` is optional — if omitted, the tool searches the current directory recursively for the first `*.xcstrings` file.

Commands: `list-keys`, `get-key`, `find-key`, `find-value`, `get-source-language`, `count-keys`, `count-key-languages` (read-only), and `add-key`, `update-key`, `delete-key` (which rewrite the file in Xcode's own format so diffs stay clean).

```
xcstrings-cli list-keys --missing fr
xcstrings-cli get-key cancelButton
xcstrings-cli add-key cancelButton --value 'Cancel'
xcstrings-cli update-key cancelButton --lang fr --value 'Annuler'
```

Run `xcstrings-cli --full-help` for the full command reference and format notes.

## Testing

```
python3 -m unittest test_xcstrings_cli.py -v
```
