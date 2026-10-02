const $ = (id) => document.getElementById(id);
const statusEl = $('status');

// Sidebar grouping. Tables missing here (new ones added to _tables.py)
// still show up, under "Other", so the registry stays the source of truth.
const GROUPS = [
  ['Workbook', ['overview', 'published-refs']],
  ['Data', ['datasources', 'parameters', 'fields', 'raw-fields', 'calculated-fields', 'field-usage', 'missing-references', 'field-renames']],
  ['Data model', ['relationships', 'joins', 'relations', 'inferred-relationships', 'graph']],
  ['Dashboards', ['dashboards', 'dashboard-sheets']],
  ['SQL', ['custom-sql', 'initial-sql']],
];

const INFO = {
  'overview': ['Overview', 'Counts of everything parsed from the workbook.'],
  'datasources': ['Datasources', 'Connections and their primary tables.'],
  'parameters': ['Parameters', 'Workbook parameters and their current values.'],
  'fields': ['Fields', 'Every column across all datasources.'],
  'raw-fields': ['Raw fields', 'Columns that come straight from the source.'],
  'calculated-fields': ['Calculated fields', 'Calculations and their formulas.'],
  'field-usage': ['Field usage', 'Which worksheets, dashboards and calculations use each field.'],
  'missing-references': ['Missing references', 'Calculations that name a field the workbook does not have.'],
  'field-renames': ['Field renames', 'Suggested clean names. Create a copy of the workbook with them applied.'],
  'joins': ['Joins', 'Join clauses from the physical layer.'],
  'relations': ['Relations', 'Physical tables and custom SQL relations.'],
  'relationships': ['Relationships', 'Logical-layer relationships (Tableau 2020.2+).'],
  'inferred-relationships': ['Inferred relationships', 'Likely links guessed from matching field names.'],
  'dashboards': ['Dashboards', 'Dashboards defined in the workbook.'],
  'dashboard-sheets': ['Dashboard sheets', 'Sheets placed on each dashboard, with positions.'],
  'custom-sql': ['Custom SQL', 'Relations defined by custom SQL.'],
  'initial-sql': ['Initial SQL', 'SQL run when a connection opens.'],
  'published-refs': ['Published sources', 'References to published datasources.'],
  'graph': ['Relationship graph', 'Joins and relationships as Graphviz DOT.'],
};

// Overview columns that have a table of their own to jump to.
const OVERVIEW_LINKS = {
  datasources: 'datasources', parameters: 'parameters', relationships: 'relationships',
  // raw_fields counts every field (as upstream R does), so it opens Fields.
  calculated_fields: 'calculated-fields', raw_fields: 'fields',
  inferred_relationships: 'inferred-relationships', dashboards: 'dashboards',
};

const CODE_COLUMNS = new Set(['formula', 'custom_sql', 'initial_sql', 'connection_target']);

const state = { table: 'overview', columns: [], data: [], sortCol: -1, sortDir: 0,
                loaded: false, uploaded: false, req: 0, dot: '', fresh: false, dsLabels: {}, hay: null, hayKey: '',
                colLower: {}, sortKeys: {}, numeric: {}, natural: null, drawerIdx: null,
                drawerInfo: null, drawerOpener: null, graph: {nodes: [], edges: []} };
let filterTimer = null;
let toastTimer = null;

// The status element is both the live region and a toast. kind 'ok' fades after a few seconds,
// 'busy' and errors stay until the next message or a click. The text is kept after it fades.
function toastMs() { return typeof window.TOAST_MS === 'number' ? window.TOAST_MS : 4500; }
function hideToast() { statusEl.classList.remove('show'); }
function setStatus(msg, isErr, kind) {
  clearTimeout(toastTimer);
  statusEl.textContent = msg || '';
  statusEl.classList.toggle('err', !!isErr);
  statusEl.classList.toggle('ok', kind === 'ok');
  statusEl.classList.toggle('show', !!msg);
  if (msg && kind === 'ok') toastTimer = setTimeout(hideToast, toastMs());
}
function fail(e, note) {
  setStatus('That didn\u2019t work: ' + e.message + (note ? '. ' + note : ''), true);
}
statusEl.addEventListener('click', hideToast);

// The skip link moves focus without touching the URL hash, which remembers the current table.
document.querySelector('.skip').addEventListener('click', (e) => {
  e.preventDefault();
  $('main').focus();
});

// A view fades in when you switch to it (not on every filter keystroke), and screen readers hear
// where they landed, without moving focus out of the sidebar.
function playEnter(node) {
  node.classList.remove('enter');
  void node.offsetWidth;
  node.classList.add('enter');
}
function finishView(fresh, node, message) {
  if (!fresh) return;
  playEnter(node);
  $('announce').textContent = message;
}
function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
function showSkeleton() {
  const wrap = $('tableWrap');
  wrap.innerHTML = '';
  const box = el('div', 'skeleton');
  box.setAttribute('aria-hidden', 'true');
  for (let i = 0; i < 8; i++) box.appendChild(el('div', 'row'));
  wrap.appendChild(box);
}

async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function titleOf(name) { return (INFO[name] || [name])[0]; }

function allTables() { return (window.TABLE_NAMES || []).concat(['graph']); }

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function populateTables() {
  const names = allTables();
  const sel = $('tableSel');
  sel.innerHTML = '';
  names.forEach((name) => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = titleOf(name);
    sel.appendChild(opt);
  });

  const nav = $('nav');
  nav.innerHTML = '';
  const placed = new Set();
  const groups = GROUPS.map(([title, items]) => {
    const present = items.filter((n) => names.includes(n));
    present.forEach((n) => placed.add(n));
    return [title, present];
  });
  const other = names.filter((n) => !placed.has(n));
  if (other.length) groups.push(['Other', other]);

  groups.forEach(([title, items]) => {
    if (!items.length) return;
    nav.appendChild(el('div', 'label nav-group', title));
    items.forEach((name) => {
      const item = el('button', 'nav-item');
      item.type = 'button';
      item.dataset.table = name;
      item.appendChild(el('span', '', titleOf(name)));
      // The overview is always one row and the graph is not a table.
      if (name !== 'overview' && name !== 'graph') {
        const count = el('span', 'count');
        count.dataset.countFor = name;
        item.appendChild(count);
      }
      item.addEventListener('click', () => selectTable(name));
      nav.appendChild(item);
    });
  });
  if (window.APP_VERSION) $('version').textContent = 'v' + window.APP_VERSION;
}

function setCounts(counts) {
  document.querySelectorAll('[data-count-for]').forEach((node) => {
    const n = counts ? counts[node.dataset.countFor] : undefined;
    node.textContent = (n === undefined || n === null) ? '' : String(n);
    node.classList.toggle('zero', n === 0);
  });
}

function markCurrent() {
  document.querySelectorAll('.nav-item').forEach((item) => {
    if (item.dataset.table === state.table) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  });
  $('tableSel').value = state.table;
}

function selectTable(name) {
  if (!allTables().includes(name)) return;
  const changed = name !== state.table;
  state.table = name;
  clearTimeout(filterTimer);
  closeMenu(false);
  closeDrawer(false);
  if (changed) {
    $('filter').value = ''; state.sortCol = -1; state.sortDir = 0; state.fresh = true;
    $('colsBtn').textContent = 'Columns';   // the old table hidden count must not linger while the new one loads
  }
  markCurrent();
  if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
  showTable();
}

