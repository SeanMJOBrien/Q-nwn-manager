"""Walkability and ground height from the game's tile walkmeshes.

Ported from Q-nwn-mcp's `walkmesh.ts`.  Pipeline for a world position (x, y), in meters:
  tile = (floor(x/10), floor(y/10))  ->  ARE `Tile_List[ty * Width + tx]`  ->  tileset `.set` [TILE<id>] Model
  ->  `<model>.wok` (ASCII walkmesh)  ->  rotate into the tile's unrotated [-5, 5] space (Tile_Orientation)
  ->  2-D triangle test  ->  surfacemat.2da `Walk` flag of the face material  +  interpolated Z.
Where several faces overlap, the walkable one with the greatest Z wins (e.g. a bridge over a pit).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import gffjson as G
from .gamedata import GameData

TILE = 10.0
# Metres per ARE Tile_Height level when a tileset does not say.  The real value is the tileset's own
# `[GENERAL] Transition=` (5 for most outdoor sets, 4 for tcn01, 2 for tno01): TFN's `benzor` (tcn01) has 115
# objects on raised tiles and 94 % match to 0.5 m with Transition=4 but only 3 % with a flat 5; tno01 areas 92 % vs 0 %.
HEIGHT_STEP = 5.0

# surfacemat.2da fallback (id -> (label, walkable))
DEFAULT_SURFACES = {
    0: ("NotDefined", False), 1: ("Dirt", True), 2: ("Obscuring", False), 3: ("Grass", True), 4: ("Stone", True),
    5: ("Wood", True), 6: ("Water", True), 7: ("Nonwalk", False), 8: ("Transparent", False), 9: ("Carpet", True),
    10: ("Metal", True), 11: ("Puddles", True), 12: ("Swamp", True), 13: ("Mud", True), 14: ("Leaves", True),
    15: ("Lava", False), 16: ("BottomlessPit", False), 17: ("DeepWater", False), 18: ("Door", True),
    19: ("Snow", True), 20: ("Sand", True), 21: ("Barebones", True), 22: ("StoneBridge", True),
}


@dataclass
class Wok:
    verts: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int, int]]                    # v1, v2, v3, surface material id
    boxes: list[tuple[float, float, float, float]] = field(default_factory=list)  # per face: xmin, xmax, ymin, ymax

    def build_boxes(self) -> None:
        self.boxes = []
        for v1, v2, v3, _m in self.faces:
            try:
                xs = [self.verts[v1][0], self.verts[v2][0], self.verts[v3][0]]
                ys = [self.verts[v1][1], self.verts[v2][1], self.verts[v3][1]]
            except IndexError:
                self.boxes.append((1e9, -1e9, 1e9, -1e9))
                continue
            self.boxes.append((min(xs), max(xs), min(ys), max(ys)))


def parse_wok(text: str) -> Wok:
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].strip()
        if line.startswith("verts "):
            count = int(line.split()[1])
            i += 1
            for _ in range(count):
                parts = lines[i].split()
                if len(parts) >= 3:
                    verts.append((float(parts[0]), float(parts[1]), float(parts[2])))
                i += 1
            break
        i += 1
    while i < n:
        line = lines[i].strip()
        if line.startswith("faces "):
            count = int(line.split()[1])
            i += 1
            for _ in range(count):
                parts = lines[i].split()
                if len(parts) >= 8:  # v1 v2 v3 smooth adj1 adj2 adj3 material
                    faces.append((int(parts[0]), int(parts[1]), int(parts[2]), int(parts[7])))
                i += 1
            break
        i += 1
    # the geometry node carries a position offset (e.g. 0 0 1.5) that the vertices are relative to
    m = re.search(r"^\s*node\s+aabb\b.*?^\s*position\s+(\S+)\s+(\S+)\s+(\S+)", text, re.M | re.S)
    if m:
        ox, oy, oz = float(m.group(1)), float(m.group(2)), float(m.group(3))
        verts = [(x + ox, y + oy, z + oz) for x, y, z in verts]
    wok = Wok(verts, faces)
    wok.build_boxes()
    return wok


def parse_set(text: str) -> list[str]:
    """Tile id -> model name from a tileset .set file."""
    models: dict[int, str] = {}
    cur: int | None = None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^\[TILE(\d+)\]$", line, re.I)
        if m:
            cur = int(m.group(1))
            continue
        if line.startswith("["):
            cur = None
            continue
        if cur is not None and line.lower().startswith("model="):
            models[cur] = line.split("=", 1)[1].strip().lower()
    return [models.get(i, "") for i in range(max(models) + 1)] if models else []


def parse_transition(text: str) -> float:
    """`[GENERAL] Transition=` of a tileset .set: metres per Tile_Height level (HEIGHT_STEP when absent or invalid)."""
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            section = line.upper()
            continue
        if section == "[GENERAL]" and line.lower().startswith("transition="):
            try:
                value = float(line.split("=", 1)[1].strip())
            except ValueError:
                return HEIGHT_STEP
            return value if value > 0 else HEIGHT_STEP
    return HEIGHT_STEP


def parse_surfacemat(text: str) -> dict[int, tuple[str, bool]]:
    out: dict[int, tuple[str, bool]] = {}
    lines = text.splitlines()
    header = None
    for line in lines[2:]:
        parts = line.split()
        if not parts:
            continue
        if header is None:
            header = parts
            continue
        try:
            rid = int(parts[0])
            walk = parts[1 + header.index("Walk")] if "Walk" in header else "0"
            label = parts[1 + header.index("Label")] if "Label" in header else str(rid)
        except (ValueError, IndexError):
            continue
        out[rid] = (label, walk == "1")
    return out


def unrotate(x: float, y: float, orientation: int) -> tuple[float, float]:
    """World-local (tile-centred) coords -> the tile model's own unrotated space."""
    o = orientation % 4
    if o == 1:
        return y, -x
    if o == 2:
        return -x, -y
    if o == 3:
        return -y, x
    return x, y


