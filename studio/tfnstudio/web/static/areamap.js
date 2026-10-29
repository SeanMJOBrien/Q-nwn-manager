// Pan/zoom canvas map of one TFN area.
// World coordinates are meters: x = east, y = north, origin at the south-west corner. One tile = 10 m.
// Facing is degrees, 0 = east, 90 = north (NWScript convention).

export const KIND_COLOR = {
  creature: '#e5675c', placeable: '#5aa0ff', waypoint: '#46c07a', door: '#e0a43a', trigger: '#b58cf0',
  sound: '#7fd0d0', store: '#f0b84d', encounter: '#d6d66f', marker: '#c86cf0', spot: '#2ec4b6', pivot: '#ffffff',
};
const MARKER_RE = /^random([1-9])$/;
const TILE = 10;

export function tileColor(id) { return `hsl(${(Number(id) * 47) % 360} 26% 25%)`; }

/** Where a random camp's object `o` stands when the camp's pivot `origin` is moved to `spot` and turned to the spot's facing.
 *  Same maths as campevent.transform on the server: counter-clockwise by spot.facing - origin.facing about the pivot. */
export function xformPoint(o, origin, spot) {
  const th = (spot.facing - origin.facing) * Math.PI / 180, c = Math.cos(th), s = Math.sin(th);
  const dx = o.x - origin.x, dy = o.y - origin.y;
  return { x: spot.x + dx * c - dy * s, y: spot.y + dx * s + dy * c, facing: ((((o.facing || 0) + spot.facing - origin.facing) % 360) + 360) % 360 };
}

export class AreaMap {
  /**
   * handlers: { onHover(x, y | null), onClick(x, y, ev)  // tool 'place'
   *             onPick(index, ev)                          // tool 'select'; -1 = empty space
   *             onMove(index, x, y, final)                 // dragging a plan object
   *             onSpotPick(index, ev) / onSpotMove(index, x, y, final)  // random-camp spots (tool 'select')
   *             onView() }                                 // pan/zoom changed
   */
  constructor(canvas, handlers = {}) {
    this.c = canvas;
    this.ctx = canvas.getContext('2d');
    this.h = handlers;
    this.area = null;
    this.plan = [];
    this.selected = new Set();
    this.ghost = null;
    this.hidePlan = '';
    this.layers = { tiles: true, grid: true, existing: true, hints: false, labels: false, walk: true, camp: true };
    this.camp = null;     // random camp: { origin, spots: [{x, y, facing}], template: [plan objects], sel, radius, designBuilt }
    this.walk = null;
    this.view = { scale: 4, ox: 24, oy: 24 };
    this.tool = 'select';
    this.snap = 0.5;
    this._drag = null;
    this._hover = null;
    this._space = false;
    this._raf = 0;
    this._bind();
    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(canvas.parentElement);
    this.resize();
  }

  // ------------------------------------------------------------ geometry
  get W() { return this.area ? this.area.width * TILE : 100; }
  get H() { return this.area ? this.area.height * TILE : 100; }
  toScreen(x, y) { return [this.view.ox + x * this.view.scale, this.view.oy - y * this.view.scale]; }
  toWorld(sx, sy) { return [(sx - this.view.ox) / this.view.scale, (this.view.oy - sy) / this.view.scale]; }
  inBounds(x, y, margin = 0) { return x >= margin && y >= margin && x <= this.W - margin && y <= this.H - margin; }
  snapPoint(x, y, free = false) {
    if (free || !this.snap) return [Math.round(x * 100) / 100, Math.round(y * 100) / 100];
    return [Math.round(x / this.snap) * this.snap, Math.round(y / this.snap) * this.snap];
  }

  // -------------------------------------------------------------- state
  setArea(area) { this.area = area; this.fit(); }
  setPlan(objs) { this.plan = objs; this.render(); }
  setSelected(indices) { this.selected = new Set(indices); this.render(); }
  setGhost(items) { this.ghost = items; this.render(); }
  setCamp(camp) { this.camp = camp; this.render(); }

