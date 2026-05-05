from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Sequence
from uuid import UUID
from zoneinfo import ZoneInfo

from .db import Database

GEORGIA_TZ = ZoneInfo('Asia/Tbilisi')
MONEY = Decimal('0.01')


@dataclass(slots=True)
class Punch:
    log_id: int | None
    employee_id: UUID
    device_id: UUID | None
    device_user_id: str | None
    ts: datetime
    direction: str = 'unknown'
    verify_mode: str | None = None


@dataclass(slots=True)
class ResolvedShift:
    assignment_id: UUID | None
    work_date: date
    start_local: datetime
    end_local: datetime
    planned_minutes: int
    break_minutes: int
    early_grace_minutes: int
    late_grace_minutes: int


@dataclass(slots=True)
class WorkSession:
    employee_id: UUID
    work_date: date
    check_in_ts: datetime
    check_out_ts: datetime | None
    source_log_in_id: int | None
    source_log_out_id: int | None
    total_minutes: int
    night_minutes: int
    holiday_minutes: int
    overtime_minutes: int = 0
    manager_review_required: bool = False
    incomplete_reason: str | None = None
    flags: list[dict[str, str]] = field(default_factory=list)

    @property
    def is_incomplete(self) -> bool:
        return self.check_out_ts is None


@dataclass(slots=True)
class PayPolicy:
    standard_weekly_hours: Decimal = Decimal('40.00')
    overtime_multiplier: Decimal = Decimal('1.25')
    night_bonus_multiplier: Decimal = Decimal('0.00')
    holiday_multiplier: Decimal = Decimal('2.00')
    employee_pension_rate: Decimal = Decimal('0.02')
    income_tax_rate: Decimal = Decimal('0.20')


@dataclass(slots=True)
class CompensationTerms:
    base_salary: Decimal
    salary_type: str = 'monthly_fixed'
    hourly_rate_override: Decimal | None = None
    is_pension_participant: bool = True


@dataclass(slots=True)
class PayrollBreakdown:
    salary_type: str
    hourly_rate: Decimal
    regular_pay: Decimal
    overtime_pay: Decimal
    night_pay: Decimal
    holiday_pay: Decimal
    gross_pay: Decimal
    employee_pension_amount: Decimal
    income_tax_amount: Decimal
    net_pay: Decimal


@dataclass(slots=True)
class MonthlyTimesheetResult:
    employee_id: UUID
    year: int
    month: int
    total_minutes: int
    night_minutes: int
    holiday_minutes: int
    overtime_minutes: int
    incomplete_session_count: int
    sessions: list[WorkSession]
    payroll: PayrollBreakdown

    def as_export_row(self, employee_number: str, full_name: str) -> dict[str, object]:
        return {
            'employee_id': str(self.employee_id),
            'employee_number': employee_number,
            'full_name': full_name,
            'year': self.year,
            'month': self.month,
            'salary_type': self.payroll.salary_type,
            'total_hours': round(self.total_minutes / 60.0, 2),
            'night_hours': round(self.night_minutes / 60.0, 2),
            'holiday_hours': round(self.holiday_minutes / 60.0, 2),
            'overtime_hours': round(self.overtime_minutes / 60.0, 2),
            'hourly_rate': str(self.payroll.hourly_rate),
            'regular_pay': str(self.payroll.regular_pay),
            'overtime_pay': str(self.payroll.overtime_pay),
            'night_pay': str(self.payroll.night_pay),
            'holiday_pay': str(self.payroll.holiday_pay),
            'gross_pay': str(self.payroll.gross_pay),
            'employee_pension_amount': str(self.payroll.employee_pension_amount),
            'income_tax_amount': str(self.payroll.income_tax_amount),
            'net_pay': str(self.payroll.net_pay),
        }


