from __future__ import annotations

import argparse
import csv
import ctypes
import io
import json
import logging
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

LOGGER = logging.getLogger('hrms.middleware')


def configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get('HRMS_MIDDLEWARE_LOG_LEVEL', 'INFO').upper(),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )


@dataclass(slots=True)
class AgentConfig:
    api_base_url: str
    middleware_key: str
    heartbeat_interval_seconds: int = 30
    device_ping_interval_seconds: int = 60

    @classmethod
    def from_env(cls) -> 'AgentConfig':
        api_base_url = (os.environ.get('HRMS_API_BASE_URL') or '').rstrip('/')
        middleware_key = (os.environ.get('HRMS_MIDDLEWARE_KEY') or '').strip()
        heartbeat_interval_seconds = int(os.environ.get('HRMS_HEARTBEAT_INTERVAL_SECONDS') or '30')
        device_ping_interval_seconds = int(os.environ.get('HRMS_DEVICE_PING_INTERVAL_SECONDS') or '60')
        if not api_base_url or not middleware_key:
            raise RuntimeError('HRMS_API_BASE_URL and HRMS_MIDDLEWARE_KEY must be configured')
        return cls(
            api_base_url=api_base_url,
            middleware_key=middleware_key,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            device_ping_interval_seconds=device_ping_interval_seconds,
        )


@dataclass(slots=True)
class DahuaDbPollingConfig:
    connection_url: str
    query: str
    checkpoint_file: Path
    poll_interval_seconds: int = 20
    timezone: str = 'Asia/Tbilisi'


@dataclass(slots=True)
class ZktecoSdkBridgeConfig:
    dll_path: str | None = None
    poll_interval_seconds: int = 20
    command_limit: int = 50
    default_authorize_timezone_id: str = '1'
    default_authorize_door_id: str = '1'
    timeout_seconds: int = 10
    dry_run: bool = False
    attendance_polling_enabled: bool = True
    checkpoint_file: Path = Path('tmp/zkteco-sdk-checkpoint.json')


