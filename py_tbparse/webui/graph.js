// The relationship graph: a small layered layout and an SVG renderer, with no libraries.
//
// layout(data) is pure and deterministic: the same nodes and edges always give the same picture.
//   1. connected components, largest first
//   2. cycles broken by a depth-first search in name order (back edges are laid out reversed)
//   3. layers by longest path, so every edge points to the right
//   4. a few barycentre sweeps to cut crossings, then plain coordinates
// render(box, data, options) draws it and returns a controller (fit, zoom, focus, export).
(function () {
  'use strict';

  const NODE_H = 34;
  const GAP_X = 96;
  const GAP_Y = 22;
  const PAD = 28;
  const COMP_GAP = 56;
  const SWEEPS = 4;
  const SVG_NS = 'http://www.w3.org/2000/svg';

  function nodeWidth(label) { return Math.max(104, Math.min(248, 30 + String(label).length * 7)); }

  // ---- layout ----------------------------------------------------------------------------------------

  function layout(data) {
    const ids = [];
    const seen = new Set();
    const add = (id) => { if (!seen.has(id)) { seen.add(id); ids.push(id); } };
    (data.nodes || []).forEach((n) => add(n.id));
    (data.edges || []).forEach((e) => { add(e.source); add(e.target); });
    ids.sort();
    const index = new Map(ids.map((id, i) => [id, i]));

    // distinct directed pairs without self loops drive the layout; every edge is still drawn
    const succ = ids.map(() => new Set());
    const pred = ids.map(() => new Set());
    const und = ids.map(() => new Set());
    (data.edges || []).forEach((e) => {
      const a = index.get(e.source);
      const b = index.get(e.target);
      if (a === b) return;
      succ[a].add(b); pred[b].add(a); und[a].add(b); und[b].add(a);
    });

    // components, found breadth first from the lowest name, then ordered largest first
    const comp = new Array(ids.length).fill(-1);
    const comps = [];
    for (let i = 0; i < ids.length; i++) {
      if (comp[i] !== -1) continue;
      const members = [];
      const queue = [i];
      comp[i] = comps.length;
      while (queue.length) {
        const v = queue.shift();
        members.push(v);
        [...und[v]].sort((x, y) => x - y).forEach((w) => { if (comp[w] === -1) { comp[w] = comps.length; queue.push(w); } });
      }
      members.sort((x, y) => x - y);
      comps.push(members);
    }
    comps.sort((a, b) => b.length - a.length || a[0] - b[0]);

    const nodes = new Map();
    const placed = [];
    comps.forEach((members, ci) => {
      const inComp = new Set(members);
      // 2. break cycles: an iterative depth-first search, back edges are flagged as reversed
      const state = new Map();
      const reversed = new Set();
      members.forEach((root) => {
        if (state.has(root)) return;
        const stack = [[root, [...succ[root]].sort((x, y) => x - y), 0]];
        state.set(root, 1);
        while (stack.length) {
          const top = stack[stack.length - 1];
          if (top[2] >= top[1].length) { state.set(top[0], 2); stack.pop(); continue; }
          const w = top[1][top[2]++];
          if (state.get(w) === 1) reversed.add(top[0] + ':' + w);
          else if (!state.has(w)) { state.set(w, 1); stack.push([w, [...succ[w]].sort((x, y) => x - y), 0]); }
        }
      });
      const out = new Map(members.map((v) => [v, []]));
      const into = new Map(members.map((v) => [v, []]));
      members.forEach((v) => {
        succ[v].forEach((w) => {
          if (!inComp.has(w)) return;
          const [a, b] = reversed.has(v + ':' + w) ? [w, v] : [v, w];
          out.get(a).push(b);
          into.get(b).push(a);
        });
      });
      // 3. longest-path layers over the now acyclic graph
      const layer = new Map(members.map((v) => [v, 0]));
      const waiting = new Map(members.map((v) => [v, into.get(v).length]));
      const ready = members.filter((v) => waiting.get(v) === 0);
      while (ready.length) {
        const v = ready.shift();
        out.get(v).forEach((w) => {
          layer.set(w, Math.max(layer.get(w), layer.get(v) + 1));
          waiting.set(w, waiting.get(w) - 1);
          if (waiting.get(w) === 0) ready.push(w);
        });
      }
      const depth = Math.max(...members.map((v) => layer.get(v))) + 1;
      const columns = Array.from({length: depth}, () => []);
      members.forEach((v) => columns[layer.get(v)].push(v));
      // 4. barycentre sweeps: a node moves toward the average position of its neighbours
      const rank = new Map();
      const renumber = () => columns.forEach((col) => col.forEach((v, i) => rank.set(v, i)));
      renumber();
      const sweep = (cols, nbrs) => {
        cols.forEach((col) => {
          const key = new Map(col.map((v) => {
            const ns = nbrs.get(v);
            return [v, ns.length ? ns.reduce((s, w) => s + rank.get(w), 0) / ns.length : rank.get(v)];
          }));
          col.sort((a, b) => key.get(a) - key.get(b) || a - b);
          col.forEach((v, i) => rank.set(v, i));
        });
      };
      for (let k = 0; k < SWEEPS; k++) {
        sweep(columns.slice(1), into);
        sweep(columns.slice(0, -1).reverse(), out);
      }
      // coordinates, relative to this component
      const widths = columns.map((col) => Math.max(...col.map((v) => nodeWidth(ids[v]))));
      const tallest = Math.max(...columns.map((col) => col.length));
      const height = tallest * NODE_H + (tallest - 1) * GAP_Y;
      let x = 0;
      columns.forEach((col, li) => {
        const colHeight = col.length * NODE_H + (col.length - 1) * GAP_Y;
        col.forEach((v, i) => {
          nodes.set(ids[v], {id: ids[v], x, y: (height - colHeight) / 2 + i * (NODE_H + GAP_Y),
                             w: nodeWidth(ids[v]), h: NODE_H, layer: li, row: i, comp: ci});
        });
        x += widths[li] + GAP_X;
      });
      placed.push({index: ci, size: members.length, width: x - GAP_X, height, nodes: members.map((v) => ids[v])});
    });

    // edges: parallel ones (same pair, either direction) fan out so none hides another
    const groups = new Map();
    const edges = (data.edges || []).map((e, i) => {
      const key = [e.source, e.target].sort().join('\u0000');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(i);
      return {index: i, source: e.source, target: e.target, label: e.label || '', kind: e.kind || 'join'};
    });
    groups.forEach((list) => list.forEach((i, k) => { edges[i].slot = k; edges[i].slots = list.length; }));
    return {nodes: [...nodes.values()], edges, components: placed};
  }

  // Where each component sits when several are shown: stacked, widest not wider than needed.
  function place(lay, only) {
    const shown = lay.components.filter((c) => only === null || only === undefined || c.index === only);
    const origin = new Map();
    let y = PAD;
    let width = 0;
    shown.forEach((c) => { origin.set(c.index, {x: PAD, y}); y += c.height + COMP_GAP; width = Math.max(width, c.width); });
    return {origin, width: width + 2 * PAD, height: Math.max(0, y - COMP_GAP + PAD)};
  }

  // The path of one edge between two placed nodes, as a cubic curve, plus its midpoint for the label.
  function edgePath(e, a, b) {
    if (a === b) {
      const x = a.px + a.w - 18;
      const y = a.py;
      return {d: `M ${x} ${y} C ${x + 8} ${y - 34}, ${x - 52} ${y - 34}, ${x - 44} ${y}`, mx: x - 22, my: y - 26};
    }
    let x1; let x2; let dir;
    if (b.px >= a.px + a.w) { x1 = a.px + a.w; x2 = b.px; dir = 1; }
    else if (b.px + b.w <= a.px) { x1 = a.px; x2 = b.px + b.w; dir = -1; }
    else { x1 = a.px + a.w; x2 = b.px + b.w; dir = 1; }
    const y1 = a.py + a.h / 2;
    const y2 = b.py + b.h / 2;
    const fan = (e.slot - (e.slots - 1) / 2) * 18;
    let dx = Math.max(44, Math.abs(x2 - x1) / 2);
    if (x1 === a.px + a.w && x2 === b.px + b.w) dx = 60 + Math.abs(y2 - y1) / 4;
    const c1x = x1 + dir * dx;
    const c2x = (x2 === b.px + b.w && dir === 1 && b.px < a.px + a.w) ? x2 + dx : x2 - dir * dx;
    const c1y = y1 + fan;
    const c2y = y2 + fan;
    return {d: `M ${x1} ${y1} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${x2} ${y2}`,
            mx: (x1 + 3 * c1x + 3 * c2x + x2) / 8, my: (y1 + 3 * c1y + 3 * c2y + y2) / 8};
  }

  // ---- styling: the same rules for the live page (CSS variables) and for an exported file (literals) ---

  function graphCss(c) {
    return [
      '.node rect { fill: ' + c('panel') + '; stroke: ' + c('border') + '; stroke-width: 1.5; }',
      '.node text { fill: ' + c('text') + '; font: 13px system-ui, sans-serif; pointer-events: none; }',
      '.node.on rect { stroke: ' + c('primary') + '; fill: ' + c('primary-soft') + '; }',
      '.node.on text { fill: ' + c('primary-on-soft') + '; }',
      '.node.dim rect { fill: ' + c('panel') + '; stroke: ' + c('border') + '; }',
      '.node.dim text { fill: ' + c('faint') + '; }',
      '.edge .line { fill: none; stroke: ' + c('muted') + '; stroke-width: 1.6; }',
      '.edge.relationship .line { stroke: ' + c('primary') + '; stroke-width: 2; }',
      '.edge.inferred .line { stroke-dasharray: 6 5; stroke: ' + c('accent') + '; }',
      '.edge.dim .line { stroke: ' + c('border') + '; }',
      '.edge.on .line { stroke-width: 3; }',
      '.edge .hit { fill: none; stroke: transparent; stroke-width: 14; }',
      '.edge .elabel { fill: ' + c('text') + '; font: 12px system-ui, sans-serif; display: none; paint-order: stroke;',
      '  stroke: ' + c('panel') + '; stroke-width: 4px; text-anchor: middle; pointer-events: none; }',
      '.edge.on .elabel { display: block; }',
      '.arrow-join { fill: ' + c('muted') + '; }',
      '.arrow-relationship { fill: ' + c('primary') + '; }',
      '.arrow-inferred { fill: ' + c('accent') + '; }',
      '.graph-bg { fill: ' + c('panel') + '; }',
    ].join('\n');
  }

  const liveColour = (name) => 'var(--' + name + ')';

  // ---- render ----------------------------------------------------------------------------------------

  function s(tag, attrs, text) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach((k) => node.setAttribute(k, attrs[k]));
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function truncate(label, w) {
    const room = Math.floor((w - 22) / 7);
    return label.length > room ? label.slice(0, Math.max(1, room - 1)) + '…' : label;
  }

  function kindWord(kind) {
    return kind === 'inferred' ? 'inferred' : kind === 'relationship' ? 'relationship' : 'join';
  }

  function render(box, data, options) {
    const opts = options || {};
    const lay = layout(data);
    const only = opts.component === undefined ? null : opts.component;
    const spot = place(lay, only);
    const svg = s('svg', {class: 'graph', role: 'group', 'aria-label': opts.label || 'Relationship graph'});
    svg.appendChild(s('style', {}, graphCss(liveColour)));
    const defs = s('defs');
    ['join', 'relationship', 'inferred'].forEach((k) => {
      const m = s('marker', {id: 'arrow-' + k, viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '8', markerHeight: '8',
                             orient: 'auto-start-reverse'});
      m.appendChild(s('path', {d: 'M 0 1 L 10 5 L 0 9 z', class: 'arrow-' + k}));
      defs.appendChild(m);
    });
    svg.appendChild(defs);
    svg.appendChild(s('rect', {class: 'graph-bg', x: '-100000', y: '-100000', width: '200000', height: '200000'}));
    const view = s('g', {class: 'viewport'});
    svg.appendChild(view);

    const shownNodes = lay.nodes.filter((n) => spot.origin.has(n.comp));
    const byId = new Map();
    shownNodes.forEach((n) => {
      const o = spot.origin.get(n.comp);
      n.px = o.x + n.x;
      n.py = o.y + n.y;
      byId.set(n.id, n);
    });
    const shownEdges = lay.edges.filter((e) => byId.has(e.source) && byId.has(e.target));

    const edgeLayer = s('g', {class: 'edges', 'aria-hidden': 'true'});
    const nodeLayer = s('g', {class: 'nodes'});
    view.append(edgeLayer, nodeLayer);

    const edgeEls = [];
    const touching = new Map(shownNodes.map((n) => [n.id, []]));
    shownEdges.forEach((e) => {
      const a = byId.get(e.source);
      const b = byId.get(e.target);
      const p = edgePath(e, a, b);
      const g = s('g', {class: 'edge ' + kindWord(e.kind)});
      g.dataset.edge = String(e.index);
      g.appendChild(s('path', {class: 'hit', d: p.d}));
      g.appendChild(s('path', {class: 'line', d: p.d, 'marker-end': 'url(#arrow-' + kindWord(e.kind) + ')'}));
      g.appendChild(s('text', {class: 'elabel', x: String(p.mx), y: String(p.my - 6)}, e.label));
      g.appendChild(s('title', {}, e.source + ' to ' + e.target + ': ' + e.label + ' (' + kindWord(e.kind) + ')'));
      g.addEventListener('click', (ev) => { ev.stopPropagation(); highlight(null, e); if (opts.onSelectEdge) opts.onSelectEdge(e, g); });
      g.addEventListener('pointerenter', () => highlight(null, e));
      g.addEventListener('pointerleave', () => highlight(null, null));
      edgeLayer.appendChild(g);
      edgeEls[e.index] = g;
      touching.get(e.source).push(e);
      if (e.source !== e.target) touching.get(e.target).push(e);
    });

    // roving tabindex: one tab stop for the whole graph, arrow keys move between tables
    const nodeEls = new Map();
    const order = shownNodes.slice().sort((x, y) => x.comp - y.comp || x.layer - y.layer || x.row - y.row);
    shownNodes.forEach((n) => {
      const g = s('g', {class: 'node', role: 'button', tabindex: '-1', 'data-id': n.id,
                        'aria-label': n.id + ', ' + touching.get(n.id).length + (touching.get(n.id).length === 1 ? ' connection' : ' connections')});
      g.appendChild(s('rect', {x: String(n.px), y: String(n.py), width: String(n.w), height: String(n.h), rx: '10'}));
      g.appendChild(s('text', {x: String(n.px + 12), y: String(n.py + n.h / 2 + 4.5)}, truncate(n.id, n.w)));
      g.appendChild(s('title', {}, n.id));
      g.addEventListener('pointerenter', () => highlight(n, null));
      g.addEventListener('pointerleave', () => highlight(null, null));
      g.addEventListener('focus', () => { setStop(g); highlight(n, null); reveal(n); });
      g.addEventListener('blur', () => highlight(null, null));
      g.addEventListener('click', (ev) => { ev.stopPropagation(); setStop(g); if (opts.onSelectNode) opts.onSelectNode(n, touching.get(n.id), g); });
      g.addEventListener('keydown', (ev) => nodeKey(ev, n, g));
      nodeLayer.appendChild(g);
      nodeEls.set(n.id, g);
    });
    let stop = null;
    function setStop(g) {
      if (stop && stop !== g) stop.setAttribute('tabindex', '-1');
      stop = g;
      g.setAttribute('tabindex', '0');
    }
    if (order.length) setStop(nodeEls.get(order[0].id));

    function highlight(node, edge) {
      const on = new Set();
      const onEdges = new Set();
      if (node) {
        on.add(node.id);
        touching.get(node.id).forEach((e) => { onEdges.add(e.index); on.add(e.source); on.add(e.target); });
      } else if (edge) {
        onEdges.add(edge.index); on.add(edge.source); on.add(edge.target);
      }
      const any = on.size > 0;
      nodeEls.forEach((g, id) => { g.classList.toggle('on', on.has(id)); g.classList.toggle('dim', any && !on.has(id)); });
      edgeEls.forEach((g, i) => { if (g) { g.classList.toggle('on', onEdges.has(i)); g.classList.toggle('dim', any && !onEdges.has(i)); } });
    }

    // arrow keys: right follows an edge out, left follows one in, up and down walk the column
    function nodeKey(ev, n, g) {
      let next = null;
      const col = order.filter((o) => o.comp === n.comp && o.layer === n.layer);
      const mine = col.indexOf(n);
      const link = (dirOut) => {
        const list = touching.get(n.id).map((e) => (dirOut ? (e.source === n.id ? byId.get(e.target) : null) : (e.target === n.id ? byId.get(e.source) : null))).filter(Boolean);
        return list.filter((o) => o !== n).sort((x, y) => Math.abs(x.py - n.py) - Math.abs(y.py - n.py) || x.row - y.row)[0] || null;
      };
      if (ev.key === 'ArrowRight') next = link(true);
      else if (ev.key === 'ArrowLeft') next = link(false);
      else if (ev.key === 'ArrowDown') next = col[mine + 1] || null;
      else if (ev.key === 'ArrowUp') next = col[mine - 1] || null;
      else if (ev.key === 'Home') next = order[0];
      else if (ev.key === 'End') next = order[order.length - 1];
      else if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        if (opts.onSelectNode) opts.onSelectNode(n, touching.get(n.id), g);
        return;
      } else return;
      ev.preventDefault();
      if (next) nodeEls.get(next.id).focus();
    }

    // ---- pan and zoom ----
    const T = {k: 1, x: 0, y: 0};
    const MIN_K = 0.15;
    const MAX_K = 3;
    function apply() { view.setAttribute('transform', `translate(${T.x} ${T.y}) scale(${T.k})`); }
    function size() { const r = svg.getBoundingClientRect(); return {w: r.width || 800, h: r.height || 500}; }
    function fit() {
      const {w, h} = size();
      const k = Math.max(MIN_K, Math.min(1.25, (w - 24) / spot.width, (h - 24) / Math.max(1, spot.height)));
      T.k = k;
      T.x = (w - spot.width * k) / 2;
      T.y = Math.max(12, (h - spot.height * k) / 2);
      apply();
    }
    function zoomAt(factor, cx, cy) {
      const {w, h} = size();
      const px = cx === undefined ? w / 2 : cx;
      const py = cy === undefined ? h / 2 : cy;
      const k = Math.max(MIN_K, Math.min(MAX_K, T.k * factor));
      T.x = px - (px - T.x) * (k / T.k);
      T.y = py - (py - T.y) * (k / T.k);
      T.k = k;
      apply();
    }
    function reveal(n) {
      const {w, h} = size();
      const x0 = T.x + n.px * T.k;
      const y0 = T.y + n.py * T.k;
      const x1 = x0 + n.w * T.k;
      const y1 = y0 + n.h * T.k;
      if (x0 < 16) T.x += 16 - x0; else if (x1 > w - 16) T.x -= x1 - (w - 16);
      if (y0 < 16) T.y += 16 - y0; else if (y1 > h - 16) T.y -= y1 - (h - 16);
      apply();
    }
    let drag = null;
    svg.addEventListener('pointerdown', (ev) => {
      if (ev.button !== 0 || ev.target.closest('.node, .edge')) return;
      drag = {x: ev.clientX, y: ev.clientY, tx: T.x, ty: T.y};
      svg.setPointerCapture(ev.pointerId);
      svg.classList.add('panning');
    });
    svg.addEventListener('pointermove', (ev) => {
      if (!drag) return;
      T.x = drag.tx + ev.clientX - drag.x;
      T.y = drag.ty + ev.clientY - drag.y;
      apply();
    });
    const endDrag = () => { drag = null; svg.classList.remove('panning'); };
    svg.addEventListener('pointerup', endDrag);
    svg.addEventListener('pointercancel', endDrag);
    svg.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const r = svg.getBoundingClientRect();
      zoomAt(Math.pow(1.0016, -ev.deltaY), ev.clientX - r.left, ev.clientY - r.top);
    }, {passive: false});
    svg.addEventListener('click', () => { highlight(null, null); });

    box.replaceChildren(svg);
    // fit once the box has a size
    requestAnimationFrame(fit);

    function exportSvg() {
      const doc = svg.cloneNode(true);
      const root = getComputedStyle(document.documentElement);
      doc.querySelector('style').textContent = graphCss((name) => root.getPropertyValue('--' + name).trim());
      doc.querySelector('.viewport').removeAttribute('transform');
      doc.querySelector('.graph-bg').setAttribute('width', String(spot.width));
      doc.querySelector('.graph-bg').setAttribute('height', String(spot.height));
      doc.querySelector('.graph-bg').setAttribute('x', '0');
      doc.querySelector('.graph-bg').setAttribute('y', '0');
      doc.setAttribute('xmlns', SVG_NS);
      doc.setAttribute('viewBox', '0 0 ' + spot.width + ' ' + spot.height);
      doc.setAttribute('width', String(Math.ceil(spot.width)));
      doc.setAttribute('height', String(Math.ceil(spot.height)));
      doc.querySelectorAll('[tabindex]').forEach((n) => n.removeAttribute('tabindex'));
      return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(doc);
    }

    return {
      svg, layout: lay, fit, exportSvg,
      zoomIn: () => zoomAt(1.25), zoomOut: () => zoomAt(0.8),
      transform: () => ({k: T.k, x: T.x, y: T.y}),
      focusFirst: () => { if (order.length) nodeEls.get(order[0].id).focus(); },
      nodeEl: (id) => nodeEls.get(id),
      shown: () => ({nodes: shownNodes.length, edges: shownEdges.length}),
    };
  }

  window.VGraph = {layout, render, place, edgePath, graphCss, NODE_H, GAP_X, GAP_Y};
})();
