# Nasher CLI Cheat Sheet

Nasher manages a NWN:EE module as source-controlled JSON/NSS, compiling and
packing into a `.mod`/`.erf`/`.hak` for the target defined in `nasher.cfg`.

## Project layout (typical)

```
project/
├── nasher.cfg
├── src/
│   └── <target>/
│       ├── areas/          # .are.json, .git.json, .gic.json
│       ├── scripts/        # .nss
│       ├── blueprints/     # .utc.json, .uti.json, .utp.json, etc.
│       └── module.ifo.json
└── .nasher/
    └── cache/<target>/     # build intermediates — do NOT hand-edit
```

## Commands

| Command                     | Effect                                                        |
|------------------------------|----------------------------------------------------------------|
| `nasher unpack <target>`     | Explodes an existing packed file into JSON sources under `src/` |
| `nasher compile <target>`    | Compiles `.nss` → `.ncs` via configured compiler (nwnsc or nwn_script_comp) |
| `nasher convert <target>`    | Converts JSON sources → GFF binaries in `.nasher/cache/<target>` |
| `nasher pack <target>`       | Runs convert + compile as needed, then packs into final module file |
| `nasher install <target>`    | Packs and copies/installs into the NWN installation directory |
| `nasher list`                | Lists installed/available targets |

`nasher convert` and `nasher compile` are both invoked automatically by
`nasher pack` — you rarely need to call them separately except to debug one
step in isolation (e.g. checking compiler errors without a full pack).

## Config notes (`nasher.cfg`)

- `gffUtil` — path to the `nwn_gff`/`nwn-gff` binary nasher shells out to
- `nssCompiler` — path to `nwnsc` or `nwn_script_comp`
- `erfUtil` — path to `nwn_erf` for packing
- `truncateFloats` — rounds float precision in GFF output to avoid noisy
  diffs from insignificant float changes; useful to enable for a cleaner git
  history when editing positions by hand

## Debugging a failed pack

1. Run `nasher compile <target>` alone first — script errors show file/line,
   fix those before worrying about GFF issues.
2. Run `nasher convert <target>` alone — JSON → GFF conversion errors here
   usually mean a malformed field (wrong type, missing `__struct_id`, bad
   ResRef length). Cross-check against `references/gff-json-schema.md` and the
   bundled `scripts/validate_gff_json.py`.
3. Only after both succeed independently, run the full `nasher pack`.
