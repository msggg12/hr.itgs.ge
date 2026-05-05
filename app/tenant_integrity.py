from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException


async def ensure_employee_reference_tenant(
    conn: Any,
    legal_entity_id: UUID,
    *,
    department_id: UUID | None = None,
    job_role_id: UUID | None = None,
    manager_employee_id: UUID | None = None,
    pay_policy_id: UUID | None = None,
) -> None:
    checks = [
        ('department_id', 'departments', department_id),
        ('job_role_id', 'job_roles', job_role_id),
        ('manager_employee_id', 'employees', manager_employee_id),
        ('pay_policy_id', 'pay_policies', pay_policy_id),
    ]
    for field_name, table_name, value in checks:
        if value is None:
            continue
        exists = await conn.fetchval(
            f"SELECT EXISTS (SELECT 1 FROM {table_name} WHERE id = $1 AND legal_entity_id = $2)",
            value,
            legal_entity_id,
        )
        if not exists:
            raise HTTPException(status_code=422, detail=f'{field_name} does not belong to the target tenant')
