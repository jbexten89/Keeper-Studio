// Keeper Studio UI — core. Plain scripts sharing one global scope, loaded in order by index.html.
'use strict';

/* ================= Utilities ================= */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
const LABELS = ['red', 'yellow', 'green', 'blue'];
const LABEL_NAMES = { red: 'Red', yellow: 'Yellow', green: 'Green', blue: 'Blue' };
const THUMB_MAX = 400;
let FW = 92; // filmstrip cell width (follows the filmstrip height)
const QUICK = 'quick';
const ext = n => (n.match(/\.([^.]+)$/) || ['', ''])[1];
const sanitize = s => String(s || '').replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, ' ').trim();
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

const FLAG_PATH = '<path d="M2.2 1v12" stroke="currentColor" stroke-width="1.4" fill="none"/><path d="M2.9 1.6h7.6L8.4 4.7l2.1 3.1H2.9z"';
const SVG_PICK = `<svg viewBox="0 0 12 14" width="11" height="13">${FLAG_PATH} fill="currentColor"/></svg>`;
const SVG_OPEN = `<svg viewBox="0 0 12 14" width="11" height="13">${FLAG_PATH} fill="none" stroke="currentColor" stroke-width="1.1"/></svg>`;
const SVG_REJ = `<svg viewBox="0 0 12 14" width="11" height="13">${FLAG_PATH} fill="currentColor"/><path d="M5 3l3 3.2M8 3L5 6.2" stroke="#07080A" stroke-width="1.3"/></svg>`;
const ICONS = {
  grid: '<svg width="16" height="14" viewBox="0 0 16 14"><g fill="currentColor"><rect x="0" y="0" width="4" height="3.5" rx=".6"/><rect x="6" y="0" width="4" height="3.5" rx=".6"/><rect x="12" y="0" width="4" height="3.5" rx=".6"/><rect x="0" y="5.25" width="4" height="3.5" rx=".6"/><rect x="6" y="5.25" width="4" height="3.5" rx=".6"/><rect x="12" y="5.25" width="4" height="3.5" rx=".6"/><rect x="0" y="10.5" width="4" height="3.5" rx=".6"/><rect x="6" y="10.5" width="4" height="3.5" rx=".6"/><rect x="12" y="10.5" width="4" height="3.5" rx=".6"/></g></svg>',
  loupe: '<svg width="16" height="14" viewBox="0 0 16 14"><rect x="1" y="1" width="14" height="12" rx="1.2" fill="none" stroke="currentColor" stroke-width="1.6"/><rect x="4" y="4" width="8" height="6" rx=".6" fill="currentColor"/></svg>',
  compare: '<svg width="18" height="14" viewBox="0 0 18 14"><rect x=".8" y="1.5" width="7.4" height="11" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="9.8" y="1.5" width="7.4" height="11" rx="1" fill="currentColor"/><text x="2.7" y="9.6" font-size="6.5" font-weight="700" fill="currentColor" font-family="sans-serif">X</text><text x="11.6" y="9.6" font-size="6.5" font-weight="700" fill="#13161A" font-family="sans-serif">Y</text></svg>',
  survey: '<svg width="18" height="14" viewBox="0 0 18 14"><g fill="currentColor"><rect x="0" y="0" width="8" height="6" rx=".8"/><rect x="10" y="0" width="8" height="6" rx=".8"/><rect x="0" y="8" width="8" height="6" rx=".8"/><rect x="10" y="8" width="8" height="6" rx=".8" opacity=".45"/></g></svg>'
};

/* ================= Desktop bridge (Keeper Studio) ================= */
const KS_TOKEN = window.KS_TOKEN;
async function api(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-KS-Token': KS_TOKEN }, body: JSON.stringify(body || {}) });
  const j = await r.json().catch(() => ({ error: 'Keeper Studio sent back something unexpected.' }));
  if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}
