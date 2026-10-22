// The layout preview panel of the Dashboards table (#84, docs/plan-84-layout-preview.md): a large drawing of one
// dashboard from the stored zone positions, with the zone names written in it where they fit, and a list of every
// zone. It is a sketch for reading, not how Tableau draws it, and says so in a note under the drawing. The page asks
// GET /dashboard-layout for one dashboard at a time (at most 200 zones); the DOM never holds more than one drawing and
// two short lists. Everything is inside one function so no name here can clash with app.js, which passes in its
// helpers (init) and calls show, hide and render. Names are workbook content and are only ever set with textContent.
(function () {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const GRID = 100000;            // the usual 0 to 100000 range of stored positions; a marker shows it when exceeded
  const OVERLAP_NOTE_MIN = 5;     // the overlap sentence shows when MORE than this many pairs cross (owner: start at 5)
  const SHARE_MIN = 0.01;         // two zones are related when they share more than 1 percent of the smaller one
  const MIN_PX = 3;               // a zone is drawn at least 3 x 3 screen pixels
  const NAME_MIN_W = 40;          // narrower on screen than this: the letter instead of the name
  const LETTER_MIN_W = 12;        // narrower than this: nothing
  const LABEL_PX = 12;            // label font size in screen pixels
  const LABEL_H = 15;             // height of a label box in screen pixels
  const INSET = 3;                // label inset from the zone edge in screen pixels
  const NAME_CUT = 60;            // characters of a name in the list; the full text goes in the title
  const MAX_W = 560;              // drawing width on a wide screen
  const MAX_H_SHARE = 0.7;        // drawing height at most this share of the window height
  const NOTE_ROOM = 120;          // pixels kept under the drawing for the note and the panel padding
  const MIN_DRAW_H = 160;         // the drawing is never made shorter than this to make room
  const FOLD_RATIO = 4;           // wider than 4:1 or taller than 1:4 is called very wide or very tall
  const LETTER = { sheet: 'S', filter: 'F', param: 'P', text: 'T', bitmap: 'I', web: 'W' };
  const WORD = { sheet: 'Worksheet', filter: 'Quick filter', param: 'Parameter control', text: 'Text',
                 bitmap: 'Image', web: 'Web page', other: 'Other zone' };
  const LEGEND = [['sheet', 'Worksheet (S)'], ['filter', 'Quick filter (F)'], ['param', 'Parameter control (P)'],
                  ['text', 'Text (T)'], ['bitmap', 'Image (I)'], ['web', 'Web page (W)'], ['other', 'Other zone']];
  const STANDING = 'A sketch from stored positions, not how Tableau draws it.';

  let D = null;                   // helpers from app.js: $, el, plural, open (name), copy (text, message)
  let req = 0;
  let current = null;             // { row, host, ctl } of the dashboard shown
  let probe = null;               // canvas context for measuring text

  function init(helpers) { D = helpers; }

  function svgEl(tag, attrs) {
    const node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach((k) => node.setAttribute(k, attrs[k]));
    return node;
  }

  function measure(text) {
    if (!probe) {
      const canvas = document.createElement('canvas');
      probe = canvas.getContext('2d');
      if (probe) probe.font = '600 ' + LABEL_PX + 'px ' + (getComputedStyle(document.body).fontFamily || 'sans-serif');
    }
    return probe ? probe.measureText(text).width : text.length * 7;
  }

  function cut(text, max) { return text.length > max ? text.slice(0, max - 1) + '…' : text; }

  function pct(v) {
    const a = Math.abs(v);
    if (a >= 10) return String(Math.round(v));
    if (a >= 0.1) return String(Math.round(v * 10) / 10);
    return a === 0 ? '0' : String(Math.round(v * 100) / 100);
  }

  // ---- the geometry: which zones are inside, cross or sit exactly on another ---------------------------------------

  function contains(a, b) {
    return a.x <= b.x && a.y <= b.y && a.x + a.w >= b.x + b.w && a.y + a.h >= b.y + b.h;
  }

  function analyse(zs) {
    zs.forEach((z) => { z.inside = []; z.holds = []; z.crosses = []; z.same = []; });
    let nested = 0;
    let crossing = 0;
    for (let i = 0; i < zs.length; i++) {
      for (let j = i + 1; j < zs.length; j++) {
        const a = zs[i];
        const b = zs[j];
        const ix = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
        const iy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
        if (ix <= 0 || iy <= 0) continue;
        if (ix * iy <= Math.min(a.w * a.h, b.w * b.h) * SHARE_MIN) continue;
        if (contains(a, b) && contains(b, a)) { a.same.push(j); b.same.push(i); nested++; }
        else if (contains(a, b)) { b.inside.push(i); a.holds.push(j); nested++; }
        else if (contains(b, a)) { a.inside.push(j); b.holds.push(i); nested++; }
        else { a.crosses.push(j); b.crosses.push(i); crossing++; }
      }
    }
    return { nested, crossing };
  }

  function drawOrder(info, zs) {
    const n = zs.length;
    const given = info.order;
    if (Array.isArray(given) && given.length === n && new Set(given).size === n && given.every((v) => v >= 0 && v < n)) return given;
    return zs.map((z, i) => i).sort((p, q) => (zs[q].w * zs[q].h - zs[p].w * zs[p].h) || (p - q));
  }

  // ---- the panel body: drawing, note, legend and list ------------------------------------------------------------

  function render(host, info) {
    if (host.__lp) host.__lp.destroy();
    host.replaceChildren();
    host.__lp = null;
    if (!info) {
      host.appendChild(D.el('p', 'lp-empty', 'The layout could not be read.'));
      return null;
    }
    const zs = (info.zones || []).map((a, i) => ({
      i, kind: a[0], x: a[1], y: a[2], w: a[3], h: a[4], label: a[5] || '', id: String(a[6]),
      parent: (info.parents || [])[i] || '' }));
    const unplaced = info.unplaced_zones || [];
    const total = info.total || 0;
    const ctl = zs.length ? drawn(host, info, zs, unplaced, total) : empty(host, info, unplaced);
    host.__lp = ctl;
    return ctl;
  }

  function nameOf(z) { return z.label || (WORD[z.kind] || WORD.other) + ' ' + z.id; }

  function lineText(zs, idxs, max) {
    const names = idxs.slice(0, max).map((j) => nameOf(zs[j]));
    const more = idxs.length - max;
    if (!names.length) return '';
    if (more > 0) return names.join(', ') + ' and ' + more + ' more';
    return names.length > 1 ? names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1] : names[0];
  }

  function hintOf(zs, z) {
    const parts = [];
    if (z.same.length) parts.push('same position as ' + lineText(zs, z.same, 1));
    if (z.inside.length) {
      const small = z.inside.slice().sort((p, q) => (zs[p].w * zs[p].h - zs[q].w * zs[q].h) || (q - p));
      parts.push('inside ' + nameOf(zs[small[0]]) + (small.length > 1 ? ' and ' + (small.length - 1) + ' more' : ''));
    }
    if (z.holds.length) parts.push('contains ' + D.plural(z.holds.length, 'zone'));
    if (z.crosses.length) parts.push('crosses ' + lineText(zs, z.crosses, 2));
    return parts.join('; ');
  }

  function empty(host, info, unplaced) {
    const box = D.el('div', 'lp-empty');
    box.appendChild(D.el('strong', '', 'No positions are stored for this dashboard.'));
    box.appendChild(D.el('span', '', unplaced.length
      ? D.plural(unplaced.length, 'zone') + (unplaced.length === 1 ? ' is' : ' are') + ' listed below without a position.'
      : 'It has no zones to draw.'));
    host.appendChild(box);
    host.appendChild(unplacedList(info, unplaced));
    return { destroy() {}, zones: [], info };
  }

  function unplacedList(info, unplaced) {
    const wrap = D.el('div', 'lp-unwrap');
    if (!unplaced.length) return wrap;
    wrap.appendChild(D.el('h3', 'lp-h', 'Zones without a stored position'));
    const ol = D.el('ol', 'lp-list lp-unplaced');
    ol.setAttribute('aria-label', 'Zones without a stored position in ' + info.name);
    unplaced.forEach((u) => {
      const li = D.el('li', 'lp-line');
      const badge = D.el('span', 'lp-k dk-' + u[0], LETTER[u[0]] || '·');
      badge.setAttribute('aria-hidden', 'true');
      const label = u[1] || '';
      const nm = D.el('span', 'lp-name', cut(label || (WORD[u[0]] || WORD.other) + ' ' + u[2], NAME_CUT));
      if (label.length > NAME_CUT) nm.title = label;
      li.append(badge, nm, D.el('span', 'lp-kind', WORD[u[0]] || WORD.other), D.el('span', 'lp-pos', 'no stored position'));
      ol.appendChild(li);
    });
    wrap.appendChild(ol);
    if ((info.unplaced || 0) > unplaced.length) {
      wrap.appendChild(D.el('p', 'lp-more', 'The first ' + unplaced.length + ' of ' + info.unplaced + ' are listed.'));
    }
    return wrap;
  }

  function drawn(host, info, zs, unplaced, total) {
    const stats = analyse(zs);
    const order = drawOrder(info, zs);
    const rank = new Array(zs.length);
    order.forEach((k, r) => { rank[k] = r; });
    // the view box: from the zones, not from 100000; a start below 0 is kept, the far edge is the server extent
    const left = Math.min(0, ...zs.map((z) => z.x));
    const top = Math.min(0, ...zs.map((z) => z.y));
    const right = Math.max(info.width || 0, ...zs.map((z) => z.x + z.w));
    const bottom = Math.max(info.height || 0, ...zs.map((z) => z.y + z.h));
    const vw = right - left;
    const vh = bottom - top;
    const beyond = right > GRID || bottom > GRID || left < 0 || top < 0;
    const ratio = vw / vh;
    const flat = ratio > FOLD_RATIO || ratio < 1 / FOLD_RATIO;

    const fig = D.el('div', 'lp-fig');
    const frame = D.el('div', 'lp-frame');
    const note = D.el('p', 'lp-note');
    note.setAttribute('role', 'note');
    const key = D.el('div', 'lp-legend');
    LEGEND.forEach((l) => {
      const item = D.el('span', '');
      item.append(D.el('i', 'dk-' + l[0]), l[1]);
      key.appendChild(item);
    });
    fig.append(frame, note, key);

    const listWrap = D.el('div', 'lp-listwrap');
    listWrap.appendChild(D.el('h3', 'lp-h', 'Zones'));
    const ol = D.el('ol', 'lp-list');
    ol.setAttribute('aria-label', 'Zones of ' + info.name);
    const lines = zs.map((z) => {
      const li = D.el('li', 'lp-line');
      li.dataset.i = String(z.i);
      li.tabIndex = z.i === 0 ? 0 : -1;
      const badge = D.el('span', 'lp-k dk-' + z.kind, LETTER[z.kind] || '·');
      badge.setAttribute('aria-hidden', 'true');
      const nm = D.el('span', 'lp-name', cut(nameOf(z), NAME_CUT));
      if (nameOf(z).length > NAME_CUT) nm.title = nameOf(z);
      const px = (z.x - left) / vw * 100;
      const py = (z.y - top) / vh * 100;
      const pw = z.w / vw * 100;
      const ph = z.h / vh * 100;
      const pos = D.el('span', 'lp-pos', 'position ' + pct(px) + ', ' + pct(py) + ', size ' + pct(pw) + ' by ' + pct(ph) + ' percent');
      pos.title = 'Stored: x ' + z.x + ', y ' + z.y + ', width ' + z.w + ', height ' + z.h + (z.parent ? ', in layout container ' + z.parent : '');
      const hint = D.el('span', 'lp-hint', hintOf(zs, z));
      li.dataset.inside = String(z.inside.length);
      li.dataset.contains = String(z.holds.length);
      li.dataset.crosses = String(z.crosses.length);
      li.dataset.same = String(z.same.length);
      const flag = D.el('span', 'lp-flag', '');
      li.append(badge, nm, D.el('span', 'lp-kind', WORD[z.kind] || WORD.other), pos, hint, flag);
      ol.appendChild(li);
      return li;
    });
    listWrap.appendChild(ol);
    listWrap.appendChild(unplacedList(info, unplaced));
    host.append(fig, listWrap);

    let shapes = [];
    let sel = -1;
    let hot = -1;
    let overlay = null;
    let timer = 0;
    let lastSize = '';
    let observer = null;

    function setHot(k) {
      if (hot >= 0) {
        if (shapes[hot]) shapes[hot].classList.remove('lp-hot');
        lines[hot].classList.remove('lp-hot');
      }
      hot = k;
      if (k >= 0) {
        if (shapes[k]) shapes[k].classList.add('lp-hot');
        lines[k].classList.add('lp-hot');
      }
    }

    function setSel(k, scroll) {
      if (sel >= 0) {
        lines[sel].removeAttribute('aria-current');
        lines[sel].classList.remove('lp-sel');
        if (shapes[sel]) shapes[sel].classList.remove('lp-selected');
      }
      sel = k;
      if (k >= 0) {
        lines[k].setAttribute('aria-current', 'true');
        lines[k].classList.add('lp-sel');
        if (shapes[k]) shapes[k].classList.add('lp-selected');
        if (scroll) keepInView(lines[k]);
      }
      placeOverlay();
    }

    // scroll the list itself, never the panel, so the drawing does not move under the pointer
    function keepInView(li) {
      const top = li.getBoundingClientRect().top - ol.getBoundingClientRect().top + ol.scrollTop;
      if (top < ol.scrollTop) ol.scrollTop = top;
      else if (top + li.offsetHeight > ol.scrollTop + ol.clientHeight) ol.scrollTop = top + li.offsetHeight - ol.clientHeight;
    }

    function placeOverlay() {
      if (!overlay) return;
      const r = sel >= 0 && shapes[sel] ? shapes[sel] : null;
      overlay.style.display = r ? '' : 'none';
      if (!r) return;
      ['x', 'y', 'width', 'height'].forEach((a) => overlay.setAttribute(a, r.getAttribute(a)));
    }

    function rove(k) {
      lines.forEach((li, i) => { li.tabIndex = i === k ? 0 : -1; });
      lines[k].focus();
    }

    ol.addEventListener('keydown', (e) => {
      const li = e.target.closest('li.lp-line');
      if (!li || !ol.contains(li)) return;
      const k = Number(li.dataset.i);
      const to = { ArrowDown: k + 1, ArrowUp: k - 1, Home: 0, End: lines.length - 1 }[e.key];
      if (to !== undefined) { e.preventDefault(); rove(Math.max(0, Math.min(lines.length - 1, to))); }
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(k, false); }
      else if (e.key === 'Escape' && sel >= 0) { e.preventDefault(); setSel(-1, false); lines[k].focus(); }
    });
    ol.addEventListener('click', (e) => {
      const li = e.target.closest('li.lp-line');
      if (!li) return;
      const k = Number(li.dataset.i);
      lines.forEach((l, i) => { l.tabIndex = i === k ? 0 : -1; });
      setSel(k, false);
    });
    ol.addEventListener('mouseover', (e) => { const li = e.target.closest('li.lp-line'); if (li) setHot(Number(li.dataset.i)); });
    ol.addEventListener('mouseleave', () => { if (!ol.contains(document.activeElement)) setHot(-1); else setHot(Number(document.activeElement.dataset.i)); });
    ol.addEventListener('focusin', (e) => { const li = e.target.closest('li.lp-line'); if (li) setHot(Number(li.dataset.i)); });
    ol.addEventListener('focusout', () => setHot(-1));

    function sizeNow() {
      const room = Math.max(160, Math.min((fig.clientWidth || MAX_W) - 2, MAX_W));
      let w = room;
      let h = w / ratio;
      let cap = window.innerHeight * MAX_H_SHARE;
      // keep the note under the drawing on screen: the panel has a maximum height, so leave room for the header and the note
      const panel = fig.closest('.lpanel');
      const limit = panel ? parseFloat(getComputedStyle(panel).maxHeight) : NaN;
      if (panel && limit > 0) {
        const headH = fig.getBoundingClientRect().top - panel.getBoundingClientRect().top + panel.scrollTop;
        cap = Math.min(cap, limit - headH - NOTE_ROOM);
      }
      cap = Math.max(MIN_DRAW_H, cap);
      if (h > cap) { h = cap; w = h * ratio; }
      return { w: Math.max(w, 24), h: Math.max(h, 24) };
    }

    function draw() {
      const size = sizeNow();
      const s = size.w / vw;                       // screen pixels per stored unit
      lastSize = Math.round(size.w) + 'x' + Math.round(size.h);
      const svg = svgEl('svg', { 'class': 'lp-svg', role: 'img', viewBox: left + ' ' + top + ' ' + vw + ' ' + vh,
                                 width: size.w, height: size.h, preserveAspectRatio: 'xMidYMid meet',
                                 'aria-label': 'Layout of ' + info.name + ': ' + D.plural(zs.length, 'zone') + '; the zone list has them all' });
      if (beyond) {
        const m = svgEl('g', { 'class': 'lp-marker', 'aria-hidden': 'true' });
        m.appendChild(svgEl('rect', { x: 0, y: 0, width: GRID, height: GRID }));
        const t = svgEl('text', { x: GRID - 4 / s, y: GRID - 4 / s, 'text-anchor': 'end', 'font-size': LABEL_PX / s });
        t.textContent = String(GRID);
        m.appendChild(t);
        svg.appendChild(m);
      }
      const layer = svgEl('g', { 'class': 'lp-shapes', 'aria-hidden': 'true' });
      shapes = new Array(zs.length);
      const box = new Array(zs.length);
      let tiny = 0;
      order.forEach((k) => {
        const z = zs[k];
        let r = { x: z.x, y: z.y, w: z.w, h: z.h };
        const small = z.w * s < MIN_PX || z.h * s < MIN_PX;
        if (small) {
          const w = Math.max(z.w, MIN_PX / s);
          const h = Math.max(z.h, MIN_PX / s);
          r = { x: z.x + z.w / 2 - w / 2, y: z.y + z.h / 2 - h / 2, w, h };
          tiny++;
        }
        z.tiny = small;
        box[k] = r;
        layer.appendChild(svgEl('rect', { 'class': 'lp-halo', x: r.x, y: r.y, width: r.w, height: r.h, 'aria-hidden': 'true' }));
        const rect = svgEl('rect', { 'class': 'dzone lp-z dk-' + z.kind + (z.crosses.length ? ' lp-cross' : '') + (small ? ' lp-tiny' : ''),
                                     x: r.x, y: r.y, width: r.w, height: r.h, 'data-i': k, 'aria-hidden': 'true' });
        layer.appendChild(rect);
        shapes[k] = rect;
      });
      overlay = svgEl('rect', { 'class': 'lp-seloverlay', 'aria-hidden': 'true' });
      layer.appendChild(overlay);
      svg.appendChild(layer);

      // labels: topmost zone first; a name if it fits, else the letter, else nothing; never over another label
      // and never over a zone drawn above its own
      const labels = svgEl('g', { 'class': 'lp-labels', 'aria-hidden': 'true' });
      const placed = [];
      let missing = 0;
      const free = (b, k) => {
        if (placed.some((p) => b.l < p.r && b.r > p.l && b.t < p.b && b.b > p.t)) return false;
        for (let m = 0; m < zs.length; m++) {
          if (rank[m] <= rank[k]) continue;
          const o = box[m];
          if (b.l < (o.x + o.w - left) * s && b.r > (o.x - left) * s && b.t < (o.y + o.h - top) * s && b.b > (o.y - top) * s) return false;
        }
        return true;
      };
      for (let r = order.length - 1; r >= 0; r--) {
        const k = order[r];
        const z = zs[k];
        const px = (box[k].x - left) * s;
        const py = (box[k].y - top) * s;
        const pw = box[k].w * s;
        const ph = box[k].h * s;
        let text = '';
        let box1 = null;
        let kindOfLabel = '';
        if (z.label && pw >= NAME_MIN_W && ph >= LABEL_H + 2 * INSET) {
          const avail = pw - 2 * INSET;
          let shown = z.label;
          if (measure(shown) > avail) {
            let n = shown.length;
            while (n > 1 && measure(shown.slice(0, n) + '…') > avail) n--;
            shown = shown.slice(0, n) + '…';
          }
          const b = { l: px + INSET, t: py + INSET, r: px + INSET + Math.min(measure(shown), avail), b: py + INSET + LABEL_H };
          if (free(b, k)) { text = shown; box1 = b; kindOfLabel = 'name'; }
        }
        if (!text && LETTER[z.kind] && pw >= LETTER_MIN_W && ph >= LABEL_H + 2 * INSET) {
          const b = { l: px + INSET, t: py + INSET, r: px + INSET + measure(LETTER[z.kind]), b: py + INSET + LABEL_H };
          if (free(b, k)) { text = LETTER[z.kind]; box1 = b; kindOfLabel = 'letter'; }
        }
        if (!text) { if (z.label) missing++; continue; }
        placed.push(box1);
        const t = svgEl('text', { 'class': 'lp-label lp-' + kindOfLabel, x: box1.l / s + left, y: (box1.t + 11) / s + top,
                                  'font-size': LABEL_PX / s, 'data-i': k, 'aria-hidden': 'true' });
        t.style.strokeWidth = String(3 / s);
        t.textContent = text;
        labels.appendChild(t);
      }
      svg.appendChild(labels);

      // events
      svg.addEventListener('mouseover', (e) => { const r = e.target.closest ? e.target.closest('rect.lp-z') : null; if (r) setHot(Number(r.dataset.i)); });
      svg.addEventListener('mouseleave', () => setHot(-1));
      svg.addEventListener('click', (e) => {
        const r = e.target.closest ? e.target.closest('rect.lp-z') : null;
        if (r) { const k = Number(r.dataset.i); setSel(k, true); lines.forEach((l, i) => { l.tabIndex = i === k ? 0 : -1; }); }
      });
      frame.replaceChildren(svg);

      // the list lines that depend on the size
      zs.forEach((z, k) => { lines[k].querySelector('.lp-flag').textContent = z.tiny ? 'drawn larger than stored' : ''; });

      // the note
      const extra = [];
      if (stats.crossing > OVERLAP_NOTE_MIN) {
        extra.push(['overlap', D.plural(stats.nested + stats.crossing, 'pair') + ' of zones overlap (' + stats.nested + ' inside another, ' +
          stats.crossing + ' crossing). The order and look here is for reading; Tableau may draw them differently.']);
      }
      if (beyond) {
        extra.push(['extent', 'Positions go past the ' + GRID + ' grid (to ' + right + ' by ' + bottom + ') or start below 0; they are drawn as stored and their unit is not known.']);
      }
      if (info.unplaced > 0) {
        extra.push(['unplaced', info.unplaced === 1 ? '1 zone has no stored position and is only in the list.'
          : info.unplaced + ' zones have no stored position and are only in the list.']);
      }
      if (total > zs.length) {
        extra.push(['cap', 'Showing the ' + zs.length + ' largest of ' + total + ' zones; the smallest are not drawn, so some overlaps may be missing.']);
      }
      if (tiny) extra.push(['tiny', tiny === 1 ? '1 tiny zone is drawn larger than it is.' : tiny + ' tiny zones are drawn larger than they are.']);
      if (missing) {
        extra.push(['names', missing === 1 ? '1 name is not shown in the drawing; the list has it.'
          : missing + ' names are not shown in the drawing; the list has them.']);
      }
      if (flat) extra.push(['shape', 'The extent is very ' + (ratio > 1 ? 'wide' : 'tall') + ', so the drawing is small; the list is easier to read.']);
      note.replaceChildren(D.el('span', 'lp-note-main', STANDING));
      extra.forEach((x) => {
        const sp = D.el('span', 'lp-note-extra', ' ' + x[1]);
        sp.dataset.cond = x[0];
        note.appendChild(sp);
      });
      frame.classList.toggle('lp-provisional', extra.length > 0);
      frame.dataset.hidden = String(missing);
      placeOverlay();
      if (sel >= 0 && shapes[sel]) shapes[sel].classList.add('lp-selected');
      if (hot >= 0 && shapes[hot]) shapes[hot].classList.add('lp-hot');
    }

    draw();
    if (typeof ResizeObserver === 'function') {
      observer = new ResizeObserver(() => {
        clearTimeout(timer);
        timer = setTimeout(() => {
          const size = sizeNow();
          if (Math.round(size.w) + 'x' + Math.round(size.h) !== lastSize) draw();
        }, 120);
      });
      observer.observe(fig);
    }
    return {
      destroy() { clearTimeout(timer); if (observer) observer.disconnect(); },
      zones: zs, info, redraw: draw, select: (k) => setSel(k, true),
    };
  }

  // ---- the panel: header, facts and buttons around render() ------------------------------------------------------------

  function names(text) { return text ? text.split('; ').filter(Boolean) : []; }

  function zoneText(info) {
    const rows = [['kind', 'name', 'x', 'y', 'width', 'height', 'zone id'].join('\t')];
    (info.zones || []).forEach((z) => rows.push([z[0], z[5], z[1], z[2], z[3], z[4], z[6]].join('\t')));
    (info.unplaced_zones || []).forEach((u) => rows.push([u[0], u[1], '', '', '', '', u[2]].join('\t')));
    return rows.join('\n');
  }

  function fact(dl, label, text) {
    if (!text) return;
    dl.appendChild(D.el('dt', '', label));
    dl.appendChild(D.el('dd', '', text));
  }

  // panel: the section element. row: the Dashboards row object. cb: { allColumns(), close() }.
  function show(panel, row, cb) {
    const mine = ++req;
    panel.hidden = false;
    panel.replaceChildren();
    const head = D.el('header', 'lp-head');
    const title = D.el('h2', 'lp-title', row.name);
    title.id = 'lpTitle';
    const acts = D.el('div', 'lp-acts');
    const mk = (text, label, fn) => {
      const b = D.el('button', 'btn small', text);
      b.type = 'button';
      if (label) b.setAttribute('aria-label', label);
      b.addEventListener('click', fn);
      acts.appendChild(b);
      return b;
    };
    mk('Show its sheets and positions', 'Show the sheets and positions of ' + row.name, () => D.open(row.name));
    const all = mk('All columns', 'All columns of ' + row.name, () => cb.allColumns(all));
    const copy = mk('Copy zone list', null, () => {
      if (current && current.info) D.copy(zoneText(current.info), 'Copied the zone list');
    });
    copy.disabled = true;
    mk('Close', 'Close the layout panel', () => cb.close());
    head.append(title, acts);
    panel.setAttribute('aria-labelledby', 'lpTitle');
    const facts = D.el('dl', 'lp-facts');
    fact(facts, 'Size', row.size);
    const sheets = names(row.sheets);
    if (sheets.length) fact(facts, 'Worksheets', sheets.join(', '));
    fact(facts, 'Filters on', names(row.filter_fields).join(', '));
    fact(facts, 'Parameters', names(row.parameter_names).join(', '));
    const count = D.el('p', 'lp-count', 'Reading the layout…');
    const status = D.el('p', 'sr-only');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const body = D.el('div', 'lp-body');
    panel.append(head, facts, count, status, body);
    current = { row, host: body, info: null };

    fetch('/dashboard-layout?' + new URLSearchParams({ name: row.name }).toString())
      .then((res) => res.json().then((data) => ({ res, data })))
      .then(({ res, data }) => {
        if (mine !== req) return;
        if (res.status === 404) {
          count.textContent = '';
          body.replaceChildren(D.el('p', 'lp-empty', 'This dashboard is no longer in the workbook.'));
          return;
        }
        if (!res.ok) throw new Error(data.error || res.statusText);
        current.info = data;
        render(body, data);
        copy.disabled = false;
        const shown = (data.zones || []).length;
        count.textContent = data.total > shown ? shown + ' largest of ' + data.total + ' zones'
          : D.plural(data.total, 'zone') + (data.unplaced ? ' placed, ' + data.unplaced + ' without a position' : '');
        status.textContent = 'Layout of ' + row.name + ': ' + D.plural(shown, 'zone');
      })
      .catch((e) => {
        if (mine !== req) return;
        count.textContent = '';
        body.replaceChildren(D.el('p', 'lp-empty', 'The layout could not be read: ' + e.message));
      });
  }

  function hide(panel) {
    req++;
    if (current && current.host && current.host.__lp) current.host.__lp.destroy();
    current = null;
    panel.hidden = true;
    panel.replaceChildren();
  }

  window.LayoutPanel = { init, show, hide, render, analyse, OVERLAP_NOTE_MIN, SHARE_MIN, MIN_PX };
})();