def _request_json(config: AgentConfig, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if method.upper() == 'GET' and payload is None else json.dumps(payload or {}).encode('utf-8')
    request = urllib.request.Request(
        f"{config.api_base_url}{path}",
        data=body,
        method=method,
        headers={
            'Content-Type': 'application/json',
            'X-Middleware-Key': config.middleware_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content = response.read().decode('utf-8') or '{}'
            return json.loads(content)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'HTTP {exc.code}: {detail}') from exc


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _tcp_port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def collect_device_tcp_pings(config: AgentConfig) -> list[dict[str, Any]]:
    """TCP reachability per registered SDK-bridge device (IP:port). Sent with bridge heartbeat for granular last_seen_at."""
    try:
        data = fetch_zkteco_sdk_devices(config)
    except Exception as exc:
        LOGGER.warning('sdk-bridge devices fetch failed: %s', exc)
        return []
    devices = data.get('devices') or []
    results: list[dict[str, Any]] = []
    probe_timeout = float(os.environ.get('HRMS_DEVICE_TCP_PROBE_TIMEOUT', '3') or '3')
    probe_timeout = max(0.5, min(probe_timeout, 8.0))
    for item in devices:
        host = str(item.get('host') or '').strip()
        if not host:
            continue
        try:
            port = int(item.get('port') or 4370)
        except (TypeError, ValueError):
            port = 4370
        device_id = item.get('id')
        if not device_id:
            continue
        started = time.perf_counter()
        ok = _tcp_port_open(host, port, timeout=probe_timeout)
        rtt_ms = int((time.perf_counter() - started) * 1000) if ok else 0
        results.append({'device_id': str(device_id), 'reachable': ok, 'rtt_ms': rtt_ms})
    if results:
        reachable = sum(1 for row in results if row.get('reachable'))
        LOGGER.info('device tcp probe: %s/%s reachable', reachable, len(results))
    return results


def heartbeat_loop(config: AgentConfig) -> None:
    LOGGER.info(
        'heartbeat loop started: api_base_url=%s interval_seconds=%s device_ping_interval_seconds=%s',
        config.api_base_url,
        config.heartbeat_interval_seconds,
        config.device_ping_interval_seconds,
    )
    last_ping_monotonic = time.monotonic() - float(config.device_ping_interval_seconds)
    while True:
        body: dict[str, Any] = {}
        now = time.monotonic()
        if now - last_ping_monotonic >= float(config.device_ping_interval_seconds):
            last_ping_monotonic = now
            body['device_pings'] = collect_device_tcp_pings(config)
        response = _request_json(config, 'POST', '/api/v1/devices/bridge/heartbeat', body)
        LOGGER.info('heartbeat response: %s', json.dumps(response, ensure_ascii=False))
        time.sleep(config.heartbeat_interval_seconds)


def submit_card_read(config: AgentConfig, enrollment_token: str, card_id: str, device_serial: str | None = None) -> None:
    response = _request_json(
        config,
        'POST',
        '/api/v1/devices/enroll-card/read',
        {
            'enrollment_token': enrollment_token,
            'card_id': card_id,
            'device_serial': device_serial,
        },
    )
    print(json.dumps(response, ensure_ascii=False))


def submit_attendance_logs(config: AgentConfig, logs: list[dict[str, Any]]) -> dict[str, Any]:
    response = _request_json(
        config,
        'POST',
        '/api/v1/attendance/middleware-import',
        {'logs': logs},
    )
    print(json.dumps(response, ensure_ascii=False))
    return response


def fetch_zkteco_sdk_commands(config: AgentConfig, limit: int) -> dict[str, Any]:
    return _request_json(config, 'POST', '/api/v1/devices/sdk-bridge/commands/next', {'limit': limit})


def fetch_zkteco_sdk_devices(config: AgentConfig) -> dict[str, Any]:
    return _request_json(config, 'GET', '/api/v1/devices/sdk-bridge/devices')


def report_zkteco_sdk_command_result(config: AgentConfig, command_id: str, status: str, error: str | None = None) -> None:
    payload = {'status': status}
    if error:
        payload['error'] = error
    response = _request_json(config, 'POST', f'/api/v1/devices/sdk-bridge/commands/{command_id}/result', payload)
    print(json.dumps(response, ensure_ascii=False))


def load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {'last_event_ts': '1970-01-01 00:00:00'}
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError:
        return {'last_event_ts': '1970-01-01 00:00:00'}


def save_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _coerce_event_ts(value: Any, tz_name: str) -> str:
    timezone_value = ZoneInfo(tz_name)
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone_value)
    return parsed.astimezone(ZoneInfo('UTC')).isoformat()


def load_dahua_db_config(config_path: Path) -> DahuaDbPollingConfig:
    payload = json.loads(config_path.read_text(encoding='utf-8-sig'))
    dahua_db = payload.get('dahua_db') or {}
    connection_url = str(dahua_db.get('connection_url') or '').strip()
    query = str(dahua_db.get('query') or '').strip()
    checkpoint_file = Path(str(dahua_db.get('checkpoint_file') or 'tmp/dahua-db-checkpoint.json'))
    if not connection_url or not query:
        raise RuntimeError('Config file must include dahua_db.connection_url and dahua_db.query')
    return DahuaDbPollingConfig(
        connection_url=connection_url,
        query=query,
        checkpoint_file=checkpoint_file,
        poll_interval_seconds=int(dahua_db.get('poll_interval_seconds', 20)),
        timezone=str(dahua_db.get('timezone') or 'Asia/Tbilisi'),
    )


def load_zkteco_sdk_config(config_path: Path | None) -> ZktecoSdkBridgeConfig:
    payload: dict[str, Any] = {}
    if config_path:
        payload = json.loads(config_path.read_text(encoding='utf-8-sig'))
    sdk_config = payload.get('zkteco_sdk') or {}
    return ZktecoSdkBridgeConfig(
        dll_path=str(sdk_config.get('dll_path') or '').strip() or None,
        poll_interval_seconds=int(sdk_config.get('poll_interval_seconds', 20)),
        command_limit=int(sdk_config.get('command_limit', 50)),
        default_authorize_timezone_id=str(sdk_config.get('default_authorize_timezone_id') or '1'),
        default_authorize_door_id=str(sdk_config.get('default_authorize_door_id') or '1'),
        timeout_seconds=int(sdk_config.get('timeout_seconds', 10)),
        dry_run=bool(sdk_config.get('dry_run', False)),
        attendance_polling_enabled=bool(sdk_config.get('attendance_polling_enabled', True)),
        checkpoint_file=Path(str(sdk_config.get('checkpoint_file') or 'tmp/zkteco-sdk-checkpoint.json')),
    )


def poll_dahua_db_once(config: AgentConfig, db_config: DahuaDbPollingConfig) -> dict[str, Any]:
    checkpoint = load_checkpoint(db_config.checkpoint_file)
    last_event_ts = checkpoint.get('last_event_ts') or '1970-01-01 00:00:00'
    engine = create_engine(db_config.connection_url)
    rows: list[dict[str, Any]] = []
    with engine.connect() as conn:
        result = conn.execute(text(db_config.query), {'last_event_ts': last_event_ts})
        rows = [dict(row._mapping) for row in result]
    if not rows:
        response = {'status': 'idle', 'fetched_count': 0, 'last_event_ts': last_event_ts}
        print(json.dumps(response, ensure_ascii=False))
        return response

    normalized_logs: list[dict[str, Any]] = []
    for row in rows:
        person_id = str(
            row.get('person_id')
            or row.get('PersonID')
            or row.get('UserID')
            or row.get('user_id')
            or ''
        ).strip()
        if not person_id:
            continue
        event_ts = row.get('event_ts') or row.get('EventTime') or row.get('Time')
        if event_ts in (None, ''):
            continue
        normalized_logs.append(
            {
                'person_id': person_id,
                'event_ts': _coerce_event_ts(event_ts, db_config.timezone),
                'direction': str(row.get('direction') or row.get('Direction') or row.get('EventType') or 'unknown'),
                'verify_mode': row.get('verify_mode') or row.get('VerifyMode'),
                'external_log_id': str(row.get('external_log_id') or row.get('LogID') or row.get('RecNo') or ''),
                'device_serial': row.get('device_serial') or row.get('DeviceSerial'),
                'device_name': row.get('device_name') or row.get('DeviceName'),
                'raw_payload': row,
            }
        )
    if not normalized_logs:
        response = {'status': 'idle', 'fetched_count': 0, 'reason': 'rows_missing_required_aliases'}
        print(json.dumps(response, ensure_ascii=False))
        return response

    submit_response = submit_attendance_logs(config, normalized_logs)
    save_checkpoint(
        db_config.checkpoint_file,
        {
            'last_event_ts': normalized_logs[-1]['event_ts'],
            'last_external_log_id': normalized_logs[-1]['external_log_id'],
        },
    )
    return {
        'status': 'imported',
        'fetched_count': len(rows),
        'submitted_count': len(normalized_logs),
        **submit_response,
    }


def dahua_db_poll_loop(config: AgentConfig, db_config: DahuaDbPollingConfig, once: bool) -> None:
    LOGGER.info('Dahua DB polling started: once=%s checkpoint=%s', once, db_config.checkpoint_file)
    while True:
        poll_dahua_db_once(config, db_config)
        if once:
            return
        time.sleep(db_config.poll_interval_seconds)


def _require_windows() -> None:
    if os.name != 'nt':
        raise RuntimeError('ZKTeco SDK bridge requires Windows because Pull SDK ships as a Windows DLL')


def _encode_sdk_text(value: str) -> bytes:
    return value.encode('utf-8')


def _sdk_record_data(value: str) -> str:
    clean = value.rstrip('\r\n')
    return f'{clean}\r\n' if clean else ''


def _clean_field(value: Any) -> str:
    return str(value or '').replace('\t', ' ').replace('\r', ' ').replace('\n', ' ').strip()


class ZktecoPullSdk:
    def __init__(self, dll_path: str | None, timeout_seconds: int) -> None:
        _require_windows()
        self.timeout_seconds = timeout_seconds
        self.dll_path = Path(dll_path) if dll_path else Path('plcommpro.dll')
        if self.dll_path.parent != Path('.'):
            dll_dir = str(self.dll_path.parent.resolve())
            os.environ['PATH'] = dll_dir + os.pathsep + os.environ.get('PATH', '')
            add_dll_directory = getattr(os, 'add_dll_directory', None)
            if add_dll_directory is not None:
                add_dll_directory(dll_dir)
        self.dll = ctypes.WinDLL(str(self.dll_path))
        self.dll.Connect.argtypes = [ctypes.c_char_p]
        self.dll.Connect.restype = ctypes.c_void_p
        self.dll.Disconnect.argtypes = [ctypes.c_void_p]
        self.dll.Disconnect.restype = ctypes.c_int
        self.dll.SetDeviceData.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        self.dll.SetDeviceData.restype = ctypes.c_int
        self.dll.DeleteDeviceData.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        self.dll.DeleteDeviceData.restype = ctypes.c_int
        self.dll.GetDeviceData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
        ]
        self.dll.GetDeviceData.restype = ctypes.c_int
        self.dll.PullLastError.argtypes = []
        self.dll.PullLastError.restype = ctypes.c_int

    def connect(self, device: dict[str, Any]) -> ctypes.c_void_p:
        host = _clean_field(device.get('host'))
        port = int(device.get('port') or 4370)
        password = _clean_field(device.get('password') or '')
        if not host:
            raise RuntimeError('Device host is missing')
        if not self._tcp_port_open(host, port):
            raise RuntimeError(f'Device {host}:{port} is not reachable from this PC')
        params = f'protocol=TCP,ipaddress={host},port={port},timeout={self.timeout_seconds * 1000},passwd={password}'
        handle = self.dll.Connect(_encode_sdk_text(params))
        if not handle:
            error_code = self.dll.PullLastError()
            raise RuntimeError(f'Pull SDK failed to connect to {host}:{port} (error {error_code})')
        return handle

    def disconnect(self, handle: ctypes.c_void_p) -> None:
        self.dll.Disconnect(handle)

    def set_device_data(self, handle: ctypes.c_void_p, table: str, data: str) -> None:
        result = self.dll.SetDeviceData(handle, _encode_sdk_text(table), _encode_sdk_text(_sdk_record_data(data)), b'')
        if result != 0:
            raise RuntimeError(f'SetDeviceData({table}) failed with code {result}')

    def delete_device_data(self, handle: ctypes.c_void_p, table: str, data: str) -> None:
        result = self.dll.DeleteDeviceData(handle, _encode_sdk_text(table), _encode_sdk_text(_sdk_record_data(data)), b'')
        if result != 0:
            raise RuntimeError(f'DeleteDeviceData({table}) failed with code {result}')

    def get_device_data(self, handle: ctypes.c_void_p, table: str, fields: str = '*', filters: str = '') -> str:
        buffer_size = 4 * 1024 * 1024
        buffer = ctypes.create_string_buffer(buffer_size)
        result = self.dll.GetDeviceData(
            handle,
            buffer,
            buffer_size,
            _encode_sdk_text(table),
            _encode_sdk_text(fields),
            _encode_sdk_text(filters),
            b'',
        )
        if result < 0:
            raise RuntimeError(f'GetDeviceData({table}) failed with code {result}')
        return buffer.value.decode('utf-8', errors='replace')

    def _tcp_port_open(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=min(self.timeout_seconds, 5)):
                return True
        except OSError:
            return False


