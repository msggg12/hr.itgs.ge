from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

try:  # pragma: no cover - dependency presence varies by environment
    import asyncpg  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    asyncpg = None  # type: ignore


class DatabaseUnavailable(RuntimeError):
    pass


_current_legal_entity_id: ContextVar[str | None] = ContextVar('current_legal_entity_id', default=None)
_current_employee_id: ContextVar[str | None] = ContextVar('current_employee_id', default=None)
_current_is_hr: ContextVar[str | None] = ContextVar('current_is_hr', default=None)
_current_managed_department_ids: ContextVar[str | None] = ContextVar('current_managed_department_ids', default=None)
_current_can_read_assets_all: ContextVar[str | None] = ContextVar('current_can_read_assets_all', default=None)


def set_database_rls_context(
    *,
    legal_entity_id: UUID | str | None,
    employee_id: UUID | str | None = None,
    is_hr: bool | None = None,
    managed_department_ids: set[UUID] | list[UUID] | tuple[UUID, ...] | None = None,
    can_read_assets_all: bool | None = None,
) -> None:
    _current_legal_entity_id.set(str(legal_entity_id) if legal_entity_id else None)
    _current_employee_id.set(str(employee_id) if employee_id else None)
    _current_is_hr.set('true' if is_hr else 'false' if is_hr is not None else None)
    if managed_department_ids is None:
        _current_managed_department_ids.set(None)
    else:
        _current_managed_department_ids.set(','.join(str(dep_id) for dep_id in managed_department_ids))
    _current_can_read_assets_all.set(
        'true' if can_read_assets_all else 'false' if can_read_assets_all is not None else None
    )


async def apply_current_database_rls_context(conn: Any) -> None:
    legal_entity_id = _current_legal_entity_id.get()
    if not legal_entity_id:
        return
    await conn.execute("SELECT set_config('app.current_legal_entity_id', $1, true)", legal_entity_id)
    employee_id = _current_employee_id.get()
    if employee_id:
        await conn.execute("SELECT set_config('app.current_employee_id', $1, true)", employee_id)
    is_hr = _current_is_hr.get()
    if is_hr is not None:
        await conn.execute("SELECT set_config('app.is_hr', $1, true)", is_hr)
    managed_department_ids = _current_managed_department_ids.get()
    if managed_department_ids is not None:
        await conn.execute("SELECT set_config('app.managed_department_ids', $1, true)", managed_department_ids)
    can_read_assets_all = _current_can_read_assets_all.get()
    if can_read_assets_all is not None:
        await conn.execute("SELECT set_config('app.can_read_assets_all', $1, true)", can_read_assets_all)


@dataclass(slots=True)
class DatabaseTransaction:
    pool: Any
    connection: Any | None = None
    _tx: Any | None = None

    async def start(self) -> 'DatabaseTransaction':
        if self.pool is None:
            raise DatabaseUnavailable('Database pool is not initialized')
        self.connection = await self.pool.acquire()
        self._tx = self.connection.transaction()
        await self._tx.start()
        await apply_current_database_rls_context(self.connection)
        return self

    async def commit(self) -> None:
        if self._tx is not None:
            await self._tx.commit()
        if self.connection is not None:
            await self.pool.release(self.connection)
            self.connection = None
            self._tx = None

    async def rollback(self) -> None:
        if self._tx is not None:
            await self._tx.rollback()
        if self.connection is not None:
            await self.pool.release(self.connection)
            self.connection = None
            self._tx = None


class Database:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10, runtime_role: str | None = None) -> None:
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self.runtime_role = runtime_role.strip() if runtime_role else None
        self.pool: Any | None = None
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    async def connect(self) -> None:
        if not self.dsn:
            raise DatabaseUnavailable('DATABASE_URL is not configured')
        if asyncpg is None:
            raise DatabaseUnavailable('asyncpg is required to connect to PostgreSQL')
        async def _init_connection(conn: Any) -> None:
            if not self.runtime_role:
                return
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', self.runtime_role):
                raise DatabaseUnavailable('DATABASE_RUNTIME_ROLE must be a valid PostgreSQL identifier')
            await conn.execute(f'SET ROLE {self.runtime_role}')

        self.pool = await asyncpg.create_pool(  # type: ignore[attr-defined]
            dsn=self.dsn,
            min_size=self.min_size,
            max_size=self.max_size,
            command_timeout=60,
            server_settings={'search_path': 'hrms,public'},
            init=_init_connection,
        )
        sqlalchemy_dsn = self.dsn.replace('postgresql://', 'postgresql+asyncpg://', 1)
        self.engine = create_async_engine(sqlalchemy_dsn, future=True, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None
            self.session_factory = None
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    def acquire(self) -> Any:
        if self.pool is None:
            raise DatabaseUnavailable('Database pool is not initialized')
        return self.pool.acquire()

    async def transaction(self) -> DatabaseTransaction:
        return await DatabaseTransaction(self.pool).start()

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        if self.pool is None:
            raise DatabaseUnavailable('Database pool is not initialized')
        if _current_legal_entity_id.get():
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await apply_current_database_rls_context(conn)
                    return await conn.fetch(query, *args)
        return await self.pool.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        if self.pool is None:
            raise DatabaseUnavailable('Database pool is not initialized')
        if _current_legal_entity_id.get():
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await apply_current_database_rls_context(conn)
                    return await conn.fetchrow(query, *args)
        return await self.pool.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        if self.pool is None:
            raise DatabaseUnavailable('Database pool is not initialized')
        if _current_legal_entity_id.get():
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await apply_current_database_rls_context(conn)
                    return await conn.fetchval(query, *args)
        return await self.pool.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        if self.pool is None:
            raise DatabaseUnavailable('Database pool is not initialized')
        if _current_legal_entity_id.get():
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await apply_current_database_rls_context(conn)
                    return await conn.execute(query, *args)
        return await self.pool.execute(query, *args)

    def session(self) -> AsyncSession:
        if self.session_factory is None:
            raise DatabaseUnavailable('SQLAlchemy session factory is not initialized')
        return self.session_factory()

    async def executemany(self, query: str, args_list: list[tuple[Any, ...]]) -> None:
        if self.pool is None:
            raise DatabaseUnavailable('Database pool is not initialized')
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await apply_current_database_rls_context(conn)
                await conn.executemany(query, args_list)
