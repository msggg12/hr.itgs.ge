# Tenant Container Deployment Runbook

This project is ready for a **same-image / separate-container-per-company** rollout.

## Model

- one shared app image
- one isolated app container per company
- one isolated database/schema target per company
- one isolated Mattermost URL/team per company
- one isolated middleware API key per company

## Files

- Base stack: `docker-compose.yml`
- Tenant override: `deployment/docker-compose.tenant.yml`
- Optional live-edit override: `deployment/docker-compose.tenant.edit.yml`
- Tenant env template: `deployment/tenant.env.example`

## Create a tenant env file

Example:

```powershell
Copy-Item deployment\tenant.env.example deployment\tenant-company-a.env
```

Set at minimum:

- `TENANT_LABEL`
- `FORCE_TENANT_LEGAL_ENTITY_ID`
- `TENANT_DATABASE_URL`
- `TENANT_APP_PORT`
- `TENANT_CHAT_PORT`
- `PUBLIC_BASE_URL`
- `CORS_ORIGINS`
- `JWT_SECRET`
- `MATTERMOST_SITE_URL`
- `MATTERMOST_PUBLIC_URL`

## Launch one company

```powershell
docker compose -p hrms-company-a --env-file deployment\tenant-company-a.env -f docker-compose.yml -f deployment\docker-compose.tenant.yml up --build -d
```

## Launch one company with bind-mounted editable code

Use this only for test/staging environments where you want container isolation but still want to edit source files locally and see them inside the container.

```powershell
docker compose -p hrms-company-a --env-file deployment\tenant-company-a.env -f docker-compose.yml -f deployment\docker-compose.tenant.yml -f deployment\docker-compose.tenant.edit.yml up --build -d
```

## Launch another company

Create a second env file with different ports, database URL, public URL, and tenant legal entity id:

```powershell
docker compose -p hrms-company-b --env-file deployment\tenant-company-b.env -f docker-compose.yml -f deployment\docker-compose.tenant.yml up --build -d
```

## Notes

- You can keep **one image** and still run many tenant stacks because isolation is driven by env vars and target database/schema.
- Always use a unique `-p` compose project name per company so container names, networks, and volumes stay isolated.
- If you want to edit code “inside” the container for a specific company, use the bind-mount override.
- If one company needs a code change later, create a separate branch or override stack for that tenant before rebuilding.
