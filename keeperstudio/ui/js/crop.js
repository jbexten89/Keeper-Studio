// Keeper Studio UI — crop. Plain scripts sharing one global scope, loaded in order by index.html.
'use strict';
/* ================================================================ Crop ==== */
const STYLE_TAGS = { full: 'Full', knee_above: '¾↑', knee_below: '¾↓', preschool: 'Pre' };
function styleTag(p) { const v = Crop.styleOf(p.path); return v ? `<span class="style-tag" title="Own framing style: ${esc(Crop.STYLE_NAMES[v])}">${STYLE_TAGS[v]}</span>` : ''; }
const Crop = {
  settings: null, sizes: [], warnings: [], ordersName: 'Orders', configPath: '',
  plans: new Map(), inflight: new Map(), status: new Map(), manual: new Map(),
  outDir: '', outCustom: false, scope: 'all', job: null, jobState: null, result: null,
  adjusting: null, hover: null, focus: null, circle: false, compare: false, styles: new Map(), overlay: true, planError: null, rotations: new Map(), live: null,
  async load() {
    try {
      const r = await api('/api/crop/settings', {});
      Object.assign(this, { settings: r.settings, sizes: r.sizes, warnings: r.warnings || [], ordersName: r.orders_name, configPath: r.config_path });
    } catch (e) { this.planError = e.message; }
    try { for (const [k, v] of await DB.entries('manual')) this.manual.set(k, v); } catch {}
    try { for (const [k, v] of await DB.entries('styles')) this.styles.set(k, v); } catch {}
    try { for (const [k, v] of await DB.entries('cropstatus')) this.status.set(k, v); } catch {}
    try { for (const [k, v] of Object.entries((await api('/api/crop/rotations', {})).rotations)) this.rotations.set(k, v); } catch {}
    try { this.circle = !!(await DB.get('kv', 'cropCircle')); } catch {}
    try { this.compare = !!(await DB.get('kv', 'cropCompare')); } catch {}
  },
  CIRCLE_IN: 3,
  squareInches(name) { const m = /^(\d+(?:_\d+)?)x\1$/.exec(name); return m ? parseFloat(m[1].replace('_', '.')) : null; },
  circleFor(b) {  // [cx, cy, r] in photo pixels, or null
    const inch = this.squareInches(b.name); if (!this.circle || !inch || inch <= this.CIRCLE_IN) return null;
    const [x, y, w, h] = b.box; return [x + w / 2, y + h / 2, w * (this.CIRCLE_IN / inch) / 2];
  },
  toggleCircle(name) {
    this.circle = !this.circle; DB.put('kv', 'cropCircle', this.circle).catch(() => {});
    if (this.focus === name) this.focus = null;
    this.center(); renderRight();
  },
  STYLE_NAMES: { full: 'Full length', knee_above: '3/4 · above knees', knee_below: '3/4 · below knees', preschool: 'Preschool' },
  batchStyle() { const s = this.settings || {}; return s.preschool ? 'preschool' : ['knee_above', 'knee_below'].includes(s.framing_style) ? s.framing_style : 'full'; },
  styleOf(path) { return this.styles.get(path) || null; },
  async setStyle(v) {
    // applies to every selected photo (or just this one)
    const ids = S.selected.size ? [...S.selected] : [S.active];
    const ps = ids.map(id => S.byId.get(id)).filter(Boolean);
    for (const p of ps) {
      if (v) { this.styles.set(p.path, v); } else this.styles.delete(p.path);
      this.plans.delete(p.path); const st = this.status.get(p.path); if (st && st.src === 'check') this.status.delete(p.path);
    }
    try { if (v) await DB.putMany('styles', ps.map(p => [p.path, v])); else await Promise.all(ps.map(p => DB.del('styles', p.path))); } catch (e) { toast(esc(e.message)); }
    toast(`${plural(ps.length, 'photo')}: ${v ? this.STYLE_NAMES[v] : 'batch style'}`);
    renderAll(); this.ensurePlan();
  },
  styleRows() {
    const cnt = { batch: 0, full: 0, knee_above: 0, knee_below: 0, preschool: 0 };
    for (const p of S.photos) cnt[this.styleOf(p.path) || 'batch']++;
    const cur = S.filter.cstyle || 'any';
    const row = (k, label, tag) => cnt[k] ? `<div class="row ${cur === k ? 'on' : ''}" data-stylefilter="${k}" title="Show only these photos">${tag ? `<span class="style-tag inline">${tag}</span>` : '<span class="style-tag inline none">—</span>'}<span class="lbl">${label}</span><span class="cnt">${cnt[k]}</span></div>` : '';
    return `<div class="style-rows">${row('batch', 'Same as left side')}${row('full', 'Full length', 'Full')}${row('knee_above', '3/4 · above knees', '¾↑')}${row('knee_below', '3/4 · below knees', '¾↓')}${row('preschool', 'Preschool', 'Pre')}</div>`;
  },
  async clearStyles() {
    // only this folder's photos: other folders keep their own styles
    const mine = S.photos.map(p => p.path).filter(k => this.styles.has(k)); const n = mine.length; if (!n) return;
    for (const k of mine) { this.plans.delete(k); this.styles.delete(k); DB.del('styles', k).catch(() => {}); } S.filter.cstyle = 'any'; afterFilter(); toast(`${plural(n, 'photo')} back on the batch style`); renderAll(); this.ensurePlan();
  },
  toggleCompare() {
    this.compare = !this.compare; DB.put('kv', 'cropCompare', this.compare).catch(() => {});
    this.render(); this.modbar();
  },
  // fixed colours per size, so adding a size never repaints the others
  color(name) {
    if (name === 'needed') return '#E5484D';
    if (SIZE_COLOR_BY_NAME[name]) return SIZE_COLOR_BY_NAME[name];
    const i = this.sizes.findIndex(s => s.name === name); return SIZE_COLORS[(i < 0 ? 0 : i) % SIZE_COLORS.length];
  },
  async libraryLoaded() {
    this.result = null; this.plans.clear();
    const saved = S.root ? await DB.get('kv', 'cropout|' + S.root).catch(() => null) : null;
    this.outCustom = !!saved; this.outDir = saved || (S.root ? `${S.root}_out` : '');
    if (S.module === 'crop') this.loadKnown();
  },
  enter() { this.render(); this.loadKnown(); },
  // every framing check already saved for this folder, fetched in one go, so
  // stepping through photos that were checked before never waits
  async loadKnown() {
    const paths = S.photos.map(p => p.path).filter(p => !this.plans.has(p));
    if (paths.length) {
      const manual = {}; for (const p of paths) { const m = this.manual.get(p); if (m) manual[p] = m; }
      try {
        const r = await api('/api/crop/known', { paths, manual });
        for (const [path, plan] of Object.entries(r.plans || {})) {
          if (this.plans.has(path)) continue;
          this.plans.set(path, plan);
          this.status.set(path, { status: plan.status, label: plan.label, reason: plan.reason, src: 'check' });
        }
      } catch {}
    }
    if (S.module === 'crop') { renderView(); renderRight(); renderLeft(); schedule(R_CELLS); this.ensurePlan(); }
  },
  async saveSettings(patch) {
    Object.assign(this.settings, patch);
    try { await api('/api/crop/settings', { settings: this.settings }); } catch (e) { toast(esc(e.message)); }
    this.plans.clear();
    for (const [k, v] of [...this.status]) if (v.src === 'check') this.status.delete(k);
    renderAll(); this.loadKnown();
  },
  active() { return S.byId.get(S.active) || null; },
  seq: 0,
  ensurePlan(p = this.active(), prefetch = false) {
    if (!p || S.module !== 'crop') return;
    if (this.plans.has(p.path) || this.inflight.has(p.path)) return;
    const manual = this.manual.get(p.path) || null;
    const focus = !prefetch && p === this.active();
    const pr = api('/api/crop/plan', { path: p.path, manual, seq: ++this.seq, focus }).then(plan => {
      if (plan.stale) return;  // skipped: you had already moved on
      this.plans.set(p.path, plan);
      this.status.set(p.path, { status: plan.status, label: plan.label, reason: plan.reason, src: 'check' });
      DB.put('cropstatus', p.path, this.status.get(p.path)).catch(() => {});
    }).catch(e => { this.plans.set(p.path, { error: e.message }); })
      .finally(() => {
        this.inflight.delete(p.path);
        if (S.module !== 'crop') return;
        if (!this.plans.has(p.path) && this.active() === p) return this.ensurePlan(p);  // was skipped but is back on screen
        renderView(); renderRight(); renderLeft(); schedule(R_CELLS);
      });
    this.inflight.set(p.path, pr);
    renderView();
    const i = S.viewIndex.get(p.id);  // warm up the neighbours so stepping through is instant
    if (i != null) setTimeout(() => { const n = S.view[i + 1]; if (n && S.module === 'crop' && !this.plans.has(n.path) && !this.inflight.has(n.path) && this.inflight.size < 2) this.ensurePlan(n, true); }, 400);
  },
  render() { renderView(); renderLeft(); renderRight(); },

  /* ---------- center ---------- */
  center() {
    const v = $('#modView');
    if (v.dataset.mod !== 'crop') {
      v.dataset.mod = 'crop';
      v.innerHTML = `<div class="crop-stage" id="cropStage">
        <div class="crop-canvas" id="cropCanvas"><img id="cropImg" alt="" draggable="false"><svg id="cropSvg" preserveAspectRatio="none"></svg><div id="cropLabels"></div><div id="cropGrid" hidden></div><div id="cropAdj" hidden><div class="adj-box" id="adjBox"><i data-h="nw"></i><i data-h="ne"></i><i data-h="sw"></i><i data-h="se"></i><div class="adj-third v1"></div><div class="adj-third v2"></div><div class="adj-third h1"></div><div class="adj-third h2"></div><div class="adj-tag" id="adjTag">8 × 10 framing</div></div></div><span class="cmp-tag" id="cmpTagL" hidden>Original</span></div>
        <div class="crop-canvas cmp" id="cropCmp" hidden><img id="cropCmpImg" alt="" draggable="false"><svg id="cropCmpSvg" preserveAspectRatio="none"></svg><span class="cmp-tag" id="cmpTagR"></span></div>
        <div class="crop-hud" id="cropHud"></div><div class="crop-spin" id="cropSpin" hidden><span></span>Finding the face…</div><div class="crop-job" id="cropJob" hidden></div></div>`;
      this.bindAdjust();
    }
    const p = this.active(); const stage = $('#cropStage');
    if (!p) { $('#cropHud').innerHTML = '<div class="hud-msg">Select a photo in the filmstrip.</div>'; $('#cropCanvas').hidden = true; $('#cropCmp').hidden = true; return; }
    $('#cropCanvas').hidden = false;
    if (!this.plans.has(p.path) && !this.inflight.has(p.path)) setTimeout(() => this.ensurePlan(p), 0);
    const plan = this.plans.get(p.path);
    $('#cropSpin').hidden = !this.inflight.has(p.path) || !!plan || !!this.job;
    this.paintJob();
    const W = (plan && plan.size && plan.size[0]) || p.w || 3, H = (plan && plan.size && plan.size[1]) || p.h || 2;
    const cmp = this.compare && !this.adjusting, gap = 16;
    const sw = cmp ? (stage.clientWidth - 48 - gap) / 2 : stage.clientWidth - 48, sh = stage.clientHeight - 96;
    const sc = Math.max(0.01, Math.min(sw / W, sh / H));
    const dw = W * sc, dh = H * sc;
    const cv = $('#cropCanvas');
    const left = cmp ? (stage.clientWidth - 2 * dw - gap) / 2 : (stage.clientWidth - dw) / 2, top = 48 + (sh - dh) / 2;
    cv.style.cssText = `width:${dw}px;height:${dh}px;left:${left}px;top:${top}px`;
    const cc = $('#cropCmp'); cc.hidden = !cmp; $('#cmpTagL').hidden = !cmp;
    if (cmp) {
      cc.style.cssText = `width:${dw}px;height:${dh}px;left:${left + dw + gap}px;top:${top}px`;
      const kind = this.settings.preschool ? 'preschool' : 'standard';
      const rot0 = this.rotations.get(p.path) || 0;
      const g = `/graded?p=${enc(p.path)}&s=2048&k=${kind}${rot0 ? `&r=${rot0}` : ''}&t=${KS_TOKEN}`;
      const ci = $('#cropCmpImg'); if (ci.dataset.want !== g) { ci.dataset.want = g; ci.src = g; }
      $('#cmpTagR').innerHTML = `${kind === 'preschool' ? 'Preschool' : 'Standard'} color preset${this.settings.enhance ? '' : ' <i>· off, won’t be applied</i>'}`;
    }
    this.scale = sc; this.W = W; this.H = H;
    const img = $('#cropImg'); const rot = this.rotations.get(p.path) || 0;
    const want = previewUrl(p.path, 2048) + (rot ? `&r=${rot}` : '');
    if (img.dataset.want !== want) {
      const samePhoto = img.dataset.path === p.path;
      img.dataset.want = want; img.dataset.path = p.path;
      if (!samePhoto) { img.style.transform = ''; if (!rot && p.thumbUrl) img.src = p.thumbUrl; }
      const im = new Image();
      im.onload = () => { if (img.dataset.want === want) { img.src = want; if (this.live == null) img.style.transform = ''; } };
      im.src = want;
    }
    cv.classList.toggle('rotating', this.live != null);
    const svg = $('#cropSvg'); svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    let shapes = '', labels = '';
    if (plan && plan.boxes && this.overlay && !this.adjusting) {
      const fname = this.hover || this.focus;
      const focus = fname ? plan.boxes.find(b => b.name === fname) : null;
      const dimRect = cmp ? `M0 0H${W}V${H}H0Z` : `M${-W} ${-H}H${2 * W}V${2 * H}H${-W}Z`;  // side by side: keep the dimming on its own photo
      const sq = !focus && plan.boxes.find(b => this.circleFor(b));
      if (sq) {  // 3" circle on: dim outside the circle, every size still drawn
        const c = this.circleFor(sq);
        shapes += `<path d="${dimRect} M${c[0] - c[2]} ${c[1]}a${c[2]} ${c[2]} 0 1 0 ${2 * c[2]} 0a${c[2]} ${c[2]} 0 1 0 ${-2 * c[2]} 0Z" fill="rgba(5,6,8,.6)" fill-rule="evenodd"/>`;
      }
      if (focus) {
        const [x, y, w, h] = focus.box; const c = this.circleFor(focus);
        const hole = c ? `M${c[0] - c[2]} ${c[1]}a${c[2]} ${c[2]} 0 1 0 ${2 * c[2]} 0a${c[2]} ${c[2]} 0 1 0 ${-2 * c[2]} 0Z` : `M${x} ${y}V${y + h}H${x + w}V${y}Z`;
        shapes += `<path d="${dimRect} ${hole}" fill="${c ? 'rgba(5,6,8,.9)' : 'rgba(5,6,8,.62)'}" fill-rule="evenodd"/>`;
      }
      plan.boxes.forEach(b => {
        const [x, y, w, h] = b.box; const col = this.color(b.name); const hot = fname === b.name;
        if (fname && !hot) return;
        shapes += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none" stroke="${col}" stroke-width="${hot ? 2.5 : 1.6}" vector-effect="non-scaling-stroke" ${b.fits ? '' : 'stroke-dasharray="7 5"'}/>`;
        const c = this.circleFor(b);
        if (c) shapes += `<circle cx="${c[0]}" cy="${c[1]}" r="${c[2]}" fill="none" stroke="#fff" stroke-width="1.6" stroke-dasharray="${hot ? '0' : '6 5'}" vector-effect="non-scaling-stroke"/>`;
        if (fname || b.name === 'needed') labels += `<span class="box-tag" style="left:${x / W * 100}%;top:${y / H * 100}%;--c:${col}">${b.name === 'needed' ? 'Needed frame (off the photo)' : prettySize(b.name) + (c ? ` · ${this.CIRCLE_IN}″ circle` : '')}</span>`;
      });
    }
    svg.innerHTML = shapes; $('#cropLabels').innerHTML = labels;
    if (cmp) { const s2 = $('#cropCmpSvg'); s2.setAttribute('viewBox', `0 0 ${W} ${H}`); s2.innerHTML = shapes; }
    this.layoutAdjust();
    // HUD
    const st = plan && !plan.error ? STATUS_INFO[plan.status] : null;
    const i = S.viewIndex.get(p.id);
    $('#cropHud').innerHTML = `<div class="hud-left">${st ? `<span class="st-pill ${st.cls}">${st.icon} ${plan.status === 'review' ? 'Needs review — ' + esc(plan.label) : st.label}</span>` : plan && plan.error ? `<span class="st-pill review">! ${esc(plan.error)}</span>` : '<span class="st-pill none">Checking framing…</span>'}
      <span class="hud-name">${esc(p.name)}</span><span class="muted">${i != null ? `${i + 1} of ${S.view.length}` : ''}</span></div>
      ${this.adjusting ? `<div class="hud-right"><span class="muted">${this.group ? 'Draw around the whole team · drag a corner to resize' : 'Drag or arrow keys to move (Shift = faster) · corner or + − to resize'}</span><button class="btn sm" data-crop="adj-cancel">Cancel</button><button class="btn sm primary" data-crop="adj-apply">Apply</button></div>` : ''}`;
  },
  // A real progress bar on the photo while Check framing or Export prints runs.
  paintJob() {
    const el = $('#cropJob'); if (!el) return;
    const s = this.job && this.jobState && !this.jobState.finished ? this.jobState : null;
    el.hidden = !s; if (!s) return;
    const verb = this.jobKind === 'analyze' ? 'Checking framing' : 'Exporting prints';
    const f = s.total ? s.done / s.total : 0, starting = !s.done && (s.busy || s.message);
    el.innerHTML = `<div class="cj-top"><b>${verb}</b><span>${s.total ? `${s.done} of ${s.total}` : ''}${s.eta ? ` · about ${fmtDur(s.eta)} left` : ''}</span>
        <button class="btn sm" data-cancel-job="${s.id}">Cancel</button></div>
      <div class="prog ${starting ? 'busy' : ''}"><div class="bar" style="width:${(f * 100).toFixed(1)}%"></div></div>
      <div class="cj-sub">${esc(starting ? (s.message || 'Loading face detector…') : (s.current || ''))}</div>`;
  },
  /* ---------- straighten ---------- */
  livePreview(deg) {
    const p = this.active(); if (!p) return;
    this.live = deg;
    const d = deg - (this.rotations.get(p.path) || 0), a = Math.abs(d) * Math.PI / 180;
    const k = Math.cos(a) + Math.sin(a) * Math.max(this.W / this.H, this.H / this.W);
    $('#cropImg').style.transform = `rotate(${d}deg) scale(${k})`;
    $('#cropCanvas').classList.add('rotating'); $('#cropGrid').hidden = false;
    const v = $('#rotVal'); if (v) v.textContent = `${deg > 0 ? '+' : ''}${(+deg).toFixed(1)}°`;
  },
  async setRotation(deg) {
    const p = this.active(); if (!p) return;
    deg = Math.round(clamp(+deg, -10, 10) * 10) / 10;
    try { await api('/api/crop/rotate', { path: p.path, angle: deg }); } catch (e) { return toast(esc(e.message)); }
    if (deg) this.rotations.set(p.path, deg); else this.rotations.delete(p.path);
    if (this.manual.has(p.path)) {  // a hand placement was drawn on the old angle
      this.manual.delete(p.path); DB.del('manual', p.path).catch(() => {});
      toast('Straightened — the hand-placed framing was reset, so place it again if needed', 3500);
    }
    this.live = null; $('#cropGrid').hidden = true;
    this.plans.delete(p.path); this.status.delete(p.path);
    this.render(); this.ensurePlan(p);
  },
  nudge(step) {
    const p = this.active(); if (!p || this.adjusting) return;
    const base = this.live ?? this.rotations.get(p.path) ?? 0;
    const v = Math.round(clamp(base + step, -10, 10) * 10) / 10;
    this.livePreview(v); const r = $('[data-straight]'); if (r) r.value = v;
    clearTimeout(this._rt); this._rt = setTimeout(() => this.setRotation(v), 450);
  },
  /* ---------- adjust (hand placement) ---------- */
  tightSize() { return this.sizes.find(z => z.own_framing && z.kind === 'portrait' && !(this.settings.disabled_sizes || []).includes(z.name)); },
  startSquare() {
    const p = this.active(); const plan = p && this.plans.get(p.path); const z = this.tightSize();
    if (!plan || plan.error || !plan.reference) return toast('Still checking this photo — try again in a moment');
    if (!z) return toast('There is no tight size (like 3.5 × 3.5) switched on');
    if (plan.landscape) return toast('Group shots don’t get the square size');
    const m = this.manual.get(p.path); const ex = plan.boxes.find(b => b.name === z.name);
    let a;
    if (m && m.square) a = { ...m.square };
    else if (ex) { const [x, y, w, h] = ex.box; a = { center_x: x + w / 2, top: y, height: h }; }
    else { const r = plan.reference; const h = Math.min(r.height * 0.8, this.W, this.H); a = { center_x: r.center_x, top: Math.max(0, r.top - h * 0.05), height: h }; }
    this.A = z.w / z.h; this.group = false; this.target = 'square'; this.targetName = z.name;
    a.height = Math.min(a.height, this.H, this.W / this.A); a.top = clamp(a.top, 0, this.H - a.height);
    this.adjusting = a; this.render();
  },
  startAdjust() {
    this.target = 'full';
    const p = this.active(); const plan = p && this.plans.get(p.path);
    if (!plan || plan.error) return toast(this.inflight.has(p && p.path) ? 'Still checking this photo — try again in a moment' : 'This photo couldn’t be checked, so it can’t be adjusted');
    const r = plan.reference; if (!r) return toast('Nothing to adjust on this photo');
    this.A = plan.ref_aspect || 0.8; this.group = !!plan.landscape;
    this.adjusting = { center_x: r.center_x, top: r.top, height: Math.min(r.height, this.H, this.W / this.A) };
    this.render();
  },
  // arrow keys: 0.25% of the photo per press, 2.5% with Shift; + / − resize around the centre
  moveAdjust(dx, dy, big) {
    const a = this.adjusting; if (!a) return;
    const step = Math.max(1, this.H * (big ? 0.025 : 0.0025)), w = a.height * (this.A || 0.8);
    this.adjusting = { center_x: clamp(a.center_x + dx * step, w / 2, this.W - w / 2), top: clamp(a.top + dy * step, 0, this.H - a.height), height: a.height };
    this.layoutAdjust();
  },
  resizeAdjust(dir, big) {
    const a = this.adjusting; if (!a) return; const A = this.A || 0.8;
    const h = clamp(a.height * (1 + dir * (big ? 0.05 : 0.01)), 60, Math.min(this.H, this.W / A)), w = h * A;
    const cy = a.top + a.height / 2;
    this.adjusting = { center_x: clamp(a.center_x, w / 2, this.W - w / 2), top: clamp(cy - h / 2, 0, this.H - h), height: h };
    this.layoutAdjust();
  },
  cancelAdjust(quiet) { this.adjusting = null; this.target = 'full'; if (!quiet) this.render(); },
  async applyAdjust() {
    const p = this.active(); if (!p || !this.adjusting) return;
    const box = { center_x: Math.round(this.adjusting.center_x), top: Math.round(this.adjusting.top), height: Math.round(this.adjusting.height) };
    const prev = this.manual.get(p.path); const plan = this.plans.get(p.path);
    let m;
    if (this.target === 'square') {
      // the full-length sizes keep what they had: a hand placement, or the automatic framing
      const base = prev && !prev.kind ? prev : plan && plan.reference ? plan.reference : box;
      m = { center_x: Math.round(base.center_x), top: Math.round(base.top), height: Math.round(base.height), square: box };
    } else {
      m = { ...box };
      if (this.group) m.kind = 'group';
      else if (prev && prev.square) m.square = prev.square;
    }
    const wasSquare = this.target === 'square'; this.target = 'full';
    this.adjusting = null; this.manual.set(p.path, m); DB.put('manual', p.path, m).catch(() => {});
    this.plans.delete(p.path); this.render(); this.ensurePlan(p);
    toast(wasSquare ? `${prettySize(this.targetName)} placed by hand` : m.kind === 'group' ? 'Group framing placed by hand — both group sizes keep everything inside it' : 'Framing placed by hand — every full-length size is cut from it', 3500);
  },
  async resetManual() {
    const p = this.active(); if (!p || !this.manual.has(p.path)) return;
    this.manual.delete(p.path); DB.del('manual', p.path).catch(() => {});
    this.plans.delete(p.path); this.render(); this.ensurePlan(p); toast('Back to automatic framing');
  },
  layoutAdjust() {
    const a = this.adjusting; $('#cropAdj').hidden = !a; if (!a) return;
    const w = a.height * (this.A || 0.8), l = a.center_x - w / 2;
    const tag = $('#adjTag'); if (tag) tag.textContent = this.target === 'square' ? `${prettySize(this.targetName)} framing` : this.group ? 'Group framing — keep the whole team inside' : '8 × 10 framing';
    Object.assign($('#adjBox').style, { left: l / this.W * 100 + '%', top: a.top / this.H * 100 + '%', width: w / this.W * 100 + '%', height: a.height / this.H * 100 + '%' });
  },
  bindAdjust() {
    const box = $('#adjBox'); let drag = null;
    box.addEventListener('pointerdown', e => {
      if (!this.adjusting) return; e.preventDefault(); box.setPointerCapture(e.pointerId);
      drag = { h: e.target.dataset.h || 'move', x: e.clientX, y: e.clientY, a: { ...this.adjusting } };
    });
    box.addEventListener('pointermove', e => {
      if (!drag) return;
      const dx = (e.clientX - drag.x) / this.scale, dy = (e.clientY - drag.y) / this.scale, a0 = drag.a, A = this.A || 0.8;
      let { center_x, top, height } = a0; const w0 = height * A, l0 = center_x - w0 / 2;
      if (drag.h === 'move') { center_x = clamp(a0.center_x + dx, w0 / 2, this.W - w0 / 2); top = clamp(a0.top + dy, 0, this.H - height); }
      else {
        const right = l0 + w0, bottom = a0.top + a0.height;
        const sgnX = drag.h.includes('e') ? 1 : -1, sgnY = drag.h.includes('s') ? 1 : -1;
        let nh = Math.max(height + sgnY * dy, (height * A + sgnX * dx) / A);
        const anchorX = sgnX > 0 ? l0 : right, anchorY = sgnY > 0 ? a0.top : bottom;
        const maxW = sgnX > 0 ? this.W - anchorX : anchorX, maxH = sgnY > 0 ? this.H - anchorY : anchorY;
        nh = clamp(nh, 60, Math.min(maxH, maxW / A));
        const nw = nh * A;
        center_x = sgnX > 0 ? anchorX + nw / 2 : anchorX - nw / 2;
        top = sgnY > 0 ? anchorY : anchorY - nh; height = nh;
      }
      this.adjusting = { center_x, top, height }; this.layoutAdjust();
    });
    const up = () => { drag = null; };
    box.addEventListener('pointerup', up); box.addEventListener('pointercancel', up);
  },

  /* ---------- left panel ---------- */
  counts(list) {
    const c = { ok: 0, shortened: 0, manual: 0, review: 0, unchecked: 0 };
    for (const p of list) c[(this.status.get(p.path) || {}).status || 'unchecked']++;
    return c;
  },
  left() {
    const all = S.view.length, sel = S.selected.size;
    const list = scopeList(this.scope); const c = this.counts(S.photos.length ? sourcePhotos().filter(p => matchRules(p, { ...S.filter, crop: 'any' })) : []);
    const row = (k) => { const st = STATUS_INFO[k]; return `<div class="row st-row-${st.cls} ${S.filter.crop === k ? 'on' : ''}" data-cropfilter="${k}"><span class="st-dot ${st.cls}"></span><span class="lbl">${st.label}</span><span class="cnt">${c[k]}</span></div>`; };
    let html = sectionHTML('c-scope', 'Photos to crop', `<div class="pad" title="${esc(sourceName())}${S.filter.flag !== 'any' || S.filter.rating || S.filter.label !== 'any' || S.filter.text ? ' (filtered)' : ''}. Pick your keepers in Library, then crop them here.">${segHTML('cropScope', this.scope, [['all', `Filmstrip · ${all}`], ['selected', `Selected · ${sel}`]])}
</div>`);
    html += sectionHTML('c-check', 'Framing check', `${['ok', 'shortened', 'manual', 'review', 'unchecked'].map(row).join('')}
      <div class="pad"><button class="btn wide" data-crop="analyze" ${this.job ? 'disabled' : ''}>Check framing on ${plural(list.length, 'photo')}</button>
      </div>`);
    const s = this.settings;
    if (s) {
      const tq = !s.preschool && ['knee_above', 'knee_below'].includes(s.framing_style);
      if (S.sections['c-out'] === undefined) S.sections['c-out'] = false;  // set once, rarely touched
    const nOwn = S.photos.filter(p => this.styles.has(p.path)).length;  // this folder only
    html += sectionHTML('c-frame', 'Framing style', `<div class="pad">${nOwn ? `<div class="own-note">${plural(nOwn, 'photo')} use${nOwn === 1 ? 's' : ''} its own style <button class="btn sm" data-crop="clear-styles">Clear</button></div>${this.styleRows()}` : ''}${segHTML('cropMode', s.preschool ? 'preschool' : tq ? 'tq' : 'full', [['full', 'Full'], ['tq', '3/4'], ['preschool', 'Preschool']])}</div>
        ${tq ? `<div class="pad" title="The bottom edge crosses the legs a little above or below the knees — never on the joint. The square keeps its own face framing.">${segHTML('kneeLine', s.framing_style, [['knee_above', 'Just above knees'], ['knee_below', 'Just below knees']])}</div>` : ''}
        ${tq ? '' : switchHTML('balance_feet', s.balance_feet && !s.preschool, 'Balance feet', 'Center shorter and taller kids by finding their feet (standing poses only)')}
        ${s.balance_feet && !s.preschool && !tq ? `<div class="slider-row" title="Space under the feet"><span>Margin</span><input type="range" min="0" max="0.3" step="0.005" value="${s.bottom_margin}" data-range="bottom_margin"><b>${Math.round(s.bottom_margin * 1000) / 10}%</b></div>` : ''}
        ${switchHTML('fit_to_frame', s.fit_to_frame, 'Shorten to fit', 'When the ideal frame runs off the photo, shorten it instead of sending the photo to review')}
        ${switchHTML('landscape', s.landscape, 'Crop group shots', 'Landscape photos are cropped to the landscape sizes around the whole group')}
        <div class="pad"><button class="btn sm wide" data-crop="tunables">Fine-tune framing…</button></div>`)
      + sectionHTML('c-color', 'Color', `${switchHTML('enhance', s.enhance, 'Apply color preset', s.preschool ? 'Uses the preschool preset' : 'Uses the standard preset')}
        <div class="pad ${s.enhance ? '' : 'disabled'}">${segHTML('enhanceWhen', s.enhance_when, [['before', 'Before cropping'], ['after', 'After cropping']])}</div>`)
      + sectionHTML('c-out', 'Output', `<div class="pad"><div class="pathrow"><span class="path" title="${esc(this.outDir)}">${esc(this.outDir || 'Open a folder first')}</span></div>
        <div class="btn-row"><button class="btn sm" data-crop="out-change">Change…</button>${this.outCustom ? '<button class="btn sm" data-crop="out-default">Use default</button>' : '<span class="muted small">default</span>'}</div></div>
        ${switchHTML('orders', s.orders, `Also copy all sizes to “${esc(this.ordersName)}”`)}
        ${switchHTML('contact_sheets', s.contact_sheets, 'Make contact sheets')}`);
    }
    if (S.filter.cstyle && S.filter.cstyle !== 'any') html = `<div class="filter-note">Showing only <b>${S.filter.cstyle === 'batch' ? 'same as left side' : esc(this.STYLE_NAMES[S.filter.cstyle])}</b> · ${S.view.length} photo${S.view.length === 1 ? '' : 's'}<button class="btn sm primary" data-stylefilter="any">Show all</button></div>` + html;
    if (S.filter.crop && S.filter.crop !== 'any') html = `<div class="filter-note">Showing only <b>${esc(STATUS_INFO[S.filter.crop].label)}</b> · ${S.view.length} photo${S.view.length === 1 ? '' : 's'}<button class="btn sm primary" data-cropfilter="any">Show all</button></div>` + html;
    let foot = '';
    if (this.job && this.jobState && !this.jobState.finished) foot = progressHTML(this.jobState, this.jobKind === 'analyze' ? 'Checking framing' : 'Exporting prints');
    else if (this.result) {
      const r = this.result;
      foot = `<div class="job-card done"><div class="job-top"><b>${r.cancelled ? 'Export stopped' : 'Prints exported'}</b>${r.seconds != null ? `<span class="job-time">in ${fmtDur(r.seconds)}</span>` : ''}</div>
        <div class="res-grid"><span class="st-dot ok"></span>${r.cropped} cropped<span class="st-dot short"></span>${r.shortened} shortened<span class="st-dot review"></span>${r.review} need review</div>
        ${r.skipped_non_jpeg && r.skipped_non_jpeg.length ? `<div class="hint tight">${plural(r.skipped_non_jpeg.length, 'non-JPEG photo')} skipped.</div>` : ''}
        <div class="btn-row"><button class="btn sm" data-crop="open-out">Open folder</button>${r.sheets && r.sheets.length ? '<button class="btn sm" data-crop="sheets">Contact sheets</button>' : ''}${r.review ? '<button class="btn sm" data-cropfilter="review">Show review</button>' : ''}</div></div>`;
    }
    $('#left').innerHTML = `<div class="scroll">${html}</div><div class="left-foot col">${foot}
      <button class="btn primary big" data-crop="export" ${this.job || !list.length ? 'disabled' : ''}>Export prints (${list.length})</button></div>`;
  },

  /* ---------- right panel ---------- */
  right() {
    const s = this.settings; const R = $('#right');
    if (!s) { R.innerHTML = `<div class="scroll"><div class="hint">${esc(this.planError || 'Loading crop settings…')}</div></div>`; return; }
    const p = this.active(); const plan = p && this.plans.get(p.path);
    const dims = {}; if (plan && plan.boxes) plan.boxes.forEach(b => dims[b.name] = b.box);
    const off = new Set(s.disabled_sizes || []);
    let status = '<div class="hint">Select a photo to check its framing.</div>';
    if (p && plan && !plan.error) {
      const st = STATUS_INFO[plan.status];
      status = `<div class="status-card ${st.cls}"><div class="sc-head"><span class="st-dot ${st.cls}"></span><b>${plan.status === 'review' ? 'Needs review' : st.label}</b></div>
        ${plan.status === 'review' ? `<div class="sc-label">${esc(plan.label)}</div>` : ''}
        ${plan.reason ? `<details data-reason ${this.detailsOpen ? 'open' : ''}><summary>Details</summary><pre>${esc(plan.reason)}</pre></details>` : ''}
        ${plan.status === 'shortened' ? '<div class="hint tight">The ideal frame ran off the photo, so the bottom edge sits a little higher than usual. Worth a glance.</div>' : ''}
        ${plan.missing && plan.missing.length ? `<div class="miss-note"><b>${plan.missing.map(prettySize).join(', ')} won’t be made</b> — its tight framing couldn’t be placed automatically on this photo (more than one face found, or it runs off the edge). Press <kbd>S</kbd> to place it by hand.</div>` : ''}
        <div class="btn-row"><button class="btn sm" data-crop="adjust">${plan.landscape ? 'Adjust group framing' : 'Adjust framing'} <kbd>A</kbd></button>${!plan.landscape && this.tightSize() && plan.status !== 'review' ? `<button class="btn sm" data-crop="square">Place ${prettySize(this.tightSize().name)} <kbd>S</kbd></button>` : ''}${plan.landscape && plan.status !== 'manual' ? '<span class="muted small">Group shot</span>' : ''}
        ${this.manual.has(p.path) ? '<button class="btn sm" data-crop="reset">Reset to automatic</button>' : ''}</div></div>`;
    } else if (p && plan && plan.error) status = `<div class="status-card review"><div class="sc-head"><span class="st-dot review"></span><b>${/switched off/.test(plan.error) ? 'No sizes switched on' : 'Couldn’t check this photo'}</b></div><div class="sc-label">${esc(plan.error.replace(/^\w+Error: /, ''))}</div></div>`;
    else if (p && this._lastCard && this._lastCard.path === p.path) {
      // re-checking the same photo (a size or setting changed): keep its card in place, dimmed
      status = `<div class="rechecking">${this._lastCard.html}<span class="recheck-badge"><span class="spin-dot"></span>Checking…</span></div>`;
    } else if (p) status = '<div class="status-card none checking"><div class="sc-head"><span class="spin-dot"></span><b>Checking framing…</b></div></div>';
    if (p && plan) this._lastCard = { path: p.path, html: status };
    const sizeRow = z => {
      const d = dims[z.name]; const on = !off.has(z.name);
      return `<div class="size-row ${on ? '' : 'off'} ${this.hover === z.name ? 'hot' : ''}" data-size="${esc(z.name)}">
        <button class="chk ${on ? 'on' : ''}" data-sizetoggle="${esc(z.name)}" title="${on ? 'Turn off' : 'Turn on'} this size"></button>
        <span class="swatch-line" style="--c:${this.color(z.name)}"></span>
        <span class="sz-name" ${z.own_framing ? 'title="Tight face framing, separate from the full-length sizes"' : ''}>${prettySize(z.name)}</span>
        <span class="sz-dim">${d ? `${d[2]} × ${d[3]}` : on ? (plan && plan.missing && plan.missing.includes(z.name) ? '<span class="warn">not made</span>' : '—') : 'off'}</span></div>
        ${this.squareInches(z.name) > this.CIRCLE_IN ? `<div class="size-sub" title="Dim everything outside a ${this.CIRCLE_IN}″ circle centred in the ${prettySize(z.name)}, to check a round print"><span class="sub-elbow"></span><span class="sub-lbl">${this.CIRCLE_IN}″ circle mask</span><button class="mini-switch ${this.circle ? 'on' : ''}" data-circle="${esc(z.name)}" aria-label="${this.CIRCLE_IN} inch circle mask"></button></div>` : ''}`;
    };
    const portrait = this.sizes.filter(z => z.kind === 'portrait'), land = this.sizes.filter(z => z.kind === 'landscape');
    const nOn = this.sizes.filter(z => !off.has(z.name)).length, allOn = nOn === this.sizes.length;
    const master = `<div class="size-row master"><button class="chk ${allOn ? 'on' : nOn ? 'some' : ''}" data-sizeall="${allOn ? 'off' : 'on'}" title="${allOn ? 'Turn every size off' : 'Turn every size on'}"></button><span class="sz-name">All sizes</span><span class="sz-dim">${nOn} of ${this.sizes.length} on</span></div>`;
    const rot = p ? (this.live ?? this.rotations.get(p.path) ?? 0) : 0;
    const straight = p && plan && !plan.error ? `<div class="straight compact" title="Drag to level the photo — a grid appears to line up walls and the floor. [ ] nudge 0.1°, with Shift 1°."><button class="btn sm icon" data-crop="rot-" title="−0.1°  ( [ )">−</button><input type="range" min="-10" max="10" step="0.1" value="${rot}" data-straight><button class="btn sm icon" data-crop="rot+" title="+0.1°  ( ] )">+</button><b id="rotVal" ${rot ? 'data-crop="rot0" title="Click to reset to 0°" class="resettable"' : ''}>${rot > 0 ? '+' : ''}${(+rot).toFixed(1)}°</b></div>` : '<div class="hint">Select a photo to straighten it.</div>';
    if (p) {
      const own = this.styleOf(p.path), nSel = S.selected.size > 1 && S.selected.has(p.id) ? S.selected.size : 1;
      status += `<div class="style-row" title="A framing style just for ${nSel > 1 ? `the ${nSel} selected photos` : 'this photo'}. Batch uses the Framing style set on the left."><span>Style</span>
        <select data-photostyle class="${own ? 'own' : ''}"><option value="">Same as left side (${esc(this.STYLE_NAMES[this.batchStyle()])})</option><option disabled>──────────</option>${Object.entries(this.STYLE_NAMES).map(([k, n]) => `<option value="${k}" ${own === k ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>${own ? `<span class="style-tag inline">${STYLE_TAGS[own]}</span>` : ''}${nSel > 1 ? `<em>${nSel} selected</em>` : ''}</div>`;
    }
    const html = sectionHTML('c-status', 'Framing', status) + sectionHTML('c-straight', 'Straighten', straight)
      + sectionHTML('c-sizes', 'Print sizes', `<div class="sizes">${master}${portrait.map(sizeRow).join('')}${land.length && (!plan || plan.landscape) ? `<div class="sz-group">Group shots (landscape)</div>${land.map(sizeRow).join('')}` : ''}</div>`, ' <span class="sec-note" title="Hover a size to see just that crop. Pixel sizes are for this photo.">ⓘ</span>')
      ;
    R.innerHTML = `<div class="scroll">${html}</div>`;
  },
  modbar() {
    const p = this.active(); const m = p && this.manual.has(p.path);
    $('#modbar').innerHTML = `<span class="muted small">Select</span><div class="seg crop-pick"><button data-crop="pick-both" title="Select every Pick (P) and team photo (T) in the folder, to crop and export them">Picks + teams</button><button data-crop="pick-picks" title="Select every Pick (P) that isn't a team photo">Picks</button><button data-crop="pick-teams" title="Select every team photo (T)">Teams</button></div><div class="tb-sep"></div><div class="tb-group"><button class="btn sm" data-crop="adjust" ${p ? '' : 'disabled'}>Adjust framing <kbd>A</kbd></button>
      ${m ? '<button class="btn sm" data-crop="reset">Reset to automatic</button>' : ''}</div><div class="tb-sep"></div>
      <button class="toggle ${this.overlay ? 'on' : ''}" data-crop="overlay" title="Show crop boxes (O)">Crop boxes</button>
      <button class="toggle ${this.compare ? 'on' : ''}" data-crop="compare" title="Original and color preset side by side (C)">Color side by side <kbd>C</kbd></button>
      <div class="tb-spacer"></div><span class="muted small">← → step through photos · P / X flag · 1–5 rate</span>`;
  },

  /* ---------- actions ---------- */
  // Everything that gets printed: one Pick per kid plus the team photos.
  // which: 'both' (Picks and team photos), 'picks' (Picks that aren't team photos) or 'teams'.
  selectPicksTeam(which = 'both') {
    const isT = p => !!getMeta(p.key).team, isP = p => getMeta(p.key).flag === 1;
    const want = which === 'teams' ? isT : which === 'picks' ? (p => isP(p) && !isT(p)) : (p => isP(p) || isT(p));
    const ids = S.photos.filter(want).map(p => p.id);
    if (!ids.length) return toast(which === 'teams' ? 'No team photos (T) in this folder yet' : which === 'picks' ? 'No Picks (P) in this folder yet' : 'No Picks (P) or team photos (T) in this folder yet', 3500);
    const nTeam = ids.filter(id => isT(S.byId.get(id))).length;
    S.selected = new Set(ids); S.active = ids[0]; S.anchor = ids[0]; this.scope = 'selected';
    refreshSelection(); renderLeft();
    // Framing is never checked on its own: Check framing starts it.
    const unchecked = ids.filter(id => !this.status.has(S.byId.get(id).path)).length;
    const what = which === 'teams' ? plural(nTeam, 'team photo') : which === 'picks' ? plural(ids.length, 'pick') : `${plural(ids.length - nTeam, 'pick')} and ${plural(nTeam, 'team photo')}`;
    toast(`${what} selected.${unchecked ? ` ${plural(unchecked, 'photo')} not checked yet — press Check framing when you're ready.` : ' Crop will export just these.'}`, 5000);
  },
  async setOut(path, custom) {
    this.outDir = path; this.outCustom = custom;
    if (S.root) { if (custom) DB.put('kv', 'cropout|' + S.root, path).catch(() => {}); else DB.del('kv', 'cropout|' + S.root).catch(() => {}); }
    renderRight();
  },
  async analyze() {
    const list = scopeList(this.scope); if (!list.length || this.job) return;
    const manual = {}; list.forEach(p => { if (this.manual.has(p.path)) manual[p.path] = this.manual.get(p.path); });
    let id; try { id = (await api('/api/crop/analyze', { paths: list.map(p => p.path), manual })).job; } catch (e) { return toast(esc(e.message)); }
    this.job = id; this.jobKind = 'analyze'; this.jobState = { id, total: list.length, done: 0, busy: true, message: 'Loading face detector…' };
    renderLeft();
    const batch = [];
    const fin = await pollJob(id, s => {
      this.jobState = s;
      for (const it of s.items) { const v = { status: it.status, label: it.label, reason: it.reason, src: 'check' }; this.status.set(it.path, v); batch.push([it.path, v]); if (it.plan) this.plans.set(it.path, it.plan); }
      if (S.module === 'crop') { renderLeft(); schedule(R_CELLS); this.paintJob(); }
    });
    DB.putMany('cropstatus', batch).catch(() => {});
    this.job = null; this.jobState = null; renderAll();
    if (fin.error) return toast('Framing check failed: ' + esc(fin.error));
    const c = this.counts(list);
    toast(`Checked ${plural(list.length, 'photo')} · ${c.review} need review`, 3500);
  },
  async exportPrints() {
    const list = scopeList(this.scope); if (!list.length || this.job) return;
    if (!this.outDir) return toast('Choose an output folder first');
    const manual = {}; list.forEach(p => { if (this.manual.has(p.path)) manual[p.path] = this.manual.get(p.path); });
    let id; try { id = (await api('/api/crop/export', { paths: list.map(p => p.path), out_dir: this.outDir, manual })).job; } catch (e) { return toast(esc(e.message)); }
    this.job = id; this.jobKind = 'prints'; this.result = null;
    this.jobState = { id, total: list.length, done: 0, busy: true, message: 'Loading face detector…' };
    renderLeft();
    const batch = [];
    const fin = await pollJob(id, s => {
      this.jobState = s;
      for (const it of s.items) { const v = { status: it.status, label: it.label, reason: it.reason, src: 'export' }; this.status.set(it.path, v); batch.push([it.path, v]); }
      if (S.module === 'crop') { renderLeft(); schedule(R_CELLS); this.paintJob(); }
    });
    DB.putMany('cropstatus', batch).catch(() => {});
    this.job = null; this.jobState = null;
    if (fin.error) { renderAll(); return toast('Export failed: ' + esc(fin.error)); }
    this.result = fin.result; renderAll();
    toast(`Exported prints for ${plural(fin.result.cropped, 'photo')}${fin.result.review ? ` · ${fin.result.review} need review` : ''} <button class="toast-link" onclick="reveal(${esc(JSON.stringify(fin.result.out_dir))})">Show</button>`, 6000);
  },
  showSheets() {
    const r = this.result; if (!r || !r.sheets.length) return;
    openModal(`<h3>Contact sheets</h3><div class="sheet-list">${r.sheets.map(s => `<button class="row" data-open="${esc(s)}"><span class="lbl">${esc(baseName(s))}</span><span class="cnt">Open</span></button>`).join('')}</div>
      <div class="m-actions"><button class="btn" data-close>Close</button></div>`, card => card.addEventListener('click', e => { const b = e.target.closest('[data-open]'); if (b) openExternal(b.dataset.open); }));
  },
  async tunables() {
    if ($('#tunePanel')) return this.closeTune();
    let t; try { t = (await api('/api/crop/tunables', {})).tunables; } catch (e) { return toast(esc(e.message)); }
    const start = Object.fromEntries(t.map(x => [`${x.section}.${x.key}`, x.value]));
    const open = { full: 'Full length', knee_above: '3/4 length', knee_below: '3/4 length', preschool: 'Preschool' }[(this.active() && this.styleOf(this.active().path)) || this.batchStyle()];
    const groups = [...new Set(t.map(x => x.group))];
    const fmt = v => v == null ? '' : (+v).toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
    const row = x => { const k = `${x.section}.${x.key}`, step = x.max > 1.5 ? 0.01 : 0.002;
      return `<div class="tune-row" title="${esc(x.help)}"><label>${esc(x.label)}</label><input type="range" min="${x.min}" max="${x.max}" step="${step}" value="${x.value ?? x.min}" data-tr="${k}"><input type="number" min="${x.min}" max="${x.max}" step="${step / 2}" value="${fmt(x.value)}" data-tn="${k}"></div>`; };
    const el = document.createElement('div'); el.id = 'tunePanel'; el.className = 'tune-panel';
    el.innerHTML = `<div class="tp-head"><b>Fine-tune framing</b><button class="btn sm" data-tp="close" title="Done">Done</button></div>
      <div class="tp-note">Changes apply as you go and re-check the photo on screen. Values are shares of the frame height. Hover a row for what it does.</div>
      <div class="tp-body">${groups.map(g => `<details ${g === open || g === 'Square (tight)' ? 'open' : ''}><summary>${esc(g)}</summary>${t.filter(x => x.group === g).map(row).join('')}</details>`).join('')}</div>
      <div class="tp-foot"><button class="btn sm" data-tp="revert">Undo changes</button><button class="btn sm" data-tp="config">Open config.yaml</button></div>`;
    document.body.appendChild(el);
    const pending = {};
    const send = () => { clearTimeout(this._tuneT); this._tuneT = setTimeout(async () => {
      const values = { ...pending }; for (const k in pending) delete pending[k];
      try { await api('/api/crop/tunables', { values }); } catch (e) { return toast(esc(e.message)); }
      this.saveSettings({});
    }, 350); };
    const setVal = (k, v, from) => {
      const r = $(`[data-tr="${k}"]`, el), n = $(`[data-tn="${k}"]`, el);
      if (from !== 'r') r.value = v; if (from !== 'n') n.value = fmt(v);
      pending[k] = +v; send();
    };
    el.addEventListener('input', e => { const r = e.target.closest('[data-tr]'); if (r) setVal(r.dataset.tr, r.value, 'r'); });
    el.addEventListener('change', e => { const n = e.target.closest('[data-tn]'); if (n && n.value !== '') setVal(n.dataset.tn, n.value, 'n'); });
    el.addEventListener('keydown', e => e.stopPropagation());
    el.addEventListener('click', e => {
      const b = e.target.closest('[data-tp]'); if (!b) return;
      if (b.dataset.tp === 'close') this.closeTune();
      else if (b.dataset.tp === 'config') openExternal(this.configPath);
      else if (b.dataset.tp === 'revert') { for (const [k, v] of Object.entries(start)) if (v != null) setVal(k, v); toast('Framing values put back'); }
    });
  },
  closeTune() { const el = $('#tunePanel'); if (el) el.remove(); },
  key(e, k) {
    if (this.adjusting) {
      if (e.key === 'Escape') { this.cancelAdjust(); return true; }
      if (e.key === 'Enter') { this.applyAdjust(); return true; }
      const mv = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      if (mv) { this.moveAdjust(mv[0], mv[1], e.shiftKey); return true; }
      if (['+', '=', '-', '_'].includes(e.key)) { this.resizeAdjust(e.key === '+' || e.key === '=' ? 1 : -1, e.shiftKey); return true; }
      return e.key === ' ';
    }
    if (k === 'a') { this.startAdjust(); return true; }
    if (k === 's') { this.startSquare(); return true; }
    if (e.key === '[' || e.key === '{') { this.nudge(e.shiftKey ? -1 : -0.1); return true; }
    if (e.key === ']' || e.key === '}') { this.nudge(e.shiftKey ? 1 : 0.1); return true; }
    if (k === 'c' && !e.ctrlKey && !e.metaKey) { this.toggleCompare(); return true; }
    if (k === 'o') { this.overlay = !this.overlay; this.render(); this.modbar(); return true; }
    return false;
  },
};

