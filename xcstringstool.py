#!/usr/bin/env python3
"""Command-line tool for reading and editing Xcode String Catalog (.xcstrings) files.

An .xcstrings file is JSON shaped like this:

    {
      "sourceLanguage": "en",
      "strings": {
        "someKey": {
          "extractionState": "manual",
          "localizations": {
            "en": {"stringUnit": {"state": "translated", "value": "Hello"}}
          }
        },
        "pluralKey": {
          "extractionState": "manual",
          "localizations": {
            "en": {
              "variations": {
                "plural": {
                  "one":   {"stringUnit": {"state": "translated", "value": "%1$(days)lld day ago"}},
                  "other": {"stringUnit": {"state": "translated", "value": "%1$(days)lld days ago"}}
                }
              }
            }
          }
        }
      },
      "version": "1.1"
    }

Each entry under "strings" is keyed by a symbol-style string key. Its value has
an "extractionState" (usually "manual" in this project), an optional
entry-level "comment", and a "localizations" map keyed by language code. Each
localization is either a plain "stringUnit" (a value + a state of "new",
"needs_review", or "translated"), or a "variations" -> "plural" map of plural
categories ("zero", "one", "two", "few", "many", "other"), each itself holding
a "stringUnit".

This tool exposes eight subcommands -- list, get, find-key, find-value, add,
update, delete, total-key-count -- for scripting edits to this format from
outside Xcode. See XCSTRINGSTOOL.md for a full worked example of every
subcommand.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

STATE_CHOICES = ("new", "needs_review", "translated")
PLURAL_CATEGORIES = ("zero", "one", "two", "few", "many", "other")


class CLIError(Exception):
    """Raised for user-facing errors (bad key, bad arguments, etc.); caught in main() and printed without a traceback."""


def find_catalog_file() -> Path | None:
    """Search the current directory and its subdirectories for the first .xcstrings file, for use when --file is omitted.

    Dot-directories (e.g. .git, .claude) are skipped, since these can contain stale
    or unrelated catalogs (worktrees, caches, etc.) that shouldn't be auto-selected.
    """
    matches = sorted(
        path
        for path in Path.cwd().rglob("*.xcstrings")
        if not any(part.startswith(".") for part in path.relative_to(Path.cwd()).parts[:-1])
    )
    return matches[0] if matches else None


def load_catalog(path: Path) -> dict[str, Any]:
    """Read and parse an .xcstrings file, raising CLIError with a friendly message if it's missing or not valid JSON."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CLIError(f"catalog file not found: {path}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CLIError(f"{path} is not valid JSON: {exc}") from exc


