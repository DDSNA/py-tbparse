// Rename review: in the Field renames view, a checkbox on every suggested rename lets you leave some out.
// Left-out renames stay as they are, and the server honours the list for Create and for Download (see
// `select_renames` in rename.py). The checkboxes live in table.js (the `check` option), so only the rows near
// the viewport are ever in the page. app.js passes in its helpers (init) and calls load, check and body.
// Everything is inside one function so no name here can clash with app.js.
(function () {
  'use strict';

  let D = null;            // the helpers from app.js: $, state, fetchJSON, fail, setStatus, options, redraw
  let ids = [];            // per data row: the id of a rename that would be applied, else null
  let total = 0;           // how many renames would be applied
  const left = new Set();  // ids of the renames the person left out

  // The same id as rename_id() in rename.py: kind, datasource and name joined by U+001F.
  function idOf(cols, row) {
    const at = (name) => cols.indexOf(name);
    const get = (name) => (at(name) < 0 || row[at(name)] === null ? '' : String(row[at(name)]));
    return [get('kind') || 'field', get('datasource'), get('name')].join('\u001f');
  }

  function load(cols, data) {
    const changed = cols.indexOf('changed');
    const reason = cols.indexOf('reason');
    ids = data.map((row) => (row[changed] === true && row[reason] !== 'conflict' ? idOf(cols, row) : null));
    const known = new Set(ids.filter(Boolean));
    total = known.size;
    Array.from(left).forEach((id) => { if (!known.has(id)) left.delete(id); });  // a changed option can drop a row
    refresh();
  }

  function kept() { return total - left.size; }

  function refresh() {
    const create = D.$('createBtn');
    const download = D.$('downloadBtn');
    const note = D.$('renameCount');
    const review = total > 0;
    D.$('renameSelect').hidden = !review;
    create.textContent = review ? 'Create with ' + kept() + ' of ' + total + ' ' + (total === 1 ? 'rename' : 'renames')
                                : 'Create fixed workbook';
    const none = review && kept() === 0;
    create.disabled = none;
    download.setAttribute('aria-disabled', none ? 'true' : 'false');
    download.classList.toggle('disabled', none);
    note.textContent = !review ? '' : none ? 'Nothing is selected. Tick at least one rename.'
      : kept() === total ? 'All ' + total + ' selected' : kept() + ' of ' + total + ' selected';
  }

  function setAll(on) {
    if (on) left.clear();
    else ids.forEach((id) => { if (id) left.add(id); });
    refresh();
    D.redraw();
  }

  function check() {
    if (D.state.table !== 'field-renames' || !total) return null;
    const cols = D.state.columns;
    const text = (index, name) => String(D.state.data[index][cols.indexOf(name)] || '');
    return {
      head: 'Include',
      applicable: (index) => !!ids[index],
      checked: (index) => !left.has(ids[index]),
      label: (index) => 'Rename ' + text(index, 'current') + ' to ' + text(index, 'suggested'),
      toggle: (index, on) => {
        if (on) left.delete(ids[index]);
        else left.add(ids[index]);
        refresh();
      },
    };
  }

  // The request options plus the ids to leave out (none when everything is kept, as before).
  function body(opts) {
    return left.size ? Object.assign({}, opts, {exclude: Array.from(left)}) : opts;
  }

  // Download is a plain link; with renames left out the list is sent in a POST body (a URL could not hold
  // it) and the answer is saved from here.
  async function download(e) {
    if (D.$('downloadBtn').getAttribute('aria-disabled') === 'true') { e.preventDefault(); return; }
    if (!left.size) return;
    e.preventDefault();
    D.setStatus('Making your fixed copy ...', false, 'busy');
    try {
      const res = await fetch('/download-workbook', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body(D.options())),
      });
      if (!res.ok) throw new Error((await res.json()).error || res.statusText);
      const named = /filename\*=UTF-8''([^;]+)/.exec(res.headers.get('Content-Disposition') || '');
      const link = document.createElement('a');
      link.href = URL.createObjectURL(await res.blob());
      link.download = named ? decodeURIComponent(named[1]) : 'workbook_renamed';
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 10000);
      D.setStatus('Downloaded a fixed copy with ' + kept() + ' of ' + total + ' renames', false, 'ok');
    } catch (err) {
      D.fail(err, 'Nothing was saved');
    }
  }

  function init(helpers) {
    D = helpers;
    D.$('renameAll').addEventListener('click', () => setAll(true));
    D.$('renameNone').addEventListener('click', () => setAll(false));
    D.$('downloadBtn').addEventListener('click', download);
  }

  window.RenameReview = {init, load, check, body};
})();
