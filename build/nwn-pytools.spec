# PyInstaller spec for nwn-pytools: a single --onedir native build of
# bin/_pytools_main.py (the multi-command dispatcher for bin/nwn-wiki,
# bin/nwn-area-editor, bin/nwn-wiki-activity, bin/check-dlg-integrity), so
# end users don't need python3 installed.
#
# --onedir, not --onefile: nwn-wiki spawns a second copy of itself (for
# wiki-activity) on every build with activity data - onefile would re-extract
# its whole payload on that second launch too. onedir also has fewer Windows
# Defender/SmartScreen false-positive issues than onefile's self-extracting
# bootloader.
#
# Build (per platform, from the repo root):
#   pip install pyinstaller
#   pyinstaller build/nwn-pytools.spec
# Output: dist/nwn-pytools/ (copy into nwn-tools/<platform>/nwn-pytools/).
#
# datas below bundle the four real scripts and wiki_data/wiki_assets flat at
# the bundle root, mirroring their layout as siblings in bin/ in a source
# checkout - this is what lets nwn-wiki's/nwn-area-editor's existing
# __file__-relative resource lookups (DATA_DIR, ASSETS_DIR, _STOCK_DATA_DIR)
# keep working unchanged when frozen. See bin/_pytools_main.py's base_dir().
#
# hiddenimports below exists because the four scripts are loaded dynamically
# via SourceFileLoader (see bin/_pytools_main.py), not statically imported -
# PyInstaller's analyzer can't trace into that, so every stdlib module they
# use must be declared by hand. KEEP THIS IN SYNC MANUALLY: a new `import`
# added inside any of the four scripts won't fail a build, only a run that
# actually exercises that code path (e.g. sqlite3 is a lazy, function-local
# import in bin/nwn-wiki, only hit when a module has bestiarybook data).

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))
BIN = os.path.join(REPO_ROOT, "bin")

HIDDEN_IMPORTS = [
    "__future__",  # from __future__ import annotations in nwn-wiki(-activity) -
                   # invisible to PyInstaller's analyzer same as everything
                   # else in the 4 scripts, but NOT auto-bundled into
                   # base_library.zip by default like most stdlib modules are
                   # (confirmed by an actual build: omitting it produces a
                   # real ModuleNotFoundError at runtime, not just a warning).
    "argparse", "collections", "datetime", "glob", "html", "http.server",
    "importlib.machinery", "importlib.util", "json", "math", "mimetypes",
    "os", "pathlib", "random", "re", "shutil", "sqlite3", "struct",
    "subprocess", "sys", "tempfile", "threading", "time", "typing",
    "urllib.parse", "uuid",
]

a = Analysis(
    [os.path.join(BIN, "_pytools_main.py")],
    pathex=[BIN],
    datas=[
        (os.path.join(BIN, "nwn-wiki"), "."),
        (os.path.join(BIN, "nwn-area-editor"), "."),
        (os.path.join(BIN, "nwn-wiki-activity"), "."),
        (os.path.join(BIN, "check-dlg-integrity"), "."),
        (os.path.join(BIN, "wiki_data"), "wiki_data"),
        (os.path.join(BIN, "wiki_assets"), "wiki_assets"),
    ],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nwn-pytools",
    console=True,
    strip=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="nwn-pytools",
)
