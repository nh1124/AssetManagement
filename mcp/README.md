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

The Docker Compose `BACKEND_USERNAME` and `BACKEND_PASSWORD` values are still available for stdio or development fallback usage. They are not used for normal streamable HTTP tool calls after OAuth authorization.

Then run:

```bash
docker compose up --build mcp
```

## Capabilities

Tools cover:

- accounts and net worth
- transactions
- quick templates and transaction batches
- analysis
- reports and period reviews
- monthly planning and monthly reviews
- action bridges
- recurring transactions
- roadmap and milestones
- products and unit economics
- capsules, life events, and financial calculators
- simulation config, Monte Carlo runs, and saved scenarios
- exchange rates
- client settings, data export/import, and AI helper endpoints

Resources:

- `asset-management://guide/overview`
- `asset-management://guide/accounting-rules`
- `asset-management://guide/data-entry`
- `asset-management://guide/recurring`
- `asset-management://guide/product-reserve`
- `asset-management://guide/dangerous-operations`
- `asset-management://summary`
- `asset-management://transactions/recent`

Prompts:

- `monthly-finance-review`
- `goal-roadmap-check`

## Safety Notes

Some tools write data: creating transactions, processing recurring transactions, applying report actions, updating reviews, and generating milestones. Read tool annotations before allowing automatic tool use.

For agent safety, prefer these before write operations:

- `help_choose_transaction_type`
- `validate_transaction_payload`
- `transactions_preview`
- `recurring_preview`
- `transaction_batches_preview`
- `products_preview`
- `monthly_plan_lines_preview`
