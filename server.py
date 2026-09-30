"""MCP server exposing Frankfurter exchange rates as tools.

Runs over Streamable HTTP (stateless) so it can sit behind a Kubernetes
Service / load balancer with multiple replicas.
"""

import logging
import os

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

FRANKFURTER_BASE_URL = os.getenv("FRANKFURTER_BASE_URL", "https://api.frankfurter.app")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "10"))
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("currency-mcp")

mcp = MCPServer(
    name="currency-exchange",
    instructions="Look up the latest foreign exchange rates (ECB reference rates via the Frankfurter API).",
    log_level=LOG_LEVEL,
)


async def _get(path: str, params: dict | None = None) -> dict:
    # frankfurter.app 301-redirects to frankfurter.dev/v1, so follow redirects.
    async with httpx.AsyncClient(base_url=FRANKFURTER_BASE_URL, timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("Frankfurter returned %s for %s: %s", e.response.status_code, path, e.response.text)
            raise ToolError(f"Frankfurter API error {e.response.status_code}: {e.response.text}") from e
        except httpx.HTTPError as e:
            logger.warning("Frankfurter request failed for %s: %s", path, e)
            raise ToolError(f"Could not reach Frankfurter API: {e}") from e


@mcp.tool()
async def get_latest_exchange_rate(from_currency: str = "USD", to_currency: str = "EUR", amount: float = 1.0) -> dict:
    """Get the latest exchange rate between two currencies.

    Args:
        from_currency: ISO 4217 base currency code, e.g. "USD".
        to_currency: ISO 4217 target currency code(s), e.g. "EUR" or "EUR,GBP,JPY".
        amount: Amount of the base currency to convert (default 1).

    Returns:
        {"amount": 1.0, "base": "USD", "date": "YYYY-MM-DD", "rates": {"EUR": 0.87}}
    """
    params = {"from": from_currency.strip().upper(), "to": to_currency.replace(" ", "").upper()}
    if amount != 1.0:
        params["amount"] = amount
    return await _get("/latest", params)


@mcp.tool()
async def list_currencies() -> dict:
    """List all currency codes supported by the exchange rate API, with their names."""
    return await _get("/currencies")


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    logger.info("Starting MCP server on %s:%s (path /mcp)", HOST, PORT)
    mcp.run(transport="streamable-http", host=HOST, port=PORT, stateless_http=True, json_response=True)
