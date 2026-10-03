import { logicalTools, interactionRules, ToolSession, toolError, type Json } from './index.js';
export type Family = 'responses' | 'chat' | 'anthropic' | 'gemini' | 'ollama';
export interface ToolCall { id: string; name: string; arguments: unknown }
export function inlineSchema(schema: Json, strict = false, gemini = false): Json {
  const definitions = schema.$defs ?? {};
  function visit(node: any): any {
    if (Array.isArray(node)) return node.map(visit);
    if (!node || typeof node !== 'object') return node;
    if (node.$ref) return visit(definitions[node.$ref.split('/').at(-1)]);
    const result: Json = {};
    for (const [key, value] of Object.entries(node)) {
      if (['$defs', 'title', 'default'].includes(key) || (gemini && key === 'additionalProperties')) continue;
      result[key] = visit(value);
    }
    if (strict && result.type === 'object') {
      result.required = Object.keys(result.properties ?? {}); result.additionalProperties = false;
    }
    if (gemini && result.anyOf) {
      const choice = result.anyOf.find((x: Json) => x.type !== 'null');
      delete result.anyOf; if (choice) Object.assign(result, choice);
    }
    if (gemini && (typeof node.type === 'string' || node.anyOf)) {
      const allowed = new Set(['type', 'format', 'description', 'nullable', 'enum', 'items', 'maxItems', 'minItems',
        'properties', 'required', 'minimum', 'maximum', 'propertyOrdering']);
      for (const key of Object.keys(result)) if (!allowed.has(key)) delete result[key];
    }
    return result;
  }
  return visit(schema);
}
export class ModelAdapter {
  constructor(readonly family: Family) {}
  tools(): Json[] {
    if (this.family === 'responses') return logicalTools.map(t => ({ type: 'function', name: t.name,
      description: t.description, parameters: inlineSchema(t.input_schema, true), strict: true }));
    if (this.family === 'anthropic') return logicalTools.map(t => ({ name: t.name,
      description: t.description, input_schema: inlineSchema(t.input_schema) }));
    if (this.family === 'gemini') return [{ functionDeclarations: logicalTools.map(t => ({
      name: t.name, description: t.description, parameters: inlineSchema(t.input_schema, false, true) })) }];
    return logicalTools.map(t => ({ type: 'function', function: { name: t.name,
      description: t.description, parameters: inlineSchema(t.input_schema) } }));
  }
  request(history: Json[]): Json {
    if (this.family === 'responses') return { input: history, instructions: interactionRules, tools: this.tools() };
    if (this.family === 'anthropic') return { messages: history, system: interactionRules, tools: this.tools() };
    if (this.family === 'gemini') return { contents: history,
      systemInstruction: { parts: [{ text: interactionRules }] }, tools: this.tools() };
    return { messages: [{ role: 'system', content: interactionRules }, ...history], tools: this.tools() };
  }
  calls(response: Json): ToolCall[] {
    if (['incomplete', 'failed'].includes(response.status) || ['max_tokens', 'refusal'].includes(response.stop_reason)) throw new Error('Incomplete model response');
    if (this.family === 'responses') return (response.output ?? []).filter((o: Json) => o.type === 'function_call')
      .map((o: Json) => ({ id: o.call_id, name: o.name, arguments: o.arguments }));
    if (this.family === 'anthropic') return (response.content ?? []).filter((o: Json) => o.type === 'tool_use')
      .map((o: Json) => ({ id: o.id, name: o.name, arguments: o.input }));
    if (this.family === 'gemini') return response.candidates[0].content.parts.filter((o: Json) => o.functionCall)
      .map((o: Json, i: number) => ({ id: o.functionCall.id ?? String(i), name: o.functionCall.name, arguments: o.functionCall.args ?? {} }));
    const message = this.family === 'ollama' ? response.message : response.choices[0].message;
    return (message.tool_calls ?? []).map((o: Json, i: number) => ({
      id: o.id ?? String(i), name: o.function.name, arguments: o.function.arguments ?? {} }));
  }
  append(history: Json[], response: Json, calls: ToolCall[], results: Json[]) {
    const clone = structuredClone;
    if (this.family === 'responses') {
      history.push(...clone(response.output ?? []), ...calls.map((c, i) => ({
        type: 'function_call_output', call_id: c.id, output: JSON.stringify(results[i]) })));
    } else if (this.family === 'anthropic') {
      history.push({ role: 'assistant', content: clone(response.content ?? []) }, { role: 'user', content: calls.map((c, i) => ({
        type: 'tool_result', tool_use_id: c.id, content: JSON.stringify(results[i]), is_error: results[i].status === 'failed' })) });
    } else if (this.family === 'gemini') {
      history.push(clone(response.candidates[0].content), { role: 'user', parts: calls.map((c, i) => ({
        functionResponse: { name: c.name, id: c.id, response: results[i] } })) });
    } else {
      history.push(clone(this.family === 'ollama' ? response.message : response.choices[0].message));
      history.push(...calls.map((c, i) => ({ role: 'tool', content: JSON.stringify(results[i]),
        ...(this.family === 'ollama' ? { tool_name: c.name } : { tool_call_id: c.id }) })));
    }
  }
}
export async function assembleStream(family: Family, stream: AsyncIterable<Json>, signal?: AbortSignal): Promise<Json> {
  let completed: Json | undefined, finished = false;
  const message: Json = { role: 'assistant', content: '' }, calls: Record<number, Json> = {};
  const blocks: Record<number, Json> = {}, buffers: Record<number, string> = {}, parts: Json[] = [];
  for await (const event of stream) {
    if (signal?.aborted) throw signal.reason;
    if (family === 'responses') {
      if (event.type === 'response.completed') completed = event.response;
    } else if (family === 'chat' || family === 'ollama') {
      if (family === 'chat' && !event.choices?.length) continue;
      if (family === 'chat' && ['length', 'content_filter'].includes(event.choices[0].finish_reason)) throw new Error('Incomplete chat response');
      const delta = family === 'ollama' ? event.message ?? {} : event.choices[0].delta ?? {};
      finished ||= family === 'ollama' ? !!event.done : event.choices[0].finish_reason != null;
      for (const key of ['content', 'reasoning_content']) if (delta[key]) message[key] = (message[key] ?? '') + delta[key];
      for (const [i, tool] of (delta.tool_calls ?? []).entries()) {
        const target = calls[tool.index ?? i] ??= { type: 'function', function: { name: '', arguments: '' } };
        if (tool.id) target.id = tool.id;
        if (tool.function?.name) target.function.name = family === 'ollama' ? tool.function.name : target.function.name + tool.function.name;
        if (typeof tool.function?.arguments === 'object') target.function.arguments = tool.function.arguments;
        else if (tool.function?.arguments) target.function.arguments += tool.function.arguments;
      }
    } else if (family === 'anthropic') {
      const i = event.index ?? 0;
      if (event.type === 'content_block_start') blocks[i] = structuredClone(event.content_block);
      if (event.type === 'content_block_delta') {
        const delta = event.delta;
        if (delta.type === 'input_json_delta') buffers[i] = (buffers[i] ?? '') + delta.partial_json;
        else for (const key of ['text', 'thinking', 'signature']) if (key in delta) blocks[i][key] = (blocks[i][key] ?? '') + delta[key];
      }
      if (event.type === 'message_stop') finished = true;
      if (event.type === 'message_delta' && event.delta?.stop_reason === 'max_tokens') throw new Error('Incomplete Anthropic response');
    } else {
      for (const candidate of event.candidates ?? []) {
        if (candidate.finishReason && candidate.finishReason !== 'STOP') throw new Error('Incomplete Gemini response');
        parts.push(...(candidate.content?.parts ?? [])); finished ||= !!candidate.finishReason;
      }
    }
  }
  if (family === 'responses') { if (!completed) throw new Error('Incomplete Responses stream'); return completed; }
  if (!finished) throw new Error('Incomplete model stream');
  if (family === 'chat' || family === 'ollama') {
    message.tool_calls = Object.keys(calls).map(Number).sort((a, b) => a - b).map(i => calls[i]);
    return family === 'ollama' ? { message } : { choices: [{ message }] };
  }
  if (family === 'anthropic') {
    for (const i of Object.keys(buffers).map(Number)) blocks[i].input = JSON.parse(buffers[i]);
    return { content: Object.keys(blocks).map(Number).sort((a, b) => a - b).map(i => blocks[i]) };
  }
  return { candidates: [{ content: { role: 'model', parts } }] };
}
export async function runToolLoop(generate: (payload: Json, signal: AbortSignal) => Promise<Json | AsyncIterable<Json>>,
  adapter: ModelAdapter, session: ToolSession, prompt: string, options: { maxTurns?: number; signal?: AbortSignal } = {}): Promise<Json> {
  const history: Json[] = [adapter.family === 'gemini' ? { role: 'user', parts: [{ text: prompt }] } : { role: 'user', content: prompt }];
  const timeout = AbortSignal.timeout(Math.max(1, Math.floor(session.remainingMs())));
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  async function bounded<T>(job: Promise<T>): Promise<T> {
    return await new Promise<T>((resolve, reject) => {
      const abort = () => reject(signal.reason);
      signal.addEventListener('abort', abort, { once: true });
      if (signal.aborted) abort();
      job.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
    });
  }
  for (let turn = 0; turn < (options.maxTurns ?? 10); turn++) {
    if (signal.aborted) throw signal.reason;
    let response: Json, calls: ToolCall[];
    try {
      const raw = await bounded(generate(adapter.request(history), signal));
      response = Symbol.asyncIterator in raw ? await bounded(assembleStream(adapter.family, raw as AsyncIterable<Json>, signal)) : raw as Json;
      calls = adapter.calls(response);
    } catch (error) { if (signal.aborted) throw signal.reason; return toolError('invalid_model_output', 'Incomplete or unsupported tool messages'); }
    if (!calls.length) return response;
    if (calls.length > 10 || new Set(calls.map(c => c.id)).size !== calls.length) return toolError('invalid_model_output', 'Too many or duplicate tool calls');
    const results: Json[] = [];
    for (const call of calls) results.push(await session.dispatch(call.name, call.arguments, signal));
    adapter.append(history, response, calls, results);
  }
  return toolError('limit_reached', 'Model tool turn limit reached');
}
export async function dispatchStructured(session: ToolSession, actionJson: string, signal?: AbortSignal): Promise<Json> {
  try { const action = JSON.parse(actionJson);
    if (!action || Object.keys(action).sort().join(',') !== 'arguments,tool') throw new Error();
    return { integration_mode: 'structured_output', result: await session.dispatch(action.tool, action.arguments, signal) };
  } catch { return toolError('invalid_model_output', 'Expected JSON tool/arguments action'); }
}
export async function codexToolCall(session: ToolSession, method: string, params: Json, dynamicToolsEnabled = false): Promise<Json> {
  if (!dynamicToolsEnabled || method !== 'item/tool/call') return { success: false,
    contentItems: [{ type: 'inputText', text: 'unsupported_runtime' }] };
  const result = await session.dispatch(params.tool ?? '', params.arguments ?? {});
  return { success: result.status !== 'failed', contentItems: [{ type: 'inputText', text: JSON.stringify(result) }] };
}
