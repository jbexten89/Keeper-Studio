// Keeper Studio UI — composite. Plain scripts sharing one global scope, loaded in order by index.html.
'use strict';
/* =========================================================== Composite ==== */
const Comp = {
  f: null, order: null, built: null, job: null, jobState: null, fontsOk: {},
  async load() {
    try {
      const r = await api('/api/composite/defaults', {});
      this.f = Object.assign({ students: 'quick', teachers: 'none', out_path: '' }, r.defaults, r.saved || {});
    } catch { this.f = { students: 'quick', teachers: 'none' }; }
  },
  libraryLoaded() { this.order = null; this.built = null; this.needPick = true; this.autoNote = ''; },
  save() { api('/api/composite/defaults', { settings: this.f }).catch(() => {}); },
  sources() {
    // folders below the shoot's top folder, e.g. "Students" and "Teachers"
    const dirs = folderTree().filter(([k]) => k.includes('/')).map(([k, n]) => ['dir:' + k, `▸ ${k.split('/').slice(1).join(' / ')} (${n})`]);
    return [['selected', `Selected photos (${S.selected.size})`], ['quick', `Quick Collection (${collCount(quickColl())})`],
      ...userColls().map(c => ['coll:' + c.id, `${c.name} (${collCount(c)})`]), ...dirs, ['filmstrip', `Filmstrip (${S.view.length})`]];
  },
  // a collection or folder called Students / Teachers is picked for you when a folder is opened
  autoPick() {
    const find = re => {
      const c = userColls().find(c => re.test(c.name.trim()) && collCount(c));
      if (c) return 'coll:' + c.id;
      const d = folderTree().find(([k]) => k.includes('/') && re.test(k.split('/').pop().trim()));
      return d ? 'dir:' + d[0] : null;
    };
    const st = find(/^(students?|kids|players?|athletes?)$/i), te = find(/^(teachers?|staff|coach(es)?)$/i);
    const got = [];
    if (st && this.f.students !== st) { this.f.students = st; got.push('Students'); }
    if (te && this.f.teachers !== te) { this.f.teachers = te; got.push('Teachers'); }
    if (got.length) { this.save(); this.autoNote = `${got.join(' and ')} picked from the folder or collection of that name.`; }
  },
  photosFor(src) { return this.photosFrom(src).filter(p => !Ret.isDonor(p.path)); },  // eye donors never go on a composite
  photosFrom(src) {
    if (!src || src === 'none') return [];
    if (src === 'selected') return orderedSelection().map(id => S.byId.get(id)).filter(Boolean);
    if (src === 'filmstrip') return S.view.slice();
    if (src.startsWith('dir:')) { const k = src.slice(4); return S.photos.filter(p => p.folder === k || p.folder.startsWith(k + '/')).sort((a, b) => collator.compare(a.name, b.name)); }
    const c = getColl(src === 'quick' ? QUICK : src.slice(5)); return c ? collPhotos(c) : [];
  },
  async refreshOrder() {
    if (this.needPick && this.f && S.photos.length) { this.needPick = false; this.autoPick(); }
    const st = this.photosFor(this.f.students).map(p => p.path), te = this.photosFor(this.f.teachers).map(p => p.path);
    try { this.order = await api('/api/composite/order', { students: st, teachers: te, max_per_row: +this.f.max_per_row || 8, row_counts: this.f.row_counts || '' }); } catch { this.order = null; }
    const fonts = [this.f.title_font, this.f.teacher_font, this.f.name_font, this.f.background].filter(Boolean);
    try { this.fontsOk = (await api('/api/exists', { paths: fonts })).exists; } catch {}
    if (S.module === 'composite') { renderRight(); renderLeft(); }
  },
  enter() { this.refreshOrder(); this.render(); },
  render() { renderView(); renderLeft(); renderRight(); },
  rows(n) {
    const raw = String(this.f.row_counts || '').trim();
    if (raw) return raw.split(/[\s,]+/).filter(Boolean).map(Number);
    const maxc = Math.max(1, +this.f.max_per_row || 8); if (!n) return [];
    const rows = Math.ceil(n / maxc), base = Math.floor(n / rows), extra = n % rows;
    return Array.from({ length: rows }, (_, i) => base + (i >= rows - extra ? 1 : 0));
  },
  defaultOut() {
    const st = this.photosFor(this.f.students); if (!st.length) return '';
    const name = `${this.f.school || 'Class'} ${this.f.year || ''}`.trim() + ' composite.jpg';
    return dirName(dirName(st[0].path)) + (st[0].path.includes('\\') ? '\\' : '/') + name;
  },
  fileRow(key, label, kind) {
    const v = this.f[key]; const missing = v && this.fontsOk[v] === false;
    return `<div class="frow"><span class="flabel">${label}</span><div class="pathrow"><span class="path ${missing ? 'bad' : ''}" title="${esc(v || '')}">${esc(v ? baseName(v) : 'Not set')}${missing ? ' — not found' : ''}</span><button class="btn sm" data-comp-pick="${key}" data-kind="${kind}">Choose…</button></div></div>`;
  },
  left() {
    const f = this.f || {}; const srcOpts = (val, none) => (none ? [['none', 'No teachers']] : []).concat(this.sources()).map(([v, l]) => `<option value="${esc(v)}" ${v === val ? 'selected' : ''}>${esc(l)}</option>`).join('');
    const html = sectionHTML('cp-class', 'Class', `<div class="form">
        <div class="frow"><span class="flabel">School name</span><input data-cf="school" value="${esc(f.school || '')}"></div>
        <div class="frow"><span class="flabel">Year</span><input data-cf="year" value="${esc(f.year || '')}" placeholder="e.g. 2026–2027"></div></div>`)
      + sectionHTML('cp-photos', 'Photos', `<div class="form">
        <div class="frow"><span class="flabel">Students</span><select data-cf="students">${srcOpts(f.students)}</select></div>
        <div class="frow"><span class="flabel">Teachers</span><select data-cf="teachers">${srcOpts(f.teachers, true)}</select></div>${this.autoNote ? `<div class="hint tight">${esc(this.autoNote)}</div>` : ''}
        ${this.fileRow('background', 'Background', 'image')}
        <div class="hint tight">Names come from the file names. Students sort by last name; number teacher files (“1 Ms Sheila”) to set their order.</div></div>`)
      + sectionHTML('cp-layout', 'Layout', `<div class="form">
        <div class="frow"><span class="flabel">Most per row</span><input type="number" min="1" max="20" data-cf="max_per_row" value="${esc(f.max_per_row ?? 8)}"></div>
        <div class="frow"><span class="flabel">Per row (optional)</span><input data-cf="row_counts" value="${esc(f.row_counts || '')}" placeholder="e.g. 6, 6, 7"></div></div>
        ${switchHTML('uppercase', !!f.uppercase, 'UPPERCASE names (Stencil look)')}`)
      + sectionHTML('cp-fonts', 'Fonts', `<div class="form">${this.fileRow('title_font', 'Title', 'font')}${this.fileRow('teacher_font', 'Teacher names', 'font')}${this.fileRow('name_font', 'Student names', 'font')}</div>`)
      + sectionHTML('cp-save', 'Save as', `<div class="form">${this.fileRow('out_path', 'File', 'save')}${!f.out_path && this.defaultOut() ? `<div class="hint tight">Default: ${esc(baseName(this.defaultOut()))}</div>` : ''}</div>`);
    const foot = this.job && this.jobState && !this.jobState.finished ? progressHTML(this.jobState, 'Building composite') : '';
    $('#left').innerHTML = `<div class="scroll">${html}</div><div class="left-foot col">${foot}<button class="btn primary big" data-comp="build" ${this.job ? 'disabled' : ''}>Build composite</button></div>`;
  },
  right() {
    const o = this.order; const R = $('#right');
    if (!o) { R.innerHTML = '<div class="scroll"><div class="hint">Choose the student photos on the left.</div></div>'; return; }
    const rows = o.rows || [];
    const person = it => `<div class="person"><img src="${thumbUrl(it.path, 200)}" alt=""><span>${esc(it.label)}</span></div>`;
    R.innerHTML = `<div class="scroll">${sectionHTML('cp-t', `Teachers · ${o.teachers.length}`, `<div class="people">${o.teachers.map(person).join('') || '<div class="hint">None</div>'}</div>`)}
      ${sectionHTML('cp-s', `Students · ${o.students.length}`, `<div class="hint tight">${rows.length ? `Rows, top to bottom: ${rows.join(' · ')}` : ''}${rows.length && rows.reduce((a, b) => a + b, 0) !== o.students.length ? ' <b class="warn">— doesn’t add up to the class size</b>' : ''}</div><div class="people">${o.students.map(person).join('') || '<div class="hint">No student photos.</div>'}</div>`)}</div>`;
  },
  center() {
    const v = $('#modView'); v.dataset.mod = 'composite';
    const src = this.built ? fileUrl(this.built.path, this.built.t) : this.f && this.f.background && this.fontsOk[this.f.background] !== false ? fileUrl(this.f.background) : null;
    v.innerHTML = `<div class="comp-stage">${src ? `<img src="${src}" alt="">` : '<div class="msg">Choose a background template and the class photos, then press Build composite.</div>'}
      ${!this.built && src ? '<div class="comp-note">Background preview — press Build composite to lay out the class</div>' : ''}</div>`;
  },
  modbar() {
    $('#modbar').innerHTML = `<button class="btn sm primary" data-comp="build" ${this.job ? 'disabled' : ''}>Build composite</button>
      ${this.built ? `<button class="btn sm" data-comp="open">Open</button><button class="btn sm" data-comp="reveal">Show in folder</button><span class="muted small">${esc(baseName(this.built.path))}</span>` : ''}<div class="tb-spacer"></div>`;
  },
  async build() {
    const f = this.f; const students = this.photosFor(f.students);
    const errs = [];
    if (!students.length) errs.push('Choose the student photos.');
    if (!f.background) errs.push('Choose a background template.');
    ['title_font', 'teacher_font', 'name_font'].forEach(k => { if (!f[k]) errs.push('Choose all three fonts.'); });
    let row_counts = null;
    if (String(f.row_counts || '').trim()) {
      row_counts = String(f.row_counts).split(/[\s,]+/).filter(Boolean).map(Number);
      if (row_counts.some(n => !(n > 0))) errs.push('“Per row” must be whole numbers, like 6, 6, 7.');
      else if (row_counts.reduce((a, b) => a + b, 0) !== students.length) errs.push(`“Per row” adds up to ${row_counts.reduce((a, b) => a + b, 0)}, but there are ${students.length} students.`);
    }
    if (errs.length) return toast(esc([...new Set(errs)][0]), 3500);
    const out = f.out_path || this.defaultOut();
    let id;
    try { id = (await api('/api/composite/build', { ...f, out_path: out, row_counts, students: students.map(p => p.path), teachers: this.photosFor(f.teachers).map(p => p.path) })).job; }
    catch (e) { return toast(esc(e.message)); }
    this.job = id; this.jobState = { id, busy: true, total: 0, done: 0, message: 'Building…' }; this.render(); this.modbar();
    const fin = await pollJob(id, s => { this.jobState = s; if (S.module === 'composite') renderLeft(); });
    this.job = null; this.jobState = null;
    if (fin.error) { this.render(); this.modbar(); return toast('Composite failed: ' + esc(fin.error), 6000); }
    this.built = { path: fin.result.out_path, t: Date.now() }; this.render(); this.modbar();
    toast(`Composite saved as “${esc(baseName(fin.result.out_path))}”`, 4000);
  },
  key() { return false; },
};

