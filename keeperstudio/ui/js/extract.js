// Keeper Studio UI — extract. Plain scripts sharing one global scope, loaded in order by index.html.
'use strict';
/* ============================================================= Extract ==== */
const Cut = {
  scope: 'all', outDir: '', outCustom: false, existing: {}, job: null, jobState: null, result: null, ready: null, view: 'cut', errors: [],
  quality: 'best', status: null, qLoaded: false,
  async libraryLoaded() {
    this.result = null; this.existing = {}; this.errors = [];
    const saved = S.root ? await DB.get('kv', 'cutout|' + S.root).catch(() => null) : null;
    this.outCustom = !!saved; this.outDir = saved || (S.root ? `${S.root}_cutouts` : '');
  },
  async refresh() {
    if (!this.qLoaded) { this.qLoaded = true; const q = await DB.get('kv', 'cutout|quality').catch(() => null); if (q === 'best' || q === 'fast') this.quality = q; }
    try { this.status = await api('/api/cutout/status', {}); this.ready = !!this.status.ready[this.quality]; } catch {}
    if (this.outDir && S.photos.length) {
      try { this.existing = (await api('/api/cutout/existing', { paths: S.photos.map(p => p.path), out_dir: this.outDir })).existing; } catch {}
    }
    if (S.module === 'cutout') this.render();
  },
  // With photos selected, Extract works on the selection, not the whole filmstrip.
  enter() { if (S.selected.size && !this.job) this.scope = 'selected'; this.refresh(); this.render(); },
  render() { renderView(); renderLeft(); renderRight(); },
  setQuality(q) { this.quality = q; DB.put('kv', 'cutout|quality', q).catch(() => {}); this.ready = this.status ? !!this.status.ready[q] : null; renderLeft(); },
  qualityHTML() {
    const st = this.status, m = st && st.models[this.quality], free = st && st.free_gb;
    const about = this.quality === 'best'
      ? 'BiRefNet: the cleanest edges on hair and pom-poms. Slower, and needs about 7 GB of free memory while it runs.'
      : 'ISNet: a few seconds a photo and about 3 GB of memory. Edges on loose hair are softer.';
    const model = !st ? 'Checking…' : st.ready[this.quality] ? `${m.label} model ready` : `${m.label} model downloads on first use (about ${m.mb} MB)`;
    const low = free != null && m && free < m.ram_gb;
    return `<div class="pad">${segHTML('cutQuality', this.quality, [['best', 'Best'], ['fast', 'Fast']])}
      <div class="hint tight" style="margin-top:6px">${about}</div>
      <div class="model-line"><span class="st-dot ${st && st.ready[this.quality] ? 'ok' : 'none'}"></span>${esc(model)}</div>
      ${free != null ? `<div class="model-line ${low ? 'warn' : ''}"><span class="st-dot ${low ? 'warn' : 'ok'}"></span>Free memory now: ${free.toFixed(1)} GB${low ? ' · close other programs or use Fast' : ''}</div>` : ''}</div>`;
  },
  left() {
    const list = scopeList(this.scope);
    const html = sectionHTML('cu-scope', 'Photos', `<div class="pad">${segHTML('cutScope', this.scope, [['all', `Filmstrip · ${S.view.length}`], ['selected', `Selected · ${S.selected.size}`]])}</div>`)
      + sectionHTML('cu-out', 'Save extracted photos to', `<div class="pad"><div class="pathrow"><span class="path" title="${esc(this.outDir)}">${esc(this.outDir || 'Open a folder first')}</span></div>
        <div class="btn-row"><button class="btn sm" data-cut="out-change">Change…</button>${this.outCustom ? '<button class="btn sm" data-cut="out-default">Use default</button>' : ''}</div>
        <div class="hint tight">Each photo becomes a PNG with a transparent background, named like the original.</div></div>`)
      + sectionHTML('cu-quality', 'Quality', this.qualityHTML());
    let foot = '';
    if (this.job && this.jobState && !this.jobState.finished) foot = progressHTML(this.jobState, 'Extracting');
    else if (this.result) foot = `<div class="job-card done"><div class="job-top"><b>${this.result.cancelled ? 'Stopped' : 'Done'}</b></div><div class="hint tight">${plural(this.result.ok, 'photo')} extracted${this.errors.length ? ` · ${this.errors.length} failed` : ''}.</div><div class="btn-row"><button class="btn sm" data-cut="open-out">Open folder</button></div></div>`;
    $('#left').innerHTML = `<div class="scroll">${html}</div><div class="left-foot col">${foot}<button class="btn primary big" data-cut="run" ${this.job || !list.length ? 'disabled' : ''}>Extract (${list.length})</button></div>`;
  },
  right() {
    const p = S.byId.get(S.active);
    $('#right').innerHTML = `<div class="scroll">${sectionHTML('cu-about', 'About', `<div class="hint">Cuts the subject out of each photo with BiRefNet, the same model PhotoExtractor uses — clean edges on hair and pom-poms. It runs on this computer; nothing is uploaded.</div>`)}
      ${p ? sectionHTML('cu-this', 'This photo', `<div class="hint">${this.existing[p.path] ? `Extracted: ${esc(baseName(this.existing[p.path]))}` : 'Not extracted yet.'}</div>${this.existing[p.path] ? `<div class="pad"><button class="btn sm" data-cut="reveal-one">Show in folder</button></div>` : ''}`) : ''}
      ${this.errors.length ? sectionHTML('cu-err', `Problems · ${this.errors.length}`, this.errors.map(e => `<div class="hint"><b>${esc(baseName(e.path))}</b><br>${esc(e.error)}</div>`).join('')) : ''}</div>`;
  },
  center() {
    const v = $('#modView'); v.dataset.mod = 'cutout';
    const p = S.byId.get(S.active);
    if (!p) { v.innerHTML = '<div class="msg">Select a photo in the filmstrip.</div>'; return; }
    const cut = this.existing[p.path]; const showCut = cut && this.view === 'cut';
    v.innerHTML = `<div class="cut-stage ${showCut ? 'checker' : ''}"><img src="${showCut ? fileUrl(cut, this.stamp || 1) : previewUrl(p.path, 2048)}" alt=""></div>
      <div class="cut-hud">${cut ? segHTML('cutView', this.view, [['orig', 'Original'], ['cut', 'Extracted']]) : '<span class="muted small">This photo hasn’t been extracted yet</span>'}<span class="hud-name">${esc(p.name)}</span></div>`;
  },
  modbar() { $('#modbar').innerHTML = `<span class="muted small">← → step through photos · press Extract to process the photos on the left</span><div class="tb-spacer"></div>`; },
  async setOut(path, custom) {
    this.outDir = path; this.outCustom = custom;
    if (S.root) { if (custom) DB.put('kv', 'cutout|' + S.root, path).catch(() => {}); else DB.del('kv', 'cutout|' + S.root).catch(() => {}); }
    this.refresh();
  },
  // Checks before a long run: low memory for Best, or a big batch.
  async run() {
    const list = scopeList(this.scope); if (!list.length || this.job) return;
    try { this.status = await api('/api/cutout/status', {}); } catch {}
    const st = this.status, m = st && st.models[this.quality], free = st && st.free_gb;
    const ask = (title, sub, buttons) => openModal(`<h3>${esc(title)}</h3><p class="muted">${sub}</p><div class="m-actions"><button class="btn" data-close>Cancel</button>${buttons}</div>`,
      card => card.addEventListener('click', e => { const b = e.target.closest('[data-go]'); if (!b) return; closeModal(); if (b.dataset.go === 'fast') this.setQuality('fast'); this.run2(list, b.dataset.go === 'more'); }));
    if (this.quality === 'best' && free != null && m && free < m.ram_gb) {
      return ask('Not much free memory', `Best needs about ${m.ram_gb} GB of free memory and this computer has ${free.toFixed(1)} GB free right now. It may run very slowly. Close other programs, or use Fast (about 3 GB).`,
        `<button class="btn" data-go="more">Run Best anyway</button><button class="btn primary" data-go="fast">Use Fast</button>`);
    }
    this.run2(list, false);
  },
  async run2(list, checked) {
    if (list.length > 5 && !checked) {
      const [lo, hi] = this.quality === 'best' ? [15, 45] : [3, 10];
      const mins = n => n < 90 ? `${Math.round(n)} seconds` : `${Math.round(n / 60)} minutes`;
      return openModal(`<h3>Extract ${list.length} photos?</h3><p class="muted">With ${this.quality === 'best' ? 'Best' : 'Fast'} that's roughly ${mins(list.length * lo)} to ${mins(list.length * hi)}, depending on the computer. The progress card shows the time left, and Cancel stops after the current photo.${this.scope === 'all' ? '<br><br>This is the whole filmstrip. To do just some photos, select them and choose Selected.' : ''}</p>
        <div class="m-actions"><button class="btn" data-close>Cancel</button><button class="btn primary" data-go>Extract ${list.length}</button></div>`,
        card => $('[data-go]', card).addEventListener('click', () => { closeModal(); this.run2(list, true); }));
    }
    let id; try { id = (await api('/api/cutout/run', { paths: list.map(p => p.path), out_dir: this.outDir, quality: this.quality })).job; } catch (e) { return toast(esc(e.message)); }
    this.job = id; this.errors = []; this.result = null; this.jobState = { id, busy: true, total: list.length, done: 0, message: 'Getting the model ready…' }; renderLeft();
    const fin = await pollJob(id, s => {
      this.jobState = s;
      for (const it of s.items) { if (it.output) this.existing[it.path] = it.output; else this.errors.push(it); }
      this.stamp = Date.now();
      if (S.module === 'cutout') { renderLeft(); if (s.items.some(it => it.path === (S.byId.get(S.active) || {}).path)) renderView(); }
    });
    this.job = null; this.jobState = null; this.refresh();
    if (fin.error) { this.render(); return toast('Extract failed: ' + esc(fin.error), 6000); }
    this.result = fin.result; this.render();
    toast(`${plural(fin.result.ok, 'photo')} extracted <button class="toast-link" onclick="reveal(${esc(JSON.stringify(fin.result.out_dir))})">Show</button>`, 5000);
  },
  key() { return false; },
};

