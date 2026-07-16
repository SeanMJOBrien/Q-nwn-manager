#!/usr/bin/env python3
"""NWN GFF web editor - stdlib-only local web app for selective bulk edits.

Serves a small UI over a flat directory of NWN:EE GFF resources (.are/.git/
.utc, plus any directory of player .bic files) and applies targeted edits via
the neverwinter.nim `nwn_gff` CLI (GFF -> JSON -> edit -> GFF round trip).

Pages:
  /areas      - list areas (filter by name/tag, group by tileset), select via
                checkbox, then bulk-edit event scripts, lighting/fog, or tags.
  /creatures  - list .utc blueprints, edit stats / feats / appearance.
  /bics       - browse a directory of .bic player files, edit the same
                character fields plus XP / gold / age.

Safety:
  - binds 127.0.0.1 only (use --host to override deliberately)
  - first edit of any file writes a one-time <file>.bak sibling backup
  - only submitted, non-blank fields are changed; everything else round-trips
    byte-identically through nwn_gff

Usage:
  python3 nwn_web_editor.py --dir /path/to/module/src [--bic-dir DIR]
                            [--port 8340] [--nwn-gff /path/to/nwn_gff]
"""

import argparse
import fnmatch
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --- nwn_gff plumbing -------------------------------------------------------

NWN_GFF = None  # resolved in main()


def find_nwn_gff(explicit):
    candidates = []
    if explicit:
        candidates.append(explicit)
    found = shutil.which("nwn_gff")
    if found:
        candidates.append(found)
    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, "git/nwn-tools/linux/neverwinter/nwn_gff"))
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    sys.exit("ERROR: nwn_gff not found. Pass --nwn-gff /path/to/nwn_gff")


