# HRMS Georgia Enterprise

Production-oriented, multi-tenant HRMS for Georgia with FastAPI, React, PostgreSQL, Redis, attendance hardware sync, payroll exports, Mattermost integration, ESS, and operational monitoring.

## What Boots Automatically

On the first `docker compose up --build -d`, the app container now runs:

1. `python scripts/init_db.py`
2. schema migration from `sql/001_hrms_schema.sql`
3. enterprise extensions from `sql/002_enterprise_extensions.sql`
4. public holiday seed
5. superadmin bootstrap

## Deployment & Quick Start

Run the commands below from PowerShell on Windows.

### Step 1. Add local tenant domains

Run PowerShell as Administrator, then execute:

```powershell
@"
127.0.0.1 hrms.local
"@ | Add-Content $env:WINDIR\System32\drivers\etc\hosts
```

### Step 2. Boot the full stack

```powershell
cd C:\Users\User\hrms_georgia_enterprise\hrms_georgia_enterprise
docker compose up --build -d
```

### Step 3. Open the seeded system

```powershell
Start-Process "http://hrms.local:8000/ux/app"
```

Use the bootstrap administrator configured through environment variables:

- `SUPERADMIN_USERNAME`
- `SUPERADMIN_PASSWORD`

Optional endpoints:

- Swagger: `http://localhost:8000/docs`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

## Edge Middleware

Use the supplied edge stack when a device sits on a branch office LAN and should not be exposed directly over the public internet.

Start the branch middleware with:

```powershell
docker compose -f docker-compose.edge.yml up -d
```

Required environment variables for the edge host:

- `CENTRAL_DATABASE_URL`
- `CENTRAL_REDIS_URL`
- `JWT_SECRET`
- `EDGE_PUBLIC_BASE_URL`
- `NODE_CODE`
- `NODE_REGION`

`docker-compose.edge.yml` now runs the API directly and skips database initialization so branch nodes do not rerun schema and seed logic against the central database.

Detailed Dahua branch-office sync steps are in:

- `deployment/DAHUA_EDGE_SYNC.md`
- `deployment/MIDDLEWARE_BRIDGE.md`

## Per-Company Container Deployment

For the **same image / separate container per company** model, use:

- `deployment/docker-compose.tenant.yml`
- `deployment/tenant.env.example`
- `deployment/TENANT_DEPLOYMENT_RUNBOOK.md`

If you want a tenant stack to stay isolated but still edit source live from the host machine, add:

- `deployment/docker-compose.tenant.edit.yml`

## SMTP

Configure SMTP in `.env` next to `docker-compose.yml`, then rebuild the app:

```env
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_USE_TLS=true
```

```powershell
docker compose up --build -d app
```

## Google Calendar

To let each employee connect the dashboard `Upcoming Schedule` card to their work Google Calendar, add these values to `.env` and rebuild the app:

```env
GOOGLE_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/integrations/google-calendar/callback
```

If you serve the app from a public host or IP, set `GOOGLE_REDIRECT_URI` to that exact public callback URL and register the same URI in the Google Cloud OAuth client.

## Notes

- Tenant isolation is enforced from the request subdomain.
- Device registry supports tenant-specific assignment and superadmin cross-tenant visibility on the central host.
- Raw attendance logs remain immutable; HR corrections are stored as separate manual adjustment records.
- Timesheets can be exported from the payroll hub as `.xlsx` and `.pdf`.
