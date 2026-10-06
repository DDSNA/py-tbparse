// The Audit view: the findings of `py-tbparse audit` for the open workbook (see workbook_audit.py), with
// severity, rule and text filters, rules that can be skipped, and downloads. The server sends one page of at most
// PAGE rows (and says how many match), so the page never holds more than that. Everything is inside one function
// so no name here can clash with app.js, which passes in its helpers (init) and calls render and reset.
(function () {
  'use strict';

  const PAGE = 100;
  const NOISY = { A008: 'noisy for a workbook that is shared as a file' };
  const SEVERITY_WORD = { error: 'Error', warning: 'Warning', info: 'Info' };
  const SEVERITY_MARK = { error: '✖', warning: '▲', info: '•' };
  const EXIT_TEXT = {
    0: 'Exit code 0: no error finding, so a CI run of py-tbparse audit would pass.',
    1: 'Exit code 1: at least one error finding, so a CI run of py-tbparse audit would fail (the default is to fail on errors; --fail-on changes that).',
    3: 'Exit code 3: a rule crashed. That is a bug in py-tbparse, not a finding about the workbook.',
  };

  let D = null;                      // helpers from app.js: $, el, fetchJSON, fail, setStatus, plural
  let q = fresh();                   // what the person chose
  let req = 0;
  let timer = null;
  let skipOpen = false;
  let last = null;                   // the last answer, so the controls can be built before a refetch finishes

  function fresh() { return { skip: new Set(), severity: '', rule: '', text: '', offset: 0 }; }
  function init(helpers) { D = helpers; }
  function reset() { q = fresh(); last = null; skipOpen = false; clearTimeout(timer); req++; }

  function params(withPage) {
    const p = new URLSearchParams();
    if (q.skip.size) p.set('skip', Array.from(q.skip).sort().join(','));
    if (q.severity) p.set('severity', q.severity);
    if (q.rule) p.set('rule', q.rule);
    if (q.text) p.set('q', q.text);
    if (withPage) { p.set('offset', String(q.offset)); p.set('limit', String(PAGE)); }
    return p.toString();
  }
  function href(path, extra) {
    const s = [extra, params(false)].filter(Boolean).join('&');
    return path + (s ? '?' + s : '');
  }
  function num(n) { return Number(n).toLocaleString('en-US'); }

  function mark(sev) {
    const m = D.el('span', 'audit-sev ' + sev);
    const glyph = D.el('span', '', SEVERITY_MARK[sev]);
    glyph.setAttribute('aria-hidden', 'true');
    m.append(glyph, D.el('span', '', SEVERITY_WORD[sev]));
    return m;
  }

  function summaryBlock(data) {
    const box = D.el('div', 'audit-summary');
    const line = D.el('p', 'audit-line');
    line.id = 'auditSummary';
    line.setAttribute('role', 'status');
    const strong = D.el('strong', '', data.summary);
    line.append(strong);
    if (data.skipped.length) line.append(' (without ' + data.skipped.join(', ') + ')');
    box.appendChild(line);
    const exit = D.el('p', 'audit-exit', EXIT_TEXT[data.exit_code] || '');
    exit.dataset.exit = String(data.exit_code);
    box.appendChild(exit);
    if (data.crashed.length) {
      box.appendChild(D.el('p', 'audit-crash', 'Crashed: ' + data.crashed.join(', ') + '. The traceback is in the terminal output of py-tbparse audit.'));
    }
    return box;
  }

  function filterBar(data) {
    const bar = D.el('div', 'audit-filters');
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Filter the findings');

    const sev = D.el('select', 'field');
    sev.id = 'auditSeverity';
    sev.setAttribute('aria-label', 'Severity');
    [['', 'All severities'], ['error', 'Errors (' + data.counts.error + ')'],
     ['warning', 'Warnings (' + data.counts.warning + ')'], ['info', 'Info (' + data.counts.info + ')']].forEach(([v, t]) => {
      const o = D.el('option', '', t); o.value = v; sev.appendChild(o);
    });
    sev.value = q.severity;
    sev.addEventListener('change', () => { q.severity = sev.value; q.offset = 0; load(); });

    const rule = D.el('select', 'field');
    rule.id = 'auditRule';
    rule.setAttribute('aria-label', 'Rule');
    const all = D.el('option', '', 'All rules'); all.value = ''; rule.appendChild(all);
    data.rules.filter((r) => !r.skipped).forEach((r) => {
      const o = D.el('option', '', r.id + ' (' + r.count + ')'); o.value = r.id; rule.appendChild(o);
    });
    rule.value = q.rule;
    rule.addEventListener('change', () => { q.rule = rule.value; q.offset = 0; load(); });

    const text = D.el('input', 'field');
    text.id = 'auditText'; text.type = 'search'; text.value = q.text; text.placeholder = 'Search the findings';
    text.setAttribute('aria-label', 'Search the findings');
    text.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => { q.text = text.value.trim(); q.offset = 0; load(); }, 250);
    });
    bar.append(sev, rule, text);
    return bar;
  }

  function skipBlock(data) {
    const box = D.el('details', 'audit-skip');
    box.id = 'auditSkip';
    box.open = skipOpen;
    box.addEventListener('toggle', () => { skipOpen = box.open; });
    const head = D.el('summary', '', q.skip.size ? 'Skip rules (' + q.skip.size + ' skipped)' : 'Skip rules');
    box.appendChild(head);
    box.appendChild(D.el('p', 'note', 'A skipped rule is not run, so its findings are left out of the counts, the exit code and the downloads. Like py-tbparse audit --skip.'));
    const list = D.el('ul', 'audit-rules');
    data.rules.forEach((r) => {
      const li = D.el('li');
      const label = D.el('label', 'check');
      const cb = D.el('input'); cb.type = 'checkbox'; cb.value = r.id; cb.checked = r.skipped;
      cb.addEventListener('change', () => {
        if (cb.checked) q.skip.add(r.id); else q.skip.delete(r.id);
        if (q.rule === r.id) q.rule = '';
        q.offset = 0;
        skipOpen = true;
        load();
      });
      const text = D.el('span', '');
      text.append(D.el('strong', '', r.id), ' ', D.el('span', 'audit-rule-title', r.title));
      label.append(cb, text);
      li.appendChild(label);
      const meta = [r.severity, r.skipped ? 'skipped' : D.plural(r.count, 'finding')];
      if (NOISY[r.id]) meta.push(NOISY[r.id]);
      li.appendChild(D.el('span', 'audit-rule-meta', meta.join(', ')));
      list.appendChild(li);
    });
    box.appendChild(list);
    return box;
  }

  function table(data) {
    if (!data.findings.length) {
      const none = D.el('p', 'audit-empty', data.total
        ? 'No finding matches these filters.'
        : (data.skipped.length ? 'No findings in the rules that ran.' : 'No findings. Every rule ran and none found anything.'));
      return none;
    }
    const wrap = D.el('div', 'audit-table-wrap');
    const t = D.el('table', 'audit-table');
    t.id = 'auditTable';
    const cap = D.el('caption', 'sr-only', 'Findings of the audit');
    const head = D.el('thead');
    const hr = D.el('tr');
    ['Rule', 'Severity', 'Message', 'Object'].forEach((h) => { const th = D.el('th', '', h); th.scope = 'col'; hr.appendChild(th); });
    head.appendChild(hr);
    const body = D.el('tbody');
    data.findings.forEach((f) => {
      const tr = D.el('tr');
      tr.dataset.rule = f.rule; tr.dataset.severity = f.severity;
      tr.appendChild(D.el('td', 'audit-id', f.rule));
      const s = D.el('td'); s.appendChild(mark(f.severity)); tr.appendChild(s);
      const m = D.el('td', 'audit-msg');
      m.appendChild(D.el('div', '', f.detail));
      if (f.fix) m.appendChild(D.el('div', 'audit-fix', 'Fix: ' + f.fix));
      tr.appendChild(m);
      tr.appendChild(D.el('td', 'audit-object', f.object));
      body.appendChild(tr);
    });
    t.append(cap, head, body);
    wrap.appendChild(t);
    return wrap;
  }

  function pager(data) {
    const box = D.el('div', 'audit-pager');
    if (!data.matching) return box;
    const first = data.offset + 1;
    const lastRow = data.offset + data.findings.length;
    const text = D.el('span', 'audit-count', 'Showing ' + num(first) + '–' + num(lastRow) + ' of ' + num(data.matching) +
                      (data.matching !== data.total ? ' matching findings (' + num(data.total) + ' in all)' : ' findings'));
    text.id = 'auditCount';
    box.appendChild(text);
    const prev = D.el('button', 'btn small', 'Previous ' + PAGE);
    prev.type = 'button'; prev.id = 'auditPrev'; prev.disabled = data.offset === 0;
    prev.addEventListener('click', () => { q.offset = Math.max(0, q.offset - PAGE); load(true); });
    const next = D.el('button', 'btn small', 'Next ' + PAGE);
    next.type = 'button'; next.id = 'auditNext'; next.disabled = lastRow >= data.matching;
    next.addEventListener('click', () => { q.offset += PAGE; load(true); });
    box.append(prev, next);
    const rest = data.matching - data.findings.length;   // rows not on this page
    if (rest > 0) {
      const more = D.el('span', 'note', num(rest) + ' more on other pages. Download for all of them.');
      more.id = 'auditMore';
      box.appendChild(more);
    }
    return box;
  }

  function downloads() {
    const box = D.el('div', 'audit-downloads');
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', 'Downloads');
    [['auditCsv', 'Download CSV', href('/audit/export', 'format=csv')],
     ['auditJson', 'Download JSON', href('/audit/export', 'format=json')]].forEach(([id, label, url]) => {
      const a = D.el('a', 'btn', label); a.id = id; a.href = url; a.setAttribute('download', '');
      box.appendChild(a);
    });
    const dict = D.el('a', 'btn', 'Data dictionary (Markdown)');
    dict.id = 'auditDict'; dict.href = '/dictionary'; dict.setAttribute('download', '');
    dict.title = 'The data dictionary of the whole workbook, like py-tbparse docs';
    box.appendChild(dict);
    box.appendChild(D.el('span', 'note', 'The downloads hold every finding that matches the filters, not only this page.'));
    return box;
  }

  function draw(wrap, data, keepFocus) {
    const focusId = keepFocus || (document.activeElement && wrap.contains(document.activeElement) ? document.activeElement.id : '');
    const caret = focusId === 'auditText' ? $text().selectionStart : null;
    const panel = D.el('div', 'audit');
    panel.append(summaryBlock(data), filterBar(data), skipBlock(data), table(data), pager(data), downloads());
    wrap.innerHTML = '';
    wrap.appendChild(panel);
    if (focusId) {
      const node = document.getElementById(focusId);
      if (node && !node.disabled) {
        node.focus();
        if (caret !== null && node.setSelectionRange) { try { node.setSelectionRange(caret, caret); } catch (e) { /* not a text box */ } }
      }
    }
  }
  function $text() { return document.getElementById('auditText') || { selectionStart: null }; }

  async function load(scrollTop) {
    const wrap = D.$('tableWrap');
    const mine = ++req;
    try {
      const data = await D.fetchJSON('/audit?' + params(true));
      if (mine !== req) return;
      last = data;
      D.$('meta').textContent = data.matching === data.total ? D.plural(data.total, 'finding')
        : num(data.matching) + ' of ' + num(data.total) + ' findings';
      draw(wrap, data, '');
      if (scrollTop) wrap.scrollTop = 0;
      D.$('announce').textContent = 'Audit: ' + data.summary + (data.matching !== data.total ? ', ' + num(data.matching) + ' match the filters' : '');
    } catch (e) {
      if (mine !== req) return;
      // a rejected option (never expected from the page controls) goes back to the plain audit
      q = fresh(); last = null;
      D.fail(e);
    }
  }

  // Called by app.js when the Audit view is chosen; resolves once the findings are on the page.
  function render() {
    D.$('exportLink').hidden = true;
    return load(false);
  }

  window.AuditView = { init: init, render: render, reset: reset, pageSize: PAGE };
})();
