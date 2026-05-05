# Middleware Bridge Runbook

This bridge is for branch-office hardware where direct webhook delivery is unreliable.

## What the EXE supports

- `heartbeat`: branch agent health ping
- `read-card`: complete browser-started card enrollment sessions
- `dahua-db-poll`: read new Dahua events directly from the local SQL database and push them into HRMS

The built executable is:

- `dist/middleware/hrms-middleware-bridge.exe`

## Dahua DB polling

Use when your Dahua firmware cannot post attendance webhooks correctly.

1. Install the Microsoft SQL ODBC driver on the branch Windows PC.
2. Copy `middleware/dahua-db.example.json` and fill in:
   - `api_base_url`
   - `middleware_key`
   - `dahua_db.connection_url`
   - `dahua_db.query`
3. Run once for a test:

```powershell
.\dist\middleware\hrms-middleware-bridge.exe --config .\middleware\dahua-db.example.json dahua-db-poll --once
```

4. Run continuously:

```powershell
.\dist\middleware\hrms-middleware-bridge.exe --config .\middleware\dahua-db.example.json dahua-db-poll
```

The SQL query must alias these columns:

- `person_id`
- `event_ts`
- optional: `direction`
- optional: `verify_mode`
- optional: `external_log_id`
- optional: `device_serial`
- optional: `device_name`

Imported rows are posted to:

- `/api/v1/attendance/middleware-import`

## ZKTeco / BioStar modes

### One-way sync

Use the built-in device ingestion loop or the Windows SDK bridge to:
- pull attendance logs from device to HRMS
- keep HRMS as the reporting/payroll source of truth

### Two-way sync

Use the existing command queue + device registry to:
- upsert employees/cards/PINs from HRMS to device
- delete/deactivate users from device
- pull attendance logs from device back into HRMS

For ZKTeco `sdk_bridge` devices, keep the bridge running:

```powershell
.\dist\middleware\hrms-middleware-bridge.exe --config .\middleware\zk-sdk.example.json zkteco-sdk-sync
```

The same loop now pushes queued HRMS user/card changes and polls the SDK `transaction` table into `/api/v1/attendance/middleware-import`.

## Card enrollment

### Browser HID mode

For simple USB keyboard-emulating readers:
- open employee card enrollment modal
- swipe the card
- the modal captures the numeric value directly in the browser

### Middleware mode

For branch readers or controlled enrollment stations:

1. Start enrollment from HRMS
2. Use the EXE:

```powershell
.\dist\middleware\hrms-middleware-bridge.exe --config .\tmp\bridge-config.json read-card --token <enrollment_token> --card-id 12345678
```

## Security

- Every branch/tenant should use its own middleware API key
- Revoke keys from Settings when a branch PC is retired
- Keep Dahua DB credentials only on the local branch PC, not in the central app container
