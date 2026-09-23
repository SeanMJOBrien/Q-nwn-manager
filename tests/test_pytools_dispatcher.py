#!/usr/bin/env python3
"""Tests for bin/_pytools_main.py, the dispatcher PyInstaller compiles into
nwn-pytools, and for bin/nwn-wiki's frozen-mode branch that spawns
wiki-activity as a dispatcher subcommand instead of by sibling-script path.

Validates the dispatch/argv-rewriting/__file__-resolution logic directly
(no PyInstaller build needed) by loading the real scripts via
SourceFileLoader - same technique tests/test_remove_objects.py already uses
for nwn-area-editor - and by faking frozen mode with sys.frozen/sys._MEIPASS,
same as bin/_pytools_main.py's own base_dir() checks for at runtime.

Run all tests:
    python3 tests/test_pytools_dispatcher.py
"""
import json
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN = REPO_ROOT / "bin"


def load(name, path):
    return SourceFileLoader(name, str(path)).load_module()


DISPATCHER = load("pytools_dispatcher_under_test", BIN / "_pytools_main.py")


class FakeModule:
    """Stand-in for a loaded nwn-wiki/nwn-area-editor/nwn-wiki-activity
    module: records what it was called with instead of doing real work."""

    def __init__(self, return_value=0):
        self.return_value = return_value
        self.argv_at_call = None
        self.call_args = None

    def main(self, argv=None):
        if argv is None:
            self.argv_at_call = list(sys.argv)  # called as mod.main() - reads bare sys.argv
        else:
            self.call_args = argv  # called as mod.main([...]) - explicit argv param
        return self.return_value


class BaseDirTests(unittest.TestCase):
    def tearDown(self):
        for attr in ("frozen", "_MEIPASS"):
            if hasattr(sys, attr):
                delattr(sys, attr)

    def test_unfrozen_resolves_to_bin(self):
        self.assertFalse(getattr(sys, "frozen", False))
        self.assertEqual(DISPATCHER.base_dir(), BIN.resolve())

    def test_frozen_resolves_to_meipass(self):
        sys.frozen = True
        sys._MEIPASS = "/fake/extraction/root"
        self.assertEqual(DISPATCHER.base_dir(), Path("/fake/extraction/root"))


class DispatchArgvTests(unittest.TestCase):
    """wiki/area-editor/wiki-activity read bare sys.argv via argparse - the
    dispatcher must rewrite it before calling main(). check-dlg-integrity
    takes argv as an explicit main(argv) parameter instead."""

    def setUp(self):
        self._orig_argv = list(sys.argv)
        self._orig_load_script = DISPATCHER.load_script
        self.fake = FakeModule(return_value=7)
        DISPATCHER.load_script = lambda name: self.fake

    def tearDown(self):
        sys.argv = self._orig_argv
        DISPATCHER.load_script = self._orig_load_script

    def test_wiki_rewrites_sys_argv_and_returns_main_result(self):
        sys.argv = ["nwn-pytools", "wiki", "--src", "unpacked", "--out", "docs"]
        rc = DISPATCHER.dispatch(sys.argv)
        self.assertEqual(rc, 7)
        self.assertEqual(
            self.fake.argv_at_call,
            [str(DISPATCHER.base_dir() / "nwn-wiki"), "--src", "unpacked", "--out", "docs"],
        )
        self.assertIsNone(self.fake.call_args)  # main() called with no args

    def test_area_editor_rewrites_sys_argv(self):
        sys.argv = ["nwn-pytools", "area-editor", "--dir", "unpacked"]
        DISPATCHER.dispatch(sys.argv)
        self.assertEqual(
            self.fake.argv_at_call,
            [str(DISPATCHER.base_dir() / "nwn-area-editor"), "--dir", "unpacked"],
        )

    def test_wiki_activity_rewrites_sys_argv(self):
        sys.argv = ["nwn-pytools", "wiki-activity", "--check-online"]
        DISPATCHER.dispatch(sys.argv)
        self.assertEqual(
            self.fake.argv_at_call,
            [str(DISPATCHER.base_dir() / "nwn-wiki-activity"), "--check-online"],
        )

    def test_check_dlg_integrity_gets_explicit_argv_not_sys_argv_rewrite(self):
        sentinel = ["untouched", "sys.argv"]
        sys.argv = list(sentinel)
        rc = DISPATCHER.dispatch(["nwn-pytools", "check-dlg-integrity", "unpacked"])
        self.assertEqual(rc, 7)
        self.assertEqual(
            self.fake.call_args,
            [str(DISPATCHER.base_dir() / "check-dlg-integrity"), "unpacked"],
        )
        self.assertIsNone(self.fake.argv_at_call)  # main(argv) called, not main()
        self.assertEqual(sys.argv, sentinel)  # dispatcher never touched sys.argv

    def test_unknown_subcommand_returns_2_without_loading_anything(self):
        loaded = []
        DISPATCHER.load_script = lambda name: loaded.append(name) or self.fake
        rc = DISPATCHER.dispatch(["nwn-pytools", "bogus"])
        self.assertEqual(rc, 2)
        self.assertEqual(loaded, [])

    def test_no_subcommand_returns_2(self):
        self.assertEqual(DISPATCHER.dispatch(["nwn-pytools"]), 2)


