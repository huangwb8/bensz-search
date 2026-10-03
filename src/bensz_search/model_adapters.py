"""SDK-independent vendor messages, streaming assembly and bounded tool loop."""

import copy
import json
from dataclasses import dataclass

from .client import tool_error
from .tools import INTERACTION_RULES, logical_tools


def object_dict(value):
    return (
        value.model_dump(mode="json", by_alias=True, exclude_none=True)
        if hasattr(value, "model_dump")
        else value
    )


def inline_schema(schema, *, strict=False, gemini=False):
    definitions = schema.get("$defs", {})

    def visit(node):
        if isinstance(node, list):
            return [visit(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return visit(definitions[node["$ref"].rsplit("/", 1)[-1]])
        result = {
            k: visit(v)
            for k, v in node.items()
            if k not in {"$defs", "title", "default"} and not (gemini and k == "additionalProperties")
        }
        if strict and result.get("type") == "object":
            result["required"] = list(result.get("properties", {}))
            result["additionalProperties"] = False
        if gemini and "anyOf" in result:
            choices = [n for n in result.pop("anyOf") if n.get("type") != "null"]
            if choices:
                result.update(choices[0])
        if gemini and (isinstance(node.get("type"), str) or "anyOf" in node):
            allowed = {
                "type",
                "format",
                "description",
                "nullable",
                "enum",
                "items",
                "maxItems",
                "minItems",
                "properties",
                "required",
                "minimum",
                "maximum",
                "propertyOrdering",
            }
            result = {k: v for k, v in result.items() if k in allowed}
        return result

    return visit(schema)


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: object


class ModelAdapter:
    """Families describe wire format, not claims about individual model versions."""

    def __init__(self, family):
        if family not in {"responses", "chat", "anthropic", "gemini", "ollama"}:
            raise ValueError("unsupported model message family")
        self.family = family

    def tools(self):
        tools = logical_tools()
        if self.family == "responses":
            return [
                {
                    "type": "function",
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": inline_schema(t["input_schema"], strict=True),
                    "strict": True,
                }
                for t in tools
            ]
        if self.family in {"chat", "ollama"}:
            return [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": inline_schema(t["input_schema"]),
                    },
                }
                for t in tools
            ]
        if self.family == "anthropic":
            return [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": inline_schema(t["input_schema"]),
                }
                for t in tools
            ]
        return [
            {
                "functionDeclarations": [
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": inline_schema(t["input_schema"], gemini=True),
                    }
                    for t in tools
                ]
            }
        ]

    def initial(self, prompt):
        if self.family == "gemini":
            return [{"role": "user", "parts": [{"text": prompt}]}]
        return [{"role": "user", "content": prompt}]

    def request(self, history):
        if self.family == "responses":
            return {"input": history, "instructions": INTERACTION_RULES, "tools": self.tools()}
        if self.family == "anthropic":
            return {"messages": history, "system": INTERACTION_RULES, "tools": self.tools()}
        if self.family == "gemini":
            return {
                "contents": history,
                "systemInstruction": {"parts": [{"text": INTERACTION_RULES}]},
                "tools": self.tools(),
            }
        return {
            "messages": [{"role": "system", "content": INTERACTION_RULES}, *history],
            "tools": self.tools(),
        }

    def calls(self, response):
        family = self.family
        if response.get("status") in {"incomplete", "failed"} or response.get("stop_reason") in {
            "max_tokens",
            "refusal",
        }:
            raise ValueError("incomplete model response")
        if family == "responses":
            return [
                ToolCall(o["call_id"], o["name"], o["arguments"])
                for o in response.get("output", [])
                if o.get("type") == "function_call"
            ]
        if family in {"chat", "ollama"}:
            message = response["message"] if family == "ollama" else response["choices"][0]["message"]
            return [
                ToolCall(t.get("id", str(i)), t["function"]["name"], t["function"].get("arguments", {}))
                for i, t in enumerate(message.get("tool_calls", []))
            ]
        if family == "anthropic":
            return [
                ToolCall(b["id"], b["name"], b["input"])
                for b in response.get("content", [])
                if b.get("type") == "tool_use"
            ]
        return [
            ToolCall(
                p["functionCall"].get("id", str(i)),
                p["functionCall"]["name"],
                p["functionCall"].get("args", {}),
            )
            for i, p in enumerate(response["candidates"][0]["content"].get("parts", []))
            if "functionCall" in p
        ]

    def append(self, history, response, calls, results):
        # Retain full assistant blocks: reasoning items, text order, thought signatures.
        if self.family == "responses":
            history.extend(copy.deepcopy(response.get("output", [])))
            history.extend(
                {"type": "function_call_output", "call_id": c.call_id, "output": json.dumps(r)}
                for c, r in zip(calls, results, strict=True)
            )
        elif self.family == "anthropic":
            history.append({"role": "assistant", "content": copy.deepcopy(response.get("content", []))})
            history.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": c.call_id,
                            "content": json.dumps(r),
                            "is_error": r.get("status") == "failed",
                        }
                        for c, r in zip(calls, results, strict=True)
                    ],
                }
            )
        elif self.family == "gemini":
            history.append(copy.deepcopy(response["candidates"][0]["content"]))
            history.append(
                {
                    "role": "user",
                    "parts": [
                        {"functionResponse": {"name": c.name, "id": c.call_id, "response": r}}
                        for c, r in zip(calls, results, strict=True)
                    ],
                }
            )
        else:
            history.append(
                copy.deepcopy(
                    response["message"] if self.family == "ollama" else response["choices"][0]["message"]
                )
            )
            for c, r in zip(calls, results, strict=True):
                history.append(
                    {
                        "role": "tool",
                        "content": json.dumps(r),
                        **({"tool_name": c.name} if self.family == "ollama" else {"tool_call_id": c.call_id}),
                    }
                )


