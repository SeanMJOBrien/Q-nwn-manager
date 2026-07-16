---
name: nwn-web-editor
description: Use this skill when the user wants a browser/web UI to inspect or bulk-edit NWN:EE game data — selecting areas by checkbox, category, or type (outside/interior/underground) to change their scripts, lighting, fog, music, or tags; browsing and editing player .bic character files; or editing creature blueprint stats, feats, and appearance. Trigger on "web app", "web editor", "UI to edit areas/characters", "area music", "filter areas by outside/interior/underground", or when a user wants point-and-click selective editing instead of CLI/scripted edits. Launches a local stdlib-only Python web app (scripts/nwn_web_editor.py).
---

# NWN Web Editor

A local, dependency-free (Python 3 stdlib only) web app for selective bulk
editing of NWN:EE GFF data. All edits round-trip through `nwn_gff`
(GFF -> JSON -> edit -> GFF); only submitted, non-blank fields change.

## Launch

```bash
python3 ~/.claude/skills/nwn-web-editor/scripts/nwn_web_editor.py \
    --dir /path/to/flat/gff/dir \            # .are/.git/.utc live here
    --bic-dir /path/to/servervault \         # optional; searched recursively
    --port 8340                              # default; binds 127.0.0.1 only
# then open http://127.0.0.1:8340/
```

- `--dir` expects a **flat** directory of GFF resources — a repo like hos1's
  root, a nasher `src/` flattened, or an `nwn_erf -x` extraction of a .mod.
- `nwn_gff` is auto-found on PATH or at
  `~/git/nwn-tools/linux/neverwinter/nwn_gff`; override with `--nwn-gff`.
- `--url-prefix /qedit` serves the app under a subpath for reverse-proxy
  setups (e.g. Apache `ProxyPass "/qedit" "http://<bridge-ip>:8340/qedit"`
  with basic auth — see the hos1 deployment: editor bound to the docker
  bridge gateway 172.23.0.1, proxied by the UniverseOfArlandia container at
  port 88 `/qedit/`, htpasswd at `docker/qedit.htpasswd` in that repo).
- `--wiki-shell <wiki>/assets/embed-shell.html --wiki-base /hos1-wiki` wraps
  every editor page in an nwn-manager wiki's header/nav/stylesheet, so the
  editor reads as part of the wiki instead of a separate app. nwn-wiki emits
  that shell file on every generation; its `wiki-theme/editor.json`
  (`{"base": "/qedit"}`) makes each wiki area page link back to the editor's
  lighting/tags/scripts forms for that area. Regenerate the wiki, then
  restart the editor so it picks up the fresh shell.
- First edit of any file writes a one-time sibling `<file>.bak` backup.
- Full per-feature behavior spec: `references/feature-specs.md` — read it
  before extending the app or diagnosing unexpected behavior.

## Features

| Page | Does |
|------|------|
| `/areas` | list all areas; filter by name/tag substring, tileset, and/or type (Outside/Interior/Underground checkboxes, AND'd together — an area's Flags bitmask can match more than one); select via checkboxes; route selection to one of four bulk editors |
| areas -> Edit scripts | set OnEnter/OnExit/OnHeartbeat/OnUserDefined on every selected area (blank = keep, `-` = clear) |
| areas -> Edit lighting/fog | set sun/moon ambient/diffuse/fog colors (hex, auto-converted to NWN BGR dwords), fog amounts, FogClipDist, day/night cycle, shadows, wind |
| areas -> Edit music | set MusicDay/MusicNight/MusicBattle (ambientmusic.2da row indices) and MusicDelay on every selected area |
| areas -> Edit tags | per-area tag rename, optional resref rename (renames the .are/.git/.gic files too) |
| `/creatures` | list .utc blueprints; per-creature editor: abilities, HP/AC/saves/CR, appearance fields, feat add/remove, names/tag |
| `/bics` | recursive .bic browser (point at a servervault); same editor plus Experience, Gold, Age |
| `/module` | edit `module.ifo`'s Mod_Name (title) and Mod_Description together, as the toolset's Module Properties tab does |

## Area map generator (scripts/nwn_area_map.py)

Companion script producing a **self-contained pan/zoomable HTML map** of all
areas, laid out by the cardinal directions implied by door/trigger
transitions (exit position in source vs. landing position in destination
votes on the compass direction; votes are averaged per area pair, diagonals
supported). Disconnected groups of areas are shelf-packed into their own
labeled regions; areas with no transitions land in an "Unconnected" block.
Underground areas (ARE Flags & 0x02) may share a grid cell with a surface
area as a layered, offset, dashed node; surface/underground layers can be
toggled, and cross-layer links render dashed amber.

```bash
python3 ~/.claude/skills/nwn-web-editor/scripts/nwn_area_map.py \
    --dir /path/to/flat/gff/dir -o area_map.html --title "My module"
```

Output is one static HTML file (inline SVG + JS: drag-pan, wheel-zoom,
search-highlight) — host it anywhere or open from disk.

## Editing files that are inside a .mod

The app edits loose files only. For a packed module: extract first
(`nwn_erf -x -f mod.mod` into an empty dir), point `--dir` there, edit, then
repack — for hos1 specifically, edit the repo's flat files and run
`bash build_module.sh` instead, so git stays the source of truth.

## After editing

- Areas/creatures: rebuild + repack the module (hos1: `build_module.sh`).
- .bic: only edit while the character is logged out / server down — the
  server rewrites .bic on save and will clobber concurrent edits.
- Diff against the `.bak` to review what changed
  (`nwn_gff -i f.are -k json > new.json; nwn_gff -i f.are.bak -k json > old.json; diff old.json new.json`).

## Extending

Single file, ~600 lines, no framework. Each feature is a render function
(GET form) + apply function (POST handler) pair using the shared helpers
(`gff_load/gff_save`, `getv/setv`, `loc_get/loc_set`, `hex_to_dword`).
Follow `references/feature-specs.md`'s per-feature spec format when adding
one: define selection model, fields touched, blank-field semantics,
validation, and failure modes before writing code.