// Plain words for the errors a person can run into when opening a file.
function friendlyOpenError(message) {
  const m = String(message || '');
  if (/No such file|not found|FileNotFound/i.test(m)) return m + '. Check the path, or drop the file onto the page instead.';
  if (/BadZipFile|not a zip|zip archive/i.test(m)) return 'that .twbx is damaged or not a zip archive.';
  if (/no \.twb|No .*twb.* in/i.test(m)) return 'there is no workbook (.twb) inside that .twbx.';
  return m;
}

function recentPaths() {
  try {
    const list = JSON.parse(localStorage.getItem('py-tbparse:recent') || '[]');
    return Array.isArray(list) ? list.filter((p) => typeof p === 'string').slice(0, 8) : [];
  } catch (e) { return []; }
}
function saveRecent(list) {
  try { localStorage.setItem('py-tbparse:recent', JSON.stringify(list.slice(0, 8))); } catch (e) { /* private window */ }
}
function rememberRecent(path) {
  if (!path) return;
  saveRecent([path].concat(recentPaths().filter((p) => p !== path)));
  renderRecent();
}
function forgetRecent(path) {
  saveRecent(recentPaths().filter((p) => p !== path));
  renderRecent();
}
function baseName(path) { return path.split(/[\\/]/).filter(Boolean).pop() || path; }
function renderRecent() {
  const list = recentPaths();
  $('recent').hidden = !list.length;
  const ul = $('recentList');
  ul.innerHTML = '';
  list.forEach((path) => {
    const li = el('li');
    const open = el('button', 'open-recent', baseName(path));
    open.type = 'button';
    open.title = path;
    const dir = el('small', '', path.slice(0, path.length - baseName(path).length).replace(/[\\/]$/, ''));
    open.appendChild(dir);
    open.addEventListener('click', () => { $('path').value = path; loadWorkbook(); });
    const forget = el('button', 'forget', '\u00d7');
    forget.type = 'button';
    forget.setAttribute('aria-label', 'Forget ' + baseName(path));
    forget.addEventListener('click', () => { forgetRecent(path); });
    li.appendChild(open);
    li.appendChild(forget);
    ul.appendChild(li);
  });
}

// Show a freshly opened workbook. `request` resolves to the /load or /upload answer.
async function openWorkbook(label, request) {
  setStatus('Opening ' + label + ' ...', false, 'busy');
  const btn = $('loadBtn');
  btn.disabled = true; btn.textContent = 'Opening';
  try {
    const data = await request();
    setStatus('Opened ' + (data.name || data.path), false, 'ok');
    state.loaded = true;
    state.uploaded = !!data.uploaded;
    $('uploadNote').hidden = !state.uploaded;
    $('createBtn').hidden = state.uploaded;
    $('empty').hidden = true;
    $('controls').hidden = false;
    $('wbName').textContent = data.name || data.path;
    $('wbName').title = data.path || data.name;
    document.title = (data.name || 'workbook') + ' - py-tbparse';
    setCounts(data.counts);
    state.dsLabels = data.datasource_labels || {};
    Object.keys(views).forEach((name) => { delete views[name]; });
    const dsSel = $('renameDs');
    dsSel.innerHTML = '<option value="">(all datasources)</option>';
    (data.datasources || []).forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name; opt.textContent = name;
      dsSel.appendChild(opt);
    });
    const dashSel = $('dashboardSel');
    dashSel.innerHTML = '<option value="">(all)</option>';
    (data.dashboards || []).forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name; opt.textContent = name;
      dashSel.appendChild(opt);
    });
    const fromHash = decodeURIComponent(location.hash.slice(1));
    if (allTables().includes(fromHash)) state.table = fromHash;
    markCurrent();
    state.fresh = true;
    await showTable();
    if (!data.uploaded) rememberRecent(data.path);
  } catch (e) {
    setStatus('That didn\u2019t work: ' + friendlyOpenError(e.message), true);
  } finally {
    btn.disabled = false; btn.textContent = 'Load';
  }
}

async function loadWorkbook() {
  const path = $('path').value.trim();
  if (!path) { setStatus('Enter a workbook path first, or drop a file onto the page.', true); return; }
  await openWorkbook(path, () => fetchJSON('/load', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path}),
  }));
}

const MAX_UPLOAD_MB = 200;
function uploadFile(file) {
  const name = file.name || 'workbook';
  if (!/\.(twb|twbx)$/i.test(name)) { setStatus('That didn\u2019t work: only .twb and .twbx files can be opened.', true); return Promise.resolve(); }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    setStatus('That didn\u2019t work: ' + name + ' is ' + Math.round(file.size / 1048576) + ' MB; the limit is ' + MAX_UPLOAD_MB + ' MB.', true);
    return Promise.resolve();
  }
  $('path').value = '';
  return openWorkbook(name, () => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/upload');
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.setRequestHeader('X-Filename', encodeURIComponent(name));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && file.size > 5 * 1048576) {
        setStatus('Opening ' + name + ' (' + Math.round(100 * e.loaded / e.total) + '%) ...', false, 'busy');
      }
    };
    xhr.onerror = () => reject(new Error('the upload did not go through'));
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(data.error || xhr.statusText));
    };
    xhr.send(file);
  }));
}

async function showTable() {
  const name = state.table;
  const isGraph = name === 'graph';
  const isOverview = name === 'overview';
  $('viewTitle').textContent = titleOf(name);
  $('viewDesc').textContent = (INFO[name] || ['', ''])[1];
  $('dashboardWrap').hidden = name !== 'dashboard-sheets';
  $('paramsWrap').hidden = name !== 'calculated-fields';
  $('inferredWrap').hidden = !isGraph;
  $('copyBtn').hidden = !isGraph;
  $('renameTools').hidden = name !== 'field-renames';
  $('filter').hidden = isGraph || isOverview;
  $('hint').hidden = isGraph || isOverview;
  $('exportBtn').textContent = isGraph ? 'Export DOT' : 'Export CSV';
  $('colsBtn').hidden = isGraph || isOverview;
  $('densityBtn').hidden = isGraph || isOverview;
  if (isGraph || isOverview) $('chips').hidden = true;
  const req = ++state.req;
  const fresh = state.fresh;
  state.fresh = false;
  // A quick answer never flashes a skeleton; a slow one gets calm placeholder rows.
  const loadingTimer = setTimeout(() => { if (req === state.req) showSkeleton(); }, 180);
  const failed = (e) => {
    clearTimeout(loadingTimer);
    if ($('tableWrap').querySelector('.skeleton')) $('tableWrap').innerHTML = '';
    fail(e);
  };

  if (isGraph) {
    const params = new URLSearchParams();
    if ($('includeInferred').checked) params.set('include_inferred', 'true');
    // Set before the request so the link never points at the previous view.
    $('exportLink').href = '/graph?' + params.toString() + '&download=1';
    try {
      const data = await fetchJSON('/graph?' + params.toString());
      clearTimeout(loadingTimer);
      if (req !== state.req) return;
      state.dot = data.dot;
      state.graph = data.graph || {nodes: [], edges: []};
      const wrap = $('tableWrap');
      renderGraphView(wrap);
      finishView(fresh, wrap, 'Showing the relationship graph, ' + plural(state.graph.nodes.length, 'table') + ', ' +
                 plural(state.graph.edges.length, 'connection'));
    } catch (e) {
      failed(e);
    }
    return;
  }

  const params = new URLSearchParams({name});
  if (name === 'dashboard-sheets' && $('dashboardSel').value) {
    params.set('dashboard', $('dashboardSel').value);
  }
  if (name === 'calculated-fields' && $('includeParams').checked) {
    params.set('include_parameters', 'true');
  }
  if (name === 'field-renames') {
    const opts = renameOptions();
    Object.entries(opts).forEach(([k, v]) => { if (v) params.set(k, v); });
    if ($('renameChanged').checked) params.set('only_changed', 'true');
    $('downloadBtn').href = '/download-workbook?' + new URLSearchParams(opts).toString();
  }
  $('exportLink').href = '/export?' + params.toString();
  try {
    const data = await fetchJSON('/table?' + params.toString());
    clearTimeout(loadingTimer);
    if (req !== state.req) return;
    const sortedName = state.sortCol >= 0 ? state.columns[state.sortCol] : null;
    state.columns = data.columns || [];
    state.data = data.data || [];
    state.sortCol = sortedName === null ? -1 : state.columns.indexOf(sortedName);
    if (state.sortCol < 0) state.sortDir = 0;
    resetCaches();
    if (isOverview) renderOverview();
    else { renderTable(); scheduleHay(); }
    finishView(fresh, $('tableWrap'),
               'Showing ' + titleOf(name) + (isOverview ? '' : ', ' + plural(state.data.length, 'row')));
  } catch (e) {
    failed(e);
  }
}

