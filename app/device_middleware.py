from __future__ import annotations

import asyncio
import json
import logging
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable
from urllib.parse import parse_qs
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from .db import Database

LOGGER = logging.getLogger(__name__)
GEORGIA_TZ = ZoneInfo('Asia/Tbilisi')
ZK_ROUTER = APIRouter(prefix='/devices/zk', tags=['zk-adms'])


@dataclass(slots=True)
class DeviceRecord:
    id: UUID
    brand: str
    transport: str
    device_name: str
    model: str
    serial_number: str
    host: str
    port: int
    api_base_url: str | None
    username: str | None
    password: str | None
    device_timezone: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class EmployeeSyncPayload:
    employee_id: UUID
    external_user_id: str
    employee_number: str
    first_name: str
    last_name: str
    department_name: str | None
    pin_code: str | None
    card_number: str | None

    @property
    def display_name(self) -> str:
        return f'{self.first_name} {self.last_name}'.strip()


@dataclass(slots=True)
class DeviceLog:
    device_id: UUID
    device_user_id: str
    event_ts: datetime
    direction: str
    verify_mode: str | None
    external_log_id: str | None
    raw_payload: dict[str, Any]


class DeviceDriver(ABC):
    def __init__(self, db: Database, device: DeviceRecord) -> None:
        self.db = db
        self.device = device
        self.tz = ZoneInfo(device.device_timezone)

    @abstractmethod
    async def add_user_to_device(self, payload: EmployeeSyncPayload) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_user_from_device(self, external_user_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def pull_logs(self, since: datetime | None) -> list[DeviceLog]:
        raise NotImplementedError

    async def ping(self) -> bool:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._ping_blocking)
            return True
        except OSError:
            return False

    def _ping_blocking(self) -> None:
        with socket.create_connection((self.device.host, self.device.port), timeout=5):
            return None


class ZkAdmsDriver(DeviceDriver):
    async def add_user_to_device(self, payload: EmployeeSyncPayload) -> None:
        command_text = build_zk_upsert_command(payload)
        await self.db.execute(
            """
            INSERT INTO device_command_queue (device_id, employee_id, command_type, payload)
            VALUES ($1, $2, 'upsert_user', $3::jsonb)
            """,
            self.device.id,
            payload.employee_id,
            json.dumps({'command': command_text, 'external_user_id': payload.external_user_id}),
        )

    async def delete_user_from_device(self, external_user_id: str) -> None:
        command_text = f'C:DELETE_USER:{external_user_id}:DATA DELETE USERINFO PIN={external_user_id}'
        await self.db.execute(
            """
            INSERT INTO device_command_queue (device_id, command_type, payload)
            VALUES ($1, 'delete_user', $2::jsonb)
            """,
            self.device.id,
            json.dumps({'command': command_text, 'external_user_id': external_user_id}),
        )

    async def pull_logs(self, since: datetime | None) -> list[DeviceLog]:
        rows = await self.db.fetch(
            """
            SELECT id, raw_body
              FROM device_push_batches
             WHERE device_id = $1
               AND batch_kind IN ('ATTLOG', 'OPERLOG', 'UNKNOWN')
               AND processed_at IS NULL
               AND ($2::timestamptz IS NULL OR received_at >= $2)
             ORDER BY received_at ASC
            """,
            self.device.id,
            since,
        )
        parsed_logs: list[DeviceLog] = []
        processed_ids: list[UUID] = []
        for row in rows:
            parsed_logs.extend(parse_zk_attlog_lines(self.device.id, row['raw_body'], self.tz))
            processed_ids.append(row['id'])
        if processed_ids:
            await self.db.execute(
                "UPDATE device_push_batches SET processed_at = now() WHERE id = ANY($1::uuid[])",
                processed_ids,
            )
        return parsed_logs