const enc = encodeURIComponent;
const EDIT_VER = new Map();  // path -> retouch time, so a retouched photo's pictures refresh
const ev = path => { const v = EDIT_VER.get(path); return v ? `&v=${v}` : ''; };
// Features Jamie doesn't use: hidden from the menus, code kept so they can come back.
const HIDDEN = new Set(['roes', 'import']);
const thumbUrl = (path, s = 400) => `/thumb?p=${enc(path)}&s=${s}&t=${KS_TOKEN}${ev(path)}`;
const previewUrl = (path, s = 2048) => `/preview?p=${enc(path)}&s=${s}&t=${KS_TOKEN}${ev(path)}`;
const fullUrlFor = path => `/full?p=${enc(path)}&t=${KS_TOKEN}${ev(path)}`;
const fileUrl = (path, bust) => `/file?p=${enc(path)}&t=${KS_TOKEN}${bust ? '&v=' + bust : ''}`;
const WORK_STORES = new Set(['meta', 'collections', 'manual', 'styles']);
const workTouched = s => { if (WORK_STORES.has(s) && typeof Work !== 'undefined') Work.schedule(); };
const DB = {
  get: (s, k) => api('/api/db/get', { store: s, key: k }).then(r => r.value),
  put: (s, k, v) => api('/api/db/put', { store: s, items: [[k, v]] }).then(r => (workTouched(s), r)),
  del: (s, k) => api('/api/db/del', { store: s, key: k }).then(r => (workTouched(s), r)),
  putMany: (s, list) => list.length ? api('/api/db/put', { store: s, items: list }).then(r => (workTouched(s), r)) : Promise.resolve(),
  entries: s => api('/api/db/entries', { store: s }).then(r => r.entries),
};
const baseName = p => String(p || '').split(/[\\/]/).pop();
const dirName = p => { const s = String(p || ''); const i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\')); return i > 0 ? s.slice(0, i) : s; };
// Native dialogs in the app window; a typed path when running in a plain browser.
async function pickPath(kind, opts = {}) {
  let r;
  try { r = await api('/api/dialog', { kind, ...opts }); } catch (e) { toast(esc(e.message)); return null; }
  if (!r.unavailable) return (r.paths && r.paths[0]) || null;
  return promptPath(kind === 'folder' ? 'Choose a folder' : kind === 'save' ? 'Save as' : 'Choose a file', opts.initial || '');
}
function promptPath(label, initial) {
  // Its own little dialog (above any open one), used only when running in a plain browser.
  return new Promise(res => {
    const wrap = document.createElement('div'); wrap.className = 'prompt-wrap';
    wrap.innerHTML = `<div class="modal-card"><h3>${esc(label)}</h3><label class="fld"><span>Full path</span><input id="ppIn" value="${esc(initial)}" spellcheck="false"></label>
      <div class="m-actions"><button class="btn" data-pp="0">Cancel</button><button class="btn primary" data-pp="1">OK</button></div></div>`;
    document.body.appendChild(wrap);
    const input = wrap.querySelector('#ppIn'); input.focus(); input.select();
    const done = ok => { const v = input.value.trim(); wrap.remove(); res(ok && v ? v : null); };
    wrap.addEventListener('click', e => { const b = e.target.closest('[data-pp]'); if (b) done(b.dataset.pp === '1'); });
    input.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') done(true); if (e.key === 'Escape') done(false); });
  });
}
const reveal = path => api('/api/reveal', { path }).catch(e => toast(esc(e.message)));
const openExternal = path => api('/api/open-file', { path }).catch(e => toast(esc(e.message)));
async function pollJob(id, onUpdate) {
  let since = 0;
  for (;;) {
    let s;
    try { s = await (await fetch(`/api/job/${id}?since=${since}`, { headers: { 'X-KS-Token': KS_TOKEN } })).json(); }
    catch { await new Promise(r => setTimeout(r, 800)); continue; }
    since = s.items_total || since;
    onUpdate && onUpdate(s);
    if (s.finished) return s;
    await new Promise(r => setTimeout(r, 350));
  }
}
const cancelJob = id => api('/api/job/cancel', { id }).catch(() => {});
function fmtDur(sec) { sec = Math.max(0, Math.round(sec || 0)); return sec < 60 ? `${sec}s` : `${Math.floor(sec / 60)}m ${String(sec % 60).padStart(2, '0')}s`; }

/* ================= State ================= */
const prefs = (() => { try { return JSON.parse(localStorage.getItem('keeperstudio.prefs') || '{}'); } catch { return {}; } })();
const S = {
  gen: 0, photos: [], byId: new Map(), byKey: new Map(), nextId: 1, skipped: 0, skippedExt: new Map(), undecodable: 0, failures: [], heicNative: null, loadingMsg: '',
  view: [], viewIndex: new Map(),
  selected: new Set(), active: null, anchor: null, pendingSingle: null,
  mode: 'grid', cols: 1,
  source: { type: 'all' },
  filter: { flag: 'any', rating: 0, label: 'any', text: '', crop: 'any' },
  cropShow: 'all',  // Crop's Show buttons: all / both (Picks + teams) / picks / teams
  sort: prefs.sort || 'capture', sortDir: prefs.sortDir || 1,
  thumbSize: prefs.thumbSize || 190,
  filmH: Math.min(320, Math.max(84, prefs.filmH || 124)),
  leftW: Math.min(520, Math.max(200, prefs.leftW || 240)),
  rightW: Math.min(560, Math.max(240, prefs.rightW || 280)),
  compare: { select: null, cand: null, side: 'select' },
  surveyIds: [],
  zoom: { mode: 'fit', cx: .5, cy: .5 },
  lights: 0, fs: false,
  autoAdvance: !!prefs.autoAdvance, caps: false,
  panels: Object.assign({ left: innerWidth > 900, right: innerWidth > 900, top: true, film: true, toolbar: true, filterbar: true }, prefs.panels || {}),
  sections: Object.assign({}, prefs.sections || {}),
  banners: [],
  module: 'library', root: '', rootName: '', recent: [], byPath: new Map(), exportDest: '',
  exporting: null,
};
function savePrefs() {
  try { localStorage.setItem('keeperstudio.prefs', JSON.stringify({ sort: S.sort, sortDir: S.sortDir, thumbSize: S.thumbSize, filmH: S.filmH, leftW: S.leftW, rightW: S.rightW, autoAdvance: S.autoAdvance, panels: S.panels, sections: S.sections, ordShowArchived: !!prefs.ordShowArchived, ordWhatIfClosed: !!prefs.ordWhatIfClosed, ordPv: prefs.ordPv || null, ordSort: prefs.ordSort || null, ordThumbs: prefs.ordThumbs !== false })); } catch {}
}

/* ---------- Metadata (flags / ratings / labels) ---------- */
const META_DEFAULT = Object.freeze({ flag: 0, rating: 0, label: '', team: false });
const metaMap = new Map();
const dirtyMeta = new Set(); let metaTimer = null;
const getMeta = key => metaMap.get(key) || META_DEFAULT;
function setMeta(key, patch) {
  metaMap.set(key, { ...getMeta(key), ...patch });
  dirtyMeta.add(key);
  clearTimeout(metaTimer); metaTimer = setTimeout(flushMeta, 250);
}
async function flushMeta() {
  const keys = [...dirtyMeta]; dirtyMeta.clear();
  try { await DB.putMany('meta', keys.map(k => [k, metaMap.get(k)])); } catch {}
}
window.addEventListener('beforeunload', () => { if (dirtyMeta.size) flushMeta(); });

/* ---------- Collections ---------- */
let collections = [{ id: QUICK, name: 'Quick Collection', keys: new Set(), smart: null, created: 0 }];
const getColl = id => collections.find(c => c.id === id);
const quickColl = () => getColl(QUICK);
const userColls = () => collections.filter(c => c.id !== QUICK).sort((a, b) => collator.compare(a.name, b.name));
function saveColl(c) { DB.put('collections', c.id, { id: c.id, name: c.name, keys: [...c.keys], smart: c.smart || null, created: c.created || 0 }).catch(() => {}); }
const inQuick = p => quickColl().keys.has(p.key);
function inColl(c, p) { return c.smart ? matchRules(p, c.smart) : c.keys.has(p.key); }
function collPhotos(c) {
  if (c.smart) return S.photos.filter(p => matchRules(p, c.smart));
  const out = []; for (const k of c.keys) { const p = S.byKey.get(k); if (p) out.push(p); } return out;
}
function collCount(c) {
  if (c.smart) { let n = 0; for (const p of S.photos) if (matchRules(p, c.smart)) n++; return n; }
  let n = 0; for (const k of c.keys) if (S.byKey.has(k)) n++; return n;
}

async function loadStore() {
  try { for (const [k, v] of await DB.entries('meta')) metaMap.set(k, v); } catch {}
  try {
    for (const [, v] of await DB.entries('collections')) {
      if (v.id === QUICK) { for (const k of v.keys || []) quickColl().keys.add(k); continue; }
      collections.push({ id: v.id, name: v.name, keys: new Set(v.keys || []), smart: v.smart || null, created: v.created || 0 });
    }
  } catch {}
}

/* ================= Filtering & sorting ================= */
function matchRules(p, r) {
  const m = getMeta(p.key);
  switch (r.flag) {
    case 'pick': if (m.flag !== 1) return false; break;
    case 'unflagged': if (m.flag !== 0) return false; break;
    case 'rejected': if (m.flag !== -1) return false; break;
    case 'notrejected': if (m.flag === -1) return false; break;
  }
  if (r.team && !m.team) return false;
  if (r.rating && m.rating < r.rating) return false;
  if (r.label && r.label !== 'any') { if (r.label === 'none' ? !!m.label : m.label !== r.label) return false; }
  if (r.text && !p.name.toLowerCase().includes(r.text.toLowerCase())) return false;
  if (r.crop && r.crop !== 'any') { const st = (Crop.status.get(p.path) || {}).status || 'unchecked'; if (r.crop === 'ready' ? !READY.has(st) : st !== r.crop) return false; }
  if (r.cstyle && r.cstyle !== 'any' && (Crop.styleOf(p.path) || 'batch') !== r.cstyle) return false;
  return true;
}
function sorter() {
  const d = S.sortDir;
  if (S.sort === 'name') return (a, b) => d * collator.compare(a.name, b.name) || d * (a.id - b.id);
  if (S.sort === 'rating') return (a, b) => d * (getMeta(a.key).rating - getMeta(b.key).rating) || (a.capture - b.capture) || (a.id - b.id);
  return (a, b) => d * (a.capture - b.capture) || d * collator.compare(a.name, b.name);
}
function sourcePhotos() {
  const s = S.source;
  if (s.type === 'folder') return S.photos.filter(p => p.folder === s.id || p.folder.startsWith(s.id + '/'));
  if (s.type === 'coll') { const c = getColl(s.id); return c ? collPhotos(c) : []; }
  return S.photos;
}
const srcKey = s => s.type === 'all' ? 'all' : `${s.type}:${s.id}`;
function parseSrc(k) { if (k === 'all') return { type: 'all' }; const i = k.indexOf(':'); return { type: k.slice(0, i), id: k.slice(i + 1) }; }
function sourceName() {
  const s = S.source;
  if (s.type === 'all') return 'All Photographs';
  if (s.type === 'folder') return 'Folder: ' + s.id.split('/').pop();
  const c = getColl(s.id); return c ? (c.id === QUICK ? 'Quick Collection' : 'Collection: ' + c.name) : 'Collection';
}
// Crop's Show buttons filter the filmstrip: Picks (P) and team photos (T)
function cropShowTest(w) {
  if (!w || w === 'all') return null;
  const isT = p => !!getMeta(p.key).team, isP = p => getMeta(p.key).flag === 1;
  return w === 'teams' ? isT : w === 'picks' ? (p => isP(p) && !isT(p)) : (p => isP(p) || isT(p));
}
const CROP_SHOW_NAMES = { both: 'Picks + Teams', picks: 'Picks', teams: 'Teams' };
function recomputeView() {
  const cs = S.module === 'crop' ? cropShowTest(S.cropShow) : null;
  const arr = sourcePhotos().filter(p => matchRules(p, S.filter) && (!cs || cs(p))).sort(sorter());
  S.view = arr;
  S.viewIndex = new Map(arr.map((p, i) => [p.id, i]));
  for (const id of [...S.selected]) if (!S.viewIndex.has(id)) S.selected.delete(id);
  if (S.active != null && !S.viewIndex.has(S.active)) S.active = null;
  S.surveyIds = S.surveyIds.filter(id => S.viewIndex.has(id));
}
const orderedSelection = () => [...S.selected].filter(id => S.viewIndex.has(id)).sort((a, b) => S.viewIndex.get(a) - S.viewIndex.get(b));

/* ================= Render scheduler ================= */
const R_CELLS = 1, R_ALL = 2, R_RECOMPUTE = 4;
let rafFlags = 0, rafPending = false;
function schedule(f) { rafFlags |= f; if (!rafPending) { rafPending = true; requestAnimationFrame(flush); } }
function flush() {
  rafPending = false; const f = rafFlags; rafFlags = 0;
  if (f & R_RECOMPUTE) {
    recomputeView();
    if (S.mode !== 'grid' && S.active == null && S.view.length) { S.active = S.view[0].id; S.selected = new Set([S.active]); }
    if (S.mode === 'compare' && (!S.viewIndex.has(S.compare.select) || (S.compare.cand != null && !S.viewIndex.has(S.compare.cand)))) enterCompare();
    renderAll();
  } else if (f & R_ALL) renderAll();
  else if (f & R_CELLS) { renderGrid(); renderFilm(); if (S.mode === 'survey') renderSurvey(); if (S.mode === 'loupe') renderLoupe(); if (S.mode === 'compare') renderCompare(); }
}

/* ================= Thumbnails & full-size images (served by Keeper Studio) ================= */
const Thumbs = { request(p) { if (p.thumbState >= 2 || p.dead) return; p.thumbUrl = thumbUrl(p.path); p.thumbState = 2; }, reset() {} };
const isHeic = () => false;
const needsConvert = () => false;
const ENV = { blobImg: true, ready: Promise.resolve() };
// Large views show a 2560 px preview (fast, light on memory); the 30 MP original
// is only fetched when you zoom in past the preview's detail.
const PREVIEW_PX = 2560;
function fullUrl(p) { return previewUrl(p.path, PREVIEW_PX); }
async function fullUrlAsync(p) { return fullUrl(p); }
async function displayBlob() { return null; }
function preload(p) { if (!p) return; const im = new Image(); im.decoding = 'async'; im.src = fullUrl(p); }
function onThumb(p) { schedule(R_CELLS); if (p.id === S.active) renderRight(); }
async function readExif(p) { return p.exif; }

/* ---------- Photo details (pixel size, capture time, camera) ---------- */
async function infoPass(gen) {
  const list = S.photos.slice(); const B = 150;
  for (let i = 0; i < list.length; i += B) {
    if (gen !== S.gen) return;
    let r;
    try { r = await api('/api/library/info', { paths: list.slice(i, i + B).map(p => p.path) }); } catch { continue; }
    if (gen !== S.gen) return;
    for (const it of r.items) {
      const p = S.byPath.get(it.path); if (!p) continue;
      p.w = it.w || 0; p.h = it.h || 0; p.exif = it.exif || {};
      if (it.capture) { p.capture = it.capture; p.hasCapture = true; }
    }
    if (i === 0) { renderRight(); layoutAllPanes(); }
  }
  if (gen !== S.gen) return;
  if (S.sort === 'capture') { schedule(R_RECOMPUTE); requestAnimationFrame(() => requestAnimationFrame(ensureVisible)); }
  renderRight(); layoutAllPanes();
}

/* ================= Loading photos ================= */
async function openFolder() {
  const path = await pickPath('folder', { initial: S.root || '' });
  if (path) loadFolder(path);
}
const openFiles = openFolder;
/* ================= Folder work file ================= */
// Marks also go into "Keeper Studio work.json" in the shoot folder, so they survive the
// folder being moved, renamed or opened on another PC (see keeperstudio/workfile.py).
const Work = {
  timer: null, pending: null, ready: false, warned: false,
  // rel: the photo's place inside the opened folder (not including the folder's own name), with / separators
  rel(p) { const r = String(S.root || '').replace(/[\\/]+$/, ''), q = String(p.path); return (q.toLowerCase().startsWith(r.toLowerCase()) ? q.slice(r.length) : p.name).replace(/\\/g, '/').replace(/^\/+/, ''); },
  args() { return { root: S.root, photos: S.photos.map(p => ({ path: p.path, rel: this.rel(p), size: p.size })) }; },
  schedule() {
    if (!S.root || !S.photos.length || !this.ready) return;
    this.pending = this.args();
    clearTimeout(this.timer); this.timer = setTimeout(() => this.flush(), 4000);
  },
  async flush(say) {
    clearTimeout(this.timer); this.timer = null;
    if (say && dirtyMeta.size) await flushMeta();  // marks typed in the last moment
    const a = this.pending || (say && S.root ? this.args() : null); this.pending = null;
    if (!a || !a.root) return;
    try {
      const r = await api('/api/work/save', a);
      if (r.error) { if (say || !this.warned) toast(esc(r.error), 5000); this.warned = true; return; }
      if (say) toast(r.zip ? 'Photos opened from a .zip can’t have a work file; their marks are kept in the catalog' : r.skipped ? 'Nothing marked in this folder yet, so there was nothing to save' : `Saved this folder's work (${plural(r.photos, 'marked photo')}) to “Keeper Studio work.json” in the folder`, 4500);
    } catch (e) { if (say) toast(esc(e.message)); }
  },
  // After a folder opens: offer to restore marks saved with it, or left behind where it used to be.
  async check(gen) {
    this.ready = false;
    S.banners = S.banners.filter(b => b.id !== 'work');
    let st;
    try { st = await api('/api/work/status', this.args()); } catch { this.ready = true; return; }
    if (gen !== S.gen) return;
    if (!st.marks_here && st.file && st.file.photos) {
      const when = st.file.saved ? new Date(st.file.saved * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '';
      S.banners.push({ id: 'work', cls: 'info', text: `This folder has saved work: marks on ${plural(st.file.photos, 'photo')}${when ? `, saved ${when}` : ''}${st.file.folder && st.file.folder !== S.root ? ` in “${st.file.folder}”` : ''}. Bring them back?`, work: { source: 'file', label: 'Restore marks' } });
    } else if (!st.marks_here && st.moved) {
      S.banners.push({ id: 'work', cls: 'info', text: `${plural(st.moved.photos, 'photo')} in this folder were marked before, in “${st.moved.folder}”. Bring those marks over?`, work: { source: 'moved', folder: st.moved.folder, label: 'Bring marks over' } });
    }
    renderBanners();
    this.ready = true;
    if (st.marks_here && !st.file) { this.pending = this.args(); this.flush(); }  // first time: start the work file for a shoot that already has marks
  },
  async restore(w) {
    const btn = $('#banners [data-banner-work]'); if (btn) btn.disabled = true;
    let r;
    try { r = await api('/api/work/restore', { ...this.args(), source: w.source, folder: w.folder || '' }); }
    catch (e) { if (btn) btn.disabled = false; return toast(esc(e.message)); }
    S.banners = S.banners.filter(b => b.id !== 'work');
    metaMap.clear(); collections = [{ id: QUICK, name: 'Quick Collection', keys: new Set(), smart: null, created: 0 }]; await loadStore();
    Crop.manual.clear(); Crop.styles.clear(); Crop.rotations.clear(); await Crop.load();
    recomputeView(); renderAll(); renderBanners();
    toast(`Restored marks on ${plural(r.restored, 'photo')}`, 4000);
  },
};

async function loadFolder(path) {
  setLoading(`Reading “${baseName(path)}”…`);
  let res;
  try { res = await api('/api/library/open', { path }); }
  catch (e) { S.loadingMsg = ''; renderEmpty(); return toast(esc(e.message)); }
  S.recent = res.recent || S.recent; S.root = res.root; S.rootName = res.name;
  loadPhotos(res);
}
window.KS_onDropPaths = async paths => {
  S.dropDepth = 0; $('#dropzone').classList.remove('on');
  if (!paths || !paths.length) return;
  const first = paths[0];
  try { await api('/api/library/open', { path: first }); loadFolder(first); }
  catch { loadFolder(dirName(first)); }
};
function setLoading(msg) { S.loadingMsg = msg; if (!S.photos.length) renderEmpty(); }

function loadPhotos(res) {
  if (Work.pending) Work.flush();
  S.gen++; clearGrid(); clearFilm();
  S.photos = []; S.byId.clear(); S.byKey.clear(); S.byPath = new Map(); S.selected = new Set(); S.active = null; S.anchor = null;
  S.skipped = 0; S.skippedExt = new Map(); S.undecodable = 0; S.failures = []; S.surveyIds = []; undoStack.length = 0; S.loadingMsg = '';
  for (const f of res.photos) {
    const p = { id: S.nextId++, key: `${f.path}|${f.size}`, path: f.path, name: f.name, rel: f.rel, folder: f.folder,
                size: f.size, capture: f.mtime, hasCapture: false, w: 0, h: 0, thumbUrl: null, thumbState: 0, exif: null, hist: null, dead: false };
    S.photos.push(p); S.byId.set(p.id, p); S.byKey.set(p.key, p); S.byPath.set(p.path, p);
  }
  for (const [x, n] of Object.entries(res.skipped || {})) { S.skipped += n; S.skippedExt.set(x.replace(/^\./, '') || 'no extension', n); }
  S.source = { type: 'all' }; S.mode = 'grid'; S.zoom = { mode: 'fit', cx: .5, cy: .5 };
  // A new shoot starts unfiltered: a leftover filter (e.g. Crop: Needs review) would hide every photo.
  S.filter = { flag: 'any', rating: 0, label: 'any', text: '', crop: 'any' }; if ($('#fText')) $('#fText').value = '';
  updateSkippedBanner();
  recomputeView();
  if (S.view.length) { S.active = S.view[0].id; S.selected = new Set([S.active]); S.anchor = S.active; }
  $('#gridScroll').scrollTop = 0; $('#filmScroll').scrollLeft = 0;
  for (const p of S.photos) Thumbs.request(p);
  document.title = `${res.name} — Keeper Studio`;
  Mods.libraryLoaded();
  renderAll();
  infoPass(S.gen);
  if (S.photos.length) Work.check(S.gen);
  if (!S.photos.length) toast(S.skipped ? 'No photos Keeper Studio can read in that folder' : 'That folder has no photos');
  else toast(`Loaded ${plural(S.photos.length, 'photo')} from “${esc(res.name)}”`);
}

function updateSkippedBanner() {
  S.banners = S.banners.filter(b => b.id !== 'skipped' && !b.id.startsWith('fail'));
  if (S.skipped) {
    const kinds = [...S.skippedExt].map(([x, n]) => `${n} .${x}`).join(', ');
    S.banners.push({ id: 'skipped', text: `${plural(S.skipped, 'file')} skipped (${kinds}) — not a photo format Keeper reads. Supported: JPEG, PNG, WebP, HEIC/HEIF/HIF, or a .zip of those.` });
  }
  const groups = new Map();
  for (const f of S.failures) { if (!groups.has(f.reason)) groups.set(f.reason, []); groups.get(f.reason).push(f.name); }
  let gi = 0;
  for (const [reason, names] of groups) {
    const list = names.slice(0, 3).join(', ') + (names.length > 3 ? `, +${names.length - 3} more` : '');
    S.banners.push({ id: 'fail' + gi++, text: `${plural(names.length, 'photo')} couldn’t be opened because ${reason}: ${list}` });
  }
  renderBanners();
}

/* ================= Marking & undo ================= */
const undoStack = [];
function pushUndo(u) { undoStack.push(u); if (undoStack.length > 300) undoStack.shift(); }
function undo() {
  const u = undoStack.pop(); if (!u) return toast('Nothing to undo');
  if (u.meta) for (const [k, v] of u.meta) setMeta(k, v);
  if (u.coll) { const c = getColl(u.coll.id); if (c) { u.coll.added.forEach(k => c.keys.delete(k)); u.coll.removed.forEach(k => c.keys.add(k)); saveColl(c); } }
  toast('Undo: ' + u.label);
  afterChange(false);
}
function targets() {
  let ids;
  if (S.module !== 'library') ids = S.selected.size > 1 ? orderedSelection() : (S.active != null ? [S.active] : []);
  else if (S.mode === 'grid') ids = S.selected.size ? orderedSelection() : (S.active != null ? [S.active] : []);
  else if (S.mode === 'compare') ids = [S.compare.side === 'cand' ? S.compare.cand : S.compare.select].filter(v => v != null);
  else ids = S.active != null ? [S.active] : [];
  return ids.map(id => S.byId.get(id)).filter(Boolean);
}
const autoOn = () => S.autoAdvance || S.caps;
function describe(f, v) {
  if (f === 'flag') return v === 1 ? `<span style="color:var(--accent)">⚑</span> Flagged as Pick` : v === -1 ? `<span style="color:var(--reject)">⚑</span> Flagged as Rejected` : 'Unflagged';
  if (f === 'rating') return v ? 'Rating ' + '★'.repeat(v) : 'Rating cleared';
  if (f === 'team') return v ? '<span class="tbadge">T</span> Marked as a team photo' : 'Team photo mark removed';
  return v ? `Label: <span style="color:var(--l-${v})">■</span> ${LABEL_NAMES[v]}` : 'Label cleared';
}
function applyMetaTo(ps, field, value, advance) {
  if (!ps.length) return;
  if (field === 'label' && value && ps.every(p => getMeta(p.key).label === value)) value = '';
  const before = new Map();
  for (const p of ps) { before.set(p.key, { ...getMeta(p.key) }); setMeta(p.key, { [field]: value }); }
  const label = describe(field, value);
  pushUndo({ label, meta: before });
  toast(label + (ps.length > 1 ? ` · ${ps.length} photos` : ''));
  afterChange(advance && ps.length === 1);
}
const mark = (field, value, forceAdvance) => applyMetaTo(targets(), field, value, forceAdvance || autoOn());
// T: team photo on/off (all of the targets on, unless they all already are)
const markTeam = forceAdvance => { const ps = targets(); applyMetaTo(ps, 'team', !ps.every(p => getMeta(p.key).team), forceAdvance || autoOn()); };
const teamBadge = m => m.team ? '<span class="tbadge" title="Team photo (T)">T</span>' : '';
function toggleQuickFor(ps) {
  if (!ps.length) return;
  const q = quickColl(); const allIn = ps.every(p => q.keys.has(p.key)); const added = [], removed = [];
  for (const p of ps) {
    if (allIn) { q.keys.delete(p.key); removed.push(p.key); }
    else if (!q.keys.has(p.key)) { q.keys.add(p.key); added.push(p.key); }
  }
  saveColl(q);
  const label = allIn ? 'Removed from Quick Collection' : 'Added to Quick Collection';
  pushUndo({ label, coll: { id: QUICK, added, removed } });
  toast(label + (ps.length > 1 ? ` · ${ps.length} photos` : ''));
  afterChange(false);
}
function addToColl(id, ids) {
  const c = getColl(id); if (!c || c.smart) return;
  const added = [];
  for (const pid of ids) { const p = S.byId.get(pid); if (p && !c.keys.has(p.key)) { c.keys.add(p.key); added.push(p.key); } }
  saveColl(c);
  const name = c.id === QUICK ? 'Quick Collection' : `“${c.name}”`;
  pushUndo({ label: `Add to ${name}`, coll: { id, added, removed: [] } });
  toast(added.length ? `Added ${plural(added.length, 'photo')} to ${esc(name)}` : `Already in ${esc(name)}`);
  afterChange(false);
}
function cellAction(id, act, v) {
  const p = S.byId.get(id); if (!p) return;
  const m = getMeta(p.key);
  if (act === 'qc') toggleQuickFor([p]);
  else if (act === 'flag') applyMetaTo([p], 'flag', m.flag === 1 ? 0 : 1, false);
  else if (act === 'star') applyMetaTo([p], 'rating', m.rating === v ? 0 : v, false);
  else if (act === 'remove') { S.surveyIds = S.surveyIds.filter(x => x !== id); S.selected.delete(id); if (S.active === id) S.active = S.surveyIds[0] ?? null; renderAll(); }
}
function moveTo(i) {
  if (!S.view.length) return;
  const p = S.view[clamp(i, 0, S.view.length - 1)];
  S.active = p.id; S.selected = new Set([p.id]); S.anchor = p.id;
}
function afterChange(advance) {
  const m = S.module !== 'library' ? 'module' : S.mode;
  if (m === 'module') {
    const old = S.active, oldIdx = old != null ? S.viewIndex.get(old) : null;
    recomputeView();
    if (old != null) { if (S.viewIndex.has(old)) { if (advance) moveTo(S.viewIndex.get(old) + 1); } else if (S.view.length && oldIdx != null) moveTo(Math.min(oldIdx, S.view.length - 1)); }
    renderAll(); ensureVisible(); return;
  }
  if (m === 'compare') {
    const c = S.compare; const si = S.viewIndex.get(c.select), ci = S.viewIndex.get(c.cand);
    recomputeView();
    const pick = (idx, avoid) => {
      if (idx == null || !S.view.length) return null;
      let i = Math.min(idx, S.view.length - 1);
      if (S.view[i].id === avoid) i = i + 1 < S.view.length ? i + 1 : i - 1;
      return S.view[i] ? S.view[i].id : null;
    };
    if (!S.viewIndex.has(c.select)) c.select = pick(si, c.cand);
    if (c.cand == null || !S.viewIndex.has(c.cand) || c.cand === c.select) c.cand = pick(ci ?? si, c.select);
    else if (advance) compareStep(1);
    if (c.cand === c.select) c.cand = null;
    S.active = (c.side === 'cand' ? c.cand : c.select) ?? c.select;
    renderAll(); ensureVisible(); return;
  }
  if (m === 'survey') {
    const i = S.surveyIds.indexOf(S.active);
    recomputeView();
    if (!S.surveyIds.includes(S.active)) S.active = S.surveyIds[clamp(i, 0, S.surveyIds.length - 1)] ?? null;
    else if (advance) S.active = S.surveyIds[Math.min(i + 1, S.surveyIds.length - 1)];
    renderAll(); return;
  }
  const old = S.active; const oldIdx = old != null ? S.viewIndex.get(old) : null;
  recomputeView();
  if (old != null) {
    if (S.viewIndex.has(old)) { if (advance) moveTo(S.viewIndex.get(old) + 1); }
    else if (S.view.length && oldIdx != null) moveTo(Math.min(oldIdx, S.view.length - 1));
  }
  renderAll(); ensureVisible();
}

/* ================= Selection & navigation ================= */
function selectByClick(id, e, fromFilm) {
  const mod = e.ctrlKey || e.metaKey;
  if (fromFilm && S.mode === 'compare' && !mod && !e.shiftKey) {
    if (id !== S.compare.select) { S.compare.cand = id; S.compare.side = 'cand'; S.active = id; S.selected = new Set([S.compare.select, id]); }
    renderAll(); return;
  }
  if (e.shiftKey && S.anchor != null && S.viewIndex.has(S.anchor)) {
    const a = S.viewIndex.get(S.anchor), b = S.viewIndex.get(id); const [lo, hi] = a < b ? [a, b] : [b, a];
    const set = mod ? new Set(S.selected) : new Set();
    for (let i = lo; i <= hi; i++) set.add(S.view[i].id);
    S.selected = set; S.active = id;
  } else if (mod) {
    if (S.selected.has(id)) { S.selected.delete(id); if (S.active === id) S.active = S.selected.size ? orderedSelection().pop() : null; }
    else { S.selected.add(id); S.active = id; }
    S.anchor = id;
  } else {
    if (S.selected.has(id) && S.selected.size > 1) { S.pendingSingle = id; S.active = id; }
    else { S.selected = new Set([id]); S.active = id; }
    S.anchor = id;
  }
  if (S.mode === 'survey') { S.surveyIds = orderedSelection(); if (!S.surveyIds.length && S.active != null) S.surveyIds = [S.active]; }
  if (S.mode === 'compare') enterCompare();
  refreshSelection();
  if (fromFilm && S.module === 'orders' && !mod && !e.shiftKey) Ord.photoClicked(id);
}
function refreshSelection() {
  $('#app').classList.toggle('multi', S.photos.length > 0 && S.selected.size > 1 && S.mode !== 'grid');
  renderGrid(); renderFilm(); renderFilmBar(); renderRight(); syncToolbar();
  // Crop / Composite / Extract draw their own view: a click in the filmstrip must redraw it
  // even when Library was left in Grid view.
  if (S.module !== 'library') renderLeft();
  if (S.mode !== 'grid' || S.module !== 'library') renderView();
  if (S.fs) renderFs();
}
function selectAll() { S.selected = new Set(S.view.map(p => p.id)); if (S.active == null && S.view.length) S.active = S.view[0].id; refreshSelection(); }
function deselect() { S.selected = new Set(); S.active = null; refreshSelection(); }
function step(d) {
  const cur = S.viewIndex.get(S.active) ?? -1;
  const i = clamp(cur + d, 0, S.view.length - 1); const p = S.view[i]; if (!p) return;
  S.active = p.id; S.selected = new Set([p.id]); S.anchor = p.id;
  renderAll(); ensureVisible();
}
function nav(dx, dy, e) {
  if (!S.view.length) return;
  const d = dx || dy;
  if (S.fs || S.mode === 'loupe' || S.module !== 'library') return step(d);
  if (S.mode === 'compare') { compareStep(d); S.compare.side = 'cand'; S.active = S.compare.cand ?? S.compare.select; renderAll(); ensureVisible(); return; }
  if (S.mode === 'survey') {
    const ids = S.surveyIds; if (!ids.length) return;
    S.active = ids[clamp(ids.indexOf(S.active) + d, 0, ids.length - 1)]; renderAll(); return;
  }
  const cols = S.cols || 1;
  const cur = S.active != null && S.viewIndex.has(S.active) ? S.viewIndex.get(S.active) : -1;
  const i = cur < 0 ? 0 : clamp(cur + dx + dy * cols, 0, S.view.length - 1);
  const id = S.view[i].id;
  if (e.shiftKey && S.anchor != null && S.viewIndex.has(S.anchor)) {
    const a = S.viewIndex.get(S.anchor); const [lo, hi] = a < i ? [a, i] : [i, a];
    S.selected = new Set(S.view.slice(lo, hi + 1).map(p => p.id));
  } else { S.selected = new Set([id]); S.anchor = id; }
  S.active = id; refreshSelection(); ensureVisible();
}
function ensureVisible() {
  const i = S.viewIndex.get(S.active); if (i == null) return;
  if (S.mode === 'grid') {
    const sc = $('#gridScroll'); const { cols, ch, pad } = gridMetrics();
    const y = pad + Math.floor(i / cols) * ch;
    if (y < sc.scrollTop) sc.scrollTop = y - pad;
    else if (y + ch > sc.scrollTop + sc.clientHeight) sc.scrollTop = y + ch - sc.clientHeight + pad;
  }
  const fs = $('#filmScroll'); const x = i * FW;
  if (x < fs.scrollLeft) fs.scrollLeft = Math.max(0, x - FW);
  else if (x + FW > fs.scrollLeft + fs.clientWidth) fs.scrollLeft = x + FW * 2 - fs.clientWidth;
}

/* ================= Modes ================= */
function setMode(m) {
  if (!S.photos.length) return;
  if (m !== 'grid' && S.active == null && S.view.length) { S.active = S.view[0].id; S.selected = new Set([S.active]); S.anchor = S.active; }
  if (m === 'compare') enterCompare();
  if (m === 'survey') {
    let ids = orderedSelection(); if (!ids.length && S.active != null) ids = [S.active];
    S.surveyIds = ids; if (!ids.includes(S.active)) S.active = ids[0] ?? null;
  }
  if (m !== S.mode && (m === 'loupe' || m === 'compare' || m === 'survey')) S.zoom = { mode: 'fit', cx: .5, cy: .5 };
  S.mode = m; renderAll();
  if (m === 'grid') requestAnimationFrame(ensureVisible); else ensureVisible();
}
function enterCompare() {
  const sel = orderedSelection();
  let select = S.viewIndex.has(S.active) ? S.active : (sel[0] ?? S.view[0]?.id ?? null);
  let cand = sel.find(id => id !== select) ?? null;
  if (cand == null && select != null) { const i = S.viewIndex.get(select); cand = S.view[i + 1]?.id ?? S.view[i - 1]?.id ?? null; }
  S.compare = { select, cand, side: S.compare.side === 'cand' && S.active === cand ? 'cand' : 'select' };
  S.active = S.compare.side === 'cand' ? cand : select;
}
function compareStep(d) {
  const c = S.compare; if (c.select == null) return;
  let j = S.viewIndex.get(c.cand ?? c.select);
  do { j += d; } while (S.view[j] && S.view[j].id === c.select);
  if (S.view[j]) c.cand = S.view[j].id;
}
function swapCompare() { const c = S.compare; if (c.cand == null) return; [c.select, c.cand] = [c.cand, c.select]; S.active = c.side === 'cand' ? c.cand : c.select; renderAll(); }
function makeSelect() {
  const c = S.compare; if (c.cand == null) return;
  c.select = c.cand; c.cand = null;
  const i = S.viewIndex.get(c.select); c.cand = S.view[i + 1]?.id ?? S.view[i - 1]?.id ?? null;
  c.side = 'select'; S.active = c.select; renderAll(); ensureVisible();
}
function toggleZoom() {
  if (S.mode !== 'loupe' && S.mode !== 'compare' && S.mode !== 'survey') { if (S.mode === 'grid' && S.active != null) { setMode('loupe'); S.zoom = { mode: '1:1', cx: .5, cy: .5 }; layoutAllPanes(); } return; }
  S.zoom = S.zoom.mode === 'fit' ? { mode: '1:1', cx: S.zoom.cx, cy: S.zoom.cy } : { mode: 'fit', cx: .5, cy: .5 };
  layoutAllPanes();
}
function cycleLights() { S.lights = (S.lights + 1) % 3; applyLights(); toast(['Lights on', 'Lights dim', 'Lights out'][S.lights]); }
function applyLights() { document.body.classList.toggle('lights1', S.lights === 1); document.body.classList.toggle('lights2', S.lights === 2); }
function toggleFs() {
  if (S.fs) return exitFs();
  if (S.active == null) { if (!S.view.length) return; S.active = S.view[0].id; }
  S.fs = true; $('#fs').classList.add('on'); renderFs();
  try { const r = document.documentElement.requestFullscreen?.(); r && r.catch(() => {}); } catch {}
}
function exitFs() {
  S.fs = false; $('#fs').classList.remove('on'); $('#fs')._pid = null;
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}

/* ================= Panels ================= */
function applyPanels() {
  const a = $('#app'), P = S.panels;
  a.style.setProperty('--lw', P.left ? S.leftW + 'px' : '0px');
  a.style.setProperty('--rw', P.right ? S.rightW + 'px' : '0px');
  a.style.setProperty('--th', P.top ? '44px' : '0px');
  a.style.setProperty('--fh', P.film ? S.filmH + 'px' : '0px'); FW = Math.round(S.filmH - 32);
  a.classList.toggle('no-left', !P.left); a.classList.toggle('no-right', !P.right);
  a.classList.toggle('no-top', !P.top); a.classList.toggle('no-film', !P.film);
  $('#edgeLeft button').textContent = P.left ? '◀' : '▶';
  $('#edgeRight button').textContent = P.right ? '▶' : '◀';
  $('#edgeTop button').textContent = P.top ? '▲' : '▼';
  $('#edgeBottom button').textContent = P.film ? '▼' : '▲';
  $('#toolbar').hidden = !P.toolbar;
  document.documentElement.style.setProperty('--fh', P.film ? S.filmH + 'px' : '0px');
}
function togglePanel(k) { S.panels[k] = !S.panels[k]; savePrefs(); renderAll(); }
function toggleSidePanels() { const v = !(S.panels.left || S.panels.right); S.panels.left = S.panels.right = v; savePrefs(); renderAll(); }
function toggleAllPanels() { const P = S.panels; const v = !(P.left || P.right || P.top || P.film); P.left = P.right = P.top = P.film = v; savePrefs(); renderAll(); }

/* ================= Rendering ================= */
function renderAll() {
  applyPanels(); renderBanners(); renderTop(); Mods.chrome(); renderLeft(); syncFilterBar(); renderView();
  renderFilm(); renderFilmBar(); renderRight(); syncToolbar(); if (S.fs) renderFs();
  if (S.module !== 'library') { const m = Mods.get(S.module); m && m.modbar && m.modbar(); }
}
function flagHTML(f, interactive) {
  const act = interactive ? ' data-act="flag" title="Toggle Pick (P)"' : '';
  if (f === 1) return `<span class="flag pick"${act}>${SVG_PICK}</span>`;
  if (f === -1) return `<span class="flag rej"${act}>${SVG_REJ}</span>`;
  return `<span class="flag"${act}>${SVG_OPEN}</span>`;
}
function starsHTML(r, interactive, cls = '') {
  let s = '';
  for (let i = 1; i <= 5; i++) s += `<i class="${i <= r ? 'on' : ''}"${interactive ? ` data-act="star" data-v="${i}"` : ''}>★</i>`;
  return `<span class="stars ${r ? '' : 'zero'} ${cls}">${s}</span>`;
}
function renderBanners() {
  $('#banners').innerHTML = S.banners.map(b => `<div class="banner ${b.cls || 'amber'}" data-id="${b.id}"><span>${esc(b.text)}</span>${b.action ? `<button class="btn sm banner-act" data-banner-url="${esc(b.action.url)}">${esc(b.action.label)}</button>` : ''}${b.work ? `<button class="btn sm banner-act primary" data-banner-work style="margin-left:auto">${esc(b.work.label)}</button>` : ''}${b.go ? `<button class="btn sm banner-act primary" data-banner-go="${b.id}" style="margin-left:auto">${esc(b.go.label)}</button>` : ''}<button data-dismiss="${b.id}" title="${b.id === 'update' ? 'Later' : 'Dismiss'}">✕</button></div>`).join('');
}
function renderTop() {
  if ($('#top')._built) return; $('#top')._built = true;
  $('#top').innerHTML = `<div class="logo">Keeper<b>.</b><span class="logo-sub">Studio</span></div>
    <div class="modules">${MODULES.map(([k, l], i) => `${!i ? '' : OCCASIONAL.has(k) && !OCCASIONAL.has(MODULES[i - 1][0]) ? '<span class="mod-div"></span>' : `<span class="bar">${OCCASIONAL.has(k) ? '·' : '|'}</span>`}<button data-module="${k}" class="${OCCASIONAL.has(k) ? 'occ' : ''}" title="${k === 'cutout' ? 'Extract the subject from the background' : l} (Ctrl+${i + 1})">${l}</button>`).join('')}</div>
    <div class="top-actions"><button class="btn sm" data-act="open" title="Open folder (Ctrl+O)">Open Folder…</button><button class="btn sm" data-act="export" title="Export (Ctrl+Shift+E)">Export…</button><button class="btn sm" data-act="help" title="Keyboard shortcuts (?)">?</button></div>`;
}
function sectionHTML(id, title, body, extra = '') {
  return `<section class="sec ${S.sections[id] === false ? 'closed' : ''}" data-sec="${id}"><header><span class="tri">▼</span><span>${title}</span>${extra}</header><div class="body">${body}</div></section>`;
}
function folderTree() {
  const counts = new Map();
  for (const p of S.photos) { const parts = p.folder.split('/'); for (let i = 1; i <= parts.length; i++) { const k = parts.slice(0, i).join('/'); counts.set(k, (counts.get(k) || 0) + 1); } }
  return [...counts.entries()].sort((a, b) => collator.compare(a[0], b[0]));
}
function keepScroll(sel, draw) {
  // panels are redrawn often (every check, every click): keep where the user had scrolled to
  const old = $(sel + ' .scroll'), y = old ? old.scrollTop : 0;
  // …and keep the cursor in a box the user is typing in (it is rebuilt by the redraw)
  const ae = document.activeElement; let key = null, ss = null, se = null;
  if (ae && $(sel).contains(ae) && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName)) {
    const at = [...ae.attributes].find(x => x.name.startsWith('data-'));
    if (at) { key = `[${at.name}="${CSS.escape(at.value)}"]`; try { ss = ae.selectionStart; se = ae.selectionEnd; } catch {} }
  }
  draw();
  const neu = $(sel + ' .scroll'); if (neu && y) neu.scrollTop = y;
  if (key) { const el = $(sel + ' ' + key); if (el && el !== document.activeElement) { el.focus({ preventScroll: true }); try { if (ss != null) el.setSelectionRange(ss, se); } catch {} } }
}
function renderLeft() {
  if (!S.panels.left) return;
  if (S.module !== 'library') { const m = Mods.get(S.module); return m && keepScroll('#left', () => m.left()); }
  const cur = srcKey(S.source);
  const row = (key, label, count, extra = '', attrs = '') =>
    `<div class="row src ${key === cur ? 'on' : ''}" data-src="${esc(key)}" ${attrs}>${label}${extra}<span class="cnt">${count}</span></div>`;
  const q = quickColl();
  let html = sectionHTML('catalog', 'Catalog',
    row('all', '<span class="ico">▦</span><span class="lbl">All Photographs</span>', S.photos.length) +
    row('coll:' + QUICK, '<span class="ico">●</span><span class="lbl">Quick Collection <span class="plus">+</span></span>', collCount(q), collCount(q) ? `<span class="row-acts"><button data-saveqc title="Save Quick Collection as a new collection (Ctrl/Cmd+Alt+B)">⤓</button></span>` : '', `data-drop="${QUICK}"`));
  const folders = folderTree();
  html += sectionHTML('folders', 'Folders', folders.length ? folders.map(([path, n]) => {
    const depth = path.split('/').length - 1;
    return row('folder:' + path, `<span class="ico">▸</span><span class="lbl">${esc(path.split('/').pop())}</span>`, n, '', `style="padding-left:${10 + depth * 14}px" title="${esc(path)}"`);
  }).join('') : '<div class="hint">No folder loaded yet.</div>');
  const colls = userColls();
  html += sectionHTML('colls', 'Collections', colls.length ? colls.map(c =>
    row('coll:' + c.id, `<span class="ico">${c.smart ? '⚙' : '▤'}</span><span class="lbl">${esc(c.name)}</span>`, collCount(c),
      `<span class="row-acts"><button data-edit="${c.id}" title="${c.smart ? 'Edit rules / rename' : 'Rename'}">✎</button><button data-delete="${c.id}" title="Delete collection">✕</button></span>`,
      c.smart ? 'title="Smart collection — updates live"' : `data-drop="${c.id}"`)).join('')
    : '<div class="hint">Click + to make a collection, then drag photos onto it. Smart collections fill themselves from rules.</div>',
    `<button class="hdr-btn" data-newcoll title="New collection (Ctrl/Cmd+N)">+</button>`);
  $('#left').innerHTML = `<div class="scroll">${html}</div><div class="left-foot"><button class="btn" data-act="open">Open…</button><button class="btn" data-act="export">Export…</button></div>`;
}
function syncFilterBar() {
  const fb = $('#filterbar'); if (!fb._built) return;
  $('#fFlag').value = S.filter.flag; $('#fCrop').value = S.filter.crop || 'any'; $('#fRating').value = String(S.filter.rating); $('#fLabel').value = S.filter.label;
  if (document.activeElement !== $('#fText')) $('#fText').value = S.filter.text;
  const opts = [['all', 'All Photographs'], ['coll:' + QUICK, 'Quick Collection'],
    ...userColls().map(c => ['coll:' + c.id, (c.smart ? '⚙ ' : '') + c.name]),
    ...folderTree().map(([p]) => ['folder:' + p, '▸ ' + p])];
  const sel = $('#fSource');
  const sig = JSON.stringify(opts);
  if (sel._sig !== sig) { sel.innerHTML = opts.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join(''); sel._sig = sig; }
  sel.value = srcKey(S.source);
  const total = sourcePhotos().length;
  $('#fCount').textContent = S.photos.length ? `Showing ${S.view.length} of ${total}` : '';
  const active = S.filter.flag !== 'any' || S.filter.rating || S.filter.label !== 'any' || S.filter.text || (S.filter.crop && S.filter.crop !== 'any') || (S.filter.cstyle && S.filter.cstyle !== 'any');
  $('#fReset').classList.toggle('primary', !!active);
}
function renderView() {
  const has = S.photos.length > 0, m = S.mode;
  if (S.module !== 'library') {
    ['#gridScroll', '#loupe', '#compare', '#survey', '#filterbar'].forEach(x => $(x).hidden = true);
    $('#app').classList.remove('multi');
    const showEmpty = !has && !NO_PHOTOS_NEEDED.has(S.module);
    $('#empty').hidden = !showEmpty; $('#modView').hidden = showEmpty;
    if (showEmpty) return renderEmpty();
    const mod = Mods.get(S.module); return mod && mod.center();
  }
  $('#modView').hidden = true;
  $('#empty').hidden = has;
  $('#gridScroll').hidden = !has || m !== 'grid';
  $('#loupe').hidden = !has || m !== 'loupe';
  $('#compare').hidden = !has || m !== 'compare';
  $('#survey').hidden = !has || m !== 'survey';
  $('#filterbar').hidden = !S.panels.filterbar || m !== 'grid' || !has;
  $('#app').classList.toggle('multi', has && S.selected.size > 1 && (m === 'survey' || m === 'compare' || m === 'loupe'));
  if (!has) return renderEmpty();
  if (m === 'grid') renderGrid();
  else if (m === 'loupe') renderLoupe();
  else if (m === 'compare') renderCompare();
  else renderSurvey();
}
function renderEmpty() {
  const e = $('#empty');
  if (S.loadingMsg) { e.innerHTML = `<div class="empty-card"><div class="logo-big">Keeper<b>.</b> <span class="logo-sub">Studio</span></div><p class="muted">${esc(S.loadingMsg)}</p></div>`; return; }
  const recent = (S.recent || []).slice(0, 6);
  e.innerHTML = `<div class="empty-card"><div class="logo-big">Keeper<b>.</b> <span class="logo-sub">Studio</span></div>
    <p class="muted">Cull the shoot, crop every print size, build composites and extract subjects from the background — all in one place.</p>
    <button class="btn primary lg" data-act="open">Open Folder…</button>
    ${recent.length ? `<div class="recent"><h4>Recent<button class="rc-clear" data-recentclear title="Clear the whole list (the folders aren't touched)">Clear all</button></h4>${recent.map(p => `<div class="rc-row"><button data-recent="${esc(p)}"><span>${esc(baseName(p))}</span><small>${esc(p)}</small></button><button class="rc-x" data-recentx="${esc(p)}" title="Remove from Recent (the folder isn't touched)">✕</button></div>`).join('')}</div>` : ''}
    <p class="muted small">or drag a folder onto this window · photos never leave this computer</p></div>`;
}
/* ---------- Grid (virtualized) ---------- */
const cellEls = new Map();
function clearGrid() { cellEls.forEach(el => el.remove()); cellEls.clear(); }
function gridMetrics() {
  const sc = $('#gridScroll'); const pad = 8;
  const W = Math.max(100, sc.clientWidth - pad * 2);
  const cols = Math.max(1, Math.floor(W / S.thumbSize));
  const cw = W / cols; const ch = Math.round(cw * 1.08);
  return { cols, cw, ch, pad };
}
function cropDot(p) { const c = Crop.status.get(p.path); if (!c) return ''; const cls = (STATUS_INFO[c.status] || {}).cls; return cls && cls !== 'none' ? `<span class="crop-dot ${cls}" title="${esc((STATUS_INFO[c.status] || {}).label || '')}${c.status === 'review' ? ': ' + esc(c.label || '') : ''}"></span>` : ''; }
function cellSig(p, i) {
  const m = getMeta(p.key);
  return `${i}|${p.thumbState}|${m.flag}|${m.team ? 1 : 0}|${m.rating}|${m.label}|${S.selected.has(p.id) ? 1 : 0}|${S.active === p.id ? 1 : 0}|${inQuick(p) ? 1 : 0}|${cropDot(p)}|${Crop.styleOf(p.path) || ''}|${EDIT_VER.get(p.path) || ''}${Ret.isDonor(p.path) ? 'D' : ''}`;
}
function updateCell(el, p, i) {
  const sig = cellSig(p, i); if (el._sig === sig) return; el._sig = sig;
  const m = getMeta(p.key);
  el.className = 'cell' + (S.selected.has(p.id) ? ' sel' : '') + (S.active === p.id ? ' active' : '') + (m.flag === -1 ? ' rejected' : '') + (m.label ? ` has-lbl lbl-${m.label}` : '');
  el.title = p.name;
  el.innerHTML = `<div class="cell-in"><span class="num">${i + 1}</span>${cropDot(p)}${styleTag(p)}${retouchTag(p)}<button class="qc ${inQuick(p) ? 'on' : ''}" data-act="qc" title="Quick Collection (B)"></button>
    <div class="cell-img">${p.thumbUrl ? `<img src="${p.thumbUrl}" alt="" draggable="false">` : '<div class="ph"></div>'}</div>
    <div class="cell-foot">${flagHTML(m.flag, true)}${teamBadge(m)}${starsHTML(m.rating, true)}<span class="ext">${esc(ext(p.name))}</span></div></div>`;
}
function renderGrid() {
  if (S.mode !== 'grid' || !S.photos.length) return;
  const sc = $('#gridScroll'), inner = $('#gridInner');
  if (!sc.clientWidth) return;
  const { cols, cw, ch, pad } = gridMetrics(); S.cols = cols;
  const rows = Math.ceil(S.view.length / cols);
  inner.style.height = (rows * ch + pad * 2) + 'px';
  const top = sc.scrollTop, H = sc.clientHeight;
  const r0 = Math.max(0, Math.floor((top - pad) / ch) - 2), r1 = Math.min(rows, Math.ceil((top + H) / ch) + 2);
  const want = new Set(); const urgent = [];
  for (let i = r0 * cols; i < Math.min(S.view.length, r1 * cols); i++) {
    const p = S.view[i]; want.add(p.id);
    let el = cellEls.get(p.id);
    if (!el) { el = document.createElement('div'); el.dataset.id = p.id; el.draggable = true; inner.appendChild(el); cellEls.set(p.id, el); }
    const x = pad + (i % cols) * cw, y = pad + Math.floor(i / cols) * ch;
    const css = `transform:translate(${x}px,${y}px);width:${cw}px;height:${ch}px`;
    if (el._css !== css) { el.style.cssText = css; el._css = css; }
    updateCell(el, p, i);
    if (p.thumbState < 2) urgent.push(p);
  }
  for (const [id, el] of cellEls) if (!want.has(id)) { el.remove(); cellEls.delete(id); }
  for (let i = urgent.length - 1; i >= 0; i--) Thumbs.request(urgent[i], true);
  if (!S.view.length) inner.innerHTML = `<div class="msg filter-empty"><div><b>No photos match the current filter</b><br><span class="muted">${esc(filterSummary())}</span><br><button class="btn primary" data-clear-filter>Show all ${sourcePhotos().length} photos</button></div></div>`;
  else { const msg = inner.querySelector(':scope > .msg'); if (msg) msg.remove(); }
}

/* ---------- Filmstrip (virtualized) ---------- */
const filmEls = new Map();
function clearFilm() { filmEls.forEach(el => el.remove()); filmEls.clear(); }
function renderFilm() {
  if (!S.panels.film) return;
  const sc = $('#filmScroll'), inner = $('#filmInner'); const n = S.view.length;
  inner.style.width = (n * FW) + 'px';
  const L = sc.scrollLeft, W = sc.clientWidth || 800;
  const i0 = Math.max(0, Math.floor(L / FW) - 3), i1 = Math.min(n, Math.ceil((L + W) / FW) + 3);
  const want = new Set();
  for (let i = i0; i < i1; i++) {
    const p = S.view[i]; want.add(p.id);
    let el = filmEls.get(p.id);
    if (!el) { el = document.createElement('div'); el.dataset.id = p.id; el.draggable = true; inner.appendChild(el); filmEls.set(p.id, el); }
    const css = `left:${i * FW}px;width:${FW}px`;
    if (el._css !== css) { el.style.cssText = css; el._css = css; }
    const m = getMeta(p.key); const sig = cellSig(p, i);
    if (el._sig !== sig) {
      el._sig = sig;
      el.className = 'fcell' + (S.selected.has(p.id) ? ' sel' : '') + (S.active === p.id ? ' active' : '') + (m.flag === -1 ? ' rejected' : '') + (m.label ? ` has-lbl lbl-${m.label}` : '');
      el.title = `${i + 1}. ${p.name}`;
      el.innerHTML = `<div class="fcell-in">${p.thumbUrl ? `<img src="${p.thumbUrl}" alt="" draggable="false">` : '<div class="ph"></div>'}
        ${cropDot(p)}${styleTag(p)}${retouchTag(p)}<div class="fbadges">${m.flag ? flagHTML(m.flag, false) : ''}${teamBadge(m)}${m.rating ? starsHTML(m.rating, false) : ''}${inQuick(p) ? '<span class="qcdot"></span>' : ''}</div></div>`;
    }
    if (p.thumbState < 2) Thumbs.request(p, true);
  }
  for (const [id, el] of filmEls) if (!want.has(id)) { el.remove(); filmEls.delete(id); }
}
function renderFilmBar() {
  if (!S.panels.film) return;
  const p = S.byId.get(S.active);
  $('#filmBar').innerHTML = S.photos.length
    ? `<b>${esc(sourceName())}</b><span class="sep">/</span>${S.module === 'crop' && S.cropShow !== 'all' ? `<span class="film-show">${CROP_SHOW_NAMES[S.cropShow]} · ${S.view.length} of ${S.photos.length}</span>` : `<span>${plural(S.view.length, 'photo')}</span>`}<span class="sep">/</span><span>${S.selected.size} selected</span>${p ? `<span class="sep">/</span><span>${esc(p.name)}</span>` : ''}`
    : '<span>No photos loaded</span>';
}

/* ---------- Zoom panes (Loupe & Compare) ---------- */
function makePane(parent) {
  const el = document.createElement('div'); el.className = 'zv';
  const img = document.createElement('img'); img.draggable = false; img.alt = '';
  el.appendChild(img); parent.appendChild(el); el._img = img;
  img.addEventListener('load', () => layoutPane(el));
  bindZoom(el); return el;
}
function setPaneImage(el, p) {
  if (el._pid !== p.id) {
    el._pid = p.id; el._full = false; el._orig = null; el._origLoading = null;
    if (p.thumbUrl) el._img.src = p.thumbUrl; else el._img.removeAttribute('src');
    el._loading = null;
    if (el._lazy && S.zoom.mode === 'fit' && Math.max(el.clientWidth, el.clientHeight) < THUMB_MAX * 1.1) return;
    el._loading = p.id;
    fullUrlAsync(p).then(url => {
      if (el._pid !== p.id) return;
      const im = new Image();
      im.onload = () => { if (el._pid === p.id) { el._full = true; el._img.src = url; } };
      im.src = url;
    }).catch(e => toast('Couldn’t open this HEIC photo: ' + esc(e.message || e)));
  } else if (!el._full && p.thumbUrl && el._img.getAttribute('src') !== p.thumbUrl) el._img.src = p.thumbUrl;
}
function layoutPane(el) {
  const p = S.byId.get(el._pid); if (!p) return;
  const img = el._img; const nw = p.w || img.naturalWidth, nh = p.h || img.naturalHeight;
  const cw = el.clientWidth, ch = el.clientHeight; if (!nw || !nh || !cw || !ch) return;
  const fit = Math.min(cw / nw, ch / nh);
  const z = S.zoom; const dpr = window.devicePixelRatio || 1;
  const s = z.mode === 'fit' ? fit : z.mode === '1:1' ? 1 / dpr : clamp(fit * z.factor, fit, Math.max(fit, MAX_ZOOM / dpr));
  el._fit = fit; el._s = s;
  const dw = nw * s, dh = nh * s;
  const left = dw <= cw ? (cw - dw) / 2 : clamp(cw / 2 - z.cx * dw, cw - dw, 0);
  const top = dh <= ch ? (ch - dh) / 2 : clamp(ch / 2 - z.cy * dh, ch - dh, 0);
  img.style.width = dw + 'px'; img.style.height = dh + 'px'; img.style.transform = `translate(${left}px,${top}px)`;
  el.classList.toggle('zoomed', dw > cw + 1 || dh > ch + 1);
  el._geom = { left, top, dw, dh, cw, ch };
  const badge = el.parentElement && el.parentElement.querySelector(':scope > .zoom-badge');
  if (badge) badge.textContent = zoomLabel(el);
  if (z.mode !== 'fit' && (el._lazy || s * Math.max(nw, nh) > PREVIEW_PX * 0.95)) loadFull(el, p);
}
const MAX_ZOOM = 4; // 400 % of the photo's real pixels
function zoomLabel(el) { return S.zoom.mode === 'fit' || !el ? 'Fit' : Math.round(el._s * (window.devicePixelRatio || 1) * 100) + '%'; }
function layoutAllPanes() { $$('.zv').forEach(layoutPane); syncZoomUI(); }
function refPane() { return $$('.zv').find(el => el.clientWidth && el._fit && (S.mode !== 'survey' || el._pid === S.active)) || $$('.zv').find(el => el.clientWidth && el._fit); }
// Zoom by a multiplier, keeping the given pane point (0–1) under the given screen point, or the centre
function zoomBy(mult, el, ev) {
  if (S.mode !== 'loupe' && S.mode !== 'compare' && S.mode !== 'survey') return;
  el = el || refPane(); if (!el) return;
  const fit = el._fit, cur = el._s || fit;
  let next = cur * mult; const max = Math.max(fit, MAX_ZOOM / (window.devicePixelRatio || 1));
  next = clamp(next, fit, max);
  const g = el._geom; let cx = S.zoom.cx, cy = S.zoom.cy;
  if (g && ev) {
    const r = el.getBoundingClientRect(); const mx = ev.clientX - r.left, my = ev.clientY - r.top;
    const px = clamp((mx - g.left) / g.dw, 0, 1), py = clamp((my - g.top) / g.dh, 0, 1);
    const p = S.byId.get(el._pid); const nw = g.dw / cur, nh = g.dh / cur;
    cx = (g.cw / 2 - (mx - px * nw * next)) / (nw * next); cy = (g.ch / 2 - (my - py * nh * next)) / (nh * next);
  } else if (g && S.zoom.mode === 'fit') { cx = .5; cy = .5; }
  S.zoom = next <= fit * 1.001 ? { mode: 'fit', cx: .5, cy: .5 } : { mode: 'x', factor: next / fit, cx, cy };
  layoutAllPanes();
}
function setZoom(mode) { S.zoom = mode === 'fit' ? { mode: 'fit', cx: .5, cy: .5 } : { mode, factor: 1, cx: S.zoom.cx ?? .5, cy: S.zoom.cy ?? .5 }; layoutAllPanes(); }
function syncZoomUI() {
  const show = S.photos.length && (S.mode === 'loupe' || S.mode === 'compare' || S.mode === 'survey');
  const g = $('#tbZoom'); if (!g) return; g.hidden = !show;
  if (show) $('#tbZoomVal').textContent = zoomLabel(refPane());
}
function loadFull(el, p) {
  if (el._orig === p.id || el._origLoading === p.id) return;
  el._origLoading = p.id;
  const url = fullUrlFor(p.path);
  const im = new Image(); im.onload = () => { if (el._pid === p.id) { el._orig = p.id; el._full = true; el._img.src = url; } }; im.src = url;
}
function bindZoom(el) {
  let down = null;
  el.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    down = { x: e.clientX, y: e.clientY, moved: false, cx: S.zoom.cx, cy: S.zoom.cy };
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener('pointermove', e => {
    if (!down) return;
    const dx = e.clientX - down.x, dy = e.clientY - down.y;
    if (!down.moved && Math.hypot(dx, dy) < 4) return;
    down.moved = true;
    if (S.zoom.mode === 'fit' || !el._geom) return;
    S.zoom.cx = down.cx - dx / el._geom.dw; S.zoom.cy = down.cy - dy / el._geom.dh;
    el.classList.add('grabbing'); layoutAllPanes();
  });
  const up = e => {
    if (!down) return; const d = down; down = null; el.classList.remove('grabbing');
    const g = el._geom;
    if (d.moved) { // normalise centre so panning never drifts past the edge
      if (g) { if (g.dw > g.cw) S.zoom.cx = (g.cw / 2 - g.left) / g.dw; if (g.dh > g.ch) S.zoom.cy = (g.ch / 2 - g.top) / g.dh; }
      return;
    }
    if (e.type === 'pointercancel') return;
    if (el._isActive && !el._isActive()) { el._onActivate(); return; }
    if (S.zoom.mode === 'fit') {
      let cx = .5, cy = .5;
      if (g) { const r = el.getBoundingClientRect(); cx = clamp((e.clientX - r.left - g.left) / g.dw, 0, 1); cy = clamp((e.clientY - r.top - g.top) / g.dh, 0, 1); }
      S.zoom = { mode: '1:1', factor: 1, cx, cy };
    } else S.zoom = { mode: 'fit', cx: .5, cy: .5 };
    layoutAllPanes();
  };
  el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
  el.addEventListener('wheel', e => {
    e.preventDefault();
    const d = e.deltaMode === 1 ? e.deltaY * 30 : e.deltaY;
    zoomBy(Math.exp(-d * (e.ctrlKey ? 0.01 : 0.0025)), el, e);
  }, { passive: false });
}
function qcPill(parent, getId) {
  const b = document.createElement('button'); b.className = 'qc-pill off'; b.title = 'Quick Collection (B)';
  b.addEventListener('pointerdown', e => e.stopPropagation());
  b.addEventListener('click', e => { e.stopPropagation(); const p = S.byId.get(getId()); if (p) toggleQuickFor([p]); });
  parent.appendChild(b); return b;
}
function syncQc(pill, img, p) {
  const on = !!p && inQuick(p);
  pill.classList.toggle('off', !on); pill.textContent = on ? 'Quick Collection' : 'Add to Quick';
  pill.hidden = !p; if (img) img.classList.toggle('qc-ring', on);
}
function buildLoupe() {
  const box = $('#loupe');
  box.innerHTML = '<div class="msg" hidden>No photo selected</div>';
  box._pane = makePane(box);
  box._info = document.createElement('div'); box._info.className = 'loupe-info'; box.appendChild(box._info);
  const b = document.createElement('div'); b.className = 'zoom-badge'; box.appendChild(b);
  box._qc = qcPill(box, () => S.active);
}
function renderLoupe() {
  const box = $('#loupe'); const p = S.byId.get(S.active);
  box.querySelector('.msg').hidden = !!p; box._pane.hidden = !p; box._info.hidden = !p;
  syncQc(box._qc, box._pane._img, p);
  if (!p) return;
  setPaneImage(box._pane, p); layoutPane(box._pane);
  const m = getMeta(p.key); const i = S.viewIndex.get(p.id);
  box._info.innerHTML = `<b>${esc(p.name)}</b><br>${i != null ? `${i + 1} of ${S.view.length}` : ''}${p.hasCapture ? ' · ' + esc(new Date(p.capture).toLocaleString()) : ''}<br>
    ${m.flag ? (m.flag === 1 ? 'Picked' : 'Rejected') : 'Unflagged'}${m.team ? ' · Team photo' : ''}${m.rating ? ' · ' + '★'.repeat(m.rating) : ''}${m.label ? ` · <span style="color:var(--l-${m.label})">■</span> ${LABEL_NAMES[m.label]}` : ''}${inQuick(p) ? ' · Quick Collection' : ''}`;
  if (i != null) { preload(S.view[i + 1]); preload(S.view[i - 1]); }
}
function buildCompare() {
  const box = $('#compare');
  box.innerHTML = ['select', 'cand'].map(s => `<div class="cmp-pane" data-side="${s}"><div class="cmp-stage"><div class="zoom-badge"></div></div><div class="cmp-foot"></div></div>`).join('');
  $$('.cmp-pane', box).forEach(pn => {
    const side = pn.dataset.side;
    const pane = makePane(pn.querySelector('.cmp-stage')); pn._pane = pane;
    pn._qc = qcPill(pn.querySelector('.cmp-stage'), () => side === 'select' ? S.compare.select : S.compare.cand);
    pane._isActive = () => S.compare.side === side;
    pane._onActivate = () => activateSide(side);
    pn.querySelector('.cmp-foot').addEventListener('click', e => {
      const a = e.target.closest('[data-act]'); const id = side === 'select' ? S.compare.select : S.compare.cand;
      if (a && id != null) { activateSide(side, true); cellAction(id, a.dataset.act, +a.dataset.v); return; }
      activateSide(side);
    });
  });
}
function activateSide(side, quiet) {
  S.compare.side = side; S.active = side === 'select' ? S.compare.select : S.compare.cand;
  if (S.active == null) { S.compare.side = 'select'; S.active = S.compare.select; }
  if (!quiet) renderAll();
}
function renderCompare() {
  const c = S.compare;
  $$('#compare .cmp-pane').forEach(pn => {
    const side = pn.dataset.side; const id = side === 'select' ? c.select : c.cand; const p = S.byId.get(id);
    pn.classList.toggle('on', c.side === side);
    pn._pane.hidden = !p; syncQc(pn._qc, pn._pane._img, p);
    if (p) { setPaneImage(pn._pane, p); layoutPane(pn._pane); }
    const m = p ? getMeta(p.key) : null;
    pn.querySelector('.cmp-foot').innerHTML = `<span class="cmp-tag">${side === 'select' ? 'Select' : 'Candidate'}</span>` +
      (p ? `<span class="nm">${esc(p.name)}</span>${flagHTML(m.flag, true)}${teamBadge(m)}${starsHTML(m.rating, true)}${m.label ? `<span style="color:var(--l-${m.label})">■</span>` : ''}` : '<span class="muted">Use ← → or click the filmstrip to pick a candidate</span>');
  });
  const i = S.viewIndex.get(c.cand); if (i != null) { preload(S.view[i + 1]); preload(S.view[i - 1]); }
}

/* ---------- Survey ---------- */
const svEls = new Map();
function renderSurvey() {
  const box = $('#survey'); const ids = S.surveyIds.filter(id => S.viewIndex.has(id)); S.surveyIds = ids;
  const n = ids.length;
  let msg = box.querySelector(':scope > .msg');
  if (!n) {
    svEls.forEach(el => el.remove()); svEls.clear();
    if (!msg) { msg = document.createElement('div'); msg.className = 'msg'; box.appendChild(msg); }
    msg.textContent = 'Select two or more photos (Ctrl/Cmd-click or Shift-click in the filmstrip) to survey them.';
    return;
  }
  if (msg) msg.remove();
  const W = box.clientWidth - 12, H = box.clientHeight - 12;
  let best = { cols: 1, rows: n, tw: W, th: H / n, size: 0 };
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols); const tw = W / cols, th = H / rows;
    const size = Math.min(tw - 20, (th - 40) * 1.5);
    if (size > best.size) best = { cols, rows, tw, th, size };
  }
  const want = new Set(ids);
  for (const [id, el] of svEls) if (!want.has(id)) { el.remove(); svEls.delete(id); }
  ids.forEach((id, k) => {
    const p = S.byId.get(id); const m = getMeta(p.key);
    let el = svEls.get(id);
    if (!el) {
      el = document.createElement('div'); el.dataset.id = id;
      el.innerHTML = `<div class="sv-in"><div class="sv-img"></div><div class="sv-foot"></div>
        <button class="qc-pill off" data-act="qc" title="Quick Collection (B)"></button>
        <button class="sv-x" data-act="remove" title="Remove from survey">✕</button></div>`;
      const pane = makePane(el.querySelector('.sv-img')); pane._lazy = true;
      pane._isActive = () => S.active === id;
      pane._onActivate = () => { S.active = id; renderAll(); };
      el._pane = pane; box.appendChild(el); svEls.set(id, el);
    }
    const x = 6 + (k % best.cols) * best.tw, y = 6 + Math.floor(k / best.cols) * best.th;
    el.style.cssText = `left:${x}px;top:${y}px;width:${best.tw}px;height:${best.th}px`;
    el.className = `sv ${S.active === id ? 'active' : ''} ${m.flag === -1 ? 'rejected' : ''} ${m.label ? `has-lbl lbl-${m.label}` : ''}`;
    el.title = p.name;
    const foot = `${flagHTML(m.flag, true)}${starsHTML(m.rating, true)}`;
    const ft = el.querySelector('.sv-foot'); if (ft._html !== foot) { ft.innerHTML = foot; ft._html = foot; }
    const pill = el.querySelector('.qc-pill'); const q = inQuick(p);
    pill.classList.toggle('off', !q); pill.textContent = q ? 'Quick Collection' : 'Add to Quick';
    el._pane._img.classList.toggle('qc-ring', q);
    setPaneImage(el._pane, p); layoutPane(el._pane);
  });
  syncZoomUI();
}