function renameOptions() {
  const opts = {style: $('renameStyle').value};
  if ($('renameDs').value) opts.datasource = $('renameDs').value;
  if ($('renameKinds').value) opts.kinds = $('renameKinds').value;
  const ref = $('renameRef').value.trim();
  if (ref) opts.reference = ref;
  return opts;
}

async function createWorkbook() {
  const btn = $('createBtn');
  btn.disabled = true;
  setStatus('Making your fixed copy ...', false, 'busy');
  try {
    const data = await fetchJSON('/create-workbook', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(renameOptions()),
    });
    setStatus('Saved a fixed copy next to your original (' + plural(data.renamed, 'change') + '): ' + data.path,
              false, 'ok');
  } catch (e) {
    fail(e, 'Your original is untouched');
  } finally {
    btn.disabled = false;
  }
}

function renderOverview() {
  const wrap = $('tableWrap');
  wrap.innerHTML = '';
  $('meta').textContent = 'Summary';
  const row = state.data[0] || [];
  const cards = el('div', 'cards');
  state.columns.forEach((col, i) => {
    if (col === 'file') return;
    const target = OVERVIEW_LINKS[col];
    const value = row[i];
    const card = el(target ? 'button' : 'div', 'stat');
    if (target) {
      card.type = 'button';
      card.dataset.goto = target;
      card.addEventListener('click', () => selectTable(target));
    }
    if (value === 0) card.classList.add('zero');
    card.append(el('div', 'n', value === null ? '-' : String(value)),
                el('div', 'l', col.split('_').join(' ')));
    cards.appendChild(card);
  });
  wrap.appendChild(cards);
  fillReport(wrap, cards);
}

// ---- the report card: a sentence about the workbook, what deserves a look, what is on the dashboards ------

const SEVERITY = {
  problem: ['\u2716', 'Problem'],
  warning: ['\u25B2', 'Needs a look'],
  info: ['\u2022', 'Worth knowing'],
};

// Open a table with column filters already on, so a count on the card lands on exactly its rows.
function openWithFilters(table, filters) {
  const v = viewFor(table);
  v.filters = (filters || []).map((f) => ({col: f.col, text: f.text}));
  if (state.table === table) { showTable(); return; }
  selectTable(table);
}

async function fillReport(wrap, cards) {
  let rep;
  try { rep = await fetchJSON('/overview'); } catch (e) { return; }
  if (state.table !== 'overview' || !cards.isConnected) return;
  const lead = el('p', 'lead', rep.summary);
  wrap.insertBefore(lead, cards);

  const heading = el('h2', 'section-title', 'Worth a look');
  heading.id = 'healthTitle';
  const list = el('ul', 'health');
  list.setAttribute('aria-labelledby', 'healthTitle');
  const serious = rep.health.filter((h) => h.severity !== 'info');
  if (!serious.length) {
    const ok = el('li', 'health-item ok');
    ok.append(el('span', 'sev', '\u2713'), el('div', 'health-text', 'All clear. No broken relationships, missing references or unused calculations.'));
    list.appendChild(ok);
  }
  rep.health.forEach((h) => {
    const [icon, word] = SEVERITY[h.severity] || SEVERITY.info;
    const li = el('li', 'health-item ' + h.severity);
    const sev = el('span', 'sev', icon);
    sev.setAttribute('aria-hidden', 'true');
    const text = el('div', 'health-text');
    text.append(el('span', 'sr-only', word + ': '), el('strong', '', h.title));
    if (h.detail) text.append(el('span', 'health-detail', h.detail));
    li.append(sev, text);
    if (h.table) {
      const go = el('button', 'btn small health-go', 'Show');
      go.type = 'button';
      go.dataset.health = h.id;
      go.setAttribute('aria-label', 'Show the rows: ' + h.title);
      go.addEventListener('click', () => openWithFilters(h.table, h.filters));
      li.appendChild(go);
    }
    list.appendChild(li);
  });
  wrap.append(heading, list);

  if (rep.dashboards.length || rep.worksheets.length) {
    const title = el('h2', 'section-title', 'On the dashboards');
    title.id = 'dashTitle';
    const grid = el('div', 'dash-grid');
    grid.setAttribute('role', 'list');
    grid.setAttribute('aria-labelledby', 'dashTitle');
    rep.dashboards.forEach((d) => {
      const card = el('div', 'dash-card');
      card.setAttribute('role', 'listitem');
      card.append(el('h3', '', d.name), el('div', 'dash-count', plural(d.sheets.length, 'worksheet')));
      const ul = el('ul', 'dash-sheets');
      d.sheets.slice(0, 6).forEach((s) => ul.appendChild(el('li', '', s)));
      if (d.sheets.length > 6) ul.appendChild(el('li', 'more', 'and ' + (d.sheets.length - 6) + ' more'));
      card.appendChild(ul);
      grid.appendChild(card);
    });
    if (!rep.dashboards.length) grid.appendChild(el('p', 'quiet', 'No dashboards. ' + plural(rep.worksheets.length, 'worksheet') + ' on their own.'));
    wrap.append(title, grid);
  }
}

// ---- the table: filtering, sorting and windowed rendering ---------------------------------------------

const COLLATOR = new Intl.Collator(undefined, {numeric: true, sensitivity: 'base'});
const OPAQUE_ID = /^[a-z]+\.[0-9a-z]{20,}$/;
const views = {};  // per table: hidden columns, widths, the pinned column, column filters
let hayJob = 0;

// Column settings are remembered by column NAME, not by position. A table can change shape (Field renames
// gains a kind column in front when you widen it to the whole report), and a setting for a column that is
// not there waits, unused, until it is. Names are the keys of hidden, widths, auto and pinned, and the
// col of every filter.
function colIndex(name) { return state.columns.indexOf(name); }
function liveFilters(v) { return v.filters.filter((f) => colIndex(f.col) >= 0); }
function hiddenCount(v) { return state.columns.filter((name) => v.hidden.has(name)).length; }

function viewFor(name) {
  if (!views[name]) views[name] = {hidden: new Set(), widths: {}, auto: {}, pinned: null, filters: []};
  return views[name];
}