def _in_tri(px, py, ax, ay, bx, by, cx, cy) -> bool:
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(den) < 1e-10:
        return False
    a = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den
    b = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den
    c = 1 - a - b
    return a >= -1e-6 and b >= -1e-6 and c >= -1e-6


def _interp_z(px, py, v1, v2, v3) -> float:
    den = (v2[1] - v3[1]) * (v1[0] - v3[0]) + (v3[0] - v2[0]) * (v1[1] - v3[1])
    if abs(den) < 1e-10:
        return v1[2]
    a = ((v2[1] - v3[1]) * (px - v3[0]) + (v3[0] - v2[0]) * (py - v3[1])) / den
    b = ((v3[1] - v1[1]) * (px - v3[0]) + (v1[0] - v3[0]) * (py - v3[1])) / den
    return a * v1[2] + b * v2[2] + (1 - a - b) * v3[2]


@dataclass
class Probe:
    walkable: bool
    z: float | None = None
    material: int | None = None
    label: str = ""
    error: str = ""


class WalkGrid:
    """1 m raster of an area: 0 = not walkable, 1 = walkable, 2 = unknown (no mesh data)."""

    def __init__(self, width_m: int, height_m: int):
        self.width, self.height = width_m, height_m
        self.rows = [bytearray(width_m) for _ in range(height_m)]  # rows[y][x], y = 0 is the south edge

    def at(self, x: float, y: float) -> int:
        xi, yi = int(x), int(y)
        if 0 <= xi < self.width and 0 <= yi < self.height:
            return self.rows[yi][xi]
        return 0

    def to_rows(self) -> list[str]:
        return ["".join(str(c) for c in row) for row in self.rows]

    def walkable_fraction(self) -> float:
        total = sum(1 for row in self.rows for c in row if c != 2)
        return sum(1 for row in self.rows for c in row if c == 1) / total if total else 0.0