  /** data = {available, width, height, rows[]} from /api/areas/<resref>/walk ('0' blocked, '1' walkable, '2' unknown; row 0 = south). */
  setWalk(data) {
    this.walk = null;
    if (data && data.available) {
      const c = document.createElement('canvas');
      c.width = data.width; c.height = data.height;
      const cx = c.getContext('2d');
      const img = cx.createImageData(data.width, data.height);
      for (let y = 0; y < data.height; y++) {
        const row = data.rows[y], py = data.height - 1 - y;
        for (let x = 0; x < data.width; x++) {
          const v = row.charCodeAt(x) - 48, o = (py * data.width + x) * 4;
          if (v === 1) { img.data[o] = 70; img.data[o + 1] = 205; img.data[o + 2] = 120; img.data[o + 3] = 62; }
          else if (v === 0) { img.data[o] = 6; img.data[o + 1] = 8; img.data[o + 2] = 14; img.data[o + 3] = 130; }
        }
      }
      cx.putImageData(img, 0, 0);
      this.walk = { data, canvas: c };
    }
    this.render();
  }

  /** 1 walkable, 0 blocked/outside, 2 unknown, null when no walkmesh data is loaded. */
  walkAt(x, y) {
    if (!this.walk) return null;
    const d = this.walk.data, xi = Math.floor(x), yi = Math.floor(y);
    if (xi < 0 || yi < 0 || xi >= d.width || yi >= d.height) return 0;
    return d.rows[yi].charCodeAt(xi) - 48;
  }

  /** Creatures, spawn markers and waypoints need ground to stand on; props may legitimately sit on rock. */
  needsGround(kind) { return kind === 'creature' || kind === 'marker' || kind === 'waypoint' || kind === 'spot'; }
  blocked(o) { return this.needsGround(o.kind) && this.walkAt(o.x, o.y) === 0; }
  setLayers(l) { Object.assign(this.layers, l); this.render(); }
  setTool(t) { this.tool = t; this._cursor(); this.render(); }

  resize() {
    const p = this.c.parentElement;
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(50, p.clientWidth), h = Math.max(50, p.clientHeight);
    this.cw = w; this.ch = h;
    this.c.width = Math.round(w * dpr); this.c.height = Math.round(h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!this._fitted) this.fit(); else this.render();
  }

  fit() {
    this._fitted = true;
    const pad = 28;
    const sc = Math.min((this.cw - pad * 2) / this.W, (this.ch - pad * 2) / this.H);
    this.view.scale = Math.max(0.3, Math.min(90, sc || 4));
    this.view.ox = (this.cw - this.W * this.view.scale) / 2;
    this.view.oy = (this.ch + this.H * this.view.scale) / 2;
    this.render();
    this.h.onView && this.h.onView();
  }

  zoomAt(sx, sy, factor) {
    const [wx, wy] = this.toWorld(sx, sy);
    const sc = Math.max(0.3, Math.min(90, this.view.scale * factor));
    this.view.scale = sc;
    this.view.ox = sx - wx * sc;
    this.view.oy = sy + wy * sc;
    this.render();
    this.h.onView && this.h.onView();
  }

  centerOn(x, y) {
    this.view.ox = this.cw / 2 - x * this.view.scale;
    this.view.oy = this.ch / 2 + y * this.view.scale;
    this.render();
  }

  // ------------------------------------------------------------ picking
  /** Index of the plan object under screen point (sx, sy), or -1. */
  pick(sx, sy) {
    let best = -1, bd = 14 * 14;
    this.plan.forEach((o, i) => {
      const [px, py] = this.toScreen(o.x, o.y);
      const d = (px - sx) ** 2 + (py - sy) ** 2;
      if (d < bd) { bd = d; best = i; }
    });
    return best;
  }

  /** Index of the random-camp spot under screen point (sx, sy), or -1. */
  pickSpot(sx, sy) {
    if (!this.camp || !this.layers.camp) return -1;
    let best = -1, bd = 16 * 16;
    this.camp.spots.forEach((p, i) => {
      const [px, py] = this.toScreen(p.x, p.y);
      const d = (px - sx) ** 2 + (py - sy) ** 2;
      if (d < bd) { bd = d; best = i; }
    });
    return best;
  }

  // ------------------------------------------------------------- events
  _evPos(ev) {
    const r = this.c.getBoundingClientRect();
    return [ev.clientX - r.left, ev.clientY - r.top];
  }

