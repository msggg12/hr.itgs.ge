from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)


class LegalEntity(Base):
    __tablename__ = 'legal_entities'
    __table_args__ = {'schema': 'hrms'}

    id: Mapped[UUID] = uuid_pk()
    legal_name: Mapped[str] = mapped_column(Text)
    trade_name: Mapped[str] = mapped_column(Text)
    tax_id: Mapped[str] = mapped_column(Text, unique=True)
    timezone: Mapped[str] = mapped_column(Text, default='Asia/Tbilisi')
    currency_code: Mapped[str] = mapped_column(String(3), default='GEL')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    departments: Mapped[list['Department']] = relationship(back_populates='legal_entity')
    employees: Mapped[list['Employee']] = relationship(back_populates='legal_entity')


class Department(Base):
    __tablename__ = 'departments'
    __table_args__ = (
        UniqueConstraint('legal_entity_id', 'code', name='uq_departments_legal_entity_code'),
        {'schema': 'hrms'},
    )

    id: Mapped[UUID] = uuid_pk()
    legal_entity_id: Mapped[UUID] = mapped_column(ForeignKey('hrms.legal_entities.id', ondelete='CASCADE'))
    code: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str] = mapped_column(Text)
    name_ka: Mapped[str] = mapped_column(Text)
    manager_employee_id: Mapped[UUID | None] = mapped_column(ForeignKey('hrms.employees.id', ondelete='SET NULL'))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    legal_entity: Mapped[LegalEntity] = relationship(back_populates='departments')


class JobRole(Base):
    __tablename__ = 'job_roles'
    __table_args__ = (
        UniqueConstraint('legal_entity_id', 'code', name='uq_job_roles_legal_entity_code'),
        {'schema': 'hrms'},
    )

    id: Mapped[UUID] = uuid_pk()
    legal_entity_id: Mapped[UUID] = mapped_column(ForeignKey('hrms.legal_entities.id', ondelete='CASCADE'))
    code: Mapped[str] = mapped_column(Text)
    title_en: Mapped[str] = mapped_column(Text)
    title_ka: Mapped[str] = mapped_column(Text)
    is_managerial: Mapped[bool] = mapped_column(Boolean, default=False)


class Employee(Base):
    __tablename__ = 'employees'
    __table_args__ = (
        UniqueConstraint('legal_entity_id', 'employee_number', name='uq_employees_legal_entity_number'),
        {'schema': 'hrms'},
    )

    id: Mapped[UUID] = uuid_pk()
    legal_entity_id: Mapped[UUID] = mapped_column(ForeignKey('hrms.legal_entities.id', ondelete='CASCADE'))
    employee_number: Mapped[str] = mapped_column(Text)
    personal_number: Mapped[str | None] = mapped_column(Text)
    first_name: Mapped[str] = mapped_column(Text)
    last_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    department_id: Mapped[UUID | None] = mapped_column(ForeignKey('hrms.departments.id', ondelete='SET NULL'))
    job_role_id: Mapped[UUID | None] = mapped_column(ForeignKey('hrms.job_roles.id', ondelete='SET NULL'))
    manager_employee_id: Mapped[UUID | None] = mapped_column(ForeignKey('hrms.employees.id', ondelete='SET NULL'))
    hire_date: Mapped[date] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    employment_status: Mapped[str] = mapped_column(Text, default='active')
    default_device_user_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    legal_entity: Mapped[LegalEntity] = relationship(back_populates='employees')
    auth_identities: Mapped[list['AuthIdentity']] = relationship(back_populates='employee')


class AccessRole(Base):
    __tablename__ = 'access_roles'
    __table_args__ = {'schema': 'hrms'}

    id: Mapped[UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text, unique=True)
    name_en: Mapped[str] = mapped_column(Text)
    name_ka: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)


class EmployeeCompensation(Base):
    __tablename__ = 'employee_compensation'
    __table_args__ = {'schema': 'hrms'}

    id: Mapped[UUID] = uuid_pk()
    employee_id: Mapped[UUID] = mapped_column(ForeignKey('hrms.employees.id', ondelete='CASCADE'))
    policy_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    base_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    hourly_rate_override: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    is_pension_participant: Mapped[bool] = mapped_column(Boolean, default=True)


class DeviceRegistry(Base):
    __tablename__ = 'device_registry'
    __table_args__ = {'schema': 'hrms'}

    id: Mapped[UUID] = uuid_pk()
    legal_entity_id: Mapped[UUID] = mapped_column(ForeignKey('hrms.legal_entities.id', ondelete='CASCADE'))
    brand: Mapped[str] = mapped_column(Text)
    transport: Mapped[str] = mapped_column(Text)
    device_name: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    serial_number: Mapped[str] = mapped_column(Text, unique=True)
    host: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer)
    api_base_url: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(Text)
    password_ciphertext: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column('metadata', JSONB, default=dict)


class MattermostIntegration(Base):
    __tablename__ = 'mattermost_integrations'
    __table_args__ = {'schema': 'hrms'}

    legal_entity_id: Mapped[UUID] = mapped_column(ForeignKey('hrms.legal_entities.id', ondelete='CASCADE'), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    server_base_url: Mapped[str | None] = mapped_column(Text)
    incoming_webhook_url: Mapped[str | None] = mapped_column(Text)
    hr_webhook_url: Mapped[str | None] = mapped_column(Text)
    general_webhook_url: Mapped[str | None] = mapped_column(Text)
    it_webhook_url: Mapped[str | None] = mapped_column(Text)
    bot_access_token: Mapped[str | None] = mapped_column(Text)
    command_token: Mapped[str | None] = mapped_column(Text)
    action_secret: Mapped[str | None] = mapped_column(Text)


class PublicHoliday(Base):
    __tablename__ = 'public_holidays_ge'
    __table_args__ = {'schema': 'hrms'}

    holiday_date: Mapped[date] = mapped_column(Date, primary_key=True)
    holiday_code: Mapped[str] = mapped_column(Text, unique=True)
    name_en: Mapped[str] = mapped_column(Text)
    name_ka: Mapped[str] = mapped_column(Text)
    is_movable: Mapped[bool] = mapped_column(Boolean, default=False)


class DashboardPreference(Base):
    __tablename__ = 'employee_dashboard_preferences'
    __table_args__ = {'schema': 'hrms'}

    employee_id: Mapped[UUID] = mapped_column(ForeignKey('hrms.employees.id', ondelete='CASCADE'), primary_key=True)
    theme_preference: Mapped[str] = mapped_column(Text, default='system')
    pinned_widgets: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    layout_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    mobile_layout_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class AuthIdentity(Base):
    __tablename__ = 'auth_identities'
    __table_args__ = {'schema': 'hrms'}

    id: Mapped[UUID] = uuid_pk()
    employee_id: Mapped[UUID] = mapped_column(ForeignKey('hrms.employees.id', ondelete='CASCADE'))
    username: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    employee: Mapped[Employee] = relationship(back_populates='auth_identities')