/* ---------- Fullscreen preview ---------- */
function renderFs(force) {
  if (!S.fs) return; const p = S.byId.get(S.active); if (!p) return;
  const box = $('#fs'), img = $('#fs img');
  if (box._pid !== p.id || force) {
    box._pid = p.id;
    if (p.thumbUrl) img.src = p.thumbUrl;
    fullUrlAsync(p).then(u => { const im = new Image(); im.onload = () => { if (S.active === p.id && S.fs) img.src = u; }; im.src = u; }).catch(() => {});
    const i = S.viewIndex.get(p.id); if (i != null) { preload(S.view[i + 1]); }
  }
  syncQc($('#fsQc'), img, p);
  const m = getMeta(p.key);
  $('#fsInfo').innerHTML = `<span>${esc(p.name)}</span>${m.flag ? flagHTML(m.flag, false) : ''}${m.rating ? starsHTML(m.rating, false) : ''}<span>· F or Esc to exit</span>`;
}

/* ---------- Right panel ---------- */
function fmtExif(p) {
  const e = p.exif || {};
  let camera = [e.Make, e.Model].filter(Boolean).join(' ');
  if (e.Make && e.Model && String(e.Model).toLowerCase().startsWith(String(e.Make).toLowerCase())) camera = e.Model;
  const t = e.ExposureTime;
  return {
    camera: camera || '—', lens: e.LensModel || '—',
    focal: e.FocalLength ? Math.round(e.FocalLength) + ' mm' : '—',
    shutter: t ? (t >= 1 ? `${+t.toFixed(1)} s` : `1/${Math.round(1 / t)} s`) : '—',
    aperture: e.FNumber ? 'f/' + (+e.FNumber).toFixed(1).replace(/\.0$/, '') : '—',
    iso: e.ISO ? 'ISO ' + e.ISO : '—',
  };
}
function fmtSize(b) { return b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.round(b / 1024) + ' KB'; }
function renderRight() {
  if (!S.panels.right) return;
  if (S.module !== 'library') { const m = Mods.get(S.module); return m && keepScroll('#right', () => m.right()); }
  const p = S.byId.get(S.active); const R = $('#right');
  if (!p) {
    R.innerHTML = `<div class="scroll">${sectionHTML('hist', 'Histogram', '<div class="hist-wrap"><canvas id="hist" width="512" height="200"></canvas></div>')}<div class="hint">${S.photos.length ? 'Select a photo to see its details.' : 'Open a folder to get started.'}</div></div>`;
    drawHist($('#hist'), null); return;
  }
  if (!p.exif && window.exifr) readExif(p).then(() => { if (S.active === p.id) renderRight(); });
  const x = fmtExif(p); const m = getMeta(p.key); const multi = S.mode === 'grid' && S.selected.size > 1;
  const colls = collections.filter(c => inColl(c, p));
  const capture = p.hasCapture ? new Date(p.capture).toLocaleString() : (p.exif ? new Date(p.capture).toLocaleString() + ' (file date)' : '…');
  const lblBtns = LABELS.map(l => `<button class="swatch lbl-${l} ${m.label === l ? 'on' : ''}" data-mark="label:${l}" title="${LABEL_NAMES[l]} (${LABELS.indexOf(l) + 6})"></button>`).join('');
  let html = sectionHTML('hist', 'Histogram', `<div class="hist-wrap"><canvas id="hist" width="512" height="200"></canvas>
    <div class="hist-meta"><span>${x.iso}</span><span>${x.focal}</span><span>${x.aperture}</span><span>${x.shutter}</span></div></div>`);
  html += multi ? `<div class="sel-note">${S.selected.size} photos selected — changes below apply to all of them. Showing <b>${esc(p.name)}</b>.</div>` : '';
  html += sectionHTML('status', 'Quick Develop · Status', `<div class="status">
    <div class="st-row"><span class="k">Flag</span>
      <button class="icon-btn ${m.flag === 1 ? 'on' : ''}" data-mark="flag:1" title="Pick (P)">${SVG_PICK}</button>
      <button class="icon-btn ${m.flag === 0 ? 'on' : ''}" data-mark="flag:0" title="Unflag (U)">${SVG_OPEN}</button>
      <button class="icon-btn ${m.flag === -1 ? 'on' : ''}" data-mark="flag:-1" title="Reject (X)" style="${m.flag === -1 ? 'color:var(--reject);border-color:var(--reject);background:rgba(210,87,79,.12)' : ''}">${SVG_REJ}</button></div>
    <div class="st-row"><span class="k">Rating</span><span class="big-stars">${[1, 2, 3, 4, 5].map(i => `<i class="${i <= m.rating ? 'on' : ''}" data-mark="rating:${i}" title="${i} star${i > 1 ? 's' : ''} (${i})">★</i>`).join('')}</span>
      ${m.rating ? '<button class="btn sm" data-mark="rating:0">Clear</button>' : ''}</div>
    <div class="st-row"><span class="k">Label</span>${lblBtns}</div>
    <div class="st-row"><span class="k">Quick</span><button class="toggle ${inQuick(p) ? 'on' : ''}" data-quick>${inQuick(p) ? '● In Quick Collection' : '○ Add to Quick Collection'}</button></div>
  </div>`);
  html += sectionHTML('info', 'Metadata', `<div class="info-tbl">
    <span class="k">File</span><span class="v" title="${esc(p.rel)}">${esc(p.name)}</span>
    <span class="k">Folder</span><span class="v" title="${esc(p.folder)}">${esc(p.folder)}</span>
    <span class="k">Captured</span><span class="v">${esc(capture)}</span>
    <span class="k">Dimensions</span><span class="v">${p.w ? `${p.w} × ${p.h}` : '—'}</span>
    <span class="k">Size</span><span class="v">${fmtSize(p.size)}</span>
    <span class="k">Camera</span><span class="v" title="${esc(x.camera)}">${esc(x.camera)}</span>
    <span class="k">Lens</span><span class="v" title="${esc(x.lens)}">${esc(x.lens)}</span>
    <span class="k">Focal length</span><span class="v">${x.focal}</span>
    <span class="k">Shutter</span><span class="v">${x.shutter}</span>
    <span class="k">Aperture</span><span class="v">${x.aperture}</span>
    <span class="k">ISO</span><span class="v">${x.iso}</span></div>`);
  html += sectionHTML('pcolls', 'Collections', `<div class="chips">${colls.length ? colls.map(c => `<button class="chip" data-src="coll:${esc(c.id)}">${c.smart ? '⚙' : c.id === QUICK ? '●' : '▤'} ${esc(c.name)}</button>`).join('') : '<span class="muted small">Not in any collection. Drag it onto one in the left panel, or press B for the Quick Collection.</span>'}</div>`);
  R.innerHTML = `<div class="scroll">${html}</div>`;
  const cv = $('#hist'); drawHist(cv, p.hist);
  if (!p.hist && p.thumbUrl) getHist(p).then(h => { if (S.active === p.id && $('#hist')) drawHist($('#hist'), h); }).catch(() => {});
}
async function getHist(p) {
  if (p.hist) return p.hist;
  const img = new Image(); img.src = p.thumbUrl; await img.decode();
  const w = Math.min(220, img.naturalWidth), h = Math.max(1, Math.round(img.naturalHeight * w / img.naturalWidth));
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const x = c.getContext('2d', { willReadFrequently: true }); x.drawImage(img, 0, 0, w, h);
  const d = x.getImageData(0, 0, w, h).data;
  const r = new Uint32Array(256), g = new Uint32Array(256), b = new Uint32Array(256);
  for (let i = 0; i < d.length; i += 4) { r[d[i]]++; g[d[i + 1]]++; b[d[i + 2]]++; }
  return (p.hist = { r, g, b });
}
function drawHist(cv, hist) {
  if (!cv) return; const ctx = cv.getContext('2d'); const W = cv.width, H = cv.height;
  ctx.globalCompositeOperation = 'source-over';
  ctx.fillStyle = '#0B0C0F'; ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = '#1C2026'; ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) { ctx.beginPath(); ctx.moveTo(i * W / 4 + .5, 0); ctx.lineTo(i * W / 4 + .5, H); ctx.stroke(); }
  if (!hist) return;
  let max = 1; for (const a of [hist.r, hist.g, hist.b]) for (let i = 2; i < 254; i++) if (a[i] > max) max = a[i];
  ctx.globalCompositeOperation = 'lighter';
  [[hist.r, 'rgba(225,72,72,.7)'], [hist.g, 'rgba(70,195,95,.7)'], [hist.b, 'rgba(46,120,255,.8)']].forEach(([a, col]) => {
    ctx.fillStyle = col; ctx.beginPath(); ctx.moveTo(0, H);
    for (let i = 0; i < 256; i++) ctx.lineTo(i / 255 * W, H - Math.sqrt(Math.min(1, a[i] / max)) * H * .94);
    ctx.lineTo(W, H); ctx.closePath(); ctx.fill();
  });
  ctx.globalCompositeOperation = 'source-over';
}

