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
  const SEVERITIES = [
    ['error', '\u2716', 'Problem', 'problem'],
    ['warning', '\u25B2', 'Needs a look', 'warning'],
    ['info', '\u2022', 'Worth knowing', 'info'],
  ];

  let D = null;   // the helpers from app.js: $, el, setStatus, fetchJSON, fail, plural
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
  };

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
      render();
    } catch (e) {
      if (mine === S.seq) D.fail(e);
    }
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
    sel.addEventListener('change', () => { S.tplDs = sel.value; });
    wrap.append(label, sel);
    return wrap;
  }

  function findings(all) {
    const box = el('div', 'tpl-check');
    const counts = {error: 0, warning: 0, info: 0};
    all.forEach((f) => { if (f.severity in counts) counts[f.severity] += 1; });
    const title = el('h3', 'tpl-sub');
    title.id = 'tplCheckTitle';
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
    list.setAttribute('aria-labelledby', 'tplCheckTitle');
    sorted.slice(0, limit).forEach((f) => list.appendChild(findingItem(f)));
    box.appendChild(list);
    if (limit < sorted.length) {
      if (limit < SHOW_MAX) {
        const more = Math.min(SHOW_STEP, sorted.length - limit, SHOW_MAX - limit);
        box.appendChild(button('tplMore', 'Show ' + more + ' more', 'small', () => { S.shown = limit + SHOW_STEP; renderTemplate(); D.$('tplMore') && D.$('tplMore').focus(); }));
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

  function renderReview() {
    if (!ready() || !chosen()) {
      setCard(3, 'locked', !ready() ? 'Choose a template and your data first.' : 'Choose your data first.');
      return;
    }
    const body = setCard(3, 'todo');
    body.appendChild(el('p', 'tpl-lead', S.template.name + ' with ' + S.dataName));
    body.appendChild(el('p', 'note', 'Next comes matching the template\u2019s fields to your columns, and creating the workbook. That part is not built yet.'));
  }

  function render() {
    renderTemplate();
    renderData();
    renderReview();
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
    return {template: S.template, data: S.data, templateDatasource: S.tplDs, dataPlace: S.place.trim()};
  }

  window.TemplatesView = {init: init, show: show, hide: hide, acceptDrop: acceptDrop, dropHint: dropHint, getState: getState};
})();
