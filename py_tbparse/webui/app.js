const $ = (id) => document.getElementById(id);
const statusEl = $('status');

// Sidebar grouping. Tables missing here (new ones added to _tables.py)
// still show up, under "Other", so the registry stays the source of truth.
const GROUPS = [
  ['Workbook', ['overview', 'published-refs']],
  ['Data', ['datasources', 'parameters', 'fields', 'raw-fields', 'calculated-fields', 'field-renames']],
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
                loaded: false, req: 0, dot: '' };

function setStatus(msg, isErr) {
  statusEl.textContent = msg || '';
  statusEl.classList.toggle('err', !!isErr);
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
  if (changed) { $('filter').value = ''; state.sortCol = -1; state.sortDir = 0; }
  markCurrent();
  if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
  showTable();
}

async function loadWorkbook() {
  const path = $('path').value.trim();
  if (!path) { setStatus('Enter a workbook path first.', true); return; }
  setStatus('Loading ' + path + ' ...');
  const btn = $('loadBtn');
  btn.disabled = true; btn.textContent = 'Loading';
  try {
    const data = await fetchJSON('/load', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path}),
    });
    setStatus('Loaded: ' + data.path);
    state.loaded = true;
    $('empty').hidden = true;
    $('controls').hidden = false;
    $('wbName').textContent = data.name || data.path;
    $('wbName').title = data.path;
    document.title = (data.name || 'workbook') + ' - py-tbparse';
    setCounts(data.counts);
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
    await showTable();
  } catch (e) {
    setStatus('Error: ' + e.message, true);
  } finally {
    btn.disabled = false; btn.textContent = 'Load';
  }
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
  const req = ++state.req;

  if (isGraph) {
    const params = new URLSearchParams();
    if ($('includeInferred').checked) params.set('include_inferred', 'true');
    // Set before the request so the link never points at the previous view.
    $('exportLink').href = '/graph?' + params.toString() + '&download=1';
    try {
      const data = await fetchJSON('/graph?' + params.toString());
      if (req !== state.req) return;
      state.dot = data.dot;
      const wrap = $('tableWrap');
      wrap.innerHTML = '';
      wrap.appendChild(el('pre', 'dot', data.dot));
      $('meta').textContent = data.dot.split('\n').length + ' line(s)';
    } catch (e) {
      setStatus('Error: ' + e.message, true);
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
    if (req !== state.req) return;
    state.columns = data.columns || [];
    state.data = data.data || [];
    if (isOverview) renderOverview(); else renderTable();
  } catch (e) {
    setStatus('Error: ' + e.message, true);
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
  setStatus('Creating workbook ...');
  try {
    const data = await fetchJSON('/create-workbook', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(renameOptions()),
    });
    setStatus('Saved ' + data.renamed + ' rename(s) to ' + data.path);
  } catch (e) {
    setStatus('Error: ' + e.message, true);
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
}

function compareValues(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, {numeric: true, sensitivity: 'base'});
}

function visibleRows() {
  const q = $('filter').value.trim().toLowerCase();
  let rows = state.data;
  if (q) {
    rows = rows.filter((r) => r.some((v) => v !== null && String(v).toLowerCase().includes(q)));
  }
  if (state.sortCol >= 0) {
    const i = state.sortCol;
    const dir = state.sortDir;
    rows = rows.slice().sort((a, b) => {
      const x = a[i], y = b[i];
      if (x === null || y === null) return (x === null) - (y === null);
      return dir * compareValues(x, y);
    });
  }
  return rows;
}

function toggleSort(i) {
  if (state.sortCol !== i) { state.sortCol = i; state.sortDir = 1; }
  else if (state.sortDir === 1) { state.sortDir = -1; }
  else { state.sortCol = -1; state.sortDir = 0; }
  renderTable();
}

function cellNode(col, value) {
  const td = el('td');
  if (value === null || value === '') {
    td.appendChild(el('span', 'null', '-'));
  } else if (typeof value === 'boolean') {
    td.appendChild(el('span', value ? 'pill yes' : 'pill', value ? 'yes' : 'no'));
  } else {
    if (typeof value === 'number') td.className = 'num';
    else if (CODE_COLUMNS.has(col)) td.className = 'code';
    td.textContent = String(value);
    td.title = String(value);
  }
  return td;
}

function emptyState(title, text) {
  const box = el('div', 'empty-state');
  box.append(el('strong', '', title), el('span', '', text));
  return box;
}

function renderTable() {
  const wrap = $('tableWrap');
  wrap.innerHTML = '';
  const total = state.data.length;
  if (!total) {
    $('meta').textContent = '0 row(s)';
    wrap.appendChild(emptyState('Nothing here', 'This workbook has no rows in this table.'));
    return;
  }
  const rows = visibleRows();
  const filtered = $('filter').value.trim() !== '';
  $('meta').textContent = filtered ? rows.length + ' of ' + total + ' row(s)' : total + ' row(s)';

  const table = el('table', 'tbl');
  const headRow = el('tr');
  state.columns.forEach((col, i) => {
    const th = el('th');
    th.tabIndex = 0;
    const sorted = state.sortCol === i;
    th.setAttribute('aria-sort', sorted ? (state.sortDir === 1 ? 'ascending' : 'descending') : 'none');
    th.append(el('span', '', col), el('span', 'arrow', sorted ? (state.sortDir === 1 ? '▲' : '▼') : ''));
    th.addEventListener('click', () => toggleSort(i));
    th.addEventListener('keydown', (e) => { if (e.key === 'Enter') toggleSort(i); });
    headRow.appendChild(th);
  });
  table.appendChild(el('thead')).appendChild(headRow);

  const body = el('tbody');
  rows.forEach((r) => {
    const tr = el('tr');
    r.forEach((v, i) => tr.appendChild(cellNode(state.columns[i], v)));
    tr.addEventListener('click', () => tr.classList.toggle('open'));
    body.appendChild(tr);
  });
  table.appendChild(body);
  wrap.appendChild(table);
  if (!rows.length) wrap.appendChild(emptyState('No matches', 'No rows contain that text.'));
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
$('path').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadWorkbook(); });
$('tableSel').addEventListener('change', () => selectTable($('tableSel').value));
$('dashboardSel').addEventListener('change', showTable);
$('includeParams').addEventListener('change', showTable);
$('includeInferred').addEventListener('change', showTable);
$('copyBtn').addEventListener('click', copyDot);
$('filter').addEventListener('input', renderTable);
['renameStyle', 'renameDs', 'renameKinds', 'renameRef', 'renameChanged'].forEach((id) =>
  $(id).addEventListener('change', showTable));
$('createBtn').addEventListener('click', createWorkbook);
$('filter').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { $('filter').value = ''; renderTable(); }
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

populateTables();
if (window.PRELOAD_PATH) {
  $('path').value = window.PRELOAD_PATH;
  loadWorkbook();
}
