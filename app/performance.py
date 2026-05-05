from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .api_support import get_db_from_request, require_actor
from .rbac import ensure_permission

PERFORMANCE_ROUTER = APIRouter(prefix='/performance', tags=['performance'])


class OkrCycleCreate(BaseModel):
    legal_entity_id: UUID
    code: str
    title: str
    year: int = Field(ge=2000)
    quarter: int = Field(ge=1, le=4)
    start_date: str
    end_date: str


class ObjectiveCreate(BaseModel):
    cycle_id: UUID
    scope: Literal['department', 'employee']
    title: str
    description: str | None = None
    department_id: UUID | None = None
    employee_id: UUID | None = None
    owner_employee_id: UUID | None = None
    weight: Decimal = Field(default=Decimal('1.00'), gt=0)


class KeyResultCreate(BaseModel):
    objective_id: UUID
    title: str
    metric_unit: str
    start_value: Decimal = Decimal('0.00')
    target_value: Decimal
    current_value: Decimal = Decimal('0.00')


class KeyResultUpdate(BaseModel):
    current_value: Decimal
    note: str | None = None


class FeedbackCycleCreate(BaseModel):
    legal_entity_id: UUID
    code: str
    title: str
    start_date: str
    end_date: str


class FeedbackEntryCreate(BaseModel):
    cycle_id: UUID
    subject_employee_id: UUID
    relation: Literal['self', 'peer', 'manager']
    overall_rating: int = Field(ge=1, le=5)
    strengths: str
    improvements: str
    is_anonymous: bool = False


def _percentage(current_value: Decimal, start_value: Decimal, target_value: Decimal) -> Decimal:
    if target_value == start_value:
        return Decimal('100.00')
    raw = ((current_value - start_value) / (target_value - start_value)) * Decimal('100')
    clamped = min(max(raw, Decimal('0')), Decimal('100'))
    return clamped.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@PERFORMANCE_ROUTER.post('/okr-cycles', status_code=201)
