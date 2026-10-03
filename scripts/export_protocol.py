"""Export public OpenAPI/schema/tool artifacts from the authoritative Python models."""

import json
from pathlib import Path

from fastapi import FastAPI

from bensz_search.protocol_http import router
from bensz_search.protocol_models import CapabilitySnapshot, ProtocolSearch, SearchEnvelope
from bensz_search.tools import INTERACTION_RULES, logical_tools

root = Path(__file__).resolve().parents[1]
output = root / "docs/smart-search-router/protocol/v1"
output.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="bensz-search protocol", version="1.0")
app.include_router(router)
for name, value in {
    "openapi.json": app.openapi(),
    "search.schema.json": ProtocolSearch.model_json_schema(),
    "capabilities.schema.json": CapabilitySnapshot.model_json_schema(),
    "result.schema.json": SearchEnvelope.model_json_schema(),
    "tools.json": {"interaction_version": "1.0", "instructions": INTERACTION_RULES, "tools": logical_tools()},
}.items():
    (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
typescript = root / "clients/typescript/src"
typescript.mkdir(parents=True, exist_ok=True)
(typescript / "tools.json").write_text((output / "tools.json").read_text())
