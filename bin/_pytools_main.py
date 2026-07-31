#!/usr/bin/env python3
"""Multi-command dispatcher for Q-nwn-manager's Python tools.

This is the entry point PyInstaller compiles into a single native binary
(nwn-pytools) so end users don't need python3 installed. bin/nwn-wiki,
bin/nwn-area-editor, bin/nwn-wiki-activity, and bin/check-dlg-integrity are
bundled as data files (not statically imported - their filenames aren't
valid module identifiers) and loaded here via SourceFileLoader, generalizing
the exact technique bin/nwn-wiki-activity already uses to load bin/nwn-wiki
at runtime. Loading them from a real path on disk (the bin/ directory in
dev mode, the PyInstaller extraction root when frozen) means their own
__file__-relative resource lookups (wiki_data/, wiki_assets/) keep working
unchanged either way.

Usage: nwn-pytools <subcommand> [args...]
Subcommands: wiki, area-editor, wiki-activity, check-dlg-integrity,
             hak-list, tlk-name
"""
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = {
    "wiki": "nwn-wiki",
    "area-editor": "nwn-area-editor",
    "wiki-activity": "nwn-wiki-activity",
    "check-dlg-integrity": "check-dlg-integrity",
}


def base_dir():
    """Directory holding the real scripts + wiki_data/wiki_assets - the
    PyInstaller extraction root when frozen, else bin/ (this file's own
    directory in a source checkout)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def load_script(name):
    """Load one of the real scripts as a module, by source path - the same
    technique bin/nwn-wiki-activity's _load_nwn_wiki() already uses."""
    path = base_dir() / name
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _hak_list(argv):
    """Print each declared hak's name, one per line - replicates the former
    inline `python3 -c` lookup in bin/nwn-manager's extract_hak_includes."""
    if not argv:
        print("usage: nwn-pytools hak-list <module.ifo.json>", file=sys.stderr)
        return 2
    try:
        with open(argv[0], encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return 0
    for h in d.get("Mod_HakList", {}).get("value", []):
        n = h.get("Mod_Hak", {}).get("value", "").strip()
        if n:
            print(n)
    return 0


def _tlk_name(argv):
    """Print the module's custom TLK name, if any - replicates the former
    inline `python3 -c` lookup in bin/nwn-manager's extract_tlks."""
    if not argv:
        print("usage: nwn-pytools tlk-name <module.ifo.json>", file=sys.stderr)
        return 2
    try:
        with open(argv[0], encoding="utf-8") as fh:
            d = json.load(fh)
        print(str(d.get("Mod_CustomTlk", {}).get("value", "")).strip())
    except (OSError, ValueError):
        pass
    return 0


def dispatch(argv):
    """argv is sys.argv-shaped: argv[0] is this program, argv[1] the
    subcommand. Returns a process exit code."""
    if len(argv) < 2:
        print("usage: nwn-pytools <subcommand> [args...]", file=sys.stderr)
        print("subcommands: %s, hak-list, tlk-name" %
              ", ".join(SCRIPTS), file=sys.stderr)
        return 2
    sub = argv[1]
    rest = argv[2:]

    if sub == "hak-list":
        return _hak_list(rest)
    if sub == "tlk-name":
        return _tlk_name(rest)
    if sub not in SCRIPTS:
        print("nwn-pytools: unknown subcommand %r" % sub, file=sys.stderr)
        return 2

    script_path = base_dir() / SCRIPTS[sub]
    mod = load_script(SCRIPTS[sub])
    if sub == "check-dlg-integrity":
        # main(argv) takes argv explicitly - no sys.argv rewrite needed.
        return mod.main([str(script_path)] + rest)
    # wiki / area-editor / wiki-activity read bare sys.argv via argparse.
    sys.argv = [str(script_path)] + rest
    return mod.main()


def main():
    return dispatch(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
