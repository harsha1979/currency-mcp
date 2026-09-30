# currency-mcp

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that gives AI assistants and agents live foreign-exchange rates. It wraps the public [Frankfurter API](https://frankfurter.dev), which serves the European Central Bank (ECB) reference rates, and exposes it as MCP tools.

It uses the **Streamable HTTP** transport in **stateless** mode, so you can run several replicas behind a load balancer or Kubernetes Service with no sticky sessions.

## Use case

An LLM doesn't know today's exchange rates, and asking it to guess produces made-up numbers. This server lets an MCP client (Claude Desktop, Claude Code, MCP Inspector, an agent framework, or an API gateway that proxies MCP) answer questions such as:

- "What is 1 USD in EUR today?"
- "Convert 250 GBP to JPY, INR and AUD."
- "Which currencies can you convert between?"

The model calls a tool, the server fetches the current ECB rate from Frankfurter, and the model answers with a real figure and its date.

It also works as a small reference implementation of **turning an existing REST API into an MCP server**: two thin tools over two HTTP endpoints, a health probe, a container image and a Kubernetes manifest.

## How it works

```
┌──────────────┐   MCP (JSON-RPC over HTTP)   ┌─────────────────┐    HTTPS GET     ┌────────────────────┐
│  MCP client  │ ───────────────────────────▶ │  currency-mcp   │ ───────────────▶ │  Frankfurter API   │
│ (LLM / agent)│ ◀─────────────────────────── │  POST /mcp      │ ◀─────────────── │  (ECB ref. rates)  │
└──────────────┘       tool result (JSON)     └─────────────────┘      JSON        └────────────────────┘
```

1. **Connect:** the client sends `initialize` to `POST /mcp` and gets back the server name (`currency-exchange`) and its instructions.
2. **Discover:** the client calls `tools/list` and receives the two tools with their argument schemas. The LLM uses these to decide when to call a tool.
3. **Call:** when a user asks about rates, the LLM issues `tools/call`, for example `get_latest_exchange_rate(from_currency="USD", to_currency="EUR", amount=100)`.
4. **Fetch:** the server normalizes the arguments (trims whitespace, uppercases codes) and calls Frankfurter: `GET /latest?from=USD&to=EUR&amount=100`. Redirects are followed, because `api.frankfurter.app` redirects to `api.frankfurter.dev/v1`.
5. **Respond:** the Frankfurter JSON is returned as the tool result. If Frankfurter returns an error, such as an unknown currency code, or can't be reached, the server returns an MCP tool error (`isError: true`) with the reason, so the LLM can recover instead of failing.

Because the server is stateless (no MCP session is stored between requests), any replica can handle any request.

> ECB reference rates are published once per working day, around 16:00 CET. "Latest" means the most recent published rate, not a real-time market quote, and the response's `date` field shows which day it is from.

## Tools

### `get_latest_exchange_rate`

Get the latest exchange rate from one currency to one or more others, optionally converting an amount.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `from_currency` | string | `USD` | ISO 4217 base currency code, e.g. `USD` |
| `to_currency` | string | `EUR` | Target currency code, or several comma-separated: `EUR,GBP,JPY` |
| `amount` | number | `1` | Amount of the base currency to convert |

Example result for `amount=100`, `from_currency=USD`, `to_currency=EUR,GBP,JPY`:

```json
{
  "amount": 100.0,
  "base": "USD",
  "date": "2026-09-30",
  "rates": { "EUR": 88.07, "GBP": 75.262, "JPY": 15700 }
}
```

With an `amount`, each value in `rates` is the converted amount, not the unit rate.

### `list_currencies`

List every currency code the API supports, with its name. No arguments.

```json
{ "AUD": "Australian Dollar", "BRL": "Brazilian Real", "CAD": "Canadian Dollar", "...": "..." }
```

## HTTP endpoints

| Method & path | Purpose |
|---------------|---------|
| `POST /mcp` | MCP endpoint (Streamable HTTP, JSON responses) |
| `GET /health` | Liveness/readiness probe, returns `{"status":"ok"}` |

## Configuration

All settings come from environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `FRANKFURTER_BASE_URL` | `https://api.frankfurter.app` | Upstream API base URL; point it at a self-hosted Frankfurter if you have one |
| `HTTP_TIMEOUT` | `10` | Upstream request timeout, in seconds |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Listen port |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

## Run it

### Prerequisites

- Python 3.10 or later (the Docker image uses 3.12)
- Outbound HTTPS access to `api.frankfurter.app`

### Locally

```bash
git clone https://github.com/harsha1979/currency-mcp.git
cd currency-mcp

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

The server listens on `http://localhost:8000/mcp`. To check that it's up:

```bash
curl -s localhost:8000/health
# {"status":"ok"}
```

### With Docker

```bash
docker build -t currency-mcp:0.1.0 .
docker run --rm -p 8000:8000 currency-mcp:0.1.0
```

## Test it

### Smoke-test script

[scripts/test_client.py](scripts/test_client.py) uses the official MCP Python client to connect, list the tools and call each one:

```bash
.venv/bin/python scripts/test_client.py                    # defaults to http://localhost:8000/mcp
.venv/bin/python scripts/test_client.py http://host:port/mcp
```

Expected output (the rates will differ):

```
Connecting to http://localhost:8000/mcp
Server: currency-exchange, protocol 2025-11-25
Tools: get_latest_exchange_rate, list_currencies

get_latest_exchange_rate(USD->EUR) isError=False
{ "amount": 1.0, "base": "USD", "date": "2026-09-30", "rates": { "EUR": 0.88067 } }
...
```

### MCP Inspector

```bash
npx @modelcontextprotocol/inspector
```

In the Inspector UI, set the transport to **Streamable HTTP**, set the URL to `http://localhost:8000/mcp`, click **Connect**, then open **Tools** to run them.

### curl

The MCP protocol is plain JSON-RPC over HTTP, so curl works too. Because the server is stateless, you can call a tool directly without an `initialize` handshake first:

```bash
# List tools
curl -s -X POST localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Convert 100 USD to EUR and GBP
curl -s -X POST localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_latest_exchange_rate","arguments":{"from_currency":"USD","to_currency":"EUR,GBP","amount":100}}}'
```

## Use it from an MCP client

### Claude Code

```bash
claude mcp add --transport http currency http://localhost:8000/mcp
```

Then ask, for example: *"Using the currency tool, convert 500 EUR to USD and JPY."*

### Claude Desktop, or other clients that only support stdio

Use the [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) bridge in the client's config file (for Claude Desktop, `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "currency": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/mcp"]
    }
  }
}
```

### Any client that supports Streamable HTTP

Point it at `http://<host>:<port>/mcp` with the transport set to Streamable HTTP. No authentication is built in (see [Security notes](#security-notes)).

