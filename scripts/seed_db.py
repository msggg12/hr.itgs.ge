from __future__ import annotations

import asyncpg


async def run_seed_if_needed(conn: asyncpg.Connection) -> None:
    """Compatibility hook kept for older entrypoints.

    Production startup must not create synthetic employees, attendance,
    devices, payroll rows, or recruitment records. The initializer now creates
    only schema, public holidays, and the bootstrap administrator.
    """
    await conn.execute('SET LOCAL search_path TO hrms, public')
