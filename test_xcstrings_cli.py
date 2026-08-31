"""Unit tests for xcstrings-cli, covering list/get/find/add/update/delete against a small fixture catalog."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

_script_path = Path(__file__).resolve().parent / "xcstrings-cli"
_loader = importlib.machinery.SourceFileLoader("xcstrings_cli", str(_script_path))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
cli = importlib.util.module_from_spec(_spec)
_loader.exec_module(cli)


def make_fixture() -> dict:
    return {
        "sourceLanguage": "en",
        "strings": {
            "cancelButton": {
                "extractionState": "manual",
                "localizations": {
                    "en": {"stringUnit": {"state": "translated", "value": "Cancel"}},
                    "fr": {"stringUnit": {"state": "needs_review", "value": "Annuler?"}},
                },
            },
            "daysAgoLabel": {
                "extractionState": "manual",
                "localizations": {
                    "en": {
                        "variations": {
                            "plural": {
                                "one": {"stringUnit": {"state": "translated", "value": "%d day ago"}},
                                "other": {"stringUnit": {"state": "translated", "value": "%d days ago"}},
                            }
                        }
                    }
                },
            },
        },
        "version": "1.1",
    }


class CatalogHelpersTests(unittest.TestCase):
    def test_load_catalog_missing_file(self):
        with self.assertRaises(cli.CLIError):
            cli.load_catalog(Path("/nonexistent/path/Localizable.xcstrings"))

    def test_load_catalog_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.xcstrings"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(cli.CLIError):
                cli.load_catalog(path)

    def test_save_catalog_roundtrip(self):
        catalog = make_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.xcstrings"
            cli.save_catalog(path, catalog)
            reloaded = cli.load_catalog(path)
            self.assertEqual(reloaded, catalog)
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertNotIn("\n\n\n", text)


class RealCatalogFormatTests(unittest.TestCase):
    """Proves save_catalog() reproduces Xcode's own serialization byte-for-byte."""

    def test_roundtrip_matches_real_file_bytes(self):
        real_path = Path(__file__).resolve().parent / "Canopy" / "Localizable.xcstrings"
        if not real_path.exists():
            self.skipTest("Canopy/Localizable.xcstrings not present in this checkout")

        original_bytes = real_path.read_bytes()
        catalog = cli.load_catalog(real_path)

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "roundtrip.xcstrings"
            cli.save_catalog(out_path, catalog)
            self.assertEqual(out_path.read_bytes(), original_bytes)


class AddCommandTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_fixture()

    def test_add_simple_entry(self):
        args = cli.build_parser().parse_args(["add", "newKey", "--value", "Hello", "--lang", "en"])
        cli.cmd_add(args, self.catalog)
        entry = self.catalog["strings"]["newKey"]
        self.assertEqual(entry["extractionState"], "manual")
        self.assertEqual(entry["localizations"]["en"]["stringUnit"]["value"], "Hello")
        self.assertEqual(entry["localizations"]["en"]["stringUnit"]["state"], "translated")

    def test_add_plural_entry(self):
        args = cli.build_parser().parse_args(
            ["add", "itemsLabel", "--plural", "one=1 item", "--plural", "other=%d items"]
        )
        cli.cmd_add(args, self.catalog)
        plural = self.catalog["strings"]["itemsLabel"]["localizations"]["en"]["variations"]["plural"]
        self.assertEqual(plural["one"]["stringUnit"]["value"], "1 item")
        self.assertEqual(plural["other"]["stringUnit"]["value"], "%d items")

    def test_add_duplicate_key_raises(self):
        args = cli.build_parser().parse_args(["add", "cancelButton", "--value", "x"])
        with self.assertRaises(cli.CLIError):
            cli.cmd_add(args, self.catalog)

    def test_add_with_comment_and_state(self):
        args = cli.build_parser().parse_args(
            ["add", "newKey", "--value", "Hi", "--state", "new", "--comment", "shown in header"]
        )
        cli.cmd_add(args, self.catalog)
        entry = self.catalog["strings"]["newKey"]
        self.assertEqual(entry["comment"], "shown in header")
        self.assertEqual(entry["localizations"]["en"]["stringUnit"]["state"], "new")


class UpdateCommandTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_fixture()

    def test_update_simple_value_preserves_other_languages(self):
        args = cli.build_parser().parse_args(["update", "cancelButton", "--value", "Nevermind"])
        cli.cmd_update(args, self.catalog)
        localizations = self.catalog["strings"]["cancelButton"]["localizations"]
        self.assertEqual(localizations["en"]["stringUnit"]["value"], "Nevermind")
        self.assertEqual(localizations["fr"]["stringUnit"]["value"], "Annuler?")

    def test_update_plural_category(self):
        args = cli.build_parser().parse_args(["update", "daysAgoLabel", "--plural", "other=%d days ago now"])
        cli.cmd_update(args, self.catalog)
        plural = self.catalog["strings"]["daysAgoLabel"]["localizations"]["en"]["variations"]["plural"]
        self.assertEqual(plural["other"]["stringUnit"]["value"], "%d days ago now")
        self.assertEqual(plural["one"]["stringUnit"]["value"], "%d day ago")

    def test_update_state_only(self):
        args = cli.build_parser().parse_args(["update", "cancelButton", "--state", "needs_review"])
        cli.cmd_update(args, self.catalog)
        self.assertEqual(
            self.catalog["strings"]["cancelButton"]["localizations"]["en"]["stringUnit"]["state"],
            "needs_review",
        )

    def test_update_missing_key_raises(self):
        args = cli.build_parser().parse_args(["update", "noSuchKey", "--value", "x"])
        with self.assertRaises(cli.CLIError):
            cli.cmd_update(args, self.catalog)

    def test_update_new_language_creates_localization(self):
        args = cli.build_parser().parse_args(["update", "cancelButton", "--lang", "de", "--value", "Abbrechen"])
        cli.cmd_update(args, self.catalog)
        self.assertEqual(
            self.catalog["strings"]["cancelButton"]["localizations"]["de"]["stringUnit"]["value"],
            "Abbrechen",
        )


class DeleteCommandTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_fixture()

    def test_delete_whole_entry(self):
        args = cli.build_parser().parse_args(["delete", "cancelButton"])
        cli.cmd_delete(args, self.catalog)
        self.assertNotIn("cancelButton", self.catalog["strings"])

    def test_delete_single_language(self):
        args = cli.build_parser().parse_args(["delete", "cancelButton", "--lang", "fr"])
        cli.cmd_delete(args, self.catalog)
        localizations = self.catalog["strings"]["cancelButton"]["localizations"]
        self.assertNotIn("fr", localizations)
        self.assertIn("en", localizations)

    def test_delete_missing_key_raises(self):
        args = cli.build_parser().parse_args(["delete", "noSuchKey"])
        with self.assertRaises(cli.CLIError):
            cli.cmd_delete(args, self.catalog)

    def test_delete_missing_language_raises(self):
        args = cli.build_parser().parse_args(["delete", "cancelButton", "--lang", "de"])
        with self.assertRaises(cli.CLIError):
            cli.cmd_delete(args, self.catalog)


class GetCommandTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_fixture()

    def test_get_missing_key_raises(self):
        args = cli.build_parser().parse_args(["get", "noSuchKey"])
        with self.assertRaises(cli.CLIError):
            cli.cmd_get(args, self.catalog)

    def test_get_prints_summary(self):
        args = cli.build_parser().parse_args(["get", "cancelButton"])
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.cmd_get(args, self.catalog)
        output = buf.getvalue()
        self.assertIn("cancelButton", output)
        self.assertIn("Cancel", output)
        self.assertIn("Annuler?", output)

    def test_get_json_output_is_valid_json(self):
        args = cli.build_parser().parse_args(["get", "cancelButton", "--json"])
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.cmd_get(args, self.catalog)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed, self.catalog["strings"]["cancelButton"])

    def test_get_missing_lang_raises(self):
        import io
        import contextlib

        args = cli.build_parser().parse_args(["get", "cancelButton", "--lang", "de"])
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(cli.CLIError):
            cli.cmd_get(args, self.catalog)


class FindKeyCommandTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_fixture()

    def _output(self, argv):
        import io
        import contextlib

        args = cli.build_parser().parse_args(argv)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.cmd_find_key(args, self.catalog)
        return buf.getvalue()

    def test_find_key_matches_substring(self):
        output = self._output(["find-key", "cancel"])
        self.assertEqual(output, "cancelButton\n")

    def test_find_key_does_not_search_values(self):
        output = self._output(["find-key", "Annuler"])
        self.assertEqual(output, "")

    def test_find_key_glob_pattern_matches(self):
        output = self._output(["find-key", "can*ton"])
        self.assertIn("cancelButton", output)

    def test_find_key_glob_pattern_is_anchored_to_whole_string(self):
        # Unlike a plain substring search, a glob pattern must match the entire
        # key -- "ancel*" doesn't match "cancelButton" because it's missing the
        # leading "c".
        output = self._output(["find-key", "ancel*"])
        self.assertEqual(output, "")

    def test_find_key_glob_pattern_is_case_insensitive_by_default(self):
        output = self._output(["find-key", "CANCEL*"])
        self.assertIn("cancelButton", output)

    def test_find_key_glob_pattern_case_sensitive(self):
        output = self._output(["find-key", "CANCEL*", "--case-sensitive"])
        self.assertEqual(output, "")


class FindValueCommandTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_fixture()

    def _output(self, argv):
        import io
        import contextlib

        args = cli.build_parser().parse_args(argv)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.cmd_find_value(args, self.catalog)
        return buf.getvalue()

    def test_find_value_matches_substring(self):
        output = self._output(["find-value", "Annuler"])
        self.assertIn("cancelButton", output)

    def test_find_value_does_not_search_keys(self):
        output = self._output(["find-value", "cancelButton"])
        self.assertEqual(output, "")

    def test_find_value_restricted_to_lang(self):
        output = self._output(["find-value", "Annuler", "--lang", "fr"])
        self.assertIn("cancelButton", output)
        output_en_only = self._output(["find-value", "Annuler", "--lang", "en"])
        self.assertEqual(output_en_only, "")

    def test_find_value_glob_pattern_matches(self):
        output = self._output(["find-value", "*day ago"])
        self.assertIn("daysAgoLabel", output)


class ListCommandTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_fixture()

    def _output(self, argv):
        import io
        import contextlib

        args = cli.build_parser().parse_args(argv)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.cmd_list(args, self.catalog)
        return buf.getvalue().splitlines()

    def test_list_all_keys(self):
        keys = self._output(["list"])
        self.assertEqual(keys, ["cancelButton", "daysAgoLabel"])

    def test_list_filtered_by_lang(self):
        keys = self._output(["list", "--lang", "fr"])
        self.assertEqual(keys, ["cancelButton"])

    def test_list_filtered_by_state(self):
        keys = self._output(["list", "--lang", "fr", "--state", "needs_review"])
        self.assertEqual(keys, ["cancelButton"])

    def test_list_missing_language(self):
        keys = self._output(["list", "--missing", "fr"])
        self.assertEqual(keys, ["daysAgoLabel"])


class TotalKeyCountCommandTests(unittest.TestCase):
    def setUp(self):
        self.catalog = make_fixture()

    def test_total_key_count_prints_count(self):
        import io
        import contextlib

        args = cli.build_parser().parse_args(["total-key-count"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.cmd_total_key_count(args, self.catalog)
        self.assertEqual(buf.getvalue().strip(), "2")


class MainEntryPointTests(unittest.TestCase):
    def test_end_to_end_add_update_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Localizable.xcstrings"
            cli.save_catalog(path, make_fixture())

            self.assertEqual(cli.main(["add", "greeting", "--value", "Hi", "--file", str(path)]), 0)
            self.assertEqual(cli.load_catalog(path)["strings"]["greeting"]["localizations"]["en"]["stringUnit"]["value"], "Hi")

            self.assertEqual(cli.main(["update", "greeting", "--value", "Hi there", "--file", str(path)]), 0)
            self.assertEqual(cli.load_catalog(path)["strings"]["greeting"]["localizations"]["en"]["stringUnit"]["value"], "Hi there")

            self.assertEqual(cli.main(["delete", "greeting", "--file", str(path)]), 0)
            self.assertNotIn("greeting", cli.load_catalog(path)["strings"])

    def test_main_returns_1_on_cli_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Localizable.xcstrings"
            cli.save_catalog(path, make_fixture())
            self.assertEqual(cli.main(["delete", "noSuchKey", "--file", str(path)]), 1)

    def test_add_value_and_plural_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Localizable.xcstrings"
            cli.save_catalog(path, make_fixture())
            with self.assertRaises(SystemExit):
                cli.main(["add", "x", "--value", "a", "--plural", "one=b", "--file", str(path)])

    def test_full_help_prints_docs_file(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cli.main(["--full-help"]), 0)
        self.assertIn("xcstrings-cli", buf.getvalue())
        self.assertIn("## Commands", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