class JsonLookupTests(unittest.TestCase):
    """hak-list / tlk-name replicate what used to be inline `python3 -c`
    one-liners in bin/nwn-manager's extract_hak_includes/extract_tlks."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ifo_path = Path(self.tmp.name) / "module.ifo.json"

    def _write_ifo(self, data):
        self.ifo_path.write_text(json.dumps(data), encoding="utf-8")

    def test_hak_list_prints_each_hak_name(self, capsys=None):
        self._write_ifo({
            "Mod_HakList": {"type": "list", "value": [
                {"Mod_Hak": {"type": "cexostring", "value": "hakA"}},
                {"Mod_Hak": {"type": "cexostring", "value": "  hakB  "}},
                {"Mod_Hak": {"type": "cexostring", "value": ""}},
            ]},
        })
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = DISPATCHER.dispatch(["nwn-pytools", "hak-list", str(self.ifo_path)])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().splitlines(), ["hakA", "hakB"])

    def test_tlk_name_prints_custom_tlk(self):
        self._write_ifo({"Mod_CustomTlk": {"type": "cexostring", "value": "mymod"}})
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = DISPATCHER.dispatch(["nwn-pytools", "tlk-name", str(self.ifo_path)])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "mymod")

    def test_hak_list_missing_file_returns_0_prints_nothing(self):
        rc = DISPATCHER.dispatch(["nwn-pytools", "hak-list", str(self.ifo_path)])  # never written
        self.assertEqual(rc, 0)

    def test_tlk_name_malformed_json_returns_0_prints_nothing(self):
        self.ifo_path.write_text("{not valid json", encoding="utf-8")
        rc = DISPATCHER.dispatch(["nwn-pytools", "tlk-name", str(self.ifo_path)])
        self.assertEqual(rc, 0)


class NwnWikiFrozenSpawnTests(unittest.TestCase):
    """bin/nwn-wiki spawns nwn-wiki-activity as a subprocess when a build has
    activity data. Frozen builds must route that through the dispatcher
    (`[sys.executable, "wiki-activity", ...]`) instead of a sibling-script
    path, since a frozen nwn-wiki has no on-disk nwn-wiki-activity file next
    to it. Real log-file parsing is mocked out (parse_nwserver_logs) so this
    isolates just the frozen-vs-unfrozen command-construction branch."""

    def setUp(self):
        self.wiki = load("nwn_wiki_frozen_test", BIN / "nwn-wiki")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.src = root / "unpacked"
        self.out = root / "docs"
        self.src.mkdir()
        self.log_dir = root / "logs"
        self.log_dir.mkdir()
        (self.src / "module.ifo.json").write_text(json.dumps({
            "Mod_Name": {"type": "cexolocstring", "value": {"0": "Frozen Spawn Test"}},
            "Mod_Description": {"type": "cexolocstring", "value": {"0": ""}},
            "Mod_Entry_Area": {"type": "resref", "value": ""},
            "Mod_HakList": {"type": "list", "value": []},
        }), encoding="utf-8")

        # Bypass real NWN server-log parsing: return one Player session so
        # _HAS_ACTIVITY_PAGE flips True and the subprocess spawn is reached.
        self.wiki.parse_nwserver_logs = lambda *a, **k: {
            "sessions": [{"player": "Alice", "role": "Player",
                          "join": "2026-01-01T00:00:00", "leave": "2026-01-01T01:00:00",
                          "duration_min": 60.0}],
            "file_count": 0,
        }

        self.captured_cmd = []

        def fake_run(cmd, check=True, **kw):
            self.captured_cmd.append(cmd)
            class Result:
                returncode = 0
            return Result()

        self._orig_run = self.wiki.subprocess.run
        self.wiki.subprocess.run = fake_run
        self.addCleanup(setattr, self.wiki.subprocess, "run", self._orig_run)

        self._orig_argv = list(sys.argv)
        self._orig_executable = sys.executable
        self.addCleanup(setattr, sys, "argv", self._orig_argv)
        self.addCleanup(setattr, sys, "executable", self._orig_executable)

    def _run_main(self):
        sys.argv = ["nwn-wiki", "--src", str(self.src), "--out", str(self.out),
                    "--log-dir", str(self.log_dir)]
        try:
            self.wiki.main()
        except SystemExit:
            pass

    def test_unfrozen_spawns_by_sibling_script_path(self):
        self.assertFalse(getattr(sys, "frozen", False))
        self._run_main()
        self.assertEqual(len(self.captured_cmd), 1)
        cmd = self.captured_cmd[0]
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1], str(BIN / "nwn-wiki-activity"))
        self.assertIn("--src", cmd)

    def test_frozen_spawns_via_dispatcher_subcommand(self):
        sys.frozen = True
        sys.executable = "/fake/dist/nwn-pytools/nwn-pytools"
        try:
            self._run_main()
        finally:
            del sys.frozen
        self.assertEqual(len(self.captured_cmd), 1)
        cmd = self.captured_cmd[0]
        self.assertEqual(cmd[0], "/fake/dist/nwn-pytools/nwn-pytools")
        self.assertEqual(cmd[1], "wiki-activity")
        self.assertNotIn("nwn-wiki-activity", " ".join(cmd))
        self.assertIn("--src", cmd)


if __name__ == "__main__":
    unittest.main()
