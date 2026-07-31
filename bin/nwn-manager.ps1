#Requires -Version 5.1
<#
nwn-manager.ps1 -- PowerShell port of bin/nwn-manager (multi-module manager
for NWN1 .mod files). Thin wrapper around nasher (squattingmonk/nasher) and
the neverwinter.nim CLIs (niv/neverwinter.nim). Ports the same subcommands
as the bash original 1:1; see that file's comments for background on *why*
each step exists (hak-include extraction, include-case shims, build stamp,
etc). This file only notes where Windows semantics forced a different
approach.
#>

$PROG = 'nwn-manager.ps1'
$SCRIPT_DIR = $PSScriptRoot
$ErrorActionPreference = 'Stop'

function Write-ErrLine {
    param([string]$Message)
    [Console]::Error.WriteLine($Message)
}

function Get-Platform {
    if ($PSVersionTable.PSVersion.Major -ge 6) {
        if ($IsWindows) { return 'win' }
        elseif ($IsMacOS) { return 'macos_arm64' }
        elseif ($IsLinux) { return 'linux' }
        else { return '' }
    }
    return 'win'
}
$script:PLAT = Get-Platform

function Add-ToolPath {
    param([string]$Dir)
    if ($Dir -and (Test-Path -LiteralPath $Dir -PathType Container)) {
        $env:PATH = "$env:PATH;$Dir"
    }
}

# Make external tools discoverable as a PATH fallback (bundled nwn-tools/,
# then the usual Nim install bin dirs) -- mirrors the bash original.
if ($script:PLAT) {
    $roots = @($env:NWN_TOOLS_DIR, (Join-Path $SCRIPT_DIR '..\nwn-tools'), (Join-Path $SCRIPT_DIR '..\..\nwn-tools')) |
        Where-Object { $_ }
    foreach ($r in $roots) {
        $platDir = Join-Path $r $script:PLAT
        if (Test-Path -LiteralPath $platDir -PathType Container) {
            foreach ($d in @('nasher', 'neverwinter', 'neverwinter64', 'nwnsc', 'sqlite')) {
                Add-ToolPath (Join-Path $platDir $d)
            }
        }
    }
}
if ($env:NWN_TOOLS_DIR -and (Test-Path -LiteralPath $env:NWN_TOOLS_DIR -PathType Container)) {
    Add-ToolPath $env:NWN_TOOLS_DIR
}
foreach ($d in @((Join-Path $HOME '.nimble\bin'), (Join-Path $HOME '.local\bin'))) {
    Add-ToolPath $d
}

# Locate a compiled nwn-pytools binary (built from bin/_pytools_main.py via
# build/nwn-pytools.spec) under the same nwn-tools/<platform>/ convention
# used above for nasher/nwn_gff/nwnsc, so wiki/console/edit-areas/serve and
# the repack dlg-check gate can run without python3 installed. Empty when
# none is found -- Invoke-PyTool below falls back to today's `python3
# <script>` behavior in that case.
$script:PYTOOLS_BIN = $null
if ($script:PLAT) {
    $ptExe = if ($script:PLAT -eq 'win') { 'nwn-pytools.exe' } else { 'nwn-pytools' }
    $ptRoots = @($env:NWN_TOOLS_DIR, (Join-Path $SCRIPT_DIR '..\nwn-tools'), (Join-Path $SCRIPT_DIR '..\..\nwn-tools')) |
        Where-Object { $_ }
    foreach ($r in $ptRoots) {
        $cand = Join-Path (Join-Path (Join-Path $r $script:PLAT) 'nwn-pytools') $ptExe
        if (Test-Path -LiteralPath $cand -PathType Leaf) {
            $script:PYTOOLS_BIN = $cand
            break
        }
    }
}

# Run a Python-based subcommand: prefer the compiled nwn-pytools binary when
# found, else fall back to running the real script under python3 (or, for
# the two dispatcher-only lookups with no standalone script, the dispatcher
# source file itself). Mirrors bin/nwn-manager's run_pytool().
function Invoke-PyTool {
    param([string]$Sub, [string[]]$RestArgs = @())
    if ($script:PYTOOLS_BIN) {
        & $script:PYTOOLS_BIN $Sub @RestArgs
    } elseif ($Sub -eq 'check-dlg-integrity') {
        & python3 (Join-Path $SCRIPT_DIR 'check-dlg-integrity') @RestArgs
    } elseif ($Sub -in @('hak-list', 'tlk-name')) {
        & python3 (Join-Path $SCRIPT_DIR '_pytools_main.py') $Sub @RestArgs
    } else {
        & python3 (Join-Path $SCRIPT_DIR "nwn-$Sub") @RestArgs
    }
}