/* ---------- Filter bar & toolbar (built once, synced) ---------- */
function buildFilterBar() {
  const fb = $('#filterbar');
  fb.innerHTML = `<span class="fb-title">Library Filter</span>
    <label>Flag <select id="fFlag"><option value="any">Any</option><option value="pick">Picked</option><option value="unflagged">Unflagged</option><option value="rejected">Rejected</option><option value="notrejected">Picked + Unflagged</option></select></label>
    <label>Rating <select id="fRating"><option value="0">Any</option>${[1, 2, 3, 4, 5].map(i => `<option value="${i}">≥ ${'★'.repeat(i)}</option>`).join('')}</select></label>
    <label>Label <select id="fLabel"><option value="any">Any</option><option value="none">No label</option>${LABELS.map(l => `<option value="${l}">${LABEL_NAMES[l]}</option>`).join('')}</select></label>
    <label>Source <select id="fSource"></select></label>
    <label>Crop <select id="fCrop"><option value="any">Any</option><option value="ready">Ready to print</option><option value="ok">Framed as planned</option><option value="shortened">Shortened</option><option value="manual">Placed by hand</option><option value="review">Needs review</option><option value="unchecked">Not checked</option></select></label>
    <input id="fText" type="search" placeholder="Search filename…" autocomplete="off">
    <button id="fReset" class="btn sm">Reset</button>
    <span id="fCount" class="fb-count"></span>`;
  fb._built = true;
  const onF = () => { S.filter = { flag: $('#fFlag').value, rating: +$('#fRating').value, label: $('#fLabel').value, text: $('#fText').value.trim(), crop: $('#fCrop').value }; afterFilter(); };
  ['#fFlag', '#fRating', '#fLabel', '#fCrop'].forEach(s => $(s).addEventListener('change', e => { onF(); e.target.blur(); }));
  $('#fText').addEventListener('input', onF);
  $('#fSource').addEventListener('change', e => { setSource(e.target.value); e.target.blur(); });
  $('#fReset').addEventListener('click', () => { S.filter = { flag: 'any', rating: 0, label: 'any', text: '', crop: 'any' }; $('#fText').value = ''; afterFilter(); });
}
function filterSummary() {
  const f = S.filter, parts = [];
  if (f.flag !== 'any') parts.push('Flag: ' + $('#fFlag').selectedOptions[0].text);
  if (f.rating) parts.push('Rating ≥ ' + f.rating + '★');
  if (f.label !== 'any') parts.push('Label: ' + f.label);
  if (f.crop && f.crop !== 'any') parts.push('Crop: ' + (STATUS_INFO[f.crop] || {}).label);
  if (f.cstyle && f.cstyle !== 'any') parts.push('Style: ' + (f.cstyle === 'batch' ? 'same as shoot' : Crop.STYLE_NAMES[f.cstyle]));
  if (f.text) parts.push('Name contains “' + f.text + '”');
  return parts.length ? 'Filtered by ' + parts.join(' · ') : 'This source is empty';
}
function afterFilter() {
  recomputeView();
  if (S.active == null && S.view.length && (S.mode !== 'grid' || S.module !== 'library')) { S.active = S.view[0].id; S.selected = new Set([S.active]); S.anchor = S.active; }
  $('#gridScroll').scrollTop = 0; renderAll(); ensureVisible();
}
function setSource(k) {
  S.source = parseSrc(k); recomputeView();
  if (S.active == null && S.view.length && S.mode !== 'grid') { S.active = S.view[0].id; S.selected = new Set([S.active]); }
  if (S.mode === 'compare') enterCompare();
  if (S.mode === 'survey' && !S.surveyIds.length && S.active != null) S.surveyIds = [S.active];
  $('#gridScroll').scrollTop = 0; $('#filmScroll').scrollLeft = 0;
  renderAll(); ensureVisible();
}
function buildToolbar() {
  const tb = $('#toolbar');
  tb.innerHTML = `<div class="tb-group" id="tbModes">
      <button class="icon-btn" data-mode="grid" title="Grid (G)">${ICONS.grid}</button>
      <button class="icon-btn" data-mode="loupe" title="Loupe (E)">${ICONS.loupe}</button>
      <button class="icon-btn" data-mode="compare" title="Compare (C)">${ICONS.compare}</button>
      <button class="icon-btn" data-mode="survey" title="Survey (N)">${ICONS.survey}</button></div>
    <div class="tb-sep"></div>
    <span class="tb-lbl">Sort</span>
    <select id="tbSort"><option value="capture">Capture Time</option><option value="name">File Name</option><option value="rating">Rating</option></select>
    <button class="icon-btn" id="tbDir" title="Reverse sort order"></button>
    <div class="tb-sep"></div>
    <div class="tb-group"><button class="icon-btn" id="tbPick" data-mark="flag:1" title="Flag as Pick (P)">${SVG_PICK}</button><button class="icon-btn" id="tbRej" data-mark="flag:-1" title="Flag as Rejected (X)">${SVG_REJ}</button></div>
    <span class="tb-stars" id="tbStars">${[1, 2, 3, 4, 5].map(i => `<i data-mark="rating:${i}" title="${i} (${i})">★</i>`).join('')}</span>
    <div class="tb-group" id="tbLabels">${LABELS.map((l, i) => `<button class="swatch lbl-${l}" data-mark="label:${l}" title="${LABEL_NAMES[l]} (${i + 6})"></button>`).join('')}</div>
    <div class="tb-sep"></div>
    <button class="toggle" id="tbAuto" title="Move to the next photo after each flag, rating, or label (or turn on Caps Lock)">Auto-advance</button>
    <div class="tb-group" id="tbZoom" hidden><div class="tb-sep" style="margin-right:6px"></div>
      <button class="icon-btn" id="tbZoomOut" title="Zoom out (−)">−</button>
      <button class="btn sm" id="tbZoomFit" title="Fit (Z toggles Fit / 1:1)">Fit</button>
      <button class="btn sm" id="tbZoom11" title="Actual pixels (Z)">1:1</button>
      <button class="icon-btn" id="tbZoomIn" title="Zoom in (+)">+</button>
      <span id="tbZoomVal" class="tb-lbl" style="min-width:40px;text-align:right"></span></div>
    <div class="tb-group" id="tbCompare"><div class="tb-sep" style="margin-right:6px"></div><button class="btn sm" id="tbSwap" title="Swap Select and Candidate">⇄ Swap</button><button class="btn sm" id="tbMakeSel" title="Make the Candidate the new Select">Make Select</button></div>
    <div class="tb-spacer"></div>
    <span id="tbInfo"></span>
    <label id="tbThumbWrap" title="Thumbnail size"><span style="font-size:10px">▣</span> <input type="range" id="tbThumb" min="110" max="380" step="5"></label>`;
  tb.addEventListener('click', e => {
    const md = e.target.closest('[data-mode]'); if (md) return setMode(md.dataset.mode);
    const mk = e.target.closest('[data-mark]'); if (mk) { const [f, v] = mk.dataset.mark.split(':'); return mark(f, f === 'label' ? v : +v, false); }
  });
  $('#tbSort').addEventListener('change', e => { S.sort = e.target.value; savePrefs(); e.target.blur(); afterSort(); });
  $('#tbDir').addEventListener('click', () => { S.sortDir = -S.sortDir; savePrefs(); afterSort(); });
  $('#tbAuto').addEventListener('click', () => { S.autoAdvance = !S.autoAdvance; savePrefs(); syncToolbar(); toast(`Auto-advance ${S.autoAdvance ? 'on' : 'off'}`); });
  $('#tbSwap').addEventListener('click', swapCompare);
  $('#tbZoomOut').addEventListener('click', () => zoomBy(1 / 1.25));
  $('#tbZoomIn').addEventListener('click', () => zoomBy(1.25));
  $('#tbZoomFit').addEventListener('click', () => setZoom('fit'));
  $('#tbZoom11').addEventListener('click', () => setZoom('1:1'));
  $('#tbMakeSel').addEventListener('click', makeSelect);
  const th = $('#tbThumb'); th.value = S.thumbSize;
  th.addEventListener('input', () => {
    const sc = $('#gridScroll'); const ratio = sc.scrollHeight ? sc.scrollTop / sc.scrollHeight : 0;
    S.thumbSize = +th.value; renderGrid(); sc.scrollTop = ratio * sc.scrollHeight; renderGrid();
  });
  th.addEventListener('change', () => { savePrefs(); th.blur(); });
}
function afterSort() { recomputeView(); renderAll(); ensureVisible(); }
function syncToolbar() {
  $$('#tbModes [data-mode]').forEach(b => b.classList.toggle('on', b.dataset.mode === S.mode));
  $('#tbSort').value = S.sort;
  $('#tbDir').textContent = S.sortDir > 0 ? '↑' : '↓';
  const p = targets()[0]; const m = p ? getMeta(p.key) : META_DEFAULT;
  $('#tbPick').classList.toggle('on', m.flag === 1);
  $('#tbRej').classList.toggle('on', m.flag === -1);
  $$('#tbStars i').forEach((s, i) => s.classList.toggle('on', i < m.rating));
  $$('#tbLabels .swatch').forEach(s => s.classList.toggle('on', s.dataset.mark === 'label:' + m.label));
  const auto = $('#tbAuto'); auto.classList.toggle('on', autoOn());
  auto.textContent = S.caps && !S.autoAdvance ? 'Auto-advance (Caps Lock)' : 'Auto-advance';
  $('#tbCompare').hidden = S.mode !== 'compare';
  syncZoomUI();
  $('#tbThumbWrap').hidden = S.mode !== 'grid';
  $('#tbInfo').textContent = S.photos.length ? `${S.selected.size} / ${S.view.length} selected` : '';
}

