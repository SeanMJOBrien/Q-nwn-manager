"""`tfn-studio doctor`: a readable environment check.

Works even when the TFN checkout cannot be found (that is exactly when you need it), so it only uses
path helpers and never builds the content indexes.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import gamedata as GD
from . import project as P
from .mdhtml import render_page, write_page

MIN_PYTHON = (3, 9)
TOOLS = (("nwn_gff", "JSON round-trip validation of everything the studio generates"),
         ("nwnsc", "compile check for generated scripts"),
         ("nwn_resman_extract", "exact ground heights + walkability from the NWN install"),
         ("nasher", "only needed to build the module yourself (the studio does not run it)"))


class Report:
    COLORS = {"ok": "\033[32m", "warn": "\033[33m", "FAIL": "\033[31m", "info": "\033[2m", "off": "\033[0m"}

    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0
        self._tty = sys.stdout.isatty()

    def line(self, level: str, text: str, *more: str) -> None:
        tag = f"[{level}]".ljust(6)
        if self._tty:
            tag = f"{self.COLORS[level]}{tag}{self.COLORS['off']}"
        print(f"{tag} {text}")
        for extra in more:
            if extra:
                print(f"         {extra}")
        if level == "FAIL":
            self.failures += 1
        elif level == "warn":
            self.warnings += 1


def _git_version() -> str | None:
    git = shutil.which("git")
    if not git:
        return None
    try:
        out = subprocess.run([git, "--version"], capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _git_state(root: Path) -> tuple[str, int] | None:
    git = shutil.which("git")
    if not git:
        return None
    try:
        branch = subprocess.run([git, "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, timeout=30).stdout.strip()
        status = subprocess.run([git, "-C", str(root), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return branch or "(detached)", len([ln for ln in status.splitlines() if ln.strip()])


def manual_path() -> Path:
    return P.STUDIO_ROOT / "MANUAL.html"


def run_manual(open_browser: bool = False) -> int:
    """Print where MANUAL.html is - a single file that needs no checkout, tools or server - and optionally open it."""
    path = manual_path()
    if not path.is_file():
        source = P.STUDIO_ROOT / "MANUAL.md"
        if not source.is_file():
            print(f"error: neither MANUAL.html nor MANUAL.md found in {P.STUDIO_ROOT}", file=sys.stderr)
            return 2
        write_page(path, render_page(source.read_text(encoding="utf-8")))
        print("(MANUAL.html was missing; generated it from MANUAL.md)")
    print(path)
    print(path.as_uri())
    if open_browser:
        webbrowser.open(path.as_uri())
    return 0


def run_doctor(tfn_arg: str | None = None, port: int = 8350) -> int:
    """Print the checklist; the exit status is 0 unless something required is missing."""
    rep = Report()
    prog = P.prog_name()
    print("TFN Content Studio - environment check\n")

    # --- Python -----------------------------------------------------------------------------------
    v = sys.version_info
    if v[:2] >= MIN_PYTHON:
        rep.line("ok", f"Python {v[0]}.{v[1]}.{v[2]}", sys.executable)
    else:
        rep.line("FAIL", f"Python {v[0]}.{v[1]}.{v[2]} is too old (need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)",
                 "macOS: `brew install python`, then run `python3 bin/tfn-studio ...`")
    rep.line("info", f"{platform.system()} {platform.release()} ({platform.machine()}); tool folder expected: "
                     f"{', '.join(P.platform_dirs())}")
    here = Path(__file__).resolve().parent
    rep.line("ok" if (here / "web" / "static").is_dir() else "FAIL", f"Studio folder: {here.parent}",
             "" if (here / "web" / "static").is_dir() else "the web pages are missing - re-copy the whole folder")

    # --- git --------------------------------------------------------------------------------------
    gv = _git_version()
    if gv:
        rep.line("ok", gv)
    else:
        rep.line("warn", "git not found", "the studio uses git to refuse overwriting your uncommitted files and to show the branch")

    # --- TFN checkout -----------------------------------------------------------------------------
    root, source = P.resolve_root(tfn_arg)
    problem = P.checkout_problem(root, source)
    checkout_ok = problem is None
    if checkout_ok:
        rep.line("ok", f"TFN checkout: {root}", f"(taken from {source})")
        if not P.looks_like_tfn(root):
            rep.line("warn", "this has src/are and src/git but not TFN's own files (src/nss/inc_quest.nss, SPAWN_SYSTEM.md)",
                     "is this really The Frozen North, or a different NWN module?")
        state = _git_state(root)
        if state:
            branch, dirty = state
            rep.line("ok", f"branch {branch}, {dirty} uncommitted file(s)",
                     "Apply refuses to overwrite files that have uncommitted changes" if dirty else "")
        for sub in ("utc", "utp", "ute", "dlg", "jrl", "nss"):
            if not (root / "src" / sub).is_dir():
                rep.line("warn", f"src/{sub} is missing - generators that need it will fail")
    else:
        first, *rest = problem.splitlines()
        rep.line("FAIL", first, *[ln[2:] if ln.startswith("  ") else ln for ln in rest])

    # --- tools ------------------------------------------------------------------------------------
    missing_tool = False
    for name, purpose in TOOLS:
        found = P.find_tool(name, root)
        if found:
            rep.line("ok", f"{name}: {found}")
        else:
            missing_tool = True
            rep.line("warn", f"{name} not found - {purpose} will be skipped", f"(or point ${name.upper()} at the program)")
    if missing_tool:
        places = [str(r / plat) for r in P.tool_roots(root) for plat in P.platform_dirs()]
        rep.line("info", "tools are looked for in (folders neverwinter/, nwnsc/, nasher/ inside):", *places,
                 "$NWN_TOOLS can add another place")

    # --- NWN install ------------------------------------------------------------------------------
    gd_root = GD.find_root()
    key = gd_root / "data" / "nwn_base.key"
    if key.is_file():
        rep.line("ok", f"NWN install: {gd_root}", "exact ground heights and walkability are available (needs nwn_resman_extract above)")
    else:
        rep.line("warn", f"NWN install not found (looked for data/nwn_base.key under {gd_root})",
                 "without it the studio still works, but object heights are guessed from neighbours and walkability is unchecked",
                 'set it with:  export NWN_ROOT="/path/to/Neverwinter Nights"   (the folder that contains data/)')

    # --- port -------------------------------------------------------------------------------------
    if _port_free(port):
        rep.line("ok", f"port {port} is free", f"{prog} serve  ->  http://127.0.0.1:{port}/")
    else:
        rep.line("warn", f"port {port} is already in use", f"another studio running? use:  {prog} serve --port {port + 1}")

    if manual_path().is_file():
        rep.line("info", f"Manual (open in any browser, no setup needed): {manual_path()}")

    print()
    if rep.failures:
        print(f"{rep.failures} problem(s), {rep.warnings} warning(s). Fix the [FAIL] items first, then run `{prog} doctor` again.")
        return 1
    if rep.warnings:
        print(f"Ready to run, with {rep.warnings} warning(s) (optional features reduced). Start with:  {prog} serve")
    else:
        print(f"Everything looks good. Start with:  {prog} serve")
    return 0