def save_catalog(path: Path, catalog: dict[str, Any]) -> None:
    """Write the catalog back out formatted the way Xcode itself writes it.

    Xcode serializes .xcstrings with keys sorted alphabetically at every
    level, 2-space indentation, literal (non-escaped) Unicode characters, and
    a single trailing newline. Matching that exactly keeps `git diff` minimal
    the next time Xcode opens and re-saves the file.
    """
    text = json.dumps(catalog, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def _entries(catalog: dict[str, Any]) -> dict[str, Any]:
    return catalog.setdefault("strings", {})


def _require_entry(catalog: dict[str, Any], key: str) -> dict[str, Any]:
    """Look up an existing entry by key, raising CLIError if it doesn't exist."""
    entries = _entries(catalog)
    if key not in entries:
        raise CLIError(f"no such key: {key!r}")
    return entries[key]


def _make_string_unit(value: str, state: str) -> dict[str, Any]:
    return {"stringUnit": {"state": state, "value": value}}


def _set_simple_value(localization: dict[str, Any], value: str | None, state: str | None) -> None:
    """Create or update a plain (non-plural) stringUnit in place on a localization dict."""
    unit = localization.setdefault("stringUnit", {})
    if value is not None:
        unit["value"] = value
    unit.setdefault("state", state or "translated")
    if state is not None:
        unit["state"] = state


def _set_plural_values(localization: dict[str, Any], plural_values: dict[str, str], state: str | None) -> None:
    """Create or update one or more plural categories in place on a localization dict."""
    variations = localization.setdefault("variations", {})
    plural = variations.setdefault("plural", {})
    for category, value in plural_values.items():
        if category not in PLURAL_CATEGORIES:
            raise CLIError(
                f"unknown plural category {category!r}; expected one of {', '.join(PLURAL_CATEGORIES)}"
            )
        plural[category] = _make_string_unit(value, state or "translated")


def _parse_plural_args(pairs: list[str]) -> dict[str, str]:
    """Parse repeated `category=value` CLI arguments (e.g. from --plural) into a dict."""
    result: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise CLIError(f"invalid --plural argument {pair!r}; expected category=value, e.g. one='1 item'")
        category, _, value = pair.partition("=")
        result[category] = value
    return result


def _iter_string_units(localization: dict[str, Any]):
    """Yield (label, string_unit_dict) pairs for a localization: one plain unit, or one per plural category."""
    if "stringUnit" in localization:
        yield None, localization["stringUnit"]
    elif "variations" in localization and "plural" in localization["variations"]:
        for category, entry in localization["variations"]["plural"].items():
            if "stringUnit" in entry:
                yield category, entry["stringUnit"]


def cmd_list(args: argparse.Namespace, catalog: dict[str, Any]) -> None:
    """Print keys, optionally filtered by having/lacking a language or by that language's state."""
    entries = _entries(catalog)
    for key in sorted(entries):
        entry = entries[key]
        localizations = entry.get("localizations", {})

        if args.missing:
            if args.missing not in localizations:
                print(key)
            continue

        lang = args.lang or catalog.get("sourceLanguage", "en")
        if lang not in localizations:
            if args.lang:
                continue
            print(key)
            continue

        if args.state:
            states = [unit.get("state") for _, unit in _iter_string_units(localizations[lang])]
            if args.state not in states:
                continue

        print(key)


def cmd_get(args: argparse.Namespace, catalog: dict[str, Any]) -> None:
    """Print a human-readable (or --json) summary of a single entry."""
    entry = _require_entry(catalog, args.key)

    if args.json:
        print(json.dumps(entry, indent=2, sort_keys=True, ensure_ascii=False))
        return

    print(f"key: {args.key}")
    print(f"extractionState: {entry.get('extractionState', 'unknown')}")
    if "comment" in entry:
        print(f"comment: {entry['comment']}")

    localizations = entry.get("localizations", {})
    langs = [args.lang] if args.lang else sorted(localizations)
    for lang in langs:
        if lang not in localizations:
            raise CLIError(f"key {args.key!r} has no localization for {lang!r}")
        print(f"  [{lang}]")
        for category, unit in _iter_string_units(localizations[lang]):
            label = f"{category}: " if category else ""
            print(f"    {label}{unit.get('value', '')!r} ({unit.get('state', 'unknown')})")


def _make_matcher(query: str, case_sensitive: bool) -> Callable[[str], bool]:
    """Build a matcher: a glob (fnmatch, anchored to the whole string) if query contains *?[, otherwise a substring test."""
    if any(ch in query for ch in "*?["):
        pattern = re.compile(fnmatch.translate(query), 0 if case_sensitive else re.IGNORECASE)
        return lambda text: pattern.match(text) is not None

    needle = query if case_sensitive else query.lower()
    return lambda text: needle in (text if case_sensitive else text.lower())


def cmd_find_key(args: argparse.Namespace, catalog: dict[str, Any]) -> None:
    """Print every key matching a substring (or, with *?[ present, glob) query."""
    matches = _make_matcher(args.query, args.case_sensitive)
    for key in sorted(_entries(catalog)):
        if matches(key):
            print(key)


def cmd_find_value(args: argparse.Namespace, catalog: dict[str, Any]) -> None:
    """Print every key/language/value matching a substring (or, with *?[ present, glob) query."""
    matches = _make_matcher(args.query, args.case_sensitive)
    entries = _entries(catalog)

    for key in sorted(entries):
        localizations = entries[key].get("localizations", {})
        langs = [args.lang] if args.lang else localizations
        for lang in langs:
            if lang not in localizations:
                continue
            for category, unit in _iter_string_units(localizations[lang]):
                value = unit.get("value", "")
                if matches(value):
                    label = f"{category}/" if category else ""
                    print(f"{key}  ({lang}/{label}: {value!r})")


def cmd_total_key_count(args: argparse.Namespace, catalog: dict[str, Any]) -> None:
    """Print the total number of keys in the catalog."""
    print(len(_entries(catalog)))


def cmd_add(args: argparse.Namespace, catalog: dict[str, Any]) -> None:
    """Create a new entry; raises CLIError if the key already exists."""
    entries = _entries(catalog)
    if args.key in entries:
        raise CLIError(f"key already exists: {args.key!r} (use `update` instead)")

    entry: dict[str, Any] = {"extractionState": args.extraction_state}
    if args.comment:
        entry["comment"] = args.comment

    localization: dict[str, Any] = {}
    if args.plural:
        _set_plural_values(localization, _parse_plural_args(args.plural), args.state)
    else:
        _set_simple_value(localization, args.value, args.state)

    entry["localizations"] = {args.lang: localization}
    entries[args.key] = entry


def cmd_update(args: argparse.Namespace, catalog: dict[str, Any]) -> None:
    """Update an existing entry's value(s), state, and/or comment; raises CLIError if the key doesn't exist."""
    entry = _require_entry(catalog, args.key)

    if args.comment is not None:
        entry["comment"] = args.comment

    if args.value is not None or args.plural or args.state is not None:
        localizations = entry.setdefault("localizations", {})
        localization = localizations.setdefault(args.lang, {})
        if args.plural:
            _set_plural_values(localization, _parse_plural_args(args.plural), args.state)
        elif args.value is not None:
            _set_simple_value(localization, args.value, args.state)
        elif args.state is not None:
            for _, unit in _iter_string_units(localization):
                unit["state"] = args.state


def cmd_delete(args: argparse.Namespace, catalog: dict[str, Any]) -> None:
    """Delete a whole entry, or just one language's localization if --lang is given."""
    entry = _require_entry(catalog, args.key)

    if args.lang:
        localizations = entry.get("localizations", {})
        if args.lang not in localizations:
            raise CLIError(f"key {args.key!r} has no localization for {args.lang!r}")
        del localizations[args.lang]
    else:
        del _entries(catalog)[args.key]


READ_ONLY_COMMANDS = {"list", "get", "find-key", "find-value", "total-key-count"}


def _make_file_parent() -> argparse.ArgumentParser:
    """A shared parent parser for --file, attached to each subcommand (so it goes after the subcommand name, e.g. `list --file path`)."""
    file_parent = argparse.ArgumentParser(add_help=False)
    file_parent.add_argument(
        "--file",
        type=Path,
        default=None,
        help=(
            "path to the .xcstrings file to operate on "
            "(default: the first .xcstrings file found under the current directory)"
        ),
    )
    return file_parent


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argparse parser with all subcommands, help text, and usage examples."""
    file_parent = _make_file_parent()

    parser = argparse.ArgumentParser(
        prog="xcstringstool.py",
        description="Inspect and edit an Xcode String Catalog (.xcstrings) file from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  xcstringstool.py list --missing fr\n"
            "  xcstringstool.py get cancelButton\n"
            "  xcstringstool.py find-key 'shared*lant*'\n"
            "  xcstringstool.py add cancelButton --value 'Cancel'\n"
            "  xcstringstool.py update cancelButton --lang fr --value 'Annuler'\n"
            "  xcstringstool.py total-key-count\n"
            "\n"
            "By default the tool operates on the first .xcstrings file found under\n"
            "the current directory (searched recursively, skipping dot-directories\n"
            "such as .git or .claude); pass --file PATH after any subcommand to\n"
            "target a different catalog.\n"
            "\n"
            "See XCSTRINGSTOOL.md for a full worked example of every subcommand."
        ),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list",
        help="list keys in the catalog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[file_parent],
        epilog=(
            "examples:\n"
            "  xcstringstool.py list\n"
            "  xcstringstool.py list --lang fr --state needs_review\n"
            "  xcstringstool.py list --missing fr\n"
        ),
    )
    list_parser.add_argument("--lang", help="only list keys that have a localization for LANG")
    list_parser.add_argument("--state", choices=STATE_CHOICES, help="only list keys whose LANG state matches")
    list_parser.add_argument("--missing", metavar="LANG", help="only list keys with NO localization for LANG")

    get_parser = subparsers.add_parser(
        "get",
        help="show one entry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[file_parent],
        epilog=(
            "examples:\n"
            "  xcstringstool.py get cancelButton\n"
            "  xcstringstool.py get cancelButton --lang fr\n"
            "  xcstringstool.py get cancelButton --json\n"
        ),
    )
    get_parser.add_argument("key", help="the string key to show")
    get_parser.add_argument("--lang", help="only show this language's localization")
    get_parser.add_argument("--json", action="store_true", help="print the raw JSON entry instead of a summary")

    find_key_parser = subparsers.add_parser(
        "find-key",
        help="search keys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[file_parent],
        epilog=(
            "examples:\n"
            "  xcstringstool.py find-key cancel\n"
            "  xcstringstool.py find-key 'shared*lant*'\n"
        ),
    )
    find_key_parser.add_argument(
        "query",
        help="substring to search for, or a glob pattern (with *, ?, or [...]) matched against the whole key",
    )
    find_key_parser.add_argument("--case-sensitive", action="store_true", help="match case exactly")

    find_value_parser = subparsers.add_parser(
        "find-value",
        help="search values",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[file_parent],
        epilog=(
            "examples:\n"
            "  xcstringstool.py find-value Annuler\n"
            "  xcstringstool.py find-value Annuler --lang fr\n"
            "  xcstringstool.py find-value '*day ago'\n"
        ),
    )
    find_value_parser.add_argument(
        "query",
        help="substring to search for, or a glob pattern (with *, ?, or [...]) matched against the whole value",
    )
    find_value_parser.add_argument("--lang", help="only search values for this language")
    find_value_parser.add_argument("--case-sensitive", action="store_true", help="match case exactly")

    subparsers.add_parser(
        "total-key-count",
        help="print the total number of keys in the catalog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[file_parent],
        epilog=("examples:\n" "  xcstringstool.py total-key-count\n"),
    )

    add_parser = subparsers.add_parser(
        "add",
        help="create a new entry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[file_parent],
        epilog=(
            "examples:\n"
            "  xcstringstool.py add cancelButton --value 'Cancel'\n"
            "  xcstringstool.py add cancelButton --value 'Cancel' --state new --comment 'Shown in dialogs'\n"
            "  xcstringstool.py add daysAgoLabel --plural one='%d day ago' other='%d days ago'\n"
        ),
    )
    add_parser.add_argument("key", help="the new string key")
    add_parser.add_argument("--lang", default="en", help="language code for the localization (default: en)")
    add_parser.add_argument("--value", help="the string value for a simple (non-plural) entry")
    add_parser.add_argument(
        "--plural",
        action="append",
        metavar="CATEGORY=VALUE",
        help="a plural category and its value, e.g. one='1 item' (repeatable); mutually exclusive with --value",
    )
    add_parser.add_argument("--state", choices=STATE_CHOICES, default="translated", help="stringUnit state (default: translated)")
    add_parser.add_argument("--extraction-state", default="manual", help="entry extractionState (default: manual)")
    add_parser.add_argument("--comment", help="optional entry-level translator comment")

    update_parser = subparsers.add_parser(
        "update",
        help="modify an existing entry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[file_parent],
        epilog=(
            "examples:\n"
            "  xcstringstool.py update cancelButton --value 'Nevermind'\n"
            "  xcstringstool.py update cancelButton --lang fr --value 'Annuler' --state translated\n"
            "  xcstringstool.py update daysAgoLabel --plural other='%d days ago now'\n"
            "  xcstringstool.py update cancelButton --state needs_review\n"
        ),
    )
    update_parser.add_argument("key", help="the string key to update")
    update_parser.add_argument("--lang", default="en", help="language code for the localization (default: en)")
    update_parser.add_argument("--value", help="new string value for a simple (non-plural) entry")
    update_parser.add_argument(
        "--plural",
        action="append",
        metavar="CATEGORY=VALUE",
        help="a plural category and its new value, e.g. other='%%d items' (repeatable)",
    )
    update_parser.add_argument("--state", choices=STATE_CHOICES, help="new stringUnit state")
    update_parser.add_argument("--comment", help="replace the entry-level translator comment")

    delete_parser = subparsers.add_parser(
        "delete",
        help="remove an entry or one of its localizations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[file_parent],
        epilog=(
            "examples:\n"
            "  xcstringstool.py delete oldUnusedKey\n"
            "  xcstringstool.py delete cancelButton --lang fr\n"
        ),
    )
    delete_parser.add_argument("key", help="the string key to delete")
    delete_parser.add_argument("--lang", help="only delete this language's localization, keeping the rest of the entry")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "add" and args.value is not None and args.plural:
        parser.error("--value and --plural are mutually exclusive")

    if args.file is None:
        found = find_catalog_file()
        if found is None:
            print(
                "error: no .xcstrings file found in the current directory or its subdirectories; "
                "use --file to specify one",
                file=sys.stderr,
            )
            return 1
        args.file = found

    try:
        catalog = load_catalog(args.file)

        commands = {
            "list": cmd_list,
            "get": cmd_get,
            "find-key": cmd_find_key,
            "find-value": cmd_find_value,
            "total-key-count": cmd_total_key_count,
            "add": cmd_add,
            "update": cmd_update,
            "delete": cmd_delete,
        }
        commands[args.command](args, catalog)

        if args.command not in READ_ONLY_COMMANDS:
            save_catalog(args.file, catalog)
    except CLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
