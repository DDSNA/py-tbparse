// The Styles view: the custom colour palettes of the open workbook as a paged list with colour chips, the
// `style check` results, an export of the ticked palettes (a style file, or a Preferences.tps to download), and
// adding the palettes of an uploaded file to the workbook with a clash policy. The server sends at most PAGE rows
// at a time. Nothing here sends a path: the palette file goes up as bytes, everything else comes back as a
// download, and neither the open workbook nor any Preferences.tps is ever written. Adding palettes only makes them
// selectable in the colour picker; it recolours nothing. Everything is inside one function so no name here can
// clash with app.js, which passes in its helpers (init) and calls render and reset.
(function () {
  'use strict';

  const PAGE = 100;
  const MAX_FILE_MB = 2;
  const CHIPS = 20;                  // Edit Colors in Tableau shows at most 20 colours per palette
  const TYPE_TEXT = { 'regular': 'Regular', 'ordered-sequential': 'Ordered sequential', 'ordered-diverging': 'Ordered diverging' };
  const POLICIES = [
    ['fail', 'Stop (default)', 'Nothing is added if a palette with the same name but other colours is already in the workbook. The clashes are listed so you can choose another policy.'],
    ['skip', 'Skip', 'Keep the workbook’s palette and do not add the new one.'],
    ['rename', 'Rename', 'Add the new palette as Name (2), or the next free number, and keep both.'],
    ['replace', 'Replace', 'Put the new palette in the place of the workbook’s palette. Use this for a new version of your palette.'],
  ];
  const ACTION_TEXT = {
    'add': 'Add', 'skip-identical': 'Skip, already there', 'skip': 'Skip, keep existing', 'rename': 'Add, renamed',
    'replace': 'Replace existing', 'fail': 'Clash, stops the import', 'invalid': 'Cannot use',
  };

  let D = null;                      // helpers from app.js: $, el, fetchJSON, fail, setStatus, plural, labelCells
  let q = fresh();
  let req = 0;
  let planReq = 0;
  let timer = null;
  let picked = new Set();            // palette names ticked, kept across pages and filters
  let file = null;                   // summary of the uploaded palette file, or null
  let policy = 'fail';
  let planOffset = 0;
  let plan = null;
  let page = null;
  let exportName = '';
  let busy = false;

  function fresh() { return { text: '', offset: 0 }; }
  function init(helpers) { D = helpers; }
  function reset() {
    q = fresh(); picked = new Set(); file = null; policy = 'fail'; planOffset = 0; plan = null; page = null;
    exportName = ''; busy = false; clearTimeout(timer); req++; planReq++;
  }
  function num(n) { return Number(n).toLocaleString('en-US'); }

  function listUrl(names) {
    const p = new URLSearchParams();
    if (q.text) p.set('q', q.text);
    p.set('offset', String(q.offset));
    p.set('limit', String(PAGE));
    if (names) p.set('names', '1');
    return '/style/palettes?' + p.toString();
  }

  // ---- download of a POST answer, as libraries.js does ----
  async function save(url, body, fallbackName) {
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).error || msg; } catch (e) { /* not JSON */ }
      throw new Error(msg);
    }
    const named = /filename\*=UTF-8''([^;]+)/.exec(res.headers.get('Content-Disposition') || '');
    const name = named ? decodeURIComponent(named[1]) : fallbackName;
    const link = document.createElement('a');
    link.href = URL.createObjectURL(await res.blob());
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    return name;
  }

  // ---- colour chips: the hex is in the accessible name, never colour alone ----
  function chips(colors, total, labelOf) {
    const box = D.el('span', 'sty-chips');
    box.setAttribute('role', 'list');
    box.setAttribute('aria-label', labelOf + ': ' + D.plural(total, 'colour'));
    colors.slice(0, CHIPS).forEach((c) => {
      const chip = D.el('span', 'sty-chip');
      chip.setAttribute('role', 'listitem');
      chip.setAttribute('aria-label', c);
      chip.title = c;
      chip.style.background = c;     // a #RRGGBB or #RRGGBBAA value checked by the server
      box.appendChild(chip);
    });
    if (total > CHIPS) box.appendChild(D.el('span', 'sty-more', '+' + num(total - CHIPS)));
    return box;
  }

  function hexText(colors, total) {
    const d = D.el('details', 'sty-hex');
    d.appendChild(D.el('summary', '', 'Hex codes'));
    d.appendChild(D.el('code', '', colors.join(' ') + (total > colors.length ? ' ... (' + num(total - colors.length) + ' more)' : '')));
    return d;
  }

  function statusText(r) {
    if (r.status === 'invalid') return 'Not usable: ' + r.reason;
    if (r.status === 'warning') return 'Warning: ' + r.reason;
    return '';
  }

  // ---- section 1: the palettes of the workbook ----
  function checkBlock() {
    const box = D.el('div', 'sty-check'); box.id = 'styCheck';
    if (!page.problem_count) {
      box.appendChild(D.el('p', 'sty-ok', page.total ? 'Check: no problems found in the ' + D.plural(page.total, 'palette') + '.' : ''));
      if (!page.total) box.hidden = true;
      return box;
    }
    box.appendChild(D.el('p', 'lib-problem', 'Check: ' + D.plural(page.problem_count, 'problem') + ' found'));
    const ul = D.el('ul', 'sty-problems');
    page.problems.forEach((t) => ul.appendChild(D.el('li', '', t)));
    box.appendChild(ul);
    if (page.problem_count > page.problems.length) box.appendChild(D.el('p', 'note', 'The first ' + page.problems.length + ' are shown.'));
    return box;
  }

  function selectionBar() {
    const bar = D.el('div', 'lib-selbar');
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Selection and export');
    const count = D.el('span', 'lib-count', picked.size ? num(picked.size) + ' selected' : 'Nothing selected');
    count.id = 'stySelected'; count.setAttribute('role', 'status');
    const all = D.el('button', 'btn small', 'Select all ' + num(page.matching) + (page.matching !== page.total ? ' matching' : ''));
    all.type = 'button'; all.id = 'stySelectAll'; all.disabled = !page.matching;
    all.addEventListener('click', async () => {
      try {
        const data = await D.fetchJSON(listUrl(true));
        data.names.forEach((n) => picked.add(n));
        draw();
      } catch (e) { D.fail(e); }
    });
    const none = D.el('button', 'btn small', 'Clear selection');
    none.type = 'button'; none.id = 'styClear'; none.disabled = !picked.size;
    none.addEventListener('click', () => { picked = new Set(); draw(); });
    bar.append(count, all, none);
    return bar;
  }

  function palettesTable() {
    if (!page.rows.length) {
      return D.el('p', 'lib-empty', page.total ? 'No palette matches this search.'
        : 'This workbook has no custom colour palettes. Add some from a file below, or open a workbook that has them.');
    }
    const wrap = D.el('div', 'lib-table-wrap');
    const t = D.el('table', 'lib-table'); t.id = 'styTable';
    t.appendChild(D.el('caption', 'sr-only', 'Custom colour palettes of the open workbook'));
    const head = D.el('thead'); const hr = D.el('tr');
    const th0 = D.el('th'); th0.scope = 'col';
    const usable = page.rows.filter((r) => r.status === 'ok' || r.status === 'warning');
    const allBox = D.el('input'); allBox.type = 'checkbox'; allBox.id = 'styPageBox';
    allBox.setAttribute('aria-label', 'Select every usable palette on this page');
    const onPage = usable.filter((r) => picked.has(r.name)).length;
    allBox.checked = usable.length > 0 && onPage === usable.length;
    allBox.indeterminate = onPage > 0 && onPage < usable.length;
    allBox.disabled = !usable.length;
    allBox.addEventListener('change', () => {
      usable.forEach((r) => { if (allBox.checked) picked.add(r.name); else picked.delete(r.name); });
      draw(allBox.id);
    });
    th0.appendChild(allBox); hr.appendChild(th0);
    ['Name', 'Type', 'Colours', 'Count'].forEach((h) => { const th = D.el('th', '', h); th.scope = 'col'; hr.appendChild(th); });
    head.appendChild(hr);
    const body = D.el('tbody');
    page.rows.forEach((r, i) => {
      const tr = D.el('tr'); tr.dataset.name = r.name; tr.dataset.status = r.status;
      const c0 = D.el('td', 'lib-check');
      const cb = D.el('input'); cb.type = 'checkbox'; cb.id = 'styRow' + i; cb.checked = picked.has(r.name);
      cb.disabled = r.status === 'invalid';
      cb.setAttribute('aria-label', 'Select ' + (r.name || '(no name)'));
      cb.addEventListener('change', () => {
        if (cb.checked) picked.add(r.name); else picked.delete(r.name);
        draw(cb.id);
      });
      c0.appendChild(cb); tr.appendChild(c0);
      const nm = D.el('td', 'lib-name'); nm.appendChild(D.el('div', '', r.name || '(no name)'));
      const st = statusText(r);
      if (st) nm.appendChild(D.el('div', r.status === 'invalid' ? 'lib-sub sty-bad' : 'lib-sub', st));
      tr.appendChild(nm);
      tr.appendChild(D.el('td', '', TYPE_TEXT[r.type] || r.type || '-'));
      const cc = D.el('td', 'sty-colours');
      cc.appendChild(chips(r.colors, r.n_colors, r.name || 'palette'));
      if (r.colors.length) cc.appendChild(hexText(r.colors, r.n_colors));
      tr.appendChild(cc);
      tr.appendChild(D.el('td', 'sty-n', String(r.n_colors)));
      body.appendChild(tr);
    });
    t.append(head, body); wrap.appendChild(t);
    return wrap;
  }

  function pager(data, idPrefix, text, onPrev, onNext) {
    const box = D.el('div', 'lib-pager');
    const last = data.offset + data.rows.length;
    const label = D.el('span', 'lib-count', text(last)); label.id = idPrefix + 'Count';
    const prev = D.el('button', 'btn small', 'Previous ' + PAGE); prev.type = 'button'; prev.id = idPrefix + 'Prev';
    prev.disabled = data.offset === 0; prev.addEventListener('click', onPrev);
    const next = D.el('button', 'btn small', 'Next ' + PAGE); next.type = 'button'; next.id = idPrefix + 'Next';
    next.disabled = last >= (data.matching !== undefined ? data.matching : data.total); next.addEventListener('click', onNext);
    box.append(label, prev, next);
    return box;
  }

  function entriesPager() {
    if (!page.matching) return D.el('div', 'lib-pager');
    return pager(page, 'sty', (last) => 'Showing ' + num(page.offset + 1) + '–' + num(last) + ' of ' + num(page.matching) +
      (page.matching !== page.total ? ' matching (' + num(page.total) + ' in all)' : ''),
      () => { q.offset = Math.max(0, q.offset - PAGE); load(); }, () => { q.offset += PAGE; load(); });
  }

  async function doExport(fmt, button) {
    busy = true; button.disabled = true;
    D.setStatus('Making the file ...', false, 'busy');
    try {
      const name = await save('/style/export', { select: Array.from(picked), format: fmt, name: exportName.trim() || undefined },
        fmt === 'tps' ? 'Preferences_palettes.tps' : 'palettes.style.json');
      D.setStatus('Saved ' + name + ' with ' + D.plural(picked.size, 'palette') + '.' + (fmt === 'tps'
        ? ' It is a new file: it never replaces your Preferences.tps. Keep a backup of yours, copy this one into My Tableau Repository yourself and restart Tableau Desktop.' : ''), false, 'ok');
    } catch (e) { D.fail(e, 'Nothing was saved'); }
    busy = false; button.disabled = !picked.size;
  }

  function exportBlock() {
    const box = D.el('div', 'lib-export');
    const nameWrap = D.el('label', 'lib-field');
    nameWrap.append(D.el('span', '', 'Style file name (optional)'));
    const nm = D.el('input', 'field'); nm.id = 'styName'; nm.type = 'text'; nm.maxLength = 120; nm.value = exportName;
    nm.addEventListener('input', () => { exportName = nm.value; });
    nameWrap.appendChild(nm);
    const go = D.el('button', 'btn primary', 'Export style file'); go.type = 'button'; go.id = 'styExport';
    go.disabled = !picked.size || busy;
    go.addEventListener('click', () => doExport('style', go));
    const tps = D.el('button', 'btn', 'Export as Preferences.tps'); tps.type = 'button'; tps.id = 'styExportTps';
    tps.disabled = !picked.size || busy;
    tps.addEventListener('click', () => doExport('tps', tps));
    box.append(nameWrap, go, tps);
    box.appendChild(D.el('p', 'note', 'Both are saved by the browser and nothing is written on the machine that runs py-tbparse. The .tps is a new file called Preferences_palettes.tps for your Tableau Repository: this page never replaces your own Preferences.tps.'));
    return box;
  }

  function sectionOne() {
    const sec = D.el('section', 'lib-card'); sec.setAttribute('aria-labelledby', 'styH1');
    const h = D.el('h2', '', 'Palettes in this workbook'); h.id = 'styH1';
    sec.append(h, D.el('p', 'note', 'Custom colour palettes stored in the workbook’s preferences. Tick the ones to export.'));
    const bar = D.el('div', 'lib-filters');
    bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', 'Filter the list');
    const text = D.el('input', 'field'); text.id = 'styText'; text.type = 'search'; text.value = q.text;
    text.placeholder = 'Search palette names'; text.setAttribute('aria-label', 'Search palette names');
    text.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => { q.text = text.value.trim(); q.offset = 0; load(); }, 250);
    });
    bar.appendChild(text);
    sec.append(bar, checkBlock(), selectionBar(), palettesTable(), entriesPager(), exportBlock());
    return sec;
  }

  // ---- section 2: add palettes from a file ----
  function planSummary() {
    const parts = [];
    [['add', 'to add'], ['rename', 'to add renamed'], ['replace', 'to replace'], ['skip-identical', 'already there'],
     ['skip', 'skipped for a clash'], ['fail', 'in a clash'], ['invalid', 'cannot be used']].forEach(([k, t]) => {
      if (plan.counts[k]) parts.push(num(plan.counts[k]) + ' ' + t);
    });
    return parts.length ? parts.join(', ') : 'Nothing to add.';
  }

  function clashTable() {
    const wrap = D.el('div', 'lib-table-wrap');
    const t = D.el('table', 'lib-table'); t.id = 'styClashes';
    t.appendChild(D.el('caption', 'sr-only', 'Palettes that clash with a palette already in the workbook'));
    const head = D.el('thead'); const hr = D.el('tr');
    ['Palette in the file', 'What happens'].forEach((h) => { const th = D.el('th', '', h); th.scope = 'col'; hr.appendChild(th); });
    head.appendChild(hr);
    const body = D.el('tbody');
    plan.clashes.forEach((r) => {
      const tr = D.el('tr'); tr.dataset.action = r.action;
      tr.appendChild(D.el('td', 'lib-name', r.name));
      let what = ACTION_TEXT[r.action];
      if (r.action === 'rename') what = 'Added as ' + r.target_name;
      else if (r.action === 'fail') what = 'Stops the import: a palette with this name and other colours is already there';
      tr.appendChild(D.el('td', '', what));
      body.appendChild(tr);
    });
    t.append(head, body); wrap.appendChild(t);
    return wrap;
  }

  function planTable() {
    const wrap = D.el('div', 'lib-table-wrap');
    const t = D.el('table', 'lib-table'); t.id = 'styPlan';
    t.appendChild(D.el('caption', 'sr-only', 'What adding the palettes does, palette by palette'));
    const head = D.el('thead'); const hr = D.el('tr');
    ['Palette', 'Colours', 'Action', 'Why'].forEach((h) => { const th = D.el('th', '', h); th.scope = 'col'; hr.appendChild(th); });
    head.appendChild(hr);
    const body = D.el('tbody');
    plan.rows.forEach((r) => {
      const tr = D.el('tr'); tr.dataset.action = r.action;
      const nm = D.el('td', 'lib-name'); nm.appendChild(D.el('div', '', r.name || '(no name)'));
      nm.appendChild(D.el('div', 'lib-sub', TYPE_TEXT[r.type] || r.type || ''));
      tr.appendChild(nm);
      const cc = D.el('td', 'sty-colours');
      if (r.colors.length) cc.appendChild(chips(r.colors, r.n_colors, r.name || 'palette'));
      tr.appendChild(cc);
      const stopped = plan.blocked && (r.action === 'add' || r.action === 'rename' || r.action === 'replace');
      tr.appendChild(D.el('td', 'lib-action', stopped ? 'Not added (import stops)' : (ACTION_TEXT[r.action] || r.action)));
      tr.appendChild(D.el('td', 'lib-why', r.reason || ''));
      body.appendChild(tr);
    });
    t.append(head, body); wrap.appendChild(t);
    return wrap;
  }

  function planPager() {
    return pager(plan, 'styPlan', (last) => 'Plan rows ' + num(plan.offset + 1) + '–' + num(last) + ' of ' + num(plan.total),
      () => { planOffset = Math.max(0, planOffset - PAGE); loadPlan(); }, () => { planOffset += PAGE; loadPlan(); });
  }

  function policyBlock() {
    const fs = D.el('fieldset', 'lib-policy'); fs.id = 'stylePolicy';
    fs.appendChild(D.el('legend', '', 'If a palette with the same name and other colours is already there'));
    POLICIES.forEach(([v, title, text]) => {
      const row = D.el('label', 'lib-radio');
      const r = D.el('input'); r.type = 'radio'; r.name = 'styPolicy'; r.value = v; r.checked = policy === v;
      r.addEventListener('change', () => { policy = v; planOffset = 0; loadPlan(); });
      const t = D.el('span', ''); t.append(D.el('strong', '', title), D.el('span', 'lib-sub', text));
      row.append(r, t); fs.appendChild(row);
    });
    return fs;
  }

  function fileBlock() {
    const box = D.el('div', 'lib-file');
    const pick = D.el('label', 'btn'); pick.setAttribute('for', 'styFile');
    pick.textContent = file ? 'Choose another palette file' : 'Choose a palette file';
    const input = D.el('input'); input.type = 'file'; input.id = 'styFile'; input.accept = '.json,.tps,application/json,text/xml';
    input.className = 'sr-only';
    input.addEventListener('change', () => { if (input.files && input.files[0]) upload(input.files[0]); });
    input.addEventListener('focus', () => pick.classList.add('focus'));
    input.addEventListener('blur', () => pick.classList.remove('focus'));
    box.append(pick, input);
    if (file) {
      const info = D.el('p', 'lib-loaded'); info.id = 'styLoaded';
      info.append(D.el('strong', '', file.file), ': ' + D.plural(file.palettes, 'palette') +
        (file.invalid ? ', ' + file.invalid + ' not usable' : ''));
      box.appendChild(info);
      if (file.problems && file.problems.length) {
        const ul = D.el('ul', 'sty-problems'); ul.id = 'styFileProblems';
        file.problems.slice(0, 10).forEach((t) => ul.appendChild(D.el('li', '', t)));
        box.appendChild(ul);
      }
    } else {
      box.appendChild(D.el('p', 'note', 'A *.style.json file made by Export (or py-tbparse style export), or a Preferences.tps, up to ' + MAX_FILE_MB + ' MB.'));
    }
    return box;
  }

  function sectionTwo() {
    const sec = D.el('section', 'lib-card'); sec.setAttribute('aria-labelledby', 'styH2');
    const h = D.el('h2', '', 'Add palettes from a file'); h.id = 'styH2';
    sec.append(h, D.el('p', 'note', 'You get a new workbook to download. The open workbook is not changed, and no file is written on the machine that runs py-tbparse. Palettes only appear in the colour picker; no mark changes colour.'));
    sec.appendChild(fileBlock());
    if (!file) return sec;
    sec.appendChild(policyBlock());
    const out = D.el('div', 'lib-plan'); out.id = 'styPlanBox'; out.setAttribute('aria-live', 'polite');
    if (plan && plan.error) {
      const e = D.el('p', 'lib-problem', plan.error); e.id = 'styPlanError'; out.appendChild(e);
    } else if (plan) {
      const sum = D.el('p', 'lib-plan-line'); sum.id = 'styPlanSummary';
      sum.append(D.el('strong', '', plan.blocked ? 'Stopped: ' : 'Plan: '),
        plan.blocked ? D.plural(plan.counts.fail, 'palette') + ' with a name already used and other colours. ' + planSummary() : planSummary());
      sum.dataset.blocked = plan.blocked ? 'true' : 'false';
      out.appendChild(sum);
      if (plan.clash_count) {
        out.appendChild(D.el('h3', '', D.plural(plan.clash_count, 'clash') + (plan.clash_count > plan.clashes.length ? ' (first ' + plan.clashes.length + ' shown)' : '')));
        out.appendChild(clashTable());
      } else {
        out.appendChild(D.el('p', 'note', 'No palette in the file clashes with one in the workbook.'));
      }
      out.appendChild(D.el('h3', '', 'All palettes in the file'));
      out.append(planTable(), planPager());
    } else {
      out.appendChild(D.el('p', 'note', 'Checking ...'));
    }
    sec.appendChild(out);
    const go = D.el('button', 'btn primary', 'Download new workbook'); go.type = 'button'; go.id = 'styAdd';
    go.disabled = busy || !plan || !!plan.error || !!plan.blocked || !plan.will_add;
    go.addEventListener('click', async () => {
      busy = true; go.disabled = true;
      D.setStatus('Adding the palettes ...', false, 'busy');
      try {
        const name = await save('/style/add', { on_clash: policy }, 'workbook_palettes.twb');
        D.setStatus('Saved ' + name + ': ' + D.plural(plan.will_add, 'palette') + ' added to the colour picker. The open workbook is unchanged. Open the copy in Tableau before you rely on it.', false, 'ok');
      } catch (e) { D.fail(e, 'Nothing was saved'); }
      busy = false; go.disabled = false;
    });
    const row = D.el('div', 'lib-go');
    row.appendChild(go);
    if (plan && !plan.error && !plan.blocked && !plan.will_add) row.appendChild(D.el('span', 'note', 'There is nothing to add.'));
    if (plan && plan.blocked) row.appendChild(D.el('span', 'note', 'Choose Skip, Rename or Replace above to go on.'));
    sec.appendChild(row);
    return sec;
  }

  function draw(focusId) {
    const wrap = D.$('tableWrap');
    const active = focusId || (document.activeElement && wrap.contains(document.activeElement) ? document.activeElement.id : '');
    const caret = active === 'styText' ? document.activeElement.selectionStart : null;
    const panel = D.el('div', 'lib');
    panel.append(sectionOne(), sectionTwo());
    D.labelCells(panel);
    wrap.innerHTML = '';
    wrap.appendChild(panel);
    if (active) {
      const node = document.getElementById(active);
      if (node && !node.disabled) {
        node.focus();
        if (caret !== null && node.setSelectionRange) { try { node.setSelectionRange(caret, caret); } catch (e) { /* not a text box */ } }
      }
    }
  }

  async function load() {
    const mine = ++req;
    try {
      const data = await D.fetchJSON(listUrl(false));
      if (mine !== req) return;
      page = data;
      D.$('meta').textContent = data.matching === data.total ? D.plural(data.total, 'palette') : num(data.matching) + ' of ' + num(data.total) + ' palettes';
      draw();
      D.$('announce').textContent = 'Styles: ' + D.plural(data.matching, 'palette') + ' listed';
      if (file && !plan) loadPlan();
    } catch (e) {
      if (mine !== req) return;
      q = fresh(); page = null;
      D.fail(e);
    }
  }

  async function loadPlan() {
    const mine = ++planReq;
    plan = null;
    draw();
    try {
      const res = await fetch('/style/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ on_clash: policy, offset: planOffset, limit: PAGE }) });
      const data = await res.json();
      if (mine !== planReq) return;
      plan = res.ok ? data : { error: data.error || res.statusText };
    } catch (e) {
      if (mine !== planReq) return;
      plan = { error: String(e.message || e) };
    }
    draw();
  }

  function upload(f) {
    if (f.size > MAX_FILE_MB * 1024 * 1024) {
      D.setStatus('That didn’t work: ' + f.name + ' is ' + Math.round(f.size / 1024) + ' KB; a palette file can be at most ' + MAX_FILE_MB + ' MB.', true);
      return;
    }
    D.setStatus('Reading ' + f.name + ' ...', false, 'busy');
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/style/upload');
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.setRequestHeader('X-Filename', encodeURIComponent(f.name));
    xhr.onerror = () => D.fail(new Error('the upload did not go through'), 'Nothing was added');
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        file = data.file; plan = null; planOffset = 0;
        D.setStatus('Read ' + f.name + '. Check the plan before you download.', false, 'ok');
        loadPlan();
      } else {
        D.fail(new Error(data.error || xhr.statusText), 'Nothing was added');
      }
    };
    xhr.send(f);
  }

  // Called by app.js when the Styles view is chosen; resolves once the list is on the page.
  async function render() {
    D.$('exportLink').hidden = true;
    if (!file) {
      try { const st = await D.fetchJSON('/style/state'); file = st.file; } catch (e) { /* the list reports its own errors */ }
    }
    await load();
    if (file && !plan) loadPlan();
  }

  window.StylesView = { init: init, render: render, reset: reset, pageSize: PAGE };
})();