class DahuaCgiDriver(DeviceDriver):
    @property
    def base_url(self) -> str:
        return self.device.api_base_url or f'http://{self.device.host}:{self.device.port}'

    def _client(self) -> httpx.AsyncClient:
        auth = httpx.DigestAuth(self.device.username or '', self.device.password or '')
        return httpx.AsyncClient(base_url=self.base_url, auth=auth, timeout=20)

    async def add_user_to_device(self, payload: EmployeeSyncPayload) -> None:
        data = {
            'UserInfo[0].UserID': payload.external_user_id,
            'UserInfo[0].Name': payload.display_name,
            'UserInfo[0].UserType': 'normal',
            'UserInfo[0].Password': payload.pin_code or '',
        }
        async with self._client() as client:
            response = await client.post('/cgi-bin/accessUser.cgi?action=insertMulti', data=data)
            response.raise_for_status()
            if payload.card_number:
                card_response = await client.post(
                    '/cgi-bin/accessCard.cgi?action=insertMulti',
                    data={
                        'CardInfo[0].UserID': payload.external_user_id,
                        'CardInfo[0].CardNo': payload.card_number,
                        'CardInfo[0].CardStatus': '0',
                    },
                )
                card_response.raise_for_status()

    async def delete_user_from_device(self, external_user_id: str) -> None:
        async with self._client() as client:
            response = await client.get(
                '/cgi-bin/accessUser.cgi?action=removeMulti',
                params={'UserIDList[0]': external_user_id},
            )
            response.raise_for_status()

    async def pull_logs(self, since: datetime | None) -> list[DeviceLog]:
        since = since or datetime.now(tz=GEORGIA_TZ) - timedelta(days=1)
        logs: list[DeviceLog] = []
        async with self._client() as client:
            find_resp = await client.post(
                '/cgi-bin/recordFinder.cgi?action=find',
                data={
                    'name': 'AccessControlCardRecEx',
                    'condition.StartTime': since.astimezone(self.tz).strftime('%Y-%m-%d %H:%M:%S'),
                    'condition.EndTime': datetime.now(tz=self.tz).strftime('%Y-%m-%d %H:%M:%S'),
                },
            )
            find_resp.raise_for_status()
            token = parse_key_value_text(find_resp.text).get('token')
            if not token:
                return []
            try:
                while True:
                    next_resp = await client.get(
                        '/cgi-bin/recordFinder.cgi?action=findNext',
                        params={'token': token, 'count': 100},
                    )
                    next_resp.raise_for_status()
                    record_payload = parse_key_value_text(next_resp.text)
                    if record_payload.get('found') == '0' or record_payload.get('records') == '0':
                        break
                    records = parse_indexed_records(next_resp.text, prefix='records')
                    if not records:
                        break
                    for record in records:
                        event_ts = parse_device_datetime(record.get('Time') or record.get('CreateTime'), self.tz)
                        direction = 'unknown'
                        open_method = (record.get('OpenMethod') or '').lower()
                        if 'finger' in open_method or 'card' in open_method or 'remote' in open_method:
                            direction = 'in'
                        logs.append(
                            DeviceLog(
                                device_id=self.device.id,
                                device_user_id=str(record.get('UserID') or record.get('EmployeeNo') or record.get('CardNo') or record.get('Card') or ''),
                                event_ts=event_ts,
                                direction=direction,
                                verify_mode=record.get('OpenMethod'),
                                external_log_id=record.get('RecNo'),
                                raw_payload=record,
                            )
                        )
            finally:
                await client.get('/cgi-bin/recordFinder.cgi?action=close', params={'token': token})
        return [log for log in logs if log.device_user_id]


class SupremaBioStarDriver(DeviceDriver):
    @property
    def base_url(self) -> str:
        return self.device.api_base_url or f'https://{self.device.host}:{self.device.port}'

    async def _client(self) -> tuple[httpx.AsyncClient, dict[str, str]]:
        client = httpx.AsyncClient(base_url=self.base_url, verify=False, timeout=20)
        response = await client.post(
            '/api/login',
            json={'User': {'login_id': self.device.username, 'password': self.device.password}},
        )
        response.raise_for_status()
        body = response.json()
        token = body.get('token') or body.get('session_id') or body.get('Token')
        headers = {'x-auth-token': token} if token else {}
        return client, headers

    async def add_user_to_device(self, payload: EmployeeSyncPayload) -> None:
        client, headers = await self._client()
        try:
            response = await client.post(
                '/api/users',
                headers=headers,
                json={
                    'User': {
                        'user_id': payload.external_user_id,
                        'name': payload.display_name,
                        'department': payload.department_name or '',
                        'pin': payload.pin_code or '',
                        'access_groups': [],
                    }
                },
            )
            response.raise_for_status()
        finally:
            await client.aclose()

    async def delete_user_from_device(self, external_user_id: str) -> None:
        client, headers = await self._client()
        try:
            response = await client.delete(f'/api/users/{external_user_id}', headers=headers)
            response.raise_for_status()
        finally:
            await client.aclose()

    async def pull_logs(self, since: datetime | None) -> list[DeviceLog]:
        since = since or datetime.now(tz=GEORGIA_TZ) - timedelta(days=1)
        client, headers = await self._client()
        try:
            response = await client.post(
                '/api/events/search',
                headers=headers,
                json={
                    'Query': {
                        'limit': 1000,
                        'offset': 0,
                        'conditions': [
                            {'column': 'datetime', 'operator': '>=', 'values': [since.astimezone(self.tz).strftime('%Y-%m-%dT%H:%M:%S')]}
                        ],
                    }
                },
            )
            response.raise_for_status()
            body = response.json()
            raw_records = body.get('records') or body.get('Events') or []
            logs: list[DeviceLog] = []
            for record in raw_records:
                raw_ts = record.get('datetime') or record.get('timestamp')
                if not raw_ts:
                    continue
                event_ts = parse_device_datetime(raw_ts.replace('T', ' '), self.tz)
                logs.append(
                    DeviceLog(
                        device_id=self.device.id,
                        device_user_id=str(record.get('user_id') or record.get('user', {}).get('user_id') or ''),
                        event_ts=event_ts,
                        direction='in',
                        verify_mode=str(record.get('event_type_id') or record.get('type') or ''),
                        external_log_id=str(record.get('id') or ''),
                        raw_payload=record,
                    )
                )
            return [log for log in logs if log.device_user_id]
        finally:
            await client.aclose()


