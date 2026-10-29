#!/usr/bin/env python3
"""Regenerate MANUAL.html (the single-file, browser-readable manual) from MANUAL.md. Standard library only.

    python3 scripts/build_manual.py            # write MANUAL.html next to MANUAL.md
    python3 scripts/build_manual.py --check    # exit 1 if MANUAL.html is missing or out of date (the tests run this check)

MANUAL.md is the source of truth: edit it, run this script, and commit both files. The HTML is self-contained (inline CSS and
JavaScript, no network), so it can be opened straight from the file system and is also served by the studio at /manual.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tfnstudio.mdhtml import render_page, write_page  # noqa: E402


def render(root: Path = ROOT) -> str:
    return render_page((root / "MANUAL.md").read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="do not write; fail when MANUAL.html is missing or stale")
    args = ap.parse_args(argv)
    target = ROOT / "MANUAL.html"
    page = render()
    if args.check:
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current != page:
            print("MANUAL.html is " + ("missing" if current is None else "out of date with MANUAL.md")
                  + ": run  python3 scripts/build_manual.py", file=sys.stderr)
            return 1
        print("MANUAL.html is up to date")
        return 0
    write_page(target, page)
    print(f"wrote {target} ({len(page.encode('utf-8')):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
