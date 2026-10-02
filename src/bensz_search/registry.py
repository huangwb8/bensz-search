"""Capability configuration is separate from LiteLLM credentials."""

from pathlib import Path

import yaml

from .models import ProviderCapabilities


class Registry:
    def __init__(self, providers: dict[str, ProviderCapabilities]):
        if not providers or "auto" in providers:
            raise ValueError("registry must contain providers and cannot redefine auto")
        self.providers = providers

    @classmethod
    def load(cls, path: str | Path):
        data = yaml.safe_load(Path(path).read_text())
        return cls(
            {name: ProviderCapabilities.model_validate(value) for name, value in data["providers"].items()}
        )

    def configured(self, search_tools: list[dict]) -> set[str]:
        return {
            tool["search_tool_name"]
            for tool in search_tools
            if tool.get("search_tool_name") in self.providers
            and tool.get("litellm_params", {}).get("search_provider")
            == self.providers[tool["search_tool_name"]].provider
        }
