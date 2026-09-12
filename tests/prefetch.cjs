const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const views = Object.fromEntries(['content','facts','projects','launches:today','hn:news:ai:rank','xrank:tweets:24h','extra'].map(k => [k,k+'.json']));
const counts = {};
views['facts:2026-09-01'] = 'facts-history.json';
let active = 0, peak = 0, fail = true;
const context = vm.createContext({URL, Map, Set, Promise, setTimeout,
  location: {origin: 'https://example.com'},
  document: {querySelector: () => ({textContent: JSON.stringify({meta:{},views})})},
  window: {},
  fetch: async (path, options) => {
    counts[path] = (counts[path] || 0) + 1;
    assert.equal(options.priority, 'low');
    peak = Math.max(peak, ++active);
    await new Promise(r => setTimeout(r, 10));
    --active;
    if (path === 'extra.json' && fail) throw Error('offline');
    return {ok:true,json:async () => ({items:[]})};
  }
});
vm.runInContext(fs.readFileSync('static/cloud-api.js','utf8'),context);
(async () => {
  assert.equal(Object.keys(counts).length, 0);
  const pending = context.window.prefetchCloudViews();
  await context.window.cloudAPI('/api/facts'); // Shares the in-flight preload.
  await pending;
  assert.equal(peak, 2);
  assert.equal(counts['facts.json'], 1);
  assert.equal(Object.keys(counts).length, 7);
  fail = false;
  await context.window.prefetchCloudViews();
  assert.equal(counts['extra.json'], 2);
  for (const key of Object.keys(views).filter(k=>k!=='extra' && !k.startsWith('facts:'))) assert.equal(counts[views[key]],1);
  assert.equal(counts['facts-history.json'], undefined, 'History must not preload');
  console.log('PASS: deferred start, two workers, shared requests, cache reuse, failure retry');
})().catch(e=>{console.error(e);process.exitCode=1;});
