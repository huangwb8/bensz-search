"""Optional HTTP model transport using the application's existing account."""

import json

import httpx


class HttpModel:
    def __init__(self, url, key, model, family, *, stream=False, timeout=60, transport=None):
        self.family, self.model, self.stream = family, model, stream
        headers = (
            {"x-api-key": key, "anthropic-version": "2023-06-01"}
            if family == "anthropic"
            else {"x-goog-api-key": key}
            if family == "gemini"
            else {"Authorization": "Bearer " + key}
        )
        self.http = httpx.AsyncClient(
            base_url=url.rstrip("/") + "/", headers=headers, timeout=timeout, transport=transport
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.http.aclose()

    def request(self, payload):
        if self.family == "gemini":
            method = "streamGenerateContent?alt=sse" if self.stream else "generateContent"
            return f"models/{self.model}:{method}", payload
        paths = {
            "responses": "responses",
            "chat": "chat/completions",
            "anthropic": "messages",
            "ollama": "api/chat",
        }
        body = {**payload, "model": self.model, "stream": self.stream}
        if self.family == "anthropic":
            body["max_tokens"] = 4096
        if self.family == "responses":
            # Keep encrypted reasoning context across stateless multi-turn calls.
            body.update(store=False, include=["reasoning.encrypted_content"])
        return paths[self.family], body

    async def generate(self, payload):
        path, body = self.request(payload)
        if not self.stream:
            response = await self.http.post(path, json=body)
            response.raise_for_status()
            return response.json()

        async def events():
            async with self.http.stream("POST", path, json=body) as response:
                response.raise_for_status()
                data_lines = []
                async for line in response.aiter_lines():
                    if self.family == "ollama":
                        if line.strip():
                            yield json.loads(line)
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    elif not line and data_lines:
                        data = "\n".join(data_lines)
                        data_lines.clear()
                        if data != "[DONE]":
                            yield json.loads(data)
                if data_lines and "\n".join(data_lines) != "[DONE]":
                    yield json.loads("\n".join(data_lines))

        return events()
