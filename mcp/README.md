# Asset Management MCP Server

This package exposes the AssetManagement backend through MCP.

## Transports

- `stdio`: for local clients such as Claude Desktop or Codex.
- `streamable HTTP`: for remote clients. The HTTP server includes a small OAuth 2.0 authorization-code-with-PKCE flow protected by `MCP_PASSWORD`.

## Local Setup

```bash
cd mcp
npm ci
cp .env.example .env
npm run build
npm run smoke
```

For stdio tools that read or write application data, set:

```env
BACKEND_URL=http://localhost:8000
BACKEND_USERNAME=your-username
BACKEND_PASSWORD=your-password
```

`BACKEND_USERNAME` and `BACKEND_PASSWORD` are a local stdio fallback only. Streamable HTTP uses the OAuth login user: the MCP access JWT is exchanged at the backend `/auth/mcp/exchange` endpoint for a short-lived backend API token, so backend operations run as the same user that authorized the MCP session.

## Run

stdio:

```bash
npm run start
```

HTTP:

```bash
npm run start:http
```

Health check:

```bash
curl http://localhost:3000/health
```

MCP endpoint:

```text
POST http://localhost:3000/mcp
```

OAuth metadata:

```text
GET http://localhost:3000/.well-known/oauth-authorization-server
```

## Docker Compose

The root `docker-compose.yml` includes a `mcp` service. Configure these in the root `.env`:

```env
MCP_APP_ENV=development
MCP_PORT=13000
MCP_BASE_URL=http://localhost:13000
MCP_PASSWORD=change-me-to-a-strong-password
MCP_JWT_SECRET=change-me-to-a-secret-key-at-least-32-chars
BACKEND_TOKEN_AUDIENCE=asset-management-backend
BACKEND_USERNAME=your-username
BACKEND_PASSWORD=your-password
```

For production, set `MCP_APP_ENV=production` and replace `MCP_JWT_SECRET` with a strong unique value shared with the backend `MCP_JWT_SECRET`. Set backend `MCP_ALLOWED_ISSUERS` to the public MCP issuer URL, usually `MCP_BASE_URL`, and keep `MCP_TOKEN_AUDIENCE` aligned with `BACKEND_TOKEN_AUDIENCE`. The HTTP server refuses known development defaults in production mode.

The server issues access tokens only for its own resource (`MCP_BASE_URL` with or without `/mcp`; `/authorize` answers `invalid_target` for any other `resource`) and accepts only tokens whose audience is that resource. To let another MCP server that shares `MCP_JWT_SECRET` pass its tokens, list its resource in `MCP_ACCEPTED_RESOURCES` (comma-separated URLs); remove it and run `docker compose up -d mcp` to close it again. The restart also drops registered clients and refresh tokens, so every client signs in again.

The Docker Compose `BACKEND_USERNAME` and `BACKEND_PASSWORD` values are still available for stdio or development fallback usage. They are not used for normal streamable HTTP tool calls after OAuth authorization.

Then run:

```bash
docker compose up --build mcp
```

## Capabilities

Tools cover:

- accounts and net worth
- transactions
- transaction batches
- analysis
- reports and period reviews
- monthly planning (one plan per client) and monthly reviews
- automatic transactions (the settings of recurring and one-off transactions)
- products and unit economics
- capsules (earmarks), their rules and funding sources
- goals: life scenarios and their simulation, life events, contribution plans, goal earmarks, and making the plan from the goal
- financial calculators and the simulation config
- exchange rates and tracked currencies
- client settings, data export/import, and AI helper endpoints

Resources:

- `asset-management://guide/overview`
- `asset-management://guide/accounting-rules`
- `asset-management://guide/data-entry`
- `asset-management://guide/auto-transactions`
- `asset-management://guide/product-reserve`
- `asset-management://guide/dangerous-operations`
- `asset-management://summary`
- `asset-management://transactions/recent`

Prompts:

- `monthly-finance-review`
- `goal-check`

## Safety Notes

Some tools write data: creating transactions, saving automatic transactions (active ones are recorded when due), applying planned actions, updating reviews, and writing plan rows from the goal. Read tool annotations before allowing automatic tool use.

For agent safety, prefer these before write operations:

- `validate_transaction_payload`
- `transactions_preview`
- `transaction_batches_preview`
- `products_preview`
- `monthly_plan_lines_preview`
- `plan_reflection_preview`
- `depreciation_preview`
