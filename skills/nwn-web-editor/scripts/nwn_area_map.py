#!/usr/bin/env python3
"""Generate a self-contained, pan/zoomable HTML map of a NWN module's areas,
laid out by the cardinal directions implied by their transitions.

How directions are inferred: every door/trigger transition knows where it
sits inside its source area and where its destination (door or waypoint tag)
sits inside the target area. An exit near the source's north edge that lands
near the destination's south edge votes "destination is north of source".
Votes for all transitions between a pair are averaged into one cardinal.

Layout: each connected component is laid out independently (BFS from its
best-connected area, stepping one grid cell per cardinal), then components
are shelf-packed side by side so unjoined groups get their own region of the
map. When two areas contend for the same grid cell, an underground area
(ARE Flags bit 0x02) may share the cell with a surface area as a second
layer; same-layer collisions probe further along the cardinal instead.

Usage:
  python3 nwn_area_map.py --dir /path/to/flat/gff/dir -o area_map.html
                          [--nwn-gff /path/to/nwn_gff] [--title "My module"]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict

NWN_GFF = None
UNDERGROUND_FLAG = 0x02


def find_nwn_gff(explicit):
    for c in [explicit, shutil.which("nwn_gff"),
              os.path.expanduser("~/git/nwn-tools/linux/neverwinter/nwn_gff")]:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    sys.exit("ERROR: nwn_gff not found. Pass --nwn-gff /path/to/nwn_gff")


def gff_load(path):
    out = subprocess.run([NWN_GFF, "-i", path, "-k", "json"],
                         check=True, capture_output=True)
    return json.loads(out.stdout)


def getv(d, name, default=None):
    f = d.get(name)
    return f["value"] if isinstance(f, dict) and "value" in f else default


def loc_get(d, name):
    v = getv(d, name)
    if isinstance(v, dict):
        for k, txt in v.items():
            if k != "id" and isinstance(txt, str):
                return txt
    return ""


# --- data extraction ---------------------------------------------------------

def read_module(root):
    """Return (areas dict, transitions list).

    areas[res] = {name, tag, underground, w, h (meters)}
    transitions = [(src_res, dst_res, dirvec (dx,dy) normalized-ish)]
    """
    areas = {}
    exits = []           # (src_res, linked_to_tag, x, y)
    tag_landing = {}     # dest tag -> (area_res, x, y); doors + waypoints
    for f in sorted(os.listdir(root)):
        if not f.endswith(".are"):
            continue
        res = f[:-4]
        a = gff_load(os.path.join(root, f))
        areas[res] = {
            "name": loc_get(a, "Name") or res,
            "tag": getv(a, "Tag", ""),
            "underground": bool(getv(a, "Flags", 0) & UNDERGROUND_FLAG),
            "w": getv(a, "Width", 8) * 10.0,
            "h": getv(a, "Height", 8) * 10.0,
        }
        git_path = os.path.join(root, res + ".git")
        if not os.path.exists(git_path):
            continue
        g = gff_load(git_path)
        for door in getv(g, "Door List", []):
            x, y = getv(door, "X", 0.0), getv(door, "Y", 0.0)
            tag = getv(door, "Tag", "")
            if tag:
                tag_landing.setdefault(tag, (res, x, y))
            link = getv(door, "LinkedTo", "")
            if link and getv(door, "LinkedToFlags", 0):
                exits.append((res, link, x, y))
        for trig in getv(g, "TriggerList", []):
            link = getv(trig, "LinkedTo", "")
            if link and getv(trig, "LinkedToFlags", 0):
                exits.append((res, link,
                              getv(trig, "XPosition", 0.0),
                              getv(trig, "YPosition", 0.0)))
        for wp in getv(g, "WaypointList", []):
            tag = getv(wp, "Tag", "")
            if tag:
                tag_landing.setdefault(tag, (res,
                                             getv(wp, "XPosition", 0.0),
                                             getv(wp, "YPosition", 0.0)))

    transitions = []
    for src, link, x, y in exits:
        hit = tag_landing.get(link)
        if not hit or hit[0] == src or hit[0] not in areas:
            continue
        dst, dx_land, dy_land = hit
        sa, da = areas[src], areas[dst]
        # normalized offsets from each area's center, range about [-0.5, 0.5];
        # NWN Y grows northward, so +y already means north.
        exit_off = (x / sa["w"] - 0.5, y / sa["h"] - 0.5)
        entry_off = (dx_land / da["w"] - 0.5, dy_land / da["h"] - 0.5)
        transitions.append((src, dst,
                            (exit_off[0] - entry_off[0],
                             exit_off[1] - entry_off[1])))
    return areas, transitions


def build_edges(transitions):
    """Collapse raw transitions into one edge per unordered pair.

    Returns edges[(a, b)] = {"vec": (dx, dy) meaning b relative to a,
                             "two_way": bool}
    """
    votes = defaultdict(list)
    for src, dst, vec in transitions:
        votes[(src, dst)].append(vec)
    edges = {}
    for (src, dst), vs in votes.items():
        if (dst, src) in edges:
            e = edges[(dst, src)]
            e["two_way"] = True
            # fold reverse-direction votes in, flipped
            n = len(vs)
            e["vec"] = (e["vec"][0] - sum(v[0] for v in vs) / n,
                        e["vec"][1] - sum(v[1] for v in vs) / n)
            continue
        n = len(vs)
        edges[(src, dst)] = {
            "vec": (sum(v[0] for v in vs) / n, sum(v[1] for v in vs) / n),
            "two_way": False,
        }
    return edges


def grid_step(vec):
    """Vote vector -> grid step (each axis in {-1,0,1}, diagonals allowed).
    Grid Y grows SOUTH (screen coordinates), NWN Y grows north - flip here,
    once. An axis only contributes if it's a meaningful share of the vote."""
    dx, dy = vec
    m = max(abs(dx), abs(dy))
    if m == 0:
        return (1, 0)
    sx = 0 if abs(dx) < 0.4 * m else (1 if dx > 0 else -1)
    sy = 0 if abs(dy) < 0.4 * m else (-1 if dy > 0 else 1)
    return (sx, sy) if (sx, sy) != (0, 0) else (1, 0)


