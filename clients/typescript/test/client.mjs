import test from 'node:test';
import assert from 'node:assert/strict';
import { SearchClient, ToolSession, ModelAdapter, assembleStream, runToolLoop, dispatchStructured } from '../dist/index.js';
const fetcher = requests => async (url, options) => {
  requests.push({ url: String(url), options });
  return new Response(JSON.stringify(options.method === 'GET'
    ? { protocol_version: '1.0', registry_revision: 'rev', cache_ttl_seconds: 30, tools: [] }
    : { protocol_version: '1.0', status: 'success', estimated_cost_usd: .02, execution: [{ status: 'success' }], results: [] }),
    { status: 200, headers: { 'Content-Type': 'application/json' } });
};
const wire = (family, name, args) => {
  if (family === 'responses') return { output: [{ type: 'reasoning', encrypted_content: 'context' },
    { type: 'function_call', call_id: 'c', name, arguments: JSON.stringify(args) }] };
  if (family === 'anthropic') return { content: [{ type: 'thinking', thinking: 'context', signature: 'sig' },
    { type: 'tool_use', id: 'c', name, input: args }] };
  if (family === 'gemini') return { candidates: [{ content: { role: 'model', parts: [{ thoughtSignature: 'sig',
    functionCall: { id: 'c', name, args } }] } }] };
  const message = { role: 'assistant', content: '', reasoning_content: 'context', tool_calls: [{ id: 'c',
    type: 'function', function: { name, arguments: family === 'ollama' ? args : JSON.stringify(args) } }] };
  return family === 'ollama' ? { message } : { choices: [{ message }] };
};
const final = family => family === 'responses' ? { output: [] } : family === 'anthropic' ? { content: [] }
  : family === 'gemini' ? { candidates: [{ content: { role: 'model', parts: [{ text: 'answer' }] } }] }
  : family === 'ollama' ? { message: { content: 'answer' } } : { choices: [{ message: { content: 'answer' } }] };
for (const family of ['responses', 'chat', 'anthropic', 'gemini', 'ollama']) {
  test(`${family}: discover, plan, execute, answer`, async () => {
    const requests = [], payloads = [];
    const session = new ToolSession(new SearchClient('https://search.example', 'private-key', 20000, fetcher(requests)));
    const generate = async payload => {
      payloads.push(structuredClone(payload));
      if (payloads.length === 1) return wire(family, 'bensz_search_capabilities', {});
      if (payloads.length === 2) return wire(family, 'bensz_search', { mode: 'planned', registry_revision: 'rev',
        calls: [{ call_id: 'p', tool_id: 'fixture', query: '中文查询' }] });
      return final(family);
    };
    assert.deepEqual(await runToolLoop(generate, new ModelAdapter(family), session, 'find papers'), final(family));
    assert.equal(requests.length, 2);
    assert.equal(JSON.parse(requests[1].options.body).calls[0].query, '中文查询');
    assert.ok(!JSON.stringify(payloads).includes('private-key'));
    const retained = family === 'gemini' ? 'thoughtSignature' : family === 'anthropic' ? 'signature'
      : family === 'responses' ? 'encrypted_content' : 'reasoning_content';
    assert.ok(JSON.stringify(payloads[2]).includes(retained));
  });
}
test('parallel dispatch shares budget, malformed JSON executes nothing', async () => {
  const requests = [], client = new SearchClient('https://search.example', 'k', 20000, fetcher(requests));
  const session = new ToolSession(client, { budgetUsd: .02 });
  assert.equal((await session.dispatch('bensz_search', '{"query":')).error.code, 'invalid_plan');
  assert.equal(requests.length, 0);
  const result = await Promise.all(Array.from({ length: 3 }, () => session.dispatch('bensz_search', { query: 'q' })));
  assert.equal(result.filter(r => r.status === 'success').length, 1);
  assert.equal(requests.length, 1);
  assert.equal((await new ToolSession(client, { allowNetwork: false }).dispatch('bensz_search_capabilities', {})).error.code, 'network_forbidden');
});
test('capability caches isolate identities and do not expose credentials', async () => {
  const requests = [], mock = fetcher(requests);
  const a = new SearchClient('https://search.example', 'a', 20000, mock), b = new SearchClient('https://search.example', 'b', 20000, mock);
  await a.capabilities(); await a.capabilities(); await b.capabilities();
  assert.equal(requests.length, 2);
  assert.notEqual(requests[0].options.headers.Authorization, requests[1].options.headers.Authorization);
});
async function* stream(values) { yield* values; }
test('streamed parallel chat calls assemble completely', async () => {
  const result = await assembleStream('chat', stream([
    { choices: [{ delta: { tool_calls: [{ index: 0, id: 'c', function: { name: 'bensz_search', arguments: '{"query":' } }] } }] },
    { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: '"q"}' } }] }, finish_reason: 'tool_calls' }] }
  ]));
  assert.equal(JSON.parse(new ModelAdapter('chat').calls(result)[0].arguments).query, 'q');
  await assert.rejects(() => assembleStream('chat', stream([{ choices: [{ delta: { content: 'unfinished' } }] }])));
});
test('loop bounds and JSON fallback are observable', async () => {
  const session = new ToolSession(new SearchClient('https://search.example', 'k', 20000, fetcher([])));
  const result = await runToolLoop(async () => wire('chat', 'bensz_search_capabilities', {}), new ModelAdapter('chat'), session, 'q', { maxTurns: 2 });
  assert.equal(result.error.code, 'limit_reached');
  assert.equal((await dispatchStructured(session, '{"tool":"bensz_search","arguments":{"query":"q"}}')).integration_mode, 'structured_output');
});
test('unknown timeout is never automatically replayed', async () => {
  let calls = 0;
  const session = new ToolSession(new SearchClient('https://search.example', 'k', 20000, async () => { calls++; throw new Error('transport'); }));
  assert.equal((await session.autoContext('q')).search.error.code, 'outcome_unknown');
  assert.equal((await session.autoContext('q')).search.error.code, 'limit_reached');
  assert.equal(calls, 1);
});
for (const family of ['responses', 'anthropic', 'gemini', 'ollama']) {
  test(`${family}: complete and incomplete streams`, async () => {
    const response = wire(family, 'bensz_search_capabilities', {});
    const events = family === 'responses' ? [{ type: 'response.completed', response }]
      : family === 'anthropic' ? [{ type: 'content_block_start', index: 0, content_block: response.content[0] },
        { type: 'content_block_start', index: 1, content_block: response.content[1] }, { type: 'message_stop' }]
      : family === 'gemini' ? [{ ...response, candidates: [{ ...response.candidates[0], finishReason: 'STOP' }] }]
      : [{ ...response, done: true }];
    const result = await assembleStream(family, stream(events));
    assert.equal(new ModelAdapter(family).calls(result)[0].name, 'bensz_search_capabilities');
    await assert.rejects(() => assembleStream(family, stream([])));
  });
}
test('truncated streams never execute even valid partial JSON', async () => {
  await assert.rejects(() => assembleStream('chat', stream([
    { choices: [{ delta: {}, finish_reason: 'length' }] }
  ])));
});