def q2(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def orthodox_easter(year: int) -> date:
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1
    julian_easter = date(year, month, day)
    gregorian_shift = 13 if 1900 <= year <= 2099 else 0
    return julian_easter + timedelta(days=gregorian_shift)


GE_FIXED_HOLIDAYS: tuple[tuple[str, str, str, tuple[int, int]], ...] = (
    ('NEW_YEAR_1', 'New Year Holiday', 'ახალი წლის დღესასწაული', (1, 1)),
    ('NEW_YEAR_2', 'New Year Holiday', 'ახალი წლის დღესასწაული', (1, 2)),
    ('CHRISTMAS', 'Orthodox Christmas Day', 'შობა', (1, 7)),
    ('EPIPHANY', 'Orthodox Epiphany', 'ნათლისღება', (1, 19)),
    ('MOTHERS_DAY', 'Mother’s Day', 'დედის დღე', (3, 3)),
    ('WOMENS_DAY', 'International Women’s Day', 'ქალთა საერთაშორისო დღე', (3, 8)),
    ('APRIL_9', 'Independence Restoration Day', 'ეროვნული ერთიანობის, სამოქალაქო თანხმობის და სამშობლოსათვის დაღუპულთა ხსოვნის დღე', (4, 9)),
    ('VICTORY_DAY', 'Victory Day over Fascism', 'ფაშიზმზე გამარჯვების დღე', (5, 9)),
    ('ST_ANDREW', 'St. Andrew Day', 'წმინდა ანდრია პირველწოდებულის ხსენების დღე', (5, 12)),
    ('FAMILY_DAY', 'Day of Family Sanctity and Respect for Parents', 'ოჯახის სიწმინდისა და მშობლების პატივისცემის დღე', (5, 17)),
    ('INDEPENDENCE_DAY', 'Independence Day of Georgia', 'საქართველოს დამოუკიდებლობის დღე', (5, 26)),
    ('MARIAMOBA', 'Assumption of the Virgin Mary', 'მარიამობა', (8, 28)),
    ('MTSKHETOBA', 'Mtskhetoba / Svetitskhovloba', 'მცხეთობა / სვეტიცხოვლობა', (10, 14)),
    ('GIORGOBA', 'St. George’s Day', 'გიორგობა', (11, 23)),
)


def georgian_public_holidays(year: int) -> dict[date, dict[str, object]]:
    holidays: dict[date, dict[str, object]] = {}
    for code, name_en, name_ka, (month, day) in GE_FIXED_HOLIDAYS:
        holiday_date = date(year, month, day)
        holidays[holiday_date] = {
            'holiday_code': f'{code}_{year}',
            'name_en': name_en,
            'name_ka': name_ka,
            'is_movable': False,
        }

    easter = orthodox_easter(year)
    movable = (
        (easter - timedelta(days=2), 'ORTHODOX_GOOD_FRIDAY', 'Orthodox Good Friday', 'წითელი პარასკევი'),
        (easter - timedelta(days=1), 'ORTHODOX_HOLY_SATURDAY', 'Orthodox Holy Saturday', 'დიდი შაბათი'),
        (easter, 'ORTHODOX_EASTER', 'Orthodox Easter Sunday', 'აღდგომა'),
        (easter + timedelta(days=1), 'ORTHODOX_EASTER_MONDAY', 'Orthodox Easter Monday', 'აღდგომის შემდგომი დღე'),
    )
    for holiday_date, code, name_en, name_ka in movable:
        holidays[holiday_date] = {
            'holiday_code': f'{code}_{year}',
            'name_en': name_en,
            'name_ka': name_ka,
            'is_movable': True,
        }
    return holidays


async def seed_public_holidays(db: Database, year: int) -> None:
    holidays = georgian_public_holidays(year)
    await db.executemany(
        """
        INSERT INTO public_holidays_ge (holiday_date, holiday_code, name_en, name_ka, is_movable)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (holiday_date) DO UPDATE
           SET holiday_code = EXCLUDED.holiday_code,
               name_en = EXCLUDED.name_en,
               name_ka = EXCLUDED.name_ka,
               is_movable = EXCLUDED.is_movable
        """,
        [
            (
                holiday_date,
                payload['holiday_code'],
                payload['name_en'],
                payload['name_ka'],
                payload['is_movable'],
            )
            for holiday_date, payload in holidays.items()
        ],
    )


def minute_floor(delta: timedelta) -> int:
    return max(0, int(delta.total_seconds() // 60))


def overlap_minutes(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> int:
    if end <= start:
        return 0
    overlap_start = max(start, window_start)
    overlap_end = min(end, window_end)
    if overlap_end <= overlap_start:
        return 0
    return minute_floor(overlap_end - overlap_start)


def minutes_in_night_window(start: datetime, end: datetime, tz: ZoneInfo = GEORGIA_TZ) -> int:
    if end <= start:
        return 0
    cursor = start.astimezone(tz)
    end_local = end.astimezone(tz)
    total = 0
    base_day = cursor.date() - timedelta(days=1)
    final_day = end_local.date() + timedelta(days=1)
    while base_day <= final_day:
        night_start = datetime.combine(base_day, time(22, 0), tzinfo=tz)
        night_end = datetime.combine(base_day + timedelta(days=1), time(6, 0), tzinfo=tz)
        total += overlap_minutes(cursor, end_local, night_start, night_end)
        base_day += timedelta(days=1)
    return total


def minutes_on_holidays(
    start: datetime,
    end: datetime,
    holidays: Iterable[date],
    tz: ZoneInfo = GEORGIA_TZ,
) -> int:
    if end <= start:
        return 0
    start_local = start.astimezone(tz)
    end_local = end.astimezone(tz)
    total = 0
    for holiday_date in holidays:
        day_start = datetime.combine(holiday_date, time(0, 0), tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        total += overlap_minutes(start_local, end_local, day_start, day_end)
    return total


def month_date_range(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def month_analysis_window(year: int, month: int) -> tuple[date, date]:
    month_start, month_end = month_date_range(year, month)
    window_start = month_start - timedelta(days=month_start.weekday())
    window_end = month_end + timedelta(days=(6 - month_end.weekday()))
    return window_start, window_end


def split_interval_by_iso_week(start: datetime, end: datetime, tz: ZoneInfo = GEORGIA_TZ) -> list[tuple[tuple[int, int], datetime, datetime]]:
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)
    pieces: list[tuple[tuple[int, int], datetime, datetime]] = []
    cursor = local_start
    while cursor < local_end:
        iso = cursor.isocalendar()
        next_week_start_date = cursor.date() + timedelta(days=(8 - iso.weekday))
        next_week_start = datetime.combine(next_week_start_date, time(0, 0), tzinfo=tz)
        boundary = min(local_end, next_week_start)
        pieces.append(((iso.year, iso.week), cursor, boundary))
        cursor = boundary
    return pieces


def derive_hourly_rate(base_salary: Decimal, standard_weekly_hours: Decimal) -> Decimal:
    monthly_hours = (standard_weekly_hours * Decimal('52')) / Decimal('12')
    if monthly_hours <= 0:
        raise ValueError('standard_weekly_hours must be positive')
    return q2(base_salary / monthly_hours)


def resolve_work_date(local_ts: datetime, shifts_by_date: dict[date, ResolvedShift]) -> date:
    for candidate_date in (local_ts.date() - timedelta(days=1), local_ts.date()):
        shift = shifts_by_date.get(candidate_date)
        if shift is None:
            continue
        start_window = shift.start_local - timedelta(minutes=shift.early_grace_minutes)
        end_window = shift.end_local + timedelta(minutes=shift.late_grace_minutes)
        if start_window <= local_ts <= end_window:
            return candidate_date
    return local_ts.date()


def _session_from_pair(
    employee_id: UUID,
    work_date: date,
    in_punch: Punch,
    out_punch: Punch | None,
    holidays: set[date],
    tz: ZoneInfo,
    max_session_hours: int,
) -> WorkSession:
    start = in_punch.ts.astimezone(tz)
    end = out_punch.ts.astimezone(tz) if out_punch is not None else None
    flags: list[dict[str, str]] = []
    incomplete_reason = None
    manager_review_required = False

    if end is None:
        total_minutes = 0
        night_minutes = 0
        holiday_minutes = 0
        incomplete_reason = 'missing_check_out'
        manager_review_required = True
        flags.append({'flag_type': 'missing_check_out', 'severity': 'high', 'details': 'Employee did not clock out'})
    else:
        total_minutes = minute_floor(end - start)
        if total_minutes > max_session_hours * 60:
            manager_review_required = True
            flags.append(
                {
                    'flag_type': 'session_exceeds_max_hours',
                    'severity': 'high',
                    'details': f'Session exceeded {max_session_hours} hours',
                }
            )
        night_minutes = minutes_in_night_window(start, end, tz)
        holiday_minutes = minutes_on_holidays(start, end, holidays, tz)

    return WorkSession(
        employee_id=employee_id,
        work_date=work_date,
        check_in_ts=start,
        check_out_ts=end,
        source_log_in_id=in_punch.log_id,
        source_log_out_id=out_punch.log_id if out_punch else None,
        total_minutes=total_minutes,
        night_minutes=night_minutes,
        holiday_minutes=holiday_minutes,
        manager_review_required=manager_review_required,
        incomplete_reason=incomplete_reason,
        flags=flags,
    )


def pair_punches_to_sessions(
    employee_id: UUID,
    punches: Sequence[Punch],
    shifts_by_date: dict[date, ResolvedShift] | None = None,
    holidays: Iterable[date] = (),
    tz: ZoneInfo = GEORGIA_TZ,
    max_session_hours: int = 24,
) -> list[WorkSession]:
    if not punches:
        return []

    shifts_by_date = shifts_by_date or {}
    holiday_set = set(holidays)
    sessions: list[WorkSession] = []
    open_in: Punch | None = None

    def current_work_date(punch: Punch) -> date:
        return resolve_work_date(punch.ts.astimezone(tz), shifts_by_date)

    for punch in sorted(punches, key=lambda item: item.ts):
        direction = punch.direction.lower()
        work_date = current_work_date(open_in or punch)

        if direction == 'in':
            if open_in is not None:
                orphaned = _session_from_pair(employee_id, current_work_date(open_in), open_in, None, holiday_set, tz, max_session_hours)
                orphaned.flags.append(
                    {
                        'flag_type': 'duplicate_in',
                        'severity': 'medium',
                        'details': 'Consecutive IN punches detected before an OUT punch',
                    }
                )
                sessions.append(orphaned)
            open_in = punch
            continue

        if direction == 'out':
            if open_in is None:
                sessions.append(
                    WorkSession(
                        employee_id=employee_id,
                        work_date=work_date,
                        check_in_ts=punch.ts.astimezone(tz),
                        check_out_ts=None,
                        source_log_in_id=None,
                        source_log_out_id=punch.log_id,
                        total_minutes=0,
                        night_minutes=0,
                        holiday_minutes=0,
                        manager_review_required=True,
                        incomplete_reason='orphan_check_out',
                        flags=[
                            {
                                'flag_type': 'orphan_check_out',
                                'severity': 'medium',
                                'details': 'Clock-out punch has no matching clock-in',
                            }
                        ],
                    )
                )
                continue
            sessions.append(_session_from_pair(employee_id, current_work_date(open_in), open_in, punch, holiday_set, tz, max_session_hours))
            open_in = None
            continue

        if open_in is None:
            open_in = punch
        else:
            sessions.append(_session_from_pair(employee_id, current_work_date(open_in), open_in, punch, holiday_set, tz, max_session_hours))
            open_in = None

    if open_in is not None:
        sessions.append(_session_from_pair(employee_id, current_work_date(open_in), open_in, None, holiday_set, tz, max_session_hours))

    return sessions


def allocate_weekly_overtime(
    sessions: list[WorkSession],
    standard_weekly_hours: Decimal = Decimal('40.00'),
    tz: ZoneInfo = GEORGIA_TZ,
) -> list[WorkSession]:
    threshold_minutes = int((standard_weekly_hours * Decimal('60')).to_integral_value(rounding=ROUND_HALF_UP))
    weekly_totals: dict[tuple[int, int], int] = defaultdict(int)

    for session in sorted(sessions, key=lambda item: item.check_in_ts):
        session.overtime_minutes = 0
        if session.check_out_ts is None or session.total_minutes == 0:
            continue
        for week_key, segment_start, segment_end in split_interval_by_iso_week(session.check_in_ts, session.check_out_ts, tz):
            segment_minutes = minute_floor(segment_end - segment_start)
            running_before = weekly_totals[week_key]
            running_after = running_before + segment_minutes
            ot_segment = max(0, running_after - threshold_minutes) - max(0, running_before - threshold_minutes)
            weekly_totals[week_key] = running_after
            session.overtime_minutes += ot_segment
    return sessions


def summarize_sessions_for_month(
    employee_id: UUID,
    year: int,
    month: int,
    sessions: list[WorkSession],
    compensation: CompensationTerms,
    policy: PayPolicy,
) -> MonthlyTimesheetResult:
    month_sessions = [s for s in sessions if s.work_date.year == year and s.work_date.month == month]
    total_minutes = sum(session.total_minutes for session in month_sessions)
    night_minutes = sum(session.night_minutes for session in month_sessions)
    holiday_minutes = sum(session.holiday_minutes for session in month_sessions)
    overtime_minutes = sum(session.overtime_minutes for session in month_sessions)
    incomplete_session_count = sum(1 for session in month_sessions if session.is_incomplete)
    payroll = compute_payroll(
        total_minutes=total_minutes,
        overtime_minutes=overtime_minutes,
        night_minutes=night_minutes,
        holiday_minutes=holiday_minutes,
        compensation=compensation,
        policy=policy,
    )
    return MonthlyTimesheetResult(
        employee_id=employee_id,
        year=year,
        month=month,
        total_minutes=total_minutes,
        night_minutes=night_minutes,
        holiday_minutes=holiday_minutes,
        overtime_minutes=overtime_minutes,
        incomplete_session_count=incomplete_session_count,
        sessions=month_sessions,
        payroll=payroll,
    )


def compute_payroll(
    *,
    total_minutes: int,
    overtime_minutes: int,
    night_minutes: int,
    holiday_minutes: int,
    compensation: CompensationTerms,
    policy: PayPolicy,
) -> PayrollBreakdown:
    salary_type = (compensation.salary_type or 'monthly_fixed').lower()
    if salary_type not in {'monthly_fixed', 'hourly'}:
        salary_type = 'monthly_fixed'

    if salary_type == 'hourly':
        hourly_rate = compensation.hourly_rate_override or compensation.base_salary
        regular_minutes = max(0, total_minutes - overtime_minutes)
        regular_pay = q2(hourly_rate * (Decimal(regular_minutes) / Decimal(60)))
    else:
        hourly_rate = compensation.hourly_rate_override or derive_hourly_rate(
            compensation.base_salary,
            policy.standard_weekly_hours,
        )
        regular_pay = q2(compensation.base_salary)

    overtime_hours = Decimal(overtime_minutes) / Decimal(60)
    night_hours = Decimal(night_minutes) / Decimal(60)
    holiday_hours = Decimal(holiday_minutes) / Decimal(60)

    overtime_pay = q2(hourly_rate * overtime_hours * policy.overtime_multiplier)
    night_pay = q2(hourly_rate * night_hours * policy.night_bonus_multiplier)
    holiday_pay = q2(hourly_rate * holiday_hours * policy.holiday_multiplier)
    gross_pay = q2(regular_pay + overtime_pay + night_pay + holiday_pay)

    employee_pension_amount = q2(
        gross_pay * policy.employee_pension_rate if compensation.is_pension_participant else Decimal('0.00')
    )
    taxable_base = q2(gross_pay - employee_pension_amount)
    income_tax_amount = q2(taxable_base * policy.income_tax_rate)
    net_pay = q2(gross_pay - employee_pension_amount - income_tax_amount)

    return PayrollBreakdown(
        salary_type=salary_type,
        hourly_rate=q2(hourly_rate),
        regular_pay=regular_pay,
        overtime_pay=overtime_pay,
        night_pay=night_pay,
        holiday_pay=holiday_pay,
        gross_pay=gross_pay,
        employee_pension_amount=employee_pension_amount,
        income_tax_amount=income_tax_amount,
        net_pay=net_pay,
    )


async def _fetch_holidays_from_db(db: Database, start_date: date, end_date: date) -> set[date]:
    records = await db.fetch(
        """
        SELECT holiday_date
          FROM public_holidays_ge
         WHERE holiday_date BETWEEN $1 AND $2
        """,
        start_date,
        end_date,
    )
    return {record['holiday_date'] for record in records}


async def _fetch_punches_from_db(db: Database, employee_id: UUID, start_date: date, end_date: date) -> list[Punch]:
    records = await db.fetch(
        """
        SELECT id, employee_id, device_id, device_user_id, event_ts, direction::text AS direction, verify_mode
          FROM raw_attendance_logs
         WHERE employee_id = $1
           AND event_ts >= $2::date
           AND event_ts < ($3::date + INTERVAL '1 day')
         ORDER BY event_ts
        """,
        employee_id,
        start_date,
        end_date,
    )
    return [
        Punch(
            log_id=row['id'],
            employee_id=row['employee_id'],
            device_id=row['device_id'],
            device_user_id=row['device_user_id'],
            ts=row['event_ts'],
            direction=row['direction'],
            verify_mode=row['verify_mode'],
        )
        for row in records
    ]


async def _fetch_compensation_and_policy(db: Database, employee_id: UUID, month_end: date) -> tuple[CompensationTerms, PayPolicy]:
    row = await db.fetchrow(
        """
        SELECT
            ec.salary_type,
            ec.base_salary,
            ec.hourly_rate_override,
            ec.is_pension_participant,
            pp.standard_weekly_hours,
            pp.overtime_multiplier,
            pp.night_bonus_multiplier,
            pp.holiday_multiplier,
            pp.employee_pension_rate,
            pp.income_tax_rate
          FROM employee_compensation ec
          JOIN pay_policies pp ON pp.id = ec.policy_id
         WHERE ec.employee_id = $1
           AND ec.effective_from <= $2
           AND (ec.effective_to IS NULL OR ec.effective_to >= $2)
         ORDER BY ec.effective_from DESC
         LIMIT 1
        """,
        employee_id,
        month_end,
    )
    if row is None:
        raise ValueError(f'No active compensation policy for employee {employee_id}')

    compensation = CompensationTerms(
        salary_type=row['salary_type'] or 'monthly_fixed',
        base_salary=row['base_salary'],
        hourly_rate_override=row['hourly_rate_override'],
        is_pension_participant=row['is_pension_participant'],
    )
    policy = PayPolicy(
        standard_weekly_hours=row['standard_weekly_hours'],
        overtime_multiplier=row['overtime_multiplier'],
        night_bonus_multiplier=row['night_bonus_multiplier'],
        holiday_multiplier=row['holiday_multiplier'],
        employee_pension_rate=row['employee_pension_rate'],
        income_tax_rate=row['income_tax_rate'],
    )
    return compensation, policy


async def _fetch_sessions_from_db(db: Database, employee_id: UUID, start_date: date, end_date: date) -> list[WorkSession]:
    rows = await db.fetch(
        """
        SELECT id,
               employee_id,
               work_date,
               check_in_ts,
               check_out_ts,
               source_log_in_id,
               source_log_out_id,
               total_minutes,
               night_minutes,
               holiday_minutes,
               overtime_minutes,
               manager_review_required,
               incomplete_reason
          FROM attendance_work_sessions
         WHERE employee_id = $1
           AND work_date BETWEEN $2 AND $3
         ORDER BY work_date, check_in_ts
        """,
        employee_id,
        start_date,
        end_date,
    )
    return [
        WorkSession(
            employee_id=row['employee_id'],
            work_date=row['work_date'],
            check_in_ts=row['check_in_ts'],
            check_out_ts=row['check_out_ts'],
            source_log_in_id=row['source_log_in_id'],
            source_log_out_id=row['source_log_out_id'],
            total_minutes=int(row['total_minutes'] or 0),
            night_minutes=int(row['night_minutes'] or 0),
            holiday_minutes=int(row['holiday_minutes'] or 0),
            overtime_minutes=int(row['overtime_minutes'] or 0),
            manager_review_required=bool(row['manager_review_required']),
            incomplete_reason=row['incomplete_reason'],
            flags=[],
        )
        for row in rows
    ]


async def _fetch_resolved_shifts(db: Database, employee_id: UUID, start_date: date, end_date: date) -> dict[date, ResolvedShift]:
    department_id = await db.fetchval('SELECT department_id FROM employees WHERE id = $1', employee_id)
    if department_id is None:
        candidate_scope = [employee_id]
    else:
        candidate_scope = [employee_id, department_id]

    rows = await db.fetch(
        """
        SELECT
            a.id AS assignment_id,
            a.employee_id,
            a.department_id,
            a.effective_from,
            a.effective_to,
            COALESCE(a.rotation_anchor_date, a.effective_from) AS anchor_date,
            sp.pattern_type::text AS pattern_type,
            sp.cycle_length_days,
            sp.timezone,
            sp.early_check_in_grace_minutes,
            sp.late_check_out_grace_minutes,
            sps.day_index,
            sps.start_time,
            sps.planned_minutes,
            sps.break_minutes,
            sps.crosses_midnight
          FROM assigned_shifts a
          JOIN shift_patterns sp ON sp.id = a.shift_pattern_id
          JOIN shift_pattern_segments sps ON sps.shift_pattern_id = sp.id
         WHERE (
                a.employee_id = $1
                OR (a.department_id = $2 AND $2 IS NOT NULL)
               )
           AND a.effective_from <= $4
           AND (a.effective_to IS NULL OR a.effective_to >= $3)
         ORDER BY (a.employee_id IS NOT NULL) DESC, a.effective_from DESC, sps.day_index ASC
        """,
        employee_id,
        department_id,
        start_date,
        end_date,
    )
    grouped: dict[UUID, dict[str, object]] = {}
    for row in rows:
        container = grouped.setdefault(
            row['assignment_id'],
            {
                'assignment_id': row['assignment_id'],
                'employee_id': row['employee_id'],
                'department_id': row['department_id'],
                'effective_from': row['effective_from'],
                'effective_to': row['effective_to'] or end_date,
                'anchor_date': row['anchor_date'],
                'pattern_type': row['pattern_type'],
                'cycle_length_days': row['cycle_length_days'],
                'timezone': row['timezone'],
                'early_check_in_grace_minutes': row['early_check_in_grace_minutes'],
                'late_check_out_grace_minutes': row['late_check_out_grace_minutes'],
                'segments': {},
            },
        )
        container['segments'][row['day_index']] = row

    chosen: dict[date, ResolvedShift] = {}
    for assignment in grouped.values():
        tz = ZoneInfo(str(assignment['timezone']))
        current = max(start_date, assignment['effective_from'])
        final = min(end_date, assignment['effective_to'])
        while current <= final:
            if assignment['pattern_type'] == 'fixed_weekly':
                day_index = current.isoweekday()
            else:
                anchor = assignment['anchor_date']
                day_index = ((current - anchor).days % assignment['cycle_length_days']) + 1
            segment = assignment['segments'].get(day_index)
            if segment is not None and current not in chosen:
                start_local = datetime.combine(current, segment['start_time'], tzinfo=tz)
                end_local = start_local + timedelta(minutes=segment['planned_minutes'])
                chosen[current] = ResolvedShift(
                    assignment_id=assignment['assignment_id'],
                    work_date=current,
                    start_local=start_local,
                    end_local=end_local,
                    planned_minutes=segment['planned_minutes'],
                    break_minutes=segment['break_minutes'],
                    early_grace_minutes=assignment['early_check_in_grace_minutes'],
                    late_grace_minutes=assignment['late_check_out_grace_minutes'],
                )
            current += timedelta(days=1)
    return chosen


async def persist_monthly_timesheet(db: Database, result: MonthlyTimesheetResult, actor_employee_id: UUID | None = None) -> None:
    await db.execute(
        """
        INSERT INTO monthly_timesheets (
            employee_id, year, month, total_minutes, night_minutes, holiday_minutes,
            overtime_minutes, incomplete_session_count, base_salary, overtime_pay,
            night_pay, holiday_pay, gross_pay, employee_pension_amount,
            income_tax_amount, net_pay, status, approved_by_employee_id
        )
        VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10,
            $11, $12, $13, $14,
            $15, $16, 'draft', $17
        )
        ON CONFLICT (employee_id, year, month) DO UPDATE
           SET total_minutes = EXCLUDED.total_minutes,
               night_minutes = EXCLUDED.night_minutes,
               holiday_minutes = EXCLUDED.holiday_minutes,
               overtime_minutes = EXCLUDED.overtime_minutes,
               incomplete_session_count = EXCLUDED.incomplete_session_count,
               base_salary = EXCLUDED.base_salary,
               overtime_pay = EXCLUDED.overtime_pay,
               night_pay = EXCLUDED.night_pay,
               holiday_pay = EXCLUDED.holiday_pay,
               gross_pay = EXCLUDED.gross_pay,
               employee_pension_amount = EXCLUDED.employee_pension_amount,
               income_tax_amount = EXCLUDED.income_tax_amount,
               net_pay = EXCLUDED.net_pay,
               generated_at = now(),
               approved_by_employee_id = EXCLUDED.approved_by_employee_id
        """,
        result.employee_id,
        result.year,
        result.month,
        result.total_minutes,
        result.night_minutes,
        result.holiday_minutes,
        result.overtime_minutes,
        result.incomplete_session_count,
        result.payroll.gross_pay - result.payroll.overtime_pay - result.payroll.night_pay - result.payroll.holiday_pay,
        result.payroll.overtime_pay,
        result.payroll.night_pay,
        result.payroll.holiday_pay,
        result.payroll.gross_pay,
        result.payroll.employee_pension_amount,
        result.payroll.income_tax_amount,
        result.payroll.net_pay,
        actor_employee_id,
    )


async def build_monthly_timesheet_from_db(db: Database, employee_id: UUID, year: int, month: int) -> MonthlyTimesheetResult:
    month_start, month_end = month_date_range(year, month)
    analysis_start, analysis_end = month_analysis_window(year, month)
    await seed_public_holidays(db, analysis_start.year)
    if analysis_end.year != analysis_start.year:
        await seed_public_holidays(db, analysis_end.year)

    compensation, policy = await _fetch_compensation_and_policy(db, employee_id, month_end)
    sessions = await _fetch_sessions_from_db(db, employee_id, analysis_start, analysis_end)
    if not sessions:
        punches = await _fetch_punches_from_db(db, employee_id, analysis_start, analysis_end)
        holidays = await _fetch_holidays_from_db(db, analysis_start, analysis_end)
        shifts = await _fetch_resolved_shifts(db, employee_id, analysis_start, analysis_end)
        sessions = pair_punches_to_sessions(
            employee_id=employee_id,
            punches=punches,
            shifts_by_date=shifts,
            holidays=holidays,
            tz=GEORGIA_TZ,
        )
        allocate_weekly_overtime(sessions, standard_weekly_hours=policy.standard_weekly_hours, tz=GEORGIA_TZ)
    return summarize_sessions_for_month(
        employee_id=employee_id,
        year=year,
        month=month,
        sessions=sessions,
        compensation=compensation,
        policy=policy,
    )


def payroll_export_rows(results: Sequence[MonthlyTimesheetResult], employee_index: dict[UUID, tuple[str, str]]) -> list[dict[str, object]]:
    export_rows: list[dict[str, object]] = []
    for result in results:
        employee_number, full_name = employee_index[result.employee_id]
        export_rows.append(result.as_export_row(employee_number, full_name))
    return export_rows


def serialize_result(result: MonthlyTimesheetResult) -> dict[str, object]:
    payload = asdict(result)
    payload['employee_id'] = str(result.employee_id)
    payload['payroll'] = {
        key: str(value) if isinstance(value, Decimal) else value
        for key, value in payload['payroll'].items()
    }
    return payload
