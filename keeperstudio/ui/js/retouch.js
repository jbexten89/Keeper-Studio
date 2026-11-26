// Keeper Studio UI — retouch. Plain scripts sharing one global scope, loaded in order by index.html.
'use strict';
/* ============================================================= Retouch ==== */
// Eye swap for glasses glare: the photographer's Photoshop routine, automated.
//   1 Line up — the no-glasses frame is laid over at 50%, already aligned from
//               the face; nudge it if needed.
//   2 Brush in — a hidden layer mask: paint to reveal the clear eyes.
// Saved as a copy in _retouched/ beside the photo; everything else uses it.
const Ret = {
  info: { edits: {}, donors: {} },
  work: new Map(),          // path -> unsaved session state, so stepping away keeps your brushing
  s: null,                  // the session on screen
  busy: false, showBefore: false, match: true, opacity: 50,
  view: { z: 1, px: 0, py: 0 },   // zoom (1 = eye area fits the window) and pan, in screen px
  brush: { size: 0, erase: false, soft: 50 },   // soft: 0 = hard edge, 100 = feathered all the way in
  isDonor(path) { return !!this.info.donors[path]; },
  isEdited(path) { return !!this.info.edits[path]; },
  async loadInfo() {
    if (!S.photos.length) { this.info = { edits: {}, donors: {} }; return; }
    try { this.info = await api('/api/retouch/info', { paths: S.photos.map(p => p.path) }); } catch { this.info = { edits: {}, donors: {} }; }
    EDIT_VER.clear(); for (const [k, v] of Object.entries(this.info.edits)) EDIT_VER.set(k, v.mtime);
    // thumbnails asked for before we knew: point them at the retouched copy
    for (const p of S.photos) if (p.thumbUrl && p.thumbUrl !== thumbUrl(p.path)) { p.thumbState = 0; Thumbs.request(p); }
    schedule(R_CELLS);
  },
  libraryLoaded() { this.work.clear(); this.s = null; this.loadInfo(); },
  active() { return S.byId.get(S.active) || null; },
  enter() { this.render(); this.open(); },
  render() { renderView(); renderLeft(); renderRight(); this.modbar(); },

  // the frame shot without glasses: what was used before, else the next photo, else the previous one
  defaultDonor(p) {
    const e = this.info.edits[p.path]; if (e && e.donor && S.byPath.get(e.donor)) return e.donor;
    const i = S.viewIndex.get(p.id); const n = S.view[i + 1], b = S.view[i - 1];
    return (n && n.folder === p.folder ? n : b && b.folder === p.folder ? b : n || b || null)?.path || null;
  },
  async open(p = this.active(), donor) {
    if (!p || S.module !== 'retouch') return;
    const kept = this.work.get(p.path);
    if (kept && (!donor || kept.donor === donor)) { this.s = kept; return this.render(); }
    donor = donor || this.defaultDonor(p);
    if (!donor) { this.s = { path: p.path, error: 'There’s no other photo in this folder to take the eyes from.' }; return this.render(); }
    this.s = { path: p.path, donor, loading: true }; this.render();
    let r;
    try { r = await api('/api/retouch/prepare', { path: p.path, donor }); }
    catch (e) { if (this.active() === p) { this.s = { path: p.path, donor, error: e.message }; this.render(); } return; }
    if (this.active() !== p) return;  // moved on while it loaded
    const load = w => new Promise((ok, bad) => { const im = new Image(); im.onload = () => ok(im); im.onerror = bad; im.src = `/retouch-img?id=${r.id}&w=${w}&t=${KS_TOKEN}`; });
    const [tImg, dImg] = await Promise.all([load('target'), load('donor')]);
    const [, , w, h] = r.region;
    const mask = document.createElement('canvas'); mask.width = w; mask.height = h;
    const s = { path: p.path, donor, id: r.id, found: r.found, w, h, pad: r.pad, ed: r.ed, eyes: r.eyes, lensR: r.lens_r,
      tImg, dImg, mask, undo: [], adj: this.normAdj(r.adjust), step: r.mask ? 'brush' : 'align', dirty: false };
    if (r.mask) { const im = await new Promise(ok => { const i = new Image(); i.onload = () => ok(i); i.src = r.mask; }); mask.getContext('2d').drawImage(im, 0, 0); }
    if (!this.brush.size) this.brush.size = Math.round(r.ed * 0.22);
    this.view = { z: 1, px: 0, py: 0 };
    this.work.set(p.path, s); this.s = s; this.render();
  },
  normAdj(a) {
    a = a || {}; const u = +a.s || 1;
    return { dx: +a.dx || 0, dy: +a.dy || 0, sx: (+a.sx || 1) * u, sy: (+a.sy || 1) * u, r: +a.r || 0 };
  },
  stepDonor(dir) {
    const s = this.s, p = this.active(); if (!s || !p || !s.donor) return;
    const same = S.view.filter(x => x.folder === p.folder && x.path !== p.path);
    const i = same.findIndex(x => x.path === s.donor);
    const n = same[(i + dir + same.length) % same.length]; if (!n) return;
    this.work.delete(p.path); this.open(p, n.path);
  },

  /* ---------- center ---------- */
  center() {
    const v = $('#modView');
    const p = this.active();
    if (p && (!this.s || this.s.path !== p.path)) { this.s = null; setTimeout(() => this.open(p), 0); }  // stepped to another photo
    if (v.dataset.mod !== 'retouch') {
      v.dataset.mod = 'retouch';
      v.innerHTML = `<div class="rt-stage" id="rtStage"><canvas id="rtCanvas"></canvas><div class="rt-msg" id="rtMsg"></div></div>`;
      this.bindCanvas();
    }
    this.draw();
  },
  layout() {
    const s = this.s, st = $('#rtStage'), cv = $('#rtCanvas'); if (!s || !s.tImg || !st) return null;
    const W = st.clientWidth, H = st.clientHeight, dpr = window.devicePixelRatio || 1;
    // room around the eye area for the transform handles and the rotate zone
    const fit = Math.max(0.05, Math.min((W - 160) / s.w, (H - 130) / s.h));
    const v = this.view, K = fit * v.z;
    const ox = (W - s.w * K) / 2 + v.px, oy = (H - s.h * K) / 2 + v.py;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
    return this._L = { k: K, fit, ox, oy, dpr, W, H };
  },
  // zoom about a screen point (default: the centre)
  zoomView(f, sx, sy) {
    const L = this._L || this.layout(); if (!L) return;
    const z = clamp(this.view.z * f, Math.min(1, 1 / L.fit), 24); if (Math.abs(z - this.view.z) < 1e-6) return;
    if (sx == null) { sx = L.W / 2; sy = L.H / 2; }
    const rx = (sx - L.ox) / L.k, ry = (sy - L.oy) / L.k;          // region point under the cursor stays put
    this.view.z = z;
    const K = L.fit * z;
    this.view.px = sx - rx * K - (L.W - this.s.w * K) / 2;
    this.view.py = sy - ry * K - (L.H - this.s.h * K) / 2;
    if (z <= 1) { this.view.px = this.view.py = 0; }
    this.draw(); this.modbar();
  },
  fitView() { this.view = { z: 1, px: 0, py: 0 }; this.draw(); this.modbar(); },
  actualPixels() { const L = this._L || this.layout(); if (L) this.zoomView(1 / L.fit / this.view.z); },
  drawDonor(ctx, s) {
    const a = s.adj, cx = s.w / 2, cy = s.h / 2;
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, s.w, s.h); ctx.clip();  // keep the overlay inside the eye area
    ctx.translate(cx + a.dx, cy + a.dy); ctx.rotate(a.r * Math.PI / 180); ctx.scale(a.sx, a.sy); ctx.translate(-cx, -cy);
    ctx.drawImage(s.dImg, -s.pad, -s.pad); ctx.restore();
  },
  // the overlay's box: centre, its own axes, half sizes, and the 8 handles
  box() {
    const s = this.s, a = s.adj, r = a.r * Math.PI / 180;
    const c = { x: s.w / 2 + a.dx, y: s.h / 2 + a.dy }, ux = { x: Math.cos(r), y: Math.sin(r) }, uy = { x: -Math.sin(r), y: Math.cos(r) };
    const hw = s.w / 2 * a.sx, hh = s.h / 2 * a.sy;
    const at = (i, j) => ({ x: c.x + ux.x * hw * i + uy.x * hh * j, y: c.y + ux.y * hw * i + uy.y * hh * j });
    const handles = [[-1, -1, 'c'], [1, -1, 'c'], [1, 1, 'c'], [-1, 1, 'c'], [0, -1, 'y'], [1, 0, 'x'], [0, 1, 'y'], [-1, 0, 'x']].map(([i, j, k]) => ({ i, j, k, ...at(i, j) }));
    return { c, ux, uy, hw, hh, handles, corners: [at(-1, -1), at(1, -1), at(1, 1), at(-1, 1)] };
  },
  // what the pointer would grab: a handle, the rotate zone just outside a corner, the inside (move), or nothing
  hit(pt) {
    const L = this._L, b = this.box(), tol = 9 / L.k;
    for (const h of b.handles) if (Math.hypot(pt.x - h.x, pt.y - h.y) <= tol) return { kind: h.k === 'c' ? 'scale' : h.k === 'x' ? 'sx' : 'sy', h };
    const lx = (pt.x - b.c.x) * b.ux.x + (pt.y - b.c.y) * b.ux.y, ly = (pt.x - b.c.x) * b.uy.x + (pt.y - b.c.y) * b.uy.y;
    if (Math.abs(lx) <= b.hw && Math.abs(ly) <= b.hh) return { kind: 'move' };
    for (const q of b.corners) if (Math.hypot(pt.x - q.x, pt.y - q.y) <= 34 / L.k) return { kind: 'rotate' };
    return { kind: 'move' };
  },
  cursorFor(kind, h) {
    if (kind === 'rotate') return 'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%2724%27 height=%2724%27%3E%3Cpath d=%27M5 12a7 7 0 1 1 7 7%27 fill=%27none%27 stroke=%27white%27 stroke-width=%273.5%27/%3E%3Cpath d=%27M5 12a7 7 0 1 1 7 7%27 fill=%27none%27 stroke=%27black%27 stroke-width=%271.5%27/%3E%3Cpath d=%27M2 9l3 4 3-4%27 fill=%27black%27 stroke=%27white%27/%3E%3C/svg%3E") 12 12, crosshair';
    if (kind === 'move') return 'move';
    if (!h) return 'default';
    const ang = (Math.atan2(h.y - this.box().c.y, h.x - this.box().c.x) * 180 / Math.PI + 360) % 180;
    return ang < 22.5 || ang >= 157.5 ? 'ew-resize' : ang < 67.5 ? 'nwse-resize' : ang < 112.5 ? 'ns-resize' : 'nesw-resize';
  },
  draw() {
    const s = this.s, cv = $('#rtCanvas'), msg = $('#rtMsg'); if (!cv) return;
    const p = this.active();
    msg.textContent = !p ? 'Select a photo with glasses glare in the filmstrip.' : !s || s.loading ? 'Lining up the no-glasses frame…' : s.error || '';
    msg.hidden = !msg.textContent; cv.hidden = !(s && s.tImg);
    if (!s || !s.tImg) return;
    const L = this.layout(); if (!L) return;
    cv.style.cursor = this.panning || this.space ? (this.panning ? 'grabbing' : 'grab') : this.showBefore ? 'default' : s.step === 'brush' ? 'none' : this.alignCursor || 'move';
    const ctx = cv.getContext('2d');
    ctx.setTransform(L.dpr, 0, 0, L.dpr, 0, 0); ctx.clearRect(0, 0, L.W, L.H);
    ctx.setTransform(L.k * L.dpr, 0, 0, L.k * L.dpr, L.ox * L.dpr, L.oy * L.dpr);
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(s.tImg, 0, 0);
    if (this.showBefore) return;
    if (s.step === 'align') {
      ctx.globalAlpha = this.opacity / 100; this.drawDonor(ctx, s); ctx.globalAlpha = 1;
      const b = this.box(), px = 1 / L.k;
      ctx.lineWidth = 1.2 * px; ctx.strokeStyle = '#2E9BFF'; ctx.setLineDash([6 * px, 4 * px]);
      ctx.beginPath(); b.corners.forEach((q, i) => i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y)); ctx.closePath(); ctx.stroke(); ctx.setLineDash([]);
      for (const h of b.handles) { const r = 4.5 * px; ctx.fillStyle = '#fff'; ctx.strokeStyle = '#2E9BFF'; ctx.lineWidth = 1.5 * px; ctx.beginPath(); ctx.rect(h.x - r, h.y - r, 2 * r, 2 * r); ctx.fill(); ctx.stroke(); }
      ctx.fillStyle = '#2E9BFF'; ctx.beginPath(); ctx.arc(b.c.x, b.c.y, 2.5 * px, 0, Math.PI * 2); ctx.fill();
      return;
    }
    // brush: the clear eyes, through the mask
    const c = this._comp || (this._comp = document.createElement('canvas'));
    c.width = s.w; c.height = s.h; const cx = c.getContext('2d');
    this.drawDonor(cx, s); cx.globalCompositeOperation = 'destination-in'; cx.drawImage(s.mask, 0, 0); cx.globalCompositeOperation = 'source-over';
    ctx.drawImage(c, 0, 0);
    if (this.cursor && !this.space && !this.panning) {
      ctx.beginPath(); ctx.arc(this.cursor.x, this.cursor.y, this.brush.size / 2, 0, Math.PI * 2);
      ctx.lineWidth = 1.5 / L.k; ctx.strokeStyle = this.brush.erase ? '#E3A04F' : '#fff'; ctx.stroke();
      ctx.lineWidth = 1 / L.k; ctx.strokeStyle = 'rgba(0,0,0,.6)'; ctx.beginPath(); ctx.arc(this.cursor.x, this.cursor.y, this.brush.size / 2 + 1.5 / L.k, 0, Math.PI * 2); ctx.stroke();
      const core = (1 - this.brush.soft / 100) * this.brush.size / 2;  // where full strength ends
      if (core > 2 / L.k && this.brush.soft > 2) { ctx.setLineDash([4 / L.k, 4 / L.k]); ctx.lineWidth = 1 / L.k; ctx.strokeStyle = 'rgba(255,255,255,.55)'; ctx.beginPath(); ctx.arc(this.cursor.x, this.cursor.y, core, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]); }
    }
  },
  toRegion(e) { const cv = $('#rtCanvas'), r = cv.getBoundingClientRect(), L = this._L; return { x: (e.clientX - r.left - L.ox) / L.k, y: (e.clientY - r.top - L.oy) / L.k }; },
  stamp(x, y) {
    const s = this.s, m = s.mask.getContext('2d'), rad = this.brush.size / 2;
    // full strength out to the hard core, then a smooth fall-off to the edge
    const core = clamp(1 - this.brush.soft / 100, 0, 0.98);
    const g = m.createRadialGradient(x, y, 0, x, y, rad);
    g.addColorStop(0, 'rgba(255,255,255,0.95)'); g.addColorStop(core, 'rgba(255,255,255,0.95)');
    const n = 6; for (let i = 1; i <= n; i++) { const t = i / n, f = 1 - t * t * (3 - 2 * t); g.addColorStop(core + (1 - core) * t, `rgba(255,255,255,${(0.95 * f).toFixed(3)})`); }
    m.globalCompositeOperation = this.brush.erase ? 'destination-out' : 'source-over';
    m.fillStyle = g; m.beginPath(); m.arc(x, y, rad, 0, Math.PI * 2); m.fill(); m.globalCompositeOperation = 'source-over';
  },
  pushUndo() { const s = this.s; s.undo.push(s.mask.getContext('2d').getImageData(0, 0, s.w, s.h)); if (s.undo.length > 25) s.undo.shift(); },
  undoMask() { const s = this.s; if (!s || !s.undo.length) return toast('Nothing to undo'); s.mask.getContext('2d').putImageData(s.undo.pop(), 0, 0); s.dirty = true; this.draw(); },
  bindCanvas() {
    const cv = $('#rtCanvas'); let last = null, drag = null;
    let pan = null;
    cv.addEventListener('contextmenu', e => e.preventDefault());
    cv.addEventListener('pointerdown', e => {
      const s = this.s; if (!s || !s.tImg) return; e.preventDefault(); cv.setPointerCapture(e.pointerId);
      if (this.space || e.button === 1 || e.button === 2) { pan = { x: e.clientX, y: e.clientY, px: this.view.px, py: this.view.py }; this.panning = true; this.draw(); return; }
      const pt = this.toRegion(e);
      if (s.step === 'align') { const h = this.hit(pt); drag = { ...h, x: pt.x, y: pt.y, a0: { ...s.adj }, b0: this.box() }; return; }
      this.pushUndo(); this.stamp(pt.x, pt.y); last = pt; s.dirty = true; this.draw();
    });
    cv.addEventListener('pointermove', e => {
      const s = this.s; if (!s || !s.tImg) return;
      if (pan) { this.view.px = pan.px + e.clientX - pan.x; this.view.py = pan.py + e.clientY - pan.y; this.draw(); return; }
      const pt = this.toRegion(e);
      if (s.step === 'align') {
        if (!drag) { const h = this.hit(pt); const c = this.cursorFor(h.kind, h.h); if (c !== this.alignCursor) { this.alignCursor = c; $('#rtCanvas').style.cursor = c; } return; }
        const a = s.adj, a0 = drag.a0, b0 = drag.b0, c = b0.c;
        const loc = q => ({ x: (q.x - c.x) * b0.ux.x + (q.y - c.y) * b0.ux.y, y: (q.x - c.x) * b0.uy.x + (q.y - c.y) * b0.uy.y });
        if (drag.kind === 'move') { a.dx = a0.dx + pt.x - drag.x; a.dy = a0.dy + pt.y - drag.y; }
        else if (drag.kind === 'rotate') {
          const d = (Math.atan2(pt.y - c.y, pt.x - c.x) - Math.atan2(drag.y - c.y, drag.x - c.x)) * 180 / Math.PI;
          a.r = Math.round((a0.r + (e.shiftKey ? Math.round(d / 15) * 15 : d)) * 100) / 100;
        } else if (drag.kind === 'scale') {   // corner: keep the proportions (Shift = free)
          const p0 = loc({ x: drag.x, y: drag.y }), p1 = loc(pt);
          if (e.shiftKey) { a.sx = clamp(a0.sx * p1.x / (p0.x || 1e-6), 0.3, 3); a.sy = clamp(a0.sy * p1.y / (p0.y || 1e-6), 0.3, 3); }
          else { const f = Math.hypot(p1.x, p1.y) / (Math.hypot(p0.x, p0.y) || 1e-6); a.sx = clamp(a0.sx * f, 0.3, 3); a.sy = clamp(a0.sy * f, 0.3, 3); }
        } else if (drag.kind === 'sx') { const p0 = loc({ x: drag.x, y: drag.y }), p1 = loc(pt); a.sx = clamp(a0.sx * p1.x / (p0.x || 1e-6), 0.3, 3); }
        else if (drag.kind === 'sy') { const p0 = loc({ x: drag.x, y: drag.y }), p1 = loc(pt); a.sy = clamp(a0.sy * p1.y / (p0.y || 1e-6), 0.3, 3); }
        s.dirty = true; this.draw(); this.showAdj(); return;
      }
      this.cursor = pt;
      if (last) {  // stamps along the stroke, close enough to look continuous
        const d = Math.hypot(pt.x - last.x, pt.y - last.y), step = Math.max(1, this.brush.size * 0.12);
        for (let t = step; t <= d; t += step) this.stamp(last.x + (pt.x - last.x) * t / d, last.y + (pt.y - last.y) * t / d);
        if (d >= step) last = pt;
      }
      this.draw();
    });
    const end = () => { last = null; drag = null; if (pan) { pan = null; this.panning = false; this.draw(); } };
    cv.addEventListener('pointerup', end); cv.addEventListener('pointercancel', end);
    cv.addEventListener('pointerleave', () => { this.cursor = null; this.draw(); });
    cv.addEventListener('wheel', e => {
      if (!this.s || !this.s.tImg) return; e.preventDefault();
      const r = cv.getBoundingClientRect();
      this.zoomView(Math.pow(1.0015, -e.deltaY), e.clientX - r.left, e.clientY - r.top);
      this.cursor = this.toRegion(e); this.draw();
    }, { passive: false });
    // Space held = hand tool
    window.addEventListener('keyup', e => { if (e.key === ' ' && this.space) { this.space = false; this.draw(); } });
  },
  setSoft(v) { this.brush.soft = clamp(Math.round(v), 0, 100); this.draw(); const r = $('[data-rt-soft]'); if (r) r.value = this.brush.soft; const b = $('#rtSoftVal'); if (b) b.textContent = this.brush.soft + '%'; },
  setSize(v) { this.brush.size = clamp(Math.round(v), 4, 600); this.draw(); const r = $('[data-rt-size]'); if (r) r.value = this.brush.size; const b = $('#rtSizeVal'); if (b) b.textContent = this.brush.size + ' px'; },
  autoMask() {
    const s = this.s; if (!s || !s.tImg) return; this.pushUndo();
    const m = s.mask.getContext('2d'); const [rx, ry] = s.lensR;
    m.save(); m.filter = `blur(${Math.max(1, s.ed * 0.04)}px)`; m.fillStyle = '#fff';
    for (const [x, y] of s.eyes) { m.beginPath(); m.ellipse(x, y, rx * 0.9, ry * 0.9, 0, 0, Math.PI * 2); m.fill(); }
    m.restore(); s.step = 'brush'; s.dirty = true; this.render();
  },
  clearMask() { const s = this.s; if (!s || !s.tImg) return; this.pushUndo(); s.mask.getContext('2d').clearRect(0, 0, s.w, s.h); s.dirty = true; this.draw(); },
  nudge(dx, dy, big) { const s = this.s; if (!s) return; const f = big ? 10 : 1; s.adj.dx += dx * f; s.adj.dy += dy * f; s.dirty = true; this.draw(); this.showAdj(); },
  zoom(dir, big) { const s = this.s; if (!s) return; const f = 1 + dir * (big ? 0.02 : 0.004); s.adj.sx = clamp(s.adj.sx * f, 0.3, 3); s.adj.sy = clamp(s.adj.sy * f, 0.3, 3); s.dirty = true; this.draw(); this.showAdj(); },
  stretch(axis, dir, big) { const s = this.s; if (!s) return; const f = 1 + dir * (big ? 0.02 : 0.004); s.adj[axis] = clamp(s.adj[axis] * f, 0.3, 3); s.dirty = true; this.draw(); this.showAdj(); },
  setAdj(k, v) { const s = this.s; if (!s || !isFinite(v)) return; if (k === 'sx' || k === 'sy') v = clamp(v / 100, 0.3, 3); s.adj[k] = v; s.dirty = true; this.draw(); },
  // update the numbers in the panel without rebuilding it (keeps typing focus)
  showAdj() {
    const a = this.s && this.s.adj; if (!a) return;
    const set = (k, v) => { const i = $(`[data-rt-adj="${k}"]`); if (i && document.activeElement !== i) i.value = v; };
    set('sx', (a.sx * 100).toFixed(1)); set('sy', (a.sy * 100).toFixed(1)); set('r', a.r.toFixed(2));
    const m = $('#rtMoved'); if (m) m.textContent = `${Math.round(a.dx)}, ${Math.round(a.dy)} px`;
  },
  turn(dir, big) { const s = this.s; if (!s) return; s.adj.r = Math.round((s.adj.r + dir * (big ? 1 : 0.25)) * 100) / 100; s.dirty = true; this.draw(); this.showAdj(); },
  resetAlign() { const s = this.s; if (!s) return; s.adj = { dx: 0, dy: 0, sx: 1, sy: 1, r: 0 }; s.dirty = true; this.draw(); this.showAdj(); },
  setStep(st) { const s = this.s; if (!s || !s.tImg) return; s.step = st; this.render(); },
  async save() {
    const s = this.s, p = this.active(); if (!s || !s.tImg || this.busy || !p) return;
    if (s.step === 'align') return this.setStep('brush');
    // anything painted at all?
    const d = s.mask.getContext('2d').getImageData(0, 0, s.w, s.h).data; let any = false;
    for (let i = 3; i < d.length; i += 16) if (d[i] > 8) { any = true; break; }
    if (!any) return toast('Brush the eyes in first (or press M to paint them for you)');
    this.busy = true; this.right();
    try {
      await api('/api/retouch/save', { path: p.path, id: s.id, adjust: s.adj, mask: s.mask.toDataURL('image/png'), match: this.match });
      s.dirty = false;
      await this.loadInfo();
      Crop.plans.delete(p.path); Crop.status.delete(p.path);
      p.thumbState = 0; Thumbs.request(p);
      toast(`Retouched — ${esc(p.name)} now uses the clear eyes everywhere`, 3500);
    } catch (e) { toast('Couldn’t save: ' + esc(e.message), 6000); }
    this.busy = false; renderAll();
  },
  showFile() { const e = this.info.edits[(this.active() || {}).path]; if (e) reveal(e.file); },
  async saveCopy() {
    const p = this.active(), e = p && this.info.edits[p.path]; if (!e) return;
    const stem = p.name.replace(/\.[^.]+$/, '');
    const dest = await pickPath('save', { initial: S.root || '', filename: `${stem}_retouched.jpg` }); if (!dest) return;
    try { const r = await api('/api/retouch/copy', { path: p.path, dest }); toast(`Saved ${esc(baseName(r.saved))} <button class="toast-link" onclick="reveal(${esc(JSON.stringify(r.saved))})">Show</button>`, 5000); }
    catch (err) { toast('Couldn’t save the copy: ' + esc(err.message), 6000); }
  },
  async remove() {
    const p = this.active(); if (!p || !this.isEdited(p.path)) return;
    try { await api('/api/retouch/remove', { path: p.path }); } catch (e) { return toast(esc(e.message)); }
    this.work.delete(p.path); await this.loadInfo(); Crop.plans.delete(p.path); Crop.status.delete(p.path);
    p.thumbState = 0; Thumbs.request(p); toast('Retouch removed — back to the original photo'); this.open(p);
    renderAll();
  },

  /* ---------- panels ---------- */
  left() {
    const L = $('#left');
    const mine = S.photos.filter(p => this.isEdited(p.path)), donors = S.photos.filter(p => this.isDonor(p.path));
    const row = (p, tag) => `<div class="row rt-row" data-rt-go="${p.id}"><span class="style-tag inline">${tag}</span><span class="lbl">${esc(p.name)}</span></div>`;
    let html = sectionHTML('rt-how', 'Eye swap', `<div class="pad hint tight">For glasses glare: take the eyes from the frame shot without glasses.<br>
      <b>1 Line up</b> — it’s already lined up from the face; drag or use the arrow keys if it’s off.<br>
      <b>2 Brush in</b> — paint over the lenses to reveal the clear eyes.<br>
      <b>Enter</b> saves a retouched copy (the camera file is never changed). Crop, Composite and Extract use it automatically.</div>`);
    html += sectionHTML('rt-done', `Retouched in this folder (${mine.length})`, mine.length ? `<div class="style-rows">${mine.map(p => row(p, 'Fixed')).join('')}</div>` : '<div class="hint">None yet.</div>');
    html += sectionHTML('rt-don', `Eye donors (${donors.length})`, donors.length ? `<div class="hint tight">Frames the eyes came from. They’re left out of prints, composites and extracts.</div><div class="style-rows">${donors.map(p => row(p, 'Donor')).join('')}</div>` : '<div class="hint">None yet.</div>');
    L.innerHTML = `<div class="scroll">${html}</div>`;
  },
  right() {
    const R = $('#right'), p = this.active(), s = this.s;
    if (!p) { R.innerHTML = '<div class="scroll"><div class="hint">Select a photo with glasses glare.</div></div>'; return; }
    const edited = this.isEdited(p.path);
    const dn = s && s.donor ? S.byPath.get(s.donor) : null;
    let html = sectionHTML('rt-status', 'This photo', `<div class="status-card ${edited ? 'ok' : 'none'}"><div class="sc-head"><span class="st-dot ${edited ? 'ok' : 'none'}"></span><b>${edited ? 'Retouched' : this.isDonor(p.path) ? 'Eye donor' : 'Not retouched'}</b></div>
      <div class="sc-label">${edited ? 'Previews and exports use the retouched copy.' : this.isDonor(p.path) ? 'Its eyes were used for another photo; it’s left out of prints.' : 'Line up and brush in the clear eyes, then press Enter.'}</div>
      ${edited ? '<div class="btn-row"><button class="btn sm" data-rt="show" title="Open its folder in File Explorer">Show file</button><button class="btn sm" data-rt="copy" title="Save a copy of the retouched JPG somewhere else">Save a copy as…</button><button class="btn sm" data-rt="remove">Remove retouch</button></div>' : ''}</div>`);
    html += sectionHTML('rt-donor', 'Frame without glasses', dn ? `<div class="rt-donor"><img src="${thumbUrl(dn.path)}" alt=""><div><b>${esc(dn.name)}</b><div class="btn-row"><button class="btn sm" data-rt="donor-prev" title="Use the previous photo">◀</button><button class="btn sm" data-rt="donor-next" title="Use the next photo">▶</button></div></div></div>
      ${s && s.tImg && !s.found ? '<div class="miss-note">The face wasn’t found in one of the frames, so line them up by hand: drag the overlay, arrow keys to nudge, + − to resize, , . to turn.</div>' : ''}` : '<div class="hint">—</div>');
    if (s && s.tImg) {
      const a = s.adj;
      html += sectionHTML('rt-steps', 'Steps', `<div class="pad">${segHTML('rtStep', s.step, [['align', '1 Line up'], ['brush', '2 Brush in']])}</div>
        ${s.step === 'align' ? `<div class="hint tight">Line the eyes up like Free Transform: drag inside to <b>move</b>, a <b>corner</b> to resize (Shift: free), a <b>side</b> handle to stretch width or height, just <b>outside a corner</b> to rotate (Shift: 15° steps).</div>
          <div class="rt-adj"><label>Width<input type="number" step="0.1" data-rt-adj="sx" value="${(a.sx * 100).toFixed(1)}"><i>%</i></label><label>Height<input type="number" step="0.1" data-rt-adj="sy" value="${(a.sy * 100).toFixed(1)}"><i>%</i></label><label>Angle<input type="number" step="0.05" data-rt-adj="r" value="${a.r.toFixed(2)}"><i>°</i></label></div>
          <div class="hint tight">Moved <span id="rtMoved">${Math.round(a.dx)}, ${Math.round(a.dy)} px</span> · keys: arrows move · <kbd>Alt</kbd>+arrows stretch · <kbd>+</kbd> <kbd>−</kbd> size · <kbd>,</kbd> <kbd>.</kbd> rotate · Shift = bigger steps</div>
          <div class="slider-row" title="How see-through the no-glasses frame is while lining up"><span>Overlay</span><input type="range" min="15" max="85" value="${this.opacity}" data-rt-op><b id="rtOpVal">${this.opacity}%</b></div>
          <div class="btn-row pad-x"><button class="btn sm" data-rt="reset">Reset alignment</button><button class="btn sm primary" data-rt="to-brush">Looks good <kbd>Enter</kbd></button></div>`
        : `<div class="slider-row"><span>Brush</span><input type="range" min="4" max="${Math.max(60, Math.round(s.ed))}" value="${this.brush.size}" data-rt-size><b id="rtSizeVal">${this.brush.size} px</b></div>
          <div class="slider-row" title="How gradually the brush fades at its edge. Shift+[ softer, Shift+] harder"><span>Softness</span><input type="range" min="0" max="100" value="${this.brush.soft}" data-rt-soft><b id="rtSoftVal">${this.brush.soft}%</b></div>
          <div class="pad">${segHTML('rtMode', this.brush.erase ? 'erase' : 'reveal', [['reveal', 'Reveal'], ['erase', 'Erase <kbd>X</kbd>']])}</div>
          <div class="btn-row pad-x"><button class="btn sm" data-rt="auto">Paint eyes for me <kbd>M</kbd></button><button class="btn sm" data-rt="clear">Clear</button><button class="btn sm" data-rt="undo">Undo</button></div>
          <div class="hint tight"><kbd>[</kbd> <kbd>]</kbd> brush size · <kbd>Shift</kbd>+<kbd>[</kbd> <kbd>]</kbd> softness · mouse wheel or <kbd>+</kbd> <kbd>−</kbd> zoom · hold <kbd>Space</kbd> and drag to move around · <kbd>0</kbd> fit · <kbd>\\</kbd> before/after</div>`}`);
      html += sectionHTML('rt-opts', 'Options', `${switchHTML('rtMatch', this.match, 'Match brightness and colour', 'Evens out small exposure and colour differences between the two frames')}`);
      html += `<div class="pad"><button class="btn primary wide" data-rt="save" ${this.busy ? 'disabled' : ''}>${this.busy ? 'Saving…' : s.step === 'align' ? 'Next: brush in  ⏎' : (edited ? 'Save changes  ⏎' : 'Save retouch  ⏎')}</button></div>`;
    }
    R.innerHTML = `<div class="scroll">${html}</div>`;
  },
  modbar() {
    const s = this.s, mb = $('#modbar'); if (!mb || S.module !== 'retouch') return;
    const zpct = this._L ? Math.round(this._L.k * 100) : 100;
    mb.innerHTML = `<button class="toggle ${this.showBefore ? 'on' : ''}" data-rt="before" title="Before / after (\\)">Before / after <kbd>\\</kbd></button>
      <span class="rt-zoom"><button class="btn sm" data-rt="zoom-out" title="Zoom out">−</button><b>${zpct}%</b><button class="btn sm" data-rt="zoom-in" title="Zoom in (mouse wheel)">+</button><button class="btn sm" data-rt="fit" title="Fit (0)">Fit</button><button class="btn sm" data-rt="px" title="Actual pixels (1)">1:1</button></span>
      <span class="hint-keys">${!s || !s.tImg ? '' : s.step === 'align' ? 'drag inside to move · corners resize · sides stretch · outside a corner rotates · Alt+arrows stretch · wheel zoom · Enter next' : 'wheel or + − zoom · Space-drag pan · [ ] brush · Shift+[ ] softness · X erase · M paint eyes · Ctrl+Z undo · Enter save'}</span>`;
  },
  key(e, k) {
    const s = this.s, ready = s && s.tImg;
    if (e.ctrlKey || e.metaKey) { if (k === 'z' && ready) { this.undoMask(); return true; } return false; }
    if (e.key === '\\') { this.showBefore = !this.showBefore; this.draw(); this.modbar(); return true; }
    if (!ready) return false;
    if (e.key === ' ') { if (!this.space) { this.space = true; this.draw(); } return true; }
    if (e.key === '0') { this.fitView(); return true; }
    if (e.key === '1') { this.actualPixels(); return true; }
    if (e.key === 'Enter') { this.save(); return true; }
    if (s.step === 'align') {
      const mv = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      if (mv && e.altKey) { if (mv[0]) this.stretch('sx', mv[0], e.shiftKey); else this.stretch('sy', -mv[1], e.shiftKey); return true; }  // Alt+← → narrower/wider, Alt+↑ ↓ taller/shorter
      if (mv) { this.nudge(mv[0], mv[1], e.shiftKey); return true; }
      if (e.key === '+' || e.key === '=') { this.zoom(1, e.shiftKey); return true; }
      if (e.key === '-' || e.key === '_') { this.zoom(-1, e.shiftKey); return true; }
      if (e.key === ',' || e.key === '<') { this.turn(-1, e.shiftKey); return true; }
      if (e.key === '.' || e.key === '>') { this.turn(1, e.shiftKey); return true; }
      if (k === 'm') { this.autoMask(); return true; }
      return false;
    }
    if (e.key === '+' || e.key === '=') { this.zoomView(1.25); return true; }
    if (e.key === '-' || e.key === '_') { this.zoomView(0.8); return true; }
    if (e.key === '{' || (e.key === '[' && e.shiftKey)) { this.setSoft(this.brush.soft + 10); return true; }
    if (e.key === '}' || (e.key === ']' && e.shiftKey)) { this.setSoft(this.brush.soft - 10); return true; }
    if (e.key === '[') { this.setSize(this.brush.size / 1.15); return true; }
    if (e.key === ']') { this.setSize(this.brush.size * 1.15); return true; }
    if (k === 'x') { this.brush.erase = !this.brush.erase; this.right(); this.draw(); return true; }
    if (k === 'm') { this.autoMask(); return true; }
    if (k === 'a') { this.setStep('align'); return true; }
    return false;
  },
};
function retouchTag(p) {
  return Ret.isEdited(p.path) ? '<span class="rt-tag" title="Retouched (eye swap)">Fixed</span>' : Ret.isDonor(p.path) ? '<span class="rt-tag donor" title="Eye donor — left out of prints">Donor</span>' : '';
}