async def build_driver(db: Database, device_id: UUID) -> DeviceDriver:
    row = await db.fetchrow(
        """
        SELECT id, brand::text AS brand, transport::text AS transport, device_name, model,
               serial_number, host, port, api_base_url, username,
               password_ciphertext AS password, device_timezone, metadata
          FROM device_registry
         WHERE id = $1
        """,
        device_id,
    )
    if row is None:
        raise ValueError(f'Unknown device id: {device_id}')
    record = DeviceRecord(**dict(row))
    return build_driver_from_record(db, record)


def build_driver_from_record(db: Database, record: DeviceRecord) -> DeviceDriver:
    if record.brand == 'zk':
        return ZkAdmsDriver(db, record)
    if record.brand == 'dahua':
        return DahuaCgiDriver(db, record)
    if record.brand == 'suprema':
        return SupremaBioStarDriver(db, record)
    raise ValueError(f'Unsupported device brand: {record.brand}')


async def get_active_devices(db: Database) -> list[DeviceRecord]:
    rows = await db.fetch(
        """
        SELECT id, brand::text AS brand, transport::text AS transport, device_name, model,
               serial_number, host, port, api_base_url, username,
               password_ciphertext AS password, device_timezone, metadata
          FROM device_registry
         WHERE is_active = true
         ORDER BY device_name
        """
    )
    return [DeviceRecord(**dict(row)) for row in rows]


async def fetch_employee_sync_payload(db: Database, employee_id: UUID, device_id: UUID) -> EmployeeSyncPayload:
    row = await db.fetchrow(
        """
        WITH device_row AS (
            SELECT brand::text AS brand, transport::text AS transport
              FROM device_registry
             WHERE id = $2
        ),
        employee_row AS (
            SELECT id, employee_number, default_device_user_id, personal_number,
                   first_name, last_name, department_id
              FROM employees
             WHERE id = $1
        ),
        current_identity AS (
            SELECT device_user_id, pin_code, card_number
              FROM employee_device_identities
             WHERE device_id = $2
               AND employee_id = $1
        ),
        next_numeric_pin AS (
            SELECT (coalesce(max(device_user_id::bigint), 0) + 1)::text AS value
              FROM employee_device_identities
             WHERE device_id = $2
               AND device_user_id ~ '^[0-9]+$'
        ),
        chosen_identity AS (
            SELECT
                CASE
                    WHEN dr.brand = 'zk' AND dr.transport IN ('sdk_bridge', 'raw_socket') THEN coalesce(
                        CASE WHEN ci.device_user_id ~ '^[0-9]+$' THEN ci.device_user_id END,
                        CASE
                            WHEN e.default_device_user_id ~ '^[0-9]+$'
                             AND NOT EXISTS (
                                 SELECT 1
                                   FROM employee_device_identities other
                                  WHERE other.device_id = $2
                                    AND other.device_user_id = e.default_device_user_id
                                    AND other.employee_id <> $1
                             )
                            THEN e.default_device_user_id
                        END,
                        CASE
                            WHEN e.employee_number ~ '^[0-9]+$'
                             AND NOT EXISTS (
                                 SELECT 1
                                   FROM employee_device_identities other
                                  WHERE other.device_id = $2
                                    AND other.device_user_id = e.employee_number
                                    AND other.employee_id <> $1
                             )
                            THEN e.employee_number
                        END,
                        next_numeric_pin.value
                    )
                    ELSE COALESCE(ci.device_user_id, NULLIF(e.default_device_user_id, ''), e.employee_number)
                END AS device_user_id,
                COALESCE(
                    ci.pin_code,
                    right(regexp_replace(COALESCE(e.personal_number, e.employee_number), '\\D', '', 'g'), 4)
                ) AS pin_code,
                ci.card_number
              FROM employee_row e
              CROSS JOIN device_row dr
              LEFT JOIN current_identity ci ON true
              CROSS JOIN next_numeric_pin
        ),
        upsert_identity AS (
            INSERT INTO employee_device_identities (device_id, employee_id, device_user_id, pin_code, card_number, is_active, updated_at)
            SELECT $2, $1, device_user_id, pin_code, card_number, true, now()
              FROM chosen_identity
            ON CONFLICT (device_id, employee_id) DO UPDATE
               SET device_user_id = EXCLUDED.device_user_id,
                   pin_code = EXCLUDED.pin_code,
                   is_active = true,
                   updated_at = now()
            RETURNING employee_id, device_user_id, pin_code, card_number
        )
        SELECT
            e.id AS employee_id,
            ui.device_user_id AS external_user_id,
            e.employee_number,
            e.first_name,
            e.last_name,
            d.name_en AS department_name,
            ui.pin_code,
            ui.card_number
          FROM employees e
          JOIN upsert_identity ui ON ui.employee_id = e.id
          LEFT JOIN departments d ON d.id = e.department_id
         WHERE e.id = $1
        """,
        employee_id,
        device_id,
    )
    if row is None:
        raise ValueError(f'Employee not found: {employee_id}')
    return EmployeeSyncPayload(**dict(row))


