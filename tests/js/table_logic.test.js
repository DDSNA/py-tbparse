'use strict';
// The GUI's table logic (search, column filters, sorting) from app.js, run without a browser.
// Run: node --test tests/js/
const test = require('node:test');
const assert = require('node:assert/strict');
const {loadApp} = require('./load.js');

// A table: columns, rows, and the stand-ins for the page state the functions read.
function app({columns, data, filterBox = '', views = {}, table = 't', dsLabels = {}}) {
  const state = {table, columns, data, sortCol: -1, sortDir: 0, hay: null, hayKey: '', colLower: {},
                 sortKeys: {}, numeric: {}, natural: null, dsLabels};
  const globals = {
    state, views, hayJob: 0,
    $: (id) => (id === 'filter' ? {value: filterBox} : null),
  };
  const fns = loadApp(
    ['colIndex', 'liveFilters', 'viewFor', 'friendlyDatasource', 'shownText', 'searchText', 'visibleSig',
     'rowHay', 'ensureHay', 'colLowerFor', 'naturalOrder', 'isNumericColumn', 'sortKeys', 'sortOrder',
     'computeOrder', 'baseName', 'plural'],
    ['COLLATOR', 'OPAQUE_ID'],
    globals,
  );
  return Object.assign({state, views}, fns);
}

const COLS = ['name', 'count', 'datasource'];
const ROWS = [
  ['Sales', 10, 'Orders'],
  ['profit', 2, 'Orders'],
  ['Region', null, 'People'],
  ['alpha 10', 7, 'People'],
  ['alpha 2', 30, 'Orders'],
];

test('no search and no sort keeps the natural order', () => {
  const a = app({columns: COLS, data: ROWS});
  assert.deepEqual(Array.from(a.computeOrder()), [0, 1, 2, 3, 4]);
});

test('the search box matches any visible column, ignoring case', () => {
  const a = app({columns: COLS, data: ROWS, filterBox: '  PEOPLE '});
  assert.deepEqual(Array.from(a.computeOrder()), [2, 3]);
});

test('the search box does not look in a hidden column', () => {
  const views = {t: {hidden: new Set(['datasource']), widths: {}, auto: {}, pinned: null, filters: []}};
  const a = app({columns: COLS, data: ROWS, filterBox: 'people', views});
  assert.deepEqual(Array.from(a.computeOrder()), []);
});

test('a column filter only looks at its own column', () => {
  const views = {t: {hidden: new Set(), widths: {}, auto: {}, pinned: null, filters: [{col: 'name', text: 'ALP'}]}};
  const a = app({columns: COLS, data: ROWS, views});
  assert.deepEqual(Array.from(a.computeOrder()), [3, 4]);
});

test('column filters and the search box narrow each other', () => {
  const views = {t: {hidden: new Set(), widths: {}, auto: {}, pinned: null,
                     filters: [{col: 'datasource', text: 'orders'}]}};
  const a = app({columns: COLS, data: ROWS, filterBox: 'a', views});
  // Of the three "Orders" rows, only Sales and "alpha 2" contain an "a" (profit and Orders itself do not).
  assert.deepEqual(Array.from(a.computeOrder()), [0, 4]);
});

test('a filter on a column the table does not have is ignored', () => {
  const views = {t: {hidden: new Set(), widths: {}, auto: {}, pinned: null, filters: [{col: 'gone', text: 'x'}]}};
  const a = app({columns: COLS, data: ROWS, views});
  assert.deepEqual(a.liveFilters(views.t), []);
  assert.deepEqual(Array.from(a.computeOrder()), [0, 1, 2, 3, 4]);
});

test('a numeric column sorts by value, nulls last in both directions', () => {
  const a = app({columns: COLS, data: ROWS});
  assert.equal(a.isNumericColumn(1), true);
  assert.deepEqual(Array.from(a.sortOrder([0, 1, 2, 3, 4], 1, 1)), [1, 3, 0, 4, 2]);
  assert.deepEqual(Array.from(a.sortOrder([0, 1, 2, 3, 4], 1, -1)), [4, 0, 3, 1, 2]);
});

