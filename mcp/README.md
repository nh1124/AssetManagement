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

For tools that read or write application data, set:

```env
BACKEND_URL=http://localhost:8000
BACKEND_USERNAME=your-username
BACKEND_PASSWORD=your-password
```

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
MCP_PORT=13000
MCP_BASE_URL=http://localhost:13000
MCP_PASSWORD=change-me-to-a-strong-password
MCP_JWT_SECRET=change-me-to-a-secret-key-at-least-32-chars
BACKEND_USERNAME=your-username
BACKEND_PASSWORD=your-password
```

Then run:

```bash
docker compose up --build mcp
```

## Capabilities

Tools cover:

- accounts and net worth
- transactions
- analysis
- reports and period reviews
- action bridges
- recurring transactions
- roadmap and milestones
- products and unit economics
- capsules, life events, and financial calculators

Resources:

- `asset-management://summary`
- `asset-management://transactions/recent`

Prompts:

- `monthly-finance-review`
- `goal-roadmap-check`

## Safety Notes

Some tools write data: creating transactions, processing recurring transactions, applying report actions, updating reviews, and generating milestones. Read tool annotations before allowing automatic tool use.