async def create_okr_cycle(request: Request, payload: OkrCycleCreate) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    cycle_id = await db.fetchval(
        """
        INSERT INTO okr_cycles (legal_entity_id, code, title, year, quarter, start_date, end_date)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        payload.legal_entity_id,
        payload.code,
        payload.title,
        payload.year,
        payload.quarter,
        payload.start_date,
        payload.end_date,
    )
    return {'cycle_id': str(cycle_id)}


@PERFORMANCE_ROUTER.post('/objectives', status_code=201)
async def create_objective(request: Request, payload: ObjectiveCreate) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    if payload.scope == 'department' and payload.department_id is None:
        raise HTTPException(status_code=400, detail='department_id is required for department objectives')
    if payload.scope == 'employee' and payload.employee_id is None:
        raise HTTPException(status_code=400, detail='employee_id is required for employee objectives')
    db = get_db_from_request(request)
    objective_id = await db.fetchval(
        """
        INSERT INTO okr_objectives (cycle_id, scope, department_id, employee_id, owner_employee_id, title, description, weight)
        VALUES ($1, $2::okr_scope, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        payload.cycle_id,
        payload.scope,
        payload.department_id,
        payload.employee_id,
        payload.owner_employee_id or actor.employee_id,
        payload.title,
        payload.description,
        payload.weight,
    )
    return {'objective_id': str(objective_id)}


@PERFORMANCE_ROUTER.post('/key-results', status_code=201)
async def create_key_result(request: Request, payload: KeyResultCreate) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    key_result_id = await db.fetchval(
        """
        INSERT INTO okr_key_results (objective_id, title, metric_unit, start_value, target_value, current_value)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        payload.objective_id,
        payload.title,
        payload.metric_unit,
        payload.start_value,
        payload.target_value,
        payload.current_value,
    )
    return {'key_result_id': str(key_result_id)}


@PERFORMANCE_ROUTER.post('/key-results/{key_result_id}/progress')
async def update_key_result(request: Request, key_result_id: UUID, payload: KeyResultUpdate) -> dict[str, object]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    row = await db.fetchrow(
        """
        UPDATE okr_key_results
           SET current_value = $2,
               last_check_in_note = $3,
               updated_at = now()
         WHERE id = $1
         RETURNING id, start_value, target_value, current_value
        """,
        key_result_id,
        payload.current_value,
        payload.note,
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Key result not found')
    return {
        'key_result_id': str(row['id']),
        'completion_percent': str(_percentage(row['current_value'], row['start_value'], row['target_value'])),
    }


@PERFORMANCE_ROUTER.post('/feedback-cycles', status_code=201)
async def create_feedback_cycle(request: Request, payload: FeedbackCycleCreate) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'employee.manage')
    db = get_db_from_request(request)
    cycle_id = await db.fetchval(
        """
        INSERT INTO feedback_cycles (legal_entity_id, code, title, start_date, end_date)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        payload.legal_entity_id,
        payload.code,
        payload.title,
        payload.start_date,
        payload.end_date,
    )
    return {'feedback_cycle_id': str(cycle_id)}


@PERFORMANCE_ROUTER.post('/feedback', status_code=201)
async def submit_feedback(request: Request, payload: FeedbackEntryCreate) -> dict[str, str]:
    actor = await require_actor(request)
    db = get_db_from_request(request)
    feedback_id = await db.fetchval(
        """
        INSERT INTO feedback_entries (
            cycle_id, subject_employee_id, reviewer_employee_id, relation,
            overall_rating, strengths, improvements, is_anonymous
        ) VALUES ($1, $2, $3, $4::feedback_relation, $5, $6, $7, $8)
        RETURNING id
        """,
        payload.cycle_id,
        payload.subject_employee_id,
        actor.employee_id,
        payload.relation,
        payload.overall_rating,
        payload.strengths,
        payload.improvements,
        payload.is_anonymous,
    )
    return {'feedback_id': str(feedback_id)}


@PERFORMANCE_ROUTER.get('/dashboard/{legal_entity_id}')
async def performance_dashboard(request: Request, legal_entity_id: UUID) -> dict[str, object]:
    actor = await require_actor(request)
    if actor.legal_entity_id != legal_entity_id and 'ADMIN' not in actor.role_codes:
        raise HTTPException(status_code=403, detail='Cross-entity dashboard access is not allowed')
    db = get_db_from_request(request)
    department_rows = await db.fetch(
        """
        SELECT d.id AS department_id,
               d.name_en AS department_name,
               round(avg(
                   least(
                       greatest(
                           CASE
                               WHEN okr.target_value = okr.start_value THEN 100
                               ELSE ((okr.current_value - okr.start_value) / NULLIF((okr.target_value - okr.start_value), 0)) * 100
                           END,
                           0
                       ),
                       100
                   )
               )::numeric, 2) AS completion_percent
          FROM okr_key_results okr
          JOIN okr_objectives oo ON oo.id = okr.objective_id
          JOIN okr_cycles oc ON oc.id = oo.cycle_id
          JOIN departments d ON d.id = oo.department_id
         WHERE oc.legal_entity_id = $1
         GROUP BY d.id, d.name_en
         ORDER BY d.name_en
        """,
        legal_entity_id,
    )
    employee_rows = await db.fetch(
        """
        SELECT e.id AS employee_id,
               e.first_name || ' ' || e.last_name AS employee_name,
               round(avg(
                   least(
                       greatest(
                           CASE
                               WHEN okr.target_value = okr.start_value THEN 100
                               ELSE ((okr.current_value - okr.start_value) / NULLIF((okr.target_value - okr.start_value), 0)) * 100
                           END,
                           0
                       ),
                       100
                   )
               )::numeric, 2) AS completion_percent
          FROM okr_key_results okr
          JOIN okr_objectives oo ON oo.id = okr.objective_id
          JOIN okr_cycles oc ON oc.id = oo.cycle_id
          JOIN employees e ON e.id = oo.employee_id
         WHERE oc.legal_entity_id = $1
         GROUP BY e.id, e.first_name, e.last_name
         ORDER BY employee_name
        """,
        legal_entity_id,
    )
    feedback_rows = await db.fetch(
        """
        SELECT e.id AS employee_id,
               e.first_name || ' ' || e.last_name AS employee_name,
               round(avg(fe.overall_rating)::numeric, 2) AS average_rating,
               count(*) AS response_count
          FROM feedback_entries fe
          JOIN feedback_cycles fc ON fc.id = fe.cycle_id
          JOIN employees e ON e.id = fe.subject_employee_id
         WHERE fc.legal_entity_id = $1
         GROUP BY e.id, e.first_name, e.last_name
         ORDER BY average_rating DESC NULLS LAST
        """,
        legal_entity_id,
    )
    return {
        'department_progress': [dict(row) for row in department_rows],
        'employee_progress': [dict(row) for row in employee_rows],
        'feedback_summary': [dict(row) for row in feedback_rows],
    }