/* ================= Collections dialog ================= */
function rulesHTML(r) {
  return `<div class="rules">
    <label>Flag</label><select id="rFlag">${[['any', 'Any'], ['pick', 'Picked'], ['unflagged', 'Unflagged'], ['rejected', 'Rejected'], ['notrejected', 'Picked + Unflagged']].map(([v, l]) => `<option value="${v}" ${r.flag === v ? 'selected' : ''}>${l}</option>`).join('')}</select>
    <label>Rating</label><select id="rRating"><option value="0">Any</option>${[1, 2, 3, 4, 5].map(i => `<option value="${i}" ${+r.rating === i ? 'selected' : ''}>≥ ${'★'.repeat(i)}</option>`).join('')}</select>
    <label>Label</label><select id="rLabel">${[['any', 'Any'], ['none', 'No label'], ...LABELS.map(l => [l, LABEL_NAMES[l]])].map(([v, l]) => `<option value="${v}" ${r.label === v ? 'selected' : ''}>${l}</option>`).join('')}</select>
    <label>Filename</label><input id="rText" placeholder="contains… (optional)" value="${esc(r.text || '')}"></div>`;
}
const readRules = card => ({ flag: $('#rFlag', card).value, rating: +$('#rRating', card).value, label: $('#rLabel', card).value, text: $('#rText', card).value.trim() });
function openCollDialog(editId) {
  const c = editId ? getColl(editId) : null;
  if (c && c.id === QUICK) return;
  const selN = S.selected.size, filN = S.view.length;
  const r = (c && c.smart) || { flag: S.filter.flag === 'any' ? 'pick' : S.filter.flag, rating: S.filter.rating, label: S.filter.label, text: S.filter.text };
  openModal(`<h3>${c ? (c.smart ? 'Edit Smart Collection' : 'Rename Collection') : 'New Collection'}</h3>
    <label class="fld"><span>Name</span><input id="cName" value="${esc(c ? c.name : '')}" placeholder="e.g. Tigers 10U — Team Picks" autofocus></label>
    ${c ? '' : `<div class="fld"><span>Type</span>
      <label class="radio"><input type="radio" name="cType" value="regular" checked> Regular — you choose the photos</label>
      <label class="radio"><input type="radio" name="cType" value="smart"> Smart — fills itself from rules and updates live</label></div>
      <div class="fld" id="cRegular"><span>Start with</span>
      <label class="radio"><input type="radio" name="cStart" value="selected" ${selN ? 'checked' : 'disabled'}> Selected photos <em>(${selN})</em></label>
      <label class="radio"><input type="radio" name="cStart" value="filter" ${selN ? '' : 'checked'} ${filN ? '' : 'disabled'}> Everything in the current view <em>(${filN})</em></label>
      <label class="radio"><input type="radio" name="cStart" value="empty"> Empty</label></div>`}
    <div class="fld" id="cSmart" ${c ? (c.smart ? '' : 'hidden') : 'hidden'}><span>Match photos where</span>${rulesHTML(r)}</div>
    <div class="m-actions"><button class="btn" data-close>Cancel</button><button class="btn primary" data-ok>${c ? 'Save' : 'Create'}</button></div>`, card => {
    $$('input[name=cType]', card).forEach(i => i.addEventListener('change', () => { const smart = $('input[name=cType]:checked', card).value === 'smart'; $('#cSmart', card).hidden = !smart; $('#cRegular', card).hidden = smart; }));
    $('[data-ok]', card).addEventListener('click', () => {
      const name = $('#cName', card).value.trim() || 'Untitled Collection';
      if (c) { c.name = name; if (c.smart) c.smart = readRules(card); saveColl(c); closeModal(); toast(`Saved “${esc(name)}”`); recomputeView(); renderAll(); return; }
      const smart = $('input[name=cType]:checked', card).value === 'smart';
      const nc = { id: 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), name, keys: new Set(), smart: smart ? readRules(card) : null, created: Date.now() };
      if (!smart) {
        const st = ($('input[name=cStart]:checked', card) || {}).value;
        const ps = st === 'selected' ? orderedSelection().map(id => S.byId.get(id)) : st === 'filter' ? S.view : [];
        ps.forEach(p => nc.keys.add(p.key));
      }
      collections.push(nc); saveColl(nc); closeModal();
      toast(`Created “${esc(name)}” · ${plural(collCount(nc), 'photo')}`); renderAll();
    });
  });
}
function saveQuickAs() {
  const q = quickColl(), n = collCount(q);
  if (!n) return toast('The Quick Collection is empty');
  openModal(`<h3>Save Quick Collection</h3>
    <label class="fld"><span>Name</span><input id="qName" placeholder="e.g. Tigers 10U — Glare fixes" autofocus></label>
    <label class="radio"><input type="checkbox" id="qClear" checked> Clear the Quick Collection afterwards</label>
    <div class="m-actions"><button class="btn" data-close>Cancel</button><button class="btn primary" data-ok>Save · ${plural(n, 'photo')}</button></div>`, card => {
    const go = () => {
      const name = $('#qName', card).value.trim() || 'Untitled Collection';
      const nc = { id: 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), name, keys: new Set(q.keys), smart: null, created: Date.now() };
      collections.push(nc); saveColl(nc);
      if ($('#qClear', card).checked) { q.keys.clear(); saveColl(q); if (S.source.type === 'coll' && S.source.id === QUICK) S.source = { type: 'coll', id: nc.id }; }
      closeModal(); recomputeView(); renderAll();
      toast(`Saved “${esc(name)}” · ${plural(collCount(nc), 'photo')}`);
    };
    $('[data-ok]', card).addEventListener('click', go);
    $('#qName', card).addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); go(); } });
  });
}
function deleteColl(id) {
  const c = getColl(id); if (!c || c.id === QUICK) return;
  confirmDialog(`Delete the collection “${c.name}”?`, 'The photos themselves are not touched.', 'Delete', () => {
    collections = collections.filter(x => x !== c); DB.del('collections', id).catch(() => {});
    if (S.source.type === 'coll' && S.source.id === id) S.source = { type: 'all' };
    recomputeView(); renderAll(); toast(`Deleted “${esc(c.name)}”`);
  });
}

