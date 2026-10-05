// The Templates view: choose a template and the new data. The server keeps the choices (per session);
// this file only draws them and sends files. app.js passes in its helpers (init) and calls show, hide,
// dropHint and acceptDrop. Everything is inside one function so no name here can clash with app.js.
(function () {
  'use strict';

  const MAX_MB = 200;
  const DATA_EXT = /\.(csv|tsv|txt|xlsx|xlsm|twb|twbx|tds)$/i;
  const TEMPLATE_EXT = /\.twbx$/i;
  const SHOW_STEP = 50;      // findings drawn at first, and added by each Show more
  const SHOW_MAX = 500;      // never more than this many findings in the page
  const COLUMN_CAP = 200;    // column names listed under a data file
  const ROW_PAGE = 200;      // mapping rows drawn at first, and added by each Show more
  const OPTION_CAP = 1000;   // options in one open dropdown
  const GROUP_STEP = 50;     // rows of a plan group drawn at first, and added by each Show more
  const GROUP_MAX = 500;     // never more than this many rows of one plan group in the page
  const PLAN_DELAY = 300;    // ms to wait after an edit before asking the server for a new plan
  const SEVERITIES = [
    ['error', '\u2716', 'Problem', 'problem'],
    ['warning', '\u25B2', 'Needs a look', 'warning'],
    ['info', '\u2022', 'Worth knowing', 'info'],
  ];

  let D = null;   // the helpers from app.js: $, el, setStatus, fetchJSON, fail, plural
  let R = null;   // the elements of step 3, null while it is locked
  let planTimer = null, planCtl = null, planSeq = 0;
  const S = {
    open: false, seq: 0,
    template: null, data: null, sheets: null, datasources: null,
    dataName: '',            // the file name of the data, kept while a sheet or datasource is still to be chosen
    tplDs: '',               // the template datasource chosen when there are several
    place: '',               // "where will this file be on your computer" (optional)
    dsPick: '', sheetPick: '',
    shown: SHOW_STEP,
    busy: {template: '', data: ''},
    changing: {template: false, data: false},
    gen: 0,                  // counts the times a file was replaced; step 3 starts over when it changes
    rv: null,                // what the person has done in step 3, see freshReview
    workbook: '',            // the file name of the open workbook, '' when none is open
    made: null,              // the template made from it: {name, size, template, notes}
    makeName: '', makeDesc: '', making: false, makeError: '',
  };

  // What step 3 holds: only what the person changed (edits), never a copy of the whole mapping.
  function freshReview() {
    return {edits: {}, params: {}, tokens: {}, plan: null, planError: '', dirty: true, allowMissing: false,
      optional: false, filter: '', rowsShown: ROW_PAGE, showAll: {}, groupShown: {}, created: null, saved: '', working: ''};
  }
  S.rv = freshReview();

  const ready = () => S.template !== null;
  const chosen = () => S.data !== null;
  const pending = () => S.data === null && ((S.sheets && S.sheets.length > 1) || (S.datasources && S.datasources.length > 1));

  // ---- talking to the server -----------------------------------------------------------------------

  function sendFile(slot, file) {
    const url = slot === 'template' ? '/template/upload-template' : '/template/upload-data';
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url);
      xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name));
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && file.size > 5 * 1048576) {
          D.setStatus('Reading ' + file.name + ' (' + Math.round(100 * e.loaded / e.total) + '%) ...', false, 'busy');
        }
      };
      xhr.onerror = () => reject(new Error('the upload did not go through'));
      xhr.onload = () => {
        let body = {};
        try { body = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body);
        else reject(new Error(body.error || xhr.statusText));
      };
      xhr.send(file);
    });
  }

  function postJSON(url, payload) {
    return D.fetchJSON(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  }

  function wrongFile(slot, name) {
    if (slot === 'template' && !TEMPLATE_EXT.test(name)) {
      return name + ' is not a template. A template is a .twbx file made with py-tbparse template make.';
    }
    if (slot === 'data' && !DATA_EXT.test(name)) {
      return name + ' cannot be used as data. Use a .csv, .tsv, .txt, Excel (.xlsx, .xlsm), or a Tableau .twb, .twbx or .tds file.';
    }
    return '';
  }

  // Take what the server answered for a slot, then draw it.
  function accept(slot, answer, name) {
    if (slot === 'template') {
      S.template = answer.template || null;
      S.tplDs = '';
      S.changing.template = false;
    } else {
      S.data = answer.data || null;
      S.sheets = answer.sheets || null;
      S.datasources = answer.datasources || null;
      S.dataName = (answer.data && answer.data.label) || name || S.dataName;
      S.dsPick = '';
      S.sheetPick = (answer.data && answer.data.sheet) || '';
      S.changing.data = false;
    }
    S.shown = SHOW_STEP;
    S.gen += 1;
  }

  async function chooseFile(slot, file) {
    const bad = wrongFile(slot, file.name);
    if (bad) { D.fail(new Error(bad)); return; }
    if (file.size > MAX_MB * 1024 * 1024) {
      D.fail(new Error(file.name + ' is ' + Math.round(file.size / 1048576) + ' MB; the limit is ' + MAX_MB + ' MB.'));
      return;
    }
    await run(slot, file.name, () => sendFile(slot, file));
  }

  async function openPath(slot, path) {
    path = path.trim();
    if (!path) { D.setStatus('Type the path of the file first, or drop it onto the page.', true); return; }
    const name = path.replace(/\\/g, '/').split('/').pop();
    const bad = wrongFile(slot, name);
    if (bad) { D.fail(new Error(bad)); return; }
    await run(slot, name, () => postJSON(slot === 'template' ? '/template/open' : '/template/open-data', {path: path}));
  }

  async function run(slot, name, request) {
    const mine = ++S.seq;
    S.busy[slot] = name;
    D.setStatus('Reading ' + name + ' ...', false, 'busy');
    render();
    try {
      const answer = await request();
      if (mine !== S.seq) return;
      accept(slot, answer, name);
      S.busy[slot] = '';
      D.setStatus('', false);
      render();
      announceStep(slot);
    } catch (e) {
      if (mine !== S.seq) return;
      S.busy[slot] = '';
      D.fail(e);
      render();
    }
  }

  async function useChoice(kind) {
    const payload = kind === 'sheet' ? {sheet: S.sheetPick} : {datasource: S.dsPick};
    if (!payload.sheet && !payload.datasource) { D.setStatus('Choose one from the list first.', true); return; }
    const mine = ++S.seq;
    S.busy.data = S.dataName || 'the file';
    render();
    try {
      const answer = await postJSON('/template/select-data', payload);
      if (mine !== S.seq) return;
      const keep = kind === 'sheet' ? S.sheetPick : S.dsPick;
      accept('data', answer, S.dataName);
      if (kind === 'sheet') S.sheetPick = keep; else S.dsPick = keep;
      S.busy.data = '';
      render();
      announceStep('data');
    } catch (e) {
      if (mine !== S.seq) return;
      S.busy.data = '';
      D.fail(e);
      render();
    }
  }

  async function restore() {
    const mine = ++S.seq;
    try {
      const answer = await D.fetchJSON('/template/state');
      if (mine !== S.seq) return;
      S.template = answer.template || null;
      S.data = answer.data || null;
      S.sheets = answer.sheets || null;
      S.datasources = answer.datasources || null;
      S.dataName = (answer.data && answer.data.label) || S.dataName;
      S.sheetPick = (answer.data && answer.data.sheet) || '';
      takeMake(answer);
      render();
    } catch (e) {
      if (mine === S.seq) D.fail(e);
    }
  }

  function takeMake(answer) {
    S.workbook = (answer.workbook && answer.workbook.name) || '';
    if (answer.made) S.made = {name: answer.made.name, size: answer.made.size, template: answer.made.template,
      notes: (S.made && S.made.name === answer.made.name && S.made.notes) || []};
    else S.made = null;
  }

  // The open workbook changed (app.js opened one): ask again which one is open, without touching the steps.
  async function refresh() {
    try {
      takeMake(await D.fetchJSON('/template/state'));
      renderMake();
    } catch (e) { /* the next show() asks again */ }
  }

  // ---- drawing ---------------------------------------------------------------------------------------

  const el = (tag, cls, text) => D.el(tag, cls, text);

  function button(id, label, cls, onClick) {
    const b = el('button', 'btn ' + (cls || ''), label);
    b.type = 'button';
    if (id) b.id = id;
    b.addEventListener('click', onClick);
    return b;
  }

  function setCard(n, state, reason) {
    const card = D.$('tplCard' + n);
    card.dataset.state = state;
    if (state === 'locked') card.setAttribute('aria-disabled', 'true'); else card.removeAttribute('aria-disabled');
    const body = D.$('tplBody' + n);
    body.textContent = '';
    if (state === 'locked') body.appendChild(el('p', 'tpl-reason', reason));
    return body;
  }

  // The empty step: where to drop, a button for the file picker, and (on a local GUI) a path box.
  function chooser(slot, what, hint) {
    const box = el('div', 'tpl-drop');
    box.appendChild(el('p', 'tpl-lead', 'Drop ' + what + ' here, or'));
    const cap = slot === 'template' ? 'Template' : 'Data';
    box.appendChild(button('tpl' + cap + 'Choose', slot === 'template' ? 'Choose template\u2026' : 'Choose data\u2026', 'primary',
      () => D.$(slot === 'template' ? 'tplTemplatePick' : 'tplDataPick').click()));
    box.appendChild(el('p', 'note', hint));
    if (!window.SERVER_MODE) {
      const row = el('div', 'tpl-path');
      const input = el('input', 'field');
      input.id = 'tpl' + cap + 'Path';
      input.type = 'text';
      input.spellcheck = false;
      input.autocomplete = 'off';
      input.placeholder = slot === 'template' ? '/path/to/template.twbx' : '/path/to/data.csv';
      input.setAttribute('aria-label', (slot === 'template' ? 'Template' : 'Data') + ' file path');
      const go = button('tpl' + cap + 'Open', 'Open', '', () => openPath(slot, input.value));
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go.click(); });
      row.append(input, go);
      box.appendChild(row);
    }
    return box;
  }

  function fileLine(slot, name) {
    const line = el('div', 'tpl-line');
    line.appendChild(el('strong', 'tpl-file', name));
    const change = button('', 'Change', 'small tpl-change', () => { S.changing[slot] = true; render(); focusHeading(slot === 'template' ? 1 : 2); });
    change.setAttribute('aria-label', 'Change the ' + (slot === 'template' ? 'template' : 'data') + ' file, ' + name);
    line.appendChild(change);
    return line;
  }

  function keepButton(slot) {
    return button('', 'Keep the one I have', 'small tpl-keep', () => { S.changing[slot] = false; render(); });
  }

  function busyBody(body, name) {
    const p = el('p', 'tpl-busy', 'Reading ' + name + ' \u2026');
    body.appendChild(p);
  }

  function renderTemplate() {
    const t = S.template;
    const state = S.busy.template ? 'busy' : (t && !S.changing.template ? 'done' : 'todo');
    const body = setCard(1, state === 'busy' ? 'todo' : state);
    if (S.busy.template) { busyBody(body, S.busy.template); return; }
    if (!t || S.changing.template) {
      body.appendChild(chooser('template', 'a template', 'A template is a .twbx file made with py-tbparse template make.'));
      if (t) body.appendChild(keepButton('template'));
      return;
    }
    body.appendChild(fileLine('template', t.label));
    body.appendChild(el('p', 'tpl-name', t.name));
    if (t.revision !== null && t.revision !== undefined) body.appendChild(el('p', 'tpl-rev', 'Revision ' + t.revision));
    if (t.description) body.appendChild(el('p', 'tpl-desc', t.description));
    const required = (t.datasources || []).reduce((n, d) => n + d.required, 0);
    body.appendChild(el('p', 'tpl-counts', D.plural(required, 'required field') + ', ' +
      D.plural((t.parameters || []).length, 'parameter') + ', ' + D.plural((t.tokens || []).length, 'token')));
    const several = (t.datasources || []).filter((d) => d.required > 0);
    if (several.length > 1) body.appendChild(datasourcePicker(several));
    body.appendChild(findings(t.findings || []));
  }

  function datasourcePicker(list) {
    const wrap = el('div', 'tpl-pick');
    const label = el('label', '', 'This template has several data sources. Which one gets the new data? ');
    label.htmlFor = 'tplTplDsSel';
    const sel = el('select', 'field');
    sel.id = 'tplTplDsSel';
    list.forEach((d) => {
      const o = el('option', '', (d.caption || d.name) + ' (' + D.plural(d.required, 'required field') + ')');
      o.value = d.name;
      sel.appendChild(o);
    });
    if (!S.tplDs) S.tplDs = list[0].name;
    sel.value = S.tplDs;
    sel.addEventListener('change', () => { S.tplDs = sel.value; S.gen += 1; renderReview(); });
    wrap.append(label, sel);
    return wrap;
  }

  function findings(all, opts) {
    opts = opts || {};
    const titleId = opts.titleId || 'tplCheckTitle', moreId = opts.moreId || 'tplMore', redraw = opts.redraw || renderTemplate;
    const box = el('div', 'tpl-check');
    const counts = {error: 0, warning: 0, info: 0};
    all.forEach((f) => { if (f.severity in counts) counts[f.severity] += 1; });
    const title = el('h3', 'tpl-sub');
    title.id = titleId;
    if (!all.length) {
      title.textContent = 'Template check';
      box.append(title, el('p', 'tpl-ok', 'The template check found nothing to fix.'));
      return box;
    }
    const parts = [];
    if (counts.error) parts.push(D.plural(counts.error, 'problem'));
    if (counts.warning) parts.push(counts.warning + (counts.warning === 1 ? ' needs' : ' need') + ' a look');
    if (counts.info) parts.push(counts.info + ' worth knowing');
    title.textContent = 'Template check: ' + parts.join(', ');
    box.appendChild(title);
    const sorted = [];
    SEVERITIES.forEach((s) => { all.forEach((f) => { if (f.severity === s[0]) sorted.push(f); }); });
    const limit = Math.min(S.shown, SHOW_MAX, sorted.length);
    const list = el('ul', 'health tpl-findings');
    list.setAttribute('aria-labelledby', titleId);
    sorted.slice(0, limit).forEach((f) => list.appendChild(findingItem(f)));
    box.appendChild(list);
    if (limit < sorted.length) {
      if (limit < SHOW_MAX) {
        const more = Math.min(SHOW_STEP, sorted.length - limit, SHOW_MAX - limit);
        box.appendChild(button(moreId, 'Show ' + more + ' more', 'small', () => { S.shown = limit + SHOW_STEP; redraw(); D.$(moreId) && D.$(moreId).focus(); }));
        box.appendChild(el('span', 'note', ' Showing ' + limit + ' of ' + sorted.length + '.'));
      } else {
        box.appendChild(el('p', 'note', 'Showing the first ' + SHOW_MAX + ' of ' + sorted.length + '. Run py-tbparse template check on the file for the whole list.'));
      }
    }
    return box;
  }

  function findingItem(f) {
    const sev = SEVERITIES.find((s) => s[0] === f.severity) || SEVERITIES[2];
    const li = el('li', 'health-item ' + sev[3]);
    const icon = el('span', 'sev', sev[1]);
    icon.setAttribute('aria-hidden', 'true');
    const text = el('div', 'health-text');
    text.append(el('span', 'sr-only', sev[2] + ': '), el('strong', '', f.detail || f.rule || 'Check'));
    const more = [];
    if (f.object) more.push('In: ' + f.object);
    if (f.fix) more.push('To fix: ' + f.fix);
    if (f.rule) more.push('Check ' + f.rule);
    if (more.length) text.appendChild(el('span', 'health-detail', more.join('. ')));
    li.append(icon, text);
    return li;
  }

  function kindWords(d) {
    if (d.kind === 'csv') return 'Text file (CSV)';
    if (d.kind === 'excel') return 'Excel sheet' + (d.sheet ? ' ' + d.sheet : '');
    if (d.kind === 'tableau') return 'Tableau data';
    return 'Data';
  }

  function picker(kind, list, current, label, useId, selId, onPick) {
    const wrap = el('div', 'tpl-pick');
    const lab = el('label', '', label + ' ');
    lab.htmlFor = selId;
    const sel = el('select', 'field');
    sel.id = selId;
    if (!current) {
      const o = el('option', '', 'Choose one\u2026');
      o.value = '';
      sel.appendChild(o);
    }
    list.forEach((name) => { const o = el('option', '', name); o.value = name; sel.appendChild(o); });
    sel.value = current || '';
    sel.addEventListener('change', () => onPick(sel.value));
    wrap.append(lab, sel, button(useId, kind === 'sheet' ? 'Use this sheet' : 'Use this data source', '', () => useChoice(kind)));
    return wrap;
  }

  function renderData() {
    if (!ready()) { setCard(2, 'locked', 'Choose a template first.'); return; }
    const d = S.data;
    const several = pending() || (d && ((S.sheets && S.sheets.length > 1) || (S.datasources && S.datasources.length > 1)));
    const state = d && !S.changing.data ? 'done' : 'todo';
    const body = setCard(2, state);
    if (S.busy.data) { busyBody(body, S.busy.data); return; }
    const hasFile = d || several;
    if (!hasFile || S.changing.data) {
      body.appendChild(chooser('data', 'your new data', 'A .csv, .tsv, .txt or Excel file, or a Tableau .twb, .twbx or .tds. Database files are not supported here yet.'));
      if (hasFile) body.appendChild(keepButton('data'));
      return;
    }
    body.appendChild(fileLine('data', S.dataName || (d && d.label) || 'your file'));
    if (S.sheets && S.sheets.length > 1) {
      body.appendChild(picker('sheet', S.sheets, S.sheetPick, 'This file has several sheets. Which one holds the data?',
        'tplSheetUse', 'tplSheetSel', (v) => { S.sheetPick = v; }));
    }
    if (S.datasources && S.datasources.length > 1) {
      body.appendChild(picker('datasource', S.datasources, S.dsPick, 'This file has several data sources. Which one holds the data?',
        'tplDsUse', 'tplDsSel', (v) => { S.dsPick = v; }));
    }
    if (!d) {
      body.appendChild(el('p', 'note', 'Choose one to go on.'));
      return;
    }
    body.appendChild(el('p', 'tpl-kind', kindWords(d)));
    body.appendChild(el('p', 'tpl-counts', D.plural(d.columns.length, 'column')));
    body.appendChild(columnList(d.columns));
    if (d.kind === 'csv' || d.kind === 'excel') body.appendChild(placeField());
  }

  function columnList(cols) {
    const det = el('details', 'tpl-cols');
    det.appendChild(el('summary', '', 'Show the columns'));
    const ul = el('ul', 'tpl-collist');
    cols.slice(0, COLUMN_CAP).forEach((c) => {
      const li = el('li', '', c.name);
      li.appendChild(el('small', 'tpl-type', ' ' + c.datatype));
      ul.appendChild(li);
    });
    det.appendChild(ul);
    if (cols.length > COLUMN_CAP) det.appendChild(el('p', 'note', 'and ' + (cols.length - COLUMN_CAP) + ' more, not listed here.'));
    return det;
  }

  function placeField() {
    const wrap = el('div', 'tpl-place');
    const label = el('label', '', 'Where will this file be on your computer? (optional)');
    label.htmlFor = 'tplDataPlace';
    const input = el('input', 'field');
    input.id = 'tplDataPlace';
    input.type = 'text';
    input.spellcheck = false;
    input.autocomplete = 'off';
    input.placeholder = 'C:\\Users\\me\\Documents or /home/me/data';
    input.value = S.place;
    input.setAttribute('aria-describedby', 'tplPlaceNote');
    input.addEventListener('input', () => { S.place = input.value; });
    const note = el('p', 'note', 'The workbook remembers where its data file is. If you leave this empty, it only knows the file name, and Tableau will ask where the file is when you open the workbook.');
    note.id = 'tplPlaceNote';
    wrap.append(label, input, note);
    return wrap;
  }

  // ---- step 3: match the fields, review, create --------------------------------------------------------

  const setShown = (node, on) => { node.hidden = !on; };
  const bare = (name) => String(name || '').replace(/^\[|\]$/g, '');
  const capOf = (row) => bare(row.caption || row.field);

  // A parameter or allowed value as a person reads it: Tableau writes text in quotes and dates between #.
  function plainValue(literal) {
    if (literal === null || literal === undefined) return '';
    const text = String(literal), q = String.fromCharCode(34), n = text.length;
    if (n >= 2 && text.charAt(0) === q && text.charAt(n - 1) === q) return text.slice(1, -1).split(q + q).join(q);
    if (n >= 2 && text.charAt(0) === '#' && text.charAt(n - 1) === '#') return text.slice(1, -1);
    return text;
  }

  function mappedNow() {
    const now = {};
    if (S.rv.plan) S.rv.plan.mapping.rows.forEach((r) => { now[r.field] = r.mapped_to || ''; });
    Object.keys(S.rv.edits).forEach((f) => { now[f] = S.rv.edits[f]; });
    return now;
  }

  function choiceStatus(row, col) {
    const list = (S.rv.plan && S.rv.plan.choices[row.datatype]) || [];
    for (let i = 0; i < list.length; i++) if (list[i].column === col) return list[i].status;
    return 'ok';
  }

  // [kind, words] for the status column: a mark and words, never colour alone.
  function statusOf(row, now) {
    const col = now[row.field] || '';
    const edited = Object.prototype.hasOwnProperty.call(S.rv.edits, row.field);
    const raw = edited ? (col ? 'chosen' : 'unmapped') : (row.status || '');
    if (!col) {
      if (/^type mismatch/.test(raw)) return ['bad', 'No column: the one with this name has a different type'];
      if (/^column /.test(raw)) return [row.required ? 'bad' : 'none', raw.charAt(0).toUpperCase() + raw.slice(1)];
      return row.required ? ['bad', 'Missing: this field needs a column'] : ['none', 'No column (the template does not need one)'];
    }
    if (raw === 'matched') return ['ok', 'Matched by name'];
    if (raw === 'close match') return ['warn', 'Close match, please check'];
    if (raw === 'numeric type differs') return ['warn', 'Number type differs (will convert)'];
    if (raw === 'date type differs') return ['warn', 'Date type differs (will convert)'];
    if (raw === 'role differs') return ['warn', 'Dimension or measure differs'];
    if (raw === 'chosen') {
      const fit = choiceStatus(row, col);
      if (fit === 'numeric-differs') return ['warn', 'You chose this. Number type differs (will convert)'];
      if (fit === 'date-differs') return ['warn', 'You chose this. Date type differs (will convert)'];
      if (fit === 'mismatch') return ['bad', 'You chose this. Different type, it may not work'];
      return ['ok', 'You chose this'];
    }
    return ['none', raw];
  }

  const MARKS = {ok: '✔', warn: '▲', bad: '✖', none: '•'};

  function choose(row, col) {
    const now = mappedNow();
    if (col) {
      Object.keys(now).forEach((f) => { if (f !== row.field && now[f] === col) S.rv.edits[f] = ''; });
    }
    S.rv.edits[row.field] = col;
    updateMapping();
    edited();
  }

  function edited() {
    S.rv.created = null;
    S.rv.saved = '';
    S.rv.dirty = true;
    updateCreate();
    updatePlanText();
    requestPlan(PLAN_DELAY);
  }

  // ---- asking for a plan ------------------------------------------------------------------------

  function planPayload() {
    const rv = S.rv, body = {};
    if (S.tplDs) body.datasource = S.tplDs;
    if (Object.keys(rv.edits).length) body.mapping = rv.edits;
    if (Object.keys(rv.params).length) body.params = rv.params;
    if (Object.keys(rv.tokens).length) body.tokens = rv.tokens;
    return body;
  }

  function requestPlan(delay) {
    clearTimeout(planTimer);
    planTimer = setTimeout(askPlan, delay);
  }

  async function askPlan() {
    if (!R) return;
    if (planCtl) planCtl.abort();
    planCtl = new AbortController();
    const mine = ++planSeq;
    const body = planPayload();
    if (S.rv.allowMissing) body.allow_missing = true;
    try {
      const answer = await D.fetchJSON('/template/plan', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body), signal: planCtl.signal});
      if (mine !== planSeq || !R) return;
      S.rv.plan = answer;
      S.rv.planError = '';
      S.rv.dirty = false;
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      if (mine !== planSeq || !R) return;
      S.rv.planError = e.message;
      S.rv.dirty = false;
    }
    updateReview();
  }

  // ---- building step 3 -------------------------------------------------------------------------

  function reviewKey() { return S.gen + '|' + S.tplDs; }

  function renderReview() {
    if (!ready() || !chosen()) {
      R = null;
      clearTimeout(planTimer);
      if (planCtl) planCtl.abort();
      setCard(3, 'locked', !ready() ? 'Choose a template and your data first.' : 'Choose your data first.');
      return;
    }
    if (R && R.key === reviewKey()) return;
    S.rv = freshReview();
    const body = setCard(3, 'todo');
    R = {key: reviewKey(), rows: new Map(), drawn: '', groups: {}};
    body.appendChild(el('p', 'tpl-lead', S.template.name + ' with ' + S.dataName));
    body.appendChild(buildMatch());
    if ((S.template.parameters || []).length) body.appendChild(buildParams());
    if ((S.template.tokens || []).length) body.appendChild(buildTokens());
    body.appendChild(buildPlanPanel());
    body.appendChild(buildCreate());
    updateReview();
    requestPlan(0);
  }

  function updateReview() {
    updateMapping();
    updateParamErrors();
    updatePlanPanel();
    updatePlanText();
    updateCreate();
  }

  function buildMatch() {
    const box = el('section', 'tpl-sec');
    box.setAttribute('aria-labelledby', 'tplMatchTitle');
    const title = el('h3', 'tpl-sub', 'Match the fields to your columns');
    title.id = 'tplMatchTitle';
    const note = el('p', 'note', 'Each field the template uses needs one of your columns. I matched what I could by name. Change any of them here.');
    const tools = el('div', 'tpl-tools');
    const filter = el('input', 'field');
    filter.type = 'search';
    filter.id = 'tplFilter';
    filter.placeholder = 'Find a field or column';
    filter.autocomplete = 'off';
    filter.setAttribute('aria-label', 'Find a field or column');
    filter.addEventListener('input', () => { S.rv.filter = filter.value; S.rv.rowsShown = ROW_PAGE; updateMapping(); });
    const optLabel = el('label', 'tpl-check-opt');
    const opt = el('input');
    opt.type = 'checkbox';
    opt.id = 'tplOptional';
    opt.addEventListener('change', () => { S.rv.optional = opt.checked; S.rv.rowsShown = ROW_PAGE; updateMapping(); });
    const optText = el('span', '', 'Show optional fields');
    optText.id = 'tplOptionalText';
    optLabel.append(opt, optText);
    tools.append(filter, optLabel);
    const count = el('p', 'note tpl-count', '');
    count.id = 'tplMapCount';
    const table = el('table', 'tpl-map');
    table.id = 'tplMap';
    const cap = el('caption', 'sr-only', 'Template fields and the column chosen for each');
    const head = el('thead');
    const tr = el('tr');
    ['Field', 'Type', 'Used by', 'Your column', 'How it matched'].forEach((h) => {
      const th = el('th', '', h);
      th.scope = 'col';
      tr.appendChild(th);
    });
    head.appendChild(tr);
    const tbody = el('tbody');
    tbody.id = 'tplMapBody';
    table.append(cap, head, tbody);
    const more = el('div', 'tpl-more');
    const moreBtn = button('tplMapMore', '', 'small', () => { S.rv.rowsShown += ROW_PAGE; updateMapping(); });
    more.appendChild(moreBtn);
    const loading = el('p', 'tpl-busy', 'Matching the fields …');
    loading.id = 'tplMapLoading';
    box.append(title, note, tools, count, loading, table, more);
    Object.assign(R, {filter: filter, optional: opt, optionalText: optText, count: count, tbody: tbody, table: table,
      more: more, moreBtn: moreBtn, loading: loading});
    return box;
  }

  function makeRow(field) {
    const tr = el('tr', 'tpl-row');
    tr.dataset.field = field;
    const rec = {tr: tr, field: field, filled: false};
    const cells = {};
    ['name', 'type', 'used', 'col', 'status'].forEach((k, i) => {
      const td = el('td', 'tpl-c-' + k);
      td.dataset.label = ['Field', 'Type', 'Used by', 'Your column', 'How it matched'][i];
      cells[k] = td;
      tr.appendChild(td);
    });
    const sel = el('select', 'field tpl-sel');
    sel.setAttribute('aria-label', 'Column for the field');
    const all = el('input');
    all.type = 'checkbox';
    const allLabel = el('label', 'tpl-showall');
    allLabel.append(all, el('span', '', 'Show all columns'));
    cells.col.append(sel, allLabel);
    sel.addEventListener('focus', () => fillOptions(rec));
    sel.addEventListener('pointerdown', () => fillOptions(rec));
    sel.addEventListener('blur', () => { rec.filled = false; setCurrent(rec); });
    sel.addEventListener('change', () => choose(rec.row, sel.value));
    all.addEventListener('change', () => { S.rv.showAll[field] = all.checked; if (rec.filled) { rec.filled = false; fillOptions(rec); } });
    Object.assign(rec, {cells: cells, sel: sel, all: all, allLabel: allLabel});
    return rec;
  }

  // A closed dropdown holds only the chosen column, so 2000 fields do not mean 2000 times 2000 options.
  function setCurrent(rec) {
    const col = mappedNow()[rec.field] || '';
    const sel = rec.sel;
    if (rec.filled) { if (sel.value !== col) sel.value = col; return; }
    sel.textContent = '';
    const o = el('option', '', col || 'No column');
    o.value = col;
    sel.appendChild(o);
    sel.value = col;
  }

  function fillOptions(rec) {
    if (rec.filled || !S.rv.plan || !rec.row) return;
    rec.filled = true;
    const sel = rec.sel, now = mappedNow(), row = rec.row, current = now[row.field] || '';
    const usedBy = {};
    S.rv.plan.mapping.rows.forEach((r) => { const c = now[r.field]; if (c && r.field !== row.field) usedBy[c] = capOf(r); });
    sel.textContent = '';
    const none = el('option', '', 'No column');
    none.value = '';
    sel.appendChild(none);
    const groups = [['Same type', 'ok'], ['Different type (will convert)', 'differs'], ['Other types (may not work)', 'mismatch']];
    const wanted = S.rv.showAll[row.field];
    const list = S.rv.plan.choices[row.datatype] || [];
    let added = 0, left = 0;
    groups.forEach((g) => {
      const members = list.filter((c) => {
        const kind = c.status === 'ok' ? 'ok' : (c.status === 'mismatch' ? 'mismatch' : 'differs');
        return kind === g[1] && (g[1] !== 'mismatch' || wanted || c.column === current);
      });
      if (!members.length) return;
      const og = el('optgroup');
      og.label = g[0];
      members.forEach((c) => {
        if (added >= OPTION_CAP && c.column !== current) { left += 1; return; }
        const text = c.column + ' (' + c.datatype + ')' + (usedBy[c.column] ? ' (used by ' + usedBy[c.column] + ')' : '');
        const o = el('option', '', text);
        o.value = c.column;
        og.appendChild(o);
        added += 1;
      });
      sel.appendChild(og);
    });
    if (left) {
      const o = el('option', '', 'and ' + left + ' more columns, not listed');
      o.disabled = true;
      sel.appendChild(o);
    }
    sel.value = current;
    if (sel.value !== current) {
      const o = el('option', '', current);
      o.value = current;
      sel.appendChild(o);
      sel.value = current;
    }
  }

  function updateRow(rec, row, now) {
    rec.row = row;
    const c = rec.cells;
    const label = capOf(row);
    c.name.textContent = '';
    c.name.appendChild(el('strong', '', label));
    if (bare(row.field) !== label) c.name.appendChild(el('small', 'tpl-local', ' ' + bare(row.field)));
    if (row.required) c.name.appendChild(el('span', 'tpl-req', 'Required'));
    c.type.textContent = row.datatype || '';
    const used = row.used_by || '';
    c.used.textContent = used.length > 60 ? used.slice(0, 57) + '…' : used;
    if (used.length > 60) c.used.title = used; else c.used.removeAttribute('title');
    rec.sel.setAttribute('aria-label', 'Column for ' + label);
    rec.allLabel.hidden = !(S.rv.plan.choices[row.datatype] || []).some((x) => x.status === 'mismatch');
    rec.all.checked = !!S.rv.showAll[row.field];
    setCurrent(rec);
    const st = statusOf(row, now);
    c.status.textContent = '';
    c.status.className = 'tpl-c-status st-' + st[0];
    const mark = el('span', 'st-mark', MARKS[st[0]]);
    mark.setAttribute('aria-hidden', 'true');
    c.status.append(mark, el('span', '', st[1]));
  }

  function updateMapping() {
    if (!R) return;
    const plan = S.rv.plan;
    setShown(R.loading, !plan && !S.rv.planError);
    setShown(R.table, !!plan);
    if (!plan) { R.count.textContent = ''; setShown(R.more, false); return; }
    const now = mappedNow();
    const rows = plan.mapping.rows;
    const optionalCount = rows.filter((r) => !r.required).length;
    R.optionalText.textContent = optionalCount ? 'Show ' + D.plural(optionalCount, 'optional field') : 'No optional fields';
    R.optional.disabled = !optionalCount;
    const q = S.rv.filter.trim().toLowerCase();
    const visible = rows.filter((r) => {
      if (q) return (capOf(r) + ' ' + bare(r.field) + ' ' + (now[r.field] || '')).toLowerCase().indexOf(q) >= 0;
      return r.required || S.rv.optional;
    });
    const drawn = visible.slice(0, S.rv.rowsShown);
    const key = drawn.map((r) => r.field).join('\u0001');
    drawn.forEach((r) => {
      let rec = R.rows.get(r.field);
      if (!rec) { rec = makeRow(r.field); R.rows.set(r.field, rec); }
      updateRow(rec, r, now);
    });
    if (key !== R.drawn) {
      R.drawn = key;
      const active = document.activeElement;
      const keep = active && R.tbody.contains(active) ? active : null;
      R.tbody.textContent = '';
      drawn.forEach((r) => R.tbody.appendChild(R.rows.get(r.field).tr));
      if (keep && R.tbody.contains(keep)) keep.focus();
      // rows that are no longer drawn are forgotten, so the cache cannot grow past what was seen
      R.rows.forEach((rec, f) => { if (!rec.tr.isConnected) R.rows.delete(f); });
    }
    const required = rows.length - optionalCount;
    let words = visible.length === 0 ? (q ? 'No field matches that.' : 'No fields to show.')
      : 'Showing ' + drawn.length + ' of ' + D.plural(visible.length, 'field') + ' (' + required + ' required).';
    if (plan.mapping.truncated) words += ' The template has ' + plan.mapping.truncated + ' more fields, not shown here.';
    R.count.textContent = words;
    const left = visible.length - drawn.length;
    setShown(R.more, left > 0);
    if (left > 0) R.moreBtn.textContent = 'Show ' + Math.min(ROW_PAGE, left) + ' more';
  }

  // ---- parameters and tokens -------------------------------------------------------------------

  function buildParams() {
    const box = el('section', 'tpl-sec');
    box.setAttribute('aria-labelledby', 'tplParamTitle');
    const title = el('h3', 'tpl-sub', 'Parameters');
    title.id = 'tplParamTitle';
    box.append(title, el('p', 'note', 'Leave one empty to keep the value the template has.'));
    R.paramErr = {};
    (S.template.parameters || []).forEach((p, i) => {
      const row = el('div', 'tpl-in');
      const id = 'tplParam' + i;
      const label = el('label', '', p.caption);
      label.htmlFor = id;
      const type = p.datatype;
      const allowed = (p.allowed_values || []).map(plainValue);
      let input;
      if (allowed.length || type === 'boolean') {
        input = el('select', 'field');
        const first = el('option', '', 'Keep ' + (plainValue(p.value) || 'the default'));
        first.value = '';
        input.appendChild(first);
        (allowed.length ? allowed : ['true', 'false']).forEach((v) => { const o = el('option', '', v); o.value = v; input.appendChild(o); });
      } else {
        input = el('input', 'field');
        if (type === 'integer') { input.type = 'number'; input.step = '1'; }
        else if (type === 'real') { input.type = 'number'; input.step = 'any'; }
        else if (type === 'date') input.type = 'date';
        else if (type === 'datetime') input.type = 'datetime-local';
        else input.type = 'text';
        input.placeholder = plainValue(p.value);
        input.autocomplete = 'off';
      }
      input.id = id;
      const hint = el('span', 'note', 'Template value: ' + (plainValue(p.value) || 'empty'));
      hint.id = id + 'Hint';
      const err = el('p', 'tpl-err', '');
      err.id = id + 'Err';
      err.hidden = true;
      input.setAttribute('aria-describedby', hint.id + ' ' + err.id);
      const onEdit = () => {
        if (input.value === '') delete S.rv.params[p.caption]; else S.rv.params[p.caption] = input.value;
        edited();
      };
      input.addEventListener('input', onEdit);
      input.addEventListener('change', onEdit);
      const reset = button('tplParamReset' + i, 'Reset', 'small', () => { input.value = ''; onEdit(); input.focus(); });
      reset.setAttribute('aria-label', 'Reset ' + p.caption + ' to the template value');
      const line = el('div', 'tpl-in-line');
      line.append(input, reset);
      row.append(label, line, hint, err);
      box.appendChild(row);
      R.paramErr[p.caption] = {input: input, err: err};
    });
    return box;
  }

  function buildTokens() {
    const box = el('section', 'tpl-sec');
    box.setAttribute('aria-labelledby', 'tplTokenTitle');
    const title = el('h3', 'tpl-sub', 'Text to fill in');
    title.id = 'tplTokenTitle';
    box.append(title, el('p', 'note', 'The template has places for your own words, such as a title. Fill in each one.'));
    R.tokenErr = {};
    (S.template.tokens || []).forEach((t, i) => {
      const row = el('div', 'tpl-in');
      const id = 'tplToken' + i;
      const needed = t.default === null || t.default === undefined;
      const label = el('label', '', t.token + (needed ? ' (needed)' : ''));
      label.htmlFor = id;
      const input = el('input', 'field');
      input.type = 'text';
      input.id = id;
      input.autocomplete = 'off';
      input.placeholder = needed ? '' : String(t.default);
      const hint = el('span', 'note', (t.where ? 'Used in: ' + t.where + '. ' : '') + (needed ? 'No default.' : 'Empty keeps: ' + t.default));
      hint.id = id + 'Hint';
      const err = el('p', 'tpl-err', '');
      err.id = id + 'Err';
      err.hidden = true;
      input.setAttribute('aria-describedby', hint.id + ' ' + err.id);
      input.addEventListener('input', () => {
        if (input.value === '') delete S.rv.tokens[t.token]; else S.rv.tokens[t.token] = input.value;
        edited();
      });
      row.append(label, input, hint, err);
      box.appendChild(row);
      R.tokenErr[t.token] = {input: input, err: err};
    });
    return box;
  }

  function showError(pair, message) {
    pair.err.hidden = !message;
    pair.err.textContent = message || '';
    if (message) pair.input.setAttribute('aria-invalid', 'true'); else pair.input.removeAttribute('aria-invalid');
  }

  function updateParamErrors() {
    if (!R || !S.rv.plan) return;
    (S.rv.plan.params || []).forEach((p) => { if (R.paramErr && R.paramErr[p.parameter]) showError(R.paramErr[p.parameter], p.error); });
    (S.rv.plan.tokens || []).forEach((t) => { if (R.tokenErr && R.tokenErr[t.token]) showError(R.tokenErr[t.token], t.error); });
  }

  // ---- the plan panel ------------------------------------------------------------------------------

  const GROUPS = [
    ['problems', 'Problems to fix'],
    ['broken', 'What would break'],
    ['explain', 'What will change'],
    ['check', 'Checks on your data'],
  ];

  function buildPlanPanel() {
    const box = el('section', 'tpl-sec');
    box.setAttribute('aria-labelledby', 'tplPlanTitle');
    const title = el('h3', 'tpl-sub', 'Check before you create');
    title.id = 'tplPlanTitle';
    const live = el('p', 'tpl-live', 'Checking …');
    live.id = 'tplPlanLive';
    live.setAttribute('role', 'status');
    box.append(title, live);
    R.live = live;
    GROUPS.forEach((g) => {
      const det = el('details', 'tpl-group');
      det.id = 'tplGroup-' + g[0];
      const sum = el('summary', '', g[1]);
      const inner = el('div', 'tpl-group-body');
      det.append(sum, inner);
      box.appendChild(det);
      R.groups[g[0]] = {det: det, sum: sum, body: inner, opened: false};
    });
    return box;
  }

  function planItem(kind, title, sub) {
    const sev = SEVERITIES.find((s) => s[0] === kind) || SEVERITIES[2];
    const li = el('li', 'health-item ' + sev[3]);
    const icon = el('span', 'sev', sev[1]);
    icon.setAttribute('aria-hidden', 'true');
    const text = el('div', 'health-text');
    text.append(el('span', 'sr-only', sev[2] + ': '), el('strong', '', title));
    if (sub) text.appendChild(el('span', 'health-detail', sub));
    li.append(icon, text);
    return li;
  }

  function brokenItem(r) {
    const parts = [];
    [['sheets', 'Sheets'], ['dashboards', 'Dashboards'], ['calculations', 'Calculations'], ['filters', 'Filters']].forEach((k) => {
      if (r[k[0]]) parts.push(k[1] + ': ' + r[k[0]]);
    });
    return planItem('error', capOf(r) + ' has no column', parts.join('. '));
  }

  function explainItem(r) {
    return planItem(r.severity, r.detail || r.change || 'Change', [r.kind, r.object].filter(Boolean).join(': '));
  }

  function checkItem(r) {
    const parts = [];
    if (r.field) parts.push('Field: ' + bare(r.field));
    if (r.column) parts.push('Column: ' + r.column);
    return planItem(r.severity, r.detail || r.check || 'Check', parts.join('. '));
  }

  function csvText(rows, columns) {
    const quote = String.fromCharCode(34), apos = String.fromCharCode(39);
    const cell = (v) => {
      let t = v === null || v === undefined ? '' : String(v);
      if (/^[=+\-@\t\r]/.test(t)) t = apos + t;   // a spreadsheet must not run a cell as a formula
      return quote + t.split(quote).join(quote + quote) + quote;
    };
    return [columns.map(cell).join(',')].concat(rows.map((r) => columns.map((c) => cell(r[c])).join(','))).join('\r\n') + '\r\n';
  }

  function downloadCsv(name, rows, columns) {
    const url = URL.createObjectURL(new Blob([csvText(rows, columns)], {type: 'text/csv'}));
    const a = el('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function fillGroup(key, items, rows, columns, made) {
    const g = R.groups[key];
    const word = GROUPS.find((x) => x[0] === key)[1];
    const total = key === 'problems' ? items.length : (rows ? rows.total : 0);
    g.sum.textContent = word + ' (' + total + ')';
    g.det.dataset.count = String(total);
    if (!g.opened && key === 'problems' && total) { g.det.open = true; g.opened = true; }
    const hadFocus = g.body.contains(document.activeElement) ? document.activeElement.id : '';
    g.body.textContent = '';
    if (!items.length) {
      g.body.appendChild(el('p', 'note', key === 'problems' ? 'Nothing is in the way.' : 'Nothing to show.'));
      return;
    }
    const limit = Math.min(S.rv.groupShown[key] || GROUP_STEP, GROUP_MAX, items.length);
    const list = el('ul', 'health tpl-findings');
    items.slice(0, limit).forEach((it) => list.appendChild(made ? made(it) : planItem('error', it, '')));
    g.body.appendChild(list);
    if (limit < items.length) {
      if (limit < GROUP_MAX) {
        const more = button('tplMore-' + key, 'Show ' + Math.min(GROUP_STEP, items.length - limit) + ' more', 'small', () => {
          S.rv.groupShown[key] = limit + GROUP_STEP;
          fillGroup(key, items, rows, columns, made);
          const again = D.$('tplMore-' + key);
          if (again) again.focus();
        });
        g.body.append(more, el('span', 'note', ' Showing ' + limit + ' of ' + items.length + '.'));
      } else {
        g.body.appendChild(el('p', 'note', 'Showing the first ' + GROUP_MAX + ' of ' + items.length + '. Download the list for the rest.'));
      }
    }
    if (rows && rows.truncated) g.body.appendChild(el('p', 'note', 'and ' + rows.truncated + ' more not shown.'));
    if (rows && columns && items.length > GROUP_STEP) {
      g.body.appendChild(button('tplCsv-' + key, 'Download as CSV', 'small', () => downloadCsv(key + '.csv', items, columns)));
    }
    if (hadFocus && D.$(hadFocus)) D.$(hadFocus).focus();
  }

  function updatePlanPanel() {
    if (!R) return;
    const plan = S.rv.plan;
    const problems = (plan ? plan.problems : []).slice();
    if (S.rv.planError) problems.unshift(S.rv.planError);
    fillGroup('problems', problems, null, null, (m) => planItem('error', m, ''));
    if (!plan) return;
    fillGroup('broken', plan.broken.rows, plan.broken, ['field', 'caption', 'sheets', 'dashboards', 'calculations', 'filters'], brokenItem);
    fillGroup('explain', plan.explain.rows, plan.explain, ['change', 'severity', 'kind', 'object', 'detail'], explainItem);
    fillGroup('check', plan.check.rows, plan.check, ['check', 'severity', 'field', 'column', 'detail'], checkItem);
  }

  function updatePlanText() {
    if (!R) return;
    const plan = S.rv.plan;
    let words;
    if (S.rv.planError) words = 'I could not check this. See the problems below.';
    else if (!plan || S.rv.dirty) words = 'Checking …';
    else if (plan.ready) words = 'Ready to create.';
    else words = D.plural(plan.problems.length, 'problem') + ' to fix before you can create the workbook.';
    if (R.live.textContent !== words) R.live.textContent = words;
  }

  // ---- create ----------------------------------------------------------------------------------------

  function buildCreate() {
    const box = el('section', 'tpl-sec tpl-create');
    box.setAttribute('aria-labelledby', 'tplCreateTitle');
    const title = el('h3', 'tpl-sub', 'Create the workbook');
    title.id = 'tplCreateTitle';
    const anyLabel = el('label', 'tpl-check-opt');
    const any = el('input');
    any.type = 'checkbox';
    any.id = 'tplAllowMissing';
    const anyText = el('span', '', '');
    anyText.id = 'tplAllowText';
    anyLabel.append(any, anyText);
    anyLabel.hidden = true;
    any.addEventListener('change', () => { S.rv.allowMissing = any.checked; edited(); });
    const row = el('div', 'tpl-actions');
    const create = button('tplCreate', 'Create workbook', 'primary', () => create_('apply'));
    create.setAttribute('aria-describedby', 'tplCreateWhy');
    row.appendChild(create);
    let save = null;
    if (!window.SERVER_MODE) {
      save = button('tplSave', 'Save beside the template', '', () => create_('save'));
      save.setAttribute('aria-describedby', 'tplCreateWhy');
      row.appendChild(save);
    }
    const why = el('p', 'note', '');
    why.id = 'tplCreateWhy';
    const done = el('div', 'tpl-done');
    done.id = 'tplDone';
    box.append(title, anyLabel, row, why, done);
    Object.assign(R, {any: any, anyLabel: anyLabel, anyText: anyText, create: create, save: save, why: why, done: done});
    return box;
  }

  function updateCreate() {
    if (!R || !R.create) return;
    const rv = S.rv, plan = rv.plan;
    const missing = plan ? plan.missing_required : [];
    R.anyLabel.hidden = !missing.length;
    if (missing.length) {
      const shown = missing.slice(0, 3).join(', ') + (missing.length > 3 ? ' and ' + (missing.length - 3) + ' more' : '');
      R.anyText.textContent = 'Create anyway. ' + D.plural(missing.length, 'field') + ' with no column (' + shown + ') will stay broken.';
    }
    R.any.checked = rv.allowMissing;
    let why = '';
    if (rv.working) why = rv.working;
    else if (rv.planError) why = 'Fix what the problems list says first.';
    else if (!plan || rv.dirty) why = 'Checking your changes …';
    else if (!plan.ready) why = 'Fix the problems above first' + (missing.length && !rv.allowMissing ? ', or tick Create anyway.' : '.');
    const blocked = !!why;
    [R.create, R.save].forEach((b) => { if (b) b.disabled = blocked; });
    R.why.textContent = why;
    R.done.textContent = '';
    if (rv.created) {
      const line = el('p', 'tpl-ok', 'Created ' + rv.created.name + ' (' + Math.max(1, Math.round(rv.created.size / 1024)) + ' KB).');
      const link = el('a', '', 'Download it again');
      link.id = 'tplDownload';
      link.href = '/template/output';
      link.download = rv.created.name;
      line.append(' ', link);
      R.done.appendChild(line);
      if (rv.saved) R.done.appendChild(el('p', 'tpl-ok', 'Saved to ' + rv.saved));
    }
  }

  async function create_(how) {
    const rv = S.rv;
    if (rv.working || rv.dirty || !rv.plan || !rv.plan.ready) return;
    const body = planPayload();
    if (rv.allowMissing) body.allow_missing = true;
    const kind = S.data && S.data.kind;
    if (S.place.trim() && (kind === 'csv' || kind === 'excel')) body.data_path = S.place.trim();
    rv.working = how === 'save' ? 'Saving …' : 'Creating the workbook …';
    updateCreate();
    try {
      const answer = await postJSON(how === 'save' ? '/template/save' : '/template/apply', body);
      if (S.rv !== rv) return;
      rv.working = '';
      rv.created = {name: answer.name, size: answer.size};
      rv.saved = answer.path || '';
      updateCreate();
      D.$('announce').textContent = 'Workbook created: ' + answer.name + '.';
      D.setStatus('Created ' + answer.name + (how === 'save' ? '.' : '. Your download should start.'), false, 'ok');
      if (how !== 'save') {
        const a = el('a');
        a.href = '/template/output';
        a.download = answer.name;
        document.body.appendChild(a);
        a.click();
        a.remove();
      }
    } catch (e) {
      if (S.rv !== rv) return;
      rv.working = '';
      updateCreate();
      D.fail(e);
    }
  }

  // ---- make a template from the open workbook ---------------------------------------------------------

  function stemOf(name) { return name.replace(/\.(twbx|twb)$/i, ''); }

  function renderMake() {
    const body = D.$('tplMakeBody');
    if (!body) return;
    body.textContent = '';
    if (!S.workbook) {
      body.appendChild(el('p', 'tpl-reason', 'Open a workbook first, then come back here. The template is made from the workbook you have open.'));
    } else {
      buildMakeForm(body);
    }
    if (S.made) body.appendChild(madeBlock(S.made));
  }

  function buildMakeForm(body) {
    body.appendChild(el('p', '', 'Your open workbook is ' + S.workbook + '. A template keeps the workbook and a list of the fields it needs, so you can fill it with new data later. Passwords and user names are removed, and extracts and data files are left out.'));
    const nameBox = el('div', 'tpl-in');
    const nameLabel = el('label', '', 'Name of the template');
    nameLabel.htmlFor = 'tplMakeName';
    const name = el('input', 'field');
    name.id = 'tplMakeName';
    name.type = 'text';
    name.maxLength = 120;
    name.autocomplete = 'off';
    name.placeholder = stemOf(S.workbook);
    name.value = S.makeName;
    name.addEventListener('input', () => { S.makeName = name.value; });
    nameBox.append(nameLabel, name);
    const descBox = el('div', 'tpl-in');
    const descLabel = el('label', '', 'What it is for (optional)');
    descLabel.htmlFor = 'tplMakeDesc';
    const desc = el('textarea', 'field');
    desc.id = 'tplMakeDesc';
    desc.maxLength = 2000;
    desc.rows = 3;
    desc.value = S.makeDesc;
    desc.addEventListener('input', () => { S.makeDesc = desc.value; });
    descBox.append(descLabel, desc);
    const row = el('div', 'tpl-actions');
    const go = button('tplMakeBtn', S.making ? 'Making the template \u2026' : 'Make template', 'primary', makeTemplate);
    go.disabled = S.making;
    row.appendChild(go);
    const msg = el('p', 'tpl-err', S.makeError);
    msg.id = 'tplMakeMsg';
    msg.setAttribute('role', 'alert');
    body.append(nameBox, descBox, row, msg);
  }

  function madeBlock(made) {
    const box = el('div', 'tpl-made');
    box.id = 'tplMade';
    const t = made.template || {};
    box.appendChild(el('p', 'tpl-ok', 'Made ' + made.name + ' (' + Math.max(1, Math.round(made.size / 1024)) + ' KB).'));
    const required = (t.datasources || []).reduce((n, d) => n + d.required, 0);
    box.appendChild(el('p', 'tpl-counts', D.plural(required, 'required field') + ', ' +
      D.plural((t.parameters || []).length, 'parameter') + ', ' + D.plural((t.tokens || []).length, 'token')));
    const row = el('div', 'tpl-actions');
    const link = el('a', 'btn', 'Download the template');
    link.id = 'tplMadeDownload';
    link.href = '/template/made';
    link.download = made.name;
    const use = button('tplMadeUse', 'Use it as the template', 'primary', useMade);
    row.append(link, use);
    box.appendChild(row);
    box.appendChild(el('p', 'note', 'Download it to keep it. Making another template here replaces this one.'));
    if (made.notes && made.notes.length) {
      box.appendChild(el('h3', 'tpl-sub', 'Worth a look'));
      const list = el('ul', 'tpl-notes');
      made.notes.forEach((n) => list.appendChild(el('li', '', n)));
      box.appendChild(list);
    }
    if (t.findings) box.appendChild(findings(t.findings, {titleId: 'tplMakeCheckTitle', moreId: 'tplMakeMore', redraw: renderMake}));
    return box;
  }

  async function makeTemplate() {
    if (S.making) return;
    S.making = true;
    S.makeError = '';
    renderMake();
    D.setStatus('Making the template \u2026', false, 'busy');
    try {
      const payload = {description: S.makeDesc.trim()};
      if (S.makeName.trim()) payload.name = S.makeName.trim();
      const answer = await postJSON('/template/make', payload);
      S.made = {name: answer.name, size: answer.size, template: answer.template, notes: answer.notes || []};
      S.making = false;
      D.setStatus('Made ' + answer.name + '.', false, 'ok');
      D.$('announce').textContent = 'Template made: ' + answer.name + '.';
      renderMake();
    } catch (e) {
      S.making = false;
      S.makeError = e.message;
      D.fail(e);
      renderMake();
    }
  }

  async function useMade() {
    const mine = ++S.seq;
    try {
      const answer = await postJSON('/template/use-made', {});
      if (mine !== S.seq) return;
      accept('template', answer, S.made ? S.made.name : '');
      D.setStatus('', false);
      render();
      if (chosen()) {
        D.$('announce').textContent = 'Template chosen: ' + S.template.name + '. Check how the fields match your data.';
        focusHeading(3);
      } else {
        announceStep('template');
      }
    } catch (e) {
      if (mine !== S.seq) return;
      D.fail(e);
    }
  }

  function render() {
    renderTemplate();
    renderData();
    renderReview();
    renderMake();
  }

  function focusHeading(n) {
    const h = D.$('tplH' + n);
    if (h) h.focus();
  }

  function announceStep(slot) {
    if (slot === 'template') {
      D.$('announce').textContent = 'Template chosen: ' + S.template.name + '. Now choose your data.';
      focusHeading(2);
    } else if (chosen()) {
      D.$('announce').textContent = 'Data chosen: ' + S.dataName + ', ' + D.plural(S.data.columns.length, 'column') + '.';
      focusHeading(3);
    } else {
      D.$('announce').textContent = S.dataName + ' has several parts. Choose one.';
      focusHeading(2);
    }
  }

  // ---- dropping --------------------------------------------------------------------------------------

  function firstEmpty() {
    if (!ready()) return 'template';
    if (!chosen()) return 'data';
    return '';
  }

  function dropHint() {
    const slot = firstEmpty();
    if (slot === 'template') return ['Drop to use as the template', 'Or drop it on the card you want.'];
    if (slot === 'data') return ['Drop to use as the data', 'Or drop it on the card you want.'];
    return ['Drop on a card to replace it', 'Both steps are filled.'];
  }

  function acceptDrop(files, target) {
    if (!files || !files.length) return;
    if (files.length > 1) D.setStatus('Using the first of ' + files.length + ' files; one file at a time.', false, 'ok');
    let slot = '';
    const card = target && target.closest ? target.closest('.tpl-card') : null;
    if (card && card.dataset.state !== 'locked' && card.dataset.slot !== 'review') slot = card.dataset.slot;
    if (!slot) slot = firstEmpty();
    if (!slot) { D.setStatus('Both steps are filled. Drop the file on a card to replace it.', true); return; }
    chooseFile(slot, files[0]);
  }

  // ---- wiring ----------------------------------------------------------------------------------------

  function init(deps) {
    D = deps;
    [['tplTemplatePick', 'template'], ['tplDataPick', 'data']].forEach((pair) => {
      D.$(pair[0]).addEventListener('change', () => {
        const input = D.$(pair[0]);
        const file = input.files[0];
        input.value = '';
        if (file) chooseFile(pair[1], file);
      });
    });
    render();
  }

  function show() {
    S.open = true;
    render();
    restore();
  }

  function hide() { S.open = false; }

  function getState() {
    return {template: S.template, data: S.data, templateDatasource: S.tplDs, dataPlace: S.place.trim(),
      edits: S.rv.edits, params: S.rv.params, tokens: S.rv.tokens};
  }

  window.TemplatesView = {init: init, show: show, hide: hide, refresh: refresh, acceptDrop: acceptDrop, dropHint: dropHint, getState: getState};
})();
