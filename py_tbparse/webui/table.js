// A windowed table: only the rows near the viewport exist in the page, so 50,000 rows cost about
// the same as 50. app.js owns the data, the filtering and the menus; this file owns what is on screen.
//
// Rows have a fixed height (the --row-h token), which is what makes windowing cheap: row N always
// sits at N * rowHeight, a spacer row stands in for everything above and below the window, and the
// real scrollbar behaves normally. Because not every row is in the page, the table carries
// aria-rowcount and each row aria-rowindex, so assistive technology still knows the full size.
(function () {
  const BUFFER = 10;
  const MIN_WIDTH = 80;  // narrower and the options button would cover the whole header
  const MAX_WIDTH = 900;
  const CHECK_WIDTH = 72;  // the checkbox column, when a table has one

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, n)); }

  class VTable {
    // handlers: cell(colIndex, value) -> td, sort(colIndex), openRow(pos, rowElement),
    //           menu(colIndex, th), resized(colIndex, width)
    // options.check, when set, adds a leading column of checkboxes: {head, applicable(index) -> bool,
    //           checked(index) -> bool, label(index) -> string, toggle(index, on)}
    constructor(wrap, handlers) {
      this.wrap = wrap;
      this.h = handlers;
      this.table = null;
      this.tbody = null;
      this.thead = null;
      this.colgroup = null;
      this.top = null;
      this.bottom = null;
      this.cols = [];
      this.data = [];
      this.order = [];
      this.display = [];
      this.widths = {};
      this.pinned = null;
      this.sort = {col: -1, dir: 0};
      this.current = null;
      this.check = null;
      this.rowH = 40;
      this.headH = 41;
      this.start = -1;
      this.end = -1;
      this.active = 0;
      this.activeHead = 0;
      this.frame = 0;
      this.swallowClick = false;
      wrap.addEventListener('scroll', () => this.schedule(), {passive: true});
      window.addEventListener('resize', () => this.schedule());
    }

    configure(options) { Object.assign(this, options); }

    schedule() {
      if (this.frame) return;
      this.frame = requestAnimationFrame(() => { this.frame = 0; this.renderWindow(false); });
    }

    isShown() { return !!this.table && this.table.isConnected; }

    widthOf(ci) { return this.widths[ci] || 140; }

    readRowHeight() {
      const css = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--row-h'));
      if (css > 0) this.rowH = css;
    }

    // Rebuild the header and the window. resetScroll sends the view back to the top (a new sort or
    // filter); pinning, hiding and resizing columns keep it where it was.
    build(resetScroll) {
      this.readRowHeight();
      const keepTop = resetScroll === false ? this.wrap.scrollTop : 0;
      const keepLeft = this.isShown() ? this.wrap.scrollLeft : 0;
      const n = this.order.length;
      this.active = clamp(this.active, 0, Math.max(0, n - 1));
      this.activeHead = clamp(this.activeHead, 0, Math.max(0, this.display.length - 1));

      const table = el('table', 'tbl');
      table.setAttribute('aria-rowcount', String(n + 1));
      table.setAttribute('aria-colcount', String(this.display.length + (this.check ? 1 : 0)));

      const colgroup = document.createElement('colgroup');
      let total = 0;
      if (this.check) {
        const box = document.createElement('col');
        box.style.width = CHECK_WIDTH + 'px';
        total += CHECK_WIDTH;
        colgroup.appendChild(box);
      }
      this.display.forEach((ci) => {
        const col = document.createElement('col');
        const w = this.widthOf(ci);
        col.style.width = w + 'px';
        total += w;
        colgroup.appendChild(col);
      });
      table.style.width = total + 'px';
      table.appendChild(colgroup);

      const thead = document.createElement('thead');
      thead.appendChild(this.headerRow());
      table.appendChild(thead);

      const tbody = document.createElement('tbody');
      this.top = this.spacer();
      this.bottom = this.spacer();
      this.bottom.firstChild.style.height = n * this.rowH + 'px';
      tbody.append(this.top, this.bottom);
      table.appendChild(tbody);

      this.table = table;
      this.thead = thead;
      this.tbody = tbody;
      this.colgroup = colgroup;
      this.bindEvents();
      this.wrap.replaceChildren(table);
      this.headH = thead.getBoundingClientRect().height || this.headH;
      this.wrap.scrollTop = keepTop;
      this.wrap.scrollLeft = keepLeft;
      this.start = -1;
      this.end = -1;
      this.renderWindow(true);
      // The first real row tells us the true height, in case the stylesheet rounds it.
      const first = tbody.querySelector('tr[data-pos]');
      if (first) {
        const h = first.getBoundingClientRect().height;
        if (h > 0 && Math.abs(h - this.rowH) > 0.5) {
          this.rowH = h;
          this.bottom.firstChild.style.height = n * this.rowH + 'px';
          this.wrap.scrollTop = keepTop;
          this.renderWindow(true);
        }
      }
    }

    spacer() {
      const tr = el('tr', 'spacer');
      tr.setAttribute('aria-hidden', 'true');
      const td = document.createElement('td');
      td.colSpan = Math.max(1, this.display.length + (this.check ? 1 : 0));
      tr.appendChild(td);
      return tr;
    }

    headerRow() {
      const tr = document.createElement('tr');
      tr.setAttribute('aria-rowindex', '1');
      if (this.check) {
        const th = el('th', 'sel', this.check.head);
        th.setAttribute('aria-colindex', '1');
        tr.appendChild(th);
      }
      this.display.forEach((ci, k) => {
        const name = this.cols[ci];
        const th = document.createElement('th');
        th.dataset.col = String(ci);
        th.setAttribute('aria-colindex', String(k + 1 + (this.check ? 1 : 0)));
        th.setAttribute('aria-keyshortcuts', 'Alt+ArrowDown');
        th.tabIndex = k === this.activeHead ? 0 : -1;
        const sorted = this.sort.col === ci;
        th.setAttribute('aria-sort', sorted ? (this.sort.dir === 1 ? 'ascending' : 'descending') : 'none');
        if (ci === this.pinned) th.classList.add('pin');
        const label = el('span', 'th-label', name);
        const arrow = el('span', 'arrow', sorted ? (this.sort.dir === 1 ? '▲' : '▼') : '');
        const menu = el('button', 'col-menu-btn', '⋯');
        menu.type = 'button';
        menu.tabIndex = -1;
        menu.setAttribute('aria-label', 'Options for column ' + name);
        menu.setAttribute('aria-haspopup', 'menu');
        menu.setAttribute('aria-expanded', 'false');
        const grip = el('span', 'col-resize');
        grip.setAttribute('aria-hidden', 'true');
        th.append(label, arrow, menu, grip);
        tr.appendChild(th);
      });
      return tr;
    }

    bindEvents() {
      const head = this.thead;
      head.addEventListener('click', (e) => {
        const th = e.target.closest('th');
        if (!th || th.classList.contains('sel') || e.target.closest('.col-resize')) return;
        // the click that ends a column drag, released over the header, must not sort it
        if (this.swallowClick) return;
        const ci = Number(th.dataset.col);
        if (e.target.closest('.col-menu-btn')) { this.h.menu(ci, th); return; }
        this.h.sort(ci);
      });
      head.addEventListener('keydown', (e) => this.onHeadKey(e));
      head.addEventListener('focusin', (e) => {
        const th = e.target.closest('th');
        if (!th || th.classList.contains('sel')) return;
        const heads = Array.from(head.querySelectorAll('th:not(.sel)'));
        this.activeHead = heads.indexOf(th);
        heads.forEach((other) => { other.tabIndex = other === th ? 0 : -1; });
      });
      head.addEventListener('pointerdown', (e) => {
        const grip = e.target.closest('.col-resize');
        if (grip) this.startResize(e, Number(grip.parentElement.dataset.col));
      });
      const body = this.tbody;
      body.addEventListener('click', (e) => {
        const tr = e.target.closest('tr[data-pos]');
        if (tr && !e.target.closest('td.sel')) this.h.openRow(Number(tr.dataset.pos), tr);
      });
      body.addEventListener('keydown', (e) => this.onRowKey(e));
      body.addEventListener('focusin', (e) => {
        const tr = e.target.closest('tr[data-pos]');
        if (!tr) return;
        this.active = Number(tr.dataset.pos);
        body.querySelectorAll('tr[tabindex="0"]').forEach((row) => this.setStop(row, false));
        this.setStop(tr, true);
      });
    }

    onHeadKey(e) {
      const th = e.target.closest('th');
      if (!th || e.target !== th) return;
      const heads = Array.from(this.thead.querySelectorAll('th:not(.sel)'));
      const at = heads.indexOf(th);
      const ci = Number(th.dataset.col);
      const go = (to) => { e.preventDefault(); heads[clamp(to, 0, heads.length - 1)].focus(); };
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.h.sort(ci); }
      else if (e.key === 'ArrowRight') go(at + 1);
      else if (e.key === 'ArrowLeft') go(at - 1);
      else if (e.key === 'Home') go(0);
      else if (e.key === 'End') go(heads.length - 1);
      else if ((e.key === 'ArrowDown' && e.altKey) || e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey)) {
        e.preventDefault();
        this.h.menu(ci, th);
      }
    }

    onRowKey(e) {
      const tr = e.target;
      if (tr.tagName !== 'TR' || tr.dataset.pos === undefined) return;
      const pos = Number(tr.dataset.pos);
      const page = Math.max(1, Math.floor((this.wrap.clientHeight - this.headH) / this.rowH) - 1);
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.h.openRow(pos, tr); return; }
      const target = {
        ArrowDown: pos + 1, ArrowUp: pos - 1, PageDown: pos + page, PageUp: pos - page,
        Home: 0, End: this.order.length - 1,
      }[e.key];
      if (target !== undefined) { e.preventDefault(); this.focusRow(target); }
    }

    // Draw the rows that are, or are about to be, on screen.
    renderWindow(force) {
      if (!this.isShown()) return;
      const n = this.order.length;
      const area = Math.max(this.wrap.clientHeight - this.headH, this.rowH);
      const first = Math.max(0, Math.floor(this.wrap.scrollTop / this.rowH) - BUFFER);
      const last = Math.min(n, Math.ceil((this.wrap.scrollTop + area) / this.rowH) + BUFFER);
      if (!force && first === this.start && last === this.end) return;
      this.start = first;
      this.end = last;
      const focused = this.tbody.contains(document.activeElement) ? document.activeElement : null;
      const focusedRow = focused && focused.closest ? focused.closest('tr[data-pos]') : null;
      const focusedPos = focusedRow ? focusedRow.dataset.pos : undefined;
      const focusedBox = !!focused && focused.tagName === 'INPUT';
      const rows = document.createDocumentFragment();
      for (let pos = first; pos < last; pos++) rows.appendChild(this.rowElement(pos));
      this.top.firstChild.style.height = first * this.rowH + 'px';
      this.bottom.firstChild.style.height = (n - last) * this.rowH + 'px';
      this.tbody.replaceChildren(this.top, rows, this.bottom);
      // The table keeps exactly one tab stop, even when the active row scrolled out of the window.
      if (!this.tbody.querySelector('tr[tabindex="0"]')) {
        const any = this.tbody.querySelector('tr[data-pos]');
        if (any) this.setStop(any, true);
      }
      if (focusedPos !== undefined) {
        const again = this.tbody.querySelector('tr[data-pos="' + focusedPos + '"]');
        const box = again && focusedBox ? again.querySelector('input') : null;
        if (box) box.focus({preventScroll: true});
        else if (again) again.focus({preventScroll: true});
      }
    }

    // The one tab stop of the table is a row; the checkbox inside it is reached with Tab from there.
    setStop(tr, on) {
      tr.tabIndex = on ? 0 : -1;
      const box = tr.querySelector('input');
      if (box) box.tabIndex = on ? 0 : -1;
    }

    rowElement(pos) {
      const index = this.order[pos];
      const row = this.data[index];
      const tr = document.createElement('tr');
      tr.dataset.pos = String(pos);
      tr.setAttribute('aria-rowindex', String(pos + 2));
      tr.tabIndex = pos === this.active ? 0 : -1;
      if (this.check) this.checkCell(tr, index, pos === this.active);
      // A stable name per row lets the browser animate rows to their new place after a sort.
      tr.style.viewTransitionName = 'r' + index;
      if (index === this.current) tr.setAttribute('aria-current', 'true');
      this.display.forEach((ci) => {
        const td = this.h.cell(ci, row[ci], index);
        if (ci === this.pinned) td.classList.add('pin');
        tr.appendChild(td);
      });
      return tr;
    }

    checkCell(tr, index, stop) {
      const td = el('td', 'sel');
      if (this.check.applicable(index)) {
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.checked = this.check.checked(index);
        box.tabIndex = stop ? 0 : -1;
        box.setAttribute('aria-label', this.check.label(index));
        box.addEventListener('change', () => {
          tr.classList.toggle('left-out', !box.checked);
          this.check.toggle(index, box.checked);
        });
        td.appendChild(box);
        tr.classList.toggle('left-out', !box.checked);
      }
      tr.appendChild(td);
    }

    // Scroll row pos into view if it is not, draw it, and focus it.
    focusRow(pos) {
      const n = this.order.length;
      if (!n) return;
      pos = clamp(pos, 0, n - 1);
      this.active = pos;
      const area = this.wrap.clientHeight - this.headH;
      const top = pos * this.rowH;
      if (top < this.wrap.scrollTop) this.wrap.scrollTop = top;
      else if (top + this.rowH > this.wrap.scrollTop + area) this.wrap.scrollTop = top + this.rowH - area;
      this.renderWindow(true);
      const tr = this.tbody.querySelector('tr[data-pos="' + pos + '"]');
      if (tr) tr.focus({preventScroll: true});
    }

    focusRowByIndex(index) {
      const pos = this.order.indexOf(index);
      if (pos >= 0) this.focusRow(pos);
      else this.wrap.focus();
    }

    focusHeader(ci) {
      if (!this.thead) return;
      const th = this.thead.querySelector('th[data-col="' + ci + '"]') || this.thead.querySelector('th');
      if (th) th.focus();
    }

    // Mark which row is open in the details drawer.
    setCurrent(index) {
      this.current = index;
      if (!this.tbody) return;
      this.tbody.querySelectorAll('tr[data-pos]').forEach((tr) => {
        if (this.order[Number(tr.dataset.pos)] === index) tr.setAttribute('aria-current', 'true');
        else tr.removeAttribute('aria-current');
      });
    }

    setWidth(ci, width) {
      const w = clamp(Math.round(width), MIN_WIDTH, MAX_WIDTH);
      this.widths[ci] = w;
      const at = this.display.indexOf(ci);
      if (at < 0 || !this.colgroup) return w;
      this.colgroup.children[at].style.width = w + 'px';
      let total = 0;
      this.display.forEach((c) => { total += this.widthOf(c); });
      this.table.style.width = total + 'px';
      return w;
    }

    startResize(e, ci) {
      e.preventDefault();
      e.stopPropagation();
      const grip = e.target.closest('.col-resize');
      const startX = e.clientX;
      const startWidth = this.widthOf(ci);
      // Capture keeps the drag going when the pointer leaves the grip.
      try { grip.setPointerCapture(e.pointerId); } catch (err) { /* the window listeners still work */ }
      const move = (ev) => this.setWidth(ci, startWidth + ev.clientX - startX);
      const finish = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', finish);
        window.removeEventListener('pointercancel', finish);
        // That click is dispatched in this same turn, so the flag only needs to outlive it.
        this.swallowClick = true;
        setTimeout(() => { this.swallowClick = false; }, 0);
        this.h.resized(ci, this.widthOf(ci));
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', finish);
      window.addEventListener('pointercancel', finish);
    }
  }

  window.VTable = VTable;
})();