# --- layout ------------------------------------------------------------------

def components(areas, edges):
    adj = defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    seen, comps = set(), []
    for res in areas:
        if res in seen:
            continue
        stack, comp = [res], []
        seen.add(res)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nb in adj[cur]:
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    return comps, adj


def layout_component(comp, areas, edges, adj):
    """Place each area of one component on an integer grid. Returns
    pos[res] = (gx, gy). Underground and surface areas may share a cell."""
    step_of = {}
    for (a, b), e in edges.items():
        sx, sy = grid_step(e["vec"])
        step_of[(a, b)] = (sx, sy)
        step_of[(b, a)] = (-sx, -sy)

    occupied = {}   # (gx, gy, layer) -> res
    pos = {}

    def layer(res):
        return 1 if areas[res]["underground"] else 0

    def place(res, gx, gy, from_cell=None):
        """Claim the free cell nearest to the ideal (gx, gy). A cell only
        conflicts within the same layer, so an underground area stacks onto
        a surface area's cell - that's the requested layering. When probing,
        prefer cells that keep the same compass side of the parent cell."""
        lay, ring_step = layer(res), 0
        while True:
            ring = [(gx, gy)] if ring_step == 0 else [
                (gx + ox, gy + oy)
                for ox in range(-ring_step, ring_step + 1)
                for oy in range(-ring_step, ring_step + 1)
                if max(abs(ox), abs(oy)) == ring_step]
            free = [c for c in ring if (c[0], c[1], lay) not in occupied]
            if free:
                if from_cell:
                    fx, fy = from_cell
                    want = (gx - fx, gy - fy)
                    # keep the direction from the parent: penalize sign flips
                    free.sort(key=lambda c: (
                        (0 if (c[0] - fx) * want[0] >= 0 else 1) +
                        (0 if (c[1] - fy) * want[1] >= 0 else 1),
                        (c[0] - gx) ** 2 + (c[1] - gy) ** 2))
                cx, cy = free[0]
                occupied[(cx, cy, lay)] = res
                pos[res] = (cx, cy)
                return
            ring_step += 1

    start = max(comp, key=lambda r: len(adj[r]))
    place(start, 0, 0)
    queue = [start]
    while queue:
        cur = queue.pop(0)
        cx, cy = pos[cur]
        for nb in sorted(adj[cur]):
            if nb in pos:
                continue
            dx, dy = step_of.get((cur, nb), (1, 0))
            place(nb, cx + dx, cy + dy, from_cell=(cx, cy))
            queue.append(nb)
    return pos


