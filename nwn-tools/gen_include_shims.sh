#!/usr/bin/env bash
# Generates symlinks in <shim-dir> for #include directives whose referenced
# filename only differs in case from the actual file on disk.
#
# nwnsc resolves #include "X" by looking for a file literally named X.nss.
# NWScript source (notably the BioWare base scripts, and a handful of
# project files) was written assuming a case-insensitive filesystem and uses
# inconsistent case in #include directives (e.g. #include "NW_I0_GENERIC"
# for nw_i0_generic.nss). On a case-sensitive filesystem (Linux) those
# includes fail with NSC1085 "Unable to open the include file". This script
# regenerates a directory of case-correcting symlinks each run so it stays
# in sync as source files change.
#
# Usage: gen_include_shims.sh <shim-dir> <source-dir> [<source-dir> ...]
# <shim-dir> and <source-dir> may be relative (to the current directory) or
# absolute. Run from the project's repo root, e.g.:
#   ../nwn-tools/gen_include_shims.sh .build/include-shims . /path/to/nwn-base-scripts
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <shim-dir> <source-dir> [<source-dir> ...]" >&2
    exit 1
fi

SHIM_DIR="$1"
shift

rm -rf "$SHIM_DIR"
mkdir -p "$SHIM_DIR"

python3 - "$SHIM_DIR" "$@" <<'EOF'
import os, re, sys, glob

shim_dir = sys.argv[1]
dirs = sys.argv[2:]

files = []
for d in dirs:
    files += glob.glob(os.path.join(d, "*.nss"))

all_basenames = set()
lower_to_actual = {}
for f in files:
    base = os.path.basename(f)[:-4]
    all_basenames.add(base)
    lower_to_actual.setdefault(base.lower(), (base, os.path.dirname(f)))

include_re = re.compile(r'#include\s+"([^"]+)"')

shims = {}
for f in files:
    with open(f, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = include_re.search(line)
            if not m:
                continue
            inc = m.group(1)
            if inc in all_basenames or inc in shims:
                continue
            target = lower_to_actual.get(inc.lower())
            if target:
                shims[inc] = target

for inc, (actual_base, actual_dir) in shims.items():
    link_path = os.path.join(shim_dir, inc + ".nss")
    target_path = os.path.relpath(os.path.join(actual_dir, actual_base + ".nss"), shim_dir)
    os.symlink(target_path, link_path)

print(f"Generated {len(shims)} include shim(s) in {shim_dir}")
EOF