def _zkteco_user_record(payload: dict[str, Any]) -> str:
    pin = _clean_field(payload.get('external_user_id'))
    if not pin:
        raise RuntimeError('Queued command is missing external_user_id')
    name = _clean_field(f"{payload.get('first_name') or ''} {payload.get('last_name') or ''}") or pin
    fields = [
        f'Pin={pin}',
        f'Name={name}',
        f'Password={_clean_field(payload.get("pin_code"))}',
        'Group=1',
        'StartTime=0',
        'EndTime=0',
    ]
    card_number = _clean_field(payload.get('card_number'))
    if card_number:
        fields.insert(1, f'CardNo={card_number}')
    return '\t'.join(fields)


def _zkteco_userauthorize_record(payload: dict[str, Any], bridge_config: ZktecoSdkBridgeConfig, device: dict[str, Any]) -> str:
    metadata = device.get('metadata') if isinstance(device.get('metadata'), dict) else {}
    pin = _clean_field(payload.get('external_user_id'))
    timezone_id = _clean_field(metadata.get('authorize_timezone_id')) or bridge_config.default_authorize_timezone_id
    door_id = _clean_field(metadata.get('authorize_door_id')) or bridge_config.default_authorize_door_id
    return f'Pin={pin}\tAuthorizeTimezoneId={timezone_id}\tAuthorizeDoorId={door_id}'