class Walkmesh:
    def __init__(self, gamedata: GameData):
        self.gd = gamedata
        self._sets: dict[str, list[str]] = {}
        self._steps: dict[str, float] = {}
        self._woks: dict[str, Wok | None] = {}
        self._surf: dict[int, tuple[str, bool]] | None = None
        self._raster: dict[tuple[str, int], list[tuple[int, float | None]]] = {}
        self._grids: dict[tuple, WalkGrid] = {}

    def available(self) -> bool:
        return self.gd.available()

    # ------------------------------------------------------------------ data
    def surfaces(self) -> dict[int, tuple[str, bool]]:
        if self._surf is None:
            text = self.gd.read_text("surfacemat.2da")
            parsed = parse_surfacemat(text) if text else {}
            self._surf = {**DEFAULT_SURFACES, **parsed}
        return self._surf

    def tileset_models(self, tileset: str) -> list[str]:
        key = tileset.lower()
        if key not in self._sets:
            text = self.gd.read_text(f"{key}.set")
            self._sets[key] = parse_set(text) if text else []
            self._steps[key] = parse_transition(text) if text else HEIGHT_STEP
        return self._sets[key]

    def height_step(self, tileset: str) -> float:
        """Metres per Tile_Height level in this tileset (its `Transition=`; 5 when unknown)."""
        self.tileset_models(tileset)
        return self._steps.get(tileset.lower(), HEIGHT_STEP)

    def wok(self, model: str) -> Wok | None:
        key = model.lower()
        if key not in self._woks:
            text = self.gd.read_text(f"{key}.wok")
            self._woks[key] = parse_wok(text) if text else None
        return self._woks[key]

    def prepare(self, are: dict) -> None:
        """Fetch the tileset .set and every .wok the area uses in as few extractor runs as possible."""
        tileset = G.get(are, "Tileset", "")
        self.gd.fetch_many([f"{tileset}.set", "surfacemat.2da"])
        models = self.tileset_models(tileset)
        needed = set()
        for t in (are.get("Tile_List") or {}).get("value", []):
            tid = G.get(t, "Tile_ID", -1)
            if 0 <= tid < len(models) and models[tid]:
                needed.add(models[tid])
        self.gd.fetch_many([f"{m}.wok" for m in sorted(needed)])

    # ---------------------------------------------------------------- probes
    def _tile(self, are: dict, tx: int, ty: int) -> tuple[str, int, int] | None:
        width = G.get(are, "Width", 0)
        tiles = (are.get("Tile_List") or {}).get("value", [])
        idx = ty * width + tx
        if not (0 <= tx < width and 0 <= idx < len(tiles)):
            return None
        t = tiles[idx]
        models = self.tileset_models(G.get(are, "Tileset", ""))
        tid = G.get(t, "Tile_ID", -1)
        if not (0 <= tid < len(models)) or not models[tid]:
            return None
        return models[tid], G.get(t, "Tile_Orientation", 0), G.get(t, "Tile_Height", 0)

    def _probe_local(self, wok: Wok, rx: float, ry: float) -> Probe | None:
        surf = self.surfaces()
        best_walk: Probe | None = None
        best_block: Probe | None = None
        for (v1, v2, v3, mat), (x0, x1, y0, y1) in zip(wok.faces, wok.boxes):
            if rx < x0 - 1e-6 or rx > x1 + 1e-6 or ry < y0 - 1e-6 or ry > y1 + 1e-6:
                continue
            a, b, c = wok.verts[v1], wok.verts[v2], wok.verts[v3]
            if not _in_tri(rx, ry, a[0], a[1], b[0], b[1], c[0], c[1]):
                continue
            label, walk = surf.get(mat, (f"Material_{mat}", False))
            p = Probe(walk, _interp_z(rx, ry, a, b, c), mat, label)
            if walk:
                if best_walk is None or p.z > best_walk.z:
                    best_walk = p
            elif best_block is None or p.z > best_block.z:
                best_block = p
        return best_walk or best_block

    def probe(self, are: dict, x: float, y: float) -> Probe:
        width, height = G.get(are, "Width", 0), G.get(are, "Height", 0)
        if not (0 <= x < width * TILE and 0 <= y < height * TILE):
            return Probe(False, error="outside the area")
        tx, ty = int(x // TILE), int(y // TILE)
        tile = self._tile(are, tx, ty)
        if tile is None:
            return Probe(False, error="tile data unavailable")
        model, orient, tile_h = tile
        wok = self.wok(model)
        if wok is None:
            return Probe(False, error=f"no walkmesh for {model}")
        lx, ly = x - tx * TILE - TILE / 2, y - ty * TILE - TILE / 2
        rx, ry = unrotate(lx, ly, orient)
        res = self._probe_local(wok, rx, ry)
        if res is None:
            return Probe(False, error="no walkmesh face here")
        if res.z is not None:
            res.z += tile_h * self.height_step(G.get(are, "Tileset", ""))
        return res

    def clearance(self, are: dict, x: float, y: float, buffer: float = 1.0) -> Probe:
        """Like `probe`, but also requires the four cardinal points `buffer` m away to be walkable."""
        center = self.probe(are, x, y)
        if not center.walkable:
            return center
        for dx, dy, name in ((0, buffer, "north"), (0, -buffer, "south"), (buffer, 0, "east"), (-buffer, 0, "west")):
            p = self.probe(are, x + dx, y + dy)
            if not p.walkable:
                return Probe(False, center.z, center.material, center.label,
                             error=f"within {buffer:g} m of non-walkable {p.label or p.error} to the {name}")
        return center

    # ------------------------------------------------------------------ grid
    def _tile_raster(self, model: str, orient: int) -> list[tuple[int, float | None]]:
        key = (model, orient)
        if key in self._raster:
            return self._raster[key]
        wok = self.wok(model)
        cells: list[tuple[int, float | None]] = []
        for j in range(int(TILE)):
            for i in range(int(TILE)):
                if wok is None:
                    cells.append((2, None))
                    continue
                lx, ly = i + 0.5 - TILE / 2, j + 0.5 - TILE / 2
                rx, ry = unrotate(lx, ly, orient)
                p = self._probe_local(wok, rx, ry)
                cells.append((1 if (p and p.walkable) else 0, p.z if p else None))
        self._raster[key] = cells
        return cells

    def grid(self, are: dict) -> WalkGrid:
        """1 m walkability raster for the whole area (cached per area content)."""
        width, height = G.get(are, "Width", 0), G.get(are, "Height", 0)
        sig = (G.get(are, "ResRef", ""), width, height, hash(G.dumps(are.get("Tile_List", {}))))
        if sig in self._grids:
            return self._grids[sig]
        self.prepare(are)
        grid = WalkGrid(width * int(TILE), height * int(TILE))
        for ty in range(height):
            for tx in range(width):
                tile = self._tile(are, tx, ty)
                if tile is None:
                    cells = [(2, None)] * 100
                else:
                    cells = self._tile_raster(tile[0], tile[1])
                for j in range(int(TILE)):
                    row = grid.rows[ty * int(TILE) + j]
                    for i in range(int(TILE)):
                        row[tx * int(TILE) + i] = cells[j * int(TILE) + i][0]
        self._grids[sig] = grid
        return grid