  _cursor() {
    this.c.style.cursor = this._drag && this._drag.type === 'pan' ? 'grabbing'
      : this.tool === 'pan' || this._space ? 'grab'
      : this.tool === 'place' ? 'crosshair' : 'default';
  }

  _bind() {
    const c = this.c;
    c.addEventListener('contextmenu', e => e.preventDefault());
    c.addEventListener('mousedown', e => {
      c.focus && c.focus();
      const [sx, sy] = this._evPos(e);
      const panning = e.button === 1 || e.button === 2 || this.tool === 'pan' || this._space;
      if (panning) {
        this._drag = { type: 'pan', sx, sy, ox: this.view.ox, oy: this.view.oy, moved: 0 };
        this._cursor(); e.preventDefault(); return;
      }
      if (e.button !== 0) return;
      if (this.tool === 'select') {
        const hit = this.pick(sx, sy);
        const spot = hit >= 0 ? -1 : this.pickSpot(sx, sy);
        if (hit >= 0) {
          this.h.onPick && this.h.onPick(hit, e);
          this._drag = { type: 'obj', index: hit, sx, sy, moved: 0 };
        } else if (spot >= 0) {
          this.h.onSpotPick && this.h.onSpotPick(spot, e);
          this._drag = { type: 'spot', index: spot, sx, sy, moved: 0 };
        } else this._drag = { type: 'click', sx, sy, moved: 0 };
      } else this._drag = { type: 'click', sx, sy, moved: 0 };
    });
    window.addEventListener('mousemove', e => {
      const [sx, sy] = this._evPos(e);
      const d = this._drag;
      if (d) {
        d.moved = Math.max(d.moved, Math.abs(sx - d.sx) + Math.abs(sy - d.sy));
        if (d.type === 'pan') {
          this.view.ox = d.ox + (sx - d.sx); this.view.oy = d.oy + (sy - d.sy);
          this.render(); this.h.onView && this.h.onView(); return;
        }
        if ((d.type === 'obj' || d.type === 'spot') && d.moved > 4) {
          const [wx, wy] = this.snapPoint(...this.toWorld(sx, sy), e.altKey);
          const cb = d.type === 'obj' ? this.h.onMove : this.h.onSpotMove;
          if (this.inBounds(wx, wy, 0.5)) cb && cb(d.index, wx, wy, false);
          return;
        }
      }
      const r = this.c.getBoundingClientRect();
      const inside = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
      if (!inside) { if (this._hover) { this._hover = null; this.h.onHover && this.h.onHover(null, null); } return; }
      const [wx, wy] = this.toWorld(sx, sy);
      this._hover = { sx, sy, x: wx, y: wy, alt: e.altKey };
      this.h.onHover && this.h.onHover(wx, wy, e);
      if (this.ghost || this.tool === 'select') this.render();
    });
    window.addEventListener('mouseup', e => {
      const d = this._drag;
      if (!d) return;
      this._drag = null; this._cursor();
      const [sx, sy] = this._evPos(e);
      if ((d.type === 'obj' || d.type === 'spot') && d.moved > 4) {
        const [wx, wy] = this.snapPoint(...this.toWorld(sx, sy), e.altKey);
        const cb = d.type === 'obj' ? this.h.onMove : this.h.onSpotMove;
        if (this.inBounds(wx, wy, 0.5)) cb && cb(d.index, wx, wy, true);
        return;
      }
      if (d.type === 'click' && d.moved <= 4) {
        const [wx, wy] = this.snapPoint(...this.toWorld(sx, sy), e.altKey);
        if (this.tool === 'place') this.h.onClick && this.h.onClick(wx, wy, e);
        else this.h.onPick && this.h.onPick(-1, e);
      }
    });
    c.addEventListener('wheel', e => {
      e.preventDefault();
      const [sx, sy] = this._evPos(e);
      this.zoomAt(sx, sy, Math.pow(1.0018, -e.deltaY));
    }, { passive: false });
    c.addEventListener('mouseleave', () => { this._hover = null; this.h.onHover && this.h.onHover(null, null); this.render(); });
    window.addEventListener('keydown', e => {
      if (e.code === 'Space' && !/INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || '')) {
        if (!this._space) { this._space = true; this._cursor(); }
        e.preventDefault();
      }
    });
    window.addEventListener('keyup', e => { if (e.code === 'Space') { this._space = false; this._cursor(); } });
  }

  // ------------------------------------------------------------ drawing
  render() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => { this._raf = 0; this.draw(); });
  }

  _shape(kind, sx, sy, size, color, alpha = 1, facing = null, group = null) {
    const g = this.ctx;
    g.save();
    g.globalAlpha = alpha;
    g.fillStyle = color;
    g.strokeStyle = 'rgba(255,255,255,.85)';
    g.lineWidth = 1;
    g.beginPath();
    if (kind === 'placeable') g.rect(sx - size, sy - size, size * 2, size * 2);
    else if (kind === 'marker') { g.moveTo(sx, sy - size * 1.4); g.lineTo(sx + size * 1.4, sy); g.lineTo(sx, sy + size * 1.4); g.lineTo(sx - size * 1.4, sy); g.closePath(); }
    else if (kind === 'waypoint') { g.moveTo(sx, sy - size * 1.3); g.lineTo(sx + size * 1.2, sy + size); g.lineTo(sx - size * 1.2, sy + size); g.closePath(); }
    else if (kind === 'spot') g.arc(sx, sy, Math.max(size * 1.7, 9), 0, Math.PI * 2);
    else if (kind === 'pivot') { g.arc(sx, sy, Math.max(size, 6), 0, Math.PI * 2); g.moveTo(sx - size * 2, sy); g.lineTo(sx + size * 2, sy); g.moveTo(sx, sy - size * 2); g.lineTo(sx, sy + size * 2); }
    else g.arc(sx, sy, size, 0, Math.PI * 2);
    g.fill(); g.stroke();
    if (facing !== null && kind !== 'marker') {
      const r = kind === 'spot' ? Math.max(size * 3.4, 22) : Math.max(size * 2.2, 10), a = facing * Math.PI / 180;
      g.beginPath(); g.moveTo(sx, sy); g.lineTo(sx + Math.cos(a) * r, sy - Math.sin(a) * r);
      if (kind === 'spot') {                         // arrow head: the camp's front faces this way
        const hx = sx + Math.cos(a) * r, hy = sy - Math.sin(a) * r;
        g.moveTo(hx, hy); g.lineTo(hx - Math.cos(a - 0.5) * 7, hy + Math.sin(a - 0.5) * 7);
        g.moveTo(hx, hy); g.lineTo(hx - Math.cos(a + 0.5) * 7, hy + Math.sin(a + 0.5) * 7);
      }
      g.stroke();
    }
    if (group !== null) {
      g.fillStyle = '#fff'; g.font = `bold ${Math.max(9, size * 1.5)}px system-ui, sans-serif`;
      g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(String(group), sx, sy + 0.5);
    }
    g.restore();
  }

  draw() {
    const g = this.ctx, v = this.view, W = this.W, H = this.H;
    g.clearRect(0, 0, this.cw, this.ch);
    g.fillStyle = '#161a26'; g.fillRect(0, 0, this.cw, this.ch);
    if (!this.area) return;
    const [x0, y0] = this.toScreen(0, H);
    const pw = W * v.scale, ph = H * v.scale;
    g.fillStyle = '#262d40'; g.fillRect(x0, y0, pw, ph);

    // tiles
    const tiles = this.area.tiles || [];
    const aw = this.area.width, ah = this.area.height;
    if (this.layers.tiles && tiles.length === aw * ah) {
      const cell = TILE * v.scale;
      for (let i = 0; i < tiles.length; i++) {
        const col = i % aw, row = Math.floor(i / aw);
        const [tx, ty] = this.toScreen(col * TILE, (row + 1) * TILE);
        if (tx > this.cw || ty > this.ch || tx + cell < 0 || ty + cell < 0) continue;
        g.fillStyle = tileColor(tiles[i][0]);
        g.fillRect(tx, ty, cell, cell);
        if (cell > 46) {
          g.fillStyle = 'rgba(255,255,255,.35)'; g.font = '11px ui-monospace, monospace';
          g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(`#${tiles[i][0]}`, tx + cell / 2, ty + cell / 2);
        }
      }
    }
    // walkability overlay (1 px per meter, scaled)
    if (this.walk && this.layers.walk) {
      g.save(); g.imageSmoothingEnabled = false;
      g.drawImage(this.walk.canvas, x0, y0, pw, ph);
      g.restore();
    }
    // grid
    if (this.layers.grid) {
      g.strokeStyle = 'rgba(255,255,255,.13)'; g.lineWidth = 1; g.beginPath();
      for (let i = 0; i <= aw; i++) { const [sx] = this.toScreen(i * TILE, 0); g.moveTo(sx + .5, y0); g.lineTo(sx + .5, y0 + ph); }
      for (let j = 0; j <= ah; j++) { const [, sy] = this.toScreen(0, j * TILE); g.moveTo(x0, sy + .5); g.lineTo(x0 + pw, sy + .5); }
      g.stroke();
      if (v.scale > 1.2) {  // fine 5 m ticks along the edges help eyeballing coordinates
        g.fillStyle = 'rgba(255,255,255,.4)'; g.font = '10px ui-monospace, monospace'; g.textAlign = 'center'; g.textBaseline = 'top';
        const step = v.scale > 6 ? 10 : 20;
        for (let x = 0; x <= W; x += step) { const [sx] = this.toScreen(x, 0); g.fillText(String(x), sx, y0 + ph + 3); }
        g.textAlign = 'right'; g.textBaseline = 'middle';
        for (let y = 0; y <= H; y += step) { const [, sy] = this.toScreen(0, y); g.fillText(String(y), x0 - 4, sy); }
      }
    }
    g.strokeStyle = 'rgba(255,255,255,.55)'; g.lineWidth = 1.5; g.strokeRect(x0, y0, pw, ph);

    const objs = this.area.objects || [];
    // walkable hints: creatures/waypoints/doors stand on walkable ground
    if (this.layers.hints) {
      g.fillStyle = 'rgba(70,192,122,.10)';
      for (const o of objs) {
        if (!['creature', 'waypoint', 'door'].includes(o.kind) || (this.hidePlan && o.plan === this.hidePlan)) continue;
        const [sx, sy] = this.toScreen(o.x, o.y);
        g.beginPath(); g.arc(sx, sy, 4 * v.scale, 0, Math.PI * 2); g.fill();
      }
    }
    // existing objects
    if (this.layers.existing) {
      const size = Math.max(2, Math.min(5, v.scale * 0.5));
      for (const o of objs) {
        if (this.hidePlan && o.plan === this.hidePlan) continue;
        const [sx, sy] = this.toScreen(o.x, o.y);
        if (sx < -10 || sy < -10 || sx > this.cw + 10 || sy > this.ch + 10) continue;
        const m = o.kind === 'creature' ? MARKER_RE.exec(o.resref) : null;
        this._shape(m ? 'marker' : o.kind, sx, sy, size, KIND_COLOR[m ? 'marker' : o.kind] || '#999', 0.78, null, m ? m[1] : null);
        if (this.layers.labels && v.scale > 5) this._label(sx, sy, o.resref || o.kind, 0.6);
      }
    }
    // plan objects
    const hov = this._hover && this.tool === 'select' ? this.pick(this._hover.sx, this._hover.sy) : -1;
    const psize = Math.max(4, Math.min(8, v.scale * 0.8));
    this.plan.forEach((o, i) => {
      const [sx, sy] = this.toScreen(o.x, o.y);
      if (sx < -20 || sy < -20 || sx > this.cw + 20 || sy > this.ch + 20) return;
      this._shape(o.kind, sx, sy, psize, KIND_COLOR[o.kind], 1, o.facing, o.kind === 'marker' ? o.group : null);
      if (this.blocked(o)) {
        g.save(); g.strokeStyle = '#ff4d4d'; g.lineWidth = 2; g.setLineDash([3, 2]);
        g.beginPath(); g.arc(sx, sy, psize + 4, 0, Math.PI * 2); g.stroke(); g.restore();
      }
      if (this.selected.has(i)) {
        g.save(); g.strokeStyle = '#ffd84a'; g.lineWidth = 2; g.beginPath(); g.arc(sx, sy, psize + 6, 0, Math.PI * 2); g.stroke(); g.restore();
      }
      if (this.layers.labels || this.selected.has(i) || i === hov) this._label(sx, sy - psize - 6, o.kind === 'marker' ? `random${o.group}` : o.resref, 1);
    });
    this._drawCamp(psize);
    // ghost (placement preview)
    if (this.ghost && this._hover && this._hover.x !== undefined) {
      for (const it of this.ghost) {
        const [sx, sy] = this.toScreen(it.x, it.y);
        this._shape(it.kind, sx, sy, psize, KIND_COLOR[it.kind], 0.55, it.facing, it.kind === 'marker' ? it.group : null);
        if (this.blocked(it)) {
          g.save(); g.strokeStyle = '#ff4d4d'; g.lineWidth = 2; g.beginPath(); g.arc(sx, sy, psize + 4, 0, Math.PI * 2); g.stroke(); g.restore();
        }
      }
    }
  }

  /** Random camp: the design area, the pivot, and the whole camp drawn (turned) at every spot. */
  _drawCamp(psize) {
    const c = this.camp, g = this.ctx;
    if (!c || !this.layers.camp) return;
    const o = c.origin, v = this.view;
    if (o && c.template.length) {
      const [px, py] = this.toScreen(o.x, o.y);
      g.save(); g.strokeStyle = KIND_COLOR.spot; g.lineWidth = 1.5; g.setLineDash([6, 4]); g.globalAlpha = 0.9;
      g.beginPath(); g.arc(px, py, Math.max(8, (c.radius + 1) * v.scale), 0, Math.PI * 2); g.stroke(); g.restore();
      this._shape('pivot', px, py, 4, KIND_COLOR.pivot, 0.9, o.facing);
      this._label(px, py - Math.max(12, (c.radius + 1) * v.scale) - 4, c.designBuilt ? 'camp (built here too)' : 'camp design: not built here', 0.9);
    }
    c.spots.forEach((sp, i) => {
      if (o) {
        for (const t of c.template) {
          const p = xformPoint(t, o, sp), [sx, sy] = this.toScreen(p.x, p.y);
          if (sx < -20 || sy < -20 || sx > this.cw + 20 || sy > this.ch + 20) continue;
          this._shape(t.kind, sx, sy, Math.max(3, psize * 0.8), KIND_COLOR[t.kind], 0.5, p.facing);
          if (!this.inBounds(p.x, p.y, 0.5)) {
            g.save(); g.strokeStyle = '#ff4d4d'; g.lineWidth = 2; g.beginPath();
            g.moveTo(sx - 5, sy - 5); g.lineTo(sx + 5, sy + 5); g.moveTo(sx + 5, sy - 5); g.lineTo(sx - 5, sy + 5); g.stroke(); g.restore();
          } else if (this.blocked({ kind: t.kind, x: p.x, y: p.y })) {
            g.save(); g.strokeStyle = '#ff4d4d'; g.lineWidth = 2; g.setLineDash([3, 2]);
            g.beginPath(); g.arc(sx, sy, psize + 3, 0, Math.PI * 2); g.stroke(); g.restore();
          }
        }
      }
      const [sx, sy] = this.toScreen(sp.x, sp.y);
      this._shape('spot', sx, sy, 5, KIND_COLOR.spot, 0.95, sp.facing, i + 1);
      if (this.blocked({ kind: 'spot', x: sp.x, y: sp.y })) {
        g.save(); g.strokeStyle = '#ff4d4d'; g.lineWidth = 2; g.setLineDash([3, 2]);
        g.beginPath(); g.arc(sx, sy, 14, 0, Math.PI * 2); g.stroke(); g.restore();
      }
      if (i === c.sel) { g.save(); g.strokeStyle = '#ffd84a'; g.lineWidth = 2; g.beginPath(); g.arc(sx, sy, 16, 0, Math.PI * 2); g.stroke(); g.restore(); }
    });
  }

  _label(sx, sy, text, alpha) {
    const g = this.ctx;
    g.save();
    g.globalAlpha = alpha;
    g.font = '11px ui-monospace, monospace'; g.textAlign = 'center'; g.textBaseline = 'bottom';
    const w = g.measureText(text).width + 6;
    g.fillStyle = 'rgba(10,14,22,.8)'; g.fillRect(sx - w / 2, sy - 13, w, 14);
    g.fillStyle = '#e8edf8'; g.fillText(text, sx, sy);
    g.restore();
  }

  destroy() { this._ro.disconnect(); }
}
