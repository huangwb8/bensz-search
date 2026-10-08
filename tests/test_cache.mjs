import assert from 'node:assert/strict';
import { ResourceCache } from '../src/bensz_search/static/cache.js';
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const cache = new ResourceCache(2);
let requests = 0, complete, aborts = 0;
const loader = signal => { requests++; signal.addEventListener('abort', () => aborts++); return new Promise(resolve => { complete = resolve; }); };
const first = [], second = [];
const a = cache.subscribe('identity:resource', 30000, loader, value => first.push(value));
const b = cache.subscribe('identity:resource', 30000, loader, value => second.push(value));
await tick(); assert.equal(requests, 1);
a.release(); await tick(); assert.equal(aborts, 0);
complete({ value: 1 }); await b.promise;
assert.deepEqual(first, []); assert.deepEqual(second, [{ value: 1 }]);
b.release(); await tick();
const warm = []; const c = cache.subscribe('identity:resource', 30000, loader, value => warm.push(value));
assert.deepEqual(warm, [{ value: 1 }]); assert.equal(requests, 1); c.release();
cache.invalidate(key => key === 'identity:resource');
const d = cache.subscribe('identity:resource', 0, loader, () => {});
await tick(); d.release(); await tick(); assert.equal(aborts, 1); assert.equal(cache.peek('identity:resource'), undefined);
// An aborted old response never overwrites a newly acquired resource.
const oldComplete = complete;
const e = cache.subscribe('identity:resource', 30000, loader, () => {});
await tick(); oldComplete({ value: 'old' }); await d.promise;
complete({ value: 'new' }); await e.promise;
assert.deepEqual(cache.peek('identity:resource').data, { value: 'new' });
e.release();
for (const name of ['one', 'two', 'three', 'four']) {
  const item = cache.subscribe(name, 30000, () => Promise.resolve(name), () => {});
  await item.promise; item.release(); await tick();
}
assert.ok(cache.entries.size <= 2);
cache.clear(); assert.equal(cache.entries.size, 0);
console.log('cache: deduplication, shared cancellation, stale response isolation, invalidation and bounds passed');