## Deploy to Kubernetes (EKS)

[k8s/deployment.yaml](k8s/deployment.yaml) creates:

- the `internal-mcp` namespace
- a `currency-mcp` Deployment that runs as a non-root user with a read-only root filesystem, has `/health` probes and small resource requests
- a `currency-mcp` ClusterIP Service on port 80

```bash
# 1. Build and push the image to ECR
AWS_ACCOUNT=<account-id>; AWS_REGION=<region>
REPO=$AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/currency-mcp
aws ecr create-repository --repository-name currency-mcp --region $AWS_REGION
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com
docker buildx build --platform linux/amd64 -t $REPO:0.1.0 --push .   # match your node architecture

# 2. Set `image:` in k8s/deployment.yaml to $REPO:0.1.0, then apply it
kubectl apply -f k8s/deployment.yaml
kubectl -n internal-mcp rollout status deploy/currency-mcp

# 3. Quick test through a port-forward
kubectl -n internal-mcp port-forward svc/currency-mcp 8000:80
.venv/bin/python scripts/test_client.py http://localhost:8000/mcp
```

To scale out, raise `replicas`. Stateless mode means no sticky sessions are needed.

The Service is `ClusterIP`, so it's only reachable inside the cluster. To expose it, add an Ingress (for example with the AWS Load Balancer Controller) or change the Service type to `LoadBalancer`. Pods need outbound internet access (for example through a NAT gateway) to reach `api.frankfurter.app`.

## Security notes

- The server has **no authentication**. Keep it on an internal network, or put it behind a gateway that handles auth and rate limiting before exposing it.
- It is read-only: it only makes outbound `GET` requests to the configured Frankfurter URL.

## Project layout

```
.
├── server.py              # MCP server: tools, /health route, Streamable HTTP startup
├── requirements.txt       # mcp, httpx, uvicorn
├── Dockerfile             # python:3.12-slim, runs as UID 10001
├── k8s/deployment.yaml    # Namespace, Deployment and Service
└── scripts/test_client.py # MCP client smoke test
```

## License

[Apache License 2.0](LICENSE)
