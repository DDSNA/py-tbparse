'use strict';
// Loads the GUI's browser scripts without a browser, for the node:test files next to this one.
//
// app.js is a classic script that touches the DOM as soon as it runs, so it cannot simply be required.
// Instead pickFunctions() cuts the named top-level functions (and nothing else) out of its source text
// and evaluates them in a fresh vm context that holds stand-ins for the globals they read. The GUI
// source is not changed for this. A function that is renamed or no longer starts at column 0 makes the
// lookup throw, which is the signal to update the test.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const WEBUI = path.join(__dirname, '..', '..', 'py_tbparse', 'webui');

function source(name) {
  return fs.readFileSync(path.join(WEBUI, name), 'utf8');
}

// The text of `function <name>(...) {...}` at column 0: a one-liner, or up to the first line that is a lone "}".
function cutFunction(text, name) {
  const lines = text.split('\n');
  const start = lines.findIndex((line) => line.startsWith('function ' + name + '('));
  if (start < 0) throw new Error('function ' + name + ' not found at column 0');
  const open = (line) => (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
  if (open(lines[start]) === 0) return lines[start];
  let end = start + 1;
  while (end < lines.length && lines[end] !== '}') end += 1;
  if (end >= lines.length) throw new Error('end of function ' + name + ' not found');
  return lines.slice(start, end + 1).join('\n');
}

// The one-line `const NAME = ...;` declarations a function needs, copied as written.
function cutConst(text, name) {
  const line = text.split('\n').find((l) => l.startsWith('const ' + name + ' = '));
  if (!line) throw new Error('const ' + name + ' not found');
  return line;
}

// Returns {context, call}: the names of app.js evaluated in a sandbox. `globals` are the stand-ins
// (state, views, $ ...) the functions read; they stay reachable as context.state and so on.
function loadApp(functions, consts, globals) {
  const text = source('app.js');
  const code = consts.map((n) => cutConst(text, n)).concat(functions.map((n) => cutFunction(text, n))).join('\n');
  const context = vm.createContext(Object.assign({Intl, Array, Set, String, Math, Object}, globals));
  // const/let in a script are not properties of the context; hand the functions out explicitly.
  const exportList = functions.concat(consts).join(', ');
  const result = vm.runInContext('(function () {\n' + code + '\nreturn {' + exportList + '};\n})()', context);
  return result;
}

// rename.js is one IIFE that sets window.RenameReview, so it loads whole against a fake window.
function loadRename() {
  const window = {};
  vm.runInNewContext(source('rename.js'), {window, Set, Array, String, Object});
  return window.RenameReview;
}

module.exports = {loadApp, loadRename, cutFunction, source};
