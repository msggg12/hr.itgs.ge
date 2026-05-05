from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from .api_support import get_db_from_request, require_actor
from .monitoring import mark_background_job
from .rbac import ensure_permission

ANALYTICS_ROUTER = APIRouter(prefix='/analytics', tags=['analytics'])


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


async def evaluate_burnout_risk(db, legal_entity_id: UUID, as_of: date | None = None) -> list[dict[str, object]]:
    as_of = as_of or date.today()
    analysis_start = as_of - timedelta(days=7 * 12)
    employees = await db.fetch(
        """
        SELECT id, first_name, last_name, department_id
          FROM employees
         WHERE legal_entity_id = $1
           AND employment_status = 'active'
        """,
        legal_entity_id,
    )
    alerts: list[dict[str, object]] = []
    for employee in employees:
        weekly = await db.fetch(
            """
            SELECT date_trunc('week', work_date::timestamp)::date AS week_start,
                   sum(total_minutes) AS total_minutes
              FROM attendance_work_sessions
             WHERE employee_id = $1
               AND work_date BETWEEN $2 AND $3
             GROUP BY 1
             ORDER BY 1
            """,
            employee['id'],
            analysis_start,
            as_of,
        )
        overtime_weeks = []
        for row in weekly:
            if (row['total_minutes'] or 0) > 50 * 60:
                overtime_weeks.append(row['week_start'])
        overtime_weeks = sorted(overtime_weeks)
        overtime_streak = False
        if len(overtime_weeks) >= 3:
            for a, b, c in zip(overtime_weeks, overtime_weeks[1:], overtime_weeks[2:]):
                if b == a + timedelta(days=7) and c == b + timedelta(days=7):
                    overtime_streak = True
                    break
        last_leave_end = await db.fetchval(
            """
            SELECT max(end_date)
              FROM leave_requests
             WHERE employee_id = $1
               AND status = 'approved'
            """,
            employee['id'],
        )
        no_leave_six_months = last_leave_end is None or last_leave_end < (as_of - timedelta(days=180))
        risk_score = min(100, (70 if overtime_streak else 0) + (40 if no_leave_six_months else 0))
        if risk_score >= 70:
            recommended_action = 'Schedule manager check-in and encourage leave planning.'
            await db.execute(
                """
                INSERT INTO burnout_risk_alerts (
                    employee_id, as_of_date, risk_score, weekly_overtime_streak,
                    no_leave_six_months, recommended_action
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (employee_id, as_of_date) DO UPDATE
                   SET risk_score = EXCLUDED.risk_score,
                       weekly_overtime_streak = EXCLUDED.weekly_overtime_streak,
                       no_leave_six_months = EXCLUDED.no_leave_six_months,
                       recommended_action = EXCLUDED.recommended_action,
                       resolved_at = NULL,
                       updated_at = now()
                """,
                employee['id'],
                as_of,
                risk_score,
                overtime_streak,
                no_leave_six_months,
                recommended_action,
            )
            alerts.append(
                {
                    'employee_id': employee['id'],
                    'employee_name': f"{employee['first_name']} {employee['last_name']}",
                    'risk_score': risk_score,
                    'weekly_overtime_streak': overtime_streak,
                    'no_leave_six_months': no_leave_six_months,
                }
            )
        else:
            await db.execute(
                """
                UPDATE burnout_risk_alerts
                   SET resolved_at = now(), updated_at = now()
                 WHERE employee_id = $1
                   AND resolved_at IS NULL
                """,
                employee['id'],
            )
    return alerts


async def burnout_monitor_once(db) -> None:
    entities = await db.fetch('SELECT id FROM legal_entities ORDER BY trade_name')
    for entity in entities:
        await evaluate_burnout_risk(db, entity['id'])
    await mark_background_job('burnout-monitor')


async def burnout_monitor_loop(db, sleep_seconds: int) -> None:
    while True:
        await burnout_monitor_once(db)
        await asyncio.sleep(sleep_seconds)


async def turnover_report(db, legal_entity_id: UUID, year: int, month: int) -> dict[str, object]:
    month_start, month_end = _month_bounds(year, month)
    opening_headcount = await db.fetchval(
        """
        SELECT count(*)
          FROM employees
         WHERE legal_entity_id = $1
           AND hire_date < $2
           AND (termination_date IS NULL OR termination_date >= $2)
        """,
        legal_entity_id,
        month_start,
    ) or 0
    closing_headcount = await db.fetchval(
        """
        SELECT count(*)
          FROM employees
         WHERE legal_entity_id = $1
           AND hire_date <= $2
           AND (termination_date IS NULL OR termination_date > $2)
        """,
        legal_entity_id,
        month_end,
    ) or 0
    new_hires = await db.fetchval(
        'SELECT count(*) FROM employees WHERE legal_entity_id = $1 AND hire_date BETWEEN $2 AND $3',
        legal_entity_id,
        month_start,
        month_end,
    ) or 0
    leavers = await db.fetchval(
        'SELECT count(*) FROM employees WHERE legal_entity_id = $1 AND termination_date BETWEEN $2 AND $3',
        legal_entity_id,
        month_start,
        month_end,
    ) or 0
    retained = await db.fetchval(
        """
        SELECT count(*)
          FROM employees
         WHERE legal_entity_id = $1
           AND hire_date < $2
           AND (termination_date IS NULL OR termination_date > $3)
        """,
        legal_entity_id,
        month_start,
        month_end,
    ) or 0
    retention_rate = Decimal('100.00')
    if opening_headcount:
        retention_rate = (Decimal(retained) / Decimal(opening_headcount) * Decimal('100')).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )
    reason_rows = await db.fetch(
        """
        SELECT es.reason_category, count(*) AS total_count
          FROM employee_separations es
          JOIN employees e ON e.id = es.employee_id
         WHERE e.legal_entity_id = $1
           AND es.separation_date BETWEEN $2 AND $3
         GROUP BY es.reason_category
         ORDER BY total_count DESC, es.reason_category
        """,
        legal_entity_id,
        month_start,
        month_end,
    )
    return {
        'year': year,
        'month': month,
        'opening_headcount': opening_headcount,
        'closing_headcount': closing_headcount,
        'new_hires': new_hires,
        'leavers': leavers,
        'retained_from_opening': retained,
        'retention_rate_percent': str(retention_rate),
        'reasons_for_leaving': [dict(row) for row in reason_rows],
    }


@ANALYTICS_ROUTER.get('/burnout/{legal_entity_id}')
async def burnout_snapshot(request: Request, legal_entity_id: UUID) -> dict[str, object]:
    actor = await require_actor(request)
    ensure_permission(actor, 'attendance.review')
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-entity analytics access is not allowed')
    db = get_db_from_request(request)
    alerts = await evaluate_burnout_risk(db, legal_entity_id)
    return {'alerts': alerts}


@ANALYTICS_ROUTER.get('/turnover/{legal_entity_id}/{year}/{month}')
async def turnover_snapshot(request: Request, legal_entity_id: UUID, year: int, month: int) -> dict[str, object]:
    actor = await require_actor(request)
    ensure_permission(actor, 'attendance.review')
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-entity analytics access is not allowed')
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail='month must be between 1 and 12')
    db = get_db_from_request(request)
    return await turnover_report(db, legal_entity_id, year, month)
