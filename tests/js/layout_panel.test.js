'use strict';
// The layout panel's rules from app.js that need no DOM: which row is marked current, and when a filter closes the panel.
// Run: node --test tests/js/
const test = require('node:test');
const assert = require('node:assert/strict');
const {loadApp} = require('./load.js');

function app(state) {
  const calls = {closed: [], status: []};
  const globals = {
    state,
    closeLayoutPanel: (focus) => { calls.closed.push(focus); state.panelIdx = null; },
    setStatus: (msg) => calls.status.push(msg),
  };
  return Object.assign({calls}, loadApp(['currentIndex', 'panelFilterCheck'], [], globals));
}

test('the drawer row wins, then the panel row, and a vanished dashboard has no mark', () => {
  assert.equal(app({drawerIdx: 3, panelIdx: 5, panelGone: false}).currentIndex(), 3);
  assert.equal(app({drawerIdx: null, panelIdx: 5, panelGone: false}).currentIndex(), 5);
  assert.equal(app({drawerIdx: null, panelIdx: 0, panelGone: false}).currentIndex(), 0);
  assert.equal(app({drawerIdx: null, panelIdx: 5, panelGone: true}).currentIndex(), null);
  assert.equal(app({drawerIdx: null, panelIdx: null, panelGone: false}).currentIndex(), null);
});

test('a filter that hides the panel row closes the panel and says so; one that keeps it does nothing', () => {
  const kept = app({panelIdx: 4});
  kept.panelFilterCheck([2, 4, 6]);
  assert.deepEqual(kept.calls.closed, []);
  assert.deepEqual(kept.calls.status, []);
  const hidden = app({panelIdx: 4});
  hidden.panelFilterCheck([2, 6]);
  assert.deepEqual(hidden.calls.closed, [false]);
  assert.deepEqual(hidden.calls.status, ['The layout panel closed: its dashboard is filtered out.']);
  const none = app({panelIdx: null});
  none.panelFilterCheck([]);
  assert.deepEqual(none.calls.closed, []);
});