async def assemble_stream(family, stream):
    """Execute nothing until the full stream arrives; reject unfinished streams."""
    if family == "responses":
        completed = None
        async for raw in stream:
            event = object_dict(raw)
            if event.get("type") == "response.completed":
                completed = event["response"]
        if completed is None:
            raise ValueError("incomplete Responses stream")
        return completed
    if family in {"chat", "ollama"}:
        message, calls, finished = {"role": "assistant", "content": ""}, {}, False
        async for raw in stream:
            event = object_dict(raw)
            if family == "ollama":
                delta = event.get("message", {})
                finished |= event.get("done", False)
            else:
                if not event.get("choices"):
                    continue
                choice = event["choices"][0]
                if choice.get("finish_reason") in {"length", "content_filter"}:
                    raise ValueError("incomplete chat response")
                delta = choice.get("delta", {})
                finished |= choice.get("finish_reason") is not None
            for key in ("content", "reasoning_content"):
                if delta.get(key):
                    message[key] = message.get(key, "") + delta[key]
            for i, t in enumerate(delta.get("tool_calls", [])):
                index = t.get("index", i)
                target = calls.setdefault(
                    index, {"type": "function", "function": {"name": "", "arguments": ""}}
                )
                if t.get("id"):
                    target["id"] = t["id"]
                function = t.get("function", {})
                if function.get("name"):
                    if family == "ollama":
                        target["function"]["name"] = function["name"]
                    else:
                        target["function"]["name"] += function["name"]
                args = function.get("arguments")
                if isinstance(args, dict):
                    target["function"]["arguments"] = args
                elif args:
                    target["function"]["arguments"] += args
        if not finished:
            raise ValueError("incomplete chat stream")
        message["tool_calls"] = [calls[k] for k in sorted(calls)]
        return {"message": message} if family == "ollama" else {"choices": [{"message": message}]}
    if family == "anthropic":
        blocks, buffers, finished = {}, {}, False
        async for raw in stream:
            event = object_dict(raw)
            index = event.get("index", 0)
            if event.get("type") == "content_block_start":
                blocks[index] = copy.deepcopy(event["content_block"])
            elif event.get("type") == "content_block_delta":
                delta = event["delta"]
                if delta.get("type") == "input_json_delta":
                    buffers[index] = buffers.get(index, "") + delta["partial_json"]
                else:
                    for key in ("text", "thinking", "signature"):
                        if key in delta:
                            blocks[index][key] = blocks[index].get(key, "") + delta[key]
            elif event.get("type") == "message_stop":
                finished = True
            elif (
                event.get("type") == "message_delta"
                and event.get("delta", {}).get("stop_reason") == "max_tokens"
            ):
                raise ValueError("incomplete Anthropic response")
        if not finished:
            raise ValueError("incomplete Anthropic stream")
        for index, buffer in buffers.items():
            blocks[index]["input"] = json.loads(buffer)
        return {"content": [blocks[i] for i in sorted(blocks)]}
    parts, finished = [], False
    async for raw in stream:
        event = object_dict(raw)
        for candidate in event.get("candidates", []):
            if candidate.get("finishReason") and candidate["finishReason"] != "STOP":
                raise ValueError("incomplete Gemini response")
            parts.extend(candidate.get("content", {}).get("parts", []))
            finished |= bool(candidate.get("finishReason"))
    if not finished:
        raise ValueError("incomplete Gemini stream")
    return {"candidates": [{"content": {"role": "model", "parts": parts}}]}