function reducedMotion() {
  return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

function displayCols(v) {
  const shown = state.columns.map((_, i) => i).filter((i) => !v.hidden.has(state.columns[i]));
  const pin = v.pinned === null ? -1 : colIndex(v.pinned);
  if (pin >= 0 && shown.includes(pin)) return [pin].concat(shown.filter((i) => i !== pin));
  return shown;
}

// A datasource is shown by its caption when it has one, and an unreadable internal id is shortened.
// The full id is always in the tooltip, the details drawer and anything you copy.
function friendlyDatasource(value) {
  const caption = state.dsLabels[value];
  if (caption) return caption;
  if (OPAQUE_ID.test(value)) {
    const dot = value.indexOf('.');
    return value.slice(0, dot + 7) + '…' + value.slice(-4);
  }
  return value;
}

function shownText(col, value) {
  if (value === null || value === undefined) return '';
  return col === 'datasource' ? friendlyDatasource(String(value)) : String(value);
}

// What the search matches: the readable label and the real value.
function searchText(col, value) {
  if (value === null || value === undefined) return '';
  const raw = String(value);
  return col === 'datasource' ? shownText(col, value) + ' ' + raw : raw;
}

function autoWidth(ci, v) {
  const col = state.columns[ci];
  if (v.auto[col]) return v.auto[col];
  let longest = col.length + 8;  // room for the sort arrow and the options button
  const sample = Math.min(state.data.length, 300);
  for (let i = 0; i < sample; i++) {
    const len = shownText(col, state.data[i][ci]).length;
    if (len > longest) longest = len;
  }
  v.auto[col] = Math.max(96, Math.min(Math.round(longest * 7.6) + 30, 380));
  return v.auto[col];
}

function widthsFor(v) {
  const out = {};
  state.columns.forEach((name, ci) => { out[ci] = v.widths[name] || autoWidth(ci, v); });
  return out;
}

function resetCaches() {
  hayJob += 1;
  state.hay = null;
  state.hayKey = '';
  state.colLower = {};
  state.sortKeys = {};
  state.numeric = {};
  state.natural = null;
  state.drawerIdx = null;
  Object.keys(views).forEach((name) => { views[name].auto = {}; });  // new data, new widths
  closeDrawer(false);
}

function visibleSig(v) { return state.columns.filter((name) => v.hidden.has(name)).sort().join(','); }

function rowHay(row, cols) {
  let text = '';
  for (let k = 0; k < cols.length; k++) text += searchText(state.columns[cols[k]], row[cols[k]]) + '\u0001';
  return text.toLowerCase();
}

// One lowercase string per row, so a filter keystroke is a single scan. Built in small slices right
// after a table is drawn, so it never blocks the page; ensureHay finishes it at once if you type first.
function scheduleHay() {
  const v = viewFor(state.table);
  const sig = visibleSig(v);
  const cols = state.columns.map((_, i) => i).filter((i) => !v.hidden.has(state.columns[i]));
  const rows = state.data;
  const hay = new Array(rows.length);
  const job = ++hayJob;
  state.hay = null;
  state.hayKey = '';
  let at = 0;
  const step = () => {
    if (job !== hayJob) return;
    const stop = Math.min(at + 4000, rows.length);
    for (; at < stop; at++) hay[at] = rowHay(rows[at], cols);
    if (at < rows.length) setTimeout(step, 0);
    else { state.hay = hay; state.hayKey = sig; }
  };
  setTimeout(step, 0);
}

function ensureHay(v) {
  const sig = visibleSig(v);
  if (state.hay && state.hayKey === sig) return state.hay;
  hayJob += 1;
  const cols = state.columns.map((_, i) => i).filter((i) => !v.hidden.has(state.columns[i]));
  state.hay = state.data.map((row) => rowHay(row, cols));
  state.hayKey = sig;
  return state.hay;
}

function colLowerFor(ci) {
  if (!state.colLower[ci]) {
    const col = state.columns[ci];
    state.colLower[ci] = state.data.map((row) => searchText(col, row[ci]).toLowerCase());
  }
  return state.colLower[ci];
}

function naturalOrder() {
  if (!state.natural || state.natural.length !== state.data.length) {
    state.natural = Array.from({length: state.data.length}, (_, i) => i);
  }
  return state.natural;
}

function isNumericColumn(ci) {
  if (state.numeric[ci] === undefined) {
    let seen = false;
    let all = true;
    for (let i = 0; i < state.data.length && all; i++) {
      const x = state.data[i][ci];
      if (x === null) continue;
      seen = true;
      if (typeof x !== 'number') all = false;
    }
    state.numeric[ci] = seen && all;
  }
  return state.numeric[ci];
}

function sortKeys(ci) {
  if (!state.sortKeys[ci]) {
    state.sortKeys[ci] = state.data.map((row) => (row[ci] === null ? null : String(row[ci])));
  }
  return state.sortKeys[ci];
}

// Nulls always sort last, whichever way the column is sorted.
function sortOrder(order, ci, dir) {
  const rows = state.data;
  const sorted = order.slice();
  if (isNumericColumn(ci)) {
    sorted.sort((a, b) => {
      const x = rows[a][ci];
      const y = rows[b][ci];
      if (x === null || y === null) return (x === null) - (y === null);
      return dir * (x - y);
    });
  } else {
    const keys = sortKeys(ci);
    sorted.sort((a, b) => {
      const x = keys[a];
      const y = keys[b];
      if (x === null || y === null) return (x === null) - (y === null);
      return dir * COLLATOR.compare(x, y);
    });
  }
  return sorted;
}

// The rows to show, as indexes into state.data: the search box, then the column filters, then the sort.
function computeOrder() {
  const v = viewFor(state.table);
  const n = state.data.length;
  let order = null;
  const q = $('filter').value.trim().toLowerCase();
  if (q) {
    const hay = ensureHay(v);
    order = [];
    for (let i = 0; i < n; i++) if (hay[i].indexOf(q) !== -1) order.push(i);
  }
  liveFilters(v).forEach((f) => {
    const col = colLowerFor(colIndex(f.col));
    const text = f.text.toLowerCase();
    const next = [];
    if (order) {
      for (let k = 0; k < order.length; k++) if (col[order[k]].indexOf(text) !== -1) next.push(order[k]);
    } else {
      for (let i = 0; i < n; i++) if (col[i].indexOf(text) !== -1) next.push(i);
    }
    order = next;
  });
  if (!order) order = naturalOrder();
  if (state.sortCol >= 0) order = sortOrder(order, state.sortCol, state.sortDir);
  return order;
}

function toggleSort(i) {
  if (state.sortCol !== i) { state.sortCol = i; state.sortDir = 1; }
  else if (state.sortDir === 1) { state.sortDir = -1; }
  else { state.sortCol = -1; state.sortDir = 0; }
  // The table is rebuilt, which destroys the focused header; put focus back so Enter flips the direction.
  renderTable(true, false, () => vt.focusHeader(i));
}

function setSort(ci, dir) {
  state.sortCol = dir === 0 ? -1 : ci;
  state.sortDir = dir;
  renderTable(true, false, () => vt.focusHeader(ci));
}

function cellNode(col, value) {
  const td = el('td');
  if (value === null || value === '') {
    td.appendChild(el('span', 'null', '-'));
  } else if (typeof value === 'boolean') {
    td.appendChild(el('span', value ? 'pill yes' : 'pill', value ? 'yes' : 'no'));
  } else {
    const shown = shownText(col, value);
    if (typeof value === 'number') td.className = 'num';
    else if (CODE_COLUMNS.has(col)) td.className = 'code';
    td.textContent = shown;
    td.title = shown === String(value) ? shown : shown + '\n' + String(value);
  }
  return td;
}

// ---- the relationship graph view -------------------------------------------------------------------------

const BIG_GRAPH = 300;
let graphCtl = null;

function infoRows(pairs) {
  const list = el('dl', 'details');
  pairs.forEach(([k, v]) => list.append(el('dt', '', k), el('dd', '', v === null || v === undefined || v === '' ? '-' : String(v))));
  return list;
}

// The drawer also tells about a graph table or connection; closing it returns focus to what opened it.
function openInfo(title, pairs, opener, json) {
  state.drawerIdx = null;
  state.drawerInfo = json || null;
  state.drawerOpener = opener || null;
  $('drawerTitle').textContent = title;
  $('drawerBody').replaceChildren(infoRows(pairs));
  $('drawerCopy').textContent = 'Copy as JSON';
  const drawer = $('drawer');
  drawer.hidden = false;
  requestAnimationFrame(() => drawer.classList.add('show'));
  $('drawerTitle').focus();
}

function kindLabel(kind) { return kind === 'inferred' ? 'Inferred (a guess)' : kind === 'relationship' ? 'Relationship' : 'Join'; }

function renderGraphList(box, graph) {
  box.replaceChildren();
  const table = el('table', 'graph-table');
  const head = el('thead');
  const hr = el('tr');
  ['From', 'To', 'Kind', 'Keys'].forEach((h) => { const th = el('th', '', h); th.scope = 'col'; hr.appendChild(th); });
  head.appendChild(hr);
  const body = el('tbody');
  graph.edges.slice(0, 500).forEach((e) => {
    const tr = el('tr');
    [e.source, e.target, kindLabel(e.kind), e.label].forEach((v) => tr.appendChild(el('td', '', v)));
    body.appendChild(tr);
  });
  table.append(head, body);
  box.appendChild(table);
  if (graph.edges.length > 500) box.appendChild(el('p', 'quiet', 'and ' + (graph.edges.length - 500) + ' more. Export the DOT for everything.'));
}

function renderGraphView(wrap) {
  const graph = state.graph;
  wrap.innerHTML = '';
  graphCtl = null;
  const nodes = graph.nodes.length;
  $('meta').textContent = plural(nodes, 'table') + ', ' + plural(graph.edges.length, 'connection');
  const root = el('div', 'graph-view');
  const source = el('details', 'dot-source');
  source.append(el('summary', '', 'DOT source'), el('pre', 'dot', state.dot));
  if (!nodes) {
    root.append(emptyState('No joins or relationships', 'This workbook has none, so there is nothing to draw.'), source);
    wrap.appendChild(root);
    return;
  }
  const tools = el('div', 'graph-tools');
  tools.setAttribute('role', 'toolbar');
  tools.setAttribute('aria-label', 'Graph tools');
  const button = (label, title, run) => {
    const b = el('button', 'btn small', label);
    b.type = 'button'; b.title = title; b.setAttribute('aria-label', title);
    b.addEventListener('click', run);
    tools.appendChild(b);
    return b;
  };
  const box = el('div', 'graph-box');
  const list = el('div', 'graph-list');
  list.hidden = true;
  let component;
  const draw = () => {
    graphCtl = VGraph.render(box, graph, {
      component,
      onSelectNode: (n, edges, opener) => openInfo(n.id, [
        ['Kind', 'Table'],
        ['Connections', edges.length],
      ].concat(edges.map((e) => [e.source === n.id ? 'To ' + e.target : 'From ' + e.source, e.label + ' (' + kindLabel(e.kind).toLowerCase() + ')'])),
      opener, {table: n.id, connections: edges.map((e) => ({from: e.source, to: e.target, keys: e.label, kind: e.kind}))}),
      onSelectEdge: (e, opener) => openInfo(e.source + ' to ' + e.target, [
        ['Kind', kindLabel(e.kind)], ['From', e.source], ['To', e.target], ['Keys', e.label],
      ], opener, {from: e.source, to: e.target, keys: e.label, kind: e.kind}),
    });
  };
  button('+', 'Zoom in', () => graphCtl && graphCtl.zoomIn());
  button('\u2212', 'Zoom out', () => graphCtl && graphCtl.zoomOut());
  button('Fit', 'Fit the whole graph in view', () => graphCtl && graphCtl.fit());
  if (nodes > BIG_GRAPH) {
    const lay = VGraph.layout(graph);
    component = 0;
    const sel = el('select', 'field');
    sel.setAttribute('aria-label', 'Which group of connected tables to draw');
    lay.components.forEach((c) => {
      const opt = el('option', '', 'Group ' + (c.index + 1) + ': ' + plural(c.size, 'table'));
      opt.value = String(c.index);
      sel.appendChild(opt);
    });
    sel.addEventListener('change', () => { component = Number(sel.value); draw(); });
    tools.appendChild(sel);
    tools.appendChild(el('span', 'note', 'Large graph: drawing one group at a time.'));
  }
  const toggle = button('View as list', 'Switch between the picture and a list of connections', () => {
    const showList = list.hidden;
    list.hidden = !showList;
    box.hidden = showList;
    toggle.textContent = showList ? 'View as graph' : 'View as list';
    toggle.setAttribute('aria-pressed', showList ? 'true' : 'false');
    if (showList) renderGraphList(list, graph); else if (graphCtl) requestAnimationFrame(() => graphCtl.fit());
  });
  toggle.setAttribute('aria-pressed', 'false');
  button('Save as SVG', 'Download the graph as an SVG file', () => {
    if (!graphCtl) return;
    const blob = new Blob([graphCtl.exportSvg()], {type: 'image/svg+xml'});
    const a = el('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'relationships.svg';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }).classList.add('save-svg');
  root.append(tools, box, list, source);
  wrap.appendChild(root);
  draw();
}

function emptyState(title, text) {
  const box = el('div', 'empty-state');
  box.append(el('strong', '', title), el('span', '', text));
  return box;
}

const vt = new VTable($('tableWrap'), {
  cell: (ci, value) => cellNode(state.columns[ci], value),
  sort: (ci) => toggleSort(ci),
  openRow: (pos, opener) => openRow(pos, opener),
  menu: (ci, th) => openColumnMenu(ci, th),
  resized: (ci, width) => { viewFor(state.table).widths[state.columns[ci]] = width; },
});

// animate: let the browser glide rows to their new places (when it can, and motion is welcome). Only sorting
// asks for it: while a view transition runs (about 200 ms) the browser sends clicks to the page root and no
// CSS can change that, so it is kept to the one change where the glide explains something, and is never
// started by typing in the filter.
// keepScroll: pinning, hiding and resizing keep your place; a new sort or filter starts at the top.
// after: runs once the new table is on screen.
function renderTable(animate, keepScroll, after) {
  const run = () => {
    const t0 = performance.now();
    const wrap = $('tableWrap');
    const total = state.data.length;
    const v = viewFor(state.table);
    if (!total) {
      if (menuState && menuState.anchor.tagName === 'TH') closeMenu(false);  // no headers left to hang from
      wrap.innerHTML = '';
      $('meta').textContent = '0 row(s)';
      wrap.appendChild(emptyState('Nothing here yet', 'This workbook has no rows in this table.'));
      renderChips();
      updateColumnsButton();
      return;
    }
    const order = computeOrder();
    const filtered = $('filter').value.trim() !== '' || liveFilters(v).length > 0;
    $('meta').textContent = filtered ? order.length + ' of ' + total + ' row(s)' : total + ' row(s)';
    vt.configure({
      cols: state.columns, data: state.data, order, display: displayCols(v), widths: widthsFor(v),
      pinned: v.pinned === null || colIndex(v.pinned) < 0 ? null : colIndex(v.pinned),
      sort: {col: state.sortCol, dir: state.sortDir}, current: state.drawerIdx,
    });
    vt.build(!keepScroll);
    reanchorMenu();
    if (!order.length) wrap.appendChild(emptyState('No matches', 'No rows match those filters.'));
    renderChips();
    updateColumnsButton();
    performance.clearMeasures('py-tbparse:table');
    performance.measure('py-tbparse:table', {start: t0, end: performance.now()});
    if (after) after();
  };
  if (animate && document.startViewTransition && !reducedMotion()) {
    try {
      const transition = document.startViewTransition(run);
      // A newer sort or filter skips the one still gliding. That is normal, so it must not surface as
      // an error; a real error inside run() still does, through updateCallbackDone.
      transition.ready.catch(() => {});
      transition.finished.catch(() => {});
      return;
    } catch (e) { /* fall back to a plain redraw */ }
  }
  run();
}

// ---- the details drawer ---------------------------------------------------------------------------

function rowObject(idx) {
  const out = {};
  state.columns.forEach((col, ci) => { out[col] = state.data[idx][ci]; });
  return out;
}

function fillDrawer(idx) {
  const row = state.data[idx];
  const titleCol = ['name', 'field', 'sheet', 'dashboard', 'caption', 'current'].find((c) => state.columns.includes(c));
  const titleValue = titleCol ? row[state.columns.indexOf(titleCol)] : row[0];
  $('drawerTitle').textContent = titleValue === null || titleValue === undefined || titleValue === ''
    ? 'Row details' : shownText(titleCol || state.columns[0], titleValue);
  const list = el('dl', 'details');
  state.columns.forEach((col, ci) => {
    const value = row[ci];
    const dd = el('dd');
    if (value === null || value === '') {
      dd.appendChild(el('span', 'null', '—'));
    } else {
      dd.textContent = shownText(col, value);
      if (CODE_COLUMNS.has(col)) dd.className = 'code';
      if (col === 'datasource' && shownText(col, value) !== String(value)) {
        dd.appendChild(el('div', 'raw-id', String(value)));
      }
    }
    list.append(el('dt', '', col), dd);
  });
  $('drawerBody').replaceChildren(list);
}

function openRow(pos, opener) {
  const idx = vt.order[pos];
  if (idx === undefined) return;
  state.drawerIdx = idx;
  state.drawerInfo = null;
  state.drawerOpener = null;
  $('drawerCopy').textContent = 'Copy row as JSON';
  fillDrawer(idx);
  const drawer = $('drawer');
  drawer.hidden = false;
  requestAnimationFrame(() => drawer.classList.add('show'));
  vt.setCurrent(idx);
  $('drawerTitle').focus();
}

function closeDrawer(restoreFocus) {
  const drawer = $('drawer');
  if (drawer.hidden) return;
  const idx = state.drawerIdx;
  state.drawerIdx = null;
  vt.setCurrent(null);
  drawer.classList.remove('show');
  setTimeout(() => { if (!drawer.classList.contains('show')) drawer.hidden = true; }, 260);
  if (restoreFocus && idx !== null && idx !== undefined) vt.focusRowByIndex(idx);
  else if (restoreFocus && state.drawerOpener && state.drawerOpener.isConnected) state.drawerOpener.focus();
  state.drawerOpener = null;
  state.drawerInfo = null;
}

async function copyText(text, message) {
  try {
    await navigator.clipboard.writeText(text);
    setStatus(message, false, 'ok');
  } catch (e) {
    setStatus('Could not copy to the clipboard. Your browser may be blocking it.', true);
  }
}

// ---- menus: column options, and which columns to show --------------------------------------------------

let menuState = null;

// aria-expanded belongs on the control that opens a menu: the options button inside a column header,
// or the Columns button itself.
function setExpanded(anchor, open) {
  const trigger = anchor && anchor.tagName === 'TH' ? anchor.querySelector('.col-menu-btn') : anchor;
  if (trigger && trigger.getAttribute('aria-haspopup')) trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function closeMenu(restoreFocus) {
  const menu = $('menu');
  if (menu.hidden) return;
  menu.hidden = true;
  menu.replaceChildren();
  const anchor = menuState ? menuState.anchor : null;
  setExpanded(anchor, false);
  menuState = null;
  if (restoreFocus && anchor && anchor.isConnected) anchor.focus();
}

function menuButtons() {
  return Array.from($('menu').querySelectorAll('button.menu-item'));
}

// focusItem is an index into items, so focus stays on the same item when the menu is redrawn.
function fillMenu(items, focusItem) {
  const menu = $('menu');
  menu.setAttribute('role', 'menu');
  menu.replaceChildren();
  const byItem = new Map();
  items.forEach((item, at) => {
    if (item.sep) { const sep = el('div', 'menu-sep'); sep.setAttribute('role', 'separator'); menu.appendChild(sep); return; }
    const btn = el('button', 'menu-item');
    btn.type = 'button';
    btn.setAttribute('role', item.radio ? 'menuitemradio' : item.checkbox ? 'menuitemcheckbox' : 'menuitem');
    if (item.checkbox || item.radio) btn.setAttribute('aria-checked', item.checked ? 'true' : 'false');
    if (item.disabled) btn.setAttribute('aria-disabled', 'true');
    byItem.set(at, btn);
    btn.append(el('span', 'menu-check', (item.checkbox || item.radio) ? (item.checked ? '✓' : '') : ''));
    if (item.swatch) {
      // a swatch scopes the theme to itself, so it shows the real colours of that theme in the current mode
      const sw = el('span', 'menu-swatch');
      sw.dataset.theme = item.swatch;
      sw.dataset.mode = document.documentElement.dataset.mode || 'light';
      sw.setAttribute('aria-hidden', 'true');
      sw.append(el('i'), el('i'), el('i'));
      btn.appendChild(sw);
    }
    btn.appendChild(el('span', '', item.label));
    btn.addEventListener('click', () => {
      if (item.disabled) return;
      if (item.keep) {
        item.run();
        // A keep-open item normally redraws the menu (to refresh its ticks); an item that swaps in
        // its own content, like the filter form, opts out with rebuild: false.
        if (item.rebuild !== false && menuState && menuState.build) {
          fillMenu(menuState.build(), items.indexOf(item));
        }
      } else {
        const anchor = menuState ? menuState.anchor : null;
        closeMenu(false);
        item.run(anchor);
        // The menu item that had focus is gone. An action that redraws the table puts focus on the
        // right header itself; one that does not (copying) would leave it on the page, so return it.
        if (anchor && anchor.isConnected && document.activeElement === document.body) anchor.focus();
      }
    });
    menu.appendChild(btn);
  });
  const target = byItem.get(focusItem);
  if (target) target.focus();
}

function showMenu(anchor, label, build, col) {
  closeMenu(false);
  const menu = $('menu');
  const wrap = $('tableWrap');
  menuState = {anchor, build, col, scroll: [wrap.scrollLeft, wrap.scrollTop]};
  menu.setAttribute('aria-label', label);
  setExpanded(anchor, true);
  menu.hidden = false;
  const items = build();
  fillMenu(items, items.findIndex((item) => !item.sep && !item.disabled));
  placeMenu(anchor);
}

function placeMenu(anchor) {
  const menu = $('menu');
  const box = anchor.getBoundingClientRect();
  const left = Math.max(8, Math.min(box.left, window.innerWidth - menu.offsetWidth - 8));
  let top = box.bottom + 4;
  if (top + menu.offsetHeight > window.innerHeight - 8) top = Math.max(8, box.top - menu.offsetHeight - 4);
  menu.style.left = left + 'px';
  menu.style.top = top + 'px';
}

// The table redrew, which replaced the header a column menu hangs from. A redraw can arrive after the menu
// was opened (a sort runs in the next frame, inside a view transition), so the menu follows its column to
// the new header and refreshes its items, and closes only if that column is gone.
function reanchorMenu() {
  if (!menuState || menuState.anchor.tagName !== 'TH') return;
  const th = $('tableWrap').querySelector('th[data-col="' + menuState.col + '"]');
  if (!th) { closeMenu(false); return; }
  const menu = $('menu');
  menuState.anchor = th;
  setExpanded(th, true);
  const wrap = $('tableWrap');
  menuState.scroll = [wrap.scrollLeft, wrap.scrollTop];
  if (menu.getAttribute('role') === 'menu') {
    const at = menuButtons().indexOf(document.activeElement);
    fillMenu(menuState.build(), at >= 0 ? at : undefined);
  }
  placeMenu(th);
}

function afterColumnChange(ci) {
  scheduleHay();
  renderTable(false, true, () => vt.focusHeader(ci));
}

function hideColumn(ci) {
  const v = viewFor(state.table);
  if (displayCols(v).length <= 1) return;
  v.hidden.add(state.columns[ci]);
  if (v.pinned === state.columns[ci]) v.pinned = null;
  if (state.sortCol === ci) { state.sortCol = -1; state.sortDir = 0; }
  afterColumnChange(displayCols(v)[0]);
}

function resizeBy(ci, delta) {
  const v = viewFor(state.table);
  const name = state.columns[ci];
  v.widths[name] = Math.max(80, Math.min(900, (v.widths[name] || autoWidth(ci, v)) + delta));
  renderTable(false, true, () => vt.focusHeader(ci));
}

function copyColumn(ci) {
  const values = vt.order.map((idx) => {
    const x = state.data[idx][ci];
    return x === null ? '' : String(x);
  });
  copyText(values.join('\n'), 'Copied ' + plural(values.length, 'value') + ' from ' + state.columns[ci]);
}

function showFilterForm(ci) {
  const menu = $('menu');
  const name = state.columns[ci];
  menu.setAttribute('role', 'dialog');
  menu.setAttribute('aria-label', 'Filter column ' + name);
  const form = el('form', 'menu-form');
  const label = el('label', '', 'Show rows where ' + name + ' contains');
  const input = el('input', 'field');
  input.type = 'text';
  input.setAttribute('aria-label', 'Filter ' + name);
  input.spellcheck = false;
  const apply = el('button', 'btn primary small', 'Apply');
  apply.type = 'submit';
  form.append(label, input, apply);
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    const v = viewFor(state.table);
    v.filters = v.filters.filter((f) => f.col !== name).concat([{col: name, text}]);
    const anchor = menuState ? menuState.anchor : null;
    closeMenu(false);
    renderTable(false, false, () => { if (anchor && anchor.isConnected) anchor.focus(); else vt.focusHeader(ci); });
  });
  menu.replaceChildren(form);
  placeMenu(menuState.anchor);
  input.focus();
}

function openColumnMenu(ci, th) {
  const name = state.columns[ci];
  showMenu(th, 'Options for column ' + name, () => {
    const v = viewFor(state.table);
    return [
      {label: 'Sort ascending', run: () => setSort(ci, 1)},
      {label: 'Sort descending', run: () => setSort(ci, -1)},
      {label: 'Clear sort', disabled: state.sortCol !== ci, run: () => setSort(ci, 0)},
      {sep: true},
      {label: 'Filter this column…', keep: true, rebuild: false, run: () => showFilterForm(ci)},
      {label: v.pinned === name ? 'Unpin column' : 'Pin to the left', run: () => {
        v.pinned = v.pinned === name ? null : name;
        renderTable(false, true, () => vt.focusHeader(ci));
      }},
      {label: 'Hide column', disabled: displayCols(v).length <= 1, run: () => hideColumn(ci)},
      {sep: true},
      {label: 'Wider', run: () => resizeBy(ci, 40)},
      {label: 'Narrower', run: () => resizeBy(ci, -40)},
      {label: 'Reset width', run: () => { delete v.widths[name]; renderTable(false, true, () => vt.focusHeader(ci)); }},
      {sep: true},
      {label: 'Copy column values', run: () => copyColumn(ci)},
    ];
  }, ci);
}

function toggleColumn(ci) {
  const v = viewFor(state.table);
  const name = state.columns[ci];
  if (v.hidden.has(name)) { v.hidden.delete(name); scheduleHay(); renderTable(false, true); }
  else {
    if (displayCols(v).length <= 1) return;
    v.hidden.add(name);
    if (v.pinned === name) v.pinned = null;
    if (state.sortCol === ci) { state.sortCol = -1; state.sortDir = 0; }
    scheduleHay();
    renderTable(false, true);
  }
}

function openColumnsMenu() {
  showMenu($('colsBtn'), 'Columns', () => {
    const v = viewFor(state.table);
    const items = [
      {label: 'Show all columns', keep: true, disabled: hiddenCount(v) === 0,
       run: () => { v.hidden.clear(); scheduleHay(); renderTable(false, true); }},
      {sep: true},
    ];
    state.columns.forEach((name, ci) => {
      const shown = !v.hidden.has(name);
      items.push({label: name, checkbox: true, checked: shown, keep: true,
                  disabled: shown && displayCols(v).length <= 1, run: () => toggleColumn(ci)});
    });
    return items;
  });
}

// ---- themes -------------------------------------------------------------------------------------------

const THEME_LABELS = {shop: 'Shop', matcha: 'Matcha', fjord: 'Fjord', pastel: 'Pastel', neon: 'Neon', contrast: 'High contrast'};
const MODE_LABELS = {auto: 'Auto (follow my system)', light: 'Light', dark: 'Dark'};
const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

function applyTheme(theme, pref) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.dataset.pref = pref;
  root.dataset.mode = pref === 'auto' ? (systemDark.matches ? 'dark' : 'light') : pref;
  try {
    localStorage.setItem('py-tbparse:theme', theme);
    localStorage.setItem('py-tbparse:mode', pref);
  } catch (e) { /* private window: the choice lasts until the page closes */ }
  $('themeBtn').title = 'Theme: ' + THEME_LABELS[theme] + ', ' + MODE_LABELS[pref];
  $('announce').textContent = 'Theme ' + THEME_LABELS[theme] + ', ' + root.dataset.mode + ' mode';
}

systemDark.addEventListener('change', () => {
  const root = document.documentElement;
  if ((root.dataset.pref || 'auto') === 'auto') root.dataset.mode = systemDark.matches ? 'dark' : 'light';
});

function openThemeMenu() {
  showMenu($('themeBtn'), 'Theme', () => {
    const root = document.documentElement;
    const theme = root.dataset.theme || 'shop';
    const pref = root.dataset.pref || 'auto';
    const items = (window.THEMES || []).map((id) => ({
      label: THEME_LABELS[id] || id, radio: true, checked: id === theme, keep: true, swatch: id,
      run: () => applyTheme(id, root.dataset.pref || 'auto'),
    }));
    items.push({sep: true});
    ['auto', 'light', 'dark'].forEach((m) => items.push({
      label: MODE_LABELS[m], radio: true, checked: m === pref, keep: true,
      run: () => applyTheme(root.dataset.theme || 'shop', m),
    }));
    return items;
  });
}

function updateColumnsButton() {
  const hidden = hiddenCount(viewFor(state.table));
  $('colsBtn').textContent = hidden ? 'Columns (' + hidden + ' hidden)' : 'Columns';
}

// ---- column filter chips -------------------------------------------------------------------------------

function renderChips() {
  const box = $('chips');
  const v = viewFor(state.table);
  box.replaceChildren();
  const live = liveFilters(v);
  if (!live.length || state.table === 'overview' || state.table === 'graph') { box.hidden = true; return; }
  live.forEach((f) => {
    const chip = el('button', 'chip');
    chip.type = 'button';
    chip.setAttribute('aria-label', 'Remove filter: ' + f.col + ' contains ' + f.text);
    chip.append(el('span', '', f.col + ': ' + f.text), el('span', 'chip-x', '×'));
    chip.addEventListener('click', () => {
      v.filters = v.filters.filter((x) => x !== f);
      renderTable(false, false, () => { (document.querySelector('#chips .chip') || $('filter')).focus(); });
    });
    box.appendChild(chip);
  });
  const clear = el('button', 'chip-clear', 'Clear filters');
  clear.type = 'button';
  clear.addEventListener('click', () => {
    v.filters = [];
    $('filter').value = '';
    renderTable(false, false, () => $('filter').focus());
  });
  box.appendChild(clear);
  box.hidden = false;
}

// ---- row density -----------------------------------------------------------------------------------------

function applyDensity(mode, persist) {
  document.documentElement.dataset.density = mode;
  $('densityBtn').setAttribute('aria-pressed', mode === 'compact' ? 'true' : 'false');
  if (persist) {
    try { localStorage.setItem('py-tbparse.density', mode); } catch (e) { /* storage may be blocked */ }
  }
  if (state.loaded && vt.isShown()) renderTable(false, true);
}

async function copyDot() {
  try {
    await navigator.clipboard.writeText(state.dot);
    $('copyBtn').textContent = 'Copied';
  } catch (e) {
    $('copyBtn').textContent = 'Copy failed';
  }
  setTimeout(() => { $('copyBtn').textContent = 'Copy'; }, 1500);
}

$('loadBtn').addEventListener('click', loadWorkbook);
$('pickBtn').addEventListener('click', () => $('filePick').click());
$('filePick').addEventListener('change', () => {
  const file = $('filePick').files[0];
  $('filePick').value = '';
  if (file) uploadFile(file);
});
// Drop a file anywhere. The overlay only shows for drags that carry files, and a counter copes with
// dragenter/dragleave firing for every child element on the way.
let dragDepth = 0;
function hasFiles(e) { return e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files'); }
window.addEventListener('dragenter', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault(); dragDepth++; $('dropzone').hidden = false;
});
window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener('dragleave', (e) => {
  if (!hasFiles(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $('dropzone').hidden = true;
});
window.addEventListener('drop', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault(); dragDepth = 0; $('dropzone').hidden = true;
  const files = Array.from(e.dataTransfer.files);
  if (files.length > 1) setStatus('Opening the first of ' + files.length + ' files; one workbook at a time.', false, 'ok');
  if (files.length) uploadFile(files[0]);
});
renderRecent();
$('themeBtn').title = 'Theme: ' + THEME_LABELS[document.documentElement.dataset.theme || 'shop'] + ', ' +
  MODE_LABELS[document.documentElement.dataset.pref || 'auto'];
$('path').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadWorkbook(); });
$('tableSel').addEventListener('change', () => selectTable($('tableSel').value));
$('dashboardSel').addEventListener('change', showTable);
$('includeParams').addEventListener('change', showTable);
$('includeInferred').addEventListener('change', showTable);
$('copyBtn').addEventListener('click', copyDot);
$('filter').addEventListener('input', () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => renderTable(false), 120);
});
['renameStyle', 'renameDs', 'renameKinds', 'renameRef', 'renameChanged'].forEach((id) =>
  $(id).addEventListener('change', showTable));