def layout_module(areas, edges):
    """Full layout: big components shelf-packed left to right, then all
    singleton (unjoined) areas in their own dense block below."""
    comps, adj = components(areas, edges)
    multi = [c for c in comps if len(c) > 1]
    singles = [c[0] for c in comps if len(c) == 1]

    placed = {}      # res -> (gx, gy) global grid
    comp_id = {}
    shelf_x, shelf_y, shelf_h = 0, 0, 0
    total_cells = sum(len(c) for c in multi) or 1
    max_row_w = max(12, int(total_cells ** 0.5 * 2.2))
    boxes = []       # (label, gx0, gy0, gx1, gy1)

    for idx, comp in enumerate(multi):
        pos = layout_component(comp, areas, edges, adj)
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if shelf_x > 0 and shelf_x + w > max_row_w:
            shelf_x, shelf_y, shelf_h = 0, shelf_y + shelf_h + 2, 0
        ox, oy = shelf_x - min(xs), shelf_y - min(ys)
        for res, (gx, gy) in pos.items():
            placed[res] = (gx + ox, gy + oy)
            comp_id[res] = idx
        boxes.append(("Region %d (%d areas)" % (idx + 1, len(comp)),
                      shelf_x, shelf_y, shelf_x + w - 1, shelf_y + h - 1))
        shelf_x += w + 2
        shelf_h = max(shelf_h, h)

    # singles block
    if singles:
        sy0 = shelf_y + shelf_h + 3
        per_row = max(8, max_row_w)
        for i, res in enumerate(sorted(singles)):
            placed[res] = (i % per_row, sy0 + i // per_row)
            comp_id[res] = -1
        boxes.append(("Unconnected areas (%d)" % len(singles),
                      0, sy0, per_row - 1, sy0 + (len(singles) - 1) // per_row))
    return placed, comp_id, boxes


# --- rendering ---------------------------------------------------------------

CELL_W, CELL_H = 190, 140
NODE_W, NODE_H = 158, 84
UG_OFF = 18  # px offset for underground node sharing a cell


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def node_xy(placed, areas, res):
    gx, gy = placed[res]
    x = gx * CELL_W + (CELL_W - NODE_W) / 2
    y = gy * CELL_H + (CELL_H - NODE_H) / 2
    if areas[res]["underground"]:
        x += UG_OFF
        y += UG_OFF
    return x, y


def render_svg(areas, edges, placed, boxes):
    parts = []
    # region boxes first (bottom of stack)
    for label, gx0, gy0, gx1, gy1 in boxes:
        x, y = gx0 * CELL_W - 12, gy0 * CELL_H - 12
        w = (gx1 - gx0 + 1) * CELL_W + 24
        h = (gy1 - gy0 + 1) * CELL_H + 24 + UG_OFF
        parts.append(
            "<rect class='region' x='%d' y='%d' width='%d' height='%d' rx='14'/>"
            "<text class='regionlabel' x='%d' y='%d'>%s</text>"
            % (x, y, w, h, x + 10, y - 4, esc(label)))
    # edges
    for (a, b), e in edges.items():
        ax, ay = node_xy(placed, areas, a)
        bx, by = node_xy(placed, areas, b)
        ax += NODE_W / 2
        ay += NODE_H / 2
        bx += NODE_W / 2
        by += NODE_H / 2
        cls = "edge"
        if areas[a]["underground"] != areas[b]["underground"]:
            cls += " crosslayer"
        marker = "" if e["two_way"] else " marker-end='url(#arrow)'"
        parts.append(
            "<line class='%s' x1='%.0f' y1='%.0f' x2='%.0f' y2='%.0f'%s>"
            "<title>%s %s %s%s</title></line>"
            % (cls, ax, ay, bx, by, marker, esc(a),
               "&#8596;" if e["two_way"] else "&#8594;", esc(b),
               " (cross-layer)" if "crosslayer" in cls else ""))
    # nodes
    for res in placed:
        a = areas[res]
        x, y = node_xy(placed, areas, res)
        cls = "node ug" if a["underground"] else "node surface"
        name = a["name"] if len(a["name"]) <= 26 else a["name"][:25] + "…"
        parts.append(
            "<g class='%s' data-name='%s' data-res='%s'>"
            "<rect x='%.0f' y='%.0f' width='%d' height='%d' rx='8'/>"
            "<text x='%.0f' y='%.0f'>%s</text>"
            "<text class='res' x='%.0f' y='%.0f'>%s%s</text>"
            "<title>%s\nresref: %s\ntag: %s\n%s</title></g>"
            % (cls, esc(a["name"].lower()), esc(res),
               x, y, NODE_W, NODE_H,
               x + NODE_W / 2, y + 34, esc(name),
               x + NODE_W / 2, y + 58, esc(res),
               " ▼" if a["underground"] else "",
               esc(a["name"]), esc(res), esc(a["tag"]),
               "underground" if a["underground"] else "surface"))
    max_x = max(gx for gx, _ in placed.values()) + 1
    max_y = max(gy for _, gy in placed.values()) + 1
    return "\n".join(parts), max_x * CELL_W + 40, max_y * CELL_H + 60


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>%(title)s</title><style>
html,body{margin:0;height:100%%;overflow:hidden;background:#15161a;color:#d8d9de;
 font-family:system-ui,sans-serif}
#bar{position:fixed;top:0;left:0;right:0;z-index:2;background:#1e1f24ee;
 padding:.5em 1em;display:flex;gap:1.2em;align-items:center;border-bottom:1px solid #333}
#bar input[type=search]{background:#2a2b31;color:#d8d9de;border:1px solid #555;
 padding:.25em .5em;width:16em}
#bar label{user-select:none}
#stage{position:absolute;inset:0;cursor:grab;touch-action:none;overflow:hidden}
#stage.panning{cursor:grabbing}
#stage svg{position:absolute;inset:0;width:100%%;height:100%%;display:block}
svg{width:100%%;height:100%%}
.region{fill:#1c1e26;stroke:#3a3d4d;stroke-width:1.5}
.regionlabel{fill:#7a8199;font-size:15px}
.node rect{fill:#2b3c55;stroke:#5a7cae;stroke-width:1.5}
.node.ug rect{fill:#23262b;stroke:#8a6d3b;stroke-dasharray:5 3}
.node text{fill:#e8e9ee;font-size:13px;text-anchor:middle}
.node text.res{fill:#9aa0ae;font-size:11px}
.node.hit rect{stroke:#ffd75e;stroke-width:3}
.node{cursor:pointer}
.edge{stroke:#6f7787;stroke-width:1.6}
.edge.crosslayer{stroke:#8a6d3b;stroke-dasharray:6 4}
.hidden{display:none}
#popup{position:fixed;z-index:3;background:#22242b;border:1px solid #556;
 border-radius:8px;padding:.6em .9em;display:none;min-width:14em;
 box-shadow:0 4px 18px #000a}
#popup b{display:block;margin-bottom:.35em}
#popup a{display:block;color:#7ab3ff;text-decoration:none;padding:.15em 0}
#popup a:hover{text-decoration:underline}
#popup .close{position:absolute;top:.2em;right:.5em;color:#889;cursor:pointer}
#legend{position:fixed;bottom:0;left:0;z-index:2;background:#1e1f24ee;
 padding:.4em 1em;font-size:12px;color:#9aa0ae;border-top-right-radius:8px}
</style></head><body>
<div id="bar">
 <b>%(title)s</b>%(navlinks)s
 <input type="search" id="q" placeholder="find area by name/resref&#8230;">
 <label><input type="checkbox" id="ls" checked> surface</label>
 <label><input type="checkbox" id="lu" checked> underground</label>
 <label>scale <span id="zoomval">1:1</span>
  <input type="range" id="zoom" min="1" max="100" value="100"
   style="width:10em;vertical-align:middle"></label>
 <button id="fit">fit all</button>
 <button id="reset">reset view</button>
 <span style="color:#9aa0ae">%(stats)s</span>
</div>
<div id="stage"><svg>
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
 markerHeight="7" orient="auto-start-reverse">
 <path d="M0 0 L10 5 L0 10 z" fill="#6f7787"/></marker></defs>
<g id="world" transform="translate(20,70) scale(1)">
%(svg)s
</g></svg></div>
<div id="legend">drag to pan &#183; wheel to zoom &#183; click an area to edit it
 &#183; solid line = linked areas &#183; dashed amber = surface&#8596;underground link
 &#183; &#9660; dashed box = underground (layered onto the surface cell it overlaps)</div>
<div id="popup"><span class="close">&#10005;</span><b id="ptitle"></b>
 <a id="plight" target="_blank">Lighting &amp; fog settings</a>
 <a id="ptags" target="_blank">Tag / resref</a>
 <a id="pscripts" target="_blank">Event scripts</a>
 <a id="plist" target="_blank">Open in editor area list</a>
 <div id="pwarn" style="color:#9aa0ae;font-size:11px;margin-top:.4em">
  Needs nwn_web_editor.py running at %(editor)s</div></div>
<script>
const EDITOR=%(editor_js)s;
const world=document.getElementById('world'),stage=document.getElementById('stage');
const popup=document.getElementById('popup');
let tx=20,ty=70,sc=1,panning=false,px=0,py=0,moved=0;
function apply(){world.setAttribute('transform',
 `translate(${tx},${ty}) scale(${sc})`);}
// Pointer events cover mouse AND touch: one pointer pans, two pinch-zoom.
// No pointer capture (it would swallow the node-click popup); pointers are
// tracked at window level and clicks suppressed only after a real drag.
const pointers=new Map();let lastDist=0;
stage.addEventListener('pointerdown',e=>{
 pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
 lastDist=0;moved=0;stage.classList.add('panning');});
window.addEventListener('pointermove',e=>{
 if(!pointers.has(e.pointerId))return;
 const prev=pointers.get(e.pointerId);
 pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
 moved+=Math.abs(e.clientX-prev.x)+Math.abs(e.clientY-prev.y);
 if(pointers.size===1){tx+=e.clientX-prev.x;ty+=e.clientY-prev.y;apply();}
 else if(pointers.size===2){
  const pts=[...pointers.values()];
  const dist=Math.hypot(pts[0].x-pts[1].x,pts[0].y-pts[1].y);
  if(lastDist>0)setScale(sc*dist/lastDist,(pts[0].x+pts[1].x)/2,(pts[0].y+pts[1].y)/2);
  lastDist=dist;}});
function lift(e){pointers.delete(e.pointerId);lastDist=0;
 if(pointers.size===0)stage.classList.remove('panning');}
window.addEventListener('pointerup',lift);
window.addEventListener('pointercancel',lift);
stage.addEventListener('click',e=>{
 if(moved>5)return;                       // it was a pan, not a click
 const node=e.target.closest('.node');
 if(!node){popup.style.display='none';return;}
 const res=node.dataset.res,q=encodeURIComponent(res);
 document.getElementById('ptitle').textContent=res;
 document.getElementById('plight').href=EDITOR+'/areas/edit?action=lighting&res='+q;
 document.getElementById('ptags').href=EDITOR+'/areas/edit?action=tags&res='+q;
 document.getElementById('pscripts').href=EDITOR+'/areas/edit?action=scripts&res='+q;
 document.getElementById('plist').href=EDITOR+'/areas?q='+q;
 popup.style.left=Math.min(e.clientX+8,innerWidth-260)+'px';
 popup.style.top=Math.min(e.clientY+8,innerHeight-190)+'px';
 popup.style.display='block';});
popup.querySelector('.close').onclick=()=>popup.style.display='none';
// slider runs 100:1 (far left, whole-module overview) to 1:1 (far right,
// full size): position V maps to shrink factor N = 101 - V.
const zoom=document.getElementById('zoom'),zoomval=document.getElementById('zoomval');
function syncSlider(){const n=Math.min(100,Math.max(1,Math.round(1/sc)));
 zoom.value=101-n;zoomval.textContent=n+':1';}
function setScale(ns,cx,cy){ns=Math.min(4,Math.max(.01,ns));
 tx=cx-(cx-tx)*(ns/sc);ty=cy-(cy-ty)*(ns/sc);sc=ns;apply();syncSlider();}
stage.addEventListener('wheel',e=>{e.preventDefault();
 setScale(sc*(e.deltaY<0?1.15:1/1.15),e.clientX,e.clientY);},{passive:false});
zoom.addEventListener('input',()=>{
 setScale(1/(101-parseInt(zoom.value,10)),innerWidth/2,innerHeight/2);});
const WORLD_W=%(w)d,WORLD_H=%(h)d;
// Fit the whole module inside the fixed stage window: scale the map down so
// its full extent fits, and center it. The window stays the same size; only
// the map representation shrinks/grows.
function fit(){
 const vw=stage.clientWidth||innerWidth,vh=stage.clientHeight||innerHeight;
 const ns=Math.min((vw-40)/WORLD_W,(vh-40)/WORLD_H);
 sc=Math.min(4,Math.max(.01,ns));
 tx=(vw-WORLD_W*sc)/2;ty=(vh-WORLD_H*sc)/2;apply();syncSlider();}
document.getElementById('fit').onclick=fit;
document.getElementById('reset').onclick=()=>{tx=20;ty=70;sc=1;apply();syncSlider();};
// Start showing the entire module.
fit();window.addEventListener('resize',fit);
document.getElementById('q').addEventListener('input',e=>{
 const q=e.target.value.toLowerCase();
 document.querySelectorAll('.node').forEach(n=>{
  const hit=q&&(n.dataset.name.includes(q)||n.dataset.res.includes(q));
  n.classList.toggle('hit',!!hit);});});
function layerToggle(){
 const s=document.getElementById('ls').checked,u=document.getElementById('lu').checked;
 document.querySelectorAll('.node.surface').forEach(n=>n.classList.toggle('hidden',!s));
 document.querySelectorAll('.node.ug').forEach(n=>n.classList.toggle('hidden',!u));}
document.getElementById('ls').onchange=layerToggle;
document.getElementById('lu').onchange=layerToggle;
</script></body></html>
"""


def main():
    global NWN_GFF
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=".", help="flat dir of .are/.git")
    ap.add_argument("-o", "--out", default="area_map.html")
    ap.add_argument("--title", default="Module area map")
    ap.add_argument("--nwn-gff", default=None)
    ap.add_argument("--editor-url", default="http://127.0.0.1:8340",
                    help="base URL of a running nwn_web_editor.py; area "
                         "nodes link to its lighting/tags/scripts forms")
    ap.add_argument("--nav", action="append", default=[], metavar="LABEL=URL",
                    help="extra top-bar link (repeatable), e.g. "
                         "--nav 'Wiki=/hos1-wiki/'")
    args = ap.parse_args()
    NWN_GFF = find_nwn_gff(args.nwn_gff)

    areas, transitions = read_module(os.path.abspath(args.dir))
    edges = build_edges(transitions)
    placed, comp_id, boxes = layout_module(areas, edges)
    svg, w, h = render_svg(areas, edges, placed, boxes)

    n_regions = len([b for b in boxes if not b[0].startswith("Unconnected")])
    n_single = len([r for r, c in comp_id.items() if c == -1])
    n_ug = len([r for r in areas if areas[r]["underground"]])
    stats = ("%d areas (%d underground) &#183; %d transitions &#183; "
             "%d connected regions &#183; %d unconnected"
             % (len(areas), n_ug, len(edges), n_regions, n_single))
    editor = args.editor_url.rstrip("/")
    navlinks = "".join(
        " <a href='%s' style='color:#7ab3ff'>%s</a>" % (esc(u), esc(l))
        for l, _, u in (n.partition("=") for n in args.nav) if u)
    with open(args.out, "w") as fh:
        fh.write(PAGE % {"title": esc(args.title), "svg": svg,
                         "w": w, "h": h, "stats": stats, "navlinks": navlinks,
                         "editor": esc(editor), "editor_js": json.dumps(editor)})
    print("areas: %d  transitions(raw): %d  edges(merged): %d  regions: %d  "
          "singletons: %d" % (len(areas), len(transitions), len(edges),
                              n_regions, n_single))
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
