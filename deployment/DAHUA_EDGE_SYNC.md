# Dahua Edge Sync Guide

## What This Stack Supports

This HRMS stack talks to Dahua readers directly through Dahua CGI endpoints. In this repository that logic lives in:

- `app/device_middleware.py`
- `docker-compose.edge.yml`

The implemented Dahua flow uses:

- `/cgi-bin/accessUser.cgi?action=insertMulti` for user sync
- `/cgi-bin/accessUser.cgi?action=removeMulti` for revoke
- `/cgi-bin/recordFinder.cgi?action=find` and `findNext` for attendance log pull

SmartPSS itself is not the integration endpoint in the current codebase. SmartPSS can still be used by operations staff for monitoring, but the HRMS sync path is:

1. HRMS central database
2. edge middleware node on the branch LAN
3. Dahua device over local IP

## Recommended Architecture

Use this when the Dahua reader is on another network and should not be opened directly to the internet.

- Central HRMS server:
  - hosts PostgreSQL
  - hosts Redis
  - hosts the main UI if needed
- Branch edge node:
  - runs `docker-compose.edge.yml`
  - has LAN access to the Dahua reader
  - has outbound access to the central PostgreSQL and Redis
- Dahua reader:
  - static private IP on the branch LAN
  - CGI enabled

## Required Network Paths

Allow these connections:

- Edge host -> Dahua reader: TCP `80` or `443`
- Edge host -> central PostgreSQL: TCP `5432`
- Edge host -> central Redis: TCP `6379`
- Admin browser -> edge host: TCP `8010` if you want to operate the branch node UI directly

## Dahua Device Prerequisites

Before touching HRMS, configure the Dahua reader:

1. Give the reader a static IP on the branch LAN.
2. Set the correct timezone and time.
3. Set an admin username and password.
4. Enable CGI in the web interface.
5. If HTTPS is enabled on the reader, use an `https://` `api_base_url` in HRMS.
6. If the reader has an IP allowlist or firewall allowlist, add the edge node IP.

## Device Registry Values To Use In HRMS

When you register the Dahua device in the HRMS Device Registry, use:

- `brand`: `dahua`
- `transport`: `http_cgi`
- `device_type`: one of:
  - `biometric_terminal`
  - `rfid_card_reader`
  - `access_control_gate`
- `host`: the local device IP on the branch LAN, for example `192.168.50.20`
- `port`: `80` or `443`
- `api_base_url`: for example `http://192.168.50.20:80` or `https://192.168.50.20:443`
- `username`: the Dahua admin user
- `password_ciphertext`: the Dahua admin password
- `serial_number`: the real device serial
- `device_timezone`: normally `Asia/Tbilisi`

## Step 1. Prepare The Edge Host

Run this on the branch middleware machine:

```powershell
cd C:\Users\User\hrms_georgia_enterprise\hrms_georgia_enterprise
```

Create an environment file that Docker Compose will load:

```powershell
@"
CENTRAL_DATABASE_URL=postgresql://hrms:hrms@YOUR_CENTRAL_DB_HOST:5432/hrms
CENTRAL_REDIS_URL=redis://YOUR_CENTRAL_REDIS_HOST:6379/0
JWT_SECRET=change-me-before-production
EDGE_PUBLIC_BASE_URL=http://YOUR_EDGE_IP:8010
EDGE_CORS_ORIGINS=http://YOUR_EDGE_IP:8010,http://YOUR_MAIN_HRMS_HOST:8000
NODE_CODE=dahua-branch-01
NODE_REGION=tbilisi
EDGE_PORT=8010
"@ | Set-Content .env
```

If the central DB and Redis are only reachable over VPN, bring the VPN up before starting the edge stack.

## Step 2. Start The Branch Middleware

```powershell
docker compose -f docker-compose.edge.yml up --build -d
```

Health check:

```powershell
Invoke-RestMethod http://localhost:8010/monitoring/healthz
```

Expected result:

```text
status: ok
```

## Step 3. Register The Reader

You can do this from the central UI or from the edge UI because both write to the same database.

Recommended for branch-only devices:

- Open `http://YOUR_EDGE_IP:8010/ux/app`
- Log in as an admin
- Go to `Settings` -> `Device Registry`
- Create the Dahua reader with the values listed above

## Step 4. Sync Employees To The Reader

The branch-safe path now works like this:

1. HR triggers employee sync from HRMS.
2. HRMS stores a queued command in `device_command_queue`.
3. The edge node processes that queue and calls the Dahua CGI endpoint on the local network.

Operationally, the safest way is:

- open the branch UI on `http://YOUR_EDGE_IP:8010/ux/app`
- go to `Employees`
- choose the employee
- click the device sync action
- select the Dahua reader

This guarantees the request lands on the node that can reach the device.

## Step 5. Attendance Log Ingestion

The edge node continuously pulls logs from the Dahua reader on its local LAN and writes them into the central database.

No extra cron is required. The worker starts automatically because `docker-compose.edge.yml` sets:

- `ENABLE_DEVICE_WORKERS=true`

## Step 6. Verification

After syncing one employee, verify:

1. The employee appears on the Dahua device.
2. A new punch on the device shows up in HRMS live attendance.
3. The device appears online in the monitoring screen.

If needed, inspect the queue inside PostgreSQL:

```sql
SELECT id, command_type, status, last_error, created_at
FROM device_command_queue
ORDER BY created_at DESC
LIMIT 20;
```

## Troubleshooting

### Device sync stays in `failed`

Check:

- wrong device IP
- wrong port
- wrong Dahua username/password
- CGI disabled
- HTTPS enabled on device but `api_base_url` still uses `http://`
- firewall on the branch LAN blocking the edge host

### Logs are not arriving

Check:

- edge host can open the device IP
- device timezone is correct
- employee was synced with the expected `device_user_id`
- edge worker is healthy on `http://YOUR_EDGE_IP:8010/monitoring/healthz`

### SmartPSS shows events but HRMS does not

That usually means SmartPSS can see the reader, but the HRMS edge node cannot. Fix the branch LAN path between:

- edge host
- Dahua reader

Do not rely on SmartPSS alone as the data bridge for this codebase.