def _queue_payload_from_sync_payload(payload: EmployeeSyncPayload, *, include_zk_command: bool = False) -> dict[str, Any]:
    command_payload: dict[str, Any] = {
        'external_user_id': payload.external_user_id,
        'employee_number': payload.employee_number,
        'first_name': payload.first_name,
        'last_name': payload.last_name,
        'department_name': payload.department_name,
        'pin_code': payload.pin_code,
        'card_number': payload.card_number,
    }
    if include_zk_command:
        command_payload['command'] = build_zk_upsert_command(payload)
    return command_payload


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


async def queue_employee_upsert_for_device(db: Database, device: DeviceRecord, employee_id: UUID) -> None:
    payload = await fetch_employee_sync_payload(db, employee_id, device.id)
    await db.execute(
        """
        INSERT INTO device_command_queue (device_id, employee_id, command_type, payload)
        VALUES ($1, $2, 'upsert_user', $3::jsonb)
        """,
        device.id,
        employee_id,
        json.dumps(_queue_payload_from_sync_payload(payload, include_zk_command=device.brand == 'zk')),
    )


async def queue_employee_delete_for_device(db: Database, device: DeviceRecord, employee_id: UUID, external_user_id: str) -> None:
    payload: dict[str, Any] = {'external_user_id': external_user_id}
    if device.brand == 'zk':
        payload['command'] = f'C:DELETE_USER:{external_user_id}:DATA DELETE USERINFO PIN={external_user_id}'
    await db.execute(
        """
        INSERT INTO device_command_queue (device_id, employee_id, command_type, payload)
        VALUES ($1, $2, 'delete_user', $3::jsonb)
        """,
        device.id,
        employee_id,
        json.dumps(payload),
    )
    await db.execute(
        """
        UPDATE employee_device_identities
           SET is_active = false,
               updated_at = now()
         WHERE device_id = $1
           AND employee_id = $2
        """,
        device.id,
        employee_id,
    )


