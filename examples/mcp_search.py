"""Built-in MCP client; register discovered tools in the app's existing model loop."""

import asyncio
import os

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with httpx2.AsyncClient(
        headers={"Authorization": "Bearer " + os.environ["SEARCH_KEY"]}, trust_env=False
    ) as http:
        async with streamable_http_client(os.environ["SEARCH_MCP_URL"], http_client=http) as transport:
            async with ClientSession(transport[0], transport[1]) as session:
                await session.initialize()
                tools = await session.list_tools()
                print([tool.name for tool in tools.tools])
                snapshot = await session.call_tool("bensz_search_capabilities", {})
                print(snapshot)
                result = await session.call_tool(
                    "bensz_search", {"mode": "auto", "query": "colorectal cancer ctDNA"}
                )
                print(result)


if __name__ == "__main__":
    asyncio.run(main())
