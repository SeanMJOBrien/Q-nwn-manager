# Updating bundled build tools

This repo vendors prebuilt third-party CLI tools under `tools/linux/`,
`tools/macos_arm64/`, and `tools/win/` so the `*_nasher_install.sh` /
`*_nasher_install.bat` scripts work without any extra setup. Each subsection
below lists where a tool comes from, where its files land in this repo, and
how to update it.

General recipe: download the release asset for your platform, unzip it
somewhere scratch, then copy the named binaries over the existing files in
`tools/<platform>/...` **keeping the same filenames** (so the build scripts
need no changes). On Linux/macOS, `chmod +x` (or `775`) the new binaries.
Always re-run the relevant `*_nasher_install` script afterwards and confirm
it still reports "Success: All executable scripts have a matching compiled
(.ncs) script" and "Build succeeded."

## neverwinter.nim (`nwn_gff`, `nwn_erf`, `nwn_erf_tlkify`, `nwn_tlk`, ...)

- Source: https://github.com/niv/neverwinter.nim/releases
- As of 2026-06-11, all 3 platforms are on **v2.1.2** (2025-08-17).
- Download URL pattern:
  `https://github.com/niv/neverwinter.nim/releases/download/<tag>/<asset>`
- Release assets (zip, flat layout — no subdirectory):
  - `neverwinter-x86_64-linux-gnu.zip` → copy `nwn_gff`, `nwn_erf`,
    `nwn_erf_tlkify`, `nwn_tlk` into `tools/linux/neverwinter/`
  - `neverwinter-aarch64-macos.zip` → same 4 files into
    `tools/macos_arm64/neverwinter/`
  - `neverwinter-x86_64-windows.zip` → copy `nwn_gff.exe`, `nwn_erf.exe`,
    `nwn_erf_tlkify.exe`, `nwn_tlk.exe` into `tools/win/neverwinter64/`
- The Linux release binaries ship with debug symbols (~12MB each, vs ~2MB
  for macOS/Windows). Run `strip` on them after copying to keep repo size
  down — this doesn't affect functionality.
- Why this matters: versions before ~2.0 use an older `cexolocstring` JSON
  schema (StrRef as a field-level `id` sibling) and silently drop StrRefs
  / fail with `parseInt("id")` errors when converting the newer schema
  (`value.id`) used by `src/**/*.json` in this repo. Don't downgrade below
  ~2.0 without re-checking this.
- The Windows build also needs `pcre64.dll` and `sqlite3_64.dll` (already
  present in `tools/win/neverwinter64/`); the new `nwn_*.exe` binaries
  additionally rely on the Universal CRT (`api-ms-win-crt-*.dll`), which
  ships with Windows 10/11 by default — no extra DLLs needed for that.

## nasher (`nasher` / `nasher.exe`)

- Source: https://github.com/squattingmonk/nasher/releases
- Release assets: `nasher_linux.tar.gz`, `nasher_macos.tar.gz`,
  `nasher_windows.zip`
  (`https://github.com/squattingmonk/nasher/releases/download/<tag>/<asset>`)
- As of 2026-06-11: Linux bundle reports **0.19.0** (Aug 2022); the
  Windows/macOS bundles appear to already be on a newer 0.20.x/1.1.x line
  (exact version unconfirmed — `nasher --version` on Windows binary embeds
  both "0.20.0" and "1.1.1" strings). Latest upstream is **v1.1.2**
  (2025-09-18) — a major version jump from 0.x.
- **Not updated by this pass.** nasher 1.x may have CLI/config changes
  relative to 0.19/0.20 (this repo's build scripts pass specific
  `--gffUtil`/`--erfUtil`/`--nssFlags`/etc. flags to `nasher pack`/`install`).
  Before bumping, test a full build on each platform and check
  `tools/<platform>/nasher/CHANGELOG.md` (bundled with each release) for
  breaking changes between the bundled version and the target version.

## nwnsc (NWScript compiler)

- Source: https://github.com/nwneetools/nwnsc/releases
- Release assets: `nwnsc-linux-v<ver>.zip`, `nwnsc-mac-v<ver>.zip`,
  `nwnsc-win-v<ver>.zip`
  (`https://github.com/nwneetools/nwnsc/releases/download/v<ver>/<asset>`)
- Bundled version is **v1.1.5** (built 2023-03-25), which is also the
  **latest release** as of 2026-06-11 — no update available/needed.

## sqlite3

- Source: https://www.sqlite.org/download.html
- Precompiled tools: `sqlite-tools-linux-x64-<ver>.zip`,
  `sqlite-tools-osx-arm64-<ver>.zip`, `sqlite-tools-win-x64-<ver>.zip`
  (also `sqlite-tools-win-arm64-<ver>.zip` if ever needed)
- Bundled version is **3.47.0** (Oct 2024); latest as of 2026-06-11 is
  **3.53.0.2**. Not updated by this pass — low priority, used for the PW's
  database tooling rather than the build pipeline itself.