async def fetch_employee_synced_devices(db: Database, employee_id: UUID) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        SELECT dr.id,
               dr.device_name,
               dr.brand::text AS brand,
               dr.host,
               edi.device_user_id,
               edi.card_number,
               edi.pin_code
          FROM employee_device_identities edi
          JOIN device_registry dr ON dr.id = edi.device_id
         WHERE edi.employee_id = $1
           AND edi.is_active = true
           AND dr.is_active = true
         ORDER BY dr.device_name
        """,
        employee_id,
    )
    return [
        {
            'id': str(row['id']),
            'device_name': row['device_name'],
            'brand': row['brand'],
            'host': row['host'],
            'device_user_id': row['device_user_id'],
            'card_number': row['card_number'],
            'pin_code': row['pin_code'],
        }
        for row in rows
    ]


async def prepare_employee_device_profiles(db: Database, employee_id: UUID) -> int:
    employee_entity_id = await db.fetchval('SELECT legal_entity_id FROM employees WHERE id = $1', employee_id)
    if employee_entity_id is None:
        raise ValueError(f'Employee not found: {employee_id}')
    rows = await db.fetch(
        """
        INSERT INTO employee_device_identities (device_id, employee_id, device_user_id, pin_code, card_number, is_active, updated_at)
        SELECT
            dr.id,
            e.id,
            COALESCE(NULLIF(e.default_device_user_id, ''), e.employee_number),
            right(regexp_replace(COALESCE(e.personal_number, e.employee_number), '\\D', '', 'g'), 4),
            NULL,
            true,
            now()
          FROM employees e
          JOIN device_registry dr
            ON dr.legal_entity_id = e.legal_entity_id
           AND dr.is_active = true
           AND dr.device_type IN ('biometric_terminal', 'access_control_gate', 'rfid_card_reader')
         WHERE e.id = $1
        ON CONFLICT (device_id, employee_id) DO UPDATE
           SET device_user_id = EXCLUDED.device_user_id,
               pin_code = coalesce(employee_device_identities.pin_code, EXCLUDED.pin_code),
               is_active = true,
               updated_at = now()
        RETURNING device_id
        """,
        employee_id,
    )
    return len(rows)


async def sync_employee_device_assignments(db: Database, employee_id: UUID, desired_device_ids: list[UUID]) -> dict[str, object]:
    employee_entity_id = await db.fetchval('SELECT legal_entity_id FROM employees WHERE id = $1', employee_id)
    if employee_entity_id is None:
        raise ValueError(f'Employee not found: {employee_id}')

    desired_unique_ids = list(dict.fromkeys(desired_device_ids))
    if desired_unique_ids:
        desired_rows = await db.fetch(
            """
            SELECT id, brand::text AS brand, transport::text AS transport, device_name, model,
                   serial_number, host, port, api_base_url, username,
                   password_ciphertext AS password, device_timezone, metadata
              FROM device_registry
             WHERE is_active = true
               AND legal_entity_id = $1
               AND id = ANY($2::uuid[])
            """,
            employee_entity_id,
            desired_unique_ids,
        )
    else:
        desired_rows = await db.fetch(
            """
            SELECT id, brand::text AS brand, transport::text AS transport, device_name, model,
                   serial_number, host, port, api_base_url, username,
                   password_ciphertext AS password, device_timezone, metadata
              FROM device_registry
             WHERE is_active = true
               AND legal_entity_id = $1
               AND device_type IN ('biometric_terminal', 'access_control_gate', 'rfid_card_reader')
            """,
            employee_entity_id,
        )
    desired_records = [DeviceRecord(**dict(row)) for row in desired_rows]
    desired_ids = {record.id for record in desired_records}

    current_rows = await db.fetch(
        """
        SELECT dr.id, dr.brand::text AS brand, dr.transport::text AS transport, dr.device_name, dr.model,
               dr.serial_number, dr.host, dr.port, dr.api_base_url, dr.username,
               dr.password_ciphertext AS password, dr.device_timezone, dr.metadata,
               edi.device_user_id
          FROM employee_device_identities edi
          JOIN device_registry dr ON dr.id = edi.device_id
         WHERE edi.employee_id = $1
           AND edi.is_active = true
        """,
        employee_id,
    )
    current_ids = {row['id'] for row in current_rows}
    for record in desired_records:
        await queue_employee_upsert_for_device(db, record, employee_id)
    for row in current_rows:
        if row['id'] in desired_ids:
            continue
        record = DeviceRecord(
            id=row['id'],
            brand=row['brand'],
            transport=row['transport'],
            device_name=row['device_name'],
            model=row['model'],
            serial_number=row['serial_number'],
            host=row['host'],
            port=row['port'],
            api_base_url=row['api_base_url'],
            username=row['username'],
            password=row['password'],
            device_timezone=row['device_timezone'],
            metadata=row['metadata'],
        )
        await queue_employee_delete_for_device(db, record, employee_id, row['device_user_id'])
    added_device_ids = desired_ids - current_ids
    removed_device_ids = current_ids - desired_ids

    return {
        'requested': len(desired_unique_ids),
        'queued_upserts': len(desired_records),
        'queued_deletes': len(removed_device_ids),
        'added_device_ids': [str(item) for item in added_device_ids],
        'removed_device_ids': [str(item) for item in removed_device_ids],
        'current_device_ids': [str(item) for item in desired_ids],
    }


async def add_employee_to_all_devices(db: Database, employee_id: UUID) -> None:
    employee_entity_id = await db.fetchval('SELECT legal_entity_id FROM employees WHERE id = $1', employee_id)
    if employee_entity_id is None:
        raise ValueError(f'Employee not found: {employee_id}')

    devices = await db.fetch(
        """
        SELECT id, brand::text AS brand, transport::text AS transport, device_name, model,
               serial_number, host, port, api_base_url, username,
               password_ciphertext AS password, device_timezone, metadata
          FROM device_registry
         WHERE is_active = true
           AND legal_entity_id = $1
        """,
        employee_entity_id,
    )
    for row in devices:
        record = DeviceRecord(**dict(row))
        await queue_employee_upsert_for_device(db, record, employee_id)


async def add_employee_to_selected_devices(db: Database, employee_id: UUID, device_ids: list[UUID]) -> int:
    employee_entity_id = await db.fetchval('SELECT legal_entity_id FROM employees WHERE id = $1', employee_id)
    if employee_entity_id is None:
        raise ValueError(f'Employee not found: {employee_id}')
    if not device_ids:
        await add_employee_to_all_devices(db, employee_id)
        return 0

    rows = await db.fetch(
        """
        SELECT id, brand::text AS brand, transport::text AS transport, device_name, model,
               serial_number, host, port, api_base_url, username,
               password_ciphertext AS password, device_timezone, metadata
          FROM device_registry
         WHERE is_active = true
           AND legal_entity_id = $1
           AND id = ANY($2::uuid[])
        """,
        employee_entity_id,
        device_ids,
    )
    for row in rows:
        record = DeviceRecord(**dict(row))
        await queue_employee_upsert_for_device(db, record, employee_id)
    return len(rows)


async def delete_employee_from_all_devices(db: Database, employee_id: UUID) -> None:
    rows = await db.fetch(
        """
        SELECT dr.id, dr.brand::text AS brand, dr.transport::text AS transport, dr.device_name, dr.model,
               dr.serial_number, dr.host, dr.port, dr.api_base_url, dr.username,
               dr.password_ciphertext AS password, dr.device_timezone, dr.metadata,
               edi.device_user_id
          FROM employee_device_identities edi
          JOIN device_registry dr ON dr.id = edi.device_id
         WHERE edi.employee_id = $1
           AND edi.is_active = true
        """,
        employee_id,
    )
    for row in rows:
        record = DeviceRecord(
            id=row['id'],
            brand=row['brand'],
            transport=row['transport'],
            device_name=row['device_name'],
            model=row['model'],
            serial_number=row['serial_number'],
            host=row['host'],
            port=row['port'],
            api_base_url=row['api_base_url'],
            username=row['username'],
            password=row['password'],
            device_timezone=row['device_timezone'],
            metadata=row['metadata'],
        )
        await queue_employee_delete_for_device(db, record, employee_id, row['device_user_id'])


async def device_last_log_timestamp(db: Database, device_id: UUID) -> datetime | None:
    return await db.fetchval('SELECT max(event_ts) FROM raw_attendance_logs WHERE device_id = $1', device_id)


async def upsert_device_logs(db: Database, logs: Iterable[DeviceLog]) -> int:
    rows = list(logs)
    if not rows:
        return 0
    inserted = 0
    async with db.acquire() as conn:
        async with conn.transaction():
            for log in rows:
                raw_payload = json.dumps(log.raw_payload)
                inserted_row = await conn.fetchrow(
                    """
                    WITH matched_identity AS (
                        SELECT employee_id
                          FROM employee_device_identities
                         WHERE device_id = $1
                           AND is_active = true
                           AND (
                               device_user_id = $2
                               OR card_number = $2
                               OR pin_code = $2
                               OR card_number = NULLIF($7::jsonb ->> 'CardNo', '')
                               OR card_number = NULLIF($7::jsonb ->> 'Card', '')
                               OR card_number = NULLIF($7::jsonb ->> 'card_number', '')
                           )
                         ORDER BY CASE
                             WHEN device_user_id = $2 THEN 0
                             WHEN card_number = $2 THEN 1
                             WHEN pin_code = $2 THEN 2
                             ELSE 3
                         END
                         LIMIT 1
                    )
                    INSERT INTO raw_attendance_logs (
                        device_id,
                        employee_id,
                        device_user_id,
                        event_ts,
                        direction,
                        verify_mode,
                        external_log_id,
                        raw_payload
                    )
                    VALUES (
                        $1,
                        (SELECT employee_id FROM matched_identity),
                        $2,
                        $3,
                        $4::attendance_direction,
                        $5,
                        $6,
                        $7::jsonb
                    )
                    ON CONFLICT (device_id, device_user_id, event_ts) DO UPDATE
                       SET employee_id = coalesce(raw_attendance_logs.employee_id, EXCLUDED.employee_id),
                           direction = CASE
                               WHEN raw_attendance_logs.direction = 'unknown' THEN EXCLUDED.direction
                               ELSE raw_attendance_logs.direction
                           END,
                           verify_mode = coalesce(raw_attendance_logs.verify_mode, EXCLUDED.verify_mode),
                           external_log_id = coalesce(raw_attendance_logs.external_log_id, EXCLUDED.external_log_id),
                           raw_payload = CASE
                               WHEN raw_attendance_logs.raw_payload = '{}'::jsonb THEN EXCLUDED.raw_payload
                               ELSE raw_attendance_logs.raw_payload
                           END
                    RETURNING id, employee_id, event_ts, direction::text AS direction
                    """,
                    log.device_id,
                    log.device_user_id,
                    log.event_ts,
                    normalize_direction(log.direction),
                    log.verify_mode,
                    log.external_log_id,
                    raw_payload,
                )
                if inserted_row is not None:
                    inserted += 1
                    employee_for_session = inserted_row['employee_id']
                    if employee_for_session is None:
                        continue
                    from . import main as main_attendance

                    event_ts_row = inserted_row['event_ts']
                    final_direction = await main_attendance._infer_next_attendance_direction(
                        conn, employee_for_session, event_ts_row
                    )
                    await conn.execute(
                        'UPDATE raw_attendance_logs SET direction = $1::attendance_direction WHERE id = $2',
                        final_direction,
                        inserted_row['id'],
                    )
                    await main_attendance._apply_attendance_event_to_work_session(
                        conn,
                        employee_for_session,
                        final_direction,
                        event_ts_row,
                        int(inserted_row['id']),
                    )
                    await conn.execute(
                        'UPDATE raw_attendance_logs SET processed_at = now() WHERE id = $1',
                        int(inserted_row['id']),
                    )
    return inserted


async def ingest_single_device(db: Database, device: DeviceRecord) -> int:
    driver = build_driver_from_record(db, device)
    since = await device_last_log_timestamp(db, device.id)
    logs = await driver.pull_logs(since)
    inserted = await upsert_device_logs(db, logs)
    if await driver.ping():
        await db.execute('UPDATE device_registry SET last_seen_at = now() WHERE id = $1', device.id)
    return inserted


async def ingest_logs_once(db: Database) -> dict[str, int]:
    totals: dict[str, int] = {}
    for device in await get_active_devices(db):
        try:
            if device.brand != 'zk':
                await process_non_zk_device_commands(db, device)
            totals[device.device_name] = await ingest_single_device(db, device)
        except Exception as exc:  # pragma: no cover - operational logging path
            LOGGER.exception('Device ingestion failed for %s: %s', device.device_name, exc)
            totals[device.device_name] = 0
    return totals


async def device_ingestion_loop(db: Database, sleep_seconds: int = 30) -> None:
    while True:
        await ingest_logs_once(db)
        await asyncio.sleep(sleep_seconds)


async def fetch_pending_zk_commands(db: Database, device_id: UUID) -> list[tuple[UUID, str]]:
    rows = await db.fetch(
        """
        SELECT id, payload ->> 'command' AS command
          FROM device_command_queue
         WHERE device_id = $1
           AND status IN ('queued', 'failed')
         ORDER BY created_at
         LIMIT 20
        """,
        device_id,
    )
    return [(row['id'], row['command']) for row in rows if row['command']]


async def mark_zk_commands_processing(db: Database, command_ids: list[UUID]) -> None:
    if not command_ids:
        return
    await db.execute(
        """
        UPDATE device_command_queue
           SET status = 'processing', attempt_count = attempt_count + 1, last_attempt_at = now()
         WHERE id = ANY($1::uuid[])
        """,
        command_ids,
    )


async def complete_zk_commands(db: Database, command_ids: list[UUID]) -> None:
    if not command_ids:
        return
    await db.execute(
        "UPDATE device_command_queue SET status = 'completed', updated_at = now() WHERE id = ANY($1::uuid[])",
        command_ids,
    )


async def fetch_pending_device_commands(db: Database, device_id: UUID) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        SELECT id, employee_id, command_type::text AS command_type, payload
          FROM device_command_queue
         WHERE device_id = $1
           AND status IN ('queued', 'failed')
         ORDER BY created_at
         LIMIT 20
        """,
        device_id,
    )
    return [
        {
            'id': row['id'],
            'employee_id': row['employee_id'],
            'command_type': row['command_type'],
            'payload': _json_object(row['payload']),
        }
        for row in rows
    ]


