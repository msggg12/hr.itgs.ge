from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from .api_support import get_db_from_request, require_actor
from .config import settings
from .db import Database
from .rbac import ensure_permission

MONITORING_ROUTER = APIRouter(prefix='/monitoring', tags=['monitoring'])

HTTP_REQUESTS = Counter(
    'hrms_http_requests_total',
    'HTTP requests handled by the HRMS application',
    ['method', 'path', 'status_code'],
)
HTTP_LATENCY = Histogram(
    'hrms_http_request_duration_seconds',
    'Latency of HRMS HTTP requests',
    ['method', 'path'],
)
BACKGROUND_JOB_HEARTBEAT = Gauge(
    'hrms_background_job_last_ok_unixtime',
    'Unix timestamp of the last successful background job execution',
    ['job_name'],
)
NODE_LAST_HEARTBEAT = Gauge(
    'hrms_node_last_heartbeat_unixtime',
    'Unix timestamp of the last node heartbeat emission',
    ['node_code'],
)


async def metrics_middleware(request: Request, call_next: Callable):
    path = request.url.path
    method = request.method
    started = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - started
    HTTP_REQUESTS.labels(method=method, path=path, status_code=str(response.status_code)).inc()
    HTTP_LATENCY.labels(method=method, path=path).observe(elapsed)
    return response


def _memory_percent() -> float:
    try:
        with open('/proc/meminfo', 'r', encoding='utf-8') as handle:
            values: dict[str, int] = {}
            for line in handle:
                key, value = line.split(':', 1)
                values[key] = int(value.strip().split()[0])
        total = values.get('MemTotal', 0)
        available = values.get('MemAvailable', 0)
        if total <= 0:
            return 0.0
        used = max(total - available, 0)
        return round((used / total) * 100, 2)
    except OSError:
        return 0.0


def _cpu_percent() -> float:
    try:
        load = os.getloadavg()[0]
        cpu_count = max(os.cpu_count() or 1, 1)
        return round(min((load / cpu_count) * 100, 100.0), 2)
    except OSError:
        return 0.0


def current_node_metrics() -> dict[str, float | int | str]:
    return {
        'cpu_percent': _cpu_percent(),
        'memory_percent': _memory_percent(),
        'connectivity': 'online',
        'container_pid': os.getpid(),
    }


async def upsert_node_heartbeat(db: Database, service_name: str = 'api') -> None:
    metrics = current_node_metrics()
    node_id = await db.fetchval(
        """
        INSERT INTO deployment_nodes (node_code, node_role, base_url, region, metadata, last_heartbeat_at)
        VALUES ($1, $2, $3, $4, $5::jsonb, now())
        ON CONFLICT (node_code) DO UPDATE
           SET node_role = EXCLUDED.node_role,
               base_url = EXCLUDED.base_url,
               region = EXCLUDED.region,
               metadata = EXCLUDED.metadata,
               is_active = true,
               last_heartbeat_at = now(),
               updated_at = now()
        RETURNING id
        """,
        settings.node_code,
        settings.node_role,
        settings.public_base_url or None,
        settings.node_region,
        json.dumps(metrics),
    )
    await db.execute(
        """
        INSERT INTO service_heartbeats (node_id, service_name, last_ok_at, status, details)
        VALUES ($1, $2, now(), 'ok', $3::jsonb)
        ON CONFLICT (node_id, service_name) DO UPDATE
           SET last_ok_at = now(),
               status = 'ok',
               details = EXCLUDED.details,
               updated_at = now()
        """,
        node_id,
        service_name,
        json.dumps({'node_role': settings.node_role, **metrics}),
    )
    NODE_LAST_HEARTBEAT.labels(node_code=settings.node_code).set(time.time())


async def mark_background_job(job_name: str) -> None:
    BACKGROUND_JOB_HEARTBEAT.labels(job_name=job_name).set(time.time())


async def node_heartbeat_loop(db: Database, sleep_seconds: int) -> None:
    while True:
        await upsert_node_heartbeat(db)
        await mark_background_job('node-heartbeat')
        await asyncio.sleep(sleep_seconds)


@MONITORING_ROUTER.get('/healthz')
async def healthz(request: Request) -> dict[str, str]:
    db = get_db_from_request(request)
    await db.fetchval('SELECT 1')
    return {'status': 'ok'}


@MONITORING_ROUTER.get('/readyz')
async def readyz(request: Request) -> dict[str, str]:
    db = get_db_from_request(request)
    await db.fetchval('SELECT 1')
    return {'status': 'ready'}


@MONITORING_ROUTER.get('/metrics')
async def metrics_endpoint() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@MONITORING_ROUTER.get('/nodes')
async def monitoring_nodes(request: Request) -> list[dict[str, object]]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    rows = await db.fetch(
        """
        SELECT dn.node_code, dn.node_role, dn.base_url, dn.region, dn.last_heartbeat_at,
               sh.service_name, sh.status, sh.last_ok_at, sh.details
          FROM deployment_nodes dn
          LEFT JOIN service_heartbeats sh ON sh.node_id = dn.id
         WHERE dn.is_active = true
         ORDER BY dn.node_code, sh.service_name
        """
    )
    payload: list[dict[str, object]] = []
    for row in rows:
        payload.append(
            {
                'node_code': row['node_code'],
                'node_role': row['node_role'],
                'base_url': row['base_url'],
                'region': row['region'],
                'last_heartbeat_at': row['last_heartbeat_at'],
                'service_name': row['service_name'],
                'service_status': row['status'],
                'service_last_ok_at': row['last_ok_at'],
                'details': row['details'],
            }
        )
    return payload


@MONITORING_ROUTER.get('/deployment-map')
async def deployment_map(request: Request) -> list[dict[str, object]]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    rows = await db.fetch(
        """
        SELECT le.trade_name,
               dn.node_code,
               dn.base_url,
               dn.region,
               led.is_primary,
               led.active_since
          FROM legal_entity_deployments led
          JOIN legal_entities le ON le.id = led.legal_entity_id
          JOIN deployment_nodes dn ON dn.id = led.node_id
         ORDER BY le.trade_name, led.is_primary DESC, dn.node_code
        """
    )
    return [dict(row) for row in rows]
