from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import Request

from .config import settings
from .db import Database


DEFAULT_FEATURE_FLAGS = {
    'attendance_enabled': True,
    'payroll_enabled': True,
    'ats_enabled': True,
    'chat_enabled': True,
    'device_management_enabled': True,
    'mobile_sync_enabled': True,
    'assets_enabled': True,
    'org_chart_enabled': True,
    'performance_enabled': True,
}


def normalize_host(raw_host: str | None) -> str:
    if not raw_host:
        return ''
    host = raw_host.split(',', 1)[0].strip().lower()
    if ':' in host and not host.startswith('['):
        host = host.rsplit(':', 1)[0]
    return host


def is_direct_host(host: str) -> bool:
    if not host or host == 'localhost':
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def subdomain_from_host(host: str) -> str | None:
    if is_direct_host(host):
        return None
    parts = host.split('.')
    if len(parts) < 3:
        return None
    return parts[0]


def _tenant_payload(row: Any, *, isolation_enabled: bool) -> dict[str, Any]:
    return {
        'id': str(row['id']),
        'legal_entity_id': str(row['legal_entity_id']),
        'host': row['host'],
        'subdomain': row['subdomain'],
        'trade_name': row['trade_name'],
        'logo_url': row['logo_url'],
        'logo_text': row['logo_text'],
        'primary_color': row['primary_color'] or '#1A2238',
        'standalone_chat_url': row['standalone_chat_url'],
        'isolation_enabled': isolation_enabled,
        'feature_flags': {
            'attendance_enabled': row['attendance_enabled'],
            'payroll_enabled': row['payroll_enabled'],
            'ats_enabled': row['ats_enabled'],
            'chat_enabled': row['chat_enabled'],
            'device_management_enabled': row['device_management_enabled'],
            'mobile_sync_enabled': row['mobile_sync_enabled'],
            'assets_enabled': row['assets_enabled'],
            'org_chart_enabled': row['org_chart_enabled'],
            'performance_enabled': row['performance_enabled'],
        },
    }


async def _resolve_default_tenant_for_direct_host(db: Database) -> dict[str, Any] | None:
    row = await db.fetchrow(
        """
        SELECT coalesce(td.id, le.id) AS id,
               le.id AS legal_entity_id,
               td.host,
               td.subdomain,
               le.trade_name,
               esc.logo_url,
               esc.logo_text,
               esc.primary_color,
               esc.standalone_chat_url,
               coalesce(ts.attendance_enabled, true) AS attendance_enabled,
               coalesce(ts.payroll_enabled, true) AS payroll_enabled,
               coalesce(ts.ats_enabled, true) AS ats_enabled,
               coalesce(ts.chat_enabled, true) AS chat_enabled,
               coalesce(ts.device_management_enabled, true) AS device_management_enabled,
               coalesce(ts.mobile_sync_enabled, true) AS mobile_sync_enabled,
               coalesce(ts.assets_enabled, true) AS assets_enabled,
               coalesce(ts.org_chart_enabled, true) AS org_chart_enabled,
               coalesce(ts.performance_enabled, true) AS performance_enabled
          FROM legal_entities le
          LEFT JOIN tenant_domains td
            ON td.legal_entity_id = le.id
           AND td.is_active = true
           AND td.is_primary = true
          LEFT JOIN entity_system_config esc ON esc.legal_entity_id = le.id
          LEFT JOIN tenant_subscriptions ts ON ts.legal_entity_id = le.id
         ORDER BY (td.id IS NULL), td.created_at ASC NULLS LAST, le.created_at ASC
         LIMIT 1
        """
    )
    if row is None:
        return None
    return _tenant_payload(row, isolation_enabled=True)


async def _resolve_forced_tenant(db: Database) -> dict[str, Any] | None:
    forced_legal_entity_id = settings.force_tenant_legal_entity_id
    if not forced_legal_entity_id:
        return None
    row = await db.fetchrow(
        """
        SELECT coalesce(td.id, le.id) AS id,
               le.id AS legal_entity_id,
               td.host,
               td.subdomain,
               le.trade_name,
               esc.logo_url,
               esc.logo_text,
               esc.primary_color,
               esc.standalone_chat_url,
               coalesce(ts.attendance_enabled, true) AS attendance_enabled,
               coalesce(ts.payroll_enabled, true) AS payroll_enabled,
               coalesce(ts.ats_enabled, true) AS ats_enabled,
               coalesce(ts.chat_enabled, true) AS chat_enabled,
               coalesce(ts.device_management_enabled, true) AS device_management_enabled,
               coalesce(ts.mobile_sync_enabled, true) AS mobile_sync_enabled,
               coalesce(ts.assets_enabled, true) AS assets_enabled,
               coalesce(ts.org_chart_enabled, true) AS org_chart_enabled,
               coalesce(ts.performance_enabled, true) AS performance_enabled
          FROM legal_entities le
          LEFT JOIN tenant_domains td
            ON td.legal_entity_id = le.id
           AND td.is_active = true
           AND td.is_primary = true
          LEFT JOIN entity_system_config esc ON esc.legal_entity_id = le.id
          LEFT JOIN tenant_subscriptions ts ON ts.legal_entity_id = le.id
         WHERE le.id = $1::uuid
         LIMIT 1
        """,
        forced_legal_entity_id,
    )
    if row is None:
        return None
    payload = _tenant_payload(row, isolation_enabled=True)
    payload['container_mode'] = settings.tenant_container_mode
    payload['tenant_label'] = settings.tenant_label
    return payload


async def resolve_request_tenant(db: Database, request: Request) -> dict[str, Any] | None:
    forced_tenant = await _resolve_forced_tenant(db)
    if forced_tenant is not None:
        return forced_tenant
    host = normalize_host(request.headers.get('x-forwarded-host') or request.headers.get('host'))
    if not host:
        return None
    if is_direct_host(host):
        return await _resolve_default_tenant_for_direct_host(db)

    subdomain = subdomain_from_host(host)
    row = await db.fetchrow(
        """
        SELECT td.id,
               td.legal_entity_id,
               td.host,
               td.subdomain,
               le.trade_name,
               esc.logo_url,
               esc.logo_text,
               esc.primary_color,
               esc.standalone_chat_url,
               coalesce(ts.attendance_enabled, true) AS attendance_enabled,
               coalesce(ts.payroll_enabled, true) AS payroll_enabled,
               coalesce(ts.ats_enabled, true) AS ats_enabled,
               coalesce(ts.chat_enabled, true) AS chat_enabled,
               coalesce(ts.device_management_enabled, true) AS device_management_enabled,
               coalesce(ts.mobile_sync_enabled, true) AS mobile_sync_enabled,
               coalesce(ts.assets_enabled, true) AS assets_enabled,
               coalesce(ts.org_chart_enabled, true) AS org_chart_enabled,
               coalesce(ts.performance_enabled, true) AS performance_enabled
          FROM tenant_domains td
          JOIN legal_entities le ON le.id = td.legal_entity_id
          LEFT JOIN entity_system_config esc ON esc.legal_entity_id = td.legal_entity_id
          LEFT JOIN tenant_subscriptions ts ON ts.legal_entity_id = td.legal_entity_id
         WHERE td.is_active = true
           AND (td.host = $1 OR ($2::text IS NOT NULL AND td.subdomain = $2))
         ORDER BY CASE WHEN td.host = $1 THEN 0 ELSE 1 END, td.is_primary DESC, td.created_at ASC
         LIMIT 1
        """,
        host,
        subdomain,
    )
    if row is None:
        return None
    return _tenant_payload(row, isolation_enabled=True)