/* ================= Export (Library) ================= */
function exportList(o) {
  if (o.src === 'selection') return orderedSelection().map(id => S.byId.get(id));
  if (o.src === 'filter') return S.view.slice();
  const c = getColl(o.coll); return c ? collPhotos(c).sort(sorter()) : [];
}
function exportBaseName(o) {
  if (o.src === 'coll') { const c = getColl(o.coll); return c ? c.name : 'Collection'; }
  if (o.src === 'selection') return 'Selection';
  return S.source.type === 'all' ? (S.rootName || 'Export') : sourceName().replace(/^(Folder|Collection): /, '');
}
function buildNames(list, o, base) {
  const used = new Set(); const pad = Math.max(3, String(list.length).length);
  return list.map((p, i) => {
    const stem = o.naming === 'seq' ? `${sanitize(base) || 'Export'}_${String(i + 1).padStart(pad, '0')}` : p.name.replace(/\.[^.]+$/, '');
    const ex = o.resize ? '.jpg' : (p.name.match(/\.[^.]+$/) || [''])[0];
    let n = stem + ex, k = 2;
    while (used.has(n.toLowerCase())) n = `${stem}_${k++}${ex}`;
    used.add(n.toLowerCase()); return n;
  });
}
const csvCell = v => { v = String(v ?? ''); return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v; };
function buildCsv(list, names) {
  const rows = [['export_name', 'original_name', 'folder', 'flag', 'rating', 'label', 'collections', 'capture_time', 'crop_status']];
  list.forEach((p, i) => {
    const m = getMeta(p.key); const cs = Crop.status.get(p.path);
    rows.push([names ? names[i] : p.name, p.name, p.folder, m.flag === 1 ? 'pick' : m.flag === -1 ? 'reject' : '', m.rating || '', m.label,
      collections.filter(c => inColl(c, p)).map(c => c.name).join('; '), p.hasCapture ? new Date(p.capture).toISOString() : '', cs ? cs.status : '']);
  });
  return rows.map(r => r.map(csvCell).join(',')).join('\r\n');
}
function openExport() {
  if (!S.photos.length) return toast('Open a folder first');
  const selN = S.selected.size, filN = S.view.length;
  const colls = [quickColl(), ...userColls()];
  const defColl = S.source.type === 'coll' ? S.source.id : (colls.find(c => collCount(c)) || colls[0]).id;
  const defSrc = S.source.type === 'coll' ? 'coll' : selN > 1 ? 'selection' : 'filter';
  let dest = S.exportDest || (S.root ? `${S.root}_export` : '');
  openModal(`<h3>Export</h3>
    <div class="fld"><span>Photos</span>
      <label class="radio"><input type="radio" name="xSrc" value="selection" ${selN ? '' : 'disabled'} ${defSrc === 'selection' ? 'checked' : ''}> Selected photos <em>(${selN})</em></label>
      <label class="radio"><input type="radio" name="xSrc" value="coll" ${defSrc === 'coll' ? 'checked' : ''}> Collection <select id="xColl">${colls.map(c => `<option value="${esc(c.id)}" ${c.id === defColl ? 'selected' : ''}>${esc(c.name)} (${collCount(c)})</option>`).join('')}</select></label>
      <label class="radio"><input type="radio" name="xSrc" value="filter" ${defSrc === 'filter' ? 'checked' : ''}> Current view / filter <em>(${filN})</em></label></div>
    <div class="fld"><span>Export to</span>
      <div class="pathrow"><span class="path" id="xDest" title="${esc(dest)}">${esc(dest || 'Choose a folder…')}</span><button class="btn sm" id="xDestBtn">Change…</button></div></div>
    <div class="fld" id="xImgFld"><span>Files</span>
      <label class="radio"><input type="radio" name="xImg" value="orig" checked> Originals (untouched copies)</label>
      <label class="radio"><input type="radio" name="xImg" value="resize"> Resized JPEG</label>
      <div class="sub" id="xResize" hidden>Long edge <input type="number" id="xEdge" value="2048" min="200" max="12000" step="1"> px
        <span style="margin-left:8px">Quality</span> <input type="range" id="xQ" min="40" max="100" value="85"> <span id="xQv">85</span></div>
      <label class="radio"><input type="radio" name="xImg" value="none"> No photos — just the CSV list</label>
      ${Object.keys(Ret.info.edits).length ? `<label class="check" id="xRetWrap" title="Photos fixed in Retouch go out with the clear eyes, under their normal file names"><input type="checkbox" id="xRet" checked> Use retouched versions <em>(${Object.keys(Ret.info.edits).length} in this folder)</em></label>` : ''}</div>
    <div class="fld" id="xNameFld"><span>File names</span>
      <select id="xName"><option value="orig">Original filename</option><option value="seq">{collection}_{sequence}</option></select>
      <div class="muted small" id="xNamePrev"></div></div>
    <label class="check" id="xCsvWrap"><input type="checkbox" id="xCsv"> Also save a CSV list of filenames, flags, ratings, labels, collections and crop status</label>
    <div id="xProg" hidden style="margin-top:16px"><div class="prog"><div class="bar"></div></div><div class="prog-txt"></div></div>
    <div class="m-actions"><button class="btn" data-close id="xCancel">Cancel</button><button class="btn primary" data-ok>Export</button></div>`, card => {
    const opts = () => ({
      src: $('input[name=xSrc]:checked', card).value, coll: $('#xColl', card).value,
      img: $('input[name=xImg]:checked', card).value, resize: $('input[name=xImg]:checked', card).value === 'resize',
      edge: clamp(+$('#xEdge', card).value || 2048, 200, 12000), q: +$('#xQ', card).value,
      naming: $('#xName', card).value, retouched: !$('#xRet', card) || $('#xRet', card).checked, csv: $('#xCsv', card).checked || $('input[name=xImg]:checked', card).value === 'none',
    });
    const sync = () => {
      const o = opts(); const list = exportList(o);
      $('#xResize', card).hidden = !o.resize; $('#xQv', card).textContent = o.q;
      $('#xNameFld', card).hidden = o.img === 'none'; $('#xCsvWrap', card).hidden = o.img === 'none';
      const names = list.length ? buildNames(list.slice(0, 1), o, exportBaseName(o)) : [];
      $('#xNamePrev', card).textContent = names.length ? `e.g. ${names[0]}` : '';
      const ok = $('[data-ok]', card); ok.disabled = !list.length || !dest;
      ok.textContent = !list.length ? 'Nothing to export' : o.img === 'none' ? `Save list (${list.length})` : `Export ${plural(list.length, 'photo')}`;
    };
    card.addEventListener('input', sync); card.addEventListener('change', sync);
    $('#xColl', card).addEventListener('focus', () => { $('input[name=xSrc][value=coll]', card).checked = true; sync(); });
    $('#xDestBtn', card).addEventListener('click', async () => {
      const p = await pickPath('folder', { initial: dest || S.root || '' });
      if (p) { dest = p; $('#xDest', card).textContent = p; $('#xDest', card).title = p; sync(); }
    });
    sync();
    $('[data-ok]', card).addEventListener('click', () => runExport(opts(), card, dest));
  });
}
async function runExport(o, card, dest) {
  const list = exportList(o); if (!list.length || !dest) return;
  S.exportDest = dest;
  const base = exportBaseName(o); const names = buildNames(list, o, base);
  const items = o.img === 'none' ? [] : list.map((p, i) => ({ path: p.path, name: names[i] }));
  const csv = o.csv ? buildCsv(list, o.img === 'none' ? null : names) : null;
  const prog = $('#xProg', card); prog.hidden = false;
  const bar = $('.bar', prog), txt = $('.prog-txt', prog);
  $$('input,select', card).forEach(i => i.disabled = true); $('#xDestBtn', card).disabled = true;
  $('[data-ok]', card).hidden = true;
  let job;
  try { job = (await api('/api/export', { items, dest, opts: { resize: o.resize, edge: o.edge, quality: o.q, retouched: o.retouched, csv, csv_name: `${sanitize(base) || 'Export'}_list.csv` } })).job; }
  catch (e) { closeModal(); return toast('Export failed: ' + esc(e.message)); }
  S.exporting = { id: job };
  const cancelBtn = $('#xCancel', card); cancelBtn.textContent = 'Cancel export'; cancelBtn.removeAttribute('data-close');
  cancelBtn.onclick = () => { cancelJob(job); cancelBtn.disabled = true; cancelBtn.textContent = 'Cancelling…'; };
  const fin = await pollJob(job, s => {
    const f = s.total ? s.done / s.total : 1; bar.style.width = (f * 100).toFixed(1) + '%';
    txt.textContent = s.total ? `${s.done} of ${s.total}${s.current ? ' — ' + s.current : ''}${s.eta ? ' · about ' + fmtDur(s.eta) + ' left' : ''}` : 'Saving…';
  });
  S.exporting = null; closeModal();
  if (fin.error) return toast('Export failed: ' + esc(fin.error));
  const r = fin.result || {};
  if (r.cancelled) return toast(`Export cancelled after ${plural(r.copied || 0, 'photo')}`);
  toast(`${items.length ? `Exported ${plural(r.copied, 'photo')}` : 'Saved the list'} to “${esc(baseName(dest))}”${r.failed ? ` · ${r.failed} failed` : ''} <button class="toast-link" onclick="reveal(${esc(JSON.stringify(dest))})">Show</button>`, 5000);
}