async def run_tool_loop(generate, adapter, session, prompt, *, max_turns=10):
    """generate(payload) returns vendor dict/async stream using the app's model account."""
    import asyncio
    import time

    history = adapter.initial(prompt)
    for _ in range(max_turns):
        remaining = session.deadline - time.monotonic()
        if remaining <= 0:
            return tool_error("limit_reached", "Model task deadline reached")
        try:
            response = await asyncio.wait_for(generate(adapter.request(history)), remaining)
            if hasattr(response, "__aiter__"):
                response = await asyncio.wait_for(
                    assemble_stream(adapter.family, response), max(0.001, session.deadline - time.monotonic())
                )
            response = object_dict(response)
            if not isinstance(response, dict):
                raise ValueError("model response must be an object")
            calls = adapter.calls(response)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            return tool_error("invalid_model_output", "Incomplete or unsupported model tool messages")
        except TimeoutError:
            return tool_error("limit_reached", "Model task deadline reached")
        if not calls:
            return response
        if len(calls) > 10 or len({c.call_id for c in calls}) != len(calls):
            return tool_error("invalid_model_output", "Too many or duplicate tool calls")
        results = [await session.dispatch(c.name, c.arguments) for c in calls]
        adapter.append(history, response, calls, results)
    return tool_error("limit_reached", "Model tool turn limit reached")


async def dispatch_structured(session, action_json):
    """Fallback for JSON-only models; exact actions, no arbitrary code or URLs."""
    try:
        action = json.loads(action_json)
        if not isinstance(action, dict) or set(action) != {"tool", "arguments"}:
            raise ValueError("invalid action")
        return {
            "integration_mode": "structured_output",
            "result": await session.dispatch(action["tool"], action["arguments"]),
        }
    except (ValueError, TypeError, KeyError):
        return tool_error("invalid_model_output", "Expected a JSON tool/arguments action")


class CodexRuntimeAdapter:
    """Experimental App Server dynamic tool handler; host owns its existing loop."""

    @staticmethod
    def declarations():
        return [
            {"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"]}
            for t in logical_tools()
        ]

    @staticmethod
    async def handle(session, method, params, *, dynamic_tools_enabled=False):
        if not dynamic_tools_enabled or method != "item/tool/call":
            return {"success": False, "contentItems": [{"type": "inputText", "text": "unsupported_runtime"}]}
        result = await session.dispatch(params.get("tool", ""), params.get("arguments", {}))
        return {
            "success": result.get("status") != "failed",
            "contentItems": [{"type": "inputText", "text": json.dumps(result)}],
        }