function Show-Usage {
    @"
$PROG -- multi-module manager for NWN1 .mod files (PowerShell port).

Usage:
  $PROG init <project-dir> <module.mod>
                          Create a new module project. Initializes
                          nasher.cfg, populates <dir>/unpacked/ from
                          <module.mod>, writes .gitignore and a stub
                          README.md.

  $PROG unpack [<module.mod>]
                          Refresh ./unpacked/ from the .mod. With no
                          argument, re-unpacks the path stored in
                          .nasher/source. Run from inside a project
                          (or any subdir).

  $PROG repack [args...]  Build .mod from ./unpacked/ via 'nasher
                          pack'. If a path is recorded in
                          .nasher/source, copy the built .mod there.
                          Extra args pass through to nasher.

  $PROG wiki [--out <dir>] [args...]
                          Generate a static HTML wiki from
                          ./unpacked/ into <project>/docs/ (or --out).
                          docs/ is the folder GitHub Pages publishes
                          from. Extra args pass through to nwn-wiki.

  $PROG console [--projects-dir <dir>] [args...]
                          Serve the multi-project web console: a home page to
                          upload/ingest a .mod into a new project, rebuild its
                          wiki, build & download the packed .mod, and bulk-edit
                          areas. Each project lives in its own subdirectory
                          under --projects-dir (default: <repo>/projects).
                          Extra args pass through to the console (--port,
                          --host, --url-prefix, --wiki-shell, --wiki-base, --nav).

  $PROG edit-areas [--dir <dir>] [args...]
                          Serve a local web UI for bulk-editing area event
                          scripts, lighting/fog, and tags/resrefs directly
                          against ./unpacked/*.are.json (or --dir). Extra
                          args pass through to nwn-area-editor (--port,
                          --url-prefix, --wiki-shell, --wiki-base, --nav).

  $PROG serve --log-dir <dir> [options]
                          Monitor player activity via NWN server logs.
                          Polls every 5 minutes (configurable). When
                          the last player leaves, optionally refreshes
                          activity.html and publishes it to git.

                          Options:
                            --log-dir <dir>        NWN server log dir
                                                   (repeat for multiple)
                            --poll-interval <min>  Check interval in
                                                   minutes (default: 5)
                            --auto-publish         On player session end:
                                                   refresh activity.html
                                                   (and ServerFirsts.html
                                                   if --db-dir set),
                                                   git commit, and push
                            --activity-cache <path> JSON session cache
                                                   (default: first
                                                   log-dir/activity-
                                                   sessions.json)
                            --db-dir <dir>         Campaign database dir
                                                   (bestiarydb.sqlite3).
                                                   Refreshes ServerFirsts
                                                   page alongside activity
                            --backup-cmd <cmd>     Command to run at each idle
                                                   moment (no players online).
                                                   Expected to self-gate (e.g.
                                                   once/day); used to snapshot
                                                   server state opportunistically

  $PROG -h | --help       Show this help.

Per-project layout (created by 'init'):
  nasher.cfg     project + target config (committed)
  unpacked/      source tree of GFF JSON + .nss scripts (committed)
  dist/          packed .mod output (gitignored)
  docs/          generated wiki -- committed; GitHub Pages serves from here
  .nasher/       nasher cache + last-used source path (gitignored)

Prerequisites (must be on PATH):
  nasher              -- nimble install nasher
  nwn_gff, nwn_erf    -- nimble install neverwinter
  nwnsc               -- bundled in nwn-tools/<platform>/nwnsc/, or
                         squattingmonk/nwnsc release (used by 'repack' to
                         compile scripts on all platforms)
  python3             -- for 'wiki' and 'console' subcommands
"@ | Write-Host
}

function Invoke-Preflight {
    param([string[]]$Bins)
    $missing = $false
    foreach ($bin in $Bins) {
        # A compiled nwn-pytools binary makes python3 optional - Invoke-PyTool
        # already prefers it over `& python3 <script>` at every call site.
        if ($bin -eq 'python3' -and $script:PYTOOLS_BIN) { continue }
        if (-not (Get-Command $bin -ErrorAction SilentlyContinue)) {
            $hint = switch ($bin) {
                'nasher' { 'nimble install nasher' }
                { $_ -in @('nwn_gff', 'nwn_erf', 'nwn_script_comp') } { 'nimble install neverwinter' }
                'nwnsc' { 'bundled in nwn-tools/<platform>/nwnsc/, or squattingmonk/nwnsc release' }
                'python3' { 'install Python 3 (system package)' }
                default { '' }
            }
            Write-ErrLine "error: required tool '$bin' not on PATH"
            if ($hint) { Write-ErrLine "       install with: $hint" }
            $missing = $true
        }
    }
    if ($missing) { exit 1 }
}

function Get-ArgsSlice {
    param([string[]]$Arr, [int]$Start)
    if (-not $Arr -or $Start -ge $Arr.Count) { return @() }
    return $Arr[$Start..($Arr.Count - 1)]
}

# realpath-like: absolute path, doesn't require the target to exist.
function Resolve-FullPath {
    param([string]$Path)
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

# nwn_erf chokes on apostrophes (and is fragile around spaces) in input
# paths. Always invoke nasher against a sanitized copy in %TEMP%. Bash used
# a symlink; on Windows we try a hardlink first (no elevated perms needed on
# the same volume) and fall back to a plain copy. Echoes the safe path.
function Get-SanitizedModPath {
    param([string]$Src)
    if (-not (Test-Path -LiteralPath $Src -PathType Leaf)) {
        Write-ErrLine "error: $Src not found"
        return $null
    }
    $abs = (Resolve-Path -LiteralPath $Src).Path
    $base = [System.IO.Path]::GetFileName($abs)
    $clean = [regex]::Replace($base, '[^A-Za-z0-9._-]', '_')
    $link = Join-Path ([System.IO.Path]::GetTempPath()) "nwnmgr_$clean"
    if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link -Force }
    try {
        New-Item -ItemType HardLink -Path $link -Target $abs -ErrorAction Stop | Out-Null
    } catch {
        Copy-Item -LiteralPath $abs -Destination $link -Force
    }
    return $link
}

# Walk up from cwd to find a directory containing nasher.cfg.
function Find-ProjectRoot {
    $d = (Get-Location).Path
    while ($true) {
        if (Test-Path -LiteralPath (Join-Path $d 'nasher.cfg') -PathType Leaf) {
            return $d
        }
        $parent = Split-Path -Path $d -Parent
        if (-not $parent -or $parent -eq $d) { return $null }
        $d = $parent
    }
}

# Detect the NWN game-data install root for TLK extraction. Resolution
# order: $env:NWN_INSTALL, then .nasher/source's legacy <install>/data/mod/
# layout, then common Windows Steam locations.
function Get-NwnInstall {
    if ($env:NWN_INSTALL -and (Test-Path -LiteralPath $env:NWN_INSTALL -PathType Container)) {
        return $env:NWN_INSTALL
    }
    if (Test-Path -LiteralPath '.nasher/source' -PathType Leaf) {
        $modPath = (Get-Content -LiteralPath '.nasher/source' -Raw).Trim()
        if ($modPath) {
            $modDir = Split-Path -Path $modPath -Parent
            if ($modDir) {
                $parent = Split-Path -Path $modDir -Parent
                if ($parent -and (Split-Path -Path $modDir -Leaf) -eq 'mod' -and (Split-Path -Path $parent -Leaf) -eq 'data') {
                    return (Split-Path -Path $parent -Parent)
                }
            }
        }
    }
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:ProgramFiles) { $candidates.Add((Join-Path $env:ProgramFiles 'Steam\steamapps\common\Neverwinter Nights')) }
    $pf86 = ${env:ProgramFiles(x86)}
    if ($pf86) { $candidates.Add((Join-Path $pf86 'Steam\steamapps\common\Neverwinter Nights')) }
    $candidates.Add('/opt/nwn')
    foreach ($cand in $candidates) {
        if (-not $cand) { continue }
        if ((Test-Path -LiteralPath (Join-Path $cand 'lang\en\data\dialog.tlk') -PathType Leaf) -or
            (Test-Path -LiteralPath (Join-Path $cand 'data\tlk\dialog.tlk') -PathType Leaf)) {
            return $cand
        }
    }
    return $null
}

# Detect the NWN:EE user directory (where modules/, hak/, override/ live).
function Get-NwnUserDir {
    if ($env:NWN_USERDIR -and (Test-Path -LiteralPath $env:NWN_USERDIR -PathType Container)) {
        return $env:NWN_USERDIR
    }
    $candidates = @(
        (Join-Path $HOME 'Documents\Neverwinter Nights'),
        (Join-Path $HOME '.local/share/Neverwinter Nights')
    )
    foreach ($cand in $candidates) {
        if ((Test-Path -LiteralPath (Join-Path $cand 'hak') -PathType Container) -or
            (Test-Path -LiteralPath (Join-Path $cand 'modules') -PathType Container)) {
            return $cand
        }
    }
    return $null
}

# Extract each hak the module declares (via Mod_HakList) into its own
# scratch directory of plain files, for use as nwnsc's -i include-path list.
# Returns one scratch-dir path per element; caller registers them for cleanup.
function Get-HakIncludeDirs {
    $out = @()
    if (-not (Test-Path -LiteralPath 'unpacked/module.ifo.json' -PathType Leaf)) { return $out }
    $userdir = Get-NwnUserDir
    if (-not $userdir) { return $out }
    $hakDir = Join-Path $userdir 'hak'
    if (-not (Test-Path -LiteralPath $hakDir -PathType Container)) { return $out }

    $haks = @(Invoke-PyTool -Sub 'hak-list' -RestArgs @('unpacked/module.ifo.json'))
    foreach ($h in $haks) {
        if (-not $h) { continue }
        $hak = Join-Path $hakDir "$h.hak"
        if (-not (Test-Path -LiteralPath $hak -PathType Leaf)) {
            Write-ErrLine "[$PROG] warn: declared hak $h.hak not found at $hak -- compiler may miss its includes"
            continue
        }
        $name = 'nwnmgr_hakx_' + $h + '_' + [System.IO.Path]::GetRandomFileName().Replace('.', '')
        $dir = Join-Path ([System.IO.Path]::GetTempPath()) $name
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Push-Location $dir
        try {
            & nwn_erf -x -f $hak *> $null
            $ok = ($LASTEXITCODE -eq 0)
        } catch {
            $ok = $false
        } finally {
            Pop-Location
        }
        if ($ok) {
            $out += $dir
        } else {
            Write-ErrLine "[$PROG] warn: failed to extract $h.hak -- compiler may miss its includes"
            Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    return $out
}

# Extract the base dialog.tlk and the custom TLK (named in module.ifo's
# Mod_CustomTlk, if any) from the NWN install into ./tlk/. Non-fatal.
function Export-Tlks {
    if (Test-Path -LiteralPath 'tlk') { Remove-Item -LiteralPath 'tlk' -Recurse -Force }
    New-Item -ItemType Directory -Path 'tlk' -Force | Out-Null

    $install = Get-NwnInstall
    if (-not $install) {
        Write-ErrLine "[$PROG] NWN install not detected (set NWN_INSTALL=...) -- skipping TLK extract"
        return
    }

    $dialog = $null
    foreach ($cand in @((Join-Path $install 'lang\en\data\dialog.tlk'), (Join-Path $install 'data\tlk\dialog.tlk'))) {
        if (Test-Path -LiteralPath $cand -PathType Leaf) { $dialog = $cand; break }
    }
    if ($dialog) {
        Copy-Item -LiteralPath $dialog -Destination 'tlk/dialog.tlk' -Force
        Write-Host "[$PROG] copied $dialog -> tlk/dialog.tlk"
    } else {
        Write-ErrLine "warn: dialog.tlk not found under $install"
    }

    $customName = ''
    if (Test-Path -LiteralPath 'unpacked/module.ifo.json' -PathType Leaf) {
        $lines = @(Invoke-PyTool -Sub 'tlk-name' -RestArgs @('unpacked/module.ifo.json'))
        if ($lines.Count -gt 0) { $customName = $lines[0] }
    }
    if ($customName) {
        $custom = $null
        foreach ($cand in @((Join-Path $install "data\tlk\$customName.tlk"), (Join-Path $install "lang\en\data\$customName.tlk"))) {
            if (Test-Path -LiteralPath $cand -PathType Leaf) { $custom = $cand; break }
        }
        if ($custom) {
            Copy-Item -LiteralPath $custom -Destination "tlk/$customName.tlk" -Force
            Write-Host "[$PROG] copied $custom -> tlk/$customName.tlk"
        } else {
            Write-ErrLine "warn: custom TLK '$customName.tlk' not found under $install"
        }
    }
}

# Append a literal entry to .gitignore if missing. Idempotent.
function Add-GitignoreEntry {
    param([string]$Entry)
    if (-not (Test-Path -LiteralPath '.gitignore' -PathType Leaf)) { return }
    $lines = @(Get-Content -LiteralPath '.gitignore')
    if ($lines -contains $Entry) { return }
    Add-Content -LiteralPath '.gitignore' -Value $Entry
    Write-Host "[$PROG] added '$Entry' to .gitignore"
}

# Print a one-line summary of unpacked/ contents.
function Show-UnpackedSummary {
    if (-not (Test-Path -LiteralPath 'unpacked' -PathType Container)) { return }
    $files = @(Get-ChildItem -LiteralPath 'unpacked' -Recurse -File)
    Write-Host "[$PROG] unpacked/ summary:"
    Write-Host "  total files: $($files.Count)"
    $files |
        Where-Object { $_.Name.Contains('.') } |
        ForEach-Object { $_.Name.Substring($_.Name.LastIndexOf('.') + 1) } |
        Group-Object |
        Sort-Object Count -Descending |
        ForEach-Object { Write-Host "  $($_.Count) $($_.Name)" }
}

function Invoke-CmdInit {
    param([string[]]$RestArgs)
    if ($RestArgs.Count -lt 2) {
        Write-ErrLine "error: init requires <project-dir> <module.mod>"
        Write-ErrLine "usage: $PROG init <project-dir> <module.mod>"
        exit 2
    }
    $project = $RestArgs[0]
    $mod = $RestArgs[1]
    if ((Test-Path -LiteralPath $project) -and (@(Get-ChildItem -LiteralPath $project -Force -ErrorAction SilentlyContinue).Count -gt 0)) {
        Write-ErrLine "error: $project exists and is not empty"
        exit 1
    }
    if (-not (Test-Path -LiteralPath $mod -PathType Leaf)) {
        Write-ErrLine "error: module not found: $mod"
        exit 1
    }

    $modAbs = Resolve-FullPath $mod
    New-Item -ItemType Directory -Path $project -Force | Out-Null
    $project = Resolve-FullPath $project
    Push-Location $project
    try {
        $cleanMod = Get-SanitizedModPath $modAbs
        if (-not $cleanMod) { exit 1 }

        Write-Host "[$PROG] initializing $project from $modAbs"
        & nasher init --default --skipPkgInfo --yes . $cleanMod
        if ($LASTEXITCODE -ne 0) { throw "nasher init failed (exit $LASTEXITCODE)" }

        if (Test-Path -LiteralPath 'src' -PathType Container) {
            Move-Item -LiteralPath 'src' -Destination 'unpacked'
        }

        $cfg = Get-Content -LiteralPath 'nasher.cfg' -Raw
        $cfg = $cfg -replace '"src/\*\*', '"unpacked/**'
        $cfg = $cfg -replace '"\*" = "src"', '"*" = "unpacked"'
        Set-Content -LiteralPath 'nasher.cfg' -Value $cfg -NoNewline

        New-Item -ItemType Directory -Path '.nasher' -Force | Out-Null
        Set-Content -LiteralPath '.nasher/source' -Value $modAbs

        @'
/.nasher/
/dist/
/tlk/
*.mod
*.ncs
*.erf
*.hak
'@ | Set-Content -LiteralPath '.gitignore'

        if (-not (Test-Path -LiteralPath 'README.md' -PathType Leaf)) {
            $modBasename = Split-Path -Path $modAbs -Leaf
            $projectName = Split-Path -Path $project -Leaf
            $readmeTemplate = @'
# {0}

NWN1 module project unpacked from `{1}` for git-friendly,
LLM-editable editing.

## Workflow

```
nwn-manager unpack       # refresh unpacked/ from the .mod
# edit JSON / .nss in unpacked/
nwn-manager repack       # build .mod and copy back to install location
nwn-manager wiki         # regenerate docs/ (committed; published by GitHub Pages)
```

The source/install path is recorded in `.nasher/source` (per-machine,
gitignored). Pass an explicit path to `unpack` to point at a different
.mod.
'@
            ($readmeTemplate -f $projectName, $modBasename) | Set-Content -LiteralPath 'README.md'
        }

        Show-UnpackedSummary
        Write-Host "[$PROG] project ready at: $project"
    } finally {
        Pop-Location
    }
}

function Invoke-CmdUnpack {
    param([string[]]$RestArgs)
    $root = Find-ProjectRoot
    if (-not $root) {
        Write-ErrLine "error: not inside an nwn-manager project (no nasher.cfg found above $((Get-Location).Path))"
        Write-ErrLine "       run '$PROG init <dir> <module.mod>' to create one"
        exit 1
    }
    Push-Location $root
    try {
        $mod = ''
        if ($RestArgs.Count -ge 1) {
            $mod = Resolve-FullPath $RestArgs[0]
            if (-not (Test-Path -LiteralPath $mod -PathType Leaf)) {
                Write-ErrLine "error: $mod not found"
                exit 1
            }
            New-Item -ItemType Directory -Path '.nasher' -Force | Out-Null
            Set-Content -LiteralPath '.nasher/source' -Value $mod
        } elseif (Test-Path -LiteralPath '.nasher/source' -PathType Leaf) {
            $mod = (Get-Content -LiteralPath '.nasher/source' -Raw).Trim()
            if (-not (Test-Path -LiteralPath $mod -PathType Leaf)) {
                Write-ErrLine "error: stored source $mod no longer exists"
                Write-ErrLine "       pass an explicit path: $PROG unpack <module.mod>"
                exit 1
            }
        } else {
            Write-ErrLine "error: no .nasher/source recorded; pass <module.mod> explicitly"
            exit 1
        }

        $cleanMod = Get-SanitizedModPath $mod
        if (-not $cleanMod) { exit 1 }

        if (Test-Path -LiteralPath 'unpacked' -PathType Container) {
            Write-Host "[$PROG] clearing $root/unpacked/"
            Remove-Item -LiteralPath 'unpacked' -Recurse -Force
        }
        Write-Host "[$PROG] unpacking $mod -> $root/unpacked/"
        & nasher unpack --yes "--file:$cleanMod"
        if ($LASTEXITCODE -ne 0) { throw "nasher unpack failed (exit $LASTEXITCODE)" }

        Add-GitignoreEntry '/tlk/'
        Export-Tlks

        Show-UnpackedSummary
    } finally {
        Pop-Location
    }
}

# Read the `file = "..."` value from the first [target] in nasher.cfg.
function Get-NasherTargetFile {
    if (-not (Test-Path -LiteralPath 'nasher.cfg' -PathType Leaf)) { return '' }
    $inTarget = $false
    foreach ($line in Get-Content -LiteralPath 'nasher.cfg') {
        if ($line -match '^\[target') { $inTarget = $true; continue }
        if ($line -match '^\[') { $inTarget = $false; continue }
        if ($inTarget -and $line -match '^\s*file\s*=\s*"?([^"]*)"?\s*$') {
            return $matches[1]
        }
    }
    return ''
}

# Run the module-provided tests/smoke-test build gate, if present. Bash
# relies on the executable bit + shebang; Windows has no exec bit, so we
# dispatch on extension (tests/smoke-test.ps1 / .py) or, for a bare
# tests/smoke-test, sniff the shebang line. Returns $true if the gate
# passed (or nothing to run), $false if it failed.
function Invoke-SmokeTest {
    param([string]$Root)
    $base = Join-Path $Root 'tests/smoke-test'
    $ps1 = "$base.ps1"
    $py = "$base.py"
    $out = $null
    $exit = 0
    if (Test-Path -LiteralPath $ps1 -PathType Leaf) {
        Write-Host "[$PROG] running module smoke tests: tests/smoke-test.ps1"
        $out = & powershell -NoProfile -File $ps1
        $exit = $LASTEXITCODE
    } elseif (Test-Path -LiteralPath $py -PathType Leaf) {
        Write-Host "[$PROG] running module smoke tests: tests/smoke-test.py"
        $out = & python3 $py
        $exit = $LASTEXITCODE
    } elseif (Test-Path -LiteralPath $base -PathType Leaf) {
        $firstLine = Get-Content -LiteralPath $base -TotalCount 1
        Write-Host "[$PROG] running module smoke tests: tests/smoke-test"
        if ($firstLine -match 'python') {
            $out = & python3 $base
            $exit = $LASTEXITCODE
        } elseif (Get-Command bash -ErrorAction SilentlyContinue) {
            $out = & bash $base
            $exit = $LASTEXITCODE
        } else {
            Write-ErrLine "[$PROG] warn: tests/smoke-test found but no compatible interpreter (expected a python shebang, or bash on PATH) -- skipping"
            return $true
        }
    } else {
        return $true
    }

    if ($out) { $out | ForEach-Object { Write-Host $_ } }
    $outStr = ($out -join "`n")
    $passCount = ([regex]::Matches($outStr, '(?m)^(ok)[: ]')).Count
    $failCount = ([regex]::Matches($outStr, '(?m)^(fail|not ok)[: ]')).Count
    $total = $passCount + $failCount
    if ($total -gt 0) {
        Write-Host "[$PROG] $passCount/$total smoke tests passed"
    }
    return ($exit -eq 0)
}

function Invoke-CmdRepack {
    param([string[]]$RestArgs)
    $root = Find-ProjectRoot
    if (-not $root) {
        Write-ErrLine "error: not inside an nwn-manager project (no nasher.cfg found above $((Get-Location).Path))"
        exit 1
    }
    Push-Location $root
    $cleanupPaths = New-Object System.Collections.Generic.List[string]
    try {
        # --no-smoke skips ALL build gates. Strip it before forwarding the rest.
        $noSmoke = $false
        $passThrough = New-Object System.Collections.Generic.List[string]
        foreach ($a in $RestArgs) {
            if ($a -eq '--no-smoke') { $noSmoke = $true } else { $passThrough.Add($a) }
        }

        $unpackedDir = Join-Path $root 'unpacked'

        # Built-in, module-agnostic build gate: refuse to build a module whose
        # conversations are structurally broken (link structs pasted into node
        # lists) -- nwn_gff packs them silently but the engine rejects at load.
        if (-not $noSmoke) {
            $dlgScript = Join-Path $SCRIPT_DIR 'check-dlg-integrity'
            if (($script:PYTOOLS_BIN -or (Test-Path -LiteralPath $dlgScript -PathType Leaf)) -and (Test-Path -LiteralPath $unpackedDir -PathType Container)) {
                Write-Host "[$PROG] checking dialog integrity: unpacked/*.dlg.json"
                $dlgOut = Invoke-PyTool -Sub 'check-dlg-integrity' -RestArgs @($unpackedDir)
                $dlgExit = $LASTEXITCODE
                if ($dlgOut) { $dlgOut | ForEach-Object { Write-Host $_ } }
                if ($dlgExit -ne 0) {
                    Write-ErrLine "[$PROG] dialog-integrity check FAILED -- aborting repack (nothing built or installed)"
                    exit 1
                }
            }
        }

        # Module-provided build gate (optional): tests/smoke-test.
        if (-not $noSmoke -and (Invoke-SmokeTest -Root $root) -eq $false) {
            Write-ErrLine "[$PROG] smoke tests FAILED -- aborting repack (nothing built or installed)"
            exit 1
        }

        # Resolve the bundled base-game scripts dir (nwscript.nss + base/SoU/
        # HotU includes) -- vendored since nwnsc can't pull them from a live
        # install the way the old nwn_script_comp could via --root.
        $baseScripts = ''
        if ($env:NWN_BASE_SCRIPTS_DIR -and (Test-Path -LiteralPath $env:NWN_BASE_SCRIPTS_DIR -PathType Container)) {
            $baseScripts = $env:NWN_BASE_SCRIPTS_DIR
        } elseif ($env:NWN_TOOLS_DIR -and (Test-Path -LiteralPath (Join-Path $env:NWN_TOOLS_DIR 'base-scripts') -PathType Container)) {
            $baseScripts = Join-Path $env:NWN_TOOLS_DIR 'base-scripts'
        } elseif (Test-Path -LiteralPath (Join-Path $SCRIPT_DIR '..\nwn-tools\base-scripts') -PathType Container) {
            $baseScripts = Join-Path $SCRIPT_DIR '..\nwn-tools\base-scripts'
        } elseif (Test-Path -LiteralPath (Join-Path $SCRIPT_DIR '..\..\nwn-tools\base-scripts') -PathType Container) {
            $baseScripts = Join-Path $SCRIPT_DIR '..\..\nwn-tools\base-scripts'
        }
        if (-not $baseScripts) {
            Write-ErrLine "[$PROG] warn: no base-scripts dir found (checked `$env:NWN_BASE_SCRIPTS_DIR, nwn-tools/base-scripts) -- base-game includes like nwscript.nss may fail to resolve"
        }

        # Extract the haks the module declares so the compiler can resolve
        # includes (e.g. CEP/engine-base scripts). Without this, nwnsc only
        # sees unpacked/ and most hak-dependent scripts fail to compile.
        $nssIncludeDirs = New-Object System.Collections.Generic.List[string]
        if ($baseScripts) { $nssIncludeDirs.Add($baseScripts) }
        foreach ($hakDir in (Get-HakIncludeDirs)) {
            $nssIncludeDirs.Add($hakDir)
            $cleanupPaths.Add($hakDir)
        }

        # Bash generates case-corrected #include symlinks here because
        # nwnsc's include resolution is case-sensitive on Linux/macOS. NTFS
        # is case-insensitive by default, so on Windows this step is a no-op
        # and is skipped rather than shelling out to the bash helper script.
        if ($script:PLAT -eq 'win') {
            Write-Host "[$PROG] include-case shims skipped: NTFS is case-insensitive, so nwnsc's #include resolution doesn't need case-corrected symlinks here"
        } else {
            Write-ErrLine "[$PROG] warn: include-case shim generation is not ported for this platform -- case-mismatched #includes (e.g. NW_I0_SPELLS vs nw_i0_spells.nss) may fail to resolve"
        }

        $packArgs = New-Object System.Collections.Generic.List[string]
        $packArgs.Add('--yes')
        $nwnscCmd = Get-Command nwnsc -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($nwnscCmd) {
            $nwnscBin = $nwnscCmd.Source
            $packArgs.Add("--nssCompiler:$nwnscBin")
            if ($nssIncludeDirs.Count -gt 0) {
                $nssInclude = ($nssIncludeDirs.ToArray() -join ';')
                $packArgs.Add("--nssFlags:-lowqey -i $nssInclude")
                Write-Host "[$PROG] compiler: $nwnscBin -i $nssInclude"
            } else {
                Write-Host "[$PROG] compiler: $nwnscBin (no -i include dirs resolved)"
            }
        } else {
            Write-ErrLine "[$PROG] warn: nwnsc not found -- nasher will fall back to its own default compiler resolution"
        }

        # Build stamp (module-agnostic, opt-in): a module calls
        #   ExecuteScript("nwnmgr_bstamp", oPC);
        # from any event to report when/what was built. Generated
        # transiently and removed after pack so the source tree stays clean.
        $stampNss = Join-Path $root 'unpacked/nwnmgr_bstamp.nss'
        if (Test-Path -LiteralPath $unpackedDir -PathType Container) {
            $serverEnv = Join-Path $root 'server.env'
            if (Test-Path -LiteralPath $serverEnv -PathType Leaf) {
                foreach ($line in Get-Content -LiteralPath $serverEnv) {
                    if ($line -match '^\s*(?:export\s+)?TZ\s*=\s*"?([^"]*)"?\s*$') {
                        $env:TZ = $matches[1]
                    }
                }
            }
            $tzLabel = if ($env:TZ) { $env:TZ } else { (Get-TimeZone).Id }
            $stampWhen = (Get-Date -Format 'yyyy-MM-dd HH:mm') + " $tzLabel"

            # Skip automated wiki-refresh commits so they don't obscure when
            # real edits happened; still flag uncommitted working-tree changes.
            $lastReal = & git -C $root log --format=%H --invert-grep --grep='^Auto Wiki Activity Refresh:' -1 2>$null
            $stampGit = ''
            if ($lastReal) {
                $stampGit = & git -C $root describe --tags --always $lastReal 2>$null
                if (-not $stampGit) { $stampGit = & git -C $root rev-parse --short $lastReal 2>$null }
                & git -C $root diff --quiet 2>$null
                $dirty1 = ($LASTEXITCODE -ne 0)
                & git -C $root diff --cached --quiet 2>$null
                $dirty2 = ($LASTEXITCODE -ne 0)
                if ($dirty1 -or $dirty2) { $stampGit = "$stampGit-dirty" }
            } else {
                $stampGit = & git -C $root describe --tags --always --dirty 2>$null
                if (-not $stampGit) { $stampGit = & git -C $root rev-parse --short HEAD 2>$null }
            }
            $stamp = if ($stampGit) { "$stampWhen (git $stampGit)" } else { $stampWhen }
            $stampEsc = $stamp -replace '\\', '\\\\' -replace '"', '\"'

            $stampTemplate = @'
// AUTO-GENERATED by nwn-manager repack -- regenerated each build, do not edit.
// Opt in from any module event: ExecuteScript("nwnmgr_bstamp", oPC);
void main() {{ SendMessageToPC(OBJECT_SELF, "Module last edited: {0}"); }}
'@
            ($stampTemplate -f $stampEsc) | Set-Content -LiteralPath $stampNss
            $cleanupPaths.Add($stampNss)
            Write-Host "[$PROG] build stamp: $stamp"
        }

        & nasher pack @($packArgs.ToArray()) @($passThrough.ToArray())
        if ($LASTEXITCODE -ne 0) { throw "nasher pack failed (exit $LASTEXITCODE)" }

        $built = ''
        $targetFile = Get-NasherTargetFile
        if ($targetFile -and (Test-Path -LiteralPath $targetFile -PathType Leaf)) {
            $built = Resolve-FullPath $targetFile
        } elseif (Test-Path -LiteralPath 'dist' -PathType Container) {
            $modFiles = @(Get-ChildItem -LiteralPath 'dist' -Filter '*.mod' -File | Sort-Object LastWriteTime -Descending)
            if ($modFiles.Count -gt 0) { $built = $modFiles[0].FullName }
        }

        if (-not $built) {
            Write-ErrLine "[$PROG] no built .mod found at project root or in dist/ -- skipping install copy"
            return
        }
        Write-Host "[$PROG] built: $built"

        if (Test-Path -LiteralPath '.nasher/source' -PathType Leaf) {
            $install = (Get-Content -LiteralPath '.nasher/source' -Raw).Trim()
            $installDir = Split-Path -Path $install -Parent
            if (-not (Test-Path -LiteralPath $installDir -PathType Container)) {
                Write-ErrLine "[$PROG] install dir $installDir does not exist -- skipping copy"
                return
            }
            Copy-Item -LiteralPath $built -Destination $install -Force
            Write-Host "[$PROG] installed to: $install"
        }
    } finally {
        foreach ($p in $cleanupPaths) {
            Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        }
        Pop-Location
    }
}

function Invoke-CmdWiki {
    param([string[]]$RestArgs)
    $root = Find-ProjectRoot
    if (-not $root) {
        Write-ErrLine "error: not inside an nwn-manager project (no nasher.cfg found above $((Get-Location).Path))"
        exit 1
    }
    Push-Location $root
    try {
        $serverEnv = Join-Path $root 'server.env'
        if (Test-Path -LiteralPath $serverEnv -PathType Leaf) {
            foreach ($line in Get-Content -LiteralPath $serverEnv) {
                if ($line -match '^\s*(?:export\s+)?TZ\s*=\s*"?([^"]*)"?\s*$') {
                    $env:TZ = $matches[1]
                }
            }
        }

        $out = 'docs'
        $i = 0
        while ($i -lt $RestArgs.Count) {
            if ($RestArgs[$i] -eq '--out') {
                if ($i + 1 -ge $RestArgs.Count) {
                    Write-ErrLine "error: --out requires a directory"
                    exit 2
                }
                $out = $RestArgs[$i + 1]
                $i += 2
            } else {
                break
            }
        }
        $rest = Get-ArgsSlice $RestArgs $i

        $tlkArgs = New-Object System.Collections.Generic.List[string]
        if (Test-Path -LiteralPath 'tlk/dialog.tlk' -PathType Leaf) {
            $tlkArgs.Add('--dialog-tlk'); $tlkArgs.Add('tlk/dialog.tlk')
        } else {
            $install = Get-NwnInstall
            if ($install) {
                foreach ($cand in @((Join-Path $install 'lang\en\data\dialog.tlk'), (Join-Path $install 'data\tlk\dialog.tlk'))) {
                    if (Test-Path -LiteralPath $cand -PathType Leaf) {
                        $tlkArgs.Add('--dialog-tlk'); $tlkArgs.Add($cand)
                        Write-Host "[$PROG] using dialog.tlk from $cand"
                        break
                    }
                }
            }
        }
        $custom = $null
        if (Test-Path -LiteralPath 'tlk' -PathType Container) {
            $custom = Get-ChildItem -LiteralPath 'tlk' -Filter '*.tlk' -File |
                Where-Object { $_.Name -ne 'dialog.tlk' } | Select-Object -First 1
        }
        if ($custom) {
            $tlkArgs.Add('--custom-tlk'); $tlkArgs.Add($custom.FullName)
        }

        Invoke-PyTool -Sub 'wiki' -RestArgs (@('--src', 'unpacked', '--out', $out) + @($tlkArgs.ToArray()) + @rest)
        exit $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

function Invoke-CmdConsole {
    param([string[]]$RestArgs)
    $projectsDir = ''
    $i = 0
    while ($i -lt $RestArgs.Count) {
        if ($RestArgs[$i] -eq '--projects-dir') {
            if ($i + 1 -ge $RestArgs.Count) {
                Write-ErrLine "error: --projects-dir requires a directory"
                exit 2
            }
            $projectsDir = $RestArgs[$i + 1]
            $i += 2
        } else {
            break
        }
    }
    $rest = Get-ArgsSlice $RestArgs $i
    if (-not $projectsDir) {
        $projectsDir = Join-Path (Resolve-FullPath (Join-Path $SCRIPT_DIR '..')) 'projects'
    }
    New-Item -ItemType Directory -Path $projectsDir -Force | Out-Null
    Invoke-PyTool -Sub 'area-editor' -RestArgs (@(
        '--projects-dir', $projectsDir,
        '--nwn-manager', (Join-Path $SCRIPT_DIR 'nwn-manager.ps1'),
        '--landing-dir', (Resolve-FullPath (Join-Path $SCRIPT_DIR '..'))
    ) + @rest)
    exit $LASTEXITCODE
}

function Invoke-CmdEditAreas {
    param([string[]]$RestArgs)
    $root = Find-ProjectRoot
    if (-not $root) {
        Write-ErrLine "error: not inside an nwn-manager project (no nasher.cfg found above $((Get-Location).Path))"
        exit 1
    }
    Push-Location $root
    try {
        $dir = 'unpacked'
        $i = 0
        while ($i -lt $RestArgs.Count) {
            if ($RestArgs[$i] -eq '--dir') {
                if ($i + 1 -ge $RestArgs.Count) {
                    Write-ErrLine "error: --dir requires a directory"
                    exit 2
                }
                $dir = $RestArgs[$i + 1]
                $i += 2
            } else {
                break
            }
        }
        $rest = Get-ArgsSlice $RestArgs $i
        Invoke-PyTool -Sub 'area-editor' -RestArgs (@(
            '--dir', $dir,
            '--nwn-manager', (Join-Path $SCRIPT_DIR 'nwn-manager.ps1'),
            '--landing-dir', (Resolve-FullPath (Join-Path $SCRIPT_DIR '..'))
        ) + @rest)
        exit $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

function Invoke-CmdServe {
    param([string[]]$RestArgs)
    $root = Find-ProjectRoot
    if (-not $root) {
        Write-ErrLine "error: not inside a project (no nasher.cfg found)"
        exit 1
    }
    Push-Location $root
    try {
        $serverEnv = Join-Path $root 'server.env'
        if (Test-Path -LiteralPath $serverEnv -PathType Leaf) {
            foreach ($line in Get-Content -LiteralPath $serverEnv) {
                if ($line -match '^\s*(?:export\s+)?TZ\s*=\s*"?([^"]*)"?\s*$') {
                    $env:TZ = $matches[1]
                }
            }
        }

        $logDirs = New-Object System.Collections.Generic.List[string]
        $pollInterval = 5
        $autoPublish = $false
        $activityCache = ''
        $dbDir = ''
        $backupCmd = ''

        $i = 0
        while ($i -lt $RestArgs.Count) {
            switch ($RestArgs[$i]) {
                '--log-dir' {
                    if ($i + 1 -ge $RestArgs.Count) { Write-ErrLine "error: --log-dir requires a directory"; exit 2 }
                    $logDirs.Add($RestArgs[$i + 1]); $i += 2
                }
                '--poll-interval' {
                    if ($i + 1 -ge $RestArgs.Count) { Write-ErrLine "error: --poll-interval requires a number"; exit 2 }
                    $pollInterval = [int]$RestArgs[$i + 1]; $i += 2
                }
                '--auto-publish' {
                    $autoPublish = $true; $i += 1
                }
                '--activity-cache' {
                    if ($i + 1 -ge $RestArgs.Count) { Write-ErrLine "error: --activity-cache requires a path"; exit 2 }
                    $activityCache = $RestArgs[$i + 1]; $i += 2
                }
                '--db-dir' {
                    if ($i + 1 -ge $RestArgs.Count) { Write-ErrLine "error: --db-dir requires a directory"; exit 2 }
                    $dbDir = $RestArgs[$i + 1]; $i += 2
                }
                '--backup-cmd' {
                    if ($i + 1 -ge $RestArgs.Count) { Write-ErrLine "error: --backup-cmd requires a command"; exit 2 }
                    $backupCmd = $RestArgs[$i + 1]; $i += 2
                }
                default {
                    Write-ErrLine "error: unknown option: $($RestArgs[$i])"
                    Show-Usage
                    exit 2
                }
            }
        }

        if ($logDirs.Count -eq 0) {
            Write-ErrLine "error: at least one --log-dir is required"
            Show-Usage
            exit 2
        }

        $wikiActivity = Join-Path $SCRIPT_DIR 'nwn-wiki-activity'
        if (-not (Test-Path -LiteralPath $wikiActivity -PathType Leaf)) {
            Write-ErrLine "error: nwn-wiki-activity not found at $wikiActivity"
            exit 1
        }

        $logDirArgs = New-Object System.Collections.Generic.List[string]
        foreach ($d in $logDirs) { $logDirArgs.Add('--log-dir'); $logDirArgs.Add($d) }
        $cacheArgs = New-Object System.Collections.Generic.List[string]
        if ($activityCache) { $cacheArgs.Add('--activity-cache'); $cacheArgs.Add($activityCache) }
        $dbDirArgs = New-Object System.Collections.Generic.List[string]
        if ($dbDir) { $dbDirArgs.Add('--db-dir'); $dbDirArgs.Add($dbDir) }

        # The server container starts together with this monitor, so no
        # player can be online yet. Pass our own start time as a floor so a
        # leftover "open" session from a previous unclean shutdown isn't
        # reported as an active player.
        $serveStarted = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        $sinceArgs = @('--online-since', "$serveStarted")

        $pollSecs = $pollInterval * 60
        $publishLabel = if ($autoPublish) { 'enabled' } else { 'disabled' }

        Write-Host "[$PROG] serve: monitoring player activity every ${pollInterval}m (auto-publish: $publishLabel)"
        Write-Host "[$PROG] serve: project root: $root"

        while ($true) {
            $now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
            # Trigger when: no players currently online AND a logout occurred
            # within the last poll window.
            Invoke-PyTool -Sub 'wiki-activity' -RestArgs (@('--check-should-refresh', $pollSecs) + @($logDirArgs.ToArray()) + @($cacheArgs.ToArray()) + @sinceArgs) *> $null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[$PROG] serve: $now -- no players + recent logout; refreshing activity page"
                Invoke-PyTool -Sub 'wiki-activity' -RestArgs (@('--src', 'unpacked', '--out', 'docs') + @($logDirArgs.ToArray()) + @($cacheArgs.ToArray()) + @sinceArgs + @($dbDirArgs.ToArray()))
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "[$PROG] serve: activity page refreshed"
                    if ($autoPublish) {
                        $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
                        $changedFiles = New-Object System.Collections.Generic.List[string]
                        $changedFiles.Add('docs/activity.html')
                        if ($dbDir) { $changedFiles.Add('docs/manual/ServerFirsts.html') }
                        $anyChanged = $false
                        foreach ($f in $changedFiles) {
                            $status = & git -C $root status --porcelain -- $f 2>$null
                            if ($status) { $anyChanged = $true }
                        }
                        if (-not $anyChanged) {
                            Write-Host "[$PROG] serve: no changes to wiki pages; skipping commit"
                        } else {
                            & git -C $root add -- @($changedFiles.ToArray())
                            $addOk = ($LASTEXITCODE -eq 0)
                            $commitOk = $false
                            $pushOk = $false
                            if ($addOk) {
                                & git -C $root commit -m "Auto Wiki Activity Refresh: $ts"
                                $commitOk = ($LASTEXITCODE -eq 0)
                            }
                            if ($commitOk) {
                                & git -C $root push
                                $pushOk = ($LASTEXITCODE -eq 0)
                            }
                            if ($addOk -and $commitOk -and $pushOk) {
                                Write-Host "[$PROG] serve: committed and pushed activity update ($ts)"
                            } else {
                                Write-ErrLine "[$PROG] serve: warn: git publish failed; will retry next poll"
                            }
                        }
                    }
                } else {
                    Write-ErrLine "[$PROG] serve: warn: activity page refresh failed"
                }
                # Opportunistic backup at a quiet moment; the backup command
                # self-gates on its own sentinel, so calling it every idle
                # cycle is harmless.
                if ($backupCmd) {
                    & $backupCmd
                    if ($LASTEXITCODE -ne 0) {
                        Write-ErrLine "[$PROG] serve: warn: backup command failed (rc=$LASTEXITCODE)"
                    }
                }
            } else {
                Invoke-PyTool -Sub 'wiki-activity' -RestArgs (@('--check-online') + @($logDirArgs.ToArray()) + @($cacheArgs.ToArray()) + @sinceArgs) *> $null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "[$PROG] serve: $now -- poll: players online"
                }
            }
            Start-Sleep -Seconds $pollSecs
        }
    } finally {
        Pop-Location
    }
}

function Invoke-Main {
    param([string[]]$AllArgs)
    if (-not $AllArgs -or $AllArgs.Count -eq 0) {
        Show-Usage
        return
    }
    $cmd = $AllArgs[0]
    $rest = Get-ArgsSlice $AllArgs 1
    switch ($cmd) {
        'init' {
            Invoke-Preflight @('nasher', 'nwn_gff')
            Invoke-CmdInit -RestArgs $rest
        }
        'unpack' {
            Invoke-Preflight @('nasher', 'nwn_gff')
            Invoke-CmdUnpack -RestArgs $rest
        }
        'repack' {
            Invoke-Preflight @('nasher', 'nwn_gff', 'nwn_erf', 'nwnsc')
            Invoke-CmdRepack -RestArgs $rest
        }
        'wiki' {
            Invoke-Preflight @('python3')
            Invoke-CmdWiki -RestArgs $rest
        }
        'console' {
            Invoke-Preflight @('python3')
            Invoke-CmdConsole -RestArgs $rest
        }
        'edit-areas' {
            Invoke-Preflight @('python3')
            Invoke-CmdEditAreas -RestArgs $rest
        }
        'serve' {
            Invoke-Preflight @('python3')
            Invoke-CmdServe -RestArgs $rest
        }
        { $_ -in @('-h', '--help') } {
            Show-Usage
        }
        default {
            Write-ErrLine "error: unknown subcommand: $cmd"
            Show-Usage
            exit 2
        }
    }
}

try {
    Invoke-Main -AllArgs $args
} catch {
    Write-ErrLine "[$PROG] ERROR at line $($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message)"
    exit 1
}
