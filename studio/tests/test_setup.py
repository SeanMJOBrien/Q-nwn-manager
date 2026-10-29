"""Setup and portability: per-OS tool lookup, NWN install detection, checkout errors, `--tfn` anywhere, `doctor`.

Everything runs in temp dirs with the OS faked, so it also protects macOS/Windows behaviour when run on Linux.
"""

from __future__ import annotations

import contextlib
import io
import os
import platform
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixture import ROOT  # noqa: F401  (sets sys.path)

from tfnstudio import cli
from tfnstudio import gamedata as GD
from tfnstudio import project as P
from tfnstudio import validate as V
from tfnstudio.doctor import run_doctor

TOOL_ENV = ("NWN_TOOLS", "NWN_GFF", "NWNSC", "NASHER", "NWN_RESMAN_EXTRACT", "TFN_ROOT", "NWN_ROOT", "NWN_USER")


def make_exe(path: Path, body: str = "#!/bin/sh\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def make_checkout(path: Path, tfn: bool = True) -> Path:
    for sub in ("git", "are"):
        (path / "src" / sub).mkdir(parents=True, exist_ok=True)
    if tfn:
        (path / "src" / "nss").mkdir(parents=True, exist_ok=True)
        (path / "src" / "nss" / "inc_quest.nss").write_text("// quests\n")
    return path


class IsolatedCase(unittest.TestCase):
    """Temp dir + no inherited NWN/TFN environment + a studio location whose parent has no nwn-tools."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if k not in TOOL_ENV}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(P, "STUDIO_ROOT", self.base / "studio-home" / "Q-tfn-content-studio")
        p.start()
        self.addCleanup(p.stop)

    def fake_os(self, system: str, machine: str = "arm64"):
        for name, value in (("system", system), ("machine", machine)):
            p = mock.patch.object(platform, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)


class ToolLookupTests(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.tfn = make_checkout(self.base / "the-frozen-north")

    def test_platform_dirs_per_os(self):
        self.fake_os("Darwin", "arm64")
        self.assertEqual(P.platform_dirs(), ["macos_arm64"])
        self.fake_os("Windows", "AMD64")
        self.assertEqual(P.platform_dirs(), ["win"])
        self.fake_os("Linux", "x86_64")
        self.assertEqual(P.platform_dirs(), ["linux"])

    def test_mac_picks_the_macos_tools_not_the_linux_ones(self):
        linux = make_exe(self.tfn / "tools" / "linux" / "neverwinter" / "nwn_gff")
        mac = make_exe(self.tfn / "tools" / "macos_arm64" / "neverwinter" / "nwn_gff")
        self.fake_os("Darwin")
        self.assertEqual(P.find_tool("nwn_gff", self.tfn), mac)
        self.fake_os("Linux", "x86_64")
        self.assertEqual(P.find_tool("nwn_gff", self.tfn), linux)

    def test_a_linux_only_install_is_not_offered_on_a_mac(self):
        make_exe(self.tfn / "tools" / "linux" / "nwnsc" / "nwnsc")
        self.fake_os("Darwin")
        self.assertIsNone(P.find_tool("nwnsc", self.tfn))

    def test_windows_uses_exe_names_and_neverwinter64(self):
        win = make_exe(self.tfn / "tools" / "win" / "neverwinter64" / "nwn_gff.exe")
        self.fake_os("Windows", "AMD64")
        self.assertEqual(P.find_tool("nwn_gff", self.tfn), win)

    def test_shared_nwn_tools_folder_next_to_the_checkout_is_searched(self):
        shared = make_exe(self.base / "nwn-tools" / "macos_arm64" / "nwnsc" / "nwnsc")
        self.fake_os("Darwin")
        self.assertEqual(P.find_tool("nwnsc", self.tfn), shared)

    def test_nwn_tools_env_adds_a_place_and_tool_env_wins(self):
        elsewhere = make_exe(self.base / "elsewhere" / "linux" / "nasher" / "nasher")
        self.fake_os("Linux", "x86_64")
        with mock.patch.dict(os.environ, {"NWN_TOOLS": str(self.base / "elsewhere")}):
            self.assertEqual(P.find_tool("nasher", self.tfn), elsewhere)
        explicit = make_exe(self.base / "mine" / "my_nasher")
        with mock.patch.dict(os.environ, {"NASHER": str(explicit)}):
            self.assertEqual(P.find_tool("nasher", self.tfn), explicit)

    def test_unknown_tool_and_candidates(self):
        self.fake_os("Darwin")
        self.assertIsNone(P.find_tool("nwn_bogus", self.tfn))
        cands = P.tool_candidates("nwn_gff", self.tfn)
        self.assertIn(self.tfn / "tools" / "macos_arm64" / "neverwinter" / "nwn_gff", cands)
        self.assertIn(self.tfn.parent / "nwn-tools" / "macos_arm64" / "neverwinter" / "nwn_gff", cands)

    def test_a_tool_that_cannot_execute_degrades_to_skip(self):
        # what a wrong-architecture binary looks like to subprocess: OSError at launch
        broken = make_exe(self.tfn / "tools" / "linux" / "neverwinter" / "nwn_gff", "#!/nonexistent/interpreter\n")
        self.fake_os("Linux", "x86_64")
        proj = P.TfnProject(self.tfn, studio_dir=self.base / ".studio")
        self.assertEqual(proj.tool("nwn_gff"), broken)
        self.assertTrue(V.gff_roundtrip(proj, "{}").startswith("SKIP:"))
        make_exe(self.tfn / "tools" / "linux" / "nwnsc" / "nwnsc", "#!/nonexistent/interpreter\n")
        self.assertTrue(V.compile_script(proj, "x", "void main(){}")[0].startswith("SKIP:"))


class CheckoutErrorTests(IsolatedCase):
    def test_missing_folder_says_so_and_how_to_fix_it(self):
        with self.assertRaises(P.ProjectError) as cm:
            P.TfnProject(self.base / "nope")
        msg = str(cm.exception)
        self.assertIn("does not exist", msg)
        self.assertIn(str(self.base / "nope"), msg)
        self.assertIn("--tfn", msg)
        self.assertIn("TFN_ROOT", msg)
        self.assertIn("doctor", msg)

    def test_folder_without_src_is_explained(self):
        (self.base / "empty").mkdir()
        with self.assertRaises(P.ProjectError) as cm:
            P.TfnProject(self.base / "empty")
        self.assertIn("expected src/are + src/git", str(cm.exception))
        make_checkout(self.base / "half", tfn=False)
        (self.base / "half" / "src" / "are").rmdir()
        with self.assertRaises(P.ProjectError) as cm:
            P.TfnProject(self.base / "half")
        self.assertIn("expected src/are + src/git", str(cm.exception))
        self.assertNotIn("no src/git", str(cm.exception))

    def test_a_file_is_not_a_checkout(self):
        f = self.base / "a_file"
        f.write_text("x")
        with self.assertRaises(P.ProjectError) as cm:
            P.TfnProject(f)
        self.assertIn("a file, not a folder", str(cm.exception))

    def test_hints_name_tfn_checkouts_nearby_but_not_other_nwn_modules(self):
        real = make_checkout(self.base / "work" / "the-frozen-north")
        make_checkout(self.base / "work" / "DwarfStory", tfn=False)        # same layout, different module
        with self.assertRaises(P.ProjectError) as cm:
            P.TfnProject(self.base / "work" / "oops")
        msg = str(cm.exception)
        self.assertIn(str(real), msg)
        self.assertNotIn("DwarfStory", msg)

    def test_pointing_at_the_parent_folder_suggests_the_child(self):
        real = make_checkout(self.base / "git" / "the-frozen-north")
        with self.assertRaises(P.ProjectError) as cm:
            P.TfnProject(self.base / "git")
        self.assertIn(f'--tfn "{real}"', str(cm.exception))

    def test_where_the_path_came_from(self):
        self.assertEqual(P.resolve_root(self.base)[1], "--tfn")
        with mock.patch.dict(os.environ, {"TFN_ROOT": str(self.base)}):
            root, source = P.resolve_root(None)
            self.assertEqual(root, self.base)
            self.assertIn("TFN_ROOT", source)
        self.assertIn("default location", P.resolve_root(None)[1])

    def test_valid_checkout_is_accepted(self):
        proj = P.TfnProject(make_checkout(self.base / "ok"), studio_dir=self.base / ".studio")
        self.assertEqual(proj.root, self.base / "ok")


class NwnInstallTests(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.home = self.base / "home"
        self.home.mkdir()
        p = mock.patch.object(Path, "home", return_value=self.home)
        p.start()
        self.addCleanup(p.stop)

    def test_finds_the_macos_steam_install(self):
        steam = self.home / "Library" / "Application Support" / "Steam" / "steamapps" / "common" / "Neverwinter Nights"
        (steam / "data").mkdir(parents=True)
        (steam / "data" / "nwn_base.key").write_text("")
        self.assertEqual(GD.find_root(), steam)

    def test_home_nwn_data_wins_when_present_and_env_wins_over_all(self):
        (self.home / "nwn-data" / "data").mkdir(parents=True)
        (self.home / "nwn-data" / "data" / "nwn_base.key").write_text("")
        self.assertEqual(GD.find_root(), self.home / "nwn-data")
        with mock.patch.dict(os.environ, {"NWN_ROOT": "/somewhere/else"}):
            self.assertEqual(GD.find_root(), Path("/somewhere/else"))

    def test_no_install_falls_back_to_the_documented_default(self):
        self.assertEqual(GD.find_root(), self.home / "nwn-data")

    def test_user_directory_is_the_first_one_that_exists(self):
        root = self.base / "install"
        self.assertEqual(GD.find_user_dir(root), root / "user")                       # nothing exists: documented default
        (self.home / "Documents" / "Neverwinter Nights").mkdir(parents=True)
        self.assertEqual(GD.find_user_dir(root), self.home / "Documents" / "Neverwinter Nights")
        (root / "user").mkdir(parents=True)
        self.assertEqual(GD.find_user_dir(root), root / "user")

    def test_userdirectory_flag_is_only_passed_when_the_folder_exists(self):
        log = self.base / "args.log"
        fake = make_exe(self.base / "fake_resman", f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n')
        install = self.base / "install"
        (install / "data").mkdir(parents=True)
        (install / "data" / "nwn_base.key").write_text("")
        proj = P.TfnProject(make_checkout(self.base / "tfn"), studio_dir=self.base / ".studio")
        with mock.patch.dict(os.environ, {"NWN_RESMAN_EXTRACT": str(fake)}):
            gd = GD.GameData(proj, root=install, user=self.base / "no-such-user-dir")
            self.assertTrue(gd.available())
            gd.fetch_many(["a.set"])
            self.assertNotIn("--userdirectory", log.read_text())
            log.unlink()
            (self.base / "user-dir").mkdir()
            gd2 = GD.GameData(proj, root=install, user=self.base / "user-dir")
            gd2.fetch_many(["b.set"])
            self.assertIn("--userdirectory", log.read_text())


class ExtractorSalvageTests(IsolatedCase):
    """nwn_resman_extract extracts nothing if any requested resource is missing; the studio must still get the others."""

    def setUp(self):
        super().setUp()
        self.log = self.base / "calls.log"
        # behaves like the real tool: exit 1 and no output files when ANY requested name is "bad*"
        script = (f"#!{sys.executable}\n"
                  "import sys, pathlib\n"
                  "a = sys.argv[1:]\n"
                  "dest = pathlib.Path(a[a.index('-d') + 1])\n"
                  "names = [x for i, x in enumerate(a) if x.endswith(('.wok', '.set')) and a[i - 1] != '-d']\n"
                  f"open({str(self.log)!r}, 'a').write(' '.join(names) + '\\n')\n"
                  "if any(n.startswith('bad') for n in names):\n"
                  "    sys.stderr.write(\"Can't obtain a value from a `none`\\n\"); sys.exit(1)\n"
                  "for n in names:\n"
                  "    (dest / n).write_text('x')\n")
        self.fake = make_exe(self.base / "fake_resman", script)
        self.install = self.base / "install"
        (self.install / "data").mkdir(parents=True)
        (self.install / "data" / "nwn_base.key").write_text("")
        self.proj = P.TfnProject(make_checkout(self.base / "tfn"), studio_dir=self.base / ".studio")
        p = mock.patch.dict(os.environ, {"NWN_RESMAN_EXTRACT": str(self.fake)})
        p.start()
        self.addCleanup(p.stop)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.is_file() else []

    def test_existing_resources_are_extracted_around_a_missing_one(self):
        gd = GD.GameData(self.proj, root=self.install, user=self.base / "none")
        names = [f"tile_{i:02d}.wok" for i in range(10)] + ["bad_tile.wok"]
        gd.fetch_many(names)
        for n in names[:10]:
            self.assertTrue(gd.path(n).is_file(), n)
        self.assertFalse(gd.path("bad_tile.wok").is_file())
        self.assertIsNone(gd.read_text("bad_tile.wok"))
        self.assertLess(len(self.calls()), 10, self.calls())          # bisected, not one run per file

    def test_a_missing_resource_is_not_requested_twice(self):
        gd = GD.GameData(self.proj, root=self.install, user=self.base / "none")
        gd.fetch_many(["a.wok", "bad_one.wok"])
        n = len(self.calls())
        gd.fetch_many(["bad_one.wok", "a.wok"])
        gd.fetch("bad_one.wok")
        self.assertEqual(len(self.calls()), n)

    def test_a_broken_extractor_gives_up_instead_of_running_once_per_file(self):
        make_exe(self.fake, f"#!{sys.executable}\nimport sys\nopen({str(self.log)!r}, 'a').write('run\\n')\nsys.exit(1)\n")
        gd = GD.GameData(self.proj, root=self.install, user=self.base / "none")
        gd.fetch_many([f"t{i}.wok" for i in range(150)])
        self.assertLessEqual(len(self.calls()), GD.GameData.MAX_RUNS_WITHOUT_SUCCESS)
        self.assertIsNone(gd.fetch("t3.wok"))


class CommandLineTests(IsolatedCase):
    def test_extract_tfn_accepts_the_option_anywhere(self):
        self.assertEqual(cli.extract_tfn(["--tfn", "x", "status"]), (["status"], "x"))
        self.assertEqual(cli.extract_tfn(["serve", "--tfn", "x", "--port", "9"]), (["serve", "--port", "9"], "x"))
        self.assertEqual(cli.extract_tfn(["status", "--tfn=/a b/c"]), (["status"], "/a b/c"))
        self.assertEqual(cli.extract_tfn(["quest", "stage", "q_x", "--tfn", "x"]), (["quest", "stage", "q_x"], "x"))
        self.assertEqual(cli.extract_tfn(["status"]), (["status"], None))

    def test_a_dangling_option_is_left_for_argparse_to_report(self):
        self.assertEqual(cli.extract_tfn(["status", "--tfn"]), (["status", "--tfn"], None))
        self.assertEqual(cli.extract_tfn(["--tfn", "--json", "status"]), (["--tfn", "--json", "status"], None))

    def test_bad_path_before_or_after_the_command_gives_the_same_friendly_error(self):
        for argv in (["--tfn", str(self.base / "nope"), "status"], ["status", "--tfn", str(self.base / "nope")],
                     ["serve", f"--tfn={self.base / 'nope'}"]):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(cli.main(argv), 2, argv)
            self.assertIn("does not exist", err.getvalue(), argv)
            self.assertIn(str(self.base / "nope"), err.getvalue(), argv)


class ServeErrorTests(IsolatedCase):
    def test_port_already_in_use_is_a_clear_error_not_a_traceback(self):
        import socket
        from tfnstudio import server
        busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        self.addCleanup(busy.close)
        port = busy.getsockname()[1]
        studio = mock.Mock()
        with self.assertRaises(P.ProjectError) as cm:
            server.serve(studio, "127.0.0.1", port)
        self.assertIn(f"cannot listen on 127.0.0.1:{port}", str(cm.exception))
        self.assertIn(f"--port {port + 1}", str(cm.exception))


class ManualCommandTests(IsolatedCase):
    """`manual` and the pointers to MANUAL.html: it must work (and be findable) with nothing set up."""

    def setUp(self):
        super().setUp()
        self.studio = P.STUDIO_ROOT
        self.studio.mkdir(parents=True)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_manual_prints_the_location_and_needs_no_checkout(self):
        (self.studio / "MANUAL.html").write_text("<html>x</html>", encoding="utf-8")
        code, out, _ = self.run_cli("manual")                      # no --tfn, no TFN anywhere
        self.assertEqual(code, 0)
        self.assertIn(str(self.studio / "MANUAL.html"), out)
        self.assertIn("file://", out)

    def test_manual_generates_the_html_when_only_the_markdown_exists(self):
        (self.studio / "MANUAL.md").write_text("# Title\n\n## One\n\ntext\n", encoding="utf-8")
        code, out, _ = self.run_cli("manual")
        self.assertEqual(code, 0)
        self.assertIn("generated it from MANUAL.md", out)
        html = (self.studio / "MANUAL.html").read_text(encoding="utf-8")
        self.assertIn("<title>Title</title>", html)

    def test_manual_without_any_manual_is_a_clear_error(self):
        code, _, err = self.run_cli("manual")
        self.assertEqual(code, 2)
        self.assertIn("MANUAL.html", err)

    def test_manual_open_launches_the_browser_with_a_file_url(self):
        (self.studio / "MANUAL.html").write_text("<html>x</html>", encoding="utf-8")
        with mock.patch("tfnstudio.doctor.webbrowser.open") as opened:
            self.assertEqual(self.run_cli("manual", "--open")[0], 0)
        opened.assert_called_once_with((self.studio / "MANUAL.html").as_uri())

    def test_the_checkout_error_points_at_the_manual(self):
        with self.assertRaises(P.ProjectError) as cm:
            P.TfnProject(self.base / "nope")
        self.assertNotIn("MANUAL.html", str(cm.exception))          # nothing to point at yet
        (self.studio / "MANUAL.html").write_text("x", encoding="utf-8")
        with self.assertRaises(P.ProjectError) as cm:
            P.TfnProject(self.base / "nope")
        self.assertIn("needs no setup", str(cm.exception))
        self.assertIn(str(self.studio / "MANUAL.html"), str(cm.exception))

    def test_doctor_lists_the_manual(self):
        (self.studio / "MANUAL.html").write_text("x", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run_doctor(str(self.base / "nope"), port=0)
        self.assertIn(f"Manual (open in any browser, no setup needed): {self.studio / 'MANUAL.html'}", out.getvalue())


class DoctorTests(IsolatedCase):
    def run_doctor(self, tfn):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_doctor(str(tfn), port=0)
        return code, out.getvalue()

    def test_missing_checkout_is_the_failure_and_is_explained(self):
        code, text = self.run_doctor(self.base / "nope")
        self.assertEqual(code, 1)
        self.assertIn("[FAIL]", text)
        self.assertIn(str(self.base / "nope"), text)
        self.assertIn("--tfn", text)
        self.assertIn("Fix the [FAIL] items first", text)

    def test_good_checkout_with_missing_optional_tools_is_ready_with_warnings(self):
        self.fake_os("Darwin")
        code, text = self.run_doctor(make_checkout(self.base / "the-frozen-north"))
        self.assertEqual(code, 0, text)
        self.assertIn("TFN checkout:", text)
        self.assertIn("macos_arm64", text)               # tells a Mac user which tool folder is expected
        self.assertIn("nwn_gff not found", text)
        self.assertIn("Ready to run", text)

    def test_a_non_tfn_module_is_flagged(self):
        code, text = self.run_doctor(make_checkout(self.base / "other", tfn=False))
        self.assertEqual(code, 0)
        self.assertIn("is this really The Frozen North", text)


if __name__ == "__main__":
    unittest.main()