/* ================= Modal, toast, help ================= */
function openModal(html, onMount) {
  const m = $('#modal'); const card = $('.modal-card', m);
  card.className = 'modal-card'; card.innerHTML = html; m.classList.remove('hidden');  // each window starts plain: no size class left over from the last one
  $$('[data-close]', card).forEach(b => b.addEventListener('click', () => { if (b.hasAttribute('data-close')) closeModal(); }));
  onMount && onMount(card);
  const f = $('[autofocus]', card); if (f) { f.focus(); f.select && f.select(); }
}
function closeModal() { if (S.exporting) return; $('#modal').classList.add('hidden'); $('.modal-card').innerHTML = ''; $('.modal-card').className = 'modal-card'; }
const modalOpen = () => !$('#modal').classList.contains('hidden');
function confirmDialog(title, sub, okLabel, onOk) {
  openModal(`<h3>${esc(title)}</h3><p class="muted">${esc(sub)}</p><div class="m-actions"><button class="btn" data-close>Cancel</button><button class="btn danger" data-ok>${esc(okLabel)}</button></div>`,
    card => $('[data-ok]', card).addEventListener('click', () => { closeModal(); onOk(); }));
}
function toast(html, ms = 1500) {
  const box = $('#toasts'); const t = document.createElement('div'); t.className = 'toast'; t.innerHTML = html;
  box.appendChild(t); requestAnimationFrame(() => t.classList.add('in'));
  setTimeout(() => { t.classList.remove('in'); setTimeout(() => t.remove(), 250); }, ms);
  while (box.children.length > 3) box.firstChild.remove();
}
function buildHelp() {
  const g = (title, rows, key) => `<div class="${key && key === S.module ? 'here' : ''}" style="order:${key && key === S.module ? -1 : 0}"><h4>${title}${key && key === S.module ? ' <span class="here-tag">this tab</span>' : ''}</h4>${rows.map(([d, k]) => `<div class="hk"><span>${d}</span><span>${k.split(' ').map(x => `<kbd>${x}</kbd>`).join('')}</span></div>`).join('')}</div>`;
  $('#help').innerHTML = `<div class="help-card"><h3>Keyboard Shortcuts <span class="help-ver">Keeper Studio ${esc((S.hello && S.hello.version) || '')}</span></h3><div class="help-grid">
    ${g('Views', [['Grid', 'G'], ['Loupe', 'E'], ['Compare', 'C'], ['Survey', 'N'], ['Toggle Loupe / Grid', 'Space'], ['Zoom Fit ↔ 1:1', 'Z'], ['Zoom in / out (also mouse wheel)', '+ −'], ['Full-screen preview', 'F'], ['Lights out (cycle)', 'L'], ['Back to Grid / close', 'Esc']], 'library')}
    ${g('Marking (every selected photo)', [['Pick', 'P'], ['Reject', 'X'], ['Unflag', 'U'], ['Team photo on / off', 'T'], ['Star rating', '0–5'], ['Red / Yellow / Green / Blue label', '6–9'], ['Quick Collection', 'B'], ['Save Quick Collection as…', 'Ctrl Alt B'], ['Mark and move to next', 'Shift +key'], ['Auto-advance always', 'Caps Lock'], ['Undo', 'Ctrl/⌘ Z']])}
    ${g('Selection & panels', [['Next / previous photo', '← →'], ['Row up / down (Grid)', '↑ ↓'], ['Several photos in the filmstrip', 'Ctrl/Shift-click'], ['Extend selection', 'Shift ←→'], ['Select all', 'Ctrl/⌘ A'], ['Deselect all', 'Ctrl/⌘ D'], ['Hide side panels', 'Tab'], ['Hide all panels', 'Shift Tab'], ['Toolbar', 'Shift T'], ['Filter bar', '\\']])}
    ${g('Tabs', [['Library', 'Ctrl 1'], ['Retouch (eye swap)', 'Ctrl 2  Q'], ['Crop', 'Ctrl 3  R'], ['Orders', 'Ctrl 4'], ['Composite', 'Ctrl 5'], ['Extract', 'Ctrl 6']])}
    ${g('Crop', [['Adjust framing', 'A'], ['Place 3.5 × 3.5', 'S'], ['Apply / cancel placing', 'Enter Esc'], ['Straighten 0.1° (Shift 1°)', '[ ]'], ['Apply / cancel straighten', 'Enter Esc'], ['Show the grid (hold)', 'G'], ['Centering lines, team photos (hold)', 'L'], ['Crop boxes on/off', 'O'], ['Color side by side', 'C'], ['Next / previous photo', '← →']], 'crop')}
    ${g('Orders', [['New envelope', 'N'], ['Add package A–G', 'A … G'], ['Another of that package', 'Shift +letter'], ['Next / previous envelope', '↑ ↓'], ['Next / previous team (Analysis)', '↑ ↓'], ['Floating photo preview', 'V'], ['Close envelope', 'Esc'], ['Delete envelope (with Undo)', 'Del'], ['Search', '/'], ['Select several envelopes', 'Ctrl/Shift-click'], ['Select all shown', 'Ctrl A'], ['Filmstrip photo (opens its envelope)', '← →']], 'orders')}
    ${g('Files', [['Open folder', 'Ctrl/⌘ O'], ['Save folder work now (it also saves itself)', 'Ctrl/⌘ S'], ['New collection', 'Ctrl/⌘ N'], ['Export', 'Ctrl/⌘ Shift E'], ['This help', '?']])}
    </div><p class="muted small" style="margin:16px 0 0">In Compare, ← → change the Candidate. Click a side to make it active; marking keys apply to the active side. Click an image to zoom 1:1 at that spot, scroll to zoom in or out, then drag to pan. In Compare and Survey every photo zooms and pans together.</p></div>`;
  if (!buildHelp.bound) { $('#help').addEventListener('click', () => toggleHelp(false)); buildHelp.bound = true; }
}
function toggleHelp(force) { const h = $('#help'); const show = force === undefined ? h.hidden : !!force; if (show) buildHelp(); h.hidden = !show; }

