'use strict';
// The rename review's bookkeeping (rename.js): which rows get a checkbox, what is left out, and the
// ids sent to the server. The ids must equal rename_id() in py_tbparse/rename.py.
const test = require('node:test');
const assert = require('node:assert/strict');
const {loadRename} = require('./load.js');

// The script runs in its own vm context, so its objects have another Object.prototype; compare as plain data.
const plain = (x) => JSON.parse(JSON.stringify(x));

const COLS = ['kind', 'datasource', 'name', 'current', 'suggested', 'changed', 'reason'];

// A stand-in for the helpers app.js hands to init().
function setup(rows, table = 'field-renames') {
  const R = loadRename();
  const els = {};
  const get = (id) => els[id] || (els[id] = {
    hidden: false, disabled: false, textContent: '', attrs: {},
    addEventListener() {}, setAttribute(k, v) { this.attrs[k] = v; },
  });
  let redraws = 0;
  R.init({$: get, state: {table, columns: COLS, data: rows}, redraw: () => { redraws += 1; },
          fail() {}, setStatus() {}, options: () => ({})});
  R.load(COLS, rows);
  return {R, get, redraws: () => redraws};
}

const ROWS = [
  ['field', 'ds1', 'a b', 'a b', 'a_b', true, ''],
  ['field', 'ds1', 'c', 'c', 'c', false, ''],
  ['field', 'ds1', 'd', 'd', 'D', true, 'conflict'],
  ['table', 'ds2', 'e f', 'e f', 'e_f', true, ''],
];

test('only changed, non-conflicting rows get a checkbox', () => {
  const {R} = setup(ROWS);
  const c = R.check();
  assert.deepEqual([0, 1, 2, 3].map((i) => c.applicable(i)), [true, false, false, true]);
  assert.equal(c.head, 'Include');
});

test('the review is off outside Field renames or with nothing to apply', () => {
  assert.equal(setup(ROWS, 'fields').R.check(), null);
  assert.equal(setup([ROWS[1]]).R.check(), null);
});

test('the ids join kind, datasource and name with U+001F; a missing kind is "field"', () => {
  const {R} = setup([['', 'ds1', 'x', 'x', 'y', true, ''], [null, null, 'z', 'z', 'y', true, '']]);
  const c = R.check();
  c.toggle(0, false);
  c.toggle(1, false);
  assert.deepEqual(plain(R.body({}).exclude), ['field\u001fds1\u001fx', 'field\u001f\u001fz']);
});

test('everything is kept at first and the request body has no exclude list', () => {
  const {R} = setup(ROWS);
  const opts = {a: 1};
  assert.equal(R.body(opts), opts);
  assert.equal(R.check().checked(0), true);
});

test('unticking a rename leaves it out and the button counts what is kept', () => {
  const {R, get} = setup(ROWS);
  assert.equal(get('createBtn').textContent, 'Create with 2 of 2 renames');
  R.check().toggle(0, false);
  assert.equal(R.check().checked(0), false);
  assert.equal(get('createBtn').textContent, 'Create with 1 of 2 renames');
  assert.equal(get('renameCount').textContent, '1 of 2 selected');
  assert.deepEqual(plain(R.body({a: 1})), {a: 1, exclude: ['field\u001fds1\u001fa b']});
  R.check().toggle(0, true);
  assert.equal(get('renameCount').textContent, 'All 2 selected');
});

test('leaving every rename out disables Create and Download', () => {
  const {R, get} = setup(ROWS);
  R.check().toggle(0, false);
  R.check().toggle(3, false);
  assert.equal(get('createBtn').disabled, true);
  assert.equal(get('downloadBtn').attrs['aria-disabled'], 'true');
  assert.match(get('renameCount').textContent, /^Nothing is selected/);
});

test('one rename reads "rename", not "renames"; no renames hides the review', () => {
  const one = setup([ROWS[0]]);
  assert.equal(one.get('createBtn').textContent, 'Create with 1 of 1 rename');
  const none = setup([ROWS[1]]);
  assert.equal(none.get('renameSelect').hidden, true);
  assert.equal(none.get('createBtn').textContent, 'Create fixed workbook');
});

test('the checkbox label names the rename', () => {
  const {R} = setup(ROWS);
  assert.equal(R.check().label(0), 'Rename a b to a_b');
});

test('a reload forgets left-out renames that are no longer offered', () => {
  const {R} = setup(ROWS);
  R.check().toggle(0, false);
  R.check().toggle(3, false);
  R.load(COLS, [ROWS[3]]);  // only "e f" is still a rename
  assert.deepEqual(plain(R.body({}).exclude), ['table\u001fds2\u001fe f']);
});
