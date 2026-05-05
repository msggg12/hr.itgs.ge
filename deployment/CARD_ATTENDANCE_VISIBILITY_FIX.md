# Card attendance visibility fix

Date: 2026-05-03

## Problem

Card-based punches were not visible in employee attendance views, the home check-in state, or analytics.

## Root causes found

- The ZKTeco SDK bridge only synced user/card commands. It did not read device transaction logs and import them into HRMS.
- `raw_attendance_logs` had no physical card events from the device.
- The SDK transaction output was CSV (`Cardno,Pin,Verified,DoorID,EventType,InOutState,Time_second`), while the first parser handled only `key=value` rows.
- ZKTeco C3 `Time_second` is based on the ZKTeco 2000-01-01 epoch, not Unix epoch.
- The Windows worker was launched outside `C:\ZKTeco\PullSDK`, so `plcommpro.dll` loaded but `Connect` failed until the DLL directory was added to the DLL search path.
- The device clock had a wrong future date. It was set to local time through `SetDeviceParam(DateTime=...)`.
- Employee `EMP-2026-00002` (`S Sulkhanishvili`) was soft-deleted/terminated, so attendance scope and employee lists excluded the employee.
- The employee card identity for card `0012553913` was inactive.
- A queued `delete_user` device command existed for that same employee/device, which could remove the user from the ZKTeco terminal.

## Server changes

- Middleware imports now create/update `attendance_work_sessions`, so imported card punches appear in attendance and analytics.
- If a device import has no direction, HRMS infers the next direction from the latest same-day session: first punch is `in`, next is `out`.
- Added `GET /api/v1/devices/sdk-bridge/devices` for the Windows ZKTeco SDK bridge.
- Fixed employee-device assignment sync so an empty desired-device list no longer deletes all assignments.
- Fixed employee sync upsert so an existing identity is reactivated instead of staying inactive.
- Updated the ZKTeco SDK bridge to poll `transaction` logs and send them to `/api/v1/attendance/middleware-import`.
- Updated the bridge to:
  - add the Pull SDK DLL directory to the Windows DLL search path,
  - parse SDK CSV transaction output,
  - convert `Time_second` from the ZKTeco epoch,
  - ignore `Pin=0` device/system events,
  - use row-count checkpointing so corrected device time does not cause new rows to be skipped.

## Data repair

- Restored `EMP-2026-00002` to active status.
- Reactivated the card identity for `0012553913`.
- Removed the queued `delete_user` command.
- Queued a fresh `upsert_user` command for the ZKTeco device.
- Corrected the latest real `Pin=4` card punch from the device's wrong future date to `2026-05-03 01:39:22` Asia/Tbilisi and imported it.
- Removed the accidental future-dated imports after verification.

## Verification

- Backend Python files compile successfully.
- The app container was rebuilt and restarted.
- A middleware import smoke test using card `0012553913` matched `EMP-2026-00002`, inferred direction `in`, and created an attendance session. Test data was removed after verification.
- Built Windows bridge executable:
  - Local: `C:\Users\datia\hrms_remote_work\dist\middleware\hrms-middleware-bridge.exe`
  - Server: `/opt/hrms_georgia_enterprise/dist/middleware/hrms-middleware-bridge.exe`
  - SHA256: `99B4D65DBD52C78531B139737489E6254799FB9E408E4C536882C56541D6AAA7`
- The local Windows worker is running from `C:\Users\datia\hrms-middleware` with PID recorded in `zkteco-sdk-sync.pid`.
- The worker log shows repeated successful cycles with `submitted_count: 0` after checkpointing old rows.
- Database now contains the corrected raw log and an open `attendance_work_sessions` row for `EMP-2026-00002` on `2026-05-03`.

## Operational state

The local branch Windows worker has been updated and started. If this worker is stopped or moved to another PC, use the updated executable and keep the checkpoint file with the current row count so the old future-dated device history is not re-imported.
