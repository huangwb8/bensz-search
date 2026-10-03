"""An application embeds this loop; it keeps its existing model account."""

import asyncio
import os

from bensz_search.client import SearchClient, ToolSession
from bensz_search.model_adapters import ModelAdapter, run_tool_loop
from bensz_search.model_transport import HttpModel


async def main():
    family = os.environ.get("EXISTING_MODEL_FAMILY", "chat")
    async with SearchClient(os.environ["SEARCH_URL"], os.environ["SEARCH_KEY"]) as search:
        async with HttpModel(
            os.environ["EXISTING_MODEL_URL"],
            os.environ["EXISTING_MODEL_KEY"],
            os.environ["EXISTING_MODEL_ID"],
            family,
        ) as model:
            result = await run_tool_loop(
                model.generate,
                ModelAdapter(family),
                ToolSession(search),
                "Find recent evidence about colorectal cancer ctDNA",
            )
            print(result)


if __name__ == "__main__":
    asyncio.run(main())
