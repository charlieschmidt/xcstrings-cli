# xcstringstool

A command-line tool for inspecting and editing Xcode String Catalog (`.xcstrings`) files without opening Xcode. Stdlib-only Python 3.9+.

## Usage

```
./xcstringstool.py <command> [args] [--file PATH]
```

`--file` is optional — if omitted, the tool searches the current directory recursively for the first `*.xcstrings` file.

Commands: `list`, `get`, `find-key`, `find-value`, `total-key-count` (read-only), and `add`, `update`, `delete` (which rewrite the file in Xcode's own format so diffs stay clean).

```
./xcstringstool.py list --missing fr
./xcstringstool.py get cancelButton
./xcstringstool.py add cancelButton --value 'Cancel'
./xcstringstool.py update cancelButton --lang fr --value 'Annuler'
```

See [XCSTRINGSTOOL.md](XCSTRINGSTOOL.md) for full command reference and format notes.

## Testing

```
python3 -m unittest test_xcstringstool.py -v
```