def process_zkteco_sdk_command(sdk: ZktecoPullSdk | None, bridge_config: ZktecoSdkBridgeConfig, command: dict[str, Any]) -> None:
    device = _json_dict(command.get('device'))
    payload = _json_dict(command.get('payload'))
    command_type = command.get('command_type')
    if bridge_config.dry_run:
        print(json.dumps({'dry_run': True, 'command_id': command['id'], 'command_type': command_type, 'device': device.get('device_name')}, ensure_ascii=False))
        return
    if sdk is None:
        raise RuntimeError('ZKTeco Pull SDK DLL is not loaded')
    handle = sdk.connect(device)
    try:
        if command_type == 'upsert_user':
            sdk.set_device_data(handle, 'user', _zkteco_user_record(payload))
            sdk.set_device_data(handle, 'userauthorize', _zkteco_userauthorize_record(payload, bridge_config, device))
            return
        if command_type == 'delete_user':
            pin = _clean_field(payload.get('external_user_id'))
            if not pin:
                raise RuntimeError('Queued delete command is missing external_user_id')
            sdk.delete_device_data(handle, 'userauthorize', f'Pin={pin}')
            sdk.delete_device_data(handle, 'user', f'Pin={pin}')
            return
        raise RuntimeError(f'Unsupported ZKTeco SDK command type: {command_type}')
    finally:
        sdk.disconnect(handle)


