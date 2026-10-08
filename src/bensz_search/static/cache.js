// Session memory only. Each subscriber owns its interest, never the request itself.
export class ResourceCache {
  constructor(limit = 64) { this.limit = limit; this.entries = new Map(); }
  peek(key) { return this.entries.get(key); }
  clear() { for (const entry of this.entries.values()) entry.controller?.abort(); this.entries.clear(); }
  invalidate(predicate = () => true) {
    for (const [key, entry] of this.entries) if (predicate(key)) {
      entry.controller?.abort(); this.entries.delete(key);
    }
  }
  subscribe(key, ttl, loader, subscriber, force = false) {
    let entry = this.entries.get(key);
    if (!entry) { entry = { data: undefined, updated: 0, listeners: new Set(), promise: null }; this.entries.set(key, entry); }
    // Touch for bounded LRU eviction. Active entries are retained until released.
    this.entries.delete(key); this.entries.set(key, entry);
    entry.listeners.add(subscriber);
    if (entry.data !== undefined) subscriber(entry.data, null, entry.updated);
    if (!entry.promise && (force || Date.now() - entry.updated >= ttl || entry.data === undefined)) {
      const controller = entry.controller = new AbortController();
      entry.promise = Promise.resolve().then(() => loader(controller.signal)).then(data => {
        if (controller.signal.aborted || this.entries.get(key) !== entry) return;
        entry.data = data; entry.updated = Date.now();
        for (const listener of entry.listeners) listener(data, null, entry.updated);
      }).catch(error => {
        if (!controller.signal.aborted && this.entries.get(key) === entry)
          for (const listener of entry.listeners) listener(entry.data, error, entry.updated);
      }).finally(() => { if (entry.controller === controller) { entry.promise = null; entry.controller = null; } this.trim(); });
    }
    this.trim();
    return { promise: entry.promise || Promise.resolve(), release: () => {
      entry.listeners.delete(subscriber);
      queueMicrotask(() => {
        if (!entry.listeners.size && entry.promise) {
          entry.controller?.abort();
          if (this.entries.get(key) === entry) this.entries.delete(key);
        }
        this.trim();
      });
    }};
  }
  trim() {
    for (const [key, entry] of this.entries) {
      if (this.entries.size <= this.limit) break;
      if (!entry.listeners.size && !entry.promise) this.entries.delete(key);
    }
  }
}
