from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .api_support import get_db_from_request, require_actor
from .monitoring import mark_background_job
from .rbac import ensure_permission

ASSETS_ROUTER = APIRouter(prefix='/assets', tags=['assets-lifecycle'])


class ConditionEvidenceCreate(BaseModel):
    file_url: str
    note: str | None = None


class AssetAssignRequest(BaseModel):
    item_id: UUID
    employee_id: UUID
    assigned_at: datetime
    expected_return_at: datetime | None = None
    condition_on_issue: Literal['new', 'excellent', 'good', 'fair', 'damaged', 'retired', 'lost']
    note: str | None = None
    evidence: list[ConditionEvidenceCreate] = []


class AssetReturnRequest(BaseModel):
    returned_at: datetime
    condition_on_return: Literal['new', 'excellent', 'good', 'fair', 'damaged', 'retired', 'lost']
    note: str | None = None
    evidence: list[ConditionEvidenceCreate] = []


class ClearanceItemCompleteRequest(BaseModel):
    note: str | None = None

async def _ensure_default_clearance_template(db, legal_entity_id: UUID) -> UUID:
    template_id = await db.fetchval(
        'SELECT id FROM offboarding_clearance_templates WHERE legal_entity_id = $1 ORDER BY created_at LIMIT 1',
        legal_entity_id,
    )
    if template_id is not None:
        return template_id
    tx = await db.transaction()
    try:
        template_id = await tx.connection.fetchval(
            """
            INSERT INTO offboarding_clearance_templates (legal_entity_id, code, name_en, name_ka)
            VALUES ($1, 'DEFAULT_CLEARANCE', 'Default Clearance', 'სტანდარტული კლირენსი')
            RETURNING id
            """,
            legal_entity_id,
        )
        await tx.connection.executemany(
            """
            INSERT INTO offboarding_clearance_template_items (template_id, sort_order, item_code, label_en, label_ka, item_type)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            [
                (template_id, 1, 'ACCESS_REVOKE', 'Revoke physical and logical access', 'ფიზიკური და ლოგიკური წვდომის გაუქმება', 'security'),
                (template_id, 2, 'FINANCE_SIGNOFF', 'Finance sign-off', 'ფინანსური დადასტურება', 'finance'),
            ],
        )
        await tx.commit()
        return template_id
    except Exception:
        await tx.rollback()
        raise


async def refresh_final_payroll_hold(db, employee_id: UUID, resolved_by_employee_id: UUID | None = None) -> None:
    unresolved_count = await db.fetchval(
        """
        SELECT count(*)
          FROM offboarding_clearances oc
          JOIN offboarding_clearance_items oci ON oci.clearance_id = oc.id
         WHERE oc.employee_id = $1
           AND oc.status <> 'cleared'
           AND oci.required = true
           AND oci.completed = false
        """,
        employee_id,
    ) or 0
    if unresolved_count > 0:
        active_hold = await db.fetchval(
            'SELECT id FROM final_payroll_holds WHERE employee_id = $1 AND resolved_at IS NULL',
            employee_id,
        )
        if active_hold is None:
            await db.execute(
                """
                INSERT INTO final_payroll_holds (employee_id, hold_reason)
                VALUES ($1, $2)
                """,
                employee_id,
                f'Offboarding clearance has {unresolved_count} unresolved item(s)',
            )
        else:
            await db.execute(
                'UPDATE final_payroll_holds SET hold_reason = $2 WHERE id = $1',
                active_hold,
                f'Offboarding clearance has {unresolved_count} unresolved item(s)',
            )
        return
    await db.execute(
        """
        UPDATE offboarding_clearances
           SET status = 'cleared',
               cleared_at = now(),
               updated_at = now()
         WHERE employee_id = $1
           AND status <> 'cleared'
        """,
        employee_id,
    )
    await db.execute(
        """
        UPDATE final_payroll_holds
           SET resolved_at = now(),
               resolved_by_employee_id = $2,
               resolution_note = 'All clearance items completed'
         WHERE employee_id = $1
           AND resolved_at IS NULL
        """,
        employee_id,
        resolved_by_employee_id,
    )


async def generate_offboarding_clearance(db, employee_id: UUID, manager_employee_id: UUID | None = None) -> UUID:
    row = await db.fetchrow(
        'SELECT legal_entity_id FROM employees WHERE id = $1',
        employee_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail='Employee not found')
    legal_entity_id = row['legal_entity_id']
    template_id = await _ensure_default_clearance_template(db, legal_entity_id)
    clearance_id = await db.fetchval(
        """
        SELECT id
          FROM offboarding_clearances
         WHERE employee_id = $1
           AND status <> 'cleared'
         ORDER BY started_at DESC
         LIMIT 1
        """,
        employee_id,
    )
    if clearance_id is None:
        clearance_id = await db.fetchval(
            """
            INSERT INTO offboarding_clearances (employee_id, manager_employee_id, status)
            VALUES ($1, $2, 'open')
            RETURNING id
            """,
            employee_id,
            manager_employee_id,
        )
    template_items = await db.fetch(
        """
        SELECT id, label_en
          FROM offboarding_clearance_template_items
         WHERE template_id = $1
         ORDER BY sort_order
        """,
        template_id,
    )
    for item in template_items:
        exists = await db.fetchval(
            'SELECT 1 FROM offboarding_clearance_items WHERE clearance_id = $1 AND template_item_id = $2',
            clearance_id,
            item['id'],
        )
        if not exists:
            await db.execute(
                """
                INSERT INTO offboarding_clearance_items (clearance_id, template_item_id, item_label, required)
                VALUES ($1, $2, $3, true)
                """,
                clearance_id,
                item['id'],
                item['label_en'],
            )
    open_assets = await db.fetch(
        """
        SELECT aa.id AS asset_assignment_id, ii.asset_name, ii.asset_tag
          FROM asset_assignments aa
          JOIN inventory_items ii ON ii.id = aa.item_id
         WHERE aa.employee_id = $1
           AND aa.returned_at IS NULL
        """,
        employee_id,
    )
    for asset in open_assets:
        exists = await db.fetchval(
            'SELECT 1 FROM offboarding_clearance_items WHERE clearance_id = $1 AND asset_assignment_id = $2',
            clearance_id,
            asset['asset_assignment_id'],
        )
        if not exists:
            await db.execute(
                """
                INSERT INTO offboarding_clearance_items (clearance_id, asset_assignment_id, item_label, required)
                VALUES ($1, $2, $3, true)
                """,
                clearance_id,
                asset['asset_assignment_id'],
                f"Return asset {asset['asset_name']} ({asset['asset_tag']})",
            )
    await refresh_final_payroll_hold(db, employee_id)
    return clearance_id


async def offboarding_monitor_once(db) -> None:
    rows = await db.fetch(
        """
        SELECT id, manager_employee_id
          FROM employees
         WHERE termination_date IS NOT NULL
           AND termination_date <= current_date
           AND employment_status IN ('active', 'terminated', 'suspended')
        """
    )
    for row in rows:
        await generate_offboarding_clearance(db, row['id'], row['manager_employee_id'])
    await mark_background_job('offboarding-monitor')


async def offboarding_monitor_loop(db, sleep_seconds: int) -> None:
    while True:
        await offboarding_monitor_once(db)
        await asyncio.sleep(sleep_seconds)


@ASSETS_ROUTER.post('/assignments', status_code=201)
async def assign_asset(request: Request, payload: AssetAssignRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'assets.manage')
    db = get_db_from_request(request)
    tx = await db.transaction()
    try:
        assignment_id = await tx.connection.fetchval(
            """
            INSERT INTO asset_assignments (
                item_id, employee_id, assigned_by_employee_id, assigned_at, expected_return_at,
                condition_on_issue, note, employee_acknowledged_at
            ) VALUES ($1, $2, $3, $4, $5, $6::asset_condition, $7, now())
            RETURNING id
            """,
            payload.item_id,
            payload.employee_id,
            actor.employee_id,
            payload.assigned_at,
            payload.expected_return_at,
            payload.condition_on_issue,
            payload.note,
        )
        if payload.evidence:
            await tx.connection.executemany(
                """
                INSERT INTO asset_condition_evidence (assignment_id, evidence_phase, file_url, note, captured_by_employee_id)
                VALUES ($1, 'issue', $2, $3, $4)
                """,
                [(assignment_id, ev.file_url, ev.note, actor.employee_id) for ev in payload.evidence],
            )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    return {'assignment_id': str(assignment_id)}


@ASSETS_ROUTER.post('/assignments/{assignment_id}/return')
async def return_asset(request: Request, assignment_id: UUID, payload: AssetReturnRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'assets.manage')
    db = get_db_from_request(request)
    employee_id = await db.fetchval('SELECT employee_id FROM asset_assignments WHERE id = $1', assignment_id)
    if employee_id is None:
        raise HTTPException(status_code=404, detail='Asset assignment not found')
    tx = await db.transaction()
    try:
        await tx.connection.execute(
            """
            UPDATE asset_assignments
               SET returned_at = $2,
                   condition_on_return = $3::asset_condition,
                   note = coalesce(note, '') || CASE WHEN $4 IS NULL THEN '' ELSE E'\nReturn: ' || $4 END,
                   return_received_by_employee_id = $5,
                   updated_at = now()
             WHERE id = $1
            """,
            assignment_id,
            payload.returned_at,
            payload.condition_on_return,
            payload.note,
            actor.employee_id,
        )
        if payload.evidence:
            await tx.connection.executemany(
                """
                INSERT INTO asset_condition_evidence (assignment_id, evidence_phase, file_url, note, captured_by_employee_id)
                VALUES ($1, 'return', $2, $3, $4)
                """,
                [(assignment_id, ev.file_url, ev.note, actor.employee_id) for ev in payload.evidence],
            )
        await tx.commit()
    except Exception:
        await tx.rollback()
        raise
    await db.execute(
        """
        UPDATE offboarding_clearance_items
           SET completed = true,
               completed_at = now(),
               completed_by_employee_id = $2,
               updated_at = now()
         WHERE asset_assignment_id = $1
        """,
        assignment_id,
        actor.employee_id,
    )
    await refresh_final_payroll_hold(db, employee_id, actor.employee_id)
    return {'assignment_id': str(assignment_id), 'status': 'returned'}


@ASSETS_ROUTER.post('/employees/{employee_id}/offboarding-clearance', status_code=201)
async def create_offboarding_clearance(request: Request, employee_id: UUID) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'assets.manage')
    db = get_db_from_request(request)
    clearance_id = await generate_offboarding_clearance(db, employee_id, actor.employee_id)
    return {'clearance_id': str(clearance_id)}


@ASSETS_ROUTER.get('/employees/{employee_id}/open-assets')
async def open_assets(request: Request, employee_id: UUID) -> list[dict[str, object]]:
    actor = await require_actor(request)
    if actor.employee_id != employee_id:
        ensure_permission(actor, 'assets.read_all')
    db = get_db_from_request(request)
    rows = await db.fetch(
        """
        SELECT aa.id AS assignment_id, aa.assigned_at, aa.expected_return_at, aa.condition_on_issue,
               ii.asset_tag, ii.asset_name, ii.serial_number, ii.current_status::text AS current_status
          FROM asset_assignments aa
          JOIN inventory_items ii ON ii.id = aa.item_id
         WHERE aa.employee_id = $1
           AND aa.returned_at IS NULL
         ORDER BY aa.assigned_at DESC
        """,
        employee_id,
    )
    return [dict(row) for row in rows]


@ASSETS_ROUTER.post('/clearance-items/{item_id}/complete')
async def complete_clearance_item(request: Request, item_id: UUID, payload: ClearanceItemCompleteRequest) -> dict[str, str]:
    actor = await require_actor(request)
    ensure_permission(actor, 'assets.manage')
    db = get_db_from_request(request)
    employee_id = await db.fetchval(
        """
        SELECT oc.employee_id
          FROM offboarding_clearance_items oci
          JOIN offboarding_clearances oc ON oc.id = oci.clearance_id
         WHERE oci.id = $1
        """,
        item_id,
    )
    if employee_id is None:
        raise HTTPException(status_code=404, detail='Clearance item not found')
    await db.execute(
        """
        UPDATE offboarding_clearance_items
           SET completed = true,
               completed_at = now(),
               completed_by_employee_id = $2,
               note = $3,
               updated_at = now()
         WHERE id = $1
        """,
        item_id,
        actor.employee_id,
        payload.note,
    )
    await refresh_final_payroll_hold(db, employee_id, actor.employee_id)
    return {'status': 'completed'}