def gff_load(path):
    """GFF binary -> parsed JSON dict."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        tmp = tf.name
    try:
        subprocess.run([NWN_GFF, "-i", path, "-o", tmp, "-k", "json", "-p"],
                       check=True, capture_output=True)
        with open(tmp) as fh:
            return json.load(fh)
    finally:
        os.unlink(tmp)


def gff_save(path, data):
    """JSON dict -> GFF binary, with one-time .bak backup and atomic replace."""
    bak = path + ".bak"
    if os.path.exists(path) and not os.path.exists(bak):
        shutil.copy2(path, bak)
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
        json.dump(data, tf)
        tmp_json = tf.name
    tmp_out = path + ".tmp"
    try:
        subprocess.run([NWN_GFF, "-i", tmp_json, "-l", "json",
                        "-o", tmp_out, "-k", "gff"],
                       check=True, capture_output=True)
        os.replace(tmp_out, path)
    finally:
        os.unlink(tmp_json)
        if os.path.exists(tmp_out):
            os.unlink(tmp_out)


# Cache: path -> (mtime, data). Avoids a subprocess per file per page load.
_CACHE = {}


def load_cached(path):
    mtime = os.path.getmtime(path)
    hit = _CACHE.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    data = gff_load(path)
    _CACHE[path] = (mtime, data)
    return data


def invalidate(path):
    _CACHE.pop(path, None)


# --- GFF field helpers ------------------------------------------------------

def getv(d, name, default=None):
    f = d.get(name)
    return f["value"] if isinstance(f, dict) and "value" in f else default


def setv(d, name, value, gff_type=None):
    """Set a field, preserving its existing declared type when present."""
    if name in d and isinstance(d[name], dict) and "type" in d[name]:
        d[name]["value"] = value
    elif gff_type:
        d[name] = {"type": gff_type, "value": value}
    else:
        raise KeyError("field %r absent and no type given" % name)


def loc_get(d, name):
    """First inline text of a CExoLocString ('' if TLK-only or absent)."""
    v = getv(d, name)
    if isinstance(v, dict):
        for k, txt in v.items():
            if k != "id" and isinstance(txt, str):
                return txt
    return ""


def loc_set(d, name, text):
    f = d.get(name)
    if not (isinstance(f, dict) and isinstance(f.get("value"), dict)):
        d[name] = {"type": "cexolocstring", "value": {}}
        f = d[name]
    f["value"]["0"] = text


def dword_to_hex(v):
    """NWN color dword (0xBBGGRR) -> '#rrggbb'."""
    return "#%02x%02x%02x" % (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)


def hex_to_dword(s):
    s = s.lstrip("#")
    r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    return r | (g << 8) | (b << 16)


# --- HTML helpers -----------------------------------------------------------

def esc(s):
    return html.escape(str(s), quote=True)


CSS = """
body{font-family:system-ui,sans-serif;margin:1.5em;background:#1e1f24;color:#d8d9de}
a{color:#7ab3ff} table{border-collapse:collapse;margin:1em 0}
td,th{border:1px solid #444;padding:.25em .6em;text-align:left}
th{background:#2a2b31} tr:nth-child(even){background:#25262c}
input[type=text],input[type=number],select{background:#2a2b31;color:#d8d9de;
 border:1px solid #555;padding:.2em .4em}
input[type=submit],button{background:#39507a;color:#fff;border:0;
 padding:.4em 1em;cursor:pointer;margin:.2em}
.nav a{margin-right:1.2em} .note{color:#9a9;font-style:italic}
.warn{color:#e6a23c} .err{color:#f66} .ok{color:#8c6}
fieldset{border:1px solid #555;margin:.8em 0} legend{padding:0 .5em}
"""


NAV_EXTRA = []   # [(label, url)] external links appended to the nav bar
WIKI_SHELL = ""  # nwn-wiki embed-shell.html template ({{TITLE}}/{{BODY}}/{{ROOT}})
WIKI_BASE = ""   # public base URL of the wiki the shell's assets live under

# Supplemental styles for editor widgets when embedded in the wiki shell -
# theme-neutral (no fixed colors) since the wiki's stylesheet sets the look.
SHELL_CSS = """
fieldset{border:1px solid #8886;margin:.8em 0;padding:.5em 1em}
legend{padding:0 .5em;font-weight:bold}
.note{opacity:.7;font-style:italic} .warn{color:#b8860b}
.err{color:#c0392b} .ok{color:#2e8b57}
.nav a{margin-right:1.2em}
input[type=submit],button{padding:.35em 1em;cursor:pointer;margin:.2em}
"""


def page(title, body):
    # NAV_EXTRA links are external (wiki, map...) and use double quotes so
    # the reverse-proxy prefix rewrite in _send (single-quote hrefs only)
    # leaves them untouched.
    extra = "".join('<a href="%s">%s</a>' % (esc(u), esc(l))
                    for l, u in NAV_EXTRA)
    nav = ("<div class='nav'><a href='/'>Editor Home</a><a href='/areas'>Areas</a>"
           "<a href='/creatures'>Creatures</a><a href='/bics'>Characters (.bic)</a>"
           "<a href='/module'>Module Info</a>"
           "%s</div>" % extra)
    if WIKI_SHELL:
        inner = ("<style>%s</style>%s<h1>%s</h1>%s"
                 % (SHELL_CSS, nav, esc(title), body))
        return (WIKI_SHELL.replace("{{ROOT}}", WIKI_BASE)
                .replace("{{TITLE}}", esc(title))
                .replace("{{BODY}}", inner))
    return ("<!doctype html><html><head><meta charset='utf-8'><title>%s</title>"
            "<style>%s</style></head><body>%s"
            "<h1>%s</h1>%s</body></html>" % (esc(title), CSS, nav,
                                             esc(title), body))


def hidden_resrefs(resrefs):
    return "".join("<input type='hidden' name='res' value='%s'>" % esc(r)
                   for r in resrefs)


# --- Area logic -------------------------------------------------------------

AREA_SCRIPT_FIELDS = ["OnEnter", "OnExit", "OnHeartbeat", "OnUserDefined"]
# (field, gff type, hint) - colors handled separately
LIGHT_NUM_FIELDS = [
    ("SunFogAmount", "byte", "0-15"),
    ("MoonFogAmount", "byte", "0-15"),
    ("FogClipDist", "float", "e.g. 45.0"),
    ("DayNightCycle", "byte", "0=static 1=cycle"),
    ("IsNight", "byte", "0/1 (when static)"),
    ("LightingScheme", "byte", "environment preset row"),
    ("ShadowOpacity", "byte", "0-100"),
    ("SunShadows", "byte", "0/1"),
    ("MoonShadows", "byte", "0/1"),
    ("WindPower", "int", "0-2"),
]
LIGHT_COLOR_FIELDS = ["SunAmbientColor", "SunDiffuseColor", "SunFogColor",
                      "MoonAmbientColor", "MoonDiffuseColor", "MoonFogColor"]
# (field, gff type, hint) - all are ambientmusic.2da row indices except MusicDelay
MUSIC_FIELDS = [
    ("MusicDay", "int", "ambientmusic.2da row (0 = none)"),
    ("MusicNight", "int", "ambientmusic.2da row (0 = none)"),
    ("MusicBattle", "int", "ambientmusic.2da row (0 = none)"),
    ("MusicDelay", "byte", "0 = start immediately, 1 = delay day track"),
]
# Area .are "Flags" bitmask (confirmed against nwn-mcp's area-tools.ts and
# sampled area data): bit0 interior, bit1 underground, bit2 natural/outdoor.
AREA_FLAG_INTERIOR = 1
AREA_FLAG_UNDERGROUND = 2
AREA_FLAG_NATURAL = 4


def area_resrefs(root):
    return sorted(os.path.splitext(f)[0] for f in os.listdir(root)
                  if f.endswith(".are"))


def area_type_label(flags):
    parts = []
    if flags & AREA_FLAG_NATURAL:
        parts.append("Outside")
    if flags & AREA_FLAG_INTERIOR:
        parts.append("Interior")
    if flags & AREA_FLAG_UNDERGROUND:
        parts.append("Underground")
    return ", ".join(parts) if parts else "(unset)"


def area_row(root, res):
    d = load_cached(os.path.join(root, res + ".are"))
    return {
        "res": res,
        "name": loc_get(d, "Name"),
        "tag": getv(d, "Tag", ""),
        "tileset": getv(d, "Tileset", ""),
        "flags": getv(d, "Flags", 0),
        "scripts": {f: getv(d, f, "") for f in AREA_SCRIPT_FIELDS},
    }


def render_areas(root, query):
    q = (query.get("q", [""])[0]).lower()
    tileset = query.get("tileset", [""])[0]
    f_outside = query.get("outside", [""])[0] == "1"
    f_interior = query.get("interior", [""])[0] == "1"
    f_underground = query.get("underground", [""])[0] == "1"
    rows = [area_row(root, r) for r in area_resrefs(root)]
    tilesets = sorted({r["tileset"] for r in rows})
    if q:
        rows = [r for r in rows if q in r["res"].lower()
                or q in r["name"].lower() or q in r["tag"].lower()]
    if tileset:
        rows = [r for r in rows if r["tileset"] == tileset]
    if f_outside:
        rows = [r for r in rows if r["flags"] & AREA_FLAG_NATURAL]
    if f_interior:
        rows = [r for r in rows if r["flags"] & AREA_FLAG_INTERIOR]
    if f_underground:
        rows = [r for r in rows if r["flags"] & AREA_FLAG_UNDERGROUND]
    opts = "".join("<option value='%s'%s>%s</option>" %
                   (esc(t), " selected" if t == tileset else "", esc(t or "(any)"))
                   for t in [""] + tilesets)

    def cb(name, label, checked):
        return ("<label><input type='checkbox' name='%s' value='1'%s> %s</label>" %
                (name, " checked" if checked else "", label))
    filt = ("<form method='get'>Filter: <input type='text' name='q' value='%s'> "
            "Tileset: <select name='tileset'>%s</select> "
            "Type: %s %s %s "
            "<input type='submit' value='Apply filter'></form>"
            "<p class='note'>Type checkboxes narrow the list (all checked "
            "boxes must match); an area can be more than one type "
            "(e.g. an underground cave interior).</p>" %
            (esc(q), opts,
             cb("outside", "Outside", f_outside),
             cb("interior", "Interior", f_interior),
             cb("underground", "Underground", f_underground)))
    body = [filt,
            "<form method='post' action='/areas/select'>",
            "<table><tr><th><input type='checkbox' "
            "onclick=\"document.querySelectorAll('input[name=res]')"
            ".forEach(c=>c.checked=this.checked)\"></th>"
            "<th>ResRef</th><th>Name</th><th>Tag</th><th>Tileset</th><th>Type</th>"
            "<th>OnEnter</th><th>OnExit</th><th>OnHeartbeat</th><th>OnUserDefined</th></tr>"]
    for r in rows:
        body.append(
            "<tr><td><input type='checkbox' name='res' value='%s'></td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td></tr>" %
            tuple(esc(x) for x in (
                r["res"], r["res"], r["name"], r["tag"], r["tileset"],
                area_type_label(r["flags"]),
                r["scripts"]["OnEnter"], r["scripts"]["OnExit"],
                r["scripts"]["OnHeartbeat"], r["scripts"]["OnUserDefined"])))
    body.append("</table>")
    body.append("With selected: "
                "<button name='action' value='scripts'>Edit scripts</button>"
                "<button name='action' value='lighting'>Edit lighting/fog</button>"
                "<button name='action' value='music'>Edit music</button>"
                "<button name='action' value='tags'>Edit tags</button>"
                "</form>")
    body.append("<p class='note'>%d areas shown.</p>" % len(rows))
    return page("Areas", "".join(body))


def render_scripts_form(root, resrefs):
    rows = [area_row(root, r) for r in resrefs]
    inputs = "".join(
        "<tr><td>%s</td><td><input type='text' name='%s' placeholder='(leave unchanged)'>"
        "</td><td class='note'>%s</td></tr>" %
        (f, f, esc(", ".join(sorted({r["scripts"][f] or "(none)" for r in rows}))))
        for f in AREA_SCRIPT_FIELDS)
    body = ("<p>Editing <b>%d</b> area(s): %s</p>"
            "<form method='post' action='/areas/scripts/apply'>%s"
            "<table><tr><th>Event</th><th>New script resref</th>"
            "<th>Current value(s)</th></tr>%s</table>"
            "<p class='note'>Blank = leave unchanged. Enter <b>-</b> to clear "
            "a script. Max 16 chars, no extension.</p>"
            "<input type='submit' value='Apply to selected areas'></form>" %
            (len(resrefs), esc(", ".join(resrefs)), hidden_resrefs(resrefs), inputs))
    return page("Bulk edit area scripts", body)


def apply_scripts(root, form):
    resrefs, changed = form.get("res", []), []
    for res in resrefs:
        path = os.path.join(root, res + ".are")
        d = gff_load(path)
        touched = False
        for f in AREA_SCRIPT_FIELDS:
            val = form.get(f, [""])[0].strip()
            if not val:
                continue
            new = "" if val == "-" else val.lower()[:16]
            if getv(d, f) != new:
                setv(d, f, new, "resref")
                touched = True
        if touched:
            gff_save(path, d)
            invalidate(path)
            changed.append(res)
    return result_page("Scripts updated", changed, resrefs)


def render_lighting_form(root, resrefs):
    # Prefill from the first selected area so single-area edits show state.
    d0 = load_cached(os.path.join(root, resrefs[0] + ".are"))
    color_rows = "".join(
        "<tr><td>%s</td>"
        "<td><input type='text' name='%s' placeholder='(leave unchanged)'></td>"
        "<td><span style='display:inline-block;width:2em;height:1em;"
        "background:%s'></span> %s</td></tr>" %
        (f, f, dword_to_hex(getv(d0, f, 0)), dword_to_hex(getv(d0, f, 0)))
        for f in LIGHT_COLOR_FIELDS)
    num_rows = "".join(
        "<tr><td>%s</td>"
        "<td><input type='text' name='%s' placeholder='(leave unchanged)'></td>"
        "<td>%s</td><td class='note'>%s</td></tr>" %
        (f, f, esc(getv(d0, f, "")), hint)
        for f, _t, hint in LIGHT_NUM_FIELDS)
    body = ("<p>Editing <b>%d</b> area(s): %s</p>"
            "<form method='post' action='/areas/lighting/apply'>%s"
            "<fieldset><legend>Colors (hex #rrggbb)</legend>"
            "<table><tr><th>Field</th><th>New value</th>"
            "<th>Current (%s)</th></tr>%s</table></fieldset>"
            "<fieldset><legend>Fog / cycle / wind</legend>"
            "<table><tr><th>Field</th><th>New value</th><th>Current (%s)</th>"
            "<th>Hint</th></tr>%s</table></fieldset>"
            "<p class='note'>Blank fields are left unchanged on every area.</p>"
            "<input type='submit' value='Apply to selected areas'></form>" %
            (len(resrefs), esc(", ".join(resrefs)), hidden_resrefs(resrefs),
             esc(resrefs[0]), color_rows, esc(resrefs[0]), num_rows))
    return page("Bulk edit lighting & fog", body)


def apply_lighting(root, form):
    resrefs, changed = form.get("res", []), []
    for res in resrefs:
        path = os.path.join(root, res + ".are")
        d = gff_load(path)
        touched = False
        for f in LIGHT_COLOR_FIELDS:
            val = form.get(f, [""])[0].strip()
            if val:
                setv(d, f, hex_to_dword(val), "dword")
                touched = True
        for f, gff_type, _hint in LIGHT_NUM_FIELDS:
            val = form.get(f, [""])[0].strip()
            if val:
                setv(d, f, float(val) if gff_type == "float" else int(val), gff_type)
                touched = True
        if touched:
            gff_save(path, d)
            invalidate(path)
            changed.append(res)
    return result_page("Lighting updated", changed, resrefs)


def render_music_form(root, resrefs):
    # Prefill from the first selected area so single-area edits show state.
    d0 = load_cached(os.path.join(root, resrefs[0] + ".are"))
    rows = "".join(
        "<tr><td>%s</td>"
        "<td><input type='text' name='%s' placeholder='(leave unchanged)'></td>"
        "<td>%s</td><td class='note'>%s</td></tr>" %
        (f, f, esc(getv(d0, f, "")), hint)
        for f, _t, hint in MUSIC_FIELDS)
    body = ("<p>Editing <b>%d</b> area(s): %s</p>"
            "<form method='post' action='/areas/music/apply'>%s"
            "<table><tr><th>Field</th><th>New value</th><th>Current (%s)</th>"
            "<th>Hint</th></tr>%s</table>"
            "<p class='note'>Blank fields are left unchanged on every area. "
            "Day/Night/Battle values are row indices into ambientmusic.2da "
            "(look them up with the toolset's music picker or nwn-mcp's "
            "resolve_2da/search_2da tools) - not resrefs.</p>"
            "<input type='submit' value='Apply to selected areas'></form>" %
            (len(resrefs), esc(", ".join(resrefs)), hidden_resrefs(resrefs),
             esc(resrefs[0]), rows))
    return page("Bulk edit area music", body)


def apply_music(root, form):
    resrefs, changed = form.get("res", []), []
    for res in resrefs:
        path = os.path.join(root, res + ".are")
        d = gff_load(path)
        touched = False
        for f, gff_type, _hint in MUSIC_FIELDS:
            val = form.get(f, [""])[0].strip()
            if val:
                setv(d, f, int(val), gff_type)
                touched = True
        if touched:
            gff_save(path, d)
            invalidate(path)
            changed.append(res)
    return result_page("Music updated", changed, resrefs)


def render_tags_form(root, resrefs):
    rows = []
    for res in resrefs:
        d = load_cached(os.path.join(root, res + ".are"))
        rows.append(
            "<tr><td>%s</td><td>%s</td>"
            "<td><input type='text' name='tag_%s' value='%s'></td>"
            "<td><input type='text' name='ref_%s' placeholder='(keep %s)'></td></tr>" %
            (esc(res), esc(loc_get(d, "Name")), esc(res),
             esc(getv(d, "Tag", "")), esc(res), esc(res)))
    body = ("<form method='post' action='/areas/tags/apply'>%s"
            "<table><tr><th>ResRef</th><th>Name</th><th>Tag</th>"
            "<th>New ResRef (renames files!)</th></tr>%s</table>"
            "<p class='warn'>ResRef rename moves the .are/.git/.gic files on "
            "disk and rewrites the ResRef field, but does NOT update door/"
            "trigger transitions in other areas that target the old resref - "
            "search those separately.</p>"
            "<input type='submit' value='Apply'></form>" %
            (hidden_resrefs(resrefs), "".join(rows)))
    return page("Edit area tags / resrefs", body)


def apply_tags(root, form):
    resrefs, changed, errors = form.get("res", []), [], []
    for res in resrefs:
        path = os.path.join(root, res + ".are")
        d = gff_load(path)
        touched = False
        new_tag = form.get("tag_" + res, [""])[0].strip()
        if new_tag and new_tag != getv(d, "Tag"):
            setv(d, "Tag", new_tag, "cexostring")
            touched = True
        new_ref = form.get("ref_" + res, [""])[0].strip().lower()
        if new_ref and new_ref != res:
            if not re.fullmatch(r"[a-z0-9_]{1,16}", new_ref):
                errors.append("%s: invalid resref %r" % (res, new_ref))
                new_ref = ""
            elif os.path.exists(os.path.join(root, new_ref + ".are")):
                errors.append("%s: %r already exists" % (res, new_ref))
                new_ref = ""
        else:
            new_ref = ""
        if new_ref:
            setv(d, "ResRef", new_ref, "resref")
            touched = True
        if touched:
            gff_save(path, d)
            invalidate(path)
            changed.append(res)
        if new_ref:
            for ext in (".are", ".git", ".gic"):
                old_p = os.path.join(root, res + ext)
                if os.path.exists(old_p):
                    os.replace(old_p, os.path.join(root, new_ref + ext))
                    invalidate(old_p)
    extra = "".join("<p class='err'>%s</p>" % esc(e) for e in errors)
    return result_page("Tags updated", changed, resrefs, extra)


def result_page(title, changed, selected, extra=""):
    body = ("<p class='ok'>Changed %d of %d selected: %s</p>%s"
            "<p><a href='/areas'>Back to areas</a></p>" %
            (len(changed), len(selected),
             esc(", ".join(changed) or "(nothing - all values blank/same)"), extra))
    return page(title, body)


# --- Creature / BIC logic ---------------------------------------------------

ABILITY_FIELDS = ["Str", "Dex", "Con", "Int", "Wis", "Cha"]
STAT_FIELDS = [  # (field, type)
    ("NaturalAC", "byte"), ("HitPoints", "short"), ("CurrentHitPoints", "short"),
    ("MaxHitPoints", "short"), ("fortbonus", "short"), ("refbonus", "short"),
    ("willbonus", "short"), ("ChallengeRating", "float"), ("WalkRate", "int"),
]
APPEAR_FIELDS = [  # only rendered when present in the file (dynamic models)
    ("Appearance_Type", "word"), ("PortraitId", "word"), ("Gender", "byte"),
    ("Race", "byte"), ("Phenotype", "int"), ("Appearance_Head", "byte"),
    ("Color_Hair", "byte"), ("Color_Skin", "byte"),
    ("Color_Tattoo1", "byte"), ("Color_Tattoo2", "byte"),
    ("Tail_New", "dword"), ("Wings_New", "dword"),
]
BIC_EXTRA_FIELDS = [("Experience", "dword"), ("Gold", "dword"), ("Age", "int")]


def creature_summary(d):
    classes = ", ".join(
        "%s lvl %s" % (getv(c, "Class", "?"), getv(c, "ClassLevel", "?"))
        for c in getv(d, "ClassList", []))
    return {
        "first": loc_get(d, "FirstName"), "last": loc_get(d, "LastName"),
        "tag": getv(d, "Tag", ""), "classes": classes,
        "appearance": getv(d, "Appearance_Type", ""),
    }


def render_creatures(root, query):
    q = (query.get("q", [""])[0]).lower()
    body = ["<form method='get'>Filter: <input type='text' name='q' value='%s'>"
            "<input type='submit' value='Apply'></form>" % esc(q),
            "<table><tr><th>ResRef</th><th>Name</th><th>Tag</th>"
            "<th>Classes</th><th>Appearance</th></tr>"]
    count = 0
    for f in sorted(os.listdir(root)):
        if not f.endswith(".utc"):
            continue
        res = f[:-4]
        d = load_cached(os.path.join(root, f))
        s = creature_summary(d)
        name = ("%s %s" % (s["first"], s["last"])).strip()
        if q and q not in res.lower() and q not in name.lower() \
                and q not in s["tag"].lower():
            continue
        count += 1
        body.append("<tr><td><a href='/creature?res=%s'>%s</a></td>"
                    "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" %
                    (urllib.parse.quote(res), esc(res), esc(name),
                     esc(s["tag"]), esc(s["classes"]), esc(s["appearance"])))
    body.append("</table><p class='note'>%d creatures shown.</p>" % count)
    return page("Creature blueprints (.utc)", "".join(body))


def render_char_form(d, action, ident_html, is_bic):
    def num_input(f):
        return ("<tr><td>%s</td><td><input type='text' name='%s' value='%s'>"
                "</td></tr>" % (f, f, esc(getv(d, f, ""))))

    abil = "".join(num_input(f) for f in ABILITY_FIELDS)
    stats = "".join(num_input(f) for f, _t in STAT_FIELDS if f in d)
    if is_bic:
        stats += "".join(num_input(f) for f, _t in BIC_EXTRA_FIELDS if f in d)
    appear = "".join(num_input(f) for f, _t in APPEAR_FIELDS if f in d)

    feats = sorted(getv(f, "Feat", -1) for f in getv(d, "FeatList", []))
    feat_boxes = "".join(
        "<label style='display:inline-block;margin:.15em .5em'>"
        "<input type='checkbox' name='delfeat' value='%d'> %d</label>" % (n, n)
        for n in feats)

    body = (
        "<form method='post' action='%s'>%s"
        "<fieldset><legend>Identity</legend><table>"
        "<tr><td>FirstName</td><td><input type='text' name='FirstName' value='%s'></td></tr>"
        "<tr><td>LastName</td><td><input type='text' name='LastName' value='%s'></td></tr>"
        "<tr><td>Tag</td><td><input type='text' name='Tag' value='%s'></td></tr>"
        "</table></fieldset>"
        "<fieldset><legend>Abilities</legend><table>%s</table></fieldset>"
        "<fieldset><legend>Stats</legend><table>%s</table></fieldset>"
        "<fieldset><legend>Appearance</legend><table>%s</table>"
        "<p class='note'>Only fields present in this file are shown; static-"
        "appearance creatures have no head/body-part fields. IDs come from "
        "appearance.2da / portraits.2da etc.</p></fieldset>"
        "<fieldset><legend>Feats (%d) - tick to REMOVE</legend>%s"
        "<p>Add feat IDs (comma-separated): "
        "<input type='text' name='addfeats' placeholder='e.g. 1,28,411'></p>"
        "</fieldset>"
        "<p class='note'>Blank numeric fields are left unchanged.</p>"
        "<input type='submit' value='Save'></form>" %
        (action, ident_html, esc(loc_get(d, "FirstName")),
         esc(loc_get(d, "LastName")), esc(getv(d, "Tag", "")),
         abil, stats, appear, len(feats), feat_boxes or "<p class='note'>none</p>"))
    return body


def apply_char_edits(d, form, is_bic):
    """Apply shared UTC/BIC form fields onto dict d. Returns True if changed."""
    touched = False
    for name in ("FirstName", "LastName"):
        val = form.get(name, [None])[0]
        if val is not None and val != loc_get(d, name):
            loc_set(d, name, val)
            touched = True
    tag = form.get("Tag", [None])[0]
    if tag is not None and tag != getv(d, "Tag"):
        setv(d, "Tag", tag, "cexostring")
        touched = True

    numeric = [(f, "byte") for f in ABILITY_FIELDS] + STAT_FIELDS + APPEAR_FIELDS
    if is_bic:
        numeric += BIC_EXTRA_FIELDS
    for f, gff_type in numeric:
        val = form.get(f, [""])[0].strip()
        if not val:
            continue
        new = float(val) if gff_type == "float" else int(val)
        if getv(d, f) != new:
            setv(d, f, new, gff_type)
            touched = True

    delfeats = {int(x) for x in form.get("delfeat", [])}
    addfeats = [int(x) for x in
                re.split(r"[,\s]+", form.get("addfeats", [""])[0].strip()) if x]
    if delfeats or addfeats:
        fl = d.setdefault("FeatList", {"type": "list", "value": []})
        entries = fl["value"]
        have = {getv(e, "Feat") for e in entries}
        entries[:] = [e for e in entries if getv(e, "Feat") not in delfeats]
        sid = entries[0]["__struct_id"] if entries else 1
        for n in addfeats:
            if n not in have:
                entries.append({"__struct_id": sid,
                                "Feat": {"type": "word", "value": n}})
        touched = True
    return touched


# --- BIC browsing -----------------------------------------------------------

def safe_bic_path(bic_root, rel):
    full = os.path.realpath(os.path.join(bic_root, rel))
    if not full.startswith(os.path.realpath(bic_root) + os.sep) \
            and full != os.path.realpath(bic_root):
        raise ValueError("path escapes --bic-dir")
    if not full.endswith(".bic"):
        raise ValueError("not a .bic file")
    return full


def render_bics(bic_root, query):
    q = (query.get("q", [""])[0]).lower()
    body = ["<p class='note'>Browsing: %s (recursive)</p>" % esc(bic_root),
            "<form method='get'>Filter: <input type='text' name='q' value='%s'>"
            "<input type='submit' value='Apply'></form>" % esc(q),
            "<table><tr><th>File</th><th>Name</th><th>Classes</th><th>XP</th>"
            "<th>Gold</th></tr>"]
    count = 0
    for dirpath, _dirs, files in os.walk(bic_root):
        for f in sorted(files):
            if not f.endswith(".bic"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), bic_root)
            if q and q not in rel.lower():
                continue
            try:
                d = load_cached(os.path.join(dirpath, f))
            except Exception as e:
                body.append("<tr><td>%s</td><td class='err' colspan='4'>"
                            "unreadable: %s</td></tr>" % (esc(rel), esc(e)))
                continue
            s = creature_summary(d)
            count += 1
            body.append(
                "<tr><td><a href='/bic?path=%s'>%s</a></td><td>%s %s</td>"
                "<td>%s</td><td>%s</td><td>%s</td></tr>" %
                (urllib.parse.quote(rel), esc(rel), esc(s["first"]),
                 esc(s["last"]), esc(s["classes"]),
                 esc(getv(d, "Experience", "")), esc(getv(d, "Gold", ""))))
    body.append("</table><p class='note'>%d characters shown.</p>" % count)
    return page("Player characters (.bic)", "".join(body))


# --- Module info --------------------------------------------------------------

def render_module_form(d):
    return (
        "<form method='post' action='/module/apply'>"
        "<fieldset><legend>Module Info</legend><table>"
        "<tr><td>Module Name</td><td><input type='text' name='Mod_Name' "
        "value='%s' size='60'></td></tr>"
        "<tr><td>Description</td><td><textarea name='Mod_Description' "
        "rows='10' cols='70'>%s</textarea></td></tr>"
        "</table></fieldset>"
        "<input type='submit' value='Save'></form>" %
        (esc(loc_get(d, "Mod_Name")), esc(loc_get(d, "Mod_Description"))))


def apply_module(root, form):
    path = os.path.join(root, "module.ifo")
    d = gff_load(path)
    touched = False
    for name in ("Mod_Name", "Mod_Description"):
        val = form.get(name, [None])[0]
        if val is not None and val != loc_get(d, name):
            loc_set(d, name, val)
            touched = True
    if touched:
        gff_save(path, d)
        invalidate(path)
    return touched


# --- HTTP handler -----------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    root = None       # flat GFF dir (.are/.git/.utc)
    bic_root = None   # .bic dir
    url_prefix = ""   # e.g. "/qedit" when reverse-proxied under a subpath

    def _path(self):
        """Request path with any reverse-proxy prefix stripped."""
        path = urllib.parse.urlparse(self.path).path
        if self.url_prefix and path.startswith(self.url_prefix):
            path = path[len(self.url_prefix):] or "/"
        return path

    def _send(self, content, code=200):
        if self.url_prefix:
            # every internal URL in the app is a single-quoted absolute path
            content = (content
                       .replace("href='/", "href='" + self.url_prefix + "/")
                       .replace("action='/", "action='" + self.url_prefix + "/"))
        data = content.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _form(self):
        length = int(self.headers.get("Content-Length", 0))
        return urllib.parse.parse_qs(self.rfile.read(length).decode(),
                                     keep_blank_values=True)

    def log_message(self, fmt, *args):  # quieter default log
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        path = self._path()
        try:
            if path == "/":
                n_are = len(area_resrefs(self.root))
                n_utc = len([f for f in os.listdir(self.root)
                             if f.endswith(".utc")])
                self._send(page("NWN GFF web editor",
                    "<ul><li><a href='/areas'>Areas</a> - %d found - bulk-edit "
                    "event scripts, lighting/fog, tags/resrefs</li>"
                    "<li><a href='/creatures'>Creatures</a> - %d blueprints - "
                    "stats, feats, appearance</li>"
                    "<li><a href='/bics'>Characters</a> - player .bic files "
                    "under %s</li>"
                    "<li><a href='/module'>Module Info</a> - title and "
                    "description</li></ul>"
                    "<p class='note'>Data dir: %s. Every modified file gets a "
                    "one-time .bak sibling backup.</p>"
                    % (n_are, n_utc, esc(self.bic_root), esc(self.root))))
            elif path == "/areas":
                self._send(render_areas(self.root, query))
            elif path == "/areas/edit":
                # Direct-link entry point (used by the generated area map):
                # /areas/edit?res=X[&res=Y...]&action=scripts|lighting|tags
                resrefs = [r for r in query.get("res", [])
                           if os.path.exists(os.path.join(self.root, r + ".are"))]
                action = query.get("action", ["scripts"])[0]
                if not resrefs:
                    self._send(page("Unknown area",
                                    "<p class='err'>No such area here.</p>"
                                    "<p><a href='/areas'>Area list</a></p>"), 404)
                    return
                render = {"scripts": render_scripts_form,
                          "lighting": render_lighting_form,
                          "music": render_music_form,
                          "tags": render_tags_form}.get(action, render_scripts_form)
                self._send(render(self.root, resrefs))
            elif path == "/creatures":
                self._send(render_creatures(self.root, query))
            elif path == "/creature":
                res = query.get("res", [""])[0]
                path = os.path.join(self.root, res + ".utc")
                d = load_cached(path)
                ident = "<input type='hidden' name='res' value='%s'>" % esc(res)
                self._send(page("Creature: " + res,
                                render_char_form(d, "/creature/apply", ident, False)))
            elif path == "/bics":
                self._send(render_bics(self.bic_root, query))
            elif path == "/bic":
                rel = query.get("path", [""])[0]
                full = safe_bic_path(self.bic_root, rel)
                d = load_cached(full)
                ident = "<input type='hidden' name='path' value='%s'>" % esc(rel)
                self._send(page("Character: " + rel,
                                render_char_form(d, "/bic/apply", ident, True)))
            elif path == "/module":
                d = load_cached(os.path.join(self.root, "module.ifo"))
                self._send(page("Module Info", render_module_form(d)))
            else:
                self._send(page("Not found", "<p>No such page.</p>"), 404)
        except Exception as e:
            self._send(page("Error", "<p class='err'>%s</p>" % esc(e)), 500)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        form = self._form()
        path = self._path()
        try:
            if path == "/areas/select":
                resrefs = form.get("res", [])
                action = form.get("action", [""])[0]
                if not resrefs:
                    self._send(page("No areas selected",
                                    "<p><a href='/areas'>Back</a></p>"))
                    return
                render = {"scripts": render_scripts_form,
                          "lighting": render_lighting_form,
                          "music": render_music_form,
                          "tags": render_tags_form}[action]
                self._send(render(self.root, resrefs))
            elif path == "/areas/scripts/apply":
                self._send(apply_scripts(self.root, form))
            elif path == "/areas/lighting/apply":
                self._send(apply_lighting(self.root, form))
            elif path == "/areas/music/apply":
                self._send(apply_music(self.root, form))
            elif path == "/areas/tags/apply":
                self._send(apply_tags(self.root, form))
            elif path == "/creature/apply":
                res = form.get("res", [""])[0]
                path = os.path.join(self.root, res + ".utc")
                d = gff_load(path)
                if apply_char_edits(d, form, False):
                    gff_save(path, d)
                    invalidate(path)
                self._send(page("Saved", "<p class='ok'>%s saved.</p>"
                                "<p><a href='/creature?res=%s'>Back</a></p>" %
                                (esc(res), urllib.parse.quote(res))))
            elif path == "/bic/apply":
                rel = form.get("path", [""])[0]
                full = safe_bic_path(self.bic_root, rel)
                d = gff_load(full)
                if apply_char_edits(d, form, True):
                    gff_save(full, d)
                    invalidate(full)
                self._send(page("Saved", "<p class='ok'>%s saved.</p>"
                                "<p><a href='/bic?path=%s'>Back</a></p>" %
                                (esc(rel), urllib.parse.quote(rel))))
            elif path == "/module/apply":
                touched = apply_module(self.root, form)
                msg = "Module info saved." if touched else "No changes."
                self._send(page("Saved", "<p class='ok'>%s</p>"
                                "<p><a href='/module'>Back</a></p>" % esc(msg)))
            else:
                self._send(page("Not found", "<p>No such action.</p>"), 404)
        except Exception as e:
            self._send(page("Error", "<p class='err'>%s</p>" % esc(e)), 500)


def main():
    global NWN_GFF
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=".",
                    help="flat directory of .are/.git/.utc (default: cwd)")
    ap.add_argument("--bic-dir", default=None,
                    help="directory of player .bic files (default: --dir); "
                         "searched recursively, e.g. a servervault")
    ap.add_argument("--port", type=int, default=8340)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--url-prefix", default="",
                    help="serve under this path prefix (e.g. /qedit) when "
                         "behind a reverse proxy")
    ap.add_argument("--nav", action="append", default=[], metavar="LABEL=URL",
                    help="extra nav-bar link (repeatable), e.g. "
                         "--nav 'Wiki=/hos1-wiki/' --nav 'Area Map=/qarea/'")
    ap.add_argument("--wiki-shell", default=None, metavar="FILE",
                    help="path to an nwn-wiki assets/embed-shell.html; wraps "
                         "every editor page in the wiki's header/nav/styles")
    ap.add_argument("--wiki-base", default="", metavar="URL",
                    help="public base URL of that wiki (e.g. /hos1-wiki), "
                         "substituted for the shell's {{ROOT}} asset paths")
    ap.add_argument("--nwn-gff", default=None, help="path to nwn_gff binary")
    args = ap.parse_args()

    NWN_GFF = find_nwn_gff(args.nwn_gff)
    Handler.root = os.path.abspath(args.dir)
    Handler.bic_root = os.path.abspath(args.bic_dir or args.dir)
    Handler.url_prefix = args.url_prefix.rstrip("/")
    NAV_EXTRA[:] = [(label, url) for label, _, url in
                    (n.partition("=") for n in args.nav) if url]
    if args.wiki_shell:
        global WIKI_SHELL, WIKI_BASE
        with open(args.wiki_shell) as fh:
            WIKI_SHELL = fh.read()
        WIKI_BASE = args.wiki_base.rstrip("/")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("nwn_gff:  %s" % NWN_GFF)
    print("data dir: %s" % Handler.root)
    print("bic dir:  %s" % Handler.bic_root)
    print("Serving on http://%s:%d/ (Ctrl-C to stop)" % (args.host, args.port))
    srv.serve_forever()


if __name__ == "__main__":
    main()
