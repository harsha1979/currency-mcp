"""Smoke-test an MCP server with the official MCP Python client.

Usage: python scripts/test_client.py [MCP_URL]
"""

import asyncio
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/mcp"


def text(result) -> str:
    return "\n".join(c.text for c in result.content if c.type == "text")


async def main() -> None:
    print(f"Connecting to {URL}")
    async with streamable_http_client(URL) as (read, write, *_):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"Server: {init.server_info.name}, protocol {init.protocol_version}")

            tools = await session.list_tools()
            print("Tools:", ", ".join(t.name for t in tools.tools))

            r = await session.call_tool("get_latest_exchange_rate", {"from_currency": "USD", "to_currency": "EUR"})
            print(f"\nget_latest_exchange_rate(USD->EUR) isError={r.is_error}\n{text(r)}")

            r = await session.call_tool("get_latest_exchange_rate", {"from_currency": "USD", "to_currency": "EUR,GBP,JPY", "amount": 100})
            print(f"\nget_latest_exchange_rate(100 USD->EUR,GBP,JPY) isError={r.is_error}\n{text(r)}")

            r = await session.call_tool("list_currencies", {})
            print(f"\nlist_currencies isError={r.is_error}: {len(text(r).splitlines())} lines returned")


asyncio.run(main())
