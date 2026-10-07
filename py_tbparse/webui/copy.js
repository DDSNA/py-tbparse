// The Slice and copy view, two cards for the open workbook:
//  1. Slice: tick dashboards to keep; the rest of the workbook is dropped (py-tbparse slice).
//  2. Copy sheets: choose a target workbook, tick worksheets of the open workbook and copy them into a copy of
//     the target (py-tbparse sheet copy).
// Both show the plan before anything is made, and both end in a download. The server sends at most PAGE rows at a
// time (lists and plans are paged), the page never holds more. Nothing here sends a path: the target goes up as
// bytes, the open workbook and the target are never changed, and there is no overwrite option. The clash policy
// of the copy is Stop (default), Rename or Skip. Everything is inside one function so no name here can clash with
// app.js, which passes in its helpers (init) and calls render and reset.
(function () {
  'use strict';

  const PAGE = 100;
  const POLICIES = [
    ['fail', 'Stop (default)', 'Nothing is made if a calculation, a parameter or a sheet name is already in the target with another definition. The clashes are listed so you can choose another policy.'],
    ['rename', 'Rename', 'The new calculation, parameter or sheet is added as Name (2), or the next free number, and both are kept.'],
    ['skip', 'Skip', 'Keep the target’s calculation and use it, and do not copy a sheet whose name is taken.'],
  ];
  const STATUS_TEXT = { 'copy': 'Copy', 'skipped': 'Skipped', 'refused': 'Refused' };
  const LIB_TEXT = { 'add': 'Add to the target', 'add-renamed': 'Add, renamed', 'skip-identical': 'Already there',
                     'skip-clash': 'Keep the target’s', 'fail-unmapped': 'Cannot be matched', 'fail-dependency': 'Needs a field that is missing' };
  const KIND_TEXT = { 'calc': 'Calculation', 'parameter': 'Parameter' };

  let D = null;                      // helpers from app.js: $, el, fetchJSON, fail, setStatus, plural, labelCells
  let busy = false;
  let target = null;                 // summary of the uploaded target workbook, or null
  let policy = 'fail';
  let strictCopy = false;
  let strictSlice = false;
  let prune = true;
  let slicePlan = null, slicePlanOffset = 0, sliceReq = 0, sliceTimer = null;
  let copyPlan = null, copyPlanOffset = 0, copyReq = 0, copyTimer = null;
  let dash = null, sheets = null;    // the two pickers

  function num(n) { return Number(n).toLocaleString('en-US'); }
  function init(helpers) { D = helpers; }

  // ---- a paged list with ticks, used for dashboards and for worksheets ----
  function picker(o) {
    const p = { o: o, q: { text: '', offset: 0 }, picked: new Set(), page: null, req: 0, timer: null };
    p.reset = function () { p.q = { text: '', offset: 0 }; p.picked = new Set(); p.page = null; p.req++; clearTimeout(p.timer); };
    p.url = function (names) {
      const u = new URLSearchParams();
      if (p.q.text) u.set('q', p.q.text);
      u.set('offset', String(p.q.offset));
      u.set('limit', String(PAGE));
      if (names) u.set('names', '1');
      return o.url + '?' + u.toString();
    };
    p.load = async function () {
      const mine = ++p.req;
      const data = await D.fetchJSON(p.url(false));
      if (mine !== p.req) return false;
      p.page = data;
      return true;
    };
    p.node = function () {
      const box = D.el('div', 'cpy-list');
      const bar = D.el('div', 'lib-filters');
      bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', 'Filter the ' + o.plural);
      const text = D.el('input', 'field'); text.id = o.id + 'Text'; text.type = 'search'; text.value = p.q.text;
      text.placeholder = 'Search ' + o.plural; text.setAttribute('aria-label', 'Search ' + o.plural);
      text.addEventListener('input', () => {
        clearTimeout(p.timer);
        p.timer = setTimeout(async () => {
          p.q.text = text.value.trim(); p.q.offset = 0;
          try { await p.load(); draw(o.id + 'Text'); } catch (e) { D.fail(e); }
        }, 250);
      });
      bar.appendChild(text);
      box.appendChild(bar);
      const pg = p.page;
      const sel = D.el('div', 'lib-selbar');
      sel.setAttribute('role', 'group'); sel.setAttribute('aria-label', 'Selection');
      const count = D.el('span', 'lib-count', p.picked.size ? num(p.picked.size) + ' selected' : 'Nothing selected');
      count.id = o.id + 'Selected'; count.setAttribute('role', 'status');
      const all = D.el('button', 'btn small', 'Select all ' + num(pg.matching) + (pg.matching !== pg.total ? ' matching' : ''));
      all.type = 'button'; all.id = o.id + 'SelectAll'; all.disabled = !pg.matching;
      all.addEventListener('click', async () => {
        try {
          const data = await D.fetchJSON(p.url(true));
          data.names.forEach((n) => p.picked.add(n));
          changed(o.id);
        } catch (e) { D.fail(e); }
      });
      const none = D.el('button', 'btn small', 'Clear selection');
      none.type = 'button'; none.id = o.id + 'Clear'; none.disabled = !p.picked.size;
      none.addEventListener('click', () => { p.picked = new Set(); changed(o.id); });
      sel.append(count, all, none);
      box.appendChild(sel);
      if (!pg.rows.length) {
        box.appendChild(D.el('p', 'lib-empty', pg.total ? 'Nothing matches this search.' : o.empty));
        return box;
      }
      const wrap = D.el('div', 'lib-table-wrap');
      const t = D.el('table', 'lib-table'); t.id = o.id + 'Table';
      t.appendChild(D.el('caption', 'sr-only', o.caption));
      const head = D.el('thead'); const hr = D.el('tr');
      const th0 = D.el('th'); th0.scope = 'col';
      const allBox = D.el('input'); allBox.type = 'checkbox'; allBox.id = o.id + 'PageBox';
      allBox.setAttribute('aria-label', 'Select every ' + o.single + ' on this page');
      const onPage = pg.rows.filter((r) => p.picked.has(r.name)).length;
      allBox.checked = onPage === pg.rows.length;
      allBox.indeterminate = onPage > 0 && onPage < pg.rows.length;
      allBox.addEventListener('change', () => {
        pg.rows.forEach((r) => { if (allBox.checked) p.picked.add(r.name); else p.picked.delete(r.name); });
        changed(allBox.id);
      });
      th0.appendChild(allBox); hr.appendChild(th0);
      o.columns.forEach((h) => { const th = D.el('th', '', h); th.scope = 'col'; hr.appendChild(th); });
      head.appendChild(hr);
      const body = D.el('tbody');
      pg.rows.forEach((r, i) => {
        const tr = D.el('tr'); tr.dataset.name = r.name;
        const c0 = D.el('td', 'lib-check');
        const cb = D.el('input'); cb.type = 'checkbox'; cb.id = o.id + 'Row' + i; cb.checked = p.picked.has(r.name);
        cb.setAttribute('aria-label', 'Select ' + r.name);
        cb.addEventListener('change', () => {
          if (cb.checked) p.picked.add(r.name); else p.picked.delete(r.name);
          changed(cb.id);
        });
        c0.appendChild(cb); tr.appendChild(c0);
        tr.appendChild(D.el('td', 'lib-name', r.name));
        o.cells(r).forEach((c) => tr.appendChild(D.el('td', '', c)));
        body.appendChild(tr);
      });
      t.append(head, body); wrap.appendChild(t);
      box.appendChild(wrap);
      box.appendChild(pager(pg, o.id, (last) => 'Showing ' + num(pg.offset + 1) + '–' + num(last) + ' of ' + num(pg.matching) +
        (pg.matching !== pg.total ? ' matching (' + num(pg.total) + ' in all)' : ''),
        async () => { p.q.offset = Math.max(0, p.q.offset - PAGE); try { await p.load(); draw(); } catch (e) { D.fail(e); } },
        async () => { p.q.offset += PAGE; try { await p.load(); draw(); } catch (e) { D.fail(e); } },
        pg.matching));
      return box;
    };
    return p;
  }

  function pager(data, idPrefix, text, onPrev, onNext, total) {
    const box = D.el('div', 'lib-pager');
    const last = data.offset + data.rows.length;
    const label = D.el('span', 'lib-count', text(last)); label.id = idPrefix + 'Count';
    const prev = D.el('button', 'btn small', 'Previous ' + PAGE); prev.type = 'button'; prev.id = idPrefix + 'Prev';
    prev.disabled = data.offset === 0; prev.addEventListener('click', onPrev);
    const next = D.el('button', 'btn small', 'Next ' + PAGE); next.type = 'button'; next.id = idPrefix + 'Next';
    next.disabled = last >= total; next.addEventListener('click', onNext);
    box.append(label, prev, next);
    return box;
  }

  function makePickers() {
    dash = picker({
      id: 'cpyDash', url: '/copy/dashboards', plural: 'dashboards', single: 'dashboard',
      caption: 'Dashboards of the open workbook', columns: ['Dashboard', 'Kind', 'Worksheets on it'],
      empty: 'This workbook has no dashboards, so there is nothing to slice.',
      cells: (r) => [r.kind === 'story' ? 'Story' : 'Dashboard', String(r.n_sheets)],
    });
    sheets = picker({
      id: 'cpySheet', url: '/copy/sheets', plural: 'worksheets', single: 'worksheet',
      caption: 'Worksheets of the open workbook', columns: ['Worksheet', 'Datasource'],
      empty: 'This workbook has no worksheets.',
      cells: (r) => [r.datasources.length ? r.datasources.join(', ') : 'none'],
    });
  }

  // ---- what changed in a picker or an option: redraw, then ask the server for the plan (after a short pause) ----
  function changed(focusId) {
    draw(focusId);
    if (focusId && focusId.indexOf('cpyDash') === 0) scheduleSlice(); else scheduleCopy();
  }
  function scheduleSlice() {
    clearTimeout(sliceTimer); slicePlanOffset = 0;
    sliceTimer = setTimeout(loadSlicePlan, 200);
  }
  function scheduleCopy() {
    clearTimeout(copyTimer); copyPlanOffset = 0;
    copyTimer = setTimeout(loadCopyPlan, 200);
  }

  // ---- downloads and posts ----
  async function post(url, body) {
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return res;
  }
  async function save(url, body, fallbackName) {
    const res = await post(url, body);
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

  function table(id, caption, heads) {
    const wrap = D.el('div', 'lib-table-wrap');
    const t = D.el('table', 'lib-table'); t.id = id;
    t.appendChild(D.el('caption', 'sr-only', caption));
    const head = D.el('thead'); const hr = D.el('tr');
    heads.forEach((h) => { const th = D.el('th', '', h); th.scope = 'col'; hr.appendChild(th); });
    head.appendChild(hr);
    const body = D.el('tbody');
    t.append(head, body); wrap.appendChild(t);
    return { wrap: wrap, body: body };
  }

  function checkbox(id, label, checked, onChange, hint) {
    const row = D.el('label', 'lib-radio');
    const cb = D.el('input'); cb.type = 'checkbox'; cb.id = id; cb.checked = checked;
    cb.addEventListener('change', () => onChange(cb.checked));
    const t = D.el('span', ''); t.append(D.el('strong', '', label));
    if (hint) t.appendChild(D.el('span', 'lib-sub', hint));
    row.append(cb, t);
    return row;
  }

  // ---- card 1: slice ----
  function slicePlanNode() {
    const out = D.el('div', 'lib-plan'); out.id = 'cpySlicePlanBox'; out.setAttribute('aria-live', 'polite');
    if (!dash.picked.size) {
      out.appendChild(D.el('p', 'note', 'Tick at least one dashboard to see what stays and what goes.'));
      return out;
    }
    if (!slicePlan) { out.appendChild(D.el('p', 'note', 'Checking ...')); return out; }
    if (slicePlan.error) {
      const e = D.el('p', 'lib-problem', slicePlan.error); e.id = 'cpySliceError'; out.appendChild(e);
      return out;
    }
    const sp = slicePlan;
    const sum = D.el('p', 'lib-plan-line'); sum.id = 'cpySliceSummary';
    sum.dataset.blocked = sp.integrity_count ? 'true' : 'false';
    sum.append(D.el('strong', '', 'Plan: '),
      'keep ' + D.plural(sp.kept_dashboards, 'dashboard') + ' and ' + D.plural(sp.kept_sheets, 'worksheet') +
      ', remove ' + D.plural(sp.removed_dashboards, 'dashboard') + ' and ' + D.plural(sp.removed_sheets, 'worksheet') + '.');
    out.appendChild(sum);
    const extra = [];
    if (sp.action_count) extra.push(D.plural(sp.action_count, 'action') + ' dropped or trimmed');
    if (sp.dropped_filters) extra.push(D.plural(sp.dropped_filters, 'filter') + ' dropped');
    const pr = sp.pruned;
    if (pr.calculations || pr.parameters || pr.datasources) {
      extra.push('then removed as unused: ' + D.plural(pr.calculations, 'calculation') + ', ' + D.plural(pr.parameters, 'parameter') + ', ' + D.plural(pr.datasources, 'datasource'));
    }
    if (extra.length) { const l = D.el('p', 'note', extra.join('; ') + '.'); l.id = 'cpySliceExtra'; out.appendChild(l); }
    if (sp.integrity_count) {
      out.appendChild(D.el('p', 'lib-problem', 'The result would have problems the original did not, so nothing is made:'));
      const ul = D.el('ul', 'sty-problems');
      sp.integrity.forEach((t) => ul.appendChild(D.el('li', '', t)));
      out.appendChild(ul);
    }
    const t = table('cpySliceTable', 'What is kept and what is removed, by name', ['Kind', 'Name', 'What happens']);
    sp.rows.forEach((r) => {
      const tr = D.el('tr'); tr.dataset.action = r.action;
      tr.append(D.el('td', '', r.kind), D.el('td', 'lib-name', r.name), D.el('td', 'lib-action', r.action === 'keep' ? 'Kept' : 'Removed'));
      t.body.appendChild(tr);
    });
    out.appendChild(t.wrap);
    out.appendChild(pager(sp, 'cpySlice', (last) => 'Rows ' + num(sp.offset + 1) + '–' + num(last) + ' of ' + num(sp.total),
      () => { slicePlanOffset = Math.max(0, slicePlanOffset - PAGE); loadSlicePlan(); },
      () => { slicePlanOffset += PAGE; loadSlicePlan(); }, sp.total));
    if (sp.action_count) {
      out.appendChild(D.el('h3', '', 'Actions that do not survive' + (sp.action_count > sp.actions.length ? ' (first ' + sp.actions.length + ' shown)' : '')));
      const a = table('cpySliceActions', 'Dashboard actions that are dropped or trimmed', ['Action', 'What happens', 'Why']);
      sp.actions.forEach((r) => {
        const tr = D.el('tr'); tr.dataset.action = r.action;
        tr.append(D.el('td', 'lib-name', r.caption), D.el('td', 'lib-action', r.action === 'drop' ? 'Dropped' : 'Trimmed'), D.el('td', 'lib-why', r.why));
        a.body.appendChild(tr);
      });
      out.appendChild(a.wrap);
    }
    return out;
  }

  function sliceCard() {
    const sec = D.el('section', 'lib-card'); sec.setAttribute('aria-labelledby', 'cpyH1');
    const h = D.el('h2', '', 'Slice: keep some dashboards'); h.id = 'cpyH1';
    sec.append(h, D.el('p', 'note', 'Tick the dashboards to keep. You get a new workbook with those dashboards, the worksheets on them and what they need; the other dashboards and sheets are removed, then calculations, parameters and datasources nothing uses any more. The open workbook is not changed and nothing is written on the machine that runs py-tbparse.'));
    sec.appendChild(dash.node());
    const opts = D.el('div', 'lib-policy-box');
    opts.append(
      checkbox('cpySliceStrict', 'Stop instead of dropping actions', strictSlice, (v) => { strictSlice = v; scheduleSlice(); draw('cpySliceStrict'); },
        'An action that points at a removed dashboard or sheet is normally dropped and listed. With this on, the slice stops instead.'),
      checkbox('cpySlicePrune', 'Remove unused calculations, parameters and datasources afterwards', prune, (v) => { prune = v; scheduleSlice(); draw('cpySlicePrune'); },
        'This also removes calculations that were already unused before the slice.'));
    sec.appendChild(opts);
    sec.appendChild(slicePlanNode());
    const go = D.el('button', 'btn primary', 'Download sliced workbook'); go.type = 'button'; go.id = 'cpySliceGo';
    go.disabled = busy || !slicePlan || !!slicePlan.error || !!slicePlan.integrity_count;
    go.addEventListener('click', async () => {
      busy = true; go.disabled = true;
      D.setStatus('Slicing ...', false, 'busy');
      try {
        const name = await save('/copy/slice-download', { dashboards: Array.from(dash.picked), strict: strictSlice, prune: prune }, 'workbook_sliced.twb');
        D.setStatus('Saved ' + name + ' with ' + D.plural(slicePlan.kept_dashboards, 'dashboard') + '. The open workbook is unchanged. Open the copy in Tableau before you rely on it: it was not opened in Tableau here.', false, 'ok');
      } catch (e) { D.fail(e, 'Nothing was saved'); }
      busy = false; draw('cpySliceGo');
    });
    const row = D.el('div', 'lib-go'); row.appendChild(go);
    sec.appendChild(row);
    return sec;
  }

  // ---- card 2: copy sheets ----
  function copyPlanNode() {
    const out = D.el('div', 'lib-plan'); out.id = 'cpyPlanBox'; out.setAttribute('aria-live', 'polite');
    if (!sheets.picked.size) {
      out.appendChild(D.el('p', 'note', 'Tick at least one worksheet to see what the copy would do.'));
      return out;
    }
    if (!copyPlan) { out.appendChild(D.el('p', 'note', 'Checking ...')); return out; }
    if (copyPlan.error) {
      const e = D.el('p', 'lib-problem', copyPlan.error); e.id = 'cpyPlanError'; out.appendChild(e);
      return out;
    }
    const cp = copyPlan;
    const sum = D.el('p', 'lib-plan-line'); sum.id = 'cpyPlanSummary';
    sum.dataset.blocked = cp.blocked ? 'true' : 'false';
    const counts = D.plural(cp.copied, 'sheet') + ' to copy, ' + cp.skipped + ' skipped, ' + cp.refused + ' refused.';
    sum.append(D.el('strong', '', cp.blocked ? 'Stopped: ' : 'Plan: '), cp.blocked ? cp.blocked_reason + ' (' + counts + ')' : counts);
    out.appendChild(sum);
    const t = table('cpyPlan', 'What the copy does, sheet by sheet', ['Worksheet', 'Datasource', 'What happens', 'Why or what is dropped']);
    cp.rows.forEach((r) => {
      const tr = D.el('tr'); tr.dataset.status = r.status;
      const nm = D.el('td', 'lib-name'); nm.appendChild(D.el('div', '', r.sheet));
      if (r.status === 'copy' && r.new_name !== r.sheet) nm.appendChild(D.el('div', 'lib-sub', 'copied as ' + r.new_name));
      tr.append(nm, D.el('td', '', r.datasource || '-'));
      const stopped = cp.blocked && r.status === 'copy';
      tr.appendChild(D.el('td', 'lib-action', stopped ? 'Not copied (stops)' : (STATUS_TEXT[r.status] || r.status)));
      const why = D.el('td', 'lib-why');
      if (r.reason) why.appendChild(D.el('div', '', r.reason));
      r.dropped.forEach((d) => why.appendChild(D.el('div', '', 'Dropped: ' + d)));
      tr.appendChild(why);
      t.body.appendChild(tr);
    });
    out.appendChild(t.wrap);
    out.appendChild(pager(cp, 'cpyPlan', (last) => 'Rows ' + num(cp.offset + 1) + '–' + num(last) + ' of ' + num(cp.total),
      () => { copyPlanOffset = Math.max(0, copyPlanOffset - PAGE); loadCopyPlan(); },
      () => { copyPlanOffset += PAGE; loadCopyPlan(); }, cp.total));
    if (cp.library_count) {
      out.appendChild(D.el('h3', '', 'Calculations and parameters the sheets need' + (cp.library_count > cp.library.length ? ' (first ' + cp.library.length + ' of ' + num(cp.library_count) + ')' : '')));
      const l = table('cpyLibrary', 'Calculations and parameters added to the target', ['Name', 'Kind', 'What happens', 'Why']);
      cp.library.forEach((r) => {
        const tr = D.el('tr'); tr.dataset.action = r.action;
        const nm = D.el('td', 'lib-name'); nm.appendChild(D.el('div', '', r.caption || r.name));
        tr.append(nm, D.el('td', '', KIND_TEXT[r.kind] || r.kind), D.el('td', 'lib-action', LIB_TEXT[r.action] || r.action), D.el('td', 'lib-why', r.reason));
        l.body.appendChild(tr);
      });
      out.appendChild(l.wrap);
    }
    return out;
  }

  function policyBlock() {
    const fs = D.el('fieldset', 'lib-policy'); fs.id = 'cpyPolicy';
    fs.appendChild(D.el('legend', '', 'If a calculation, parameter or sheet name is already in the target'));
    POLICIES.forEach(([v, title, text]) => {
      const row = D.el('label', 'lib-radio');
      const r = D.el('input'); r.type = 'radio'; r.name = 'cpyPolicy'; r.value = v; r.checked = policy === v;
      r.addEventListener('change', () => { policy = v; scheduleCopy(); draw(); });
      const t = D.el('span', ''); t.append(D.el('strong', '', title), D.el('span', 'lib-sub', text));
      row.append(r, t); fs.appendChild(row);
    });
    return fs;
  }

  function fileBlock() {
    const box = D.el('div', 'lib-file');
    const pick = D.el('label', 'btn'); pick.setAttribute('for', 'cpyFile');
    pick.textContent = target ? 'Choose another target workbook' : 'Choose the target workbook';
    const input = D.el('input'); input.type = 'file'; input.id = 'cpyFile'; input.accept = '.twb,.twbx';
    input.className = 'sr-only';
    input.addEventListener('change', () => { if (input.files && input.files[0]) upload(input.files[0]); });
    input.addEventListener('focus', () => pick.classList.add('focus'));
    input.addEventListener('blur', () => pick.classList.remove('focus'));
    box.append(pick, input);
    if (target) {
      const info = D.el('p', 'lib-loaded'); info.id = 'cpyLoaded';
      info.append(D.el('strong', '', target.file), ': ' + D.plural(target.worksheets, 'worksheet') + ', ' + D.plural(target.dashboards, 'dashboard'));
      box.appendChild(info);
    } else {
      box.appendChild(D.el('p', 'note', 'A .twb or .twbx. The sheets are copied into a copy of it; the file you choose is not changed.'));
    }
    return box;
  }

  function copyCard() {
    const sec = D.el('section', 'lib-card'); sec.setAttribute('aria-labelledby', 'cpyH2');
    const h = D.el('h2', '', 'Copy sheets into another workbook'); h.id = 'cpyH2';
    sec.append(h, D.el('p', 'note', 'Tick worksheets of the open workbook and choose the workbook to copy them into. A sheet needs a datasource that the target already has under the same internal name; missing calculations and parameters are added. Dashboards and actions are not copied. You get a new copy of the target to download, and the open workbook and the target are not changed.'));
    sec.appendChild(fileBlock());
    sec.appendChild(sheets.node());
    if (!target) {
      sec.appendChild(D.el('p', 'note', 'Choose the target workbook to see the plan.'));
      return sec;
    }
    sec.appendChild(policyBlock());
    const opts = D.el('div', 'lib-policy-box');
    opts.appendChild(checkbox('cpyStrict', 'Stop instead of dropping', strictCopy, (v) => { strictCopy = v; scheduleCopy(); draw('cpyStrict'); },
      'Action filters and tooltip sheets that are not copied are normally dropped and listed. With this on, the copy stops instead.'));
    sec.appendChild(opts);
    sec.appendChild(copyPlanNode());
    const go = D.el('button', 'btn primary', 'Download new workbook'); go.type = 'button'; go.id = 'cpyGo';
    go.disabled = busy || !copyPlan || !!copyPlan.error || !!copyPlan.blocked || !copyPlan.will_copy;
    go.addEventListener('click', async () => {
      busy = true; go.disabled = true;
      D.setStatus('Copying the sheets ...', false, 'busy');
      try {
        const name = await save('/copy/download', { sheets: Array.from(sheets.picked), on_clash: policy, strict: strictCopy }, 'workbook_sheetcopy.twb');
        D.setStatus('Saved ' + name + ': ' + D.plural(copyPlan.will_copy, 'sheet') + ' copied. The open workbook and the target are unchanged. Open the copy in Tableau before you rely on it: it was not opened in Tableau here.', false, 'ok');
      } catch (e) { D.fail(e, 'Nothing was saved'); }
      busy = false; draw('cpyGo');
    });
    const row = D.el('div', 'lib-go'); row.appendChild(go);
    if (copyPlan && !copyPlan.error && copyPlan.blocked) row.appendChild(D.el('span', 'note', 'Choose Rename or Skip above to go on.'));
    else if (copyPlan && !copyPlan.error && !copyPlan.will_copy) row.appendChild(D.el('span', 'note', 'No sheet can be copied with these choices.'));
    sec.appendChild(row);
    return sec;
  }

  function draw(focusId) {
    const wrap = D.$('tableWrap');
    const active = focusId || (document.activeElement && wrap.contains(document.activeElement) ? document.activeElement.id : '');
    const caret = /Text$/.test(active) && document.activeElement && document.activeElement.id === active ? document.activeElement.selectionStart : null;
    const panel = D.el('div', 'lib');
    panel.append(sliceCard(), copyCard());
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

  async function loadSlicePlan() {
    const mine = ++sliceReq;
    if (!dash.picked.size) { slicePlan = null; draw(); return; }
    slicePlan = null;
    draw();
    try {
      const res = await post('/copy/slice-plan', { dashboards: Array.from(dash.picked), strict: strictSlice, prune: prune, offset: slicePlanOffset, limit: PAGE });
      const data = await res.json();
      if (mine !== sliceReq) return;
      slicePlan = res.ok ? data : { error: data.error || res.statusText };
    } catch (e) {
      if (mine !== sliceReq) return;
      slicePlan = { error: String(e.message || e) };
    }
    draw();
  }

  async function loadCopyPlan() {
    const mine = ++copyReq;
    if (!target || !sheets.picked.size) { copyPlan = null; draw(); return; }
    copyPlan = null;
    draw();
    try {
      const res = await post('/copy/plan', { sheets: Array.from(sheets.picked), on_clash: policy, strict: strictCopy, offset: copyPlanOffset, limit: PAGE });
      const data = await res.json();
      if (mine !== copyReq) return;
      copyPlan = res.ok ? data : { error: data.error || res.statusText };
    } catch (e) {
      if (mine !== copyReq) return;
      copyPlan = { error: String(e.message || e) };
    }
    draw();
  }

  function upload(f) {
    D.setStatus('Reading ' + f.name + ' ...', false, 'busy');
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/copy/upload');
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.setRequestHeader('X-Filename', encodeURIComponent(f.name));
    xhr.onerror = () => D.fail(new Error('the upload did not go through'), 'Nothing was copied');
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        target = data.target; copyPlan = null; copyPlanOffset = 0;
        D.setStatus('Read ' + f.name + '. Tick the sheets to copy and check the plan before you download.', false, 'ok');
        draw('cpyFile');
        loadCopyPlan();
      } else {
        D.fail(new Error(data.error || xhr.statusText), 'Nothing was copied');
      }
    };
    xhr.send(f);
  }

  function reset() {
    busy = false; target = null; policy = 'fail'; strictCopy = false; strictSlice = false; prune = true;
    slicePlan = null; copyPlan = null; slicePlanOffset = 0; copyPlanOffset = 0;
    sliceReq++; copyReq++; clearTimeout(sliceTimer); clearTimeout(copyTimer);
    if (dash) { dash.reset(); sheets.reset(); }
  }

  // Called by app.js when the view is chosen; resolves once the lists are on the page.
  async function render() {
    D.$('exportLink').hidden = true;
    if (!dash) makePickers();
    if (!target) {
      try { const st = await D.fetchJSON('/copy/state'); target = st.target; } catch (e) { /* the lists report their own errors */ }
    }
    try {
      await Promise.all([dash.load(), sheets.load()]);
    } catch (e) {
      D.fail(e);
      return;
    }
    D.$('meta').textContent = D.plural(dash.page.total, 'dashboard') + ', ' + D.plural(sheets.page.total, 'worksheet');
    draw();
    D.$('announce').textContent = 'Slice and copy: ' + D.plural(dash.page.total, 'dashboard') + ' and ' + D.plural(sheets.page.total, 'worksheet') + ' listed';
    if (dash.picked.size && !slicePlan) loadSlicePlan();
    if (target && sheets.picked.size && !copyPlan) loadCopyPlan();
  }

  window.CopyView = { init: init, render: render, reset: reset, pageSize: PAGE };
})();