async def complete_device_command(db: Database, command_id: UUID) -> None:
    await db.execute(
        """
        UPDATE device_command_queue
           SET status = 'completed',
               last_error = NULL,
               updated_at = now()
         WHERE id = $1
        """,
        command_id,
    )


async def fail_device_command(db: Database, command_id: UUID, error_text: str) -> None:
    await db.execute(
        """
        UPDATE device_command_queue
           SET status = 'failed',
               last_error = $2,
               updated_at = now()
         WHERE id = $1
        """,
        command_id,
        error_text[:4000],
    )


def _employee_sync_payload_from_queue(command: dict[str, Any]) -> EmployeeSyncPayload:
    payload = _json_object(command.get('payload'))
    employee_id = command['employee_id']
    if employee_id is None:
        raise ValueError('Queued device command is missing employee_id')
    return EmployeeSyncPayload(
        employee_id=employee_id,
        external_user_id=str(payload.get('external_user_id') or ''),
        employee_number=str(payload.get('employee_number') or ''),
        first_name=str(payload.get('first_name') or ''),
        last_name=str(payload.get('last_name') or ''),
        department_name=payload.get('department_name'),
        pin_code=payload.get('pin_code'),
        card_number=payload.get('card_number'),
    )


async def process_non_zk_device_commands(db: Database, device: DeviceRecord) -> int:
    commands = await fetch_pending_device_commands(db, device.id)
    if not commands:
        return 0

    command_ids = [command['id'] for command in commands]
    await mark_zk_commands_processing(db, command_ids)

    driver = build_driver_from_record(db, device)
    completed = 0
    for command in commands:
        try:
            if command['command_type'] == 'upsert_user':
                await driver.add_user_to_device(_employee_sync_payload_from_queue(command))
            elif command['command_type'] == 'delete_user':
                external_user_id = str(_json_object(command.get('payload')).get('external_user_id') or '')
                if not external_user_id:
                    raise ValueError('Queued delete command is missing external_user_id')
                await driver.delete_user_from_device(external_user_id)
            else:
                raise ValueError(f"Unsupported command type: {command['command_type']}")
            await complete_device_command(db, command['id'])
            completed += 1
        except Exception as exc:  # pragma: no cover - operational path
            await fail_device_command(db, command['id'], str(exc))
    return completed