test('a text column sorts naturally and without regard to case, nulls last', () => {
  const a = app({columns: COLS, data: ROWS});
  assert.equal(a.isNumericColumn(0), false);
  // alpha 2 before alpha 10 (numeric collation); profit before Region before Sales (case ignored)
  assert.deepEqual(Array.from(a.sortOrder([0, 1, 2, 3, 4], 0, 1)), [4, 3, 1, 2, 0]);
  assert.deepEqual(Array.from(a.sortOrder([0, 1, 2, 3, 4], 0, -1)), [0, 2, 1, 3, 4]);
});

test('a text column with a null puts it last whichever way it sorts', () => {
  const data = [['b'], [null], ['a']];
  const a = app({columns: ['x'], data});
  assert.deepEqual(Array.from(a.sortOrder([0, 1, 2], 0, 1)), [2, 0, 1]);
  assert.deepEqual(Array.from(a.sortOrder([0, 1, 2], 0, -1)), [0, 2, 1]);
});

test('a column with a string among numbers is not numeric', () => {
  const a = app({columns: ['x'], data: [[1], ['2'], [3]]});
  assert.equal(a.isNumericColumn(0), false);
});

test('a column of only nulls is not numeric', () => {
  const a = app({columns: ['x'], data: [[null], [null]]});
  assert.equal(a.isNumericColumn(0), false);
});

test('sorting applies after filtering and leaves the data alone', () => {
  const a = app({columns: COLS, data: ROWS, filterBox: 'orders'});
  a.state.sortCol = 1;
  a.state.sortDir = -1;
  assert.deepEqual(Array.from(a.computeOrder()), [4, 0, 1]);
  assert.equal(a.state.data[0][0], 'Sales');
});

test('sortOrder does not change the order it is given', () => {
  const a = app({columns: COLS, data: ROWS});
  const order = [0, 1, 2, 3, 4];
  a.sortOrder(order, 1, 1);
  assert.deepEqual(order, [0, 1, 2, 3, 4]);
});

test('an opaque datasource id is shortened but still searchable by its full value', () => {
  const id = 'federated.0abcdefghij1234567890x';
  const a = app({columns: ['datasource'], data: [[id], ['Orders']]});
  assert.equal(a.friendlyDatasource(id), 'federated.0abcde\u2026890x');
  assert.equal(a.friendlyDatasource('Orders'), 'Orders');
  assert.match(a.searchText('datasource', id), /federated\.0abcdefghij1234567890x$/);
  a.state.sortCol = -1;
  assert.equal(a.rowHay([id], [0]).includes(id), true);
});

test('a caption replaces a datasource id in the display and in the search text', () => {
  const a = app({columns: ['datasource'], data: [['federated.abc']], dsLabels: {'federated.abc': 'Sales DB'}});
  assert.equal(a.shownText('datasource', 'federated.abc'), 'Sales DB');
  assert.equal(a.searchText('datasource', 'federated.abc'), 'Sales DB federated.abc');
  assert.equal(a.shownText('name', 'federated.abc'), 'federated.abc');
});

test('null and undefined show and search as empty text', () => {
  const a = app({columns: ['x'], data: []});
  assert.equal(a.shownText('x', null), '');
  assert.equal(a.shownText('x', undefined), '');
  assert.equal(a.searchText('x', null), '');
  assert.equal(a.shownText('x', 0), '0');
});

test('visibleSig lists the hidden columns in a stable order', () => {
  const a = app({columns: ['b', 'a', 'c'], data: []});
  assert.equal(a.visibleSig({hidden: new Set(['c', 'a'])}), 'a,c');
});

test('baseName and plural', () => {
  const a = app({columns: [], data: []});
  assert.equal(a.baseName('C:\\work\\book.twbx'), 'book.twbx');
  assert.equal(a.baseName('/tmp/a/b.twb'), 'b.twb');
  assert.equal(a.baseName('/'), '/');
  assert.equal(a.plural(1, 'row'), '1 row');
  assert.equal(a.plural(0, 'row'), '0 rows');
  assert.equal(a.plural(3, 'row'), '3 rows');
});
