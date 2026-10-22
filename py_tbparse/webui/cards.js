// The Cards view of the Dashboards table (#84): one card per dashboard with a small sketch of its layout, count
// chips, and the sheet, filter and parameter names. The cards are drawn from the rows of the Dashboards table
// (so the filter box and column filters apply), one page of PAGE at a time, never all at once; the sketches come
// from GET /dashboard-cards for the dashboards on that page only. Everything is inside one function so no name
// here can clash with app.js, which passes in its helpers (init) and calls render, reset, getMode and setMode.
(function () {
  'use strict';

  const PAGE = 24;          // cards in the page at once; the server accepts at most 50 names per request
  const LIST_MAX = 8;       // names shown per list on a card, then "and N more"
  const SKETCH_W = 150;
  const SKETCH_H = 100;
  const MODE_KEY = 'py-tbparse.dashview';
  const NS = 'http://www.w3.org/2000/svg';
  const LETTER = { sheet: 'S', filter: 'F', param: 'P', text: 'T', bitmap: 'I', web: 'W' };
  const LEGEND = [
    ['sheet', 'Worksheet (S)'], ['filter', 'Quick filter (F)'], ['param', 'Parameter control (P)'],
    ['text', 'Text (T)'], ['bitmap', 'Image (I)'], ['web', 'Web page (W)'], ['other', 'Other zone'],
  ];

  let D = null;             // helpers from app.js: $, el, fetchJSON, fail, plural, open (name) => show its sheets
  let offset = 0;
  let req = 0;

  function init(helpers) { D = helpers; }
  function reset() { offset = 0; req++; }

  function getMode() {
    try { return localStorage.getItem(MODE_KEY) === 'cards' ? 'cards' : 'table'; } catch (e) { return 'table'; }
  }
  function setMode(mode) {
    try { localStorage.setItem(MODE_KEY, mode); } catch (e) { /* storage may be blocked */ }
  }

  function names(text) { return text ? text.split('; ').filter(Boolean) : []; }

  function chip(n, word, plural) {
    if (!n) return null;
    return D.el('span', 'dchip', n + ' ' + (n === 1 ? word : (plural || word + 's')));
  }

  function listRow(dl, label, items) {
    if (!items.length) return;
    dl.appendChild(D.el('dt', '', label));
    const shown = items.slice(0, LIST_MAX).join(', ');
    dl.appendChild(D.el('dd', '', items.length > LIST_MAX ? shown + ' and ' + (items.length - LIST_MAX) + ' more' : shown));
  }

  function svgEl(tag, attrs) {
    const node = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach((k) => node.setAttribute(k, attrs[k]));
    return node;
  }

  function sketch(name, info) {
    const box = D.el('div', 'dthumb');
    if (!info || !info.total) {
      box.classList.add('empty');
      box.appendChild(D.el('span', '', info ? 'No positions are stored for this dashboard.' : 'The sketch could not be read.'));
      return box;
    }
    const svg = svgEl('svg', { viewBox: '0 0 ' + SKETCH_W + ' ' + SKETCH_H, role: 'img',
                               'aria-label': 'Layout sketch of ' + name + ': ' + D.plural(info.total, 'zone') });
    // width and height are the right and bottom edges and ignore negative starts; like the layout panel, the sketch
    // starts at the smallest left and top edge it has (never later than 0), so a zone placed before 0 is not clipped
    const left = Math.min(0, ...info.zones.map((z) => z[1]));
    const top = Math.min(0, ...info.zones.map((z) => z[2]));
    const w = (info.width || 1) - left;
    const h = (info.height || 1) - top;
    info.zones.forEach((z) => {
      const x = (z[1] - left) * SKETCH_W / w;
      const y = (z[2] - top) * SKETCH_H / h;
      const zw = z[3] * SKETCH_W / w;
      const zh = z[4] * SKETCH_H / h;
      svg.appendChild(svgEl('rect', { 'class': 'dzone dk-' + z[0], x: x + 0.5, y: y + 0.5,
                                      width: Math.max(zw - 1, 0.5), height: Math.max(zh - 1, 0.5), rx: 2 }));
      if (LETTER[z[0]] && zw > 20 && zh > 14) {
        const t = svgEl('text', { x: x + zw / 2, y: y + zh / 2 + 3, 'text-anchor': 'middle', 'aria-hidden': 'true' });
        t.textContent = LETTER[z[0]];
        svg.appendChild(t);
      }
    });
    box.appendChild(svg);
    if (info.total > info.zones.length) {
      box.appendChild(D.el('p', 'dcap', 'Sketch shows the ' + info.zones.length + ' largest of ' + info.total + ' zones.'));
    }
    return box;
  }

  function card(row, info) {
    const art = D.el('div', 'dcard');
    art.setAttribute('role', 'listitem');
    const head = D.el('h2', 'dcard-name', row.name);
    head.appendChild(D.el('small', '', row.size || ''));
    const chips = D.el('div', 'dchips');
    [chip(row.worksheets, 'worksheet'), chip(row.filters, 'filter'), chip(row.parameters, 'parameter'),
     chip(row.actions, 'action'), chip(row.images, 'image'), chip(row.texts, 'text'), chip(row.webs, 'web page')]
      .forEach((c) => { if (c) chips.appendChild(c); });
    if (!chips.childNodes.length) chips.appendChild(D.el('span', 'dchip', 'Nothing placed on it'));
    const dl = D.el('dl', 'dlist');
    listRow(dl, 'Worksheets', names(row.sheets));
    listRow(dl, 'Filters on', names(row.filter_fields));
    listRow(dl, 'Parameters', names(row.parameter_names));
    const body = D.el('div', 'dbody');
    body.append(chips, dl);
    const go = D.el('button', 'btn small', 'Show its sheets and positions');
    go.type = 'button';
    go.setAttribute('aria-label', 'Show the sheets and positions of ' + row.name);
    go.addEventListener('click', () => D.open(row.name));
    const foot = D.el('div', 'dfoot');
    foot.append(go, D.el('span', 'note', 'Opens Dashboard sheets, filtered to this dashboard.'));
    art.append(head, sketch(row.name, info), body, foot);
    return art;
  }

  function legend() {
    const box = D.el('div', 'dlegend');
    box.setAttribute('aria-label', 'Legend of the sketches');
    LEGEND.forEach((l) => {
      const item = D.el('span', '');
      item.append(D.el('i', 'dk-' + l[0]), l[1]);
      box.appendChild(item);
    });
    box.appendChild(D.el('span', 'dnote',
      'The sketch is the main layout only (not phone or tablet), drawn flat from each zone’s stored position.'));
    return box;
  }

  function pager(count, first, last, again) {
    const box = D.el('div', 'dpager');
    const word = 'Showing ' + (first + 1) + ' to ' + last + ' of ' + D.plural(count, 'dashboard');
    box.appendChild(D.el('span', 'note', word));
    const prev = D.el('button', 'btn small', 'Previous ' + PAGE);
    prev.type = 'button'; prev.id = 'cardsPrev'; prev.disabled = first <= 0;
    prev.addEventListener('click', () => { offset = Math.max(0, first - PAGE); again(); });
    const next = D.el('button', 'btn small', 'Next ' + PAGE);
    next.type = 'button'; next.id = 'cardsNext'; next.disabled = last >= count;
    next.addEventListener('click', () => { offset = last; again(); });
    box.append(prev, next);
    return box;
  }

  // wrap: where the cards go. count: how many dashboards match; at(i): the row object of the i-th match.
  async function render(wrap, count, at) {
    const mine = ++req;
    if (offset >= count) offset = Math.max(0, Math.floor((count - 1) / PAGE) * PAGE);
    const first = offset;
    const last = Math.min(count, first + PAGE);
    const rows = [];
    for (let i = first; i < last; i++) rows.push(at(i));
    let infos = {};
    if (rows.length) {
      const p = new URLSearchParams();
      rows.forEach((r) => p.append('name', r.name));
      try {
        const data = await D.fetchJSON('/dashboard-cards?' + p.toString());
        (data.cards || []).forEach((c) => { infos[c.name] = c; });
      } catch (e) {
        if (mine !== req) return;
        D.fail(e);
        infos = {};
      }
      if (mine !== req) return;
    }
    wrap.innerHTML = '';
    const grid = D.el('div', 'dgrid');
    grid.id = 'dashCards';
    grid.tabIndex = -1;
    grid.setAttribute('role', 'list');
    grid.setAttribute('aria-label', 'Dashboards');
    rows.forEach((r) => grid.appendChild(card(r, infos[r.name])));
    if (!rows.length) {
      const box = D.el('div', 'empty-state');
      box.append(D.el('strong', '', count ? 'Nothing on this page' : 'No matches'),
                 D.el('span', '', 'No dashboard matches those filters.'));
      wrap.appendChild(box);
      return;
    }
    wrap.append(grid);
    if (count > PAGE) wrap.appendChild(pager(count, first, last, () => {
      render(wrap, count, at).then(() => {
        const g = wrap.querySelector('#dashCards');
        if (g) g.focus();
        wrap.scrollTop = 0;
      });
    }));
    wrap.appendChild(legend());
  }

  window.DashCards = { init, render, reset, getMode, setMode, PAGE };
})();
