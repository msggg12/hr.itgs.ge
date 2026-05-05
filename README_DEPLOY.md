# HRMS Production Deployment Runbook

## 1. New Isolated Tenant Container

Create one directory per client so environment, volumes, logs, and Caddy hostnames stay isolated.

```powershell
ssh root@SERVER_IP
mkdir -p /opt/hrms-tenants/acme
cd /opt/hrms-tenants/acme
git clone <repo-url> .
cp .env.example .env
```

Set these values in `.env`:

```env
PUBLIC_HOST=acme.example.ge
PUBLIC_BASE_URL=https://acme.example.ge
CORS_ORIGINS=https://acme.example.ge
POSTGRES_PASSWORD=<strong tenant db password>
JWT_SECRET=<64+ character random secret>
SUPERADMIN_COMPANY_NAME=Acme LLC
SUPERADMIN_COMPANY_TRADE_NAME=Acme
SUPERADMIN_COMPANY_TAX_ID=<tax id>
SUPERADMIN_USERNAME=superadmin
SUPERADMIN_PASSWORD=<temporary password>
ACME_EMAIL=it@example.ge
```

Launch the tenant stack with a unique Compose project name:

```bash
docker compose --env-file .env -p hrms_acme up -d --build
docker compose --env-file .env -p hrms_acme ps
curl -fsS https://acme.example.ge/monitoring/healthz
```

After first login, create or verify the tenant domain in `Settings > General > Tenant Domains`:

```text
host: acme.example.ge
subdomain: acme
primary: on
active: on
```

Careers portal URL:

```text
https://acme.example.ge/careers/acme
```

## 2. Middleware EXE Build

Build on Windows from the repo root:

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python scripts\build_middleware.py
```

Output:

```text
dist\hrms-middleware-bridge.exe
```

The build script uses PyInstaller `--onefile`, `--console`, `--collect-all`, and explicit `--add-binary` discovery for ZKTeco, BioStar, and Suprema SDK DLLs found under `middleware`, `sdk`, `drivers`, `deployment`, or `app`.

## 3. Windows Middleware Install

Create the runtime folder on the branch PC:

```powershell
New-Item -ItemType Directory -Force C:\HRMS\Middleware
Copy-Item .\dist\hrms-middleware-bridge.exe C:\HRMS\Middleware\
```

Create `C:\HRMS\Middleware\.env.edge`:

```env
CENTRAL_DATABASE_URL=postgresql://hrms:<password>@<server>:5432/hrms
MIDDLEWARE_POLL_SECONDS=30
NODE_CODE=branch-win-01
NODE_REGION=tbilisi
HRMS_BRIDGE_NO_PAUSE=1
```

Manual live-console test:

```powershell
C:\HRMS\Middleware\hrms-middleware-bridge.exe --env-file C:\HRMS\Middleware\.env.edge
```

Install as a Windows Service with NSSM:

```powershell
nssm install HRMSMiddlewareBridge C:\HRMS\Middleware\hrms-middleware-bridge.exe "--env-file C:\HRMS\Middleware\.env.edge"
nssm set HRMSMiddlewareBridge AppDirectory C:\HRMS\Middleware
nssm set HRMSMiddlewareBridge AppStdout C:\HRMS\Middleware\middleware.log
nssm set HRMSMiddlewareBridge AppStderr C:\HRMS\Middleware\middleware.err.log
nssm set HRMSMiddlewareBridge Start SERVICE_AUTO_START
nssm start HRMSMiddlewareBridge
```

Verify:

```powershell
Get-Service HRMSMiddlewareBridge
Get-Content C:\HRMS\Middleware\middleware.log -Tail 50
```

## 4. Production QA

Run after every deployment:

```bash
docker compose --env-file .env -p hrms_acme ps
curl -fsS https://acme.example.ge/monitoring/healthz
curl -fsS https://acme.example.ge/api/info
curl -fsS https://acme.example.ge/careers/acme
```

Application checks:

```text
Login works for tenant admin.
Settings sections open: General, Structure, Policies, Integrations, Hardware.
Device registry shows online/offline state and recent command status.
Manual middleware EXE shows heartbeat logs and does not close on sync errors.
Hardware punches create first-punch / last-punch daily attendance sessions.
Payroll recalculation reflects attendance minutes and overtime.
Employee self-service shows hardware movement logs in personal history.
Public careers filters, pagination, vacancy detail, and application submit work.
ATS board shows vacancy stats and 1-5 star candidate cards.
```