/* ================= Events ================= */
function bindCells(container, fromFilm) {
  container.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    const el = e.target.closest('.cell,.fcell'); if (!el || e.target.closest('[data-act]')) return;
    S.pendingSingle = null; selectByClick(+el.dataset.id, e, fromFilm);
  });
  container.addEventListener('click', e => {
    const el = e.target.closest('.cell,.fcell'); const a = e.target.closest('[data-act]');
    if (a && el) { e.stopPropagation(); cellAction(+el.dataset.id, a.dataset.act, +a.dataset.v); return; }
    if (el && S.pendingSingle === +el.dataset.id && !(e.ctrlKey || e.metaKey || e.shiftKey)) {
      S.selected = new Set([S.pendingSingle]); S.pendingSingle = null; refreshSelection();
    }
  });
  container.addEventListener('dblclick', e => {
    const el = e.target.closest('.cell,.fcell'); if (!el || e.target.closest('[data-act]')) return;
    S.active = +el.dataset.id; S.selected = new Set([S.active]); S.anchor = S.active;
    setMode(S.mode === 'loupe' && fromFilm ? 'loupe' : 'loupe');
  });
  container.addEventListener('dragstart', e => {
    const el = e.target.closest('.cell,.fcell'); if (!el) return;
    const id = +el.dataset.id;
    if (!S.selected.has(id)) { S.selected = new Set([id]); S.active = id; refreshSelection(); }
    S.pendingSingle = null;
    e.dataTransfer.setData('text/x-keeper', JSON.stringify(orderedSelection()));
    e.dataTransfer.effectAllowed = 'copy';
  });
}
function bindEvents() {
  bindCells($('#gridInner'), false); bindCells($('#filmInner'), true);
  $('#gridScroll').addEventListener('click', e => { if (e.target.id === 'gridScroll' || e.target.id === 'gridInner') deselect(); });
  let gs = false; $('#gridScroll').addEventListener('scroll', () => { if (!gs) { gs = true; requestAnimationFrame(() => { gs = false; renderGrid(); }); } });
  let fs = false; $('#filmScroll').addEventListener('scroll', () => { if (!fs) { fs = true; requestAnimationFrame(() => { fs = false; renderFilm(); }); } });
  $('#filmScroll').addEventListener('wheel', e => { if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) { $('#filmScroll').scrollLeft += e.deltaY; e.preventDefault(); } }, { passive: false });

  // Buttons should not steal keyboard focus (so Space / arrows keep working)
  document.addEventListener('mousedown', e => { if (e.target.closest('button') && !e.target.closest('.modal-card')) e.preventDefault(); });

  document.addEventListener('click', e => {
    const a = e.target.closest('[data-act]');
    if (a && !e.target.closest('.cell,.fcell,.sv,.cmp-foot')) {
      const act = a.dataset.act;
      if (act === 'open') return openFolder();
      if (act === 'export') return openExport();
      if (act === 'help') return toggleHelp();
    }
    const tg = e.target.closest('[data-toggle]'); if (tg) return togglePanel(tg.dataset.toggle);
    if (e.target.closest('[data-clear-filter]')) { S.filter = { flag: 'any', rating: 0, label: 'any', text: '', crop: 'any' }; $('#fText').value = ''; return afterFilter(); }
    const rx = e.target.closest('[data-recentx]'), rca = e.target.closest('[data-recentclear]');
    if (rx || rca) { api('/api/recent-forget', rca ? { all: true } : { path: rx.dataset.recentx }).then(r => { S.recent = r.recent; renderEmpty(); }).catch(err => toast(esc(err.message))); return; }
    const rc = e.target.closest('[data-recent]'); if (rc) return loadFolder(rc.dataset.recent);
    const dm = e.target.closest('[data-dismiss]'); if (dm) { S.banners = S.banners.filter(b => b.id !== dm.dataset.dismiss); renderBanners(); }
  });

  $('#left').addEventListener('click', e => {
    const t = e.target;
    if (t.closest('[data-newcoll]')) { e.stopPropagation(); return openCollDialog(); }
    if (t.closest('[data-teamaz]')) { e.stopPropagation(); return Ord.teamSortAZ(); }
    if (t.closest('[data-saveqc]')) { e.stopPropagation(); return saveQuickAs(); }
    const ed = t.closest('[data-edit]'); if (ed) { e.stopPropagation(); return openCollDialog(ed.dataset.edit); }
    const dl = t.closest('[data-delete]'); if (dl) { e.stopPropagation(); return deleteColl(dl.dataset.delete); }
    const hd = t.closest('.sec > header'); if (hd) { const id = hd.parentElement.dataset.sec; S.sections[id] = S.sections[id] === false; savePrefs(); renderLeft(); return; }
    const r = t.closest('[data-src]'); if (r) setSource(r.dataset.src);
  });
  $('#left').addEventListener('dblclick', e => { const r = e.target.closest('[data-src^="coll:"]'); if (r) { const id = r.dataset.src.slice(5); if (id !== QUICK) openCollDialog(id); } });
  $('#left').addEventListener('dragover', e => {
    const t = e.target.closest('[data-drop]');
    if (t && e.dataTransfer.types.includes('text/x-keeper')) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; $$('.drop-hover').forEach(x => x !== t && x.classList.remove('drop-hover')); t.classList.add('drop-hover'); }
  });
  $('#left').addEventListener('dragleave', e => { const t = e.target.closest('[data-drop]'); if (t && !t.contains(e.relatedTarget)) t.classList.remove('drop-hover'); });
  $('#left').addEventListener('drop', e => {
    const t = e.target.closest('[data-drop]'); $$('.drop-hover').forEach(x => x.classList.remove('drop-hover'));
    if (!t || !e.dataTransfer.types.includes('text/x-keeper')) return;
    e.preventDefault(); e.stopPropagation();
    try { addToColl(t.dataset.drop, JSON.parse(e.dataTransfer.getData('text/x-keeper'))); } catch {}
  });

  $('#right').addEventListener('click', e => {
    const hd = e.target.closest('.sec > header'); if (hd) { const id = hd.parentElement.dataset.sec; S.sections[id] = S.sections[id] === false; savePrefs(); renderRight(); return; }
    const mk = e.target.closest('[data-mark]'); if (mk) { const [f, v] = mk.dataset.mark.split(':'); return mark(f, f === 'label' ? v : +v, false); }
    if (e.target.closest('[data-quick]')) return toggleQuickFor(targets());
    const ch = e.target.closest('[data-src]'); if (ch) setSource(ch.dataset.src);
  });

  $('#survey').addEventListener('click', e => {
    const tile = e.target.closest('.sv'); if (!tile) return;
    const id = +tile.dataset.id; const a = e.target.closest('[data-act]');
    if (a) { S.active = id; return cellAction(id, a.dataset.act, +a.dataset.v); }
    S.active = id; renderAll();
  });
  $('#survey').addEventListener('dblclick', e => { const tile = e.target.closest('.sv'); if (tile && !e.target.closest('[data-act]')) { S.active = +tile.dataset.id; S.selected = new Set([S.active]); setMode('loupe'); } });

  $('#lights').addEventListener('click', () => { S.lights = 0; applyLights(); });
  $('#fs').addEventListener('click', e => { if (e.target.id === 'fsQc') { const p = S.byId.get(S.active); if (p) toggleQuickFor([p]); return; } exitFs(); });
  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && S.fs) exitFs(); });
  $('#modal').addEventListener('mousedown', e => { if (e.target.id === 'modal') closeModal(); });

  // Drag & drop folders onto the window
  let dragDepth = 0; const hasFiles = e => e.dataTransfer && [...e.dataTransfer.types].includes('Files');
  window.addEventListener('dragenter', e => { if (!hasFiles(e)) return; dragDepth++; $('#dropzone').classList.add('on'); });
  window.addEventListener('dragleave', e => { if (!hasFiles(e)) return; if (--dragDepth <= 0) { dragDepth = 0; $('#dropzone').classList.remove('on'); } });
  window.addEventListener('dragover', e => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener('drop', async e => {
    if (!hasFiles(e)) return; e.preventDefault(); dragDepth = 0; $('#dropzone').classList.remove('on');
    toast('Drag a folder onto the Keeper Studio window, or use Open Folder…', 3000);
  });

  const ro = new ResizeObserver(() => schedule(R_CELLS | R_ALL));
  ro.observe($('#viewport')); ro.observe($('#filmScroll'));
  new ResizeObserver(() => { if (S.module === 'orders') Ord.fitLeft(); }).observe($('#left'));
  // small drop-down menus (Orders bar): click to open, any click closes
  document.addEventListener('click', e => {
    const t = e.target.closest && e.target.closest('[data-dd]');
    const open = $$('.dd.open');
    if (t) { e.stopPropagation(); const dd = t.parentElement, was = dd.classList.contains('open'); open.forEach(x => x.classList.remove('open')); if (!was && !t.disabled) { dd.classList.add('open'); const m = dd.querySelector('.dd-menu'), r = t.getBoundingClientRect(); m.style.bottom = (window.innerHeight - r.top + 6) + 'px';
        if (m.classList.contains('right')) { m.style.right = (window.innerWidth - r.right) + 'px'; m.style.left = 'auto'; } else { m.style.left = r.left + 'px'; m.style.right = 'auto'; } } return; }
    open.forEach(x => x.classList.remove('open'));
  }, true);
  // Orders: drag a team in the Teams list to reorder. Done with plain mouse events, not the
  // browser's drag-and-drop, which in the app's window can stall while a drag is in flight.
  let tDrag = null;
  const tClear = () => $$('#left .dragging,#left .drop-above,#left .drop-below').forEach(x => x.classList.remove('dragging', 'drop-above', 'drop-below'));
  $('#left').addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const r = e.target.closest('[data-tdrag]'); if (!r || e.target.closest('button')) return;
    tDrag = { name: r.dataset.tdrag, y: e.clientY, on: false, id: e.pointerId };
  });
  window.addEventListener('pointermove', e => {
    if (!tDrag) return;
    if (!tDrag.on) {
      if (Math.abs(e.clientY - tDrag.y) < 6) return;
      tDrag.on = true; document.body.classList.add('team-dragging');
      const src = $(`#left [data-tdrag="${CSS.escape(tDrag.name)}"]`); if (src) src.classList.add('dragging');
    }
    e.preventDefault();
    $$('#left .drop-above,#left .drop-below').forEach(x => x.classList.remove('drop-above', 'drop-below'));
    const el = document.elementFromPoint(e.clientX, e.clientY), r = el && el.closest('[data-tdrag]');
    if (r && r.dataset.tdrag !== tDrag.name) { const bb = r.getBoundingClientRect(); r.classList.add(e.clientY < bb.top + bb.height / 2 ? 'drop-above' : 'drop-below'); tDrag.over = r.dataset.tdrag; tDrag.above = e.clientY < bb.top + bb.height / 2; }
    else tDrag.over = null;
    // scroll the team list when dragging near its top or bottom edge
    const box = $('#left [data-sec="o-teams"] > .body'); if (box) { const bb = box.getBoundingClientRect(); if (e.clientY < bb.top + 24) box.scrollTop -= 12; else if (e.clientY > bb.bottom - 24) box.scrollTop += 12; }
  });
  window.addEventListener('pointerup', () => {
    if (!tDrag) return;
    const d = tDrag; tDrag = null; document.body.classList.remove('team-dragging'); tClear();
    if (!d.on) return;  // a plain click: let it pick the team
    S.suppressTeamClick = true; setTimeout(() => { S.suppressTeamClick = false; }, 0);
    if (!d.over || d.over === d.name) return;
    const names = Ord.d.teams.map(t => t.name).filter(t => t !== d.name), i = names.indexOf(d.over);
    Ord.dropTeam(d.name, d.above ? d.over : (names[i + 1] ?? null));
  });
  window.addEventListener('pointercancel', () => { tDrag = null; document.body.classList.remove('team-dragging'); tClear(); });

  document.addEventListener('keyup', e => { const c = e.getModifierState && e.getModifierState('CapsLock'); if (c !== S.caps) { S.caps = c; syncToolbar(); } });
  document.addEventListener('keydown', onKey);
}
function onKey(e) {
  const caps = !!(e.getModifierState && e.getModifierState('CapsLock'));
  if (caps !== S.caps) { S.caps = caps; syncToolbar(); }
  const t = e.target; const tag = t.tagName;
  const typing = (tag === 'INPUT' && !['range', 'checkbox', 'radio'].includes(t.type)) || tag === 'TEXTAREA' || tag === 'SELECT';
  if (modalOpen()) {
    if (e.key === 'Escape') closeModal();
    else if (e.key === 'Enter' && tag !== 'TEXTAREA' && tag !== 'SELECT') { const ok = $('.modal-card [data-ok]'); if (ok && !ok.hidden && !ok.disabled) { e.preventDefault(); ok.click(); } }
    return;
  }
  if (typing) { if (e.key === 'Escape' || e.key === 'Enter') t.blur(); return; }
  const mod = e.ctrlKey || e.metaKey; const k = e.key.toLowerCase();
  if (mod && e.shiftKey && k === 'e') { e.preventDefault(); return openExport(); }
  if (mod && k === 'z') { e.preventDefault(); return undo(); }
  if (mod && k === 'a') { e.preventDefault(); return S.module === 'orders' ? Ord.selectAllRows() : selectAll(); }
  if (mod && k === 'd') { e.preventDefault(); return S.module === 'orders' ? Ord.clearMulti() : deselect(); }
  if (mod && k === 'o') { e.preventDefault(); return openFolder(); }
  if (mod && k === 's' && !e.shiftKey) { e.preventDefault(); return Work.flush(true); }
  if (mod && k === 'n') { e.preventDefault(); return openCollDialog(); }
  if (mod && e.altKey && e.code === 'KeyB') { e.preventDefault(); return saveQuickAs(); }
  if (mod && /^[1-6]$/.test(e.key)) { e.preventDefault(); return setModule(MODULES[+e.key - 1][0]); }
  if (mod || (e.altKey && S.module !== 'retouch')) return;
  if (e.key === '?') return toggleHelp();
  if (!$('#help').hidden) { if (e.key === 'Escape') toggleHelp(false); return; }
  if (e.key === 'Tab') { e.preventDefault(); return e.shiftKey ? toggleAllPanels() : toggleSidePanels(); }
  if (S.module !== 'library') { const mm = Mods.get(S.module); if (mm && mm.key(e, k)) { e.preventDefault(); return; } }
  if (e.key === 'Escape') {
    if (S.fs) return exitFs();
    if (S.module !== 'library') return;
    if (S.lights) { S.lights = 0; return applyLights(); }
    if (S.mode !== 'grid') return setMode('grid');
    return;
  }
  if (k === 't' && e.shiftKey) { S.panels.toolbar = !S.panels.toolbar; savePrefs(); return renderAll(); }
  if (e.key === '\\') { S.panels.filterbar = !S.panels.filterbar; savePrefs(); return renderAll(); }
  if (!S.photos.length) return;
  const dg = /^(?:Digit|Numpad)(\d)$/.exec(e.code);
  if (dg) { e.preventDefault(); const n = +dg[1]; return n <= 5 ? mark('rating', n, e.shiftKey) : mark('label', LABELS[n - 6], e.shiftKey); }
  switch (e.key) {
    case 'ArrowLeft': e.preventDefault(); return nav(-1, 0, e);
    case 'ArrowRight': e.preventDefault(); return nav(1, 0, e);
    case 'ArrowUp': e.preventDefault(); return S.mode === 'grid' && !S.fs ? nav(0, -1, e) : nav(-1, 0, e);
    case 'ArrowDown': e.preventDefault(); return S.mode === 'grid' && !S.fs ? nav(0, 1, e) : nav(1, 0, e);
    case ' ': e.preventDefault(); if (S.module !== 'library') setModule('library'); return setMode(S.mode === 'loupe' ? 'grid' : 'loupe');
  }
  if ('gecn'.includes(k) && k && S.module !== 'library') setModule('library');
  if (k === 'r' && S.module !== 'crop') return setModule('crop');
  if (k === 'q' && S.module !== 'retouch') return setModule('retouch');
  switch (k) {
    case 'g': if (S.fs) exitFs(); return setMode('grid');
    case 'e': if (S.fs) exitFs(); return setMode('loupe');
    case 'c': if (S.fs) exitFs(); return setMode('compare');
    case 'n': if (S.fs) exitFs(); return setMode('survey');
    case 'p': return mark('flag', 1, e.shiftKey);
    case 'x': return mark('flag', -1, e.shiftKey);
    case 'u': return mark('flag', 0, e.shiftKey);
    case 't': return markTeam(false);
    case 'b': return toggleQuickFor(targets());
    case 'l': return cycleLights();
    case 'f': return toggleFs();
    case 'z': return toggleZoom();
    case '=': case '+': return zoomBy(1.25);
    case '-': case '_': return zoomBy(1 / 1.25);
  }
}

/* ================= Modules: Library · Retouch · Crop · Composite · Extract · Orders ================= */
// Modules that work with no folder open.
const NO_PHOTOS_NEEDED = new Set(['composite', 'orders']);
// Picture-day tabs in workflow order, then the once-a-year ones (preschool composites, fall banners) after a divider.
const MODULES = [['library', 'Library'], ['retouch', 'Retouch'], ['crop', 'Crop'], ['orders', 'Orders'], ['composite', 'Composite'], ['cutout', 'Extract']];
const OCCASIONAL = new Set(['composite', 'cutout']);
const SIZE_COLOR_BY_NAME = { '16x20': '#FFFFFF', '8x10': '#2E9BFF', '5x7': '#3CC7A0', '4x6': '#E8C547', '4x5': '#D07AE6', '2_5x3_5': '#F08A5D', '1_8x2_8': '#7BD389', '1_7x2_2': '#9C8BFF', '3_5x3_5': '#FF6B8B', '10x8': '#5BC0EB', '7x5': '#C9CED6', '11x14': '#A0E7E5', '14x11': '#F2B5D4', '20x16': '#B8E986' };
const SIZE_COLORS = ['#2E9BFF', '#3CC7A0', '#E8C547', '#D07AE6', '#F08A5D', '#7BD389', '#9C8BFF', '#FF6B8B', '#5BC0EB', '#C9CED6', '#F2B5D4', '#B8E986'];
const prettySize = n => String(n).replace(/_/g, '.').replace(/x/g, ' × ');
// Ready to print = framed as planned, shortened to fit, or placed by hand: all three print.
const READY = new Set(['ok', 'shortened', 'manual']);
const STATUS_INFO = {
  ready: { label: 'Ready to print (all)', cls: 'ok', icon: '✓' },
  ok: { label: 'Ready to print', cls: 'ok', icon: '✓' },
  shortened: { label: 'Shortened to fit', cls: 'short', icon: '↕' },
  manual: { label: 'Placed by hand', cls: 'manual', icon: '✋' },
  review: { label: 'Needs review', cls: 'review', icon: '!' },
  unchecked: { label: 'Not checked yet', cls: 'none', icon: '·' },
};
function setModule(m) {
  if (S.module === m) return;
  if (S.module === 'orders') Ord.endTeamPick();
  if (S.fs) exitFs();
  setTimeout(() => Ord.pvPaint());
  if (Crop.adjusting) Crop.cancelAdjust(true);
  Crop.closeTune();
  const wasFiltered = S.module === 'crop' && S.cropShow !== 'all';
  S.module = m;
  if (wasFiltered) { S.cropShow = 'all'; recomputeView(); }
  if (m !== 'library' && S.active == null && S.view.length) { S.active = S.view[0].id; S.selected = new Set([S.active]); S.anchor = S.active; }
  renderAll(); ensureVisible();
  const mod = Mods.get(m); if (mod && mod.enter) mod.enter();
}
const Mods = {
  get(m) { return { crop: Crop, composite: Comp, cutout: Cut, retouch: Ret, orders: Ord }[m]; },
  libraryLoaded() { Crop.libraryLoaded(); Cut.libraryLoaded(); Comp.libraryLoaded(); Ret.libraryLoaded(); Ord.libraryLoaded(); },
  chrome() {
    const lib = S.module === 'library';
    $('#modView').hidden = lib || !S.photos.length && !NO_PHOTOS_NEEDED.has(S.module);
    $('#modbar').hidden = lib;
    $$('#top [data-module]').forEach(b => b.classList.toggle('on', b.dataset.module === S.module));
    document.body.dataset.module = S.module;
  },
};
function switchHTML(id, on, label, hint = '') {
  return `<label class="sw-row" ${hint ? `title="${esc(hint)}"` : ''}><span>${label}</span><button class="switch ${on ? 'on' : ''}" data-sw="${id}" role="switch" aria-checked="${on}"><i></i></button></label>`;
}
function segHTML(name, value, options) {
  return `<div class="seg" data-seg="${name}">${options.map(([v, l]) => `<button class="${v === value ? 'on' : ''}" data-v="${esc(v)}">${l}</button>`).join('')}</div>`;
}
function progressHTML(s, verb) {
  const f = s.total ? s.done / s.total : 0;
  return `<div class="job-card">
    <div class="job-top"><b>${esc(verb)}</b><span class="muted">${s.total ? `${s.done} / ${s.total}` : ''}</span></div>
    <div class="prog ${s.busy || !s.total ? 'busy' : ''}"><div class="bar" style="width:${(f * 100).toFixed(1)}%"></div></div>
    <div class="job-sub">${esc(s.message || s.current || '')}${s.eta ? ` · about ${fmtDur(s.eta)} left` : ''}</div>
    <button class="btn sm" data-cancel-job="${s.id}">Cancel</button></div>`;
}
function scopeList(scope) {
  const l = scope === 'selected' ? orderedSelection().map(id => S.byId.get(id)).filter(Boolean) : S.view.slice();
  return l.filter(p => !Ret.isDonor(p.path));  // eye donors (Retouch) are never printed
}

