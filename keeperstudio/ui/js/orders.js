// Keeper Studio UI — orders. Plain scripts sharing one global scope, loaded in order by index.html.
'use strict';
/* ============================================================== Orders ==== */
// Picture-day envelopes: packages, payments, photo numbers, and the lab order.
// Prices come from prices.yaml through the server; the total shown while typing
// uses the same rules (any package unlocks the lower a la carte price).
const fmt$ = c => (c < 0 ? '-' : '') + '$' + (Math.abs(c || 0) / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const parse$ = s => { const v = parseFloat(String(s || '').replace(/[$,\s]/g, '')); return Number.isFinite(v) ? Math.max(0, Math.round(v * 100)) : 0; };
const stemOf = n => String(n || '').replace(/\.[^.]+$/, '');
const fmtDay = d => { if (!d) return ''; const t = new Date(d + 'T12:00:00'); return isNaN(t) ? d : t.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }); };
const Ord = {
  shoots: [], sid: null, d: null, cat: null, pricesPath: '', team: 'all', q: '', sort: (prefs.ordSort && prefs.ordSort.k) ? prefs.ordSort : { k: 'env', dir: 1 },
  sel: null, draft: null, view: 'orders', lab: null, crops: '', onePer: true, building: false, mer: null, merBusy: false,
  saveT: null, state: '', err: false, undo: null, last: {}, stems: null, stemsKey: '', multi: new Set(), anchor: null,
  async load() {
    await this.loadCatalog();
    try { this.shoots = (await api('/api/orders/shoots', {})).shoots; } catch { this.shoots = []; }
    const [last, one] = await Promise.all([DB.get('kv', 'orders|shoot').catch(() => null), DB.get('kv', 'orders|oneper').catch(() => null)]);
    if (one === false) this.onePer = false;
    this.sid = this.shoots.some(s => s.id === last) ? last : (this.shoots.find(s => !s.archived) || {}).id || null;
    if (this.sid) await this.refresh();
  },
  async loadCatalog() {
    try { const r = await api('/api/orders/catalog', {}); this.cat = r.catalog; this.pricesPath = r.prices_path; } catch {}
  },
  shoot() { return this.shoots.find(s => s.id === this.sid) || null; },
  products(type) { return this.cat ? this.cat.products.filter(p => p.type === type) : []; },
  prod(id) { return this.cat ? this.cat.products.find(p => p.id === id) : null; },
  async refresh() {
    if (!this.sid) { this.d = null; return; }
    try { this.d = await api('/api/orders/list', { shoot_id: this.sid }); } catch (e) { toast(esc(e.message), 5000); return; }
    const s = this.shoot(); if (s) s.n = this.d.orders.length;
    if (this.team !== 'all' && !this.d.teams.some(t => t.name === this.team)) this.team = 'all';
    this.linkFolder();
  },
  libraryLoaded() { this.stems = null; this.checkFolder(); this.linkFolder(); },
  // ---------- keeping orders safe: a copy in the shoot's photo folder, and backups ----------
  // The open folder holds a shoot's photos when most of the photos picked for its envelopes are in it.
  async linkFolder() {
    const s = this.shoot(); if (!s || !S.root || !S.photos.length || s.folder === S.root || !this.d) return;
    const stems = new Set([...this.d.orders.flatMap(o => [o.image, o.edited]), ...this.d.teams.map(t => t.image)].filter(Boolean).map(n => stemOf(n).toLowerCase()));
    if (!stems.size) return;
    let found = 0; for (const st of stems) if (this.photoFor(st)) found++;
    if (found < Math.min(3, stems.size) || found < stems.size / 2) return;
    try { await api('/api/orders/folder-link', { shoot_id: s.id, folder: S.root }); } catch { return; }
    const first = !s.folder; s.folder = S.root;
    if (first) toast(`Orders for “${esc(s.name)}” are now also saved in its photo folder`, 4000);
  },
  // A folder opened with an orders file in it: offer to bring the orders in (another PC, or newer than this one's).
  async checkFolder() {
    S.banners = S.banners.filter(b => b.id !== 'ordfile');
    if (!S.root) return renderBanners();
    let st; try { st = await api('/api/orders/folder-status', { folder: S.root }); } catch { return; }
    if (!st.file || st.state === 'same') return renderBanners();
    const f = st.file, when = f.saved ? new Date(f.saved * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '';
    S.banners.push(st.state === 'new'
      ? { id: 'ordfile', cls: 'info', text: `This folder has saved orders for “${f.name}” (${plural(f.envelopes, 'envelope')}${when ? `, saved ${when}` : ''}). Bring them into Orders?`, go: { label: 'Bring them in', fn: () => this.importFolder() } }
      : { id: 'ordfile', cls: 'info', text: `The orders saved in this folder for “${f.name}” are newer than this computer’s (${f.envelopes} envelopes vs ${st.here_envelopes}${when ? `, saved ${when}` : ''}). Use them? This computer’s orders are backed up first.`, go: { label: 'Use the newer orders', fn: () => this.importFolder() } });
    renderBanners();
  },
  async importFolder() {
    let r; try { r = await api('/api/orders/folder-import', { folder: S.root }); } catch (e) { renderBanners(); return toast(esc(e.message), 5000); }
    S.banners = S.banners.filter(b => b.id !== 'ordfile'); renderBanners();
    try { this.shoots = (await api('/api/orders/shoots', {})).shoots; } catch {}
    await this.pickShoot(r.shoot_id);
    toast(r.state === 'newer' ? 'Newer orders brought in · this computer’s were backed up first' : 'Orders brought in', 4000);
  },
  async matchingPdf() {
    const s = this.shoot(); if (!s) return;
    const dir = (await DB.get('kv', 'orders|exportdir').catch(() => null)) || S.root || '';
    const p = await pickPath('save', { initial: dir, filename: `${sanitize(s.name || 'Shoot')} - matching sheets.pdf`, types: ['PDF (*.pdf)'] }); if (!p) return;
    toast('Making matching sheets…', 2000);
    try {
      const r = await api('/api/orders/matching-pdf', { shoot_id: this.sid, path: p, folder: S.root || '' });
      DB.put('kv', 'orders|exportdir', dirName(r.path)).catch(() => {});
      toast(`Saved ${esc(baseName(r.path))}${r.photos_found ? '' : ' · open the shoot’s photo folder to get the photos on it'} <button class="toast-link" onclick="reveal(${esc(JSON.stringify(r.path))})">Show</button>`, 7000);
    } catch (e) { toast(esc(e.message), 5000); }
  },
  // ---------- Form view: an envelope drawn like the paper order form, in the app ----------
  formHTML(o) {
    const s = o.summary || {}, sh = this.shoot() || {}, $$m = c => fmt$(c || 0);
    const q = {}; for (const l of o.lines || []) q[l.product_id] = (q[l.product_id] || 0) + (+l.qty || 0);
    const pk = this.products('package'), al = this.products('alacarte'), mi = this.products('misc');
    const hasPkg = pk.some(p => q[p.id]);
    const word = k => ({ 'memory-mate': 'MEMORY MATE', wallet: 'WALLETS' })[k] || k;
    const blank = n => `<u>${n || ''}</u>`;
    const pkHTML = p => `<div class="ef-p ${q[p.id] ? 'on' : ''}"><div class="t">${blank(q[p.id])}${esc(p.label.toUpperCase())} - ${$$m(p.price)}</div><div class="it">${Object.entries(p.contents || {}).map(([k, v]) => `${v} - ${esc(word(k))}`).join('<br>')}</div></div>`;
    const lab = p => { let w = p.label.toUpperCase(); if (/^\d/.test(p.label)) w = w.replace(/X/g, 'x'); return `${p.unit} - ${esc(w)}`; };
    const col = (title, items, withp) => `<div><h5 class="${withp == null ? 'm' : ''}">${title}</h5>${items.map(p => { const n = withp == null || withp === hasPkg ? q[p.id] : 0;
      return `<div class="r ${n ? 'on' : ''}">${blank(n)}<span>${lab(p)}</span>${$$m(withp ? p.with_package : p.price)}</div>`; }).join('')}</div>`;
    const stem = o.edited || o.image || '', ph = stem ? this.photoFor(stem) : null;
    const how = s.paid_auto ? 'Picture day' : (!o.paid_method || o.paid_method === 'none') ? 'Not paid' : o.paid_method[0].toUpperCase() + o.paid_method.slice(1);
    const handed = s.handed_cents ?? s.paid_cents ?? 0;
    const pay = handed ? `Paid ${how.toLowerCase()} ${$$m(handed)}` : how;
    const tag = s.change_cents ? `Change due ${$$m(s.change_cents)}` : s.due_cents ? `Owes ${$$m(s.due_cents)}` : '';
    const half = Math.floor(pk.length / 2);
    const line = (l, v) => `<div><b>${l}</b><i>${esc(v || '')}</i></div>`;
    let day = sh.date || ''; try { if (day) day = fmtDay(day); } catch {}
    return `<div class="ef-page"><div class="ef-logo"><img src="/ui/logo.jpg" alt="Jamie Bexten Photography"></div>
      <div class="ef-strip">${ph ? `<img class="ef-ph" src="${thumbUrl(ph.path, 400)}" data-efphoto="${ph.id}" title="Click to see it bigger">` : '<span class="ef-ph none"></span>'}
        <div class="ef-who"><b>${esc(stem || 'No photo picked')}</b><span>Envelope ${esc(o.envelope || '-')} · ${esc(o.team || 'No team')} · ${esc(sh.name || '')}</span></div><span class="tb-spacer"></span>
        <div class="ef-tot">Total <b>${$$m(s.total_cents)}</b><br>${esc(pay)}${tag ? ` · <span class="ef-tag">${tag}</span>` : ''}</div></div>
      <div class="ef-head">PAYMENT DUE DAY OF SHOOT. CASH/CHECKS ACCEPTABLE. PLEASE PLACE AN <b>X</b> OR <b>QTY</b> BY CHOICE.<br>CHECKS PAYABLE TO: <b>Jamie Bexten Photography</b></div>
      <div class="ef-pk"><div>${pk.slice(0, half).map(pkHTML).join('')}</div><div>${pk.slice(half).map(pkHTML).join('')}</div></div>
      <div class="ef-mm">Memory Mate: (Team 5x7 &amp; Individual 5x7)</div>
      <div class="ef-save">Save on a la carte items with the purchase of a PACKAGE</div>
      <div class="ef-box">${col('Without PACKAGE Purchase', al, false)}${col('With PACKAGE Purchase', al, true)}${col('Miscellaneous', mi, null)}</div>
      <div class="ef-f">${line('NAME', o.athlete)}${line('PARENTS NAME', o.parent)}${line('ADDRESS / PHONE', [o.address, o.phone].filter(Boolean).join(' · '))}${line('TEAM NAME', o.team)}${line("COACH'S NAME", o.coach)}</div>
      ${o.notes || o.glasses ? `<div class="ef-notes">${o.glasses ? 'Glasses. ' : ''}${esc(o.notes || '')}</div>` : ''}
      <div class="ef-side">PICTURE DAY: ${esc(day)}</div></div>`;
  },
  openForm(id) {
    if (!this.d) return;
    const list = () => { const r = this.rows(); return r.length ? r : this.d.orders; };
    let cur = id;
    const paint = card => {
      const L = list(), i = L.findIndex(o => o.id === cur), o = L[i] || this.d.orders.find(x => x.id === cur); if (!o) return closeModal();
      card.innerHTML = `<div class="ef-bar"><button class="btn sm" data-efstep="-1" ${i > 0 ? '' : 'disabled'} title="Previous envelope (←)">←</button><span class="muted small">${i + 1} of ${L.length}</span><button class="btn sm" data-efstep="1" ${i < L.length - 1 ? '' : 'disabled'} title="Next envelope (→)">→</button>
        <span class="tb-spacer"></span><button class="btn sm" data-efedit>Edit</button><button class="btn sm" data-efpdf>PDF</button><button class="btn sm" data-close>Close</button></div><div class="ef-scroll">${this.formHTML(o)}</div>`;
    };
    const step = (card, d) => { const L = list(), i = L.findIndex(o => o.id === cur); if (L[i + d]) { cur = L[i + d].id; paint(card); } };
    let onKey = null;
    openModal('<div></div>', card => {
      card.classList.add('ef-card'); paint(card);
      card.addEventListener('click', e => {
        const t = e.target;
        if (t.closest('[data-close]')) return closeModal();
        const sb = t.closest('[data-efstep]'); if (sb) return step(card, +sb.dataset.efstep);
        if (t.closest('[data-efedit]')) { closeModal(); return this.select(cur); }
        if (t.closest('[data-efpdf]')) return this.envelopesPdf([cur]);
        const ph = t.closest('[data-efphoto]'); if (ph) { const pid = +ph.dataset.efphoto; S.active = pid; S.selected = new Set([pid]); S.anchor = pid; refreshSelection(); if (!S.fs) toggleFs(); }
      });
      onKey = e => {
        if (!card.isConnected || $('#modal').classList.contains('hidden')) { document.removeEventListener('keydown', onKey, true); return; }
        if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); e.stopPropagation(); step(card, e.key === 'ArrowRight' ? 1 : -1); }
      };
      document.addEventListener('keydown', onKey, true);
    });
  },
  // Digital envelopes: each envelope drawn like the paper order form (ids: just those envelopes)
  async envelopesPdf(ids) {
    const s = this.shoot(); if (!s) return;
    const one = ids && ids.length === 1 ? this.d.orders.find(o => o.id === ids[0]) : null;
    const dir = (await DB.get('kv', 'orders|exportdir').catch(() => null)) || S.root || '';
    const name = one ? `${sanitize(s.name || 'Shoot')} - envelope ${sanitize(one.envelope || one.id)}.pdf` : `${sanitize(s.name || 'Shoot')} - envelopes.pdf`;
    const p = await pickPath('save', { initial: dir, filename: name, types: ['PDF (*.pdf)'] }); if (!p) return;
    toast('Making envelope PDF…', 2000);
    try {
      const r = await api('/api/orders/envelopes-pdf', { shoot_id: this.sid, path: p, folder: S.root || '', ids: ids || [] });
      DB.put('kv', 'orders|exportdir', dirName(r.path)).catch(() => {});
      toast(`Saved ${esc(baseName(r.path))} (${plural(r.pages, 'page')})${r.photos_found ? '' : ' · open the shoot’s photo folder to get the photos on it'} <button class="toast-link" onclick="reveal(${esc(JSON.stringify(r.path))})">Show</button>`, 7000);
    } catch (e) { toast(esc(e.message), 5000); }
  },
  async backups() {
    let L; try { L = await api('/api/orders/backups', {}); } catch (e) { return toast(esc(e.message)); }
    const s = this.shoot();
    const when = t => t ? new Date(t * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'never';
    const kind = { daily: 'app opened', close: 'app closed', manual: 'by hand', 'before-restore': 'before a restore' };
    openModal(`<h3>Backups</h3>
      <div class="bk-grid">
        <span>This shoot’s photo folder</span><b>${s && s.folder ? `<span class="ok">✓</span> ${esc(s.folder)}` : '<span class="muted">not known yet — open the shoot’s photo folder in Library</span>'}</b>
        <span>Last backup</span><b>${when(L.last)}</b>
        <span>Second copy</span><b>${L.second ? esc(L.second) : '<span class="muted">off</span>'}${L.last_second_error ? `<br><span class="due">${esc(L.last_second_error)}</span>` : ''}</b>
      </div>
      <p class="muted small">Envelopes, payments and team photos are saved in the photo folder as “Keeper Studio orders.json”, so copying the folder brings the orders too. The whole order book is also backed up each day and each time the app closes.</p>
      <div class="btn-row"><button class="btn sm primary" data-bk="now">Back up now</button><button class="btn sm" data-bk="second">${L.second ? 'Change second copy…' : 'Keep a second copy…'}</button>${L.second ? '<button class="btn sm" data-bk="second-off">Turn second copy off</button>' : ''}</div>
      <div class="bk-list">${L.items.length ? L.items.slice(0, 40).map(b => `<div class="bk-row"><span>${when(b.time)}</span><span class="muted">${kind[b.kind] || ''}</span><span class="muted">${plural(b.shoots, 'shoot')} · ${plural(b.envelopes, 'envelope')}</span><button class="btn sm" data-bk-restore="${esc(b.name)}">Restore…</button></div>`).join('') : '<div class="muted">No backups yet.</div>'}</div>
      <div class="m-actions"><button class="btn" data-close>Done</button></div>`, card => {
      card.addEventListener('click', async e => {
        const b = e.target.closest('[data-bk]'), rs = e.target.closest('[data-bk-restore]');
        if (b && b.dataset.bk === 'now') { try { const r = await api('/api/orders/backup-now', {}); toast(r.second_error ? `Backed up · second copy failed: ${esc(r.second_error)}` : 'Backed up', 3500); } catch (er) { return toast(esc(er.message)); } this.backups(); }
        else if (b && b.dataset.bk === 'second') { const p = await pickPath('folder', { initial: L.second || '' }); if (!p) return; try { await api('/api/orders/backup-second', { folder: p }); toast('Second copy on · backed up there now', 3500); } catch (er) { return toast(esc(er.message)); } this.backups(); }
        else if (b && b.dataset.bk === 'second-off') { try { await api('/api/orders/backup-second', { folder: '' }); } catch {} this.backups(); }
        else if (rs) {
          const item = L.items.find(x => x.name === rs.dataset.bkRestore);
          confirmDialog(`Restore the backup from ${when(item && item.time)}?`, `Every shoot goes back to how it was then (${plural(item ? item.envelopes : 0, 'envelope')}). The order book as it is now is backed up first, so you can undo this from the same list.`, 'Restore', async () => {
            try { await api('/api/orders/backup-restore', { name: rs.dataset.bkRestore }); } catch (er) { return toast(esc(er.message), 5000); }
            try { this.shoots = (await api('/api/orders/shoots', {})).shoots; } catch {}
            if (this.sid && !this.shoots.some(x => x.id === this.sid)) this.sid = null;
            await this.refresh(); this.render(); toast('Backup restored', 4000);
          });
        }
      });
    });
  },
  photoFor(stem) {
    const key = `${S.gen}:${S.photos.length}`;
    if (!this.stems || this.stemsKey !== key) { this.stems = new Map(S.photos.map(p => [stemOf(p.name).toLowerCase(), p])); this.stemsKey = key; }
    return this.stems.get(stemOf(stem).toLowerCase()) || null;
  },
  // ---------- envelopes <-> filmstrip ----------
  usedStems() { return new Set((this.d ? this.d.orders : []).flatMap(o => [o.image, o.edited]).filter(Boolean).map(n => stemOf(n).toLowerCase())); },
  ordersForPhoto(p) {
    const st = stemOf(p.name).toLowerCase();
    return this.d ? this.d.orders.filter(o => [o.edited, o.image].some(n => n && stemOf(n).toLowerCase() === st)) : [];
  },
  // Put a photo in front in the filmstrip without touching the envelope.
  // Clicking a team in the left pane filters the envelopes and selects its group photo in the filmstrip.
  prepaid() { const sh = this.shoot(); return !!(sh && sh.prepaid); },
  // Envelope numbers 1…highest that no envelope has (maybe a paper envelope not typed in yet), and numbers used twice.
  envGaps() {
    const nums = (this.d ? this.d.orders : []).map(o => String(o.envelope || '').trim()).filter(x => /^\d+$/.test(x)).map(Number);
    const seen = new Map(); for (const n of nums) seen.set(n, (seen.get(n) || 0) + 1);
    const hi = nums.length ? Math.max(...nums) : 0, missing = [];
    for (let n = 1; n <= hi && missing.length < 200; n++) if (!seen.has(n)) missing.push(n);
    return { missing, dup: [...seen].filter(([, c]) => c > 1).map(([n]) => n).sort((a, b) => a - b) };
  },
  envGapsHTML() {
    const { missing, dup } = this.envGaps(), list = (ns, cls) => ns.slice(0, 8).map(n => `<button class="linkish ${cls}" data-ord="env-missing" data-n="${n}" title="${cls === 'dup' ? `Two envelopes are #${n}` : `Start envelope #${n}`}">${n}</button>`).join(', ') + (ns.length > 8 ? ` +${ns.length - 8}` : '');
    return (missing.length ? `<span title="Numbers between 1 and the highest envelope that no envelope has — maybe a paper envelope not typed in yet, or one you deleted. Click one to start it.">Missing #</span><b class="env-gaps">${list(missing, 'miss')}</b>` : '')
      + (dup.length ? `<span title="Two or more envelopes share these numbers">Used twice #</span><b class="env-gaps due">${dup.slice(0, 8).map(n => `<button class="linkish dup" data-ord="env-dup" data-n="${n}">${n}</button>`).join(', ')}</b>` : '');
  },
  // Names are only typed for envelopes that owe or paid short: those need a name to chase.
  owesNoName() { return (this.d ? this.d.orders : []).filter(o => !String(o.athlete || '').trim() && o.summary && (o.summary.due_cents > 0 || o.summary.short_cents > 0)); },
  noNameHTML() {
    const l = this.owesNoName(); if (!l.length) return '';
    const key = o => String(o.envelope || '').trim() || '?';
    return `<span title="These envelopes owe money or paid short but have no name — type who it is so you know who to ask">Owes, no name #</span><b class="env-gaps due">${l.slice(0, 8).map(o => `<button class="linkish" data-ord="env-noname" data-id="${o.id}">${esc(key(o))}</button>`).join(', ')}${l.length > 8 ? ` +${l.length - 8}` : ''}</b>`;
  },
  draftOwes(d = this.draft) {
    if (!d) return false;
    const t = this.price(d.lines).total; if (!t) return false;
    if (this.prepaid() && !d.paid_cents && !d.paid_method) return false;
    return (d.accepted_cents || 0) > 0 || t - (d.paid_cents || 0) > 0;
  },
  // After marking an envelope unpaid or short: put the cursor in the name box, if it's empty.
  askName() {
    const d = this.draft; if (!d || String(d.athlete || '').trim() || !this.draftOwes(d)) return;
    setTimeout(() => { const i = $('#right [data-of="athlete"]'); if (!i) return; i.classList.add('ask'); i.placeholder = 'Who owes this?'; i.focus(); }, 30);
  },
  // How families pay. Card only shows on an old envelope that already says Card.
  payChoices(cur) {
    const ways = [['cash', 'Cash'], ['check', 'Check'], ['venmo', 'Venmo'], ...(cur === 'card' ? [['card', 'Card']] : [])];
    return this.prepaid() ? [['', 'Picture day'], ...ways, ['none', 'Unpaid']] : [['', 'Unpaid'], ...ways];
  },
  async bulkPay(method) {
    const ids = [...this.multi]; if (!ids.length) return;
    try {
      const r = await api('/api/orders/bulk-pay', { shoot_id: this.sid, ids, method });
      await this.refresh(); this.render();
      const label = (this.payChoices().find(x => x[0] === method) || [, method])[1];
      toast(`${plural(r.changed, 'envelope')} marked ${method === 'none' || (!method && !this.prepaid()) ? 'unpaid' : method ? `paid by ${esc(label)}` : 'paid on picture day'}`, 4000);
    } catch (e) { toast(esc(e.message), 5000); }
  },
  // ---------- floating preview ----------
  // A movable, resizable photo of the open envelope (or the picked team's group photo).
  pvToggle() {
    const pv = prefs.ordPv = { x: null, y: null, w: 380, h: 500, ...(prefs.ordPv || {}) };
    pv.open = !pv.open; savePrefs(); this.pvPaint(); this.modbar();
  },
  pvPaint() {
    let el = $('#ordPv');
    const pv = prefs.ordPv;
    if (S.module !== 'orders' || !pv || !pv.open || !S.photos.length) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement('div'); el.id = 'ordPv'; el.className = 'ord-pv';
      el.innerHTML = `<div class="pv-head"><span class="pv-t"></span><button class="pv-x" title="Close (V)">✕</button></div><div class="pv-img"><img alt=""><div class="pv-none"></div><div class="pv-lens"></div></div><div class="pv-sub"></div><div class="pv-grip" title="Drag to resize"></div>`;
      document.body.appendChild(el);
      this.pvWire(el);
    }
    const W = window.innerWidth, H = window.innerHeight;
    pv.w = clamp(pv.w || 380, 220, W - 20); pv.h = clamp(pv.h || 500, 220, H - 20);
    // first time: low in the middle pane, clear of its header controls
    if (pv.x == null) pv.x = W - pv.w - 300;
    if (pv.y == null) pv.y = Math.max(60, H - pv.h - 190);
    pv.x = clamp(pv.x, 0, W - 80); pv.y = clamp(pv.y, 0, H - 40);
    Object.assign(el.style, { left: pv.x + 'px', top: pv.y + 'px', width: pv.w + 'px', height: pv.h + 'px' });
    // what to show
    const d = this.draft, o = d || (this.sel != null && this.d && this.d.orders.find(x => x.id === this.sel));
    let stem = '', title = '', sub = '', img = '', note = '';
    if (o) {
      stem = o.edited || o.image || '';
      title = o.athlete || 'New envelope';
      sub = [o.envelope ? `Env ${o.envelope}` : '', o.team].filter(Boolean).join(' · ');
      img = stem ? stemOf(stem) : ''; note = stem ? (o.edited ? 'retouched' : '') : 'No photo yet';
    } else if (this.team && this.team !== 'all' && this.d) {
      const t = this.d.teams.find(x => x.name === this.team); stem = (t && t.image) || '';
      title = `${this.team} team`; sub = 'Group photo'; img = stem ? stemOf(stem) : ''; note = stem ? '' : 'No group photo yet';
    } else { title = 'Preview'; sub = 'Open an envelope or pick a team'; }
    const p = stem ? this.photoFor(stem) : null;
    $('.pv-t', el).textContent = title;
    $('.pv-sub', el).innerHTML = `<span class="pv-num">${esc(img)}</span>${note ? `<span class="pv-note">${esc(note)}</span>` : ''}<span class="pv-who">${esc(sub)}</span>`;
    const im = $('img', el), none = $('.pv-none', el);
    if (p) { const u = previewUrl(p.path, 1600); if (im.dataset.u !== u) { im.dataset.u = u; im.src = u; } im.hidden = false; none.textContent = ''; el.dataset.p = p.id; }
    else { im.hidden = true; im.removeAttribute('src'); im.dataset.u = ''; none.textContent = stem ? `${stemOf(stem)} isn't in the open folder` : (o ? 'No photo picked for this envelope' : ''); el.dataset.p = ''; }
  },
  pvWire(el) {
    const save = () => savePrefs();
    const drag = (e, mode) => {
      e.preventDefault(); const pv = prefs.ordPv, sx = e.clientX, sy = e.clientY, o = { ...pv };
      const mv = ev => { if (mode === 'move') { pv.x = o.x + ev.clientX - sx; pv.y = o.y + ev.clientY - sy; } else { pv.w = o.w + ev.clientX - sx; pv.h = o.h + ev.clientY - sy; } this.pvPaint(); };
      const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); el.classList.remove('moving'); save(); };
      el.classList.add('moving'); window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    };
    $('.pv-head', el).addEventListener('pointerdown', e => { if (!e.target.closest('.pv-x')) drag(e, 'move'); });
    $('.pv-grip', el).addEventListener('pointerdown', e => drag(e, 'size'));
    $('.pv-x', el).addEventListener('click', () => this.pvToggle());
    // hover: a magnifier over the photo
    const box = $('.pv-img', el), lens = $('.pv-lens', el), img = $('img', el);
    box.addEventListener('pointermove', e => {
      if (img.hidden || !img.naturalWidth) return;
      const b = box.getBoundingClientRect(), r = img.getBoundingClientRect();
      const fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
      if (fx < 0 || fx > 1 || fy < 0 || fy > 1) { lens.style.display = 'none'; return; }
      const Z = 2.6, L = 170;
      Object.assign(lens.style, { display: 'block', left: (e.clientX - b.left - L / 2) + 'px', top: (e.clientY - b.top - L / 2) + 'px', width: L + 'px', height: L + 'px',
        backgroundImage: `url("${img.src}")`, backgroundSize: `${r.width * Z}px ${r.height * Z}px`, backgroundPosition: `${-(fx * r.width * Z - L / 2)}px ${-(fy * r.height * Z - L / 2)}px` });
    });
    box.addEventListener('pointerleave', () => { lens.style.display = 'none'; });
    box.addEventListener('dblclick', () => { const id = +el.dataset.p; if (id) { S.active = id; S.selected = new Set([id]); S.anchor = id; refreshSelection(); ensureVisible(); if (!S.fs) toggleFs(); } });
  },
  // ---------- team order ----------
  async setTeamOrder(names) {
    try { await api('/api/orders/team-order', { shoot_id: this.sid, teams: names }); } catch (e) { return toast(esc(e.message)); }
    await this.refresh(); this.render();
  },
  moveTeam(name, d) {
    const ns = this.d.teams.map(t => t.name), i = ns.indexOf(name), j = i + d;
    if (i < 0 || j < 0 || j >= ns.length) return;
    [ns[i], ns[j]] = [ns[j], ns[i]]; this.setTeamOrder(ns);
  },
  // ---------- Team 5x7s for the school ----------
  async openSchool() {
    if (!this.sid) return;
    if (!this.crops) this.crops = (await DB.get('kv', 'orders|crops|' + this.sid).catch(() => null)) || Crop.outDir || '';
    const load = () => api('/api/orders/school', { shoot_id: this.sid, crops_dir: this.crops });
    let R; try { R = await load(); } catch (e) { return toast(esc(e.message)); }
    const st = { to: R.school.email || '', subject: `${R.shoot} - team photos`, body: '', gmailOpened: false, busy: false, setup: !R.mail.has_password && false };
    const mb = n => (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + ' MB';
    const bodyFor = n => `Hi,\n\nAttached are the 5x7 team photos for ${R.shoot} (${plural(n, 'team')}).\n\nThank you,\nJamie Bexten Photography`;
    const paint = card => {
      const ok = R.rows.filter(r => r.status === 'ok').length, todo = R.rows.filter(r => r.status === 'todo').length, skipped = R.rows.filter(r => r.status === 'skip').length;
      // the same group photo on two teams is almost always a typo'd photo number
      const byImg = {}; for (const r of R.rows) if (r.image && r.status !== 'skip') (byImg[r.image.toLowerCase()] = byImg[r.image.toLowerCase()] || []).push(r.name);
      const dupes = Object.entries(byImg).filter(([, v]) => v.length > 1), dupNames = new Set(dupes.flatMap(([, v]) => v));
      if (!st.bodyEdited) st.body = bodyFor(ok);
      const row = r => `<div class="sd-row ${r.status}"><span class="nm">${esc(r.name)}</span>${r.status === 'ok' ? `<span class="ok" title="${esc(r.file)}">✓</span>${R.changed.includes(r.name) ? '<span class="chg">changed since sent</span>' : ''}${dupNames.has(r.name) ? `<span class="chg" title="Another team has the same group photo">same photo as ${esc(dupes.find(([, v]) => v.includes(r.name))[1].filter(n => n !== r.name).join(', '))}</span>` : ''}`

        : r.status === 'skip' ? `<span class="muted small">skipped this year</span><button class="btn sm" data-sdskip="${esc(r.name)}">Include</button>`
        : `<span class="warn">${esc(r.why)}</span>${r.why === 'No group photo picked' ? `<button class="btn sm" data-sdskip="${esc(r.name)}">Skip this year</button>` : ''}`}</div>`;
      const sent = R.school.sent;
      card.innerHTML = `<h3 class="tl-h">Team 5×7s for the school <span class="muted small">${esc(R.shoot)}</span></h3>
        <p class="muted small tl-sub">One 5×7 (300 dpi) of every team on the team list, named by team, zipped and emailed.${sent ? ` Last sent ${esc(fmtDay(new Date(sent.at * 1000).toISOString().slice(0, 10)))} to ${esc(sent.to)} · ${plural((sent.teams || []).length, 'team')}.` : ''}</p>
        <div class="pathrow sd-crops"><span class="path ${this.crops ? '' : 'bad'}" title="${esc(this.crops)}">${esc(this.crops || 'Choose the folder Crop exported the prints to')}</span><button class="btn sm" data-sdcrops>Crops folder…</button></div>
        <div class="pathrow sd-crops"><span class="path" title="Where Save zip and Open in Gmail put the zip">${st.zipDir ? 'Zip goes in ' + esc(st.zipDir) : 'Zip folder: asked the first time you save'}</span><button class="btn sm" data-sdzipdir>Zip folder…</button></div>
        <div class="sd-count"><b>${plural(R.rows.length, 'team')}</b> on the team list · <b class="${ok === R.rows.length - skipped && !todo ? 'okc' : ''}">${ok} in the email</b>${skipped ? ` · ${skipped} skipped` : ''}${todo ? ` · <span class="warn">${todo} not ready</span>` : ''} <button class="sd-link" data-ord="team-list" title="Every team on the shoot's list">Team list…</button></div>
        <div class="sd-list">${R.rows.map(row).join('') || '<div class="hint" style="padding:10px">No teams yet.</div>'}</div>
        ${dupes.length ? `<div class="sd-warn">${dupes.map(([img, v]) => `${esc(v.length > 2 ? v.slice(0, -1).join(', ') + ' and ' + v[v.length - 1] : v.join(' and '))} have the same group photo (${esc(img.toUpperCase())})`).join('; ')} - check the photo number on the team (▣ in the Teams list).</div>` : ''}
        ${todo ? `<div class="sd-warn">${plural(todo, 'team')} ${todo === 1 ? "isn't" : "aren't"} ready - pick the group photo or crop the 5×7, or skip a team that wasn't photographed.</div>` : ''}
        <div class="sd-mail"><label>To<input data-sdf="to" value="${esc(st.to)}" placeholder="the school's email" spellcheck="false"></label><label>Subject<input data-sdf="subject" value="${esc(st.subject)}"></label>
          <label class="wide">Message<textarea data-sdf="body" rows="6">${esc(st.body)}</textarea></label></div>
        ${st.setup ? `<div class="sd-setup"><b>Send from Gmail</b><p class="muted small">Google needs an <b>app password</b> for this, not your Gmail password: Google Account → Security → 2-Step Verification (must be on) → App passwords. Make one called "Keeper Studio" and paste the 16-letter code here. It's kept with Windows' own password protection, and you can delete it in Google any time.</p>
          <div class="sd-mail"><label>Your Gmail address<input data-sdm="from" value="${esc(R.mail.from)}" placeholder="you@gmail.com" spellcheck="false"></label><label>App password${R.mail.has_password ? ' <i>(saved - type to replace)</i>' : ''}<input data-sdm="pw" type="password" placeholder="xxxx xxxx xxxx xxxx" autocomplete="off"></label></div>
          <div class="sd-setup-btns"><button class="btn sm" data-sdmsave>Save & test</button>${R.mail.has_password ? '<button class="btn sm" data-sdmforget>Forget the app password</button>' : ''}<button class="btn sm" data-sdmclose>Done</button></div></div>` : ''}
        <div class="sd-foot"><span class="muted small">${ok ? `Zip about ${mb(R.estimate)}${R.estimate > R.limit ? ' (made a little smaller to fit Gmail when sent)' : ''} · ` : ''}${R.mail.has_password ? `sends from ${esc(R.mail.from)} · <button class="sd-link" data-sdsetup>change</button>` : '<button class="sd-link" data-sdsetup>Set up sending from Gmail…</button>'}</span><span class="tb-spacer"></span>
          <button class="btn" data-close>Close</button><button class="btn" data-sdzip ${ok ? '' : 'disabled'} title="Save the zip to a folder">Save zip…</button>
          ${st.gmailOpened ? `<button class="btn primary" data-sdmark title="Mark it sent once you've sent the Gmail message">I sent it</button>` : `<button class="btn" data-sdgmail ${ok && !todo ? '' : 'disabled'} title="Gmail opens with the message filled in; drag the zip in from the folder that opens">Open in Gmail</button>`}
          <button class="btn primary" data-sdsend ${ok && !todo && R.mail.has_password && !st.busy ? '' : 'disabled'} title="${R.mail.has_password ? 'Send it from your Gmail now' : 'Set up sending from Gmail first'}">${st.busy ? 'Sending…' : st.confirm ? `Click again to send ${plural(ok, 'team')} to ${esc(st.to.trim())}` : 'Send to school'}</button></div>`;
    };
    const read = card => { for (const el of $$('[data-sdf]', card)) { if (el.dataset.sdf === 'body' && el.value !== st.body) st.bodyEdited = true; st[el.dataset.sdf] = el.value; } };
    const refresh = async card => { try { R = await load(); } catch (e) { return toast(esc(e.message)); } paint(card); };
    const payload = () => ({ shoot_id: this.sid, crops_dir: this.crops, to: st.to.trim(), subject: st.subject, body: st.body });
    st.zipDir = (await DB.get('kv', 'school|zipdir|' + this.sid).catch(() => null)) || '';
    const zipDir = async (ask) => {
      if (st.zipDir && !ask) return st.zipDir;
      const p = await pickPath('folder', { initial: st.zipDir || dirName(this.crops) || S.root || '' });
      if (p) { st.zipDir = p; DB.put('kv', 'school|zipdir|' + this.sid, p).catch(() => {}); }
      return p;
    };
    openModal('<div></div>', card => {
      card.classList.add('sd-card'); paint(card);
      card.addEventListener('change', e => { if (e.target.matches('[data-sdf=to]')) api('/api/orders/school-set', { shoot_id: this.sid, email: e.target.value.trim() }).catch(() => {}); });
      card.addEventListener('click', async e => {
        const t = e.target;
        if (t.closest('[data-close]')) return closeModal();  // the window is redrawn, so Close is wired here
        read(card);
        if (st.confirm && !t.closest('[data-sdsend]')) { st.confirm = false; paint(card); }
        const sk = t.closest('[data-sdskip]');
        if (sk) { const n = sk.dataset.sdskip, skip = new Set(R.school.skip); skip.has(n) ? skip.delete(n) : skip.add(n); await api('/api/orders/school-set', { shoot_id: this.sid, skip: [...skip] }); return refresh(card); }
        if (t.closest('[data-sdcrops]')) { const p = await pickPath('folder', { initial: this.crops || Crop.outDir || S.root || '' }); if (p) { this.crops = p; DB.put('kv', 'orders|crops|' + this.sid, p).catch(() => {}); return refresh(card); } return; }
        if (t.closest('[data-sdsetup]')) { st.setup = true; return paint(card); }
        if (t.closest('[data-sdzipdir]')) { await zipDir(true); return paint(card); }
        if (t.closest('[data-sdmclose]')) { st.setup = false; return paint(card); }
        if (t.closest('[data-sdmforget]')) { R.mail = await api('/api/mail-settings', { set: true, forget: true }); return paint(card); }
        if (t.closest('[data-sdmsave]')) {
          const from = $('[data-sdm=from]', card).value.trim(), pw = $('[data-sdm=pw]', card).value;
          try { R.mail = await api('/api/mail-settings', { set: true, from, password: pw }); await api('/api/mail-test', {}); toast('Gmail is set up - test sign-in worked'); st.setup = false; }
          catch (err) { toast(esc(String(err.message).replace(/^\w+Error:\s*/, '')), 6000); }
          return paint(card);
        }
        if (t.closest('[data-sdzip]')) {
          const p = await zipDir(false); if (!p) return;
          paint(card);
          try { const z = await api('/api/orders/school-zip', { ...payload(), folder: p }); toast(`Saved ${plural(z.teams, 'team')} (${mb(z.bytes)}) <button class="toast-link" onclick="reveal(${esc(JSON.stringify(z.path))})">Show</button>`, 6000); }
          catch (err) { toast(esc(String(err.message).replace(/^\w+Error:\s*/, '')), 5000); }
          return;
        }
        if (t.closest('[data-sdgmail]')) {
          if (!/@/.test(st.to)) return toast("Type the school's email first", 3000);
          const p = await zipDir(false); if (!p) return;
          try { const z = await api('/api/orders/school-gmail', { ...payload(), folder: p }); reveal(z.path); st.gmailOpened = true; paint(card);
            toast(`Gmail is open with the message filled in - drag “${esc(z.path.split(/[\\/]/).pop())}” from the folder into it, send, then press <b>I sent it</b>.`, 9000); }
          catch (err) { toast(esc(String(err.message).replace(/^\w+Error:\s*/, '')), 5000); }
          return;
        }
        if (t.closest('[data-sdmark]')) { await api('/api/orders/school-mark-sent', payload()); toast('Marked sent'); await this.refresh(); this.render(); return refresh(card); }
        if (t.closest('[data-sdsend]')) {
          if (!/@/.test(st.to)) return toast("Type the school's email first", 3000);
          const ok = R.rows.filter(r => r.status === 'ok').length;
          if (!st.confirm) { st.confirm = true; paint(card); return; }  // second click sends
          st.confirm = false; st.busy = true; paint(card);
          try { const r = await api('/api/orders/school-send', payload()); toast(`Sent to ${esc(r.sent.to)} - ${plural(r.zip.teams, 'team')} (${mb(r.zip.bytes)}). It's in your Gmail Sent folder.`, 6000); await this.refresh(); this.render(); }
          catch (err) { toast(esc(String(err.message).replace(/^\w+Error:\s*/, '')), 7000); }
          st.busy = false; return refresh(card);
        }
      });
    });
  },
  // ---------- Team list window ----------
  async openTeamList() {
    if (!this.sid) return;
    let R; try { R = await api('/api/orders/team-list', { shoot_id: this.sid }); } catch (e) { return toast(esc(e.message)); }
    const s = this.shoot(), rows = R.teams.map(t => ({ name: t.name, coach: t.coach || '', was: t.name, count: t.count }));
    const rowHTML = (t, i) => `<tr class="${t.count ? '' : 'unused'}" draggable="true" data-tl="${i}"><td class="h" title="Drag to reorder">⋮⋮</td>
      <td><input data-tlf="name" value="${esc(t.name)}" spellcheck="false" placeholder="Team name"></td><td><input data-tlf="coach" value="${esc(t.coach)}" spellcheck="false" list="ordCoaches" placeholder="Coach"></td>
      <td class="n">${t.count || '—'}</td><td class="x">${t.count ? '' : `<button data-tlx="${i}" title="Take ${esc(t.name || 'this team')} off the list">✕</button>`}</td></tr>`;
    const paint = card => { $('tbody', card).innerHTML = rows.map(rowHTML).join('') + '<tr class="add"><td></td><td colspan="4"><button class="btn sm" data-tladd>+ Add team</button></td></tr>'; };
    const read = card => $$('tr[data-tl]', card).forEach(tr => { const r = rows[+tr.dataset.tl]; r.name = $('[data-tlf=name]', tr).value; r.coach = $('[data-tlf=coach]', tr).value; });
    openModal(`<h3 class="tl-h">Team list <span class="muted small">${esc(s ? s.name : '')}</span></h3>
      <p class="muted small tl-sub">The order here numbers the envelope files (01-, 02-, …). Renaming a team renames it on its envelopes too.</p>
      <div class="tl-scroll"><table class="tl-t"><thead><tr><th></th><th>Team</th><th>Coach</th><th class="n">Envelopes</th><th></th></tr></thead><tbody></tbody></table></div>
      <div class="tl-foot"><span class="muted small">${R.next ? `${esc(R.next)} will start with this list.` : 'The next shoot of this name will start with this list.'}</span><span class="tb-spacer"></span><button class="btn" data-close>Cancel</button><button class="btn primary" data-tlsave>Save</button></div>`, card => {
      card.classList.add('tl-card'); paint(card);
      let drag = null;
      card.addEventListener('click', async e => {
        const x = e.target.closest('[data-tlx]'); if (x) { read(card); rows.splice(+x.dataset.tlx, 1); paint(card); return; }
        if (e.target.closest('[data-tladd]')) { read(card); rows.push({ name: '', coach: '', was: '', count: 0 }); paint(card); const ins = $$('[data-tlf=name]', card); ins[ins.length - 1].focus(); return; }
        if (e.target.closest('[data-tlsave]')) {
          read(card);
          try { await api('/api/orders/team-list-save', { shoot_id: this.sid, teams: rows.map(r => ({ name: r.name, coach: r.coach, was: r.was })) }); }
          catch (err) { return toast(esc(String(err.message).replace(/^\w+Error:\s*/, '')), 4000); }
          closeModal(); if (this.team !== 'all' && !rows.some(r => r.name.trim() === this.team)) this.team = 'all';
          await this.refresh(); this.render(); toast('Team list saved');
        }
      });
      card.addEventListener('dragstart', e => { const tr = e.target.closest('tr[data-tl]'); if (!tr || e.target.matches('input')) return; read(card); drag = +tr.dataset.tl; tr.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; });
      card.addEventListener('dragover', e => { if (drag == null) return; const tr = e.target.closest('tr[data-tl]'); if (!tr) return; e.preventDefault(); $$('tr.drop-above', card).forEach(t => t.classList.remove('drop-above')); tr.classList.add('drop-above'); });
      card.addEventListener('drop', e => { if (drag == null) return; e.preventDefault(); const tr = e.target.closest('tr[data-tl]'); const to = tr ? +tr.dataset.tl : rows.length; const [m] = rows.splice(drag, 1); rows.splice(to > drag ? to - 1 : to, 0, m); drag = null; paint(card); });
      card.addEventListener('dragend', () => { drag = null; $$('tr.dragging,tr.drop-above', card).forEach(t => t.classList.remove('dragging', 'drop-above')); });
    });
  },
  async dropPlanned(name) {
    if (!name) return;
    try { await api('/api/orders/team-drop', { shoot_id: this.sid, team: name }); } catch (e) { return toast(esc(String(e.message).replace(/^\w+Error:\s*/, '')), 3500); }
    if (this.team === name) this.team = 'all';
    await this.refresh(); this.render(); toast(`${esc(name)} taken off this shoot's team list`);
  },
  teamSortAZ() { this.setTeamOrder(this.d.teams.map(t => t.name).sort(collator.compare)); },
  dropTeam(name, before) {
    const ns = this.d.teams.map(t => t.name).filter(t => t !== name);
    const k = before == null ? ns.length : ns.indexOf(before);
    ns.splice(k < 0 ? ns.length : k, 0, name); this.setTeamOrder(ns);
  },
  // Analysis: up/down walks the Teams list on the left (All teams first).
  stepTeam(d) {
    const ids = [...new Set($$('#left [data-oteam]').map(x => x.dataset.oteam))];
    if (!ids.length) return;
    const i = ids.indexOf(this.team), j = Math.max(0, Math.min(ids.length - 1, (i < 0 ? 0 : i + d)));
    if (j === i) return;
    if (this.anScope === 'all') this.anScope = 'shoot';
    this.pickTeam(ids[j]);
    const el = $(`#left [data-oteam="${CSS.escape(ids[j])}"]`); if (el) el.scrollIntoView({ block: 'nearest' });
  },
  pickTeam(name) {
    this.team = name; renderLeft(); renderView(); this.pvPaint();
    const t = name !== 'all' && this.d ? this.d.teams.find(x => x.name === name) : null;
    if (!t || !t.image || this.showPhoto(t.image)) return;
    const p = this.photoFor(t.image);
    if (p) toast(`${esc(name)}’s group photo ${esc(t.image)} is hidden by the filmstrip filter${S.filter && S.filter.flag ? ' (picks only is on)' : ''}.`, 3500);
  },
  showPhoto(stem) {
    const p = stem ? this.photoFor(stem) : null; if (!p || !S.viewIndex.has(p.id)) return false;
    S.active = p.id; S.selected = new Set([p.id]); S.anchor = p.id;
    renderFilm(); renderFilmBar(); ensureVisible(); return true;
  },
  // The photo for a new envelope: the next one in the filmstrip after the envelope
  // just finished that no envelope uses yet. With the filmstrip showing only
  // picks (one per kid, in shooting order) that is the next kid.
  nextPhoto(after) {
    if (!S.view.length) return null;
    const used = this.usedStems(), ap = after ? this.photoFor(after) : null;
    const i = ap && S.viewIndex.has(ap.id) ? S.viewIndex.get(ap.id) + 1 : (S.active != null && S.viewIndex.has(S.active) ? S.viewIndex.get(S.active) : 0);
    const free = p => !used.has(stemOf(p.name).toLowerCase()) && !getMeta(p.key).team;
    // after the last kid, wrap round to any earlier photo still without an envelope
    return S.view.slice(i).find(free) || S.view.slice(0, i).find(free) || null;
  },
  async photoClicked(id) {
    if (S.module === 'orders' && this.pickingTeam != null) return this.finishTeamPick(id);
    if (S.module !== 'orders' || this.view !== 'orders' || this.multi.size > 1) return;
    const p = S.byId.get(id); if (!p) return;
    const d = this.draft, st = stemOf(p.name);
    // An envelope still waiting for its photo (a new one, or one showing the
    // auto-picked photo) takes the clicked photo, even one another envelope
    // already uses: the same kid can have two envelopes.
    if (d && (this.autoPhoto || !(d.image || d.edited)) && !getMeta(p.key).team) {
      if (stemOf(d.image || '').toLowerCase() !== st.toLowerCase()) { d.image = st; d.edited = ''; this.changed(true); }
      return;
    }
    // Otherwise open the envelope that uses this photo; with two, each click goes to the next.
    const os = this.ordersForPhoto(p); if (!os.length) return;
    const i = os.findIndex(o => o.id === this.sel);
    const o = os[(i + 1) % os.length];
    if (o.id !== this.sel) this.select(o.id);
  },
  picksOnly() { return S.filter.flag === 'pick'; },
  setPicksOnly(on) { S.filter = { ...S.filter, flag: on ? 'pick' : 'any' }; syncFilterBar(); afterFilter(); this.modbar(); },
  // '5371' -> the photo in the open folder ending in 5371, else the folder's own prefix (IMG_5371)
  matches(digits) {
    if (!digits) return [];
    const re = new RegExp(`(^|\\D)${digits}(\\D|$)`);
    return [...new Set(S.photos.map(p => stemOf(p.name)).filter(n => re.test(n)))].sort(collator.compare).slice(0, 12);
  },
  normImage(v) {
    v = String(v || '').trim();
    if (/^\d+$/.test(v)) {
      const m = this.matches(v); if (m.length === 1) return m[0];
      const first = S.photos.length ? stemOf(S.photos[0].name) : ''; const pre = (first.match(/^\D+/) || ['IMG_'])[0];
      return pre + v;
    }
    return v.replace(/\.(jpe?g|png|tiff?|heic|hif|cr[23]|dng)$/i, '');
  },
  enter() { this.render(); if (this.view === 'lab') this.loadLab(); this.loadCatalog().then(() => { if (S.module === 'orders') renderRight(); }); },
  render() { renderView(); renderLeft(); renderRight(); this.modbar(); },
  rows() {
    if (!this.d) return [];
    let r = this.d.orders;
    if (this.team !== 'all') r = r.filter(o => (o.team || '') === this.team);
    const q = this.q.trim().toLowerCase();
    if (q) r = r.filter(o => [o.envelope, o.athlete, o.team, o.coach, o.parent, o.phone, o.image, o.edited, o.frames, o.summary.packages, o.notes].join(' ').toLowerCase().includes(q));
    const { k, dir } = this.sort;
    const teamIx = new Map((this.d.teams || []).map((t, n) => [t.name, n]));
    const teamRank = o => (o.team ? (teamIx.has(o.team) ? teamIx.get(o.team) : 9e8) : 1e9);
    const photoNum = o => { const m = String(o.edited || o.image || '').match(/(\d+)(?!.*\d)/); return m ? +m[1] : 1e12; };
    const val = o => k === 'env' ? (/^\d+$/.test(o.envelope) ? +o.envelope : 1e9) : k === 'total' ? o.summary.total_cents : k === 'due' ? o.summary.due_cents : k === 'lab' ? o.summary.lab_cents : k === 'profit' ? o.summary.keep_cents : k === 'ppct' ? (o.summary.total_cents ? o.summary.keep_cents / o.summary.total_cents : -1e9) : k === 'team' ? teamRank(o) : k === 'image' ? photoNum(o) : k === 'glasses' ? (o.glasses ? 0 : 1) : String(o[k] || '').toLowerCase();
    const envN = o => (/^\d+$/.test(String(o.envelope).trim()) ? +o.envelope : 1e9);
    return r.slice().sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * dir || envN(a) - envN(b) || collator.compare(a.athlete, b.athlete) || a.id - b.id; });
  },
  // ---------- pricing while typing (the server prices what is saved) ----------
  price(lines) {
    const live = (lines || []).filter(l => l.qty > 0 && this.prod(l.product_id));
    const hasPkg = live.some(l => this.prod(l.product_id).type === 'package');
    let total = 0, savings = 0;
    for (const l of live) { const p = this.prod(l.product_id), u = this.unit(p, hasPkg); total += u * l.qty; savings += (p.price - u) * l.qty; }
    return { hasPkg, total, savings };
  },
  unit(p, hasPkg) { return p.type === 'alacarte' && hasPkg ? p.with_package : p.price; },
  qty(pid) { const l = ((this.draft && this.draft.lines) || []).find(l => l.product_id === pid); return l ? l.qty : 0; },
  setQty(pid, q) {
    const d = this.draft; if (!d) return;
    const before = this.price(d.lines).total;
    const order = (this.cat ? this.cat.products : []).map(p => p.id);
    d.lines = d.lines.filter(l => l.product_id !== pid);
    q = clamp(q, 0, 20); if (q) d.lines.push({ product_id: pid, qty: q });
    d.lines.sort((a, b) => order.indexOf(a.product_id) - order.indexOf(b.product_id));
    // paid in full stays paid in full when the order changes
    if (d.paid_method && d.paid_cents === before) d.paid_cents = this.price(d.lines).total;
    this.changed(true);
  },
  togglePkg(letter, add) {
    const p = this.products('package').find(p => p.letter.toLowerCase() === letter.toLowerCase()); if (!p || !this.draft) return false;
    const q = this.qty(p.id); this.setQty(p.id, add ? q + 1 : q ? 0 : 1); return true;
  },
  // ---------- selecting, new, saving, deleting ----------
  async flush() { while (this.saveT || this._saving) { if (this.saveT) await this.save(); else await this._saving; } },
  async select(id) {
    await this.flush();
    const o = this.d && this.d.orders.find(o => o.id === id); if (!o) return;
    this.multi = new Set([id]); this.anchor = id; this.autoPhoto = false;
    this.sel = id; this.draft = JSON.parse(JSON.stringify(o)); this.state = ''; this.err = false;
    this.showPhoto(o.edited || o.image);
    this.paintRows(); renderRight();
    this.revealRow(id);
  },
  // Scroll the envelope list so a row shows clear of the sticky header and totals row.
  revealRow(id) {
    const tr = $(`#modView tr[data-oid="${id}"]`); if (!tr) return;
    let box = tr.parentElement; while (box && box !== document.body && !(box.scrollHeight > box.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(box).overflowY))) box = box.parentElement;
    if (!box || box === document.body) { tr.scrollIntoView({ block: 'center' }); return; }
    const tbl = tr.closest('table'), head = tbl && tbl.tHead ? tbl.tHead.offsetHeight : 0, foot = tbl && tbl.tFoot ? tbl.tFoot.offsetHeight : 0;
    const b = box.getBoundingClientRect(), r = tr.getBoundingClientRect();
    if (r.top < b.top + head + 2 || r.bottom > b.bottom - foot - 2) box.scrollTop += (r.top + r.height / 2) - (b.top + head + (b.height - head - foot) / 2);
  },
  async newOrder(env) {
    if (!this.sid) return this.editShoot(true);
    // A new envelope with nothing typed is already open: point at it instead of starting another.
    const d0 = this.draft;
    if (this.sel === 'new' && d0 && !d0.id && !d0.athlete.trim() && !d0.lines.length) {
      if (env != null) { d0.envelope = String(env); renderRight(); }
      if (this.view !== 'orders') this.setView('orders');
      this._flashNew = true; this.paintRows();
      setTimeout(() => { const i = $('#right [data-of="athlete"]'); if (i) i.focus(); }, 0);
      return;
    }
    const after = (this.draft && (this.draft.edited || this.draft.image)) || this.lastPhoto || '';
    await this.flush();
    if (this.view !== 'orders') this.setView('orders');
    this.multi = new Set(); this.sel = 'new'; this.state = ''; this.err = false;
    this.draft = { envelope: env != null ? String(env) : this.d ? this.d.next_envelope : '1', athlete: '', team: this.team !== 'all' ? this.team : (this.last.team || ''), coach: this.last.coach || '',
      lines: [], glasses: false, paid_method: '', paid_cents: 0, accepted_cents: 0, image: '', frames: '', edited: '', parent: '', phone: '', email: '', notes: '' };
    if (this.draft.team && !this.last.coach && this.d) { const o = this.d.orders.find(o => o.team === this.draft.team && o.coach); if (o) this.draft.coach = o.coach; }
    const next = this.nextPhoto(after); this.autoPhoto = !!next;
    if (next) { this.draft.image = stemOf(next.name); this.showPhoto(this.draft.image); }
    this._flashNew = true; this.paintRows(); renderRight();
    setTimeout(() => { const i = $('#right [data-of="athlete"]'); if (i) i.focus(); }, 0);
  },
  changed(redraw) {
    this.state = 'Saving…'; this.err = false; clearTimeout(this.saveT);
    this.saveT = setTimeout(() => this.save(), 450);
    if (redraw) renderRight(); else { this.paintTotal(); this.paintState(); }
  },
  async save() {
    clearTimeout(this.saveT); this.saveT = null;
    const d = this.draft; if (!d || !this.sid) return;
    if (!d.id && !d.athlete.trim() && !d.lines.length) { this.state = ''; this.paintState(); return; }  // nothing typed yet
    if (this._saving) { this._again = true; return this._saving; }
    const body = {}; for (const k of ['id', 'envelope', 'athlete', 'team', 'coach', 'parent', 'address', 'phone', 'email', 'glasses', 'frames', 'image', 'edited', 'notes', 'paid_method', 'paid_cents', 'accepted_cents', 'lines']) if (k in d) body[k] = d[k];
    this._saving = (async () => {
      try {
        const o = (await api('/api/orders/save', { shoot_id: this.sid, order: body })).order;
        if (this.draft === d) { d.id = o.id; d.summary = o.summary; if (this.sel === 'new') this.sel = o.id; }
        this.last = { team: o.team, coach: o.coach }; if (o.edited || o.image) this.lastPhoto = o.edited || o.image;
        this.state = 'Saved'; this.err = false;
        await this.refresh();
      } catch (e) { this.state = 'Not saved: ' + e.message; this.err = true; }
    })();
    await this._saving; this._saving = null;
    if (this._again) { this._again = false; return this.save(); }
    if (S.module === 'orders') { this.paintRows(); renderLeft(); this.paintState(); }
  },
  async del() {
    const d = this.draft; if (!d) return;
    clearTimeout(this.saveT); this.saveT = null;
    if (!d.id) { this.sel = null; this.draft = null; return this.render(); }
    try { this.undo = (await api('/api/orders/delete', { id: d.id })).deleted; } catch (e) { return toast(esc(e.message)); }
    this.sel = null; this.draft = null; await this.refresh(); this.render();
    toast(`Deleted ${esc((this.undo && this.undo.athlete) || 'the envelope')} <button class="toast-link" onclick="KS_ordUndo()">Undo</button>`, 7000);
  },
  async undoDelete() {
    if (!this.undo) return;
    try { const o = (await api('/api/orders/restore', { order: this.undo })).order; this.undo = null; await this.refresh(); this.render(); this.select(o.id); }
    catch (e) { toast(esc(e.message)); }
  },
  move(dir) {
    const rows = this.rows(); if (!rows.length) return;
    const i = rows.findIndex(o => o.id === this.sel);
    const n = rows[i < 0 ? (dir > 0 ? 0 : rows.length - 1) : clamp(i + dir, 0, rows.length - 1)]; if (n) this.select(n.id);
  },
  // ---------- shoots & teams ----------
  editShoot(isNew, id) {
    const s = isNew ? { name: '', date: new Date().toISOString().slice(0, 10), season: '', notes: '', prepaid: 1 } : (this.shoots.find(x => x.id === (id || this.sid)) || {});
    openModal(`<h3>${isNew ? 'New shoot' : 'Shoot'}</h3>
      <label class="fld"><span>Name</span><input id="shName" value="${esc(s.name)}" placeholder="e.g. Montpelier Basketball" autofocus spellcheck="false"></label>
      <div style="display:flex;gap:12px"><label class="fld" style="flex:1"><span>Picture day</span><input id="shDate" type="date" value="${esc(s.date)}"></label>
      <label class="fld" style="flex:1"><span>Season</span><input id="shSeason" value="${esc(s.season)}" placeholder="Winter 2026"></label></div>
      <label class="fld"><span>Notes</span><textarea id="shNotes" rows="3">${esc(s.notes)}</textarea></label>
      <label class="chk" style="margin:4px 0 2px"><input type="checkbox" id="shPrepaid" ${s.prepaid ? 'checked' : ''}> Families pay on picture day <span class="muted small">— envelopes count as paid in full unless you type what they paid or mark them Unpaid</span></label>
      <div class="m-actions">${isNew ? '' : `<button class="btn" id="shDel" style="margin-right:auto">Delete…</button><button class="btn" id="shArch">${s.archived ? 'Unarchive' : 'Archive'}</button>`}<button class="btn" data-close>Cancel</button><button class="btn primary" data-ok>${isNew ? 'Create' : 'Save'}</button></div>`, card => {
      const go = async extra => {
        const body = { ...(isNew ? {} : { id: s.id, archived: s.archived }), name: $('#shName', card).value, date: $('#shDate', card).value, season: $('#shSeason', card).value, notes: $('#shNotes', card).value, prepaid: $('#shPrepaid', card).checked, ...extra };
        try { const r = await api('/api/orders/shoot/save', { shoot: body }); this.shoots = r.shoots; closeModal(); if (isNew) await this.pickShoot(r.shoot.id); else { if (s.id === this.sid) await this.refresh(); this.render(); } }
        catch (e) { toast(esc(e.message)); }
      };
      $('[data-ok]', card).addEventListener('click', () => go({}));
      $('#shName', card).addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); go({}); } });
      const arch = $('#shArch', card); if (arch) arch.addEventListener('click', () => go({ archived: !s.archived }));
      const del = $('#shDel', card);
      if (del) del.addEventListener('click', () => { closeModal(); confirmDialog(`Delete ${s.name}?`, `This deletes the shoot and its ${plural(s.n || 0, 'envelope')}. A copy of the order book from earlier today is kept in Keeper Studio's backups folder.`, 'Delete shoot', async () => {
        try { this.shoots = (await api('/api/orders/shoot/delete', { id: s.id })).shoots; } catch (e) { return toast(esc(e.message)); }
        if (this.sid === s.id) await this.pickShoot((this.shoots.find(x => !x.archived) || {}).id || null); else this.render();
      }); });
    });
  },
  async pickShoot(id) {
    await this.flush();
    this.sid = id; this.sel = null; this.draft = null; this.team = 'all'; this.q = ''; this.lab = null; this.crops = '';
    if (id) DB.put('kv', 'orders|shoot', id).catch(() => {});
    this.d = null; await this.refresh(); this.render();
    if (this.view === 'lab') this.loadLab();
  },
  ask(title, label, value, note = '') {
    return new Promise(res => openModal(`<h3>${esc(title)}</h3><label class="fld"><span>${esc(label)}</span><input id="askIn" value="${esc(value)}" autofocus spellcheck="false"></label>${note ? `<p class="muted small">${note}</p>` : ''}
      <div class="m-actions"><button class="btn" data-close>Cancel</button><button class="btn primary" data-ok>OK</button></div>`, card => {
      const done = v => { closeModal(); res(v); };
      $('[data-ok]', card).addEventListener('click', () => done($('#askIn', card).value.trim()));
      $('#askIn', card).addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); done(e.target.value.trim()); } });
      $$('[data-close]', card).forEach(b => b.addEventListener('click', () => res(null)));
    }));
  },
  // ▣: with team photos marked T, the filmstrip switches to just those and a click sets it.
  async teamPhoto(team) {
    if (S.photos.some(p => getMeta(p.key).team)) return this.startTeamPick(team);
    return this.askTeamPhoto(team);
  },
  startTeamPick(team) {
    if (this.pickingTeam == null) this.savedFilter = { ...S.filter };
    this.pickingTeam = team;
    S.filter = { ...S.filter, flag: 'any', team: true }; syncFilterBar(); afterFilter();
    this.modbar();
  },
  endTeamPick() {
    if (this.pickingTeam == null) return;
    this.pickingTeam = null;
    const f = { ...(this.savedFilter || S.filter) }; delete f.team; S.filter = f; this.savedFilter = null;
    syncFilterBar(); afterFilter(); this.modbar();
  },
  async finishTeamPick(id) {
    const team = this.pickingTeam, p = S.byId.get(id); if (team == null || !p) return;
    this.endTeamPick();
    try { await api('/api/orders/team-photo', { shoot_id: this.sid, team, image: stemOf(p.name) }); await this.refresh(); this.lab = null; this.render(); if (this.view === 'lab') this.loadLab(); toast(`${esc(team)} group photo: ${esc(stemOf(p.name))}`, 3000); }
    catch (e) { toast(esc(e.message)); }
  },
  async askTeamPhoto(team) {
    const t = (this.d.teams.find(x => x.name === team) || {}), act = S.byId.get(S.active);
    const v = await this.ask(`Group photo · ${team}`, 'Group photo file', t.image || (act ? stemOf(act.name) : ''),
      `The team shot that team 5x7s, team 8x10s and Memory Mates are printed from. Crop names it like ${esc((t.image || 'IMG_5373') + '_7x5')}.${act ? ` Filled in from the photo selected in the filmstrip.` : ''} Tip: press T on team photos in Library, and ▣ will show just those to click.`);
    if (v == null) return;
    try { await api('/api/orders/team-photo', { shoot_id: this.sid, team, image: this.normImage(v) }); await this.refresh(); this.lab = null; this.render(); if (this.view === 'lab') this.loadLab(); }
    catch (e) { toast(esc(e.message)); }
  },
  async renameTeam(team) {
    const v = await this.ask('Rename team', 'Team name', team, 'Every envelope on this team is renamed.'); if (!v || v === team) return;
    try { await api('/api/orders/rename-team', { shoot_id: this.sid, old: team, new: v }); if (this.team === team) this.team = v; if (this.draft && this.draft.team === team) this.draft.team = v; await this.refresh(); this.render(); }
    catch (e) { toast(esc(e.message)); }
  },
  setView(v) { this.view = v; this.render(); if (v === 'lab') this.loadLab(); },
  // ---------- exports, import, lab ----------
  // Each export opens a formatted preview with Save PDF and Save CSV.
  async preview(kind) {
    if (!this.sid) return;
    const team = this.team !== 'all' ? this.team : '';
    let R; try { R = await api('/api/orders/report', { shoot_id: this.sid, kind, team }); } catch (e) { return toast(esc(e.message)); }
    this.reportModal(R, `<button class="btn" data-close>Close</button><button class="btn" data-rep="csv">Save CSV…</button><button class="btn primary" data-rep="pdf">Save PDF…</button>`,
      kind === 'pull' ? 'empty columns hidden' : '', b => this.exportCsv(kind, b.dataset.rep));
  },
  // The formatted table in a wide modal; buttons with data-rep call onAction.
  reportModal(R, buttons, note, onAction) {
    const cls = a => a === 'money' ? 'r' : a === 'num' ? 'c' : '';
    const body = R.rows.map(r => r.kind === 'group' ? `<tr class="grp"><td colspan="${R.head.length}">${esc(r.label)}</td></tr>`
      : `<tr class="${r.kind === 'total' ? 'tot' : ''}">${r.cells.map((c, i) => `<td class="${cls(R.align[i])}">${esc(c)}</td>`).join('')}</tr>`).join('');
    const n = R.rows.filter(r => r.kind === 'row').length;
    openModal(`<div class="rep-head"><div><h3>${esc(R.title)}</h3><div class="muted small">${esc(R.subtitle)} · ${plural(n, 'row')}${note ? ' · ' + note : ''}</div></div>
        <div class="m-actions" style="margin:0">${buttons}</div></div>
      <div class="rep-paper">${n ? `<table class="rep"><thead><tr>${R.head.map((h, i) => `<th class="${cls(R.align[i])}">${esc(h)}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table>` : '<p class="muted">Nothing to show yet.</p>'}</div>`,
      card => {
        card.classList.add('report');
        card.addEventListener('click', e => { const b = e.target.closest('[data-rep]'); if (b) onAction(b); });
      });
  },
  async exportCsv(kind, fmt = 'csv') {
    if (!this.sid) return;
    let name; try { name = (await api('/api/orders/export-name', { shoot_id: this.sid, kind })).filename; } catch (e) { return toast(esc(e.message)); }
    if (this.team !== 'all') name = name.replace(/\.csv$/, ` - ${sanitize(this.team)}.csv`);
    if (fmt === 'pdf') name = name.replace(/\.csv$/, '.pdf');
    const dir = (await DB.get('kv', 'orders|exportdir').catch(() => null)) || S.root || '';
    const p = await pickPath('save', { initial: dir, filename: name, types: [fmt === 'pdf' ? 'PDF (*.pdf)' : 'CSV (*.csv)'] }); if (!p) return;
    try {
      const r = await api('/api/orders/export', { shoot_id: this.sid, kind, path: p, format: fmt, team: this.team !== 'all' ? this.team : '' });
      DB.put('kv', 'orders|exportdir', dirName(r.path)).catch(() => {});
      toast(`Saved ${esc(baseName(r.path))}${this.team !== 'all' ? ` (${esc(this.team)} only)` : ''} <button class="toast-link" onclick="reveal(${esc(JSON.stringify(r.path))})">Show</button>${r.unmapped.length ? `<br>${r.unmapped.length} print items have no ROES code yet — names were used instead; add the codes under Prices…` : ''}`, 6000);
    } catch (e) { toast(esc(e.message), 5000); }
  },
  async importWeb() {
    if (!this.sid) return;
    const p = await pickPath('open', { initial: S.root || '', types: ['CSV (*.csv)'] }); if (!p) return;
    try {
      const r = await api('/api/orders/import-web', { shoot_id: this.sid, path: p });
      await this.refresh(); this.render();
      toast(`Imported ${plural(r.added, 'order')}${r.skipped ? ` · ${r.skipped} already here` : ''}`, 5000);
      if (r.problems.length) openModal(`<h3>Some items weren't recognised</h3><p class="muted">They aren't in prices.yaml, so they were left off these orders:</p><div class="hint">${r.problems.map(esc).join('<br>')}</div><div class="m-actions"><button class="btn" data-close>OK</button></div>`);
    } catch (e) { toast(esc(e.message), 6000); }
  },
  async openPrices() {
    try { const r = await api('/api/orders/open-prices', {}); toast(`Opened ${esc(r.path)} — save it and come back; prices update by themselves.`, 6000); }
    catch (e) { toast(esc(e.message)); }
  },
  selectOrdered() {
    if (!this.d) return;
    const want = new Set([...this.d.orders.filter(o => o.lines.length).map(o => o.edited || o.image), ...this.d.teams.map(t => t.image)].filter(Boolean).map(s => stemOf(s).toLowerCase()));
    const ids = S.photos.filter(p => want.has(stemOf(p.name).toLowerCase())).map(p => p.id);
    if (!ids.length) return toast('None of the ordered photos are in the open folder', 3000);
    S.selected = new Set(ids); S.active = ids[0]; S.anchor = ids[0]; Crop.scope = 'selected';
    setModule('crop'); refreshSelection();
    const miss = want.size - ids.length;
    toast(`${plural(ids.length, 'ordered photo')} selected — Crop will export just these${miss ? ` · ${miss} not in this folder` : ''}`, 5000);
  },
  async loadLab() {
    if (!this.sid) return;
    if (!this.crops) this.crops = (await DB.get('kv', 'orders|crops|' + this.sid).catch(() => null)) || Crop.outDir || '';
    try { this.lab = await api('/api/orders/lab-plan', { shoot_id: this.sid, crops_dir: this.crops }); } catch (e) { toast(esc(e.message)); }
    if (S.module === 'orders' && this.view === 'lab') renderView();
    this.syncShipping();
  },
  async pickCrops() {
    const p = await pickPath('folder', { initial: this.crops || Crop.outDir || S.root || '' }); if (!p) return;
    this.crops = p; DB.put('kv', 'orders|crops|' + this.sid, p).catch(() => {}); this.loadLab();
  },
  async buildLab() {
    const s = this.shoot(); if (!s || this.building) return;
    const parent = await pickPath('folder', { initial: dirName(this.crops) || S.root || '' }); if (!parent) return;
    const dest = parent + (parent.includes('\\') ? '\\' : '/') + sanitize(`Lab order - ${s.name}`);
    this.building = true; renderView();
    try {
      const r = await api('/api/orders/lab-build', { shoot_id: this.sid, crops_dir: this.crops, out_dir: dest, one_per_print: this.onePer });
      toast(`${plural(r.copied, 'file')} copied${r.missing.length ? ` · ${r.missing.length} missing, listed in lab-order.csv` : ''} <button class="toast-link" onclick="reveal(${esc(JSON.stringify(r.out_dir))})">Show</button>`, 8000);
    } catch (e) { toast(esc(e.message), 6000); }
    this.building = false; renderView();
  },
  // Shipping is a fixed price: a shoot that ships gets the remembered amount; Pickup is $0
  async syncShipping(force) {
    if (!this.sid || !this.d) return;
    const m = (this.lab && this.lab.meridian) || {}, cur = this.d.totals.shipping_cents || 0;
    let want = force;
    if (want == null) { if ((m.delivery || 'ship') !== 'ship' || cur) return; want = Math.round(parseFloat(m.ship_amount || '0') * 100) || 0; if (!want) return; }
    if (want === cur) return;
    try { await api('/api/orders/shipping', { shoot_id: this.sid, amount: (want / 100).toFixed(2) }); await this.refresh(); renderLeft(); if (S.module === 'orders' && this.view === 'lab') renderView(); } catch {}
  },
  async merSet(k, v) {
    try { const r = await api('/api/orders/meridian-settings', { [k]: v }); if (this.lab) this.lab.meridian = r.settings; } catch (e) { toast(esc(e.message)); }
    if (k !== 'account_email') renderView();
  },
  async summary() {
    if (!this.sid) return;
    let R; try { R = await api('/api/orders/summary', { shoot_id: this.sid }); } catch (e) { return toast(esc(e.message)); }
    const cls = a => a === 'money' ? 'r' : a === 'num' ? 'c' : '';
    const table = t => `<table class="rep" style="${t.head.length <= 3 ? 'width:auto;min-width:360px' : ''}"><thead><tr>${t.head.map((h, i) => `<th class="${cls(t.align[i])}">${esc(h)}</th>`).join('')}</tr></thead><tbody>${t.rows.map(r => `<tr class="${r.kind === 'total' ? 'tot' : ''}">${r.cells.map((c, i) => `<td class="${cls(t.align[i])}">${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    openModal(`<div class="rep-head"><div><h3>${esc(R.title)}</h3><div class="muted small">${esc(R.subtitle)}</div></div>
        <div class="m-actions" style="margin:0"><button class="btn" data-close>Close</button><button class="btn primary" data-sum-pdf>Save PDF…</button></div></div>
      <div class="rep-paper">${R.sections.map(sec => `<h4 class="rep-h">${esc(sec.heading)}</h4>${table(sec)}`).join('')}</div>`, card => {
      card.classList.add('report');
      $('[data-sum-pdf]', card).addEventListener('click', async () => {
        const s = this.shoot();
        const dir = (await DB.get('kv', 'orders|exportdir').catch(() => null)) || S.root || '';
        const p = await pickPath('save', { initial: dir, filename: `${sanitize((s && s.name) || 'Shoot')} - shoot summary.pdf`, types: ['PDF (*.pdf)'] }); if (!p) return;
        try {
          const r = await api('/api/orders/summary-pdf', { shoot_id: this.sid, path: p });
          DB.put('kv', 'orders|exportdir', dirName(r.path)).catch(() => {});
          toast(`Saved ${esc(baseName(r.path))} <button class="toast-link" onclick="reveal(${esc(JSON.stringify(r.path))})">Show</button>`, 6000);
        } catch (e) { toast(esc(e.message), 5000); }
      });
    });
  },
  async previewMeridian() {
    const M = this.mer; if (!M || !M.csv) return;
    let R; try { R = await api('/api/orders/meridian-report', { csv: M.csv }); } catch (e) { return toast(esc(e.message)); }
    const pdf = M.pdf ? `<button class="btn" data-rep="pdf">Show PDF</button>` : '';
    this.reportModal(R, `<button class="btn" data-close>Close</button>${pdf}<button class="btn primary" data-rep="csv">Show order folder</button>`,
      M.ok ? 'checked by Meridian’s checker' : 'Meridian’s checker found problems',
      b => reveal(b.dataset.rep === 'pdf' ? M.pdf : M.csv));
  },
  async buildMeridian() {
    const s = this.shoot(); if (!s || this.merBusy) return;
    const em = $('#modView [data-mer=account_email]');
    if (em && em.value.trim() !== (this.lab.meridian.account_email || '')) await this.merSet('account_email', em.value.trim());
    const parent = await pickPath('folder', { initial: dirName(this.crops) || S.root || '' }); if (!parent) return;
    const dest = parent + (parent.includes('\\') ? '\\' : '/') + sanitize(`Meridian order - ${s.name}`);
    this.merBusy = true; this.mer = null; renderView();
    try { this.mer = await api('/api/orders/meridian-build', { shoot_id: this.sid, crops_dir: this.crops, out_dir: dest }); }
    catch (e) { toast(esc(e.message), 6000); }
    this.merBusy = false; renderView();
  },
  merHTML(L, found) {
    const m = L.meridian || {}, R = this.mer;
    const noEmail = !/@/.test(m.account_email || '');
    const li = (a, f) => a.map(x => `<li>${f(x)}</li>`).join('');
    const res = !R ? '' : `<div class="mer-res ${R.ok && !R.left_out.length ? 'ok' : 'bad'}">
        <div class="mer-top"><b>${!R.ok ? '✗ Not ready' : R.left_out.length ? `✓ CSV ready · ${plural(R.left_out.length, 'print line')} not in it` : '✓ Ready to send'}</b><span>${plural(R.items, 'item')} · ${plural(R.files, 'file')}${R.total ? ` · about $${esc(R.total)} before shipping` : ''}</span>
          <span class="tb-spacer"></span>${R.csv ? '<button class="btn sm" data-ord="mer-preview">Preview</button>' : ''}${R.pdf ? `<button class="btn sm" onclick="reveal(${esc(JSON.stringify(R.pdf))})" title="${esc(R.pdf)}">PDF</button>` : ''}
          <button class="btn sm" onclick="reveal(${esc(JSON.stringify(R.csv || R.out_dir))})">Show</button></div>
        <div class="muted small">Meridian’s checker ${R.ok ? 'passed' : 'found problems'}: ${plural(R.errors.length, 'error')}, ${plural(R.warnings.length, 'warning')}.</div>
        ${R.errors.length ? `<ul class="mer-err">${li(R.errors, esc)}</ul>` : ''}
        ${R.warnings.length ? `<ul class="mer-warn">${li(R.warnings, esc)}</ul>` : ''}
        ${R.left_out.length ? `<div class="mer-sub">Not in the CSV — order these another way:</div><ul class="mer-warn">${li(R.left_out, x => `${esc(x.group)} ×${x.qty} for ${esc(x.for.join(', '))}: ${esc(x.why)}`)}</ul>` : ''}
      </div>`;
    return `<div class="mer"><div class="mer-head"><b>Meridian bulk order</b><span class="muted small">One folder with a CSV, for Meridian’s bulk upload. Every print is the file Crop cut, sent as is.</span></div>
      <div class="mer-row"><label class="fld">Meridian account email<input type="email" data-mer="account_email" value="${esc(m.account_email || '')}" placeholder="you@example.com" spellcheck="false"></label>
        <div class="fld"><span>Delivery${(m.delivery || 'ship') === 'ship' ? ' · shipping' : ''}</span><div class="deliv-row">${segHTML('merDelivery', m.delivery || 'ship', [['ship', 'Ship'], ['pickup', 'Pickup']])}${(m.delivery || 'ship') === 'ship' ? `<label class="ship-fld" title="Meridian's shipping for this order. It's remembered for the next shoot; Analysis takes it off what you keep.">$<input class="ship-in" data-oship inputmode="decimal" value="${this.d && this.d.totals.shipping_cents ? (this.d.totals.shipping_cents / 100).toFixed(2) : ''}" placeholder="0.00"></label>` : ''}</div></div>
        <div class="tb-spacer"></div>
        ${switchHTML('merEnvOrder', m.envelope_order !== 'no', 'Files in envelope order', 'File names start with the team’s place and the envelope number (03-7thBoys_E047_IMG_5031_5x7.jpg), so the lab prints and packs them in the order you stuff envelopes. Turn off to send the plain names.')}
        <button class="btn primary" data-ord="mer-build" ${this.merBusy || !L.crops_exists || !found ? 'disabled' : ''} title="${noEmail ? 'Fill in your Meridian account email first' : ''}">${this.merBusy ? 'Building…' : 'Build Meridian order…'}</button></div>
      ${res}</div>`;
  },
  // ---------- school & other orders ----------
  // Prints for the school, the park, teachers or a sponsor: not on any envelope.
  ex: null, exSel: null, exDel: false,
  async openExtras(select) {
    if (!this.sid) return;
    if (!this.crops) this.crops = (await DB.get('kv', 'orders|crops|' + this.sid).catch(() => null)) || Crop.outDir || '';
    await this.loadExtras();
    if (!this.ex) return;
    if (select != null) this.exSel = select;
    if (!this.ex.extras.some(e => e.id === this.exSel)) this.exSel = this.ex.extras.length ? this.ex.extras[0].id : null;
    openModal('<div id="exWin" class="exwin"></div>', card => {
      card.classList.add('report', 'exw');
      const w = $('#exWin', card);
      w.addEventListener('click', e => this.exClick(e));
      w.addEventListener('change', e => this.exChange(e));
      w.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('input')) { e.preventDefault(); e.target.blur(); } });
      this.exPaint();
    });
  },
  async loadExtras() {
    try { this.ex = await api('/api/orders/extras', { shoot_id: this.sid, crops_dir: this.crops || '' }); }
    catch (e) { toast(esc(e.message), 5000); this.ex = null; }
  },
  exCur() { return this.ex && this.ex.extras.find(e => e.id === this.exSel) || null; },
  exTeams() { return ((this.d && this.d.teams) || []).filter(t => !t.planned).map(t => t.name); },
  exPhotoFor(stem) { const s = String(stem || '').toLowerCase(); return s ? S.photos.find(p => stemOf(p.name).toLowerCase() === s) : null; },
  exPaint() {
    const w = $('#exWin'); if (!w || !this.ex) return;
    const X = this.ex, cur = this.exCur(), sh = this.shoot() || {}, C = X.choices;
    const list = X.extras.map(e => { const s = e.summary;
      return `<div class="ex-o ${e.id === this.exSel ? 'on' : ''}" data-x="pick" data-id="${e.id}"><span class="amt ${s.free ? 'free' : ''}">${s.free ? 'Free' : fmt$(s.sales_cents)}</span><b>${esc(e.kind || 'Other')}</b><small>${esc(e.customer || '')}${e.customer ? ' · ' : ''}${s.due_cents ? `<span class="due">owes ${fmt$(s.due_cents)}</span>` : plural(s.prints, 'print')}</small></div>`; }).join('');
    const copyOpts = X.shoots.filter(s => s.count).map(s => `<option value="${s.id}">${esc(s.name)} (${s.count})</option>`).join('');
    let detail = '<div class="ex-empty muted">Add an order on the left: the school, the park, the teachers, or anyone else.</div>';
    if (cur) {
      const s = cur.summary, why = {};
      for (const l of cur.lines) if (l.why) (why[l.item] = why[l.item] || []).push(l);
      const sizeSel = (i, v) => `<select data-xf="size" data-i="${i}">${C.sizes.map(z => `<option ${z === v ? 'selected' : ''}>${z}</option>`).join('')}</select>`;
      const prodSel = (i, size, v) => { const ps = C.products[size] || []; return `<select data-xf="product" data-i="${i}">${ps.map(p => `<option value="${esc(p.product)}" ${p.product === v ? 'selected' : ''}>${esc(p.name)}${p.lab_cents != null ? ` · lab ${fmt$(p.lab_cents)}` : ''}</option>`).join('')}${ps.some(p => p.product === v) ? '' : `<option selected value="${esc(v)}">${esc(v)} (not at this size)</option>`}</select>`; };
      const qtyOf = it => it.src === 'teams' ? Object.values(it.counts || {}).reduce((a, n) => a + Math.max(0, +n || 0), 0) : Math.max(0, +it.qty || 0);
      const labOf = i => cur.lines.filter(l => l.item === i).reduce((a, l) => a + (l.lab_each || 0) * l.qty, 0);
      const teams = this.exTeams(), photos = new Map(((this.d && this.d.teams) || []).map(t => [t.name, t.image]));
      const rows = (cur.items || []).map((it, i) => {
        let src;
        if (it.src === 'teams') {
          const c = it.counts || {}, names = [...new Set([...teams, ...Object.keys(c)])];
          const vals = names.map(t => +c[t] || 0), same = vals.every(v => v === vals[0]);
          src = `<div class="ex-src"><span class="muted">Every team photo</span><span class="ex-each" title="Set every team at once">each <button class="btn sm" data-x="each" data-i="${i}" data-d="-1">−</button><b>${same ? vals[0] || 0 : '–'}</b><button class="btn sm" data-x="each" data-i="${i}" data-d="1">+</button></span></div><div class="ex-chips">${names.map(t => {
            const n = +c[t] || 0, nophoto = n > 0 && !photos.get(t);
            return `<span class="ex-chip ${n ? 'on' : ''} ${nophoto ? 'warn' : ''}" title="${nophoto ? 'No group photo picked for this team yet' : ''}">${esc(t)}${nophoto ? ' · no photo' : ''}<span class="q"><button data-x="cnt" data-i="${i}" data-t="${esc(t)}" data-d="-1">−</button><b>× ${n}</b><button data-x="cnt" data-i="${i}" data-t="${esc(t)}" data-d="1">+</button></span></span>`; }).join('')}</div>`;
        } else if (it.src === 'team') {
          src = `<span class="ex-th">${(() => { const p = this.exPhotoFor(photos.get(it.team)); return p ? `<img src="${thumbUrl(p.path, 120)}" alt="">` : ''; })()}</span><select data-xf="team" data-i="${i}">${[...new Set([...teams, it.team || ''])].map(t => `<option ${t === it.team ? 'selected' : ''} value="${esc(t)}">${esc(t || 'Pick a team')}</option>`).join('')}</select> <span class="muted">team photo${photos.get(it.team) ? ' ' + esc(photos.get(it.team)) : ''}</span>`;
        } else {
          const p = this.exPhotoFor(it.image);
          src = `<span class="ex-th">${p ? `<img src="${thumbUrl(p.path, 120)}" alt="">` : ''}</span><input class="ex-img" data-xf="image" data-i="${i}" value="${esc(it.image || '')}" placeholder="Photo # (e.g. 4412)" spellcheck="false"><input class="ex-lbl" data-xf="label" data-i="${i}" value="${esc(it.label || '')}" placeholder="Name on it" spellcheck="false">`;
        }
        const q = qtyOf(it), pr = +it.price_cents || 0;
        const ws = (why[i] || []).map(l => `<span class="ex-why" title="${esc(l.label)}">${esc(it.src === 'teams' ? l.label.replace(/ team$/, '') + ': ' : '')}${esc(l.why)}</span>`).join('');
        return `<tr><td class="ex-srccell">${src}${ws ? `<div>${ws}</div>` : ''}</td><td>${sizeSel(i, it.size)}</td><td>${prodSel(i, it.size, it.product)}</td>
          <td class="r">${it.src === 'teams' ? q : `<input class="ex-num" data-xf="qty" data-i="${i}" value="${q}" inputmode="numeric">`}</td>
          <td class="r"><input class="ex-money ${pr ? '' : 'free'}" data-xf="price" data-i="${i}" value="${(pr / 100).toFixed(2)}" inputmode="decimal" title="0 = free"></td>
          <td class="r">${pr ? fmt$(pr * q) : '<span class="free">Free</span>'}</td><td class="r">${fmt$(labOf(i))}</td>
          <td class="r"><button class="ex-del" data-x="rm" data-i="${i}" title="Remove this item">✕</button></td></tr>`;
      }).join('');
      const blockers = cur.lines.filter(l => l.why);
      const notSetUp = [...new Set(blockers.filter(l => /set up in Crop/.test(l.why)).map(l => l.size))];
      const banner = blockers.length ? `<div class="banner amber inline">${plural(blockers.reduce((a, l) => a + l.qty, 0), 'print')} can't go to the lab yet${notSetUp.length ? ` — ${notSetUp.join(', ')} isn't set up in Crop (add it under Crop's sizes, then Check framing)` : ''}${blockers.some(l => /group photo/.test(l.why)) ? ' — pick the missing group photos under Teams' : ''}${blockers.some(l => /crop yet/.test(l.why)) ? ' — crop and export the missing sizes' : ''}.</div>` : '';
      const pm = cur.paid_method || '';
      detail = `<div class="ex-cust"><label><span>For</span><input data-xf="kind" value="${esc(cur.kind || '')}" placeholder="School" spellcheck="false"></label>
          <label class="wide"><span>Customer</span><input data-xf="customer" value="${esc(cur.customer || '')}" placeholder="Bryan High School" spellcheck="false"></label>
          <label class="wide"><span>Contact</span><input data-xf="contact" value="${esc(cur.contact || '')}" placeholder="Name, email or phone" spellcheck="false"></label></div>
        <table class="ex-t"><thead><tr><th>Photo</th><th>Size</th><th>Product</th><th class="r">Qty</th><th class="r">Price each</th><th class="r">Total</th><th class="r">Lab cost</th><th></th></tr></thead>
          <tbody>${rows || `<tr><td colspan="8" class="muted">No items yet. Add team photos or one photo below.</td></tr>`}</tbody></table>
        <div class="ex-add"><span class="muted">Add:</span><button class="btn sm" data-x="add" data-src="teams">+ Every team photo</button><button class="btn sm" data-x="add" data-src="team">+ One team's photo</button><button class="btn sm" data-x="add" data-src="photo">+ One photo…</button>${X.crops_checked ? '' : `<span class="muted small" style="margin-left:auto">Crops aren't checked: choose the crops folder under Lab order.</span>`}</div>
        ${banner}
        <div class="ex-pay"><span>Paid</span><input class="ex-money" data-xf="paid" value="${((cur.paid_cents || 0) / 100).toFixed(2)}" inputmode="decimal">
          ${segHTML('exPaid', pm, [['cash', 'Cash'], ['check', 'Check'], ['venmo', 'Venmo'], ...(pm === 'card' ? [['card', 'Card']] : []), ['other', 'Other']])}
          ${pm === 'check' ? `<input data-xf="check_no" value="${esc(cur.check_no || '')}" placeholder="Check #" style="width:110px" spellcheck="false">` : ''}
          <span class="${s.due_cents ? 'due' : 'muted'}" style="margin-left:auto">${s.free ? 'Free' : s.due_cents ? `Still owed ${fmt$(s.due_cents)}` : 'Paid in full'}</span>
          <button class="btn sm" data-x="invoice" ${s.free ? 'disabled title="Nothing to bill"' : ''}>Invoice PDF…</button></div>
        <div class="ex-foot2"><input data-xf="notes" value="${esc(cur.notes || '')}" placeholder="Notes (shown on the invoice)" spellcheck="false"><button class="btn sm ${this.exDel ? 'danger' : ''}" data-x="delorder">${this.exDel ? 'Click again to delete' : 'Delete order'}</button></div>`;
    }
    const T = X.totals, s = cur && cur.summary;
    w.innerHTML = `<div class="rep-head"><div><h3>School &amp; other orders · ${esc(sh.name || '')}</h3><div class="muted small">Prints that aren't on any envelope. A price of 0 makes it free; its lab cost still comes off profit.</div></div>
        <div class="m-actions" style="margin:0"><button class="btn primary" data-x="done">Done</button></div></div>
      <div class="ex-grid"><div class="ex-list">${list}
          <div class="ex-new"><button class="btn sm" data-x="new" data-k="School">+ School</button><button class="btn sm" data-x="new" data-k="Park">+ Park</button><button class="btn sm" data-x="new" data-k="Teachers">+ Teachers</button><button class="btn sm" data-x="new" data-k="">+ Other…</button></div>
          ${copyOpts ? `<select class="ex-copy" data-xf="copy"><option value="">Copy from another shoot…</option>${copyOpts}</select>` : ''}</div>
        <div class="ex-detail">${detail}</div></div>
      <div class="ex-foot">${s ? `<span><b>${esc(cur.kind || 'Order')}</b> · sales <b>${fmt$(s.sales_cents)}</b> · lab cost <b>${fmt$(s.lab_cents)}</b> · profit <b>${fmt$(s.profit_cents)}</b>${s.sales_cents ? ` (${(100 * s.profit_cents / s.sales_cents).toFixed(1)}%)` : ''}</span>` : ''}
        <span class="muted">${T.count ? `All ${plural(T.count, 'order')}: ${plural(T.prints, 'print')} · sales ${fmt$(T.sales_cents)} · lab ${fmt$(T.lab_cents)}${T.due_cents ? ` · owed ${fmt$(T.due_cents)}` : ''}` : ''}</span></div>`;
  },
  async exSave(patch) {
    const cur = this.exCur(); if (!cur) return;
    try {
      const r = await api('/api/orders/extra/save', { shoot_id: this.sid, order: { id: cur.id, ...patch } });
      Object.assign(cur, patch);
      await this.loadExtras();
    } catch (e) { toast(esc(e.message), 5000); }
    this.exDel = false; this.exPaint();
  },
  exItems() { return JSON.parse(JSON.stringify((this.exCur() || {}).items || [])); },
  async exClick(e) {
    const b = e.target.closest('[data-x],[data-seg] button'); if (!b) return;
    if (b.closest('[data-seg="exPaid"]')) { const v = b.dataset.v, cur = this.exCur(); return this.exSave({ paid_method: cur && cur.paid_method === v ? '' : v }); }
    const a = b.dataset.x, i = +b.dataset.i;
    if (a === 'done') { closeModal(); await this.refresh(); this.render(); return; }
    if (a === 'pick') { this.exSel = +b.dataset.id; this.exDel = false; return this.exPaint(); }
    if (a === 'new') {
      const k = b.dataset.k, size = ((this.ex.choices.kinds || {})[k] || {}).size || '5x7';
      const counts = Object.fromEntries(this.exTeams().map(t => [t, 1]));
      const items = k ? [{ src: 'teams', size, product: 'Professional Prints', counts, price_cents: 0 }] : [];
      try { const r = await api('/api/orders/extra/save', { shoot_id: this.sid, order: { kind: k || 'Other', customer: '', items } }); this.exSel = r.order.id; }
      catch (err) { return toast(esc(err.message), 5000); }
      await this.loadExtras(); this.exPaint();
      if (!k) { const f = $('#exWin [data-xf="kind"]'); if (f) { f.focus(); f.select(); } }
      return;
    }
    const items = this.exItems();
    if (a === 'add') {
      const src = b.dataset.src, base = { size: '8x10', product: 'Professional Prints', price_cents: 0 };
      if (src === 'teams') items.push({ ...base, src, counts: Object.fromEntries(this.exTeams().map(t => [t, 1])) });
      else if (src === 'team') items.push({ ...base, src, team: this.exTeams()[0] || '', qty: 1 });
      else items.push({ ...base, size: '11x14', src, image: '', label: '', qty: 1 });
      await this.exSave({ items });
      if (src === 'photo') { const f = $$('#exWin [data-xf="image"]').pop(); if (f) f.focus(); }
      return;
    }
    if (a === 'rm') { items.splice(i, 1); return this.exSave({ items }); }
    if (a === 'cnt') { const it = items[i], t = b.dataset.t; it.counts = it.counts || {}; it.counts[t] = Math.max(0, (+it.counts[t] || 0) + +b.dataset.d); return this.exSave({ items }); }
    if (a === 'each') { const it = items[i], c = it.counts || {}; const names = [...new Set([...this.exTeams(), ...Object.keys(c)])];
      const vals = names.map(t => +c[t] || 0), base = vals.every(v => v === vals[0]) ? vals[0] || 0 : Math.max(...vals);
      it.counts = Object.fromEntries(names.map(t => [t, Math.max(0, base + +b.dataset.d)])); return this.exSave({ items }); }
    if (a === 'delorder') {
      if (!this.exDel) { this.exDel = true; return this.exPaint(); }
      try { await api('/api/orders/extra/delete', { id: this.exSel }); } catch (err) { return toast(esc(err.message)); }
      this.exDel = false; this.exSel = null; await this.loadExtras();
      if (this.ex.extras.length) this.exSel = this.ex.extras[0].id;
      return this.exPaint();
    }
    if (a === 'invoice') {
      const cur = this.exCur(), sh = this.shoot() || {};
      const dir = (await DB.get('kv', 'orders|exportdir').catch(() => null)) || S.root || '';
      const p = await pickPath('save', { initial: dir, filename: `${sanitize(sh.name || 'Shoot')} - invoice - ${sanitize(cur.customer || cur.kind || 'order')}.pdf`, types: ['PDF (*.pdf)'] }); if (!p) return;
      try { const r = await api('/api/orders/invoice-pdf', { shoot_id: this.sid, id: cur.id, path: p }); DB.put('kv', 'orders|exportdir', dirName(r.path)).catch(() => {});
        toast(`Saved ${esc(baseName(r.path))} <button class="toast-link" onclick="reveal(${esc(JSON.stringify(r.path))})">Show</button>`, 6000); }
      catch (err) { toast(esc(err.message), 5000); }
    }
  },
  async exChange(e) {
    const f = e.target.closest('[data-xf]'); if (!f) return;
    const k = f.dataset.xf, i = +f.dataset.i, v = f.value;
    if (k === 'copy') {
      if (!v) return;
      try { const r = await api('/api/orders/extras-copy', { shoot_id: this.sid, from_shoot_id: +v }); toast(`Copied ${plural(r.copied, 'order')} — one person's photos don't carry over`, 5000); }
      catch (err) { return toast(esc(err.message), 5000); }
      await this.loadExtras(); if (!this.exCur() && this.ex.extras.length) this.exSel = this.ex.extras[this.ex.extras.length - 1].id;
      return this.exPaint();
    }
    if (['kind', 'customer', 'contact', 'check_no', 'notes'].includes(k)) return this.exSave({ [k]: v });
    if (k === 'paid') { const c = Math.round(parseFloat(v.replace(/[$,\s]/g, '')) * 100); if (!isFinite(c) || c < 0) { toast('Type the amount paid, like 85.00'); return this.exPaint(); } return this.exSave({ paid_cents: c }); }
    const items = this.exItems(), it = items[i]; if (!it) return;
    if (k === 'price') { const c = Math.round(parseFloat(v.replace(/[$,\s]/g, '') || '0') * 100); if (!isFinite(c) || c < 0) { toast('Type a price, like 25.00 (0 for free)'); return this.exPaint(); } it.price_cents = c; }
    else if (k === 'qty') it.qty = Math.max(0, parseInt(v, 10) || 0);
    else if (k === 'size') { it.size = v; const ps = this.ex.choices.products[v] || []; if (!ps.some(p => p.product === it.product)) it.product = (ps[0] || {}).product || 'Professional Prints'; }
    else if (k === 'product') it.product = v;
    else if (k === 'team') it.team = v;
    else if (k === 'label') it.label = v.trim();
    else if (k === 'image') {
      let st = v.trim();
      if (/^\d+$/.test(st)) { const m = this.matches(st); if (m.length) st = m[0]; }
      it.image = st;
      if (!it.label && this.d) { const o = this.d.orders.find(o => stemOf(o.edited || o.image || '').toLowerCase() === st.toLowerCase());
        if (o) it.label = [o.athlete, o.team].filter(Boolean).join(' · '); }
    }
    return this.exSave({ items });
  },
  // ---------- analysis ----------
  // Sales analysis for the shoot (or one team, or every shoot), with a What if for prices.
  an: null, anScope: 'shoot', anBusy: false, anKey: '', wi: {}, wiDrop: 10,
  async loadAn() {
    const all = this.anScope === 'all';
    const key = all ? 'all' : `${this.sid}|${this.team}`;
    this.anKey = key; this.anBusy = true;
    try {
      const r = await api('/api/orders/analysis', all ? { shoot_id: 'all' } : { shoot_id: this.sid, team: this.team === 'all' ? null : this.team });
      if (this.anKey === key) this.an = r;
    } catch (e) { toast(esc(e.message), 5000); }
    this.anBusy = false;
    if (S.module === 'orders' && this.view === 'an' && this.anKey === key) this.anPaint();
  },
  anCenter(v) {
    v.innerHTML = `<div class="ord-head"><span class="ttl" id="anTtl"></span><span class="muted small" id="anSub"></span><div class="tb-spacer"></div>
      <span class="muted small">Compare</span>${segHTML('anScope', this.anScope, [['shoot', 'This shoot'], ['all', 'All shoots']])}</div>
      <div class="ord-scroll an" id="anBody"><div class="ord-empty">Adding it up…</div></div>`;
    if (this.an && this.anKey === (this.anScope === 'all' ? 'all' : `${this.sid}|${this.team}`)) this.anPaint();
    this.loadAn();
  },
  anPaint() {
    const A = this.an, box = $('#anBody'); if (!A || !box) return;
    const all = this.anScope === 'all', one = !all && A.team != null, s = A.selection, w = A.shoot, sh = this.shoot() || {};
    const pct = (a, b, d = 0) => b ? (100 * a / b).toFixed(d) + '%' : '—';
    // Colors: green = strong, amber = worth a look, red = losing money. Margins: 70%+ green, under 50% amber.
    const mc = m => m == null || !isFinite(m) ? '' : m < 0 ? 'an-neg' : m < .5 ? 'an-lo' : m >= .7 ? 'an-good' : '';
    const vs = (v, ref) => !ref || v == null ? '' : v >= ref * 1.1 ? 'an-good' : v <= ref * .9 ? 'an-lo' : '';
    $('#anTtl').textContent = all ? 'All shoots' : `${sh.name || ''} · ${one ? A.team : 'All teams'}`;
    $('#anSub').textContent = all ? `${plural(A.shoots, 'shoot')} · ${plural(s.n, 'envelope')} with an order` : plural(s.n, 'envelope') + ' with an order';
    if (!s.n) { box.innerHTML = `<div class="ord-empty"><h3>Nothing sold yet</h3><p>Analysis fills in as envelopes are typed in.</p></div>`; return; }
    const prev = !all && !one ? this.anPrevData() : null, ps = prev && prev.selection;
    const delta = (v, o, money) => o == null || !o ? '' : (d => `<span class="${d > 0 ? 'an-up' : d < 0 ? 'an-dn' : 'dim'}">${d > 0 ? '▲' : d < 0 ? '▼' : '='} ${money ? fmt$(Math.abs(d)) : Math.abs(Math.round(100 * d / o)) + '%'}</span> vs ${esc(prev.name)}`)(money ? v - o : v - o);
    const keepTip = 'Sales minus the estimated lab cost' + (one ? '' : ' and shipping');
    const kp = [
      ['Sales', fmt$(s.sales), one ? `${pct(s.sales, w.sales)} of the shoot` : ps ? delta(s.sales, ps.sales) : [plural(s.n, 'envelope'), s.extra && s.extra.sales_cents ? `incl. ${fmt$(s.extra.sales_cents)} school & other` : ''].filter(Boolean).join(' · '), '', s.short ? `After ${fmt$(s.short)} accepted short` : ''],
      ['You keep', fmt$(s.profit), `${pct(s.profit, s.sales)} · lab ${fmt$(s.lab)}${one ? ' · before shipping' : ` · shipping ${fmt$(s.shipping)}`}`, s.profit < 0 ? 'an-neg' : 'an-good', keepTip],
      ['Average order', fmt$(s.avg), one ? `shoot ${fmt$(w.avg)}` : ps ? delta(s.avg, ps.avg, true) : 'per envelope', one ? vs(s.avg, w.avg) : '', 'Sales ÷ envelopes'],
      ['Still owed', fmt$(s.due), [s.due ? plural((A.payments.find(p => p.method === 'Not paid') || { envelopes: 0 }).envelopes, 'envelope') : 'all paid', s.change ? `${fmt$(s.change)} change to give` : ''].filter(Boolean).join(' · '), s.due || s.change ? 'an-lo' : 'an-good', s.short ? `${fmt$(s.short)} accepted short (${s.short_n})` : '']];
    const P = A.products, pk = P.filter(p => p.kind === 'package'), ac = P.filter(p => p.kind === 'alacarte'), ks = P.filter(p => p.kind === 'keepsake');
    const pkN = pk.reduce((t, p) => t + p.sold, 0), mx = Math.max(1, ...pk.map(p => p.sold));
    const bar = (l, v, max, r, cls = '') => `<div class="an-hb"><span>${l}</span><div class="tr"><div class="${cls}" style="width:${max ? 100 * v / max : 0}%"></div></div><em>${r}</em></div>`;
    let cmp;
    if (one) {
      const f = (k, v) => v == null ? '—' : k === 'money' ? fmt$(v) : k === 'pct1' ? v.toFixed(1) + '%' : Math.round(v) + '%';
      cmp = `<h4>${esc(A.team)} vs the whole shoot</h4><table class="an-t"><tr><th></th><th>${esc(A.team)}</th><th>Whole shoot</th><th></th></tr>${A.compare.map(c => {
        const na = c.team == null || c.shoot == null, same = !na && f(c.kind, c.team) === f(c.kind, c.shoot), up = !na && c.team > c.shoot;
        return `<tr><td>${esc(c.label)}</td><td>${f(c.kind, c.team)}</td><td>${f(c.kind, c.shoot)}</td><td class="nw ${na || same ? 'dim' : up ? 'an-up' : 'an-dn'}">${na ? '' : same ? '= same' : up ? '▲ above' : '▼ below'}</td></tr>`; }).join('')}</table>`;
    } else {
      const tp = A.teams.reduce((t, x) => t + x.profit, 0), fs = s.family_sales ?? s.sales;
      cmp = `<h4>By team</h4><table class="an-t team-t"><tr><th>Team</th><th>Env</th><th>Sales</th><th class="tshare">Share of sales</th><th>Avg order</th><th>Profit</th><th>Profit %</th></tr>${(this.anAllTeams || A.teams.length <= 5 ? A.teams : A.teams.slice().sort((a, b) => b.sales - a.sales).slice(0, 4)).map(t => `<tr class="${all ? '' : 'click'}" ${all ? '' : `data-oteam="${esc(t.team === 'No team' ? '' : t.team)}"`}><td>${esc(t.team)}</td><td>${t.n}</td><td>${fmt$(t.sales)}</td><td class="tshare"><span class="sh"><i style="width:${fs ? 100 * t.sales / Math.max(...A.teams.map(x => x.sales), 1) : 0}%"></i></span>${fs ? Math.round(100 * t.sales / fs) + '%' : ''}</td><td class="${vs(t.avg, s.avg)}">${fmt$(t.avg)}</td><td class="${t.profit < 0 ? 'an-neg' : ''}">${fmt$(t.profit)}</td><td class="${mc(t.profit_pct == null ? null : t.profit_pct / 100)}">${t.profit_pct == null ? '—' : t.profit_pct.toFixed(1) + '%'}</td></tr>`).join('')}<tr class="tot"><td>All teams</td><td>${s.n}</td><td>${fmt$(fs)}</td><td></td><td>${fmt$(s.avg)}</td><td>${fmt$(tp)}</td><td class="${mc(fs ? tp / fs : null)}">${pct(tp, fs, 1)}</td></tr></table>${A.teams.length > 5 ? `<div class="an-more">${this.anAllTeams ? '' : `+${A.teams.length - 4} more teams · `}<button class="linkish" data-ord="an-teams">${this.anAllTeams ? 'show the top 4' : 'show all'}</button></div>` : ''}<div class="dim small">Envelopes only; team profit is before shipping.${all ? '' : ' Click a team to see it on its own.'}</div>`;
    }
    const H = A.habits || { order_totals: [] }, OT = H.order_totals || [];
    const buckets = [[0, 1500, 'Under $15'], [1500, 2500, '$15–24'], [2500, 4000, '$25–39'], [4000, 6000, '$40–59'], [6000, 1e12, '$60 and up']]
      .map(([lo, hi, l]) => [l, OT.filter(c => c >= lo && c < hi).length]);
    const bmax = Math.max(1, ...buckets.map(b => b[1]));
    const g = (l, n, of, tip = '') => `<div class="gl" title="${tip}"><b>${of ? Math.round(100 * n / of) + '%' : '—'}</b><span>${l}<em>${plural(n, 'envelope')}</em></span></div>`;
    const sizes = OT.length ? `<div class="an-card"><h4>Order sizes</h4><div class="an-bars">${buckets.map(b => bar(b[0], b[1], bmax, `${b[1]} · ${pct(b[1], OT.length)}`)).join('')}</div><div class="dim small" style="margin-top:8px">Middle order ${fmt$(H.median)} · average ${fmt$(s.avg)}</div></div>` : '';
    const glance = OT.length ? `<div class="an-card"><h4>At a glance</h4><div class="glance">${g('added a la carte prints', s.ac_env, s.n)}${g('added a keepsake', s.ks_env, s.n)}${g('bought 2+ packages', H.multi_pkg, s.n, 'Siblings, or both sides of the family')}${g('bought no package', H.no_pkg, s.n, 'A la carte or keepsakes only')}<div class="gl"><b>${H.items_avg}</b><span>items per envelope<em>packages, prints and keepsakes</em></span></div></div></div>` : '';
    const pays = A.payments, pmax = Math.max(1, s.n);
    const pay = '<div class="an-bars">' + pays.map(p => bar(esc(p.method), p.envelopes, pmax, `${plural(p.envelopes, 'env')}${p.method === 'Not paid' ? ' · ' + fmt$(p.cents) : ''}`, p.method === 'Not paid' ? 'amb' : 'grn')).join('')
      + (s.short ? bar('Accepted short', s.short_n, pmax, `${plural(s.short_n, 'env')} · ${fmt$(s.short)}`, 'mut') : '')
      + (s.change ? bar('Change to give', s.change_n, pmax, `${plural(s.change_n, 'env')} · ${fmt$(s.change)}`, 'amb') : '')
      + `</div><div class="dim small" style="margin-top:8px">${fmt$(s.paid)} collected · ${fmt$(s.due)} still owed${s.short ? ` · ${fmt$(s.short)} let go` : ''}</div>`;
    const lab = p => p.lab_each == null ? null : p.lab_each;
    const each = p => { const l = lab(p); if (l == null || !p.sold) return l == null ? '<span class="dim" title="No Meridian price for it">not priced</span>' : ''; const avg = p.sales / p.sold, m = (avg - l) / avg; return `<span class="${mc(m)}">${fmt$(avg - l)} · ${Math.round(100 * m)}%</span>`; };
    const items = (list, envs, sales, what) => {
      let tq = 0, ts = 0, tp = 0, tsh = 0;
      const shown = this.anUnsold ? list : list.filter(p => p.sold), hidden = list.length - shown.length;
      const rows = shown.map(p => { const l = lab(p) || 0, pr = p.sales - l * p.sold; tq += p.sold; ts += p.sales; tp += pr; tsh += p.sold_shoot;
        const price = p.with_package != null ? `${fmt$(p.price)}<span class="dim"> · ${fmt$(p.with_package)} w/ pkg</span>` : fmt$(p.price);
        return `<tr class="${p.sold ? '' : 'none'}"><td>${esc(p.label)}</td><td>${price}</td><td>${p.sold}</td>${one ? `<td class="dim">${p.sold_shoot}</td>` : ''}<td>${fmt$(p.sales)}</td><td>${p.sold ? each(p) : ''}</td><td class="${p.sold ? mc(p.sales ? pr / p.sales : null) : ''}">${p.sold ? fmt$(pr) : ''}</td></tr>`; }).join('');
      return `<table class="an-t"><tr><th>Item</th><th>Price</th><th>Sold</th>${one ? '<th title="Sold across the whole shoot">Shoot</th>' : ''}<th>Sales</th><th>Profit each</th><th>Profit</th></tr>${rows}<tr class="tot"><td>Total</td><td></td><td>${tq}</td>${one ? `<td class="dim">${tsh}</td>` : ''}<td>${fmt$(ts)}</td><td>${ts ? Math.round(100 * tp / ts) + '%' : ''}</td><td>${fmt$(tp)}</td></tr></table>
        ${hidden || this.anUnsold ? `<div class="an-more">${this.anUnsold ? '' : `+${hidden} didn’t sell · `}<button class="linkish" data-ord="an-unsold">${this.anUnsold ? 'hide the ones that didn’t sell' : 'show'}</button></div>` : ''}
        <div class="dim small">${envs} of ${s.n} envelopes ${what} (${pct(envs, s.n)})${envs ? ` · average ${fmt$(Math.round(sales / envs))} each when they did` : ''}</div>`;
    };
    const pkProfit = p => { const l = lab(p); return l == null ? 0 : p.sales - l * p.sold; };
    const pkTotP = pk.reduce((t, p) => t + Math.max(0, pkProfit(p)), 0), pkTotS = pk.reduce((t, p) => t + p.sales, 0);
    const pkShown = this.anUnsold ? pk : pk.filter(p => p.sold), pkHidden = pk.length - pkShown.length;
    const pkRows = pkShown.map(p => { const l = lab(p), pr = pkProfit(p);
      return `<tr class="${p.sold ? '' : 'none'}"><td>${esc(p.label)}</td><td>${fmt$(p.price)}</td><td class="pk-bar"><div class="an-hb"><div class="tr"><div style="width:${100 * p.sold / mx}%"></div></div></div></td><td class="nw">${p.sold} · ${pct(p.sold, pkN)}</td><td>${l == null ? '<span class="dim">not priced</span>' : fmt$(l)}</td><td>${p.sold ? each(p) : ''}</td><td class="${p.sold ? mc(p.sales ? pr / p.sales : null) : ''}">${p.sold && l != null ? fmt$(pr) : ''}</td><td class="pk-share">${p.sold && l != null && pkTotP ? `<span class="sh"><i style="width:${100 * Math.max(0, pr) / pkTotP}%"></i></span>${Math.round(100 * Math.max(0, pr) / pkTotP)}%` : ''}</td></tr>`; }).join('')
      + `<tr class="tot"><td>All packages</td><td></td><td></td><td>${pkN}</td><td></td><td>${pkTotS ? Math.round(100 * pkTotP / pkTotS) + '%' : ''}</td><td>${fmt$(pkTotP)}</td><td></td></tr>`;
    const unp = A.lab_unpriced.length ? `<div class="banner amber inline" style="margin:0">Lab cost leaves out ${esc(A.lab_unpriced.join(', '))}: no Meridian price for ${A.lab_unpriced.length > 1 ? 'them' : 'it'} yet (Prices…).</div>` : '';
    const pkMore = pkHidden || this.anUnsold ? `<div class="an-more">${this.anUnsold ? '' : `+${pkHidden} didn’t sell (${esc(pk.filter(p => !p.sold).map(p => p.label.replace(/^Package /, '')).join(', '))}) · `}<button class="linkish" data-ord="an-unsold">${this.anUnsold ? 'hide the ones that didn’t sell' : 'show'}</button></div>` : '';
    const notes = this.anNotes(A, one, all, prev);
    box.innerHTML = `<div class="an-body">${unp}
      <div class="an-kpis four">${kp.map(k => `<div class="an-k ${k[3] || ''}" title="${esc(k[4] || '')}"><i>${k[0]}</i><b>${k[1]}</b><s>${k[2]}</s></div>`).join('')}</div>
      ${notes.length ? `<div class="an-notes"><h4>What stands out</h4><ul>${notes.map(n => `<li>${n}</li>`).join('')}</ul></div>` : ''}
      ${all ? this.anRankHTML(A) : !one ? this.anTimeHTML(s, prev) : ''}
      <div class="an-card c-pk"><h4>Packages <span class="h-note">${plural(pkN, 'package')} sold</span></h4><table class="an-t pk-t"><tr><th>Package</th><th>Price</th><th class="pk-bar">Sold</th><th></th><th>Lab cost</th><th>Profit each</th><th>Profit total</th><th>Share of profit</th></tr>${pkRows}</table>${pkMore}</div>
      <div class="an-row r2b"><div class="an-card">${cmp}</div><div class="an-card"><h4>Money in</h4>${pay}</div></div>
      <div class="an-row r2"><div class="an-card c-ac"><h4>A la carte</h4>${items(ac, s.ac_env, s.ac_sales, 'added a la carte prints')}</div><div class="an-card c-ks"><h4>Keepsakes</h4>${items(ks, s.ks_env, s.ks_sales, 'added a keepsake')}</div></div>
      ${sizes || glance ? `<div class="an-row r2">${sizes}${glance}</div>` : ''}
    </div>`;
    this.wiRight();
    this.wiPaint();
  },
  // The same league's shoot from before ("Montpelier Fall Sports 2025" for "... 2026"), to compare against.
  anPrevShoot() {
    const cur = this.shoot(); if (!cur) return null;
    const norm = n => String(n || '').toLowerCase().replace(/\b(19|20)\d\d\b/g, '').replace(/[^a-z]+/g, ' ').trim();
    const key = norm(cur.name); if (!key) return null;
    const before = (this.shoots || []).filter(x => x.id !== cur.id && norm(x.name) === key && (!cur.date || !x.date || x.date < cur.date));
    return before.sort((a, b) => String(b.date).localeCompare(String(a.date)))[0] || null;
  },
  anPrevData() {
    const pv = this.anPrevShoot(); if (!pv) return null;
    if (this.anPrev && this.anPrev.id === pv.id) return this.anPrev.data ? { ...this.anPrev.data, name: pv.name } : null;
    this.anPrev = { id: pv.id, data: null };
    api('/api/orders/analysis', { shoot_id: pv.id, team: null }).then(r => { if (this.anPrev && this.anPrev.id === pv.id && r.selection && r.selection.n) { this.anPrev.data = r; if (S.module === 'orders' && this.view === 'an') this.anPaint(); } }).catch(() => {});
    return null;
  },
  // ---------- your time: profit per hour ----------
  HOUR_PARTS: [['shoot', 'Shooting'], ['edit', 'Culling & editing'], ['lab', 'Envelopes & lab'], ['delivery', 'Delivery']],
  hoursOf(sh) { try { return JSON.parse((sh && sh.hours) || '{}') || {}; } catch { return {}; } },
  hoursTotal(sh) { return Object.values(this.hoursOf(sh)).reduce((t, v) => t + (+v || 0), 0); },
  anTimeHTML(s, prev) {
    const sh = this.shoot(); if (!sh) return '';
    const H = this.hoursOf(sh), tot = this.hoursTotal(sh);
    const fmtH = h => (Math.round(h * 100) / 100).toString();
    const inputs = this.HOUR_PARTS.map(([k, l]) => `<label>${l}<input type="number" min="0" step="0.25" inputmode="decimal" data-hrs="${k}" value="${H[k] != null ? H[k] : ''}" placeholder="0" onchange="Ord.setHours()"></label>`).join('');
    const pv = this.anPrevShoot(), pvH = pv ? this.hoursTotal(pv) : 0, ps = prev && prev.selection;
    const cmp = (now, before, label) => before == null ? '' : `<div class="sub">${(d => `<span class="${d >= 0 ? 'an-up' : 'an-dn'}">${d >= 0 ? '▲' : '▼'} ${fmt$(Math.abs(d))}</span>`)(Math.round(now - before))} vs ${esc(prev.name)} (${fmt$(Math.round(before))})</div>`;
    const perHr = tot ? s.profit / tot : null, perEnv = s.n ? s.profit / s.n : null;
    const prevHr = ps && pvH ? ps.profit / pvH : null, prevEnv = ps && ps.n ? ps.profit / ps.n : null;
    return `<div class="an-time">
      <div class="an-card"><h4>Your time on this shoot</h4><div class="hrs">${inputs}</div>
        <div class="tot">${tot ? `= <b>${fmtH(tot)} hour${tot === 1 ? '' : 's'}</b> · saved with the shoot` : 'Type your hours to see what this shoot paid per hour.'}</div></div>
      <div class="an-card"><h4>Profit per hour</h4>${perHr == null ? '<div class="big dim">—</div><div class="sub">needs your hours</div>' : `<div class="big ${perHr < 0 ? 'an-neg' : 'g'}">${fmt$(Math.round(perHr))}</div>${cmp(perHr, prevHr)}<div class="sub">${fmt$(s.profit)} kept ÷ ${fmtH(tot)} hours</div>`}</div>
      <div class="an-card"><h4>Profit per envelope</h4>${perEnv == null ? '<div class="big dim">—</div>' : `<div class="big">${fmt$(Math.round(perEnv))}</div>${cmp(perEnv, prevEnv)}<div class="sub">${fmt$(s.profit)} kept ÷ ${plural(s.n, 'envelope')}</div>`}</div>
    </div>`;
  },
  async setHours() {
    const sh = this.shoot(); if (!sh) return;
    const hours = {}; document.querySelectorAll('[data-hrs]').forEach(i => { hours[i.dataset.hrs] = i.value; });
    try { const r = await api('/api/orders/shoot-hours', { shoot_id: sh.id, hours }); sh.hours = Object.keys(r.hours).length ? JSON.stringify(r.hours) : ''; }
    catch (e) { return toast(esc(e.message)); }
    const f = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.hrs;
    this.anPaint();
    if (f) { const i = document.querySelector(`[data-hrs="${f}"]`); if (i) i.focus(); }
  },
  anRankHTML(A) {
    const rows = (A.per_shoot || []).filter(r => r.envelopes);
    if (!rows.length) return '';
    const withH = rows.filter(r => r.hours > 0).map(r => ({ ...r, ph: r.profit / r.hours })).sort((a, b) => b.ph - a.ph);
    const noH = rows.filter(r => !(r.hours > 0)).sort((a, b) => String(b.date).localeCompare(String(a.date)));
    const max = Math.max(1, ...withH.map(r => r.ph));
    const tr = r => `<tr class="click" data-anshoot="${r.id}"><td>${esc(r.name)}</td><td class="n">${r.hours > 0 ? (Math.round(r.hours * 100) / 100) : '—'}</td><td class="n">${r.envelopes}</td><td class="n">${fmt$(r.profit)}</td>
      <td class="l">${r.ph != null ? `<span class="rk-bar"><i style="width:${Math.max(2, 100 * r.ph / max).toFixed(1)}%"></i></span>${fmt$(Math.round(r.ph))}` : '<span class="dim">add hours to rank it</span>'}</td><td class="n">${fmt$(Math.round(r.profit / r.envelopes))}</td></tr>`;
    return `<div class="an-card"><h4>Profit per hour, every shoot <span class="h-note">${withH.length ? 'best first' : 'open a shoot and type its hours to rank it'}</span></h4>
      <table class="an-t rk"><tr><th>Shoot</th><th class="n">Hours</th><th class="n">Envelopes</th><th class="n">You keep</th><th class="l">Profit per hour</th><th class="n">Per envelope</th></tr>
      ${withH.map(tr).join('')}${noH.map(r => tr({ ...r, ph: null })).join('').replace(/<tr class="click"/g, '<tr class="click dim-row"')}</table>
      <div class="dim small">Profit is after lab cost and shipping. Click a shoot to open it.</div></div>`;
  },
  // A few plain sentences from the numbers; each one only when there's enough to say it.
  anNotes(A, one, all, prev) {
    const s = A.selection, out = [], P = A.products;
    const pk = P.filter(p => p.kind === 'package'), pkN = pk.reduce((t, p) => t + p.sold, 0);
    if (pkN >= 8 && pk.length >= 2) {
      const top = pk.slice().sort((a, b) => b.sold - a.sold)[0];
      const share = top.sold / pkN;
      if (share >= 0.3) out.push(`<b>${esc(top.label)}</b> was ${Math.round(100 * share)}% of the packages sold (${top.sold} of ${pkN}).`);
      const low = pk.filter(p => p !== top && p.sold <= Math.max(1, Math.floor(pkN * 0.04)));
      const and = l => l.length > 1 ? l.slice(0, -1).join(', ') + ' and ' + l[l.length - 1] : l[0];
      if (low.length >= 2) out.push(`<b>Packages ${esc(and(low.map(p => p.label.replace(/^Package /, ''))))}</b> sold ${low.reduce((t, p) => t + p.sold, 0)} between them${pk.length - low.length >= 3 ? ' — fewer packages might be worth trying' : ''}.`);
    }
    if (s.n >= 10) {
      const ks = P.filter(p => p.kind === 'keepsake' && p.sold).sort((a, b) => b.sold - a.sold);
      let k = `Keepsakes were in <b>${Math.round(100 * s.ks_env / s.n)}%</b> of envelopes (${s.ks_env} of ${s.n})`;
      if (prev && prev.selection && prev.selection.n) { const p0 = Math.round(100 * prev.selection.ks_env / prev.selection.n), p1 = Math.round(100 * s.ks_env / s.n); if (p0 !== p1) k += `, ${p1 > p0 ? 'up' : 'down'} from ${p0}% at ${esc(prev.name)}`; }
      if (s.ks_env) out.push(k + (ks.length ? `; ${esc(ks[0].label)} led with ${ks[0].sold}.` : '.'));
    }
    if (!one && !all) {
      const ts = A.teams.filter(t => t.n >= 3 && t.team !== 'No team');
      if (ts.length >= 3) {
        const by = ts.slice().sort((a, b) => b.avg - a.avg), hi = by[0], lo = by[by.length - 1];
        if (hi.avg - lo.avg >= 500) out.push(`<b>${esc(hi.team)}</b> averaged ${fmt$(hi.avg)} an envelope, the best team; <b>${esc(lo.team)}</b> was lowest at ${fmt$(lo.avg)}.`);
      }
    }
    const H = A.habits || {}, OT = (H.order_totals || []).slice().sort((a, b) => a - b);
    if (OT.length >= 10) {
      const q1 = OT[Math.floor(OT.length * .25)], q3 = OT[Math.floor(OT.length * .75)], big = OT.filter(c => c >= 7500).length;
      out.push(`Half of the orders were between <b>${fmt$(q1)}</b> and <b>${fmt$(q3)}</b>${big ? `; ${plural(big, 'envelope')} ${big === 1 ? 'was' : 'were'} $75 or more` : ''}.`);
    }
    if (s.due > 0) { const np = A.payments.find(p => p.method === 'Not paid'); if (np && np.envelopes) out.push(`<span class="an-lo">${plural(np.envelopes, 'envelope')} still owe${np.envelopes === 1 ? 's' : ''} ${fmt$(s.due)}.</span>`); }
    return out.slice(0, 5);
  },
  // What if lives in the right pane while Analysis is open, next to the numbers.
  wiRight() {
    if (S.module !== 'orders' || this.view !== 'an' || !this.an || !this.an.selection || !this.an.selection.n) return;
    if ($('#right #anWi')) return;
    $('#right').innerHTML = `<div class="scroll an-wi-pane"><div class="wi" id="anWi"><h4 class="wh">What if <span class="tag">try new prices</span></h4>
      <div class="dim small" style="margin-bottom:8px">Change a price to see what this ${this.anScope === 'all' ? 'season' : 'shoot'} would have made.</div>
      <div class="wl" id="wiT"></div>
      <div class="drop"><div>Families who stop buying an item when its price goes up</div><div class="dr"><input type="range" data-wi-drop min="0" max="50" step="5" value="${this.wiDrop}"><b id="wiDropV">${this.wiDrop}%</b></div></div>
      <table class="an-t wsum" id="wiSum"></table><div id="wiBe" class="be"></div><span id="wiMini" hidden></span>
      <div class="wbtn"><button class="btn sm" data-ord="wi-reset">Reset prices</button></div></div></div>`;
  },
  // What if: parts are {key, label, now, sold, lab}; a la carte has an alone part and a with-package part.
  wiParts() {
    const A = this.an; if (!A) return [];
    const out = [];
    for (const p of A.products) {
      const l = p.lab_each || 0;
      if (p.kind === 'alacarte') {
        out.push({ key: p.id, p, label: p.label, now: p.price, sold: p.sold_alone, lab: l });
        out.push({ key: p.id + ':pkg', p, label: p.label + ' (with a package)', now: p.with_package, sold: p.sold_with_pkg, lab: l });
      } else out.push({ key: p.id, p, label: p.label, now: p.price, sold: p.sold, lab: l });
    }
    return out;
  },
  wiPaint() {
    const A = this.an; if (!A || !$('#wiT')) return;
    const s = A.selection, one = this.anScope !== 'all' && A.team != null, d = this.wiDrop / 100;
    const parts = this.wiParts(), by = new Map(parts.map(x => [x.key, x]));
    let dS = 0, dL = 0; const be = [];
    for (const x of parts) {
      const np = this.wi[x.key]; if (np == null || np === x.now) continue;
      const keep = np > x.now ? x.sold * (1 - d) : x.sold;
      dS += keep * np - x.sold * x.now; dL -= (x.sold - keep) * x.lab;
      if (!x.sold) continue;
      const m0 = x.now - x.lab, m1 = np - x.lab;
      if (np > x.now && m1 > 0) { const f = Math.max(0, 1 - m0 / m1), lose = Math.floor(x.sold * f + 1e-9);
        be.push(`<div>${esc(x.label)} at ${fmt$(np)}: you could lose up to <b>${Math.round(100 * f)}% of its buyers</b> (${lose >= 1 ? `${lose} of ${x.sold}` : `under 1 of ${x.sold}`} here) and still make the same profit.</div>`); }
      else if (np < x.now) be.push(m1 > 0 ? `<div>${esc(x.label)} at ${fmt$(np)}: needs <b>${Math.ceil(x.sold * m0 / m1 - 1e-9)} buyers</b> instead of ${x.sold} to make the same profit.</div>` : `<div>${esc(x.label)} at ${fmt$(np)}: <b>loses money</b> on every one after lab cost.</div>`);
    }
    const inp = x => `<input class="${this.wi[x.key] != null && this.wi[x.key] !== x.now ? 'ch' : ''}" data-wi="${esc(x.key)}" value="${((this.wi[x.key] ?? x.now) / 100).toFixed(2)}" inputmode="decimal" spellcheck="false">`;
    const chg = (...xs) => { let t = 0, any = false; for (const x of xs) { const np = this.wi[x.key]; if (np == null || np === x.now || !x.sold) continue; any = true; const keep = np > x.now ? x.sold * (1 - d) : x.sold; t += keep * np - x.sold * x.now; }
      return any ? `<span class="${t > .5 ? 'an-up' : t < -.5 ? 'an-dn' : 'dim'}">${Math.abs(t) < .5 ? '$0.00' : (t > 0 ? '+' : '') + fmt$(Math.round(t))}</span>` : '<span class="dim">—</span>'; };
    const grp = (title, kind) => {
      const ps = A.products.filter(p => p.kind === kind); if (!ps.length) return '';
      if (kind === 'alacarte') return `<table class="an-t"><tr><th>${title}</th><th title="Price bought on its own">Alone</th><th title="Price with a package in the envelope">With pkg</th><th>Sold</th><th>Change</th></tr>${ps.map(p => { const a = by.get(p.id), b = by.get(p.id + ':pkg'); return `<tr><td>${esc(p.label)}</td><td>${inp(a)}</td><td>${inp(b)}</td><td title="${a.sold} alone · ${b.sold} with a package">${p.sold}</td><td>${chg(a, b)}</td></tr>`; }).join('')}</table>`;
      return `<table class="an-t"><tr><th>${title}</th><th>Now</th><th>New</th><th>Sold</th><th>Change</th></tr>${ps.map(p => { const x = by.get(p.id); return `<tr><td>${esc(kind === 'package' ? p.label.replace(/^Package\s+/, '') : p.label)}</td><td>${fmt$(x.now)}</td><td>${inp(x)}</td><td>${x.sold}</td><td>${chg(x)}</td></tr>`; }).join('')}</table>`;
    };
    $('#wiT').innerHTML = grp('Packages', 'package') + grp('A la carte', 'alacarte') + grp('Keepsakes', 'keepsake');
    const os = s.sales, ol = s.lab, ship = s.shipping, op = os - ol - ship, ns = os + dS, nl = ol + dL, np = ns - nl - ship;
    const row = (k, o, n, inv) => { const dd = n - o; return `<tr><td>${k}</td><td>${fmt$(Math.round(o))}</td><td><b>${fmt$(Math.round(n))}</b></td><td class="${Math.abs(dd) < .5 ? 'dim' : (dd > 0) !== !!inv ? 'an-up' : 'an-dn'}">${Math.abs(dd) < .5 ? '—' : (dd > 0 ? '+' : '') + fmt$(Math.round(dd))}</td></tr>`; };
    const p0 = os ? 100 * op / os : 0, p1 = ns ? 100 * np / ns : 0;
    $('#wiSum').innerHTML = `<tr><th></th><th>Now</th><th>New prices</th><th>Change</th></tr>${row('Sales', os, ns)}${row('Lab cost', ol, nl, 1)}${one ? '' : row('Shipping', ship, ship)}${row(one ? 'Profit (before shipping)' : 'Profit', op, np)}<tr><td>Profit %</td><td>${p0.toFixed(1)}%</td><td><b>${p1.toFixed(1)}%</b></td><td class="${Math.abs(p1 - p0) < .05 ? 'dim' : p1 > p0 ? 'an-up' : 'an-dn'}">${Math.abs(p1 - p0) < .05 ? '—' : (p1 > p0 ? '+' : '') + (p1 - p0).toFixed(1) + ' pts'}</td></tr>`;
    $('#wiBe').innerHTML = be.length ? `<div class="dim small" style="margin-bottom:4px">BREAK-EVEN</div>${be.join('')}` : '<div class="dim">Type a new price to see what it does to this shoot’s sales and profit.</div>';
    const n = Object.keys(this.wi).filter(k => by.has(k) && this.wi[k] !== by.get(k).now).length;
    $('#wiMini').innerHTML = n ? `${plural(n, 'price')} changed · profit <b>${np - op >= 0 ? '+' : ''}${fmt$(Math.round(np - op))}</b>` : 'No price changes';
    $('#wiDropV').textContent = this.wiDrop + '%';
  },
  wiSet(key, v) {
    const x = this.wiParts().find(p => p.key === key); if (!x) return;
    const c = Math.round(parseFloat(String(v).replace(/[$,\s]/g, '')) * 100);
    if (!isFinite(c) || c < 0 || c === x.now) delete this.wi[key]; else this.wi[key] = c;
    this.wiPaint();
  },
  wiToggle() { prefs.ordWhatIfClosed = !prefs.ordWhatIfClosed; savePrefs(); const c = $('#anWi'); if (c) { c.classList.toggle('closed', prefs.ordWhatIfClosed); c.querySelector('.wclose').textContent = prefs.ordWhatIfClosed ? 'Show' : 'Hide'; } },
  // ---------- drawing ----------
  left() {
    // Archived shoots stay hidden unless the switch is on; the open shoot always shows.
    const nArch = this.shoots.filter(s => s.archived).length;
    const showArch = !!(prefs.ordShowArchived);
    const sh = this.shoots.filter(s => showArch || !s.archived || s.id === this.sid).map(s => `<div class="row ${s.id === this.sid ? 'on' : ''} ${s.archived ? 'arch' : ''}" data-oshoot="${s.id}" ${s.archived ? 'title="Archived"' : ''}><span class="two"><span class="lbl">${esc(s.name)}${s.archived ? '<span class="arch-tag">Archived</span>' : ''}</span><span class="sub">${esc([fmtDay(s.date), s.season && !(s.date && String(s.season).trim() === String(s.date).slice(0, 4)) ? s.season : ''].filter(Boolean).join(' · ') || ' ')}</span></span><span class="row-acts"><button data-ord="edit-shoot" data-id="${s.id}" title="Edit shoot">✎</button></span><span class="cnt">${s.n || ''}</span></div>`).join('');
    let html = sectionHTML('o-shoots', 'Shoots', (sh || '<div class="hint">A shoot is one picture day: its envelopes, teams and lab order.</div>') + `<div class="pad shoot-foot"><button class="btn sm" data-ord="new-shoot">New shoot…</button>${nArch ? `<label class="arch-sw" title="Archived shoots are kept; this only hides them from the list"><input type="checkbox" data-ord-arch ${showArch ? 'checked' : ''}> Show archived (${nArch})</label>` : ''}</div>`);
    if (this.d) {
      // the same group photo on two teams is almost always a typo'd photo number
      const dupImg = new Map(); for (const t of this.d.teams) if (t.image) { const k = t.image.toLowerCase(); dupImg.set(k, [...(dupImg.get(k) || []), t.name]); }
      for (const [k, v] of [...dupImg]) if (v.length < 2) dupImg.delete(k);
      const team = x => `<div class="row ${this.team === x.name ? 'on' : ''} ${x.planned ? 'planned' : ''}" data-oteam="${esc(x.name)}" data-tdrag="${esc(x.name)}" ${x.planned ? 'title="On last year\'s list - no envelopes yet this year"' : ''}><span class="two"><span class="lbl">${esc(x.name)}</span><span class="sub ${x.image && dupImg.has(x.image.toLowerCase()) ? 'dup' : ''}" ${x.image && dupImg.has(x.image.toLowerCase()) ? `title="Another team has the same group photo: ${esc(dupImg.get(x.image.toLowerCase()).filter(n => n !== x.name).join(', '))}"` : ''}>${x.image ? 'Group photo ' + esc(x.image) + (dupImg.has(x.image.toLowerCase()) ? ` · used ${dupImg.get(x.image.toLowerCase()).length === 2 ? 'twice' : dupImg.get(x.image.toLowerCase()).length + ' times'}` : '') : x.planned ? 'From last year · no envelopes yet' : 'No group photo yet'}</span></span><span class="row-acts"><button data-ord="team-up" data-team="${esc(x.name)}" title="Move up">↑</button><button data-ord="team-down" data-team="${esc(x.name)}" title="Move down">↓</button><button data-ord="team-photo" data-team="${esc(x.name)}" title="Set the group photo">▣</button><button data-ord="team-rename" data-team="${esc(x.name)}" title="Rename team">✎</button>${x.planned ? `<button data-ord="team-drop" data-team="${esc(x.name)}" title="No ${esc(x.name)} this year - take it off this shoot's list">✕</button>` : ''}</span><span class="cnt">${x.count}</span></div>`;
      html += sectionHTML('o-teams', 'Teams', `<div class="row ${this.team === 'all' ? 'on' : ''}" data-oteam="all"><span class="lbl">All teams</span><span class="cnt">${this.d.orders.length}</span></div>${this.d.teams.map(team).join('')}`, `<button class="hdr-btn" data-ord="team-list" title="See and edit the whole team list: names, coaches, order">List…</button>${this.d.teams.length > 1 ? `<button class="hdr-btn az" data-teamaz title="Sort the teams A–Z (drag a team, or use ↑ ↓, to put them in your own order)">A–Z</button>` : ''}`);
      const T = this.d.totals;
      html += sectionHTML('o-totals', 'Totals', this.totalsHTML(this.d.totals));
    }
    // Shoots stay at the top and Totals at the bottom; Teams scrolls in between.
    const keep = {}; for (const id of ['o-shoots', 'o-teams', 'o-totals']) { const b = $(`#left [data-sec="${id}"] > .body`); if (b) keep[id] = b.scrollTop; }
    $('#left').innerHTML = `<div class="ord-left">${html}</div><div class="left-foot"><button class="btn primary big" data-ord="new" ${this.sid ? '' : 'disabled'}>New envelope</button></div>`;
    for (const id in keep) { const b = $(`#left [data-sec="${id}"] > .body`); if (b) b.scrollTop = keep[id]; }
    const on = $('#left [data-sec="o-teams"] .row.on'); if (on && this._teamScroll !== this.team) { this._teamScroll = this.team; on.scrollIntoView({ block: 'nearest' }); }
    this.fitLeft();
    const so = $('#left [data-sec="o-shoots"] .row.on'); if (so && this._shootScroll !== this.sid) { this._shootScroll = this.sid; so.scrollIntoView({ block: 'nearest' }); }
  },
  // Totals: the few numbers you glance at while typing envelopes, then only what needs fixing.
  // Lab cost, what you keep and profit % live in Analysis; shipping is typed on the Lab order tab.
  totalsHTML(T) {
    const todo = [];
    const gaps = this.envGapsHTML(), noName = this.noNameHTML();
    if (gaps) todo.push(gaps);
    if (noName) todo.push(noName);
    if (T.change_cents) todo.push(`<span>Change to give (${T.change_n})</span><b class="due">${fmt$(T.change_cents)}</b>`);
    if (T.no_photo) todo.push(`<span>Need a photo</span><b class="env-gaps"><button class="linkish due" data-ord="tot-nophoto" title="Show the envelopes with no photo first">${T.no_photo}</button></b>`);
    { const sc = this.d && this.d.school;
      if (sc && sc.needed && !sc.sent_at) todo.push(`<span title="One 5×7 of every team, zipped and emailed to the school">School team 5×7s</span><b class="env-gaps"><button class="linkish due" data-ord="school">not sent</button></b>`);
      else if (sc && sc.sent_at && ((sc.changed || []).length || (sc.new || []).length)) todo.push(`<span title="${esc([...(sc.changed || []), ...(sc.new || [])].join(', '))}">School team 5×7s</span><b class="env-gaps"><button class="linkish due" data-ord="school">${(sc.changed || []).length + (sc.new || []).length} changed since sent</button></b>`); }
    if (T.glasses) todo.push(`<span title="Envelopes marked Glasses: photos to fix in Retouch">Glasses to retouch</span><b class="env-gaps"><button class="linkish" data-ord="tot-glasses" title="Show the glasses envelopes first">${T.glasses}</button></b>`);
    const due = T.due_cents > 0;
    const mini = `<div class="tot-mini"><span>Sales <b>${fmt$(T.total_cents)}</b></span><span>Collected <b>${fmt$(T.paid_cents)}</b></span><span>Due <b class="${due ? 'due' : 'ok'}">${due ? fmt$(T.due_cents) : 'All paid'}</b></span>${todo.length ? `<span class="due">${todo.length} to fix</span>` : ''}<button class="linkish" data-ord="tot-full">Show all</button></div>`;
    return `${mini}<div class="tot-grid">
      <span>Envelopes</span><b>${T.orders}</b>
      <span>Sales</span><b class="big">${fmt$(T.total_cents)}</b>
      ${T.extras && T.extras.count ? `<span class="sub">Families</span><b class="sub">${fmt$(T.family_cents)}</b><span class="sub link" data-ord="extras" title="Prints for the school, the park, teachers…">School &amp; other (${T.extras.count})</span><b class="sub link" data-ord="extras">${fmt$(T.extras.sales_cents)}</b>` : ''}
      <span>Collected</span><b>${fmt$(T.paid_cents)}</b>
      <span>Still due${T.unpaid ? ` (${T.unpaid})` : ''}</span><b class="${due ? 'due' : 'ok'}">${due ? fmt$(T.due_cents) : 'All paid'}</b>
      </div>
      ${todo.length ? `<div class="tot-todo"><div class="tt">Needs attention</div><div class="tot-grid">${todo.join('')}</div></div>` : T.orders ? '<div class="tot-ok">✓ Nothing to fix</div>' : ''}
      <button class="linkish tot-an" data-ord="to-an">More in Analysis →</button>`;
  },
  // A short window: Totals shrinks to one line (Sales, Keep, Profit, Due) so Teams keeps some rows.
  fitLeft() {
    const sec = $('#left [data-sec="o-totals"]'), tb = $('#left [data-sec="o-teams"]:not(.closed) > .body'); if (!sec) return;
    sec.classList.remove('mini');
    if (this.totFull || !tb) return;
    if (tb.clientHeight < 115) sec.classList.add('mini');
  },
  center() {
    const v = $('#modView'); v.dataset.mod = 'orders';
    if (!this.sid) {
      v.innerHTML = `<div class="ord-scroll"><div class="ord-empty"><h3>Orders</h3><p>Type in picture-day envelopes, track who has paid, and build the lab order<br>from just the photos and sizes families bought.</p><br><button class="btn primary lg" data-ord="new-shoot">New shoot…</button></div></div>`;
      return;
    }
    if (this.view === 'lab') return this.labCenter(v);
    if (this.view === 'an') return this.anCenter(v);
    const s = this.shoot() || {};
    v.innerHTML = `<div class="ord-head"><span class="ttl">${esc(s.name)}${this.team !== 'all' ? ' · ' + esc(this.team) : ''}</span><span class="muted small" id="ordCount"></span><div class="tb-spacer"></div>
      <input type="search" data-oq placeholder="Search names, photos, packages  ( / )" value="${esc(this.q)}" spellcheck="false"><button class="btn sm" data-ord="select-all" title="Select every envelope shown, to set their team or coach at once (Ctrl+A). Ctrl-click or Shift-click rows to pick some.">Select all</button><button class="btn sm primary" data-ord="new">New envelope (N)</button></div>
      <div class="ord-scroll" id="ordRows"></div><div class="ord-totbar" id="ordTotBar"></div>`;
    this.paintRows();
  },
  paintRows() {
    const box = $('#ordRows'); if (!box || S.module !== 'orders') return;
    const rows = this.rows(); const cnt = $('#ordCount'); if (cnt) cnt.textContent = plural(rows.length, 'envelope');
    const th = (k, l, cls = '') => `<th class="${cls}" data-osort="${k}">${l}${this.sort.k === k ? `<span class="arr">${this.sort.dir > 0 ? '▲' : '▼'}</span>` : ''}</th>`;
    const y = box.scrollTop;
    // An envelope that's open but not saved yet (nothing typed) still gets a row, so N visibly does something.
    const d = this.draft, fresh = this.sel === 'new' && d && !d.id;
    const newRow = !fresh ? '' : `<tr class="sel new-row" data-onew><td class="env">${esc(d.envelope)}</td><td colspan="11">${d.athlete.trim() ? esc(d.athlete) : '<span class="new-tag">New</span><span class="dim">Type the athlete’s name or press a package letter. It saves as soon as you do.</span>'}</td></tr>`;
    box.innerHTML = rows.length || fresh ? `<table class="otbl"><thead><tr>${th('env', '#', 'env')}${th('athlete', 'Athlete')}${th('team', 'Team')}<th>Order</th>${th('image', 'Photo')}${this.thumbs() ? `<th class="o-thc"><button class="linkish o-thtog" data-ord="thumbs" title="Hide the photo thumbnails">▣</button></th>` : `<th class="o-thc off"><button class="linkish o-thtog" data-ord="thumbs" title="Show the photo thumbnails">▢</button></th>`}${th('glasses', 'Glasses')}${th('total', 'Total', 'amt')}${th('lab', 'Lab', 'amt')}${th('profit', 'Profit', 'amt')}${th('ppct', 'Profit %', 'amt')}${th('due', 'Due', 'amt')}</tr></thead><tbody>${rows.map(o => this.rowHTML(o)).join('')}${newRow}</tbody>${this.totalsRow(rows)}</table>`
      : `<div class="ord-empty">${this.d && this.d.orders.length ? 'No envelopes match.' : '<h3>No envelopes yet</h3><p>Press <kbd>N</kbd> to type in the first one, or import the website’s order CSV.</p>'}</div>`;
    this.pinTotals(box);
    box.scrollTop = y;
    const nr = fresh && $('tr[data-onew]', box);
    if (nr && this._flashNew) { this._flashNew = false; nr.scrollIntoView({ block: 'nearest' }); nr.classList.add('flash'); }
  },
  // The totals row sits in its own bar under the list (not over it), lined up with the columns above.
  // Hovering a row's thumbnail shows it bigger (a click opens the full Preview window).
  thumbHover(img) {
    let pop = $('#othPop');
    if (!img) { if (pop) pop.hidden = true; return; }
    if (!pop) { pop = document.createElement('div'); pop.id = 'othPop'; pop.className = 'oth-pop'; document.body.appendChild(pop); }
    pop.innerHTML = `<img src="${img.src}" alt=""><span>${esc((img.title || '').split(' — ')[0])}</span>`;
    pop.hidden = false;
    const r = img.getBoundingClientRect(), W = 200, H = 268;
    let x = r.right + 10; if (x + W > innerWidth - 8) x = r.left - W - 10;
    let y = r.top + r.height / 2 - H / 2; y = Math.max(8, Math.min(innerHeight - H - 8, y));
    pop.style.left = x + 'px'; pop.style.top = y + 'px';
  },
  pinTotals(box) {
    this.thumbHover(null);  // the rows were just redrawn
    const bar = $('#ordTotBar'); if (!bar) return;
    // the row stays in the list's table, collapsed, so the columns are still sized to fit it
    const tf = $('tfoot:not(.ghost)', box);
    if (tf) { this.totHTML = tf.outerHTML; tf.classList.add('ghost'); } else if (!$('table', box)) this.totHTML = '';
    if (!this.totHTML) { bar.innerHTML = ''; bar.hidden = true; return; }
    const tbl = $('table', box); if (!tbl) { bar.innerHTML = ''; bar.hidden = true; return; }
    const ws = [...tbl.querySelectorAll('thead th')].map(t => t.getBoundingClientRect().width);
    bar.hidden = false;
    bar.innerHTML = `<table class="otbl tot-only" style="width:${tbl.getBoundingClientRect().width}px"><colgroup>${ws.map(w => `<col style="width:${w}px">`).join('')}</colgroup>${this.totHTML}</table>`;
    bar.scrollLeft = box.scrollLeft;
    if (!box._totWired) {
      box._totWired = true;
      box.addEventListener('mouseover', e => { const i = e.target.closest && e.target.closest('img.o-th'); if (i) this.thumbHover(i); });
      box.addEventListener('mouseout', e => { if (e.target.closest && e.target.closest('img.o-th')) this.thumbHover(null); });
      box.addEventListener('scroll', () => this.thumbHover(null), { passive: true });
      box.addEventListener('scroll', () => { const b = $('#ordTotBar'); if (b) b.scrollLeft = box.scrollLeft; }, { passive: true });
      new ResizeObserver(() => { if ($('#ordTotBar') && $('table', box)) this.pinTotals(box); }).observe(box);
    }
  },
  // Totals of the envelopes in view (all teams, one team, or a search), pinned under the list.
  totalsRow(rows) {
    if (!rows.length) return '';
    const sum = k => rows.reduce((a, o) => a + (o.summary[k] || 0), 0);
    const tot = sum('total_cents'), lab = sum('lab_cents'), keep = sum('keep_cents'), due = sum('due_cents');
    const glasses = rows.filter(o => o.glasses).length, nophoto = rows.filter(o => o.lines.length && !(o.image || o.edited)).length;
    const scope = this.team !== 'all' ? this.team : 'All teams';
    return `<tfoot><tr class="tot-row"><td class="env"></td><td colspan="2"><b>${esc(scope)}</b> · ${plural(rows.length, 'envelope')}${this.q ? ' (search)' : ''}</td><td></td>
      <td class="${nophoto ? 'due' : 'dim'}">${nophoto ? `${nophoto} need a photo` : ''}</td><td class="o-thc"></td><td>${glasses || ''}</td>
      <td class="amt">${fmt$(tot)}</td><td class="amt dim">${fmt$(lab)}</td><td class="amt${keep < 0 ? ' due' : ''}">${fmt$(keep)}</td>
      <td class="amt">${tot ? (100 * keep / tot).toFixed(1) + '%' : '—'}</td><td class="amt ${due > 0 ? 'due' : 'ok'}">${due > 0 ? fmt$(due) : 'All paid'}</td></tr></tfoot>`;
  },
  // Per envelope: sales minus Meridian's estimated lab cost (shipping is one charge for the shoot, in Totals).
  profitCells(s) {
    if (!s.total_cents) return '<td class="amt dim">—</td><td class="amt dim">—</td>';
    const pct = 100 * s.keep_cents / s.total_cents, bad = s.keep_cents < 0 ? ' due' : '';
    const tip = 'Total minus the estimated lab cost. Shipping is in Totals.';
    return `<td class="amt${bad}" title="${tip}">${fmt$(s.keep_cents)}</td><td class="amt${bad}" title="${tip}">${pct.toFixed(1)}%</td>`;
  },
  rowHTML(o) {
    const s = o.summary, pic = o.edited || o.image, ord = [s.packages, s.extras].filter(Boolean).join(' + ');
    const due = s.due_cents > 0 ? `<td class="amt due">${fmt$(s.due_cents)}</td>` : s.change_cents > 0 ? `<td class="amt due" title="Paid ${fmt$(s.handed_cents)}: give back ${fmt$(s.change_cents)} change">Change ${fmt$(s.change_cents)}</td>` : s.short_cents > 0 ? `<td class="amt ok" title="Came up ${fmt$(s.short_cents)} short and you accepted it">Paid <span class="dim">−${fmt$(s.short_cents)}</span></td>` : `<td class="amt ${s.total_cents ? 'ok' : 'dim'}">${s.total_cents ? 'Paid' : '—'}</td>`;
    const on = this.multi.size > 1 ? this.multi.has(o.id) : o.id === this.sel;
    return `<tr data-oid="${o.id}" class="${on ? 'sel' : ''}"><td class="env">${esc(o.envelope)}<button class="ef-rowbtn" data-ord="row-form" data-id="${o.id}" title="See this envelope as the order form">▤</button></td><td>${o.athlete ? esc(o.athlete) : o.summary && (o.summary.due_cents > 0 || o.summary.short_cents > 0) ? '<span class="due" title="Owes or paid short — type who it is">(no name)</span>' : '<span class="dim">(no name)</span>'}</td><td>${esc(o.team)}</td>
      <td title="${esc(ord)}">${ord ? esc(ord) : '<span class="dim">—</span>'}</td>${this.photoCells(o, pic)}<td>${o.glasses ? 'Yes' : ''}</td><td class="amt">${fmt$(s.total_cents)}</td><td class="amt dim" title="Meridian's estimated cost${s.lab_unpriced && s.lab_unpriced.length ? ' (some items not priced)' : ''}">${s.lab_cents ? fmt$(s.lab_cents) : '—'}</td>${this.profitCells(s)}${due}</tr>`;
  },
  // Thumbnails in the envelope list (right of the photo #): on unless switched off in the header.
  thumbs() { return prefs.ordThumbs !== false; },
  teamStems() { return new Set((this.d ? this.d.teams : []).map(t => t.image).filter(Boolean).map(n => stemOf(n).toLowerCase())); },
  photoCells(o, pic) {
    const isTeam = pic && this.teamStems().has(stemOf(pic).toLowerCase());
    const txt = pic ? (isTeam ? `<span class="due" title="That's a team photo's number, not a portrait — check the photo # on the envelope">${esc(pic)}</span>` : esc(pic)) : o.lines.length ? '<span class="warn">needs photo</span>' : '';
    if (!this.thumbs()) return `<td>${txt}</td><td class="o-thc off"></td>`;
    const p = pic ? this.photoFor(pic) : null;
    const th = p ? `<img class="o-th" src="${thumbUrl(p.path)}" loading="lazy" alt="" draggable="false" data-othumb="${o.id}" title="${esc(pic)} — click to see it bigger">` : pic && S.photos.length ? `<span class="o-th none" title="${esc(pic)} isn't in the open folder"></span>` : pic ? '<span class="o-th none" title="Open the shoot folder to see the photos"></span>' : '';
    return `<td>${txt}</td><td class="o-thc">${th}</td>`;
  },
  labCenter(v) {
    const L = this.lab;
    if (!L) { v.innerHTML = '<div class="msg">Working out the lab order…</div>'; return; }
    const items = L.groups.flatMap(g => g.items);
    const need = items.filter(i => i.file).length, found = items.filter(i => i.found).length;
    const noPic = [...new Set(items.filter(i => !i.file && i.why === 'no photo picked').flatMap(i => i.for))];
    const prints = L.groups.reduce((a, g) => a + g.qty, 0);
    v.innerHTML = `<div class="ord-scroll"><div class="lab">
      ${this.merHTML(L, found)}
      <details class="other-send" ${this.otherOpen ? 'open' : ''} data-othersend><summary>Other ways to send <span>Meridian website · ROES</span></summary>
        <div class="os-body"><p>Copies the print files into one folder per size, plus lab-order.csv with the quantities.</p><div class="os-row">
        ${switchHTML('oneper', this.onePer, 'One file per print', 'For the Meridian website: two 4x6s become two files, so a whole size folder uploads with every quantity at 1. Off: one file each, with quantities in lab-order.csv (for ROES).')}
        <button class="btn primary" data-ord="lab-build" ${this.building || !L.crops_exists || !found ? 'disabled' : ''}>${this.building ? 'Building…' : 'Build lab folder…'}</button></div></div></details>
      <div class="lab-ctrl"><div class="pathrow"><span class="path ${L.crops_dir && !L.crops_exists ? 'bad' : ''}" title="${esc(L.crops_dir)}">${esc(L.crops_dir || 'Choose the folder Crop exported the prints to')}</span><button class="btn sm" data-ord="lab-crops">Crops folder…</button></div>
</div>
      ${L.crops_dir && !L.crops_exists ? `<div class="banner amber inline">That crops folder isn’t there any more — choose where Crop exported this shoot.</div>` : ''}
      ${noPic.length ? `<div class="banner amber inline">No photo picked yet for ${esc(noPic.slice(0, 5).join(', '))}${noPic.length > 5 ? ` and ${noPic.length - 5} more` : ''}</div>` : ''}
      <div class="lab-sum"><span><b>${prints}</b>to print</span><span><b>${need}</b>files</span>${L.crops_exists ? `<span><b>${found}</b>found</span><span><b>${need - found}</b>not cropped yet</span>` : ''}</div>
      ${L.groups.map(g => `<div class="lab-grp"><header><b>${esc(g.group)}</b><span>${plural(g.qty, /wallet/i.test(g.group) ? 'sheet' : 'print')} · ${plural(g.files, 'file')}</span></header>${g.items.map(it => `<div class="lab-it"><span class="${it.found ? 'ok' : 'bad'}" title="${it.found ? 'Found in the crops folder' : it.file ? 'Not in the crops folder yet' : esc(it.why || 'No photo picked')}">${it.found ? '✓' : it.file ? '○' : '!'}</span><span class="f" title="${esc(it.found || it.file)}">${esc(it.file || it.why || 'no photo picked')}</span><span class="mc ${it.file && !it.mcode ? 'bad' : ''}" title="${esc(it.mcode ? `Meridian: ${it.mname} ×${it.mqty}` : 'No Meridian product code yet: set one under Prices…, or order it on the website')}">${it.mcode ? esc(it.mcode) : it.file ? 'no code' : ''}</span><span class="q">×${it.qty}</span><span class="who" title="${esc(it.for.join(', '))}">${esc(it.for.join(', '))}</span></div>`).join('')}</div>`).join('') || '<div class="ord-empty">Nothing has been ordered yet.</div>'}
    </div></div>`;
  },
  totalHTML(pr, d) {
    const auto = this.prepaid() && !d.paid_cents && !d.paid_method;
    const short = Math.min(d.accepted_cents || 0, pr.total);
    const due = auto ? 0 : pr.total - short - (d.paid_cents || 0);
    const st = !pr.total ? '' : auto ? '<span class="ok">Paid on picture day</span>' : due > 0 ? `<span class="due">${fmt$(due)} due</span>` : due < 0 ? `<span class="chg">Give ${fmt$(-due)} change</span>` : short ? `<span class="short">Paid ${fmt$(pr.total - short)} · accepted ${fmt$(short)} short</span>` : '<span class="ok">Paid in full</span>';
    return `<div class="tot-sum">${this.sumHTML(pr, d, st)}</div>
      <div class="tot-pay">${segHTML('ordPay', d.paid_method || '', this.payChoices(d.paid_method))}<label class="paid-amt" title="What they actually paid. Type a smaller amount when they're short; the rest shows as due."><span>Paid $</span><input data-of="paid" value="${d.paid_cents ? (d.paid_cents / 100).toFixed(2) : ''}" placeholder="${auto ? 'in full' : '0.00'}" inputmode="decimal" spellcheck="false"></label>${due < 0 ? `<button class="btn sm" data-ord="change-given" title="You handed back the change: record the payment as the total">Change given</button>` : ''}${due > 0 && d.paid_cents ? `<button class="btn sm" data-ord="short-accept" title="Let the ${fmt$(due)} go: the envelope counts as paid, and its total becomes what they paid">Accept ${fmt$(due)} short</button>` : ''}${short && due <= 0 ? `<button class="btn sm" data-ord="short-undo" title="They still owe the ${fmt$(short)}">Undo</button>` : ''}</div>
      <div class="tot-acts">${d.id ? '<button class="btn sm" data-ord="delete" title="Delete this envelope (Del). You can undo it.">Delete</button>' : ''}${d.id ? '<button class="btn sm" data-ord="envelope-form" title="This envelope drawn like the order form (← → step through)">Form</button>' : ''}<div class="tb-spacer"></div><button class="btn sm primary" data-ord="new">Next envelope (N)</button></div>`;
  },
  sumHTML(pr, d, st) { return `<span class="big">${fmt$(pr.total)}</span><span class="st">${st}</span><span class="sub">${pr.savings ? `Package savings ${fmt$(pr.savings)} · ` : ''}${this.labHTML(pr, d)}</span>`; },
  // Meridian's estimated cost, from the server (it expands packages the same way the lab order does).
  labHTML(pr, d) {
    if (!(d.lines || []).length) return '';
    const key = JSON.stringify([d.lines, d.team || '']);
    if (key !== this.labKey) {
      this.labKey = key; clearTimeout(this.labT);
      this.labT = setTimeout(async () => {
        try {
          const r = await api('/api/orders/price', { lines: d.lines, team: d.team || '' });
          if (this.labKey !== key) return;
          this.labEst = { key, s: r.summary };
          const t = $('#ordTotal'); if (t && this.draft) t.innerHTML = this.totalHTML(this.price(this.draft.lines), this.draft);
        } catch (e) { /* the estimate is optional */ }
      }, 200);
    }
    const L = this.labEst && this.labEst.key === key ? this.labEst.s : null;
    if (!L) return '<span class="labline">Lab cost …</span>';
    const miss = L.lab_unpriced && L.lab_unpriced.length ? ` <span class="warn" title="No Meridian price for: ${esc(L.lab_unpriced.join(', '))}">+ ${L.lab_unpriced.length} not priced</span>` : '';
    return `<span class="labline" title="Meridian's list prices; shipping and tax not included">Lab cost ≈ ${fmt$(L.lab_cents)}${miss} · ${(k => `<span class="keep ${k < 0 ? 'neg' : ''}">You keep ${fmt$(k)}</span>`)(pr.total - Math.min(d.accepted_cents || 0, pr.total) - L.lab_cents)}</span>`;
  },
  photoHTML(d) {
    const stem = d.edited || d.image, ph = stem ? this.photoFor(stem) : null, act = S.byId.get(S.active);
    return `<div class="photo-row"><div class="thumb ${ph ? '' : 'none'}" ${ph ? `style="background-image:url(&quot;${esc(thumbUrl(ph.path, 200))}&quot;)" title="${esc(ph.name)}"` : ''}>${ph ? '' : stem ? 'not in the<br>open folder' : 'no photo'}</div>
      <div class="col"><label class="fld" style="margin:0"><span>Photo to print</span><input data-of="image" list="ordFrames" value="${esc(d.image)}" placeholder="5371 or IMG_5371" spellcheck="false"></label>
      ${this.autoPhoto && !d.id ? '<div class="muted small">Next photo in the filmstrip. Not them? Click the right photo.</div>' : ''}
      <div class="btn-row" style="margin:0">${act && stemOf(act.name) !== stemOf(d.image) ? `<button class="btn sm" data-ord="use-photo" title="Use the photo selected in the filmstrip">Use ${esc(stemOf(act.name))}</button>` : `<span class="muted small">${S.photos.length ? 'Click a photo in the filmstrip to use it' : 'Open the shoot’s folder to pick from the filmstrip'}</span>`}</div></div></div>
      <div class="of-grid"><label class="fld"><span>Frames shot</span><input data-of="frames" value="${esc(d.frames)}" placeholder="5370-5372" spellcheck="false"></label><label class="fld"><span>Retouched file</span><input data-of="edited" value="${esc(d.edited)}" placeholder="if renamed" spellcheck="false"></label></div>
      <div class="pad-x" style="padding-bottom:10px">${switchHTML('glasses', !!d.glasses, 'Glasses — glare to fix')}</div>`;
  },
  right() {
    this.pvPaint();
    if (this.view === 'an' && this.sid && !this.draft && this.multi.size <= 1 && this.an && this.an.selection && this.an.selection.n) { $('#right').innerHTML = ''; this.wiRight(); return this.wiPaint(); }
    if (this.multi.size > 1) return this.bulkRight();
    const d = this.draft;
    const warn = this.cat && this.cat.warnings.length ? `<div class="hint" style="color:var(--amber)">${this.cat.warnings.map(esc).join('<br>')}</div>` : '';
    if (!d) {
      $('#right').innerHTML = `<div class="scroll">${sectionHTML('o-help', 'Envelopes', `<div class="hint">${this.sid ? 'Select an envelope to edit it, or press <b>N</b> to type in a new one.' : 'Create a shoot to start.'}<br><br>While an envelope is open, press <b>A</b>–<b>G</b> to add that package (Shift adds another, for siblings). Everything saves by itself.</div>${warn}`)}</div>`;
      return;
    }
    const pr = this.price(d.lines);
    const pk = this.products('package').map(p => { const q = this.qty(p.id); return `<button class="pkg ${q ? 'on' : ''}" data-opkg="${p.id}" title="${esc(p.label)}: ${esc(p.summary)}\nClick to add or remove · Shift-click adds another · Right-click takes one off">${q > 1 ? `<span class="q">×${q}</span>` : ''}<b>${esc(p.letter)}</b><small>${p.price % 100 ? fmt$(p.price) : '$' + (p.price / 100)}</small></button>`; }).join('');
    // Fixed two-line space: what the picked packages hold, so nothing below moves as packages are added.
    const picked = this.products('package').filter(p => this.qty(p.id));
    const noteTxt = picked.map(p => `${p.label}${this.qty(p.id) > 1 ? ` ×${this.qty(p.id)}` : ''}: ${p.summary}`).join('\n');
    const notes = picked.map(p => `<b>${esc(p.label.replace(/^Package /, ''))}${this.qty(p.id) > 1 ? ` ×${this.qty(p.id)}` : ''}</b> ${esc(p.summary)}`).join(' · ');
    const qrow = p => { const q = this.qty(p.id); return `<div class="qrow ${q ? 'has' : ''}"><span class="nm" title="${esc(p.unit_label)}">${esc(p.short)}</span><span class="pr">${p.type === 'alacarte' && pr.hasPkg ? `<s>${fmt$(p.price)}</s>` : ''}${fmt$(this.unit(p, pr.hasPkg))}</span><span class="stepper"><button data-oqty="${p.id}" data-d="-1" title="One fewer">−</button><span>${q}</span><button data-oqty="${p.id}" data-d="1" title="One more">+</button></span></div>`; };
    const fld = (k, l, wide, extra = '') => `<label class="fld ${wide ? 'wide' : ''}"><span>${l}</span><input data-of="${k}" value="${esc(d[k])}" spellcheck="false" ${extra}></label>`;
    $('#right').innerHTML = `<div class="scroll ord-ed">
      ${sectionHTML('o-who', `Envelope<span class="save-state ${this.err ? 'err' : ''}">${esc(this.state)}</span>`, `<div class="of-grid who">${fld('envelope', 'Env #', false, 'title="Envelope number"')}${fld('team', 'Team', false, 'list="ordTeams"')}${(ask => fld('athlete', 'Athlete', false, `placeholder="${ask ? 'Who owes this?' : 'First and last name'}" ${ask ? 'class="ask"' : ''}`))(!String(d.athlete || '').trim() && this.draftOwes(d))}${fld('coach', 'Coach', false, 'list="ordCoaches"')}</div>`)}
      ${sectionHTML('o-pkg', 'Packages', `<div class="pkgs">${pk}</div><div class="pkg-note fixed" title="${esc(noteTxt || 'Click a package to add it · Shift-click adds another · Right-click takes one off')}">${notes || 'No package: a la carte is full price. Shift-click adds another, right-click takes one off.'}</div>`)}
      ${sectionHTML('o-ac', 'A la carte', this.products('alacarte').map(qrow).join(''))}
      ${sectionHTML('o-misc', 'Keepsakes', this.products('misc').map(qrow).join(''))}
      ${sectionHTML('o-photo', 'Photo', this.photoHTML(d))}
      ${sectionHTML('o-contact', 'Parent & notes', `<div class="of-grid">${fld('parent', 'Parent')}${fld('phone', 'Phone')}${fld('address', 'Address', true)}${fld('email', 'Email', true)}<label class="fld wide"><span>Notes</span><textarea data-of="notes" rows="2">${esc(d.notes)}</textarea></label></div>`)}
      ${warn}
      <datalist id="ordTeams">${(this.d ? this.d.teams : []).map(t => `<option value="${esc(t.name)}">`).join('')}</datalist>
      <datalist id="ordCoaches">${(this.d ? this.d.coaches : []).map(c => `<option value="${esc(c)}">`).join('')}</datalist>
      <datalist id="ordFrames">${this.matches(String(d.image || '').replace(/\D/g, '')).map(n => `<option value="${esc(n)}">`).join('')}</datalist></div>
      <div class="ord-total pinned" id="ordTotal">${this.totalHTML(pr, d)}</div>`;
  },
  // ---------- several envelopes at once ----------
  async clickRow(id, e) {
    if (!(e.ctrlKey || e.metaKey || e.shiftKey)) return this.select(id);
    await this.flush();
    const rows = this.rows().map(o => o.id);
    if (!this.multi.size && this.sel && this.sel !== 'new') this.multi.add(this.sel);
    if (e.shiftKey && this.anchor != null && rows.includes(this.anchor)) {
      const [a, b] = [rows.indexOf(this.anchor), rows.indexOf(id)].sort((x, y) => x - y);
      if (!(e.ctrlKey || e.metaKey)) this.multi = new Set();
      rows.slice(a, b + 1).forEach(i => this.multi.add(i));
    } else {
      this.multi.has(id) ? this.multi.delete(id) : this.multi.add(id); this.anchor = id;
    }
    this.afterMulti();
  },
  async selectAllRows() {
    await this.flush();
    if (this.view !== 'orders') this.setView('orders');
    this.multi = new Set(this.rows().map(o => o.id)); this.afterMulti();
  },
  clearMulti() { this.multi = new Set(); this.sel = null; this.draft = null; this.paintRows(); renderRight(); },
  afterMulti() {
    if (this.multi.size === 1) { const [only] = this.multi; return this.select(only); }
    this.sel = null; this.draft = null; this.paintRows(); renderRight();
  },
  bulkRight() {
    const sel = this.d ? this.d.orders.filter(o => this.multi.has(o.id)) : [];
    const teams = [...new Set(sel.map(o => o.team || ''))];
    const now = teams.length === 1 ? (teams[0] ? `All on <b>${esc(teams[0])}</b>.` : 'None has a team yet.') : `Now on ${plural(teams.length, 'different team')}.`;
    $('#right').innerHTML = `<div class="scroll">${sectionHTML('o-bulk', `${sel.length} envelopes selected`, `<div class="hint">${now} Type a team and/or coach to give all of them; a box left empty is left alone.</div>
      <div class="of-grid"><label class="fld wide"><span>Team</span><input id="bulkTeam" list="ordTeams" spellcheck="false" placeholder="e.g. 7th Grade"></label>
      <label class="fld wide"><span>Coach</span><input id="bulkCoach" list="ordCoaches" spellcheck="false"></label></div>
      <div class="pad"><div class="btn-row"><button class="btn sm" data-ord="clear-multi">Clear selection</button><div class="tb-spacer"></div><button class="btn primary" data-ord="bulk-apply">Apply to ${sel.length}</button></div></div>`)}
      ${sectionHTML('o-bulkpay', 'Payment', (() => { const due = sel.reduce((t, o) => t + (o.summary ? o.summary.due_cents : 0), 0), tot = sel.reduce((t, o) => t + (o.summary ? o.summary.total_cents : 0), 0);
        return `<div class="hint">Mark all ${sel.length} paid in full the same way. ${fmt$(tot)} in all${due ? `, ${fmt$(due)} of it still owed` : ', all paid'}.</div>
        <div class="pad bulk-pay">${this.payChoices().map(([v, l]) => `<button class="btn sm" data-bulkpay="${v}">${!v && !this.prepaid() ? 'Unpaid' : l}</button>`).join('')}</div>`; })())}
      ${sectionHTML('o-bulkhelp', 'Selecting', `
      <div class="hint">Ctrl-click adds or removes one envelope · Shift-click selects a run · Ctrl+A selects all shown · Esc clears. Set a team's group photo with ▣ on the team at the left.</div>`)}
      <datalist id="ordTeams">${(this.d ? this.d.teams : []).map(t => `<option value="${esc(t.name)}">`).join('')}</datalist>
      <datalist id="ordCoaches">${(this.d ? this.d.coaches : []).map(c => `<option value="${esc(c)}">`).join('')}</datalist></div>`;
    const go = () => this.bulkApply();
    ['#bulkTeam', '#bulkCoach'].forEach(s => $(s).addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); go(); } }));
  },
  async bulkApply() {
    const team = ($('#bulkTeam') || {}).value || '', coach = ($('#bulkCoach') || {}).value || '';
    if (!team.trim() && !coach.trim()) return toast('Type a team or a coach first', 2500);
    try {
      const r = await api('/api/orders/bulk', { shoot_id: this.sid, ids: [...this.multi], fields: { team, coach } });
      if (team.trim()) this.last.team = team.trim();
      if (coach.trim()) this.last.coach = coach.trim();
      await this.refresh(); this.render();
      toast(`${plural(r.changed, 'envelope')} updated${team.trim() ? ` · team ${esc(team.trim())}` : ''}${coach.trim() ? ` · coach ${esc(coach.trim())}` : ''}`, 4000);
    } catch (e) { toast(esc(e.message), 5000); }
  },
  paintTotal() {
    const t = $('#ordTotal'); if (!t || !this.draft) return;
    const sum = $('.tot-sum', t);
    if (!sum) { t.innerHTML = this.totalHTML(this.price(this.draft.lines), this.draft); return; }
    const tmp = document.createElement('div'); tmp.innerHTML = this.totalHTML(this.price(this.draft.lines), this.draft);
    sum.innerHTML = $('.tot-sum', tmp).innerHTML;
    const inp = $('[data-of="paid"]', t); if (inp && document.activeElement !== inp) inp.placeholder = $('[data-of="paid"]', tmp).placeholder;
  },
  paintState() { const s = $('#right .save-state'); if (s) { s.textContent = this.state; s.classList.toggle('err', this.err); } },
  modbar() {
    if (S.module !== 'orders') return;
    const dis = this.sid ? '' : 'disabled';
    const unm = this.cat ? this.cat.unmapped_roes.length : 0;
    if (this.pickingTeam != null) { $('#modbar').innerHTML = `<span class="banner amber inline" style="margin:0">Click the ${esc(this.pickingTeam)} team photo in the filmstrip</span><div class="tb-spacer"></div><button class="btn sm" data-ord="cancel-team-pick">Cancel (Esc)</button>`; return; }
    $('#modbar').innerHTML = `${this.sid ? segHTML('ordView', this.view, [['orders', 'Envelopes'], ['lab', 'Lab order'], ['an', 'Analysis']]) : ''}
      ${S.photos.length ? `<button class="btn sm ${prefs.ordPv && prefs.ordPv.open ? 'on' : ''}" data-ord="pv" title="A floating photo of the open envelope (V)">${prefs.ordPv && prefs.ordPv.open ? '✓ ' : ''}Preview</button>` : ''}
      ${S.photos.length ? `<button class="btn sm ${this.picksOnly() ? 'on' : ''}" data-ord="picks-only" title="Show only photos flagged Pick in the filmstrip (one per kid), so each new envelope moves on to the next kid">${this.picksOnly() ? '✓ ' : ''}Filmstrip: picks only</button>` : ''}
      ${S.photos.length && this.d && this.d.orders.length ? '<button class="btn sm" data-ord="select-photos" title="Select every photo picked for an envelope (and the group photos), so Crop exports just those">Select ordered photos</button>' : ''}
      <div class="tb-spacer"></div>
      <div class="dd"><button class="btn sm" data-dd ${dis}>Shoot ▾</button><div class="dd-menu right">
        <button data-ord="edit-shoot" data-id="${this.sid || ''}">Edit shoot…<em>name, date, paid on picture day</em></button>
        <button data-ord="extras">School &amp; other orders…<em>free or paid prints not on an envelope</em></button>
        <button data-ord="school">Team 5×7s for the school…<em>${this.d && this.d.school && this.d.school.sent_at ? 'sent ' + esc(fmtDay(new Date(this.d.school.sent_at * 1000).toISOString().slice(0, 10))) : 'zip every team photo and email it'}</em></button>
        <button data-ord="prices">Prices…<em>packages, prices, lab codes</em></button>
        <button data-ord="backups">Backups…<em>restore, second copy, the photo folder’s copy</em></button>
        ${HIDDEN.has('import') ? '' : `<hr><button data-ord="import">Import website CSV…<em>orders from the website's /admin export</em></button>`}</div></div>
      <div class="dd"><button class="btn sm" data-dd ${dis}>Export ▾</button><div class="dd-menu right">
        <button data-ord="summary">Shoot summary<em>totals, teams, payments, what sold, who owes</em></button>
        <button data-ord="matching">Matching sheets (PDF)<em>each envelope’s photo, number and contents, by team</em></button>
        <button data-ord="envelopes-pdf">Envelopes (PDF)<em>every envelope drawn like the order form, for your records</em></button>
        <button data-oexp="pull">Pull sheet<em>one row per athlete, to stuff envelopes from</em></button>
        <button data-oexp="crop">Crop list<em>only the sizes families bought</em></button>
        <hr><button data-oexp="items">Orders CSV<em>one row per item, for the books</em></button>
        ${HIDDEN.has('roes') ? '' : `<button data-oexp="roes">ROES file${unm ? ' ⚠' : ''}<em>${unm ? `${unm} items still need a ROES code` : 'older ROES event import'}</em></button>`}</div></div>`;
  },
  key(e, k) {
    if (modalOpen()) return false;
    if (this.pickingTeam != null && e.key === 'Escape') { this.endTeamPick(); return true; }
    if (e.key === '/') { const i = $('#modView [data-oq]'); if (i) { i.focus(); i.select(); return true; } }
    if (k === 'n' && !e.shiftKey) { this.newOrder(); return true; }
    if (k === 'v' && !e.shiftKey && S.photos.length) { this.pvToggle(); return true; }
    if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && this.view === 'an') { this.stepTeam(e.key === 'ArrowDown' ? 1 : -1); return true; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { if (this.view !== 'orders') return false; this.move(e.key === 'ArrowDown' ? 1 : -1); return true; }
    if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && S.view.length) { step(e.key === 'ArrowRight' ? 1 : -1); this.photoClicked(S.active); return true; }
    if (e.key === 'Delete' && this.draft) { this.del(); return true; }
    if (e.key === 'Escape' && this.multi.size > 1) { this.clearMulti(); return true; }
    if (e.key === 'Escape' && this.draft) { this.flush(); this.sel = null; this.draft = null; this.paintRows(); renderRight(); return true; }
    if (/^[a-z]$/.test(k) && this.draft && this.togglePkg(k, e.shiftKey)) return true;
    return false;
  },
  // field typing in the editor (no redraw, so the cursor stays put)
  onInput(el) {
    const d = this.draft; if (!d) return;
    const k = el.dataset.of;
    if (k === 'paid') { d.paid_cents = parse$(el.value); d.accepted_cents = 0; if (d.paid_cents && !d.paid_method) d.paid_method = 'cash'; }
    else d[k] = el.value;
    if (k === 'image') { this.autoPhoto = false; const dl = $('#ordFrames'); if (dl) dl.innerHTML = this.matches(el.value.replace(/\D/g, '')).map(n => `<option value="${esc(n)}">`).join(''); }
    this.changed(false);
  },
  onChange(el) {
    const d = this.draft; if (!d) return;
    if (el.dataset.of === 'paid') this.askName();
    if (el.dataset.of === 'athlete' && el.value.trim()) { el.classList.remove('ask'); }
    if (el.dataset.of === 'image' || el.dataset.of === 'edited') {
      const v = this.normImage(el.value); if (v !== el.value) { el.value = v; d[el.dataset.of] = v; this.changed(false); }
      const ph = $('#right .photo-row'); if (ph) keepScroll('#right', () => this.right());
    }
    if (el.dataset.of === 'paid') { if (el.value) el.value = (d.paid_cents / 100).toFixed(2); const t = $('#ordTotal'); if (t) t.innerHTML = this.totalHTML(this.price(d.lines), d); }
    if (el.dataset.of === 'team' && d.team && this.d) {
      const t = this.d.teams.find(x => x.name === d.team);
      if (!t) { const s = this.shoot(); toast(`New team “${esc(d.team)}” - it's added to ${esc(s ? s.name : 'this shoot')}'s team list`, 3500); }
      if (!d.coach) { const o = this.d.orders.find(o => o.team === d.team && o.coach), c = (o && o.coach) || (t && t.coach); if (c) { d.coach = c; this.changed(true); } }
    }
  },
};
window.KS_ordUndo = () => Ord.undoDelete();

/* ---------- module UI events ---------- */
// A newer release on GitHub? Shown once per launch as a blue banner; ✕ means "later".
async function checkForUpdate() {
  try {
    const r = await api('/api/update-check', {});
    if (!r.ok || !r.newer || S.banners.some(b => b.id === 'update')) return;
    S.banners.push({ id: 'update', cls: 'info', text: `Keeper Studio ${r.latest} is available — you have ${r.current}. Download it, unzip it, and replace your Keeper Studio folder; your settings and framing are kept.`, action: { label: 'Download', url: r.page } });
    renderBanners();
  } catch {}
}
function setFilmH(v, save) {
  const h = clamp(Math.round(v), 84, 320); if (h === S.filmH && !save) return;
  const fs = $('#filmScroll'), ratio = fs && fs.scrollWidth ? fs.scrollLeft / fs.scrollWidth : 0;
  S.filmH = h; applyPanels(); renderFilm(); if (fs) fs.scrollLeft = ratio * fs.scrollWidth; renderFilm();
  const r = $('#filmSize'); if (r && +r.value !== h) r.value = h;
  if (S.module !== 'library') renderView(); else if (S.mode !== 'grid') renderView();
  if (save) { savePrefs(); ensureVisible(); }
}
function setLeftW(v, save) {
  const w = clamp(Math.round(v), 200, Math.min(520, innerWidth * 0.45)); if (w === S.leftW && !save) return;
  S.leftW = w; applyPanels(); renderView(); renderFilm();
  if (save) savePrefs();
}
function setRightW(v, save) {
  const w = clamp(Math.round(v), 240, Math.min(560, innerWidth * 0.45)); if (w === S.rightW && !save) return;
  S.rightW = w; applyPanels(); renderView(); renderFilm();
  if (save) savePrefs();
}
function bindRightSize() {
  const g = $('#rightGrip'); if (!g) return; let d = null;
  g.addEventListener('pointerdown', e => { e.preventDefault(); g.setPointerCapture(e.pointerId); g.classList.add('drag'); d = { x: e.clientX, w: S.rightW }; });
  g.addEventListener('pointermove', e => { if (d) setRightW(d.w - (e.clientX - d.x)); });
  const end = () => { if (!d) return; d = null; g.classList.remove('drag'); setRightW(S.rightW, true); };
  g.addEventListener('pointerup', end); g.addEventListener('pointercancel', end);
  g.addEventListener('dblclick', () => setRightW(280, true));
}
function bindLeftSize() {
  bindRightSize();
  const g = $('#leftGrip'); if (!g) return; let d = null;
  g.addEventListener('pointerdown', e => { e.preventDefault(); g.setPointerCapture(e.pointerId); g.classList.add('drag'); d = { x: e.clientX, w: S.leftW }; });
  g.addEventListener('pointermove', e => { if (d) setLeftW(d.w + (e.clientX - d.x)); });
  const end = () => { if (!d) return; d = null; g.classList.remove('drag'); setLeftW(S.leftW, true); };
  g.addEventListener('pointerup', end); g.addEventListener('pointercancel', end);
  g.addEventListener('dblclick', () => setLeftW(240, true));
}
function bindFilmSize() {
  bindLeftSize();
  const r = $('#filmSize'); if (!r) return; r.value = S.filmH;
  r.addEventListener('input', () => setFilmH(+r.value));
  r.addEventListener('change', () => { setFilmH(+r.value, true); r.blur(); });
  const g = $('#filmGrip'); let d = null;
  g.addEventListener('pointerdown', e => { e.preventDefault(); g.setPointerCapture(e.pointerId); g.classList.add('drag'); d = { y: e.clientY, h: S.filmH }; });
  g.addEventListener('pointermove', e => { if (d) setFilmH(d.h + (d.y - e.clientY)); });
  const end = () => { if (!d) return; d = null; g.classList.remove('drag'); setFilmH(S.filmH, true); };
  g.addEventListener('pointerup', end); g.addEventListener('pointercancel', end);
  g.addEventListener('dblclick', () => setFilmH(124, true));
}
function bindModuleEvents() {
  $('#right').addEventListener('contextmenu', e => {
    const pk = S.module === 'orders' && e.target.closest('[data-opkg]'); if (!pk) return;
    e.preventDefault(); const q = Ord.qty(pk.dataset.opkg); if (q) Ord.setQty(pk.dataset.opkg, q - 1);
  });
  $('#banners').addEventListener('click', e => { const g = e.target.closest('[data-banner-go]'); if (g) { const b = S.banners.find(x => x.id === g.dataset.bannerGo); if (b && b.go) { g.disabled = true; b.go.fn(); } return; } const w = e.target.closest('[data-banner-work]'); if (w) { const b = S.banners.find(x => x.id === 'work'); if (b) Work.restore(b.work); return; } const u = e.target.closest('[data-banner-url]'); if (u) api('/api/open-url', { url: u.dataset.bannerUrl }).catch(err => toast(esc(err.message))); });
  bindFilmSize();
  $('#top').addEventListener('click', e => { const b = e.target.closest('[data-module]'); if (b) setModule(b.dataset.module); });
  const onClick = async e => {
    const t = e.target;
    const cj = t.closest('[data-cancel-job]'); if (cj) { cancelJob(cj.dataset.cancelJob); cj.disabled = true; cj.textContent = 'Stopping…'; return; }
    const sw = t.closest('[data-sw]');
    if (sw) {
      const k = sw.dataset.sw;
      if (S.module === 'crop') { const v = !sw.classList.contains('on'); Crop.saveSettings({ [k]: v }); }
      else if (S.module === 'composite') { Comp.f[k] = !sw.classList.contains('on'); Comp.save(); Comp.render(); }
      else if (S.module === 'orders' && k === 'glasses' && Ord.draft) { Ord.draft.glasses = !Ord.draft.glasses; Ord.changed(true); }
      else if (S.module === 'orders' && k === 'merEnvOrder') { const on = !(Ord.lab && Ord.lab.meridian && Ord.lab.meridian.envelope_order === 'no'); Ord.merSet('envelope_order', on ? 'no' : 'yes'); }
      else if (S.module === 'orders' && k === 'oneper') { Ord.onePer = !Ord.onePer; DB.put('kv', 'orders|oneper', Ord.onePer).catch(() => {}); renderView(); }
      else if (S.module === 'retouch' && k === 'rtMatch') { Ret.match = !Ret.match; Ret.right(); }
      return;
    }
    const sg = t.closest('.seg[data-seg] button');
    if (sg) {
      const name = sg.parentElement.dataset.seg, v = sg.dataset.v;
      if (name === 'cropScope') { Crop.scope = v; renderLeft(); }
      else if (name === 'cropMode') Crop.saveSettings(v === 'tq' ? { preschool: false, framing_style: ['knee_above', 'knee_below'].includes(Crop.settings.framing_style) ? Crop.settings.framing_style : 'knee_above' } : { preschool: v === 'preschool', framing_style: 'full' });
      else if (name === 'kneeLine') Crop.saveSettings({ framing_style: v });
      else if (name === 'enhanceWhen') Crop.saveSettings({ enhance_when: v });
      else if (name === 'cutScope') { Cut.scope = v; renderLeft(); }
      else if (name === 'cutQuality') Cut.setQuality(v);
      else if (name === 'cutView') { Cut.view = v; renderView(); }
      else if (name === 'ordView') Ord.setView(v);
      else if (name === 'anScope') { Ord.anScope = v; renderView(); }
      else if (name === 'merDelivery') { Ord.merSet('delivery', v).then(() => Ord.syncShipping(v === 'pickup' ? 0 : null)); }
      else if (name === 'ordPay' && Ord.draft) { const d = Ord.draft; d.paid_method = v; d.accepted_cents = 0; d.paid_cents = v && v !== 'none' ? Ord.price(d.lines).total : 0; Ord.changed(true); if (v === 'none' || (!v && !Ord.prepaid())) Ord.askName(); }
      else if (name === 'rtStep') Ret.setStep(v);
      else if (name === 'rtMode') { Ret.brush.erase = v === 'erase'; Ret.right(); }
      return;
    }
    const ci = t.closest('[data-circle]'); if (ci) { Crop.toggleCircle(ci.dataset.circle); return; }
    const rt = t.closest('[data-rt]');
    if (rt) {
      const a = rt.dataset.rt;
      if (a === 'save') Ret.save(); else if (a === 'remove') Ret.remove(); else if (a === 'show') Ret.showFile(); else if (a === 'copy') Ret.saveCopy(); else if (a === 'auto') Ret.autoMask();
      else if (a === 'clear') Ret.clearMask(); else if (a === 'undo') Ret.undoMask(); else if (a === 'reset') Ret.resetAlign();
      else if (a === 'to-brush') Ret.setStep('brush'); else if (a === 'donor-prev') Ret.stepDonor(-1); else if (a === 'donor-next') Ret.stepDonor(1);
      else if (a === 'before') { Ret.showBefore = !Ret.showBefore; Ret.draw(); Ret.modbar(); }
      else if (a === 'zoom-in') Ret.zoomView(1.25); else if (a === 'zoom-out') Ret.zoomView(0.8);
      else if (a === 'fit') Ret.fitView(); else if (a === 'px') Ret.actualPixels();
      return;
    }
    const rg = t.closest('[data-rt-go]'); if (rg) { const id = +rg.dataset.rtGo; S.active = id; S.selected = new Set([id]); S.anchor = id; refreshSelection(); ensureVisible(); return; }
    const sa = t.closest('[data-sizeall]');
    if (sa) { Crop.saveSettings({ disabled_sizes: sa.dataset.sizeall === 'on' ? [] : Crop.sizes.map(z => z.name) }); return; }
    const st = t.closest('[data-sizetoggle]');
    if (st) { const off = new Set(Crop.settings.disabled_sizes || []); const n = st.dataset.sizetoggle; off.has(n) ? off.delete(n) : off.add(n); Crop.saveSettings({ disabled_sizes: [...off] }); return; }
    const cf = t.closest('[data-cropfilter]');
    if (cf) { const v = cf.dataset.cropfilter; S.filter.crop = S.filter.crop === v ? 'any' : v; afterFilter(); return; }
    const sf = t.closest('[data-stylefilter]');
    if (sf) { const v = sf.dataset.stylefilter; S.filter.cstyle = S.filter.cstyle === v || v === 'any' ? 'any' : v; afterFilter(); return; }
    const c = t.closest('[data-crop]');
    if (c) {
      const a = c.dataset.crop;
      if (a === 'export') Crop.exportPrints(); else if (a === 'analyze') Crop.analyze(); else if (a === 'recheck') Crop.analyze(Crop.restyled ? Crop.restyled.paths.filter(k => !Crop.status.has(k)) : null); else if (a === 'recheck-x') { Crop.restyled = null; renderRight(); } else if (a === 'pick-all' || a === 'pick-both' || a === 'pick-picks' || a === 'pick-teams') Crop.selectPicksTeam(a.slice(5)); else if (a === 'show-unpicked') Crop.showUnpicked();
      else if (a === 'compare') Crop.toggleCompare(); else if (a === 'clear-styles') Crop.clearStyles();
      else if (a === 'adjust') Crop.startAdjust(); else if (a === 'square') Crop.startSquare(); else if (a === 'reset') Crop.resetManual();
      else if (a === 'adj-apply') Crop.applyAdjust(); else if (a === 'adj-cancel') Crop.cancelAdjust();
      else if (a === 'overlay') { Crop.overlay = !Crop.overlay; Crop.render(); Crop.modbar(); }
      else if (a === 'tunables') Crop.tunables();
      else if (a === 'rot-') Crop.nudge(-0.1); else if (a === 'rot+') Crop.nudge(0.1); else if (a === 'rot0') Crop.setRotation(0); else if (a === 'gridlock') { Crop.gridLock = !Crop.gridLock; Crop.syncGrid(); } else if (a === 'lineslock') { Crop.linesLock = !Crop.linesLock; Crop.syncLines(); } else if (a === 'size-undo') { const u = Crop.sizeNote && Crop.sizeNote.undo; if (u) { Crop.saveSettings({ disabled_sizes: u }).then(() => { Crop.sizeNote = null; renderRight(); }); } } else if (a === 'details') { Crop.detailsOpen = !Crop.detailsOpen; renderRight(); } else if (a === 'rot-apply') Crop.applyStraight(); else if (a === 'rot-cancel') Crop.cancelStraight(); else if (a === 'sheets') Crop.showSheets();
      else if (a === 'open-out') reveal(Crop.result ? Crop.result.out_dir : Crop.outDir);
      else if (a === 'out-change') { const p = await pickPath('folder', { initial: Crop.outDir || S.root || '' }); if (p) Crop.setOut(p, true); }
      else if (a === 'out-default') Crop.setOut(S.root ? `${S.root}_out` : '', false);
      return;
    }
    const cp = t.closest('[data-comp]');
    if (cp) { const a = cp.dataset.comp; if (a === 'build') Comp.build(); else if (a === 'open') openExternal(Comp.built.path); else if (a === 'reveal') reveal(Comp.built.path); return; }
    const pick = t.closest('[data-comp-pick]');
    if (pick) {
      const key = pick.dataset.compPick, kind = pick.dataset.kind, cur = Comp.f[key] || '';
      const types = kind === 'font' ? ['Fonts (*.ttf;*.otf;*.ttc)'] : kind === 'image' ? ['Images (*.jpg;*.jpeg;*.png)'] : ['JPEG (*.jpg)'];
      const p = await pickPath(kind === 'save' ? 'save' : 'open', { initial: cur ? dirName(cur) : (kind === 'font' ? 'C:\\Windows\\Fonts' : S.root || ''), types, filename: kind === 'save' ? baseName(cur || Comp.defaultOut() || 'composite.jpg') : undefined });
      if (p) { Comp.f[key] = kind === 'save' && !/\.jpe?g$/i.test(p) ? p + '.jpg' : p; Comp.save(); Comp.built = key === 'background' ? null : Comp.built; Comp.refreshOrder(); Comp.render(); }
      return;
    }
    if (S.module === 'orders') {
      const pk = t.closest('[data-opkg]'); if (pk) { const q = Ord.qty(pk.dataset.opkg); Ord.setQty(pk.dataset.opkg, e.shiftKey ? q + 1 : q ? 0 : 1); return; }
      const qb = t.closest('[data-oqty]'); if (qb) { Ord.setQty(qb.dataset.oqty, Ord.qty(qb.dataset.oqty) + +qb.dataset.d); return; }
      const so = t.closest('[data-osort]'); if (so) { const k = so.dataset.osort; Ord.sort = Ord.sort.k === k ? { k, dir: -Ord.sort.dir } : { k, dir: 1 }; prefs.ordSort = Ord.sort; savePrefs(); Ord.paintRows(); return; }
      const tb = t.closest('[data-othumb]'); if (tb) { Ord.thumbHover(null);  Ord.select(+tb.dataset.othumb).then(() => { if (!(prefs.ordPv && prefs.ordPv.open)) Ord.pvToggle(); else Ord.pvPaint(); }); return; }
      const rf = t.closest('[data-ord=row-form]'); if (rf) { Ord.openForm(+rf.dataset.id); return; }
      const tr = t.closest('tr[data-oid]'); if (tr) { Ord.clickRow(+tr.dataset.oid, e); return; }
      const ex = t.closest('[data-oexp]'); if (ex) { Ord.preview(ex.dataset.oexp); return; }
      const bp = t.closest('[data-bulkpay]'); if (bp) { e.stopPropagation(); return Ord.bulkPay(bp.dataset.bulkpay); }
      const oa = t.closest('[data-ord]');
      if (oa) {
        e.stopPropagation();
        const a = oa.dataset.ord;
        if (a === 'new') Ord.newOrder(); else if (a === 'new-shoot') Ord.editShoot(true); else if (a === 'edit-shoot') Ord.editShoot(false, +oa.dataset.id);
        else if (a === 'delete') Ord.del(); else if (a === 'team-photo') Ord.teamPhoto(oa.dataset.team); else if (a === 'team-rename') Ord.renameTeam(oa.dataset.team);
        else if (a === 'use-photo') { const p = S.byId.get(S.active); if (p && Ord.draft) { Ord.draft.image = stemOf(p.name); Ord.changed(true); } }
        else if (a === 'import') Ord.importWeb(); else if (a === 'prices') Ord.openPrices(); else if (a === 'select-photos') Ord.selectOrdered();
        else if (a === 'team-drop') Ord.dropPlanned(oa.dataset.team); else if (a === 'team-list') Ord.openTeamList(); else if (a === 'envelopes-pdf') Ord.envelopesPdf(); else if (a === 'envelope-pdf') { if (Ord.draft && Ord.draft.id) Ord.envelopesPdf([Ord.draft.id]); } else if (a === 'row-form') Ord.openForm(+oa.dataset.id); else if (a === 'envelope-form') { const id = Ord.draft && Ord.draft.id; if (id) (async () => { await Ord.flush(); await Ord.refresh(); Ord.openForm(id); })(); } else if (a === 'school') Ord.openSchool(); else if (a === 'lab-crops') Ord.pickCrops(); else if (a === 'lab-build') Ord.buildLab(); else if (a === 'thumbs') { prefs.ordThumbs = !Ord.thumbs(); savePrefs(); Ord.render(); toast(Ord.thumbs() ? 'Photo thumbnails on' : 'Photo thumbnails off · click ▢ beside Photo to turn them back on', 4000); } else if (a === 'an-unsold') { Ord.anUnsold = !Ord.anUnsold; Ord.anPaint(); } else if (a === 'an-teams') { Ord.anAllTeams = !Ord.anAllTeams; Ord.anPaint(); } else if (a === 'to-an') Ord.setView('an'); else if (a === 'tot-glasses') { Ord.team = 'all'; Ord.sort = { k: 'glasses', dir: 1 }; prefs.ordSort = Ord.sort; savePrefs(); Ord.setView('orders'); } else if (a === 'tot-nophoto') { Ord.team = 'all'; Ord.sort = { k: 'image', dir: -1 }; prefs.ordSort = Ord.sort; savePrefs(); Ord.setView('orders'); } else if (a === 'backups') Ord.backups(); else if (a === 'matching') Ord.matchingPdf(); else if (a === 'env-missing') Ord.newOrder(+oa.dataset.n); else if (a === 'env-noname') { Ord.team = 'all'; renderLeft(); Ord.select(+oa.dataset.id).then(() => Ord.askName()); } else if (a === 'env-dup') { Ord.sort = { k: 'env', dir: 1 }; Ord.team = 'all'; renderLeft(); const o = Ord.d.orders.find(x => String(x.envelope).trim() === oa.dataset.n); if (o) Ord.select(o.id); } else if (a === 'pv') Ord.pvToggle(); else if (a === 'short-accept' && Ord.draft) { const d = Ord.draft, t = Ord.price(d.lines).total; d.accepted_cents = Math.max(0, t - (d.paid_cents || 0)); Ord.changed(true); Ord.askName(); toast(`Accepted ${fmt$(d.accepted_cents)} short — the envelope counts as paid`, 3000); } else if (a === 'short-undo' && Ord.draft) { Ord.draft.accepted_cents = 0; Ord.changed(true); } else if (a === 'change-given' && Ord.draft) { const d = Ord.draft; d.paid_cents = Ord.price(d.lines).total; Ord.changed(true); toast('Change given — recorded as paid in full', 2500); } else if (a === 'team-up' || a === 'team-down') Ord.moveTeam(oa.dataset.team, a === 'team-up' ? -1 : 1); else if (a === 'tot-full') { Ord.totFull = true; renderLeft(); } else if (a === 'summary') Ord.summary(); else if (a === 'extras') Ord.openExtras(); else if (a === 'wi-toggle') Ord.wiToggle(); else if (a === 'wi-reset') { Ord.wi = {}; Ord.wiPaint(); } else if (a === 'mer-build') Ord.buildMeridian(); else if (a === 'mer-preview') Ord.previewMeridian();
        else if (a === 'picks-only') Ord.setPicksOnly(!Ord.picksOnly());
        else if (a === 'cancel-team-pick') Ord.endTeamPick();
        else if (a === 'select-all') Ord.selectAllRows(); else if (a === 'clear-multi') Ord.clearMulti(); else if (a === 'bulk-apply') Ord.bulkApply();
        return;
      }
      const sh = t.closest('[data-oshoot]'); if (sh) { if (+sh.dataset.oshoot !== Ord.sid) Ord.pickShoot(+sh.dataset.oshoot); return; }
      const tm = !S.suppressTeamClick && t.closest('[data-oteam]'); if (tm) { Ord.pickTeam(tm.dataset.oteam); return; }
      const ash = t.closest('[data-anshoot]'); if (ash) { Ord.anScope = 'shoot'; Ord.pickShoot(+ash.dataset.anshoot); return; }
    }
    const cu = t.closest('[data-cut]');
    if (cu) {
      const a = cu.dataset.cut;
      if (a === 'run') Cut.run(); else if (a === 'open-out') reveal(Cut.outDir);
      else if (a === 'reveal-one') reveal(Cut.existing[(S.byId.get(S.active) || {}).path]);
      else if (a === 'out-change') { const p = await pickPath('folder', { initial: Cut.outDir || S.root || '' }); if (p) Cut.setOut(p, true); }
      else if (a === 'out-default') Cut.setOut(S.root ? `${S.root}_cutouts` : '', false);
    }
  };
  ['#left', '#right', '#modView', '#modbar'].forEach(s => $(s).addEventListener('click', onClick));
  ['#left', '#right'].forEach(sel => {  // the bottom-margin slider lives in the left panel now
    $(sel).addEventListener('input', e => {
      const r = e.target.closest('[data-range]'); if (!r) return;
      const b = r.parentElement.querySelector('b'); if (b) b.textContent = Math.round(+r.value * 1000) / 10 + '%';
    });
    $(sel).addEventListener('change', e => { const r = e.target.closest('[data-range]'); if (r) Crop.saveSettings({ [r.dataset.range]: +r.value }); });
  });
  $('#right').addEventListener('input', e => { const r = e.target.closest('[data-straight]'); if (r) Crop.livePreview(+r.value); const b = e.target.closest('[data-rt-size]'); if (b) Ret.setSize(+b.value); const sf = e.target.closest('[data-rt-soft]'); if (sf) Ret.setSoft(+sf.value);
    const op = e.target.closest('[data-rt-op]'); if (op) { Ret.opacity = +op.value; $('#rtOpVal').textContent = op.value + '%'; Ret.draw(); }
    const aj = e.target.closest('[data-rt-adj]'); if (aj && aj.value !== '') Ret.setAdj(aj.dataset.rtAdj, +aj.value); });
  $('#right').addEventListener('change', e => { const r = e.target.closest('[data-photostyle]'); if (r) { r.blur(); Crop.setStyle(r.value || null); } });
  $('#right').addEventListener('change', e => { const r = e.target.closest('[data-straight]'); if (r) { r.blur(); Crop.livePreview(+r.value); const rv = $('#rotVal'); if (rv) rv.textContent = `${+r.value > 0 ? '+' : ''}${(+r.value).toFixed(1)}°`; } });
  $('#right').addEventListener('mouseover', e => {
    if (S.module !== 'crop') return;
    const row = e.target.closest('[data-size]'); const n = row ? row.dataset.size : null;
    if (n !== Crop.hover) { Crop.hover = n; Crop.center(); $$('#right .size-row').forEach(r => r.classList.toggle('hot', r.dataset.size === n)); }
  });
  // Framing card Details: remember open/closed while stepping through photos
  $('#right').addEventListener('toggle', e => { if (e.target.matches && e.target.matches('details[data-reason]')) Crop.detailsOpen = e.target.open; }, true);
  $('#right').addEventListener('mouseleave', () => { if (Crop.hover) { Crop.hover = null; if (S.module === 'crop') Crop.center(); } });
  $('#left').addEventListener('input', e => {
    const i = e.target.closest('[data-cf]'); if (!i || S.module !== 'composite') return;
    Comp.f[i.dataset.cf] = i.type === 'number' ? +i.value : i.value; Comp.save();
    if (i.dataset.cf === 'students' || i.dataset.cf === 'teachers') Comp.autoNote = '';
    clearTimeout(Comp._t); Comp._t = setTimeout(() => { if (['max_per_row', 'row_counts'].includes(i.dataset.cf)) Comp.refreshOrder(); else renderRight(); }, 300);
  });
  $('#left').addEventListener('change', e => { const i = e.target.closest('select[data-cf]'); if (i && S.module === 'composite') { Comp.refreshOrder(); i.blur(); } });
  // Orders: typing in the envelope editor and the search box
  $('#right').addEventListener('input', e => { const i = e.target.closest('[data-of]'); if (i && S.module === 'orders') Ord.onInput(i); });
  $('#right').addEventListener('change', e => { const i = e.target.closest('[data-of]'); if (i && S.module === 'orders') Ord.onChange(i); });
  $('#modView').addEventListener('input', e => { const i = e.target.closest('[data-oq]'); if (i && S.module === 'orders') { Ord.q = i.value; Ord.paintRows(); } });
  document.addEventListener('change', async e => {
    if (!(e.target.matches && e.target.matches('[data-oship]')) || !Ord.sid) return;
    try {
      const amt = e.target.value.trim();
      await api('/api/orders/shipping', { shoot_id: Ord.sid, amount: amt }); await Ord.refresh(); renderLeft();
      const c = Ord.d ? Ord.d.totals.shipping_cents || 0 : 0; Ord.merSet('ship_amount', c ? (c / 100).toFixed(2) : '');  // remembered for the next shoot
    }
    catch (err) { toast(esc(String(err.message).replace(/^\w+Error:\s*/, '')), 3500); renderLeft(); }
  });
  document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches && e.target.matches('[data-oship]')) e.target.blur(); }, true);
  document.addEventListener('toggle', e => { if (e.target.matches && e.target.matches('[data-othersend]')) { Ord.otherOpen = e.target.open; DB.put('kv', 'labOtherOpen', Ord.otherOpen).catch(() => {}); } }, true);
  DB.get('kv', 'labOtherOpen').then(v => { Ord.otherOpen = !!v; }).catch(() => {});
  document.addEventListener('change', e => { if (e.target.matches && e.target.matches('[data-wi]')) Ord.wiSet(e.target.dataset.wi, e.target.value); });
  document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches && e.target.matches('[data-wi]')) { e.preventDefault(); e.target.blur(); } }, true);
  document.addEventListener('input', e => { if (e.target.matches && e.target.matches('[data-wi-drop]')) { Ord.wiDrop = +e.target.value; Ord.wiPaint(); } });
  document.addEventListener('change', e => { if (e.target.matches && e.target.matches('[data-ord-arch]')) { prefs.ordShowArchived = e.target.checked; savePrefs(); renderLeft(); } });
  $('#modView').addEventListener('change', e => { const i = e.target.closest('[data-mer]'); if (i && S.module === 'orders') Ord.merSet(i.dataset.mer, i.value.trim()); });
  // prices.yaml edited in another program: pick the new prices up on return
  window.addEventListener('focus', () => { if (S.module === 'orders') Ord.loadCatalog().then(() => { if (S.module === 'orders') { renderRight(); Ord.modbar(); } }); });
}

