import { Ajv } from 'ajv';
import definitions from './tools.json' with { type: 'json' };
export { ModelAdapter, assembleStream, runToolLoop, dispatchStructured, codexToolCall } from './models.js';
export type Json = Record<string, any>;
export const logicalTools = definitions.tools;
export const interactionRules = definitions.instructions;
const validator = new Ajv({ strict: false }).compile(logicalTools[1].input_schema);
function validRequest(data: Json): boolean {
  if (!validator(data)) return false;
  const mode = data.mode ?? 'auto';
  if (mode === 'auto') return !!data.query?.trim() && !data.calls?.length;
  if (!data.calls?.length || data.query != null) return false;
  if (data.options && Object.entries(data.options).some(([k, v]) =>
    k === 'dialect' ? v !== 'keywords' : k === 'search_domain_filter' ? (v as any[]).length > 0 : v != null)) return false;
  const all = data.calls.flatMap((c: Json) => [c, ...(c.fallbacks ?? [])]);
  return all.length <= 10 && new Set(all.map((c: Json) => c.call_id)).size === all.length
    && all.every((c: Json) => c.query.trim());
}
export const toolError = (code: string, message: string): Json => ({ status: 'failed', error: { code, message } });

export class SearchClient {
  private snapshot?: Json;
  private expires = 0;
  constructor(private url: string, private key: string, private timeoutMs = 20000,
              private fetcher: typeof fetch = fetch) {}
  invalidate() { this.snapshot = undefined; this.expires = 0; }
  private async request(path: string, data?: Json, signal?: AbortSignal): Promise<Json> {
    const response = await this.fetcher(new URL(path, this.url.replace(/\/$/, '') + '/'), {
      method: data ? 'POST' : 'GET', headers: {
        Authorization: `Bearer ${this.key}`, ...(data ? { 'Content-Type': 'application/json' } : {})
      }, body: data ? JSON.stringify(data) : undefined,
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(this.timeoutMs)]) : AbortSignal.timeout(this.timeoutMs)
    });
    const result = await response.json() as Json;
    if (!response.ok && !result.protocol_version) throw new Error('Search HTTP transport failed');
    return result;
  }
  async capabilities(signal?: AbortSignal): Promise<Json> {
    if (this.snapshot && performance.now() < this.expires) return structuredClone(this.snapshot);
    const data = await this.request('bensz-search/v1/capabilities', undefined, signal);
    if (String(data.protocol_version).split('.')[0] !== '1') throw new Error('Unsupported protocol version');
    this.snapshot = data;
    this.expires = performance.now() + Math.min(30, Math.max(0, data.cache_ttl_seconds)) * 1000;
    return structuredClone(data);
  }
  async search(data: Json, signal?: AbortSignal): Promise<Json> {
    if (!validRequest(data)) return toolError('invalid_plan', 'Invalid complete JSON search request');
    const result = await this.request('bensz-search/v1/search', data, signal);
    if (result.error?.code === 'stale_capabilities') this.invalidate();
    return result;
  }
  async legacyAuto(query: string, maxResults = 10, signal?: AbortSignal): Promise<Json> {
    return { integration_mode: 'legacy_auto', legacy_response: await this.request('search', { query, max_results: maxResults }, signal),
      cost_basis: 'Legacy response may not report estimated cost' };
  }
}

export class ToolSession {
  private chain: Promise<unknown> = Promise.resolve();
  private revision?: string;
  private spent = 0;
  private searches = 0;
  private corrections = 0;
  readonly deadline: number;
  constructor(readonly client: SearchClient, readonly settings: {
    budgetUsd?: number; maxSearches?: number; maxCorrections?: number; durationMs?: number; allowNetwork?: boolean
  } = {}) { this.deadline = performance.now() + (settings.durationMs ?? 60000); }
  remainingMs() { return this.deadline - performance.now(); }
  dispatch(name: string, args: unknown, signal?: AbortSignal): Promise<Json> {
    const job = this.chain.then(() => this.execute(name, args, signal));
    this.chain = job.catch(() => undefined);
    return job;
  }
  private async execute(name: string, args: unknown, signal?: AbortSignal): Promise<Json> {
    if (signal?.aborted) throw signal.reason;
    if (this.settings.allowNetwork === false) return toolError('network_forbidden', 'Network disabled by host');
    if (this.remainingMs() <= 0) return toolError('limit_reached', 'Task deadline reached');
    const timeout = AbortSignal.timeout(Math.max(1, Math.floor(this.remainingMs())));
    const bounded = signal ? AbortSignal.any([signal, timeout]) : timeout;
    let data: Json;
    try {
      data = typeof args === 'string' ? JSON.parse(args) : args;
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error();
    } catch { this.corrections++; return toolError('invalid_plan', 'Complete JSON object arguments required'); }
    try {
      if (name === 'bensz_search_capabilities') {
        if (Object.keys(data).length) return toolError('invalid_plan', 'Capabilities accepts no arguments');
        const snapshot = await this.client.capabilities(bounded);
        this.revision = snapshot.registry_revision;
        return snapshot;
      }
      if (name !== 'bensz_search') return toolError('unknown_tool', 'Unknown logical tool');
      if (this.corrections > (this.settings.maxCorrections ?? 2)) return toolError('limit_reached', 'Correction limit reached');
      if (!validRequest(data)) {
        this.corrections++; return toolError('invalid_plan', 'Invalid complete search request');
      }
      if (data.mode === 'planned' && !this.revision) return toolError('capabilities_required', 'Discover capabilities first');
      if (data.mode === 'planned' && data.registry_revision !== this.revision) return toolError('stale_capabilities', 'Use delivered revision');
      const budget = this.settings.budgetUsd ?? 0.06;
      if (this.searches >= (this.settings.maxSearches ?? 3) || this.spent >= budget || this.remainingMs() < 100) {
        return toolError('limit_reached', 'Task search, time or budget limit reached');
      }
      data = structuredClone(data);
      data.constraints = { ...data.constraints,
        cost_budget_usd: Math.min(data.constraints?.cost_budget_usd ?? 0.02, budget - this.spent),
        latency_budget_ms: Math.min(data.constraints?.latency_budget_ms ?? 8000, Math.floor(this.remainingMs()), 60000)
      };
      const result = await this.client.search(data, bounded);
      if (result.error?.code === 'stale_capabilities') { this.revision = undefined; this.corrections++; }
      else if (result.status === 'failed' && !result.execution?.length) this.corrections++;
      else if (!data.dry_run) { this.searches++; this.spent += result.estimated_cost_usd ?? data.constraints.cost_budget_usd; }
      return result;
    } catch (error) {
      this.spent = this.settings.budgetUsd ?? 0.06;
      if (signal?.aborted) throw signal.reason;
      return toolError('outcome_unknown', 'Transport failed or timed out; do not replay');
    }
  }
  async autoContext(query: string, signal?: AbortSignal): Promise<Json> {
    return { integration_mode: 'host_auto', search: await this.dispatch('bensz_search', { mode: 'auto', query }, signal) };
  }
}
