// The Libraries view: the calculated fields and parameters of the open workbook as a paged table with a
// selection, an export of the selection as a library file, and adding a library file to the workbook with a
// clash policy. The server sends at most PAGE rows at a time, so the page never holds more. Nothing here sends
// a path: the library goes up as bytes, the new workbook comes back as a download, and the open workbook is
// never changed. Everything is inside one function so no name here can clash with app.js, which passes in its
// helpers (init) and calls render and reset.
(function () {
  'use strict';

  const PAGE = 100;
  const MAX_LIBRARY_MB = 8;
  const POLICIES = [
    ['fail', 'Stop (default)', 'Nothing is added if a field with the same caption is already in the workbook. The clashes are listed so you can choose another policy.'],
    ['rename', 'Rename', 'Add the new field under a caption with (2), or the next free number, after it.'],
    ['skip', 'Skip', 'Keep the workbook’s field and point the new calculations at it.'],
  ];
  const ACTION_TEXT = {
    'add': 'Add', 'add-renamed': 'Add, renamed', 'skip-identical': 'Skip, identical', 'skip-clash': 'Skip, clash',
    'fail-unmapped': 'Cannot add', 'fail-dependency': 'Cannot add', 'mapped': 'Found', 'unmapped': 'Missing',
  };

  let D = null;                      // helpers from app.js: $, el, fetchJSON, fail, setStatus, plural
  let q = fresh();
  let req = 0;
  let planReq = 0;
  let timer = null;
  let picked = new Set();            // internal names ticked, kept across pages and filters
  let lib = null;                    // summary of the added library file, or null
  let policy = 'fail';
  let planOffset = 0;
  let plan = null;
  let page = null;                   // the last entries answer
  let withDeps = true;
  let libName = '';
  let busy = false;

  function fresh() { return { datasource: '', addDs: '', kind: '', text: '', offset: 0 }; }
  function init(helpers) { D = helpers; }
  function reset() {
    q = fresh(); picked = new Set(); lib = null; policy = 'fail'; planOffset = 0; plan = null; page = null;
    withDeps = true; libName = ''; busy = false; clearTimeout(timer); req++; planReq++;
  }
  function num(n) { return Number(n).toLocaleString('en-US'); }
  function label(ds) { return ds.caption ? ds.caption + ' (' + ds.name + ')' : ds.name; }

  function entriesUrl(extra) {
    const p = new URLSearchParams();
    if (q.datasource) p.set('datasource', q.datasource);
    if (q.kind) p.set('kind', q.kind);
    if (q.text) p.set('q', q.text);
    p.set('offset', String(q.offset));
    p.set('limit', String(PAGE));
    if (extra) p.set('names', '1');
    return '/library/entries?' + p.toString();
  }

  function datasourceSelect(id, text, data, value, onChange) {
    const choices = data.datasources.filter((d) => d.has_connection);
    if (choices.length < 2) return null;
    const wrap = D.el('label', 'lib-field');
    wrap.append(D.el('span', '', text));
    const sel = D.el('select', 'field'); sel.id = id;
    if (!value) { const o = D.el('option', '', 'Choose a datasource'); o.value = ''; sel.appendChild(o); }
    choices.forEach((d) => { const o = D.el('option', '', label(d)); o.value = d.name; sel.appendChild(o); });
    sel.value = value;
    sel.addEventListener('change', () => onChange(sel.value));
    wrap.appendChild(sel);
    return wrap;
  }

  // ---- download of a POST answer, as rename.js does ----
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

  // ---- section 1: the fields of the workbook ----
  function selectionBar() {
    const bar = D.el('div', 'lib-selbar');
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Selection and export');
    const count = D.el('span', 'lib-count', picked.size ? num(picked.size) + ' selected' : 'Nothing selected');
    count.id = 'libSelected'; count.setAttribute('role', 'status');
    const all = D.el('button', 'btn small', 'Select all ' + num(page.matching) + (page.matching !== page.total ? ' matching' : ''));
    all.type = 'button'; all.id = 'libSelectAll'; all.disabled = !page.matching;
    all.addEventListener('click', async () => {
      try {
        const data = await D.fetchJSON(entriesUrl(true));
        data.names.forEach((n) => picked.add(n));
        draw();
      } catch (e) { D.fail(e); }
    });
    const none = D.el('button', 'btn small', 'Clear selection');
    none.type = 'button'; none.id = 'libClear'; none.disabled = !picked.size;
    none.addEventListener('click', () => { picked = new Set(); draw(); });
    bar.append(count, all, none);
    return bar;
  }

  function entriesTable() {
    if (!page.entries.length) {
      return D.el('p', 'lib-empty', page.total ? 'Nothing matches these filters.'
        : 'This datasource has no calculated fields or parameters that a library can hold.');
    }
    const wrap = D.el('div', 'lib-table-wrap');
    const t = D.el('table', 'lib-table'); t.id = 'libTable';
    t.appendChild(D.el('caption', 'sr-only', 'Calculated fields and parameters of the open workbook'));
    const head = D.el('thead'); const hr = D.el('tr');
    const th0 = D.el('th'); th0.scope = 'col';
    const allBox = D.el('input'); allBox.type = 'checkbox'; allBox.id = 'libPageBox';
    allBox.setAttribute('aria-label', 'Select every row on this page');
    const onPage = page.entries.filter((e) => picked.has(e.name)).length;
    allBox.checked = onPage === page.entries.length;
    allBox.indeterminate = onPage > 0 && onPage < page.entries.length;
    allBox.addEventListener('change', () => {
      page.entries.forEach((e) => { if (allBox.checked) picked.add(e.name); else picked.delete(e.name); });
      draw(allBox.id);
    });
    th0.appendChild(allBox); hr.appendChild(th0);
    ['Name', 'Kind', 'Type', 'Formula or value'].forEach((h) => { const th = D.el('th', '', h); th.scope = 'col'; hr.appendChild(th); });
    head.appendChild(hr);
    const body = D.el('tbody');
    page.entries.forEach((e, i) => {
      const tr = D.el('tr'); tr.dataset.name = e.name;
      const c0 = D.el('td', 'lib-check');
      const cb = D.el('input'); cb.type = 'checkbox'; cb.id = 'libRow' + i; cb.checked = picked.has(e.name);
      cb.setAttribute('aria-label', 'Select ' + e.caption);
      cb.addEventListener('change', () => {
        if (cb.checked) picked.add(e.name); else picked.delete(e.name);
        draw(cb.id);
      });
      c0.appendChild(cb); tr.appendChild(c0);
      const nm = D.el('td', 'lib-name'); nm.appendChild(D.el('div', '', e.caption));
      if (e.folder) nm.appendChild(D.el('div', 'lib-sub', 'Folder: ' + e.folder));
      tr.appendChild(nm);
      tr.appendChild(D.el('td', '', e.kind === 'parameter' ? 'Parameter' : 'Calculation'));
      tr.appendChild(D.el('td', '', e.datatype));
      tr.appendChild(D.el('td', 'lib-formula', e.formula + (e.truncated ? ' ...' : '')));
      body.appendChild(tr);
    });
    t.append(head, body); wrap.appendChild(t);
    return wrap;
  }

  function entriesPager() {
    const box = D.el('div', 'lib-pager');
    if (!page.matching) return box;
    const last = page.offset + page.entries.length;
    const text = D.el('span', 'lib-count', 'Showing ' + num(page.offset + 1) + '–' + num(last) + ' of ' + num(page.matching) +
      (page.matching !== page.total ? ' matching (' + num(page.total) + ' in all)' : ''));
    text.id = 'libPageCount';
    const prev = D.el('button', 'btn small', 'Previous ' + PAGE); prev.type = 'button'; prev.id = 'libPrev';
    prev.disabled = page.offset === 0;
    prev.addEventListener('click', () => { q.offset = Math.max(0, q.offset - PAGE); load(); });
    const next = D.el('button', 'btn small', 'Next ' + PAGE); next.type = 'button'; next.id = 'libNext';
    next.disabled = last >= page.matching;
    next.addEventListener('click', () => { q.offset += PAGE; load(); });
    box.append(text, prev, next);
    return box;
  }

  function exportBlock() {
    const box = D.el('div', 'lib-export');
    const dep = D.el('label', 'check');
    const cb = D.el('input'); cb.type = 'checkbox'; cb.id = 'libDeps'; cb.checked = withDeps;
    cb.addEventListener('change', () => { withDeps = cb.checked; });
    dep.append(cb, D.el('span', '', 'Also take the calculations and parameters the selection uses'));
    const nameWrap = D.el('label', 'lib-field');
    nameWrap.append(D.el('span', '', 'Library name (optional)'));
    const nm = D.el('input', 'field'); nm.id = 'libName'; nm.type = 'text'; nm.maxLength = 120; nm.value = libName;
    nm.addEventListener('input', () => { libName = nm.value; });
    nameWrap.appendChild(nm);
    const go = D.el('button', 'btn primary', 'Export library file'); go.type = 'button'; go.id = 'libExport';
    go.disabled = !picked.size || busy;
    go.addEventListener('click', async () => {
      busy = true; go.disabled = true;
      D.setStatus('Making the library file ...', false, 'busy');
      try {
        const name = await save('/library/export', {
          datasource: q.datasource || undefined, select: Array.from(picked), with_dependencies: withDeps,
          name: libName.trim() || undefined }, 'workbook.library.json');
        D.setStatus('Saved ' + name + ' with ' + D.plural(picked.size, 'selected item'), false, 'ok');
      } catch (e) { D.fail(e, 'Nothing was saved'); }
      busy = false; go.disabled = !picked.size;
    });
    box.append(dep, nameWrap, go);
    const note = D.el('p', 'note', 'The file holds the formulas and what they need; it is saved by the browser and nothing is written beside your workbook.');
    box.appendChild(note);
    return box;
  }

  function filters() {
    const bar = D.el('div', 'lib-filters');
    bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', 'Filter the list');
    const ds = datasourceSelect('libDs', 'Datasource', page, q.datasource || page.datasource || '', (v) => {
      q.datasource = v; q.offset = 0; picked = new Set(); load();
    });
    if (ds) bar.appendChild(ds);
    const kind = D.el('select', 'field'); kind.id = 'libKind'; kind.setAttribute('aria-label', 'Kind');
    [['', 'Calculations and parameters'], ['calc', 'Calculations'], ['parameter', 'Parameters']].forEach(([v, t]) => {
      const o = D.el('option', '', t); o.value = v; kind.appendChild(o);
    });
    kind.value = q.kind;
    kind.addEventListener('change', () => { q.kind = kind.value; q.offset = 0; load(); });
    const text = D.el('input', 'field'); text.id = 'libText'; text.type = 'search'; text.value = q.text;
    text.placeholder = 'Search name, formula or folder'; text.setAttribute('aria-label', 'Search the list');
    text.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => { q.text = text.value.trim(); q.offset = 0; load(); }, 250);
    });
    bar.append(kind, text);
    return bar;
  }

  function sectionOne() {
    const sec = D.el('section', 'lib-card'); sec.setAttribute('aria-labelledby', 'libH1');
    const h = D.el('h2', '', 'Export from this workbook'); h.id = 'libH1';
    sec.append(h, D.el('p', 'note', 'Tick the calculated fields and parameters to put in a library file.'));
    if (page.needs_datasource) {
      sec.appendChild(D.el('p', 'lib-hint', 'This workbook has more than one datasource. Choose the one to read.'));
      const ds = datasourceSelect('libDs', 'Datasource', page, '', (v) => { q.datasource = v; q.offset = 0; picked = new Set(); load(); });
      if (ds) sec.appendChild(ds);
      return sec;
    }
    sec.append(filters());
    if (page.unsupported_count) {
      const shown = page.unsupported.slice(0, 8).join(', ') + (page.unsupported_count > 8 ? ' and ' + (page.unsupported_count - 8) + ' more' : '');
      const n = D.el('p', 'lib-hint', page.unsupported_count + ' not listed because they use another datasource: ' + shown + '.');
      n.id = 'libUnsupported'; sec.appendChild(n);
    }
    sec.append(selectionBar(), entriesTable(), entriesPager(), exportBlock());
    return sec;
  }

  // ---- section 2: add a library ----
  function planSummary() {
    const c = plan.counts;
    const parts = [];
    [['add', 'to add'], ['add-renamed', 'to add renamed'], ['skip-identical', 'identical, skipped'], ['skip-clash', 'skipped for a clash'],
     ['fail-unmapped', 'cannot be added'], ['fail-dependency', 'cannot be added (need one that failed)']].forEach(([k, t]) => {
      if (c[k]) parts.push(num(c[k]) + ' ' + t);
    });
    return parts.length ? parts.join(', ') : 'Nothing to add.';
  }

  function clashTable() {
    const wrap = D.el('div', 'lib-table-wrap');
    const t = D.el('table', 'lib-table'); t.id = 'libClashes';
    t.appendChild(D.el('caption', 'sr-only', 'Fields that clash with a field already in the workbook'));
    const head = D.el('thead'); const hr = D.el('tr');
    ['Field in the library', 'What happens'].forEach((h) => { const th = D.el('th', '', h); th.scope = 'col'; hr.appendChild(th); });
    head.appendChild(hr);
    const body = D.el('tbody');
    plan.clashes.forEach((r) => {
      const tr = D.el('tr'); tr.dataset.action = r.action;
      tr.appendChild(D.el('td', 'lib-name', r.caption || r.name));
      let what = 'Skipped; the workbook keeps its own field';
      if (plan.blocked) what = 'Stops the import: a field with this caption is already there';
      else if (r.action === 'add-renamed') what = 'Added as ' + r.target_caption;
      tr.appendChild(D.el('td', '', what));
      body.appendChild(tr);
    });
    t.append(head, body); wrap.appendChild(t);
    return wrap;
  }

  function planTable() {
    const wrap = D.el('div', 'lib-table-wrap');
    const t = D.el('table', 'lib-table'); t.id = 'libPlan';
    t.appendChild(D.el('caption', 'sr-only', 'What adding the library does, item by item'));
    const head = D.el('thead'); const hr = D.el('tr');
    ['Item', 'Action', 'Why'].forEach((h) => { const th = D.el('th', '', h); th.scope = 'col'; hr.appendChild(th); });
    head.appendChild(hr);
    const body = D.el('tbody');
    plan.rows.forEach((r) => {
      const tr = D.el('tr'); tr.dataset.action = r.action;
      const nm = D.el('td', 'lib-name'); nm.appendChild(D.el('div', '', r.caption || r.name));
      nm.appendChild(D.el('div', 'lib-sub', r.kind === 'parameter' ? 'Parameter' : (r.kind === 'calc' ? 'Calculation' : 'Field it needs')));
      tr.appendChild(nm);
      const stopped = plan.blocked && (r.action === 'add' || r.action === 'add-renamed');
      tr.appendChild(D.el('td', 'lib-action', stopped ? 'Not added (import stops)' : (ACTION_TEXT[r.action] || r.action)));
      tr.appendChild(D.el('td', 'lib-why', r.reason || ''));
      body.appendChild(tr);
    });
    t.append(head, body); wrap.appendChild(t);
    return wrap;
  }

  function planPager() {
    const box = D.el('div', 'lib-pager');
    const last = plan.offset + plan.rows.length;
    const text = D.el('span', 'lib-count', 'Plan rows ' + num(plan.offset + 1) + '–' + num(last) + ' of ' + num(plan.total));
    text.id = 'libPlanCount';
    const prev = D.el('button', 'btn small', 'Previous ' + PAGE); prev.type = 'button'; prev.id = 'libPlanPrev';
    prev.disabled = plan.offset === 0;
    prev.addEventListener('click', () => { planOffset = Math.max(0, planOffset - PAGE); loadPlan(); });
    const next = D.el('button', 'btn small', 'Next ' + PAGE); next.type = 'button'; next.id = 'libPlanNext';
    next.disabled = last >= plan.total;
    next.addEventListener('click', () => { planOffset += PAGE; loadPlan(); });
    box.append(text, prev, next);
    return box;
  }

  function policyBlock() {
    const fs = D.el('fieldset', 'lib-policy'); fs.id = 'libPolicy';
    fs.appendChild(D.el('legend', '', 'If a field with the same caption is already there'));
    POLICIES.forEach(([v, title, text]) => {
      const row = D.el('label', 'lib-radio');
      const r = D.el('input'); r.type = 'radio'; r.name = 'libPolicy'; r.value = v; r.checked = policy === v;
      r.addEventListener('change', () => { policy = v; planOffset = 0; loadPlan(); });
      const t = D.el('span', ''); t.append(D.el('strong', '', title), D.el('span', 'lib-sub', text));
      row.append(r, t); fs.appendChild(row);
    });
    return fs;
  }

  function fileBlock() {
    const box = D.el('div', 'lib-file');
    const pick = D.el('label', 'btn'); pick.setAttribute('for', 'libFile');
    pick.textContent = lib ? 'Choose another library file' : 'Choose a library file';
    const input = D.el('input'); input.type = 'file'; input.id = 'libFile'; input.accept = '.json,application/json';
    input.className = 'sr-only';
    input.addEventListener('change', () => { if (input.files && input.files[0]) upload(input.files[0]); });
    input.addEventListener('focus', () => pick.classList.add('focus'));
    input.addEventListener('blur', () => pick.classList.remove('focus'));
    box.append(pick, input);
    if (lib) {
      const info = D.el('p', 'lib-loaded'); info.id = 'libLoaded';
      info.append(D.el('strong', '', lib.name || lib.file), ' (' + lib.file + '): ' + D.plural(lib.calcs, 'calculation') + ', ' +
        D.plural(lib.parameters, 'parameter') + (lib.source_workbook ? ', from ' + lib.source_workbook : ''));
      box.appendChild(info);
      if (lib.description) box.appendChild(D.el('p', 'note', lib.description));
    } else {
      box.appendChild(D.el('p', 'note', 'A *.library.json file made by Export (or py-tbparse library export), up to ' + MAX_LIBRARY_MB + ' MB.'));
    }
    return box;
  }

  function sectionTwo() {
    const sec = D.el('section', 'lib-card'); sec.setAttribute('aria-labelledby', 'libH2');
    const h = D.el('h2', '', 'Add a library to this workbook'); h.id = 'libH2';
    sec.append(h, D.el('p', 'note', 'You get a new workbook to download. The open workbook is not changed and no file is written on the machine that runs py-tbparse.'));
    sec.appendChild(fileBlock());
    if (!lib) return sec;
    if (page && page.datasources) {
      const ds = datasourceSelect('libAddDs', 'Add to datasource', page, q.addDs, (v) => { q.addDs = v; planOffset = 0; loadPlan(); });
      if (ds) sec.appendChild(ds);
    }
    sec.appendChild(policyBlock());
    const out = D.el('div', 'lib-plan'); out.id = 'libPlanBox'; out.setAttribute('aria-live', 'polite');
    if (plan && plan.error) {
      const e = D.el('p', 'lib-problem', plan.error); e.id = 'libPlanError'; out.appendChild(e);
    } else if (plan) {
      const sum = D.el('p', 'lib-plan-line'); sum.id = 'libPlanSummary';
      sum.append(D.el('strong', '', plan.blocked ? 'Stopped: ' : 'Plan: '), plan.blocked ? plan.blocked : planSummary());
      sum.dataset.blocked = plan.blocked ? 'true' : 'false';
      out.appendChild(sum);
      if (plan.clash_count) {
        out.appendChild(D.el('h3', '', D.plural(plan.clash_count, 'clash') + (plan.clash_count > plan.clashes.length ? ' (first ' + plan.clashes.length + ' shown)' : '')));
        out.appendChild(clashTable());
      } else {
        out.appendChild(D.el('p', 'note', 'No field in the library clashes with one in the workbook.'));
      }
      out.appendChild(D.el('h3', '', 'All items'));
      out.append(planTable(), planPager());
    } else {
      out.appendChild(D.el('p', 'note', 'Checking ...'));
    }
    sec.appendChild(out);
    const go = D.el('button', 'btn primary', 'Download new workbook'); go.type = 'button'; go.id = 'libAdd';
    go.disabled = busy || !plan || !!plan.error || !!plan.blocked || !plan.will_add;
    go.addEventListener('click', async () => {
      busy = true; go.disabled = true;
      D.setStatus('Adding the library ...', false, 'busy');
      try {
        const name = await save('/library/add', { datasource: q.addDs || undefined, on_clash: policy }, 'workbook_library.twb');
        D.setStatus('Saved ' + name + ': ' + D.plural(plan.will_add, 'item') + ' added. The open workbook is unchanged. Open the copy in Tableau before you rely on it.', false, 'ok');
      } catch (e) { D.fail(e, 'Nothing was saved'); }
      busy = false; go.disabled = false;
    });
    const row = D.el('div', 'lib-go');
    row.appendChild(go);
    if (plan && !plan.error && !plan.blocked && !plan.will_add) row.appendChild(D.el('span', 'note', 'There is nothing to add.'));
    if (plan && plan.blocked) row.appendChild(D.el('span', 'note', 'Choose Rename or Skip above to go on.'));
    sec.appendChild(row);
    return sec;
  }

  function draw(focusId) {
    const wrap = D.$('tableWrap');
    const active = focusId || (document.activeElement && wrap.contains(document.activeElement) ? document.activeElement.id : '');
    const caret = active === 'libText' ? document.activeElement.selectionStart : null;
    const panel = D.el('div', 'lib');
    panel.append(sectionOne(), sectionTwo());
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
      const data = await D.fetchJSON(entriesUrl(false));
      if (mine !== req) return;
      page = data;
      if (!q.datasource && data.datasource && data.datasources.filter((d) => d.has_connection).length > 1) q.datasource = data.datasource;
      if (!q.addDs && data.datasources.filter((d) => d.has_connection).length > 1) q.addDs = q.datasource || '';
      D.$('meta').textContent = data.needs_datasource ? 'Choose a datasource' : data.matching === data.total
        ? D.plural(data.total, 'field') : num(data.matching) + ' of ' + num(data.total) + ' fields';
      draw();
      D.$('announce').textContent = 'Libraries: ' + D.plural(data.matching, 'field') + ' listed';
      if (lib && !plan) loadPlan();
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
      const res = await fetch('/library/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ datasource: q.addDs || undefined, on_clash: policy, offset: planOffset, limit: PAGE }) });
      const data = await res.json();
      if (mine !== planReq) return;
      plan = res.ok ? data : { error: data.error || res.statusText };
    } catch (e) {
      if (mine !== planReq) return;
      plan = { error: String(e.message || e) };
    }
    draw();
  }

  function upload(file) {
    if (file.size > MAX_LIBRARY_MB * 1024 * 1024) {
      D.setStatus('That didn’t work: ' + file.name + ' is ' + Math.round(file.size / 1048576) + ' MB; a library can be at most ' + MAX_LIBRARY_MB + ' MB.', true);
      return;
    }
    D.setStatus('Reading ' + file.name + ' ...', false, 'busy');
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/library/upload');
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name));
    xhr.onerror = () => D.fail(new Error('the upload did not go through'), 'Nothing was added');
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        lib = data.library; plan = null; planOffset = 0;
        D.setStatus('Read ' + file.name + '. Check the plan before you download.', false, 'ok');
        loadPlan();
      } else {
        D.fail(new Error(data.error || xhr.statusText), 'Nothing was added');
      }
    };
    xhr.send(file);
  }

  // Called by app.js when the Libraries view is chosen; resolves once the list is on the page.
  async function render() {
    D.$('exportLink').hidden = true;
    if (!lib) {
      try { const st = await D.fetchJSON('/library/state'); lib = st.library; } catch (e) { /* the list reports its own errors */ }
    }
    await load();
    if (lib && !plan) loadPlan();
  }

  window.LibrariesView = { init: init, render: render, reset: reset, pageSize: PAGE };
})();
