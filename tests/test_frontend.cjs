const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const data = JSON.parse(fs.readFileSync('site/data/results.json', 'utf8'));
const plots = new Map();
const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id, {value: '', textContent: '', innerHTML: '', add(){}, addEventListener(){}, hasChildNodes(){return false}});
  return elements.get(id);
};
const Plotly = {newPlot(id, traces) {plots.set(id, traces); return Promise.resolve();}};
const context = {document: {getElementById: element, addEventListener(){}}, window: {Plotly}, Plotly, console, Set, Map, Date, Number, String, Math, Promise, Option: function(label,value){return {label,value};}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('site/app.js', 'utf8'), context);
vm.runInContext('d = inputData; charts();', Object.assign(context, {inputData: data}));
for (const id of ['statusChart','windowChart','delayChart','cumulativeChart','typeChart','hourChart']) {
  assert(plots.has(id), `${id} failed to initialize`);
}
assert.deepEqual([...plots.get('typeChart')[0].y], ['FFW','SVR']);
assert.equal(plots.get('typeChart')[0].x.length, 2);
assert(plots.get('typeChart')[0].x.every(Number.isFinite));
assert.equal(plots.get('hourChart')[0].y.length, 4);
element('typeFilter').value = 'SVR';
assert.equal(vm.runInContext('subset().length', context), data.warnings.filter(w=>w.type==='SVR').length);
element('typeFilter').value = 'FFW';
assert.equal(vm.runInContext('subset().length', context), data.warnings.filter(w=>w.type==='FFW').length);
element('typeFilter').value = '';
element('searchFilter').value = data.warnings[0].id;
assert.equal(vm.runInContext('subset().length', context), 1);
console.log('Frontend data preparation and filters passed');