$('createBtn').addEventListener('click', createWorkbook);
$('themeBtn').addEventListener('click', () => {
  if (menuState && menuState.anchor === $('themeBtn')) closeMenu(true);
  else openThemeMenu();
});
$('colsBtn').addEventListener('click', () => {
  if (menuState && menuState.anchor === $('colsBtn')) closeMenu(true);
  else openColumnsMenu();
});
$('densityBtn').addEventListener('click', () => {
  applyDensity(document.documentElement.dataset.density === 'compact' ? 'comfortable' : 'compact', true);
});
$('drawerClose').addEventListener('click', () => closeDrawer(true));
$('drawerCopy').addEventListener('click', () => {
  if (state.drawerIdx !== null) copyText(JSON.stringify(rowObject(state.drawerIdx), null, 2), 'Copied this row as JSON');
  else if (state.drawerInfo) copyText(JSON.stringify(state.drawerInfo, null, 2), 'Copied as JSON');
});
$('menu').addEventListener('keydown', (e) => {
  if ($('menu').getAttribute('role') === 'dialog') {
    // The filter form: Tab, Home, End and the arrows are the text box's, not the menu's. Escape still closes.
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu(true); }
    return;
  }
  const items = menuButtons();
  const at = items.indexOf(document.activeElement);
  const focusItem = (k) => { if (items.length) items[(k + items.length) % items.length].focus(); };
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu(true); }
  else if (e.key === 'ArrowDown') { e.preventDefault(); focusItem(at + 1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); focusItem(at - 1); }
  else if (e.key === 'Home') { e.preventDefault(); focusItem(0); }
  else if (e.key === 'End') { e.preventDefault(); focusItem(items.length - 1); }
  else if (e.key === 'Tab') { closeMenu(true); }
});
// Tabbing out of the filter form closes it.
$('menu').addEventListener('focusout', (e) => {
  const menu = $('menu');
  if (menu.getAttribute('role') === 'dialog' && e.relatedTarget && !menu.contains(e.relatedTarget)) closeMenu(false);
});
document.addEventListener('mousedown', (e) => {
  if ($('menu').hidden) return;
  const inside = $('menu').contains(e.target) || (menuState && menuState.anchor.contains(e.target));
  if (!inside) closeMenu(false);
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !e.defaultPrevented && !$('drawer').hidden && document.activeElement.id !== 'filter') {
    closeDrawer(true);
  }
});
// A menu closes when the table is scrolled out from under it. A scroll event can also arrive late,
// from the table redrawing itself (a sort restores the scroll position inside a view transition), after
// the menu was opened at that very position; that one must not close it.
$('tableWrap').addEventListener('scroll', () => {
  if (!menuState || !menuState.scroll) return;
  const wrap = $('tableWrap');
  if (wrap.scrollLeft !== menuState.scroll[0] || wrap.scrollTop !== menuState.scroll[1]) closeMenu(false);
}, {passive: true});
window.addEventListener('resize', () => closeMenu(false));
$('filter').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { clearTimeout(filterTimer); $('filter').value = ''; renderTable(false); }
});
document.addEventListener('keydown', (e) => {
  const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName);
  if (e.key === '/' && !typing && state.loaded && !$('filter').hidden) {
    e.preventDefault();
    $('filter').focus();
  }
});
window.addEventListener('hashchange', () => {
  const name = decodeURIComponent(location.hash.slice(1));
  if (state.loaded && name !== state.table) selectTable(name);
});

let savedDensity = null;
try { savedDensity = localStorage.getItem('py-tbparse.density'); } catch (e) { /* storage may be blocked */ }
applyDensity(savedDensity === 'compact' ? 'compact' : 'comfortable', false);

populateTables();
if (window.PRELOAD_PATH) {
  $('path').value = window.PRELOAD_PATH;
  loadWorkbook();
}