def zkteco_sdk_sync_once(config: AgentConfig, bridge_config: ZktecoSdkBridgeConfig, sdk: ZktecoPullSdk | None) -> dict[str, Any]:
    response = fetch_zkteco_sdk_commands(config, bridge_config.command_limit)
    commands = response.get('commands') or []
    completed = 0
    failed = 0
    for command in commands:
        try:
            process_zkteco_sdk_command(sdk, bridge_config, command)
            report_zkteco_sdk_command_result(config, command['id'], 'completed')
            completed += 1
        except Exception as exc:
            report_zkteco_sdk_command_result(config, command['id'], 'failed', str(exc))
            failed += 1
    summary = {'status': 'ok', 'fetched_count': len(commands), 'completed_count': completed, 'failed_count': failed}
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def _parse_sdk_record_line(line: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for separator in ('\t', ','):
        if separator in line:
            parts = line.split(separator)
            break
    else:
        parts = [line]
    for part in parts:
        clean = part.strip()
        if not clean or '=' not in clean:
            continue
        key, value = clean.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def _sdk_value(record: dict[str, str], *keys: str) -> str:
    lowered = {key.lower(): value for key, value in record.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ''):
            return value
    return ''


def _parse_sdk_event_ts(value: str, *, zkteco_epoch: bool = False) -> str | None:
    clean = value.strip()
    if not clean:
        return None
    if clean.isdigit():
        number = int(clean)
        if number > 10_000_000_000:
            number //= 1000
        if zkteco_epoch or number < 1_000_000_000:
            return (datetime(2000, 1, 1) + timedelta(seconds=number)).isoformat()
        return datetime.fromtimestamp(number).isoformat()
    for pattern in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(clean, pattern).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(clean).isoformat()
    except ValueError:
        return None


def _device_timezone(device: dict[str, Any]) -> ZoneInfo:
    try:
        return ZoneInfo(str(device.get('device_timezone') or 'Asia/Tbilisi'))
    except Exception:
        return ZoneInfo('Asia/Tbilisi')


def _correct_implausible_device_ts(event_ts: str, time_second: str, device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not time_second:
        return event_ts, {}
    try:
        parsed = datetime.fromisoformat(event_ts)
    except ValueError:
        return event_ts, {}
    tz = _device_timezone(device)
    local_dt = parsed.astimezone(tz) if parsed.tzinfo else parsed.replace(tzinfo=tz)
    now_local = datetime.now(tz)
    if local_dt.year > 2001 and local_dt <= now_local + timedelta(days=1):
        return event_ts, {}
    corrected = datetime.combine(now_local.date(), local_dt.time()).replace(tzinfo=tz)
    if corrected > now_local + timedelta(minutes=5):
        corrected -= timedelta(days=1)
    return corrected.isoformat(), {
        'source': 'zkteco_sdk_transaction_corrected_device_date',
        'corrected_reason': 'device timestamp date was outside the plausible range; local polling date was used',
        'original_event_ts': event_ts,
        'original_time_second': time_second,
    }


def _infer_sdk_direction(record: dict[str, str]) -> str | None:
    raw = _sdk_value(record, 'InOutState', 'inoutstate', 'Direction', 'direction', 'EventType', 'eventtype')
    text_value = raw.strip().lower()
    if text_value in {'in', 'checkin', 'check_in', 'entry', 'enter'}:
        return 'in'
    if text_value in {'out', 'checkout', 'check_out', 'exit', 'leave'}:
        return 'out'
    if text_value == '0':
        return 'in'
    if text_value == '1':
        return 'out'
    return None


def _normalize_sdk_transactions(raw_text: str, device: dict[str, Any]) -> list[dict[str, Any]]:
    logs: list[dict[str, Any]] = []
    lines = [line for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return logs
    if ',' in lines[0] and '=' not in lines[0]:
        records = [dict(row) for row in csv.DictReader(io.StringIO('\n'.join(lines)))]
    else:
        records = [_parse_sdk_record_line(line) for line in lines]
    for row_number, record in enumerate(records, start=1):
        if not record:
            continue
        time_second = _sdk_value(record, 'Time_second', 'time_second')
        event_ts = _parse_sdk_event_ts(
            time_second or _sdk_value(record, 'DateTime', 'Time', 'event_ts', 'PunchTime'),
            zkteco_epoch=bool(time_second),
        )
        person_id = _sdk_value(record, 'Pin', 'PIN', 'UserID', 'user_id', 'CardNo', 'CardNO', 'card_number', 'Card')
        if not event_ts or not person_id or person_id == '0':
            continue
        event_ts, correction_payload = _correct_implausible_device_ts(event_ts, time_second, device)
        raw_payload = {'source': 'zkteco_sdk_transaction', 'sdk_row_number': row_number, 'record': record}
        raw_payload.update(correction_payload)
        logs.append(
            {
                'person_id': person_id,
                'event_ts': event_ts,
                'direction': _infer_sdk_direction(record),
                'verify_mode': _sdk_value(record, 'Verified', 'verify_mode', 'EventType', 'eventtype') or None,
                'external_log_id': _sdk_value(record, 'Index', 'ID', 'LogID', 'RecordID') or f"{person_id}:{event_ts}",
                'device_serial': device.get('serial_number'),
                'device_name': device.get('device_name'),
                'raw_payload': raw_payload,
            }
        )
    return logs


def _sdk_transaction_row_count(raw_text: str) -> int:
    lines = [line for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return 0
    if ',' in lines[0] and '=' not in lines[0]:
        return max(len(lines) - 1, 0)
    return len(lines)


def zkteco_sdk_poll_attendance_once(config: AgentConfig, bridge_config: ZktecoSdkBridgeConfig, sdk: ZktecoPullSdk | None) -> dict[str, Any]:
    if not bridge_config.attendance_polling_enabled:
        return {'status': 'disabled', 'submitted_count': 0}
    if bridge_config.dry_run:
        return {'status': 'dry_run', 'submitted_count': 0}
    if sdk is None:
        raise RuntimeError('ZKTeco Pull SDK DLL is not loaded')
    checkpoint = load_checkpoint(bridge_config.checkpoint_file)
    response = fetch_zkteco_sdk_devices(config)
    submitted_count = 0
    for device in response.get('devices') or []:
        handle = sdk.connect(device)
        try:
            raw_text = sdk.get_device_data(handle, 'transaction', '*', '')
        finally:
            sdk.disconnect(handle)
        logs = _normalize_sdk_transactions(raw_text, device)
        transaction_row_count = _sdk_transaction_row_count(raw_text)
        checkpoint_key = str(device.get('serial_number') or device.get('id'))
        checkpoint_value = checkpoint.get(checkpoint_key)
        last_row_count = 0
        last_ts = ''
        if isinstance(checkpoint_value, dict):
            last_row_count = int(checkpoint_value.get('row_count') or 0)
            last_ts = str(checkpoint_value.get('last_event_ts') or '')
        elif checkpoint_value:
            last_ts = str(checkpoint_value)
        if 0 < last_row_count <= transaction_row_count:
            new_logs = [
                item for item in logs
                if int((item.get('raw_payload') or {}).get('sdk_row_number') or 0) > last_row_count
            ]
        else:
            new_logs = [item for item in logs if str(item['event_ts']) > last_ts]
        if not new_logs:
            checkpoint[checkpoint_key] = {
                'last_event_ts': max([str(item['event_ts']) for item in logs], default=last_ts),
                'row_count': transaction_row_count,
            }
            continue
        submit_attendance_logs(config, new_logs)
        submitted_count += len(new_logs)
        checkpoint[checkpoint_key] = {
            'last_event_ts': max(str(item['event_ts']) for item in logs),
            'row_count': transaction_row_count,
        }
    save_checkpoint(bridge_config.checkpoint_file, checkpoint)
    summary = {'status': 'ok', 'submitted_count': submitted_count}
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def zkteco_sdk_sync_loop(config: AgentConfig, bridge_config: ZktecoSdkBridgeConfig, once: bool) -> None:
    LOGGER.info(
        'ZKTeco SDK sync started: once=%s dry_run=%s dll_path=%s attendance_polling_enabled=%s',
        once,
        bridge_config.dry_run,
        bridge_config.dll_path or 'plcommpro.dll',
        bridge_config.attendance_polling_enabled,
    )
    sdk = None if bridge_config.dry_run else ZktecoPullSdk(bridge_config.dll_path, bridge_config.timeout_seconds)
    while True:
        zkteco_sdk_sync_once(config, bridge_config, sdk)
        zkteco_sdk_poll_attendance_once(config, bridge_config, sdk)
        if once:
            return
        time.sleep(bridge_config.poll_interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='HRMS biometric middleware bridge')
    parser.add_argument('--config', type=Path, help='Optional JSON config file with api_base_url and middleware_key')
    subparsers = parser.add_subparsers(dest='command')

    subparsers.add_parser('self-test', help='Start, inspect bundled SDK files, and exit')
    subparsers.add_parser('heartbeat', help='Send recurring heartbeats to HRMS')
    read_parser = subparsers.add_parser('read-card', help='Submit a card read to an enrollment session')
    read_parser.add_argument('--token', required=True, help='Enrollment token issued by HRMS')
    read_parser.add_argument('--card-id', required=True, help='Card number captured from local reader')
    read_parser.add_argument('--device-serial', help='Optional local device serial number')
    dahua_parser = subparsers.add_parser('dahua-db-poll', help='Poll Dahua access records directly from the local SQL database')
    dahua_parser.add_argument('--once', action='store_true', help='Run a single polling cycle and exit')
    zkteco_parser = subparsers.add_parser('zkteco-sdk-sync', help='Sync queued HRMS users/cards to ZKTeco C3/Pull SDK devices')
    zkteco_parser.add_argument('--once', action='store_true', help='Run a single sync cycle and exit')
    zkteco_parser.add_argument('--dry-run', action='store_true', help='Fetch and acknowledge commands without loading the SDK DLL')
    zkteco_parser.add_argument('--dll', help='Path to plcommpro.dll')
    args = parser.parse_args()
    if args.command is None:
        args.command = os.environ.get('HRMS_BRIDGE_COMMAND', 'heartbeat')
    return args


def resolve_local_config_file(explicit: Path | None) -> Path | None:
    """If --config is omitted, load hrms-bridge.local.json next to the EXE or from cwd (Windows double-click)."""
    if explicit is not None and str(explicit).strip():
        return explicit
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).resolve().parent
        candidate = exe_dir / 'hrms-bridge.local.json'
        if candidate.is_file():
            return candidate
    cwd_candidate = Path.cwd() / 'hrms-bridge.local.json'
    if cwd_candidate.is_file():
        return cwd_candidate
    return None


def load_config(config_path: Path | None) -> AgentConfig:
    if config_path:
        payload = json.loads(config_path.read_text(encoding='utf-8-sig'))
        api_base_url = str(payload.get('api_base_url') or payload.get('base_url') or '').rstrip('/')
        middleware_key = str(payload.get('middleware_key') or payload.get('api_key') or '').strip()
        if not api_base_url or not middleware_key:
            raise RuntimeError('Config file must include api_base_url/base_url and middleware_key/api_key')
        return AgentConfig(
            api_base_url=api_base_url,
            middleware_key=middleware_key,
            heartbeat_interval_seconds=int(payload.get('heartbeat_interval_seconds', 30)),
            device_ping_interval_seconds=int(payload.get('device_ping_interval_seconds', 60)),
        )
    return AgentConfig.from_env()


def main() -> None:
    configure_logging()
    args = parse_args()
    LOGGER.info('HRMS middleware bridge starting')
    config_path = resolve_local_config_file(args.config)
    LOGGER.info(
        'mode=%s config=%s frozen=%s',
        args.command,
        str(config_path) if config_path else 'environment',
        bool(getattr(sys, 'frozen', False)),
    )
    if args.command == 'self-test':
        runtime_dir = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
        sdk_tokens = ('zk', 'comm', 'rsc', 'tcp', 'dahua', 'netsdk', 'dh')
        sdk_names = sorted(
            path.name
            for path in runtime_dir.glob('*.dll')
            if any(token in path.name.lower() for token in sdk_tokens)
        )
        payload = {
            'status': 'ok',
            'runtime_dir': str(runtime_dir),
            'bundled_sdk_count': len(sdk_names),
            'bundled_sdk_files': sdk_names,
        }
        LOGGER.info('self-test result: %s', json.dumps(payload, ensure_ascii=False))
        print(json.dumps(payload, ensure_ascii=False))
        return
    config = load_config(config_path)
    if args.command == 'heartbeat':
        heartbeat_loop(config)
        return
    if args.command == 'read-card':
        submit_card_read(config, args.token, args.card_id, args.device_serial)
        return
    if args.command == 'dahua-db-poll':
        if not config_path:
            raise RuntimeError('dahua-db-poll requires --config with a dahua_db section')
        dahua_db_poll_loop(config, load_dahua_db_config(config_path), args.once)
        return
    if args.command == 'zkteco-sdk-sync':
        bridge_config = load_zkteco_sdk_config(config_path)
        if args.dll:
            bridge_config.dll_path = args.dll
        if args.dry_run:
            bridge_config.dry_run = True
        zkteco_sdk_sync_loop(config, bridge_config, args.once)
        return
    raise RuntimeError(f'Unsupported command: {args.command}')


def should_wait_on_exit() -> bool:
    wait_value = os.environ.get('HRMS_BRIDGE_WAIT_ON_EXIT', '').strip().lower()
    if wait_value in {'0', 'false', 'no', 'off'}:
        return False
    if wait_value in {'1', 'true', 'yes', 'on'}:
        return True
    return bool(getattr(sys, 'frozen', False) and sys.stdin and sys.stdin.isatty())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        configure_logging()
        LOGGER.exception('middleware bridge stopped during startup or sync')
        if should_wait_on_exit():
            input('Press Enter to close the middleware console...')
        raise