async def resolve_device_by_serial(db: Database, serial_number: str) -> DeviceRecord:
    row = await db.fetchrow(
        """
        SELECT id, brand::text AS brand, transport::text AS transport, device_name, model,
               serial_number, host, port, api_base_url, username,
               password_ciphertext AS password, device_timezone, metadata
          FROM device_registry
         WHERE serial_number = $1
           AND is_active = true
        """,
        serial_number,
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Device serial is not registered')
    return DeviceRecord(**dict(row))


@ZK_ROUTER.api_route('/iclock/cdata', methods=['GET', 'POST'])
async def zk_iclock_cdata(request: Request) -> Response:
    db: Database = request.app.state.db
    serial = request.query_params.get('SN') or request.query_params.get('sn')
    if not serial:
        raise HTTPException(status_code=400, detail='Missing SN query parameter')
    device = await resolve_device_by_serial(db, serial)

    raw_body = (await request.body()).decode('utf-8', errors='ignore')
    table = request.query_params.get('table', 'UNKNOWN').upper()
    if raw_body:
        await db.execute(
            """
            INSERT INTO device_push_batches (device_id, batch_kind, request_query, raw_body)
            VALUES ($1, $2, $3, $4)
            """,
            device.id,
            table,
            str(request.query_params),
            raw_body,
        )

    command_rows = await fetch_pending_zk_commands(db, device.id)
    command_ids = [command_id for command_id, _ in command_rows]
    commands = [command for _, command in command_rows]
    await mark_zk_commands_processing(db, command_ids)
    response_body = '\n'.join(commands)
    if command_ids:
        await complete_zk_commands(db, command_ids)
    await db.execute('UPDATE device_registry SET last_seen_at = now() WHERE id = $1', device.id)
    return PlainTextResponse(response_body or 'OK')


def build_zk_upsert_command(payload: EmployeeSyncPayload) -> str:
    safe_name = payload.display_name.replace('\t', ' ').strip()
    parts = [f'PIN={payload.external_user_id}', f'Name={safe_name}', 'Pri=0']
    if payload.pin_code:
        parts.append(f'Passwd={payload.pin_code}')
    if payload.card_number:
        parts.append(f'Card={payload.card_number}')
    body = '\t'.join(parts)
    return f'C:SYNC_USER:{payload.external_user_id}:DATA UPDATE USERINFO {body}'


def normalize_direction(value: str | None) -> str:
    normalized = (value or 'unknown').lower()
    if normalized in {'in', 'entry', 'checkin', 'check_in'}:
        return 'in'
    if normalized in {'out', 'exit', 'checkout', 'check_out'}:
        return 'out'
    return 'unknown'


def parse_device_datetime(value: str, tz: ZoneInfo) -> datetime:
    candidate = value.strip()
    for pattern in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(candidate, pattern).replace(tzinfo=tz).astimezone(GEORGIA_TZ)
        except ValueError:
            continue
    return datetime.fromisoformat(candidate).replace(tzinfo=tz).astimezone(GEORGIA_TZ)


def parse_key_value_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def parse_indexed_records(text: str, prefix: str) -> list[dict[str, str]]:
    records: dict[int, dict[str, str]] = {}
    for line in text.splitlines():
        if '=' not in line or not line.startswith(f'{prefix}['):
            continue
        left, value = line.split('=', 1)
        idx_part, field = left.split('].', 1)
        index = int(idx_part.removeprefix(f'{prefix}['))
        records.setdefault(index, {})[field] = value.strip()
    return [records[key] for key in sorted(records)]


def parse_zk_attlog_lines(device_id: UUID, raw_body: str, tz: ZoneInfo) -> list[DeviceLog]:
    logs: list[DeviceLog] = []
    for line in raw_body.splitlines():
        clean = line.strip()
        if not clean or clean.upper().startswith('OPLOG'):
            continue
        if '\t' in clean and clean.count('\t') >= 3 and '=' not in clean:
            parts = clean.split('\t')
            if len(parts) >= 4:
                device_user_id = parts[0].strip()
                event_ts = parse_device_datetime(parts[1].strip(), tz)
                verify_mode = parts[2].strip()
                direction = 'in' if parts[3].strip() in {'0', '1'} else 'unknown'
                logs.append(
                    DeviceLog(
                        device_id=device_id,
                        device_user_id=device_user_id,
                        event_ts=event_ts,
                        direction=direction,
                        verify_mode=verify_mode,
                        external_log_id=f'{device_user_id}:{parts[1].strip()}',
                        raw_payload={'raw_line': clean},
                    )
                )
                continue
        parsed = parse_qs(clean, keep_blank_values=True, separator='\t')
        if parsed:
            flat = {key: values[-1] for key, values in parsed.items()}
            raw_ts = flat.get('DateTime') or flat.get('time') or flat.get('timestamp')
            device_user_id = flat.get('PIN') or flat.get('UID') or flat.get('ID') or flat.get('UserID') or flat.get('CardNo') or flat.get('Card')
            if raw_ts and device_user_id:
                logs.append(
                    DeviceLog(
                        device_id=device_id,
                        device_user_id=device_user_id,
                        event_ts=parse_device_datetime(raw_ts, tz),
                        direction=normalize_direction(flat.get('Status')),
                        verify_mode=flat.get('VerifyCode'),
                        external_log_id=f"{device_user_id}:{raw_ts}",
                        raw_payload=flat,
                    )
                )
    return logs
