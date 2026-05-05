import type { CSSProperties } from 'react'
import { useMemo, useState } from 'react'

import { DndContext, DragEndEvent, DragOverlay, DragStartEvent, useDraggable, useDroppable } from '@dnd-kit/core'
import { AlertTriangle, CalendarRange, ChevronLeft, ChevronRight, Clock3, Search, Users, X } from 'lucide-react'

import { ka } from '../i18n/ka'
import type { ShiftAssignment, ShiftPattern, ShiftPlannerData } from '../types'
import { classNames, formatHours, initials } from '../utils'

type ShiftPlannerProps = {
  data: ShiftPlannerData | null
  busy: boolean
  search: string
  onSearchChange: (value: string) => void
  onPreviousWeek: () => void
  onNextWeek: () => void
  onAssign: (employeeId: string, shiftPatternId: string, shiftDate: string) => Promise<void>
  onClear: (employeeId: string, shiftDate: string) => Promise<void>
  onPageChange: (page: number) => void
}

type WeekGroup = {
  key: string
  title: string
  days: Array<{ date: string; label: string; day_index: number }>
}

function weekBucketKey(shiftDate: string): string {
  const value = new Date(`${shiftDate}T00:00:00`)
  if (Number.isNaN(value.getTime())) {
    return shiftDate
  }
  value.setDate(value.getDate() - ((value.getDay() + 6) % 7))
  return value.toISOString().slice(0, 10)
}

function shortDate(value: string): string {
  return new Intl.DateTimeFormat('ka-GE', {
    day: '2-digit',
    month: 'short'
  }).format(new Date(`${value}T00:00:00`))
}

function weekTitle(days: Array<{ date: string }>): string {
  if (!days.length) {
    return '-'
  }
  const start = shortDate(days[0].date)
  const end = shortDate(days[days.length - 1].date)
  return `${start} - ${end}`
}

function weekGridStyle(dayCount: number): CSSProperties {
  return {
    gridTemplateColumns: `220px repeat(${Math.max(dayCount, 1)}, minmax(88px, 1fr))`
  }
}

function PatternPreview(props: { pattern: ShiftPattern; dragging?: boolean }) {
  const firstSegment = props.pattern.segments?.[0]

  return (
    <div
      className={classNames(
        'rounded-lg border border-slate-200 bg-white px-4 py-3 transition',
        props.dragging && 'opacity-70'
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">{props.pattern.code}</p>
          <h3 className="mt-1 truncate text-sm font-semibold text-slate-950">{props.pattern.name}</h3>
          <p className="mt-1 text-xs text-slate-500">
            {firstSegment ? `${firstSegment.start_time} • ${formatHours(firstSegment.planned_minutes)}` : '-'}
          </p>
        </div>
        <Clock3 className="h-4 w-4 shrink-0 text-slate-400" />
      </div>
    </div>
  )
}

function PatternCard(props: { pattern: ShiftPattern; dragDisabled?: boolean }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `pattern-${props.pattern.id}`,
    data: { patternId: props.pattern.id, pattern: props.pattern },
    disabled: props.dragDisabled
  })

  const style: CSSProperties | undefined = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
    : undefined

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners} className="min-w-[220px]">
      <PatternPreview pattern={props.pattern} dragging={isDragging} />
    </div>
  )
}

function ShiftSlot(props: {
  employeeId: string
  shiftDate: string
  assignment: ShiftAssignment | undefined
  overloaded: boolean
  canEdit: boolean
  onClear: (employeeId: string, shiftDate: string) => void
}) {
  const { isOver, setNodeRef } = useDroppable({
    id: `slot-${props.employeeId}-${props.shiftDate}`,
    data: { employeeId: props.employeeId, shiftDate: props.shiftDate },
    disabled: !props.canEdit
  })

  return (
    <div
      ref={setNodeRef}
      className={classNames(
        'min-h-[78px] rounded-lg border p-2.5 transition',
        isOver ? 'border-slate-500 bg-slate-50' : 'border-slate-200 bg-white',
        props.overloaded && 'border-rose-200 bg-rose-50/60'
      )}
    >
      {props.assignment ? (
        <div className="flex h-full flex-col justify-between">
          <div>
            <div className="flex items-center justify-between gap-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                {props.assignment.pattern_code}
              </p>
              {props.overloaded ? <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-semibold text-rose-700">40h+</span> : null}
            </div>
            <p className="mt-1 text-xs font-semibold text-slate-950">{props.assignment.start_time}</p>
            <p className="mt-0.5 text-[11px] text-slate-500">{formatHours(props.assignment.planned_minutes)}</p>
          </div>
          {props.canEdit ? (
            <button
              type="button"
              className="mt-2 inline-flex items-center gap-1 text-[11px] font-semibold text-rose-700"
              onClick={() => props.onClear(props.employeeId, props.shiftDate)}
            >
              <X className="h-3 w-3" />
              {ka.clearShift}
            </button>
          ) : null}
        </div>
      ) : (
        <div className="flex h-full items-center justify-center rounded-md border border-dashed border-slate-200 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          {props.canEdit ? 'Drop' : '—'}
        </div>
      )}
    </div>
  )
}

export function ShiftPlanner(props: ShiftPlannerProps) {
  const [activePattern, setActivePattern] = useState<ShiftPattern | null>(null)

  const assignments = useMemo(() => {
    const map = new Map<string, ShiftAssignment>()
    for (const assignment of props.data?.assignments ?? []) {
      map.set(`${assignment.employee_id}-${assignment.shift_date}`, assignment)
    }
    return map
  }, [props.data])

  const dayCoverage = useMemo(() => {
    const coverage = new Map<string, number>()
    for (const assignment of props.data?.assignments ?? []) {
      coverage.set(assignment.shift_date, (coverage.get(assignment.shift_date) ?? 0) + 1)
    }
    return coverage
  }, [props.data])

  const weekGroups = useMemo<WeekGroup[]>(() => {
    const groups = new Map<string, Array<{ date: string; label: string; day_index: number }>>()
    for (const day of props.data?.days ?? []) {
      const key = weekBucketKey(day.date)
      groups.set(key, [...(groups.get(key) ?? []), day])
    }
    return Array.from(groups.entries())
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, days]) => ({
        key,
        title: weekTitle(days),
        days
      }))
  }, [props.data])

  const totalPlannedMinutes = useMemo(
    () => (props.data?.assignments ?? []).reduce((sum, assignment) => sum + assignment.planned_minutes, 0),
    [props.data]
  )

  const overloadedCount = useMemo(
    () =>
      (props.data?.employees ?? []).filter((employee) =>
        Object.values(employee.weekly_minutes_map ?? {}).some((minutes) => minutes > 2400)
      ).length,
    [props.data]
  )

  function handleDragStart(event: DragStartEvent) {
    setActivePattern((event.active.data.current?.pattern as ShiftPattern | null) ?? null)
  }

  async function handleDragEnd(event: DragEndEvent) {
    const patternId = event.active.data.current?.patternId as string | undefined
    const employeeId = event.over?.data.current?.employeeId as string | undefined
    const shiftDate = event.over?.data.current?.shiftDate as string | undefined
    setActivePattern(null)
    if (!patternId || !employeeId || !shiftDate) {
      return
    }
    await props.onAssign(employeeId, patternId, shiftDate)
  }

  return (
    <article className="panel-card p-4 sm:p-5">
      <div className="mb-4 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <p className="section-kicker">Shift Roster</p>
          <h2 className="section-title">{ka.shiftPlanner}</h2>
          <p className="mt-1 text-sm text-slate-500">Weekly sections keep the month readable on one screen while preserving drag and drop planning.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className="input-shell pl-11"
              value={props.search}
              onChange={(event) => props.onSearchChange(event.target.value)}
              placeholder={ka.search}
            />
          </div>
          <button type="button" className="muted-btn px-3 py-3" onClick={props.onPreviousWeek}>
            <ChevronLeft className="h-4 w-4" />
          </button>
          <div className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-700">
            <CalendarRange className="h-4 w-4 text-slate-500" />
            {props.data?.calendar_title ?? '-'}
          </div>
          <button type="button" className="muted-btn px-3 py-3" onClick={props.onNextWeek}>
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <Users className="h-4 w-4 text-slate-500" />
            Planned employees
          </div>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{props.data?.employees?.length ?? 0}</p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <Clock3 className="h-4 w-4 text-slate-500" />
            Planned hours
          </div>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{formatHours(totalPlannedMinutes)}</p>
        </div>
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-rose-700">
            <AlertTriangle className="h-4 w-4" />
            Over 40h / week
          </div>
          <p className="mt-2 text-2xl font-semibold text-rose-900">{overloadedCount}</p>
        </div>
      </div>

      <DndContext onDragStart={handleDragStart} onDragEnd={(event) => void handleDragEnd(event)}>
        <div className="mb-5 overflow-x-auto">
          <div className="flex gap-3 pb-1">
            {(props.data?.patterns ?? []).map((pattern) => (
              <PatternCard
                key={pattern.id}
                pattern={pattern}
                dragDisabled={props.data?.user_can_edit_shifts === false}
              />
            ))}
            {!props.data?.patterns?.length ? (
              <div className="rounded-lg border border-dashed border-slate-200 px-6 py-10 text-center text-sm text-slate-500">
                {ka.noPatterns}
              </div>
            ) : null}
          </div>
        </div>

        <div className="space-y-5">
          {weekGroups.map((week) => {
            const tableStyle = weekGridStyle(week.days.length)
            return (
              <section key={week.key} className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900">{week.title}</h3>
                    <p className="mt-1 text-xs text-slate-500">Drag a shift pattern into any day cell.</p>
                  </div>
                  <span className="subtle-badge">{week.days.length} days</span>
                </div>

                <div className="overflow-x-auto">
                  <div className="space-y-2" style={{ minWidth: 220 + week.days.length * 88 }}>
                    <div className="grid gap-2" style={tableStyle}>
                      <div className="rounded-lg bg-slate-100 px-4 py-3 text-sm font-semibold text-slate-600">{ka.employees}</div>
                      {week.days.map((day) => (
                        <div key={day.date} className="rounded-lg bg-slate-100 px-2 py-3 text-center">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{day.label}</p>
                          <p className="mt-1 text-xs font-semibold text-slate-900">{shortDate(day.date)}</p>
                          <p className="mt-1 text-[10px] text-slate-500">{dayCoverage.get(day.date) ?? 0}</p>
                        </div>
                      ))}
                    </div>

                    {(props.data?.employees ?? []).map((employee) => {
                      const weekMinutes = employee.weekly_minutes_map?.[week.key] ?? 0
                      const overloaded = weekMinutes > 2400
                      const canEdit = employee.can_edit !== false && props.data?.user_can_edit_shifts !== false

                      return (
                        <div key={`${week.key}-${employee.id}`} className="grid gap-2" style={tableStyle}>
                          <div className={classNames('rounded-lg border bg-white px-4 py-3', overloaded ? 'border-rose-200' : 'border-slate-200')}>
                            <div className="flex items-center gap-3">
                              <div className={classNames('flex h-10 w-10 items-center justify-center rounded-full text-xs font-bold text-white', overloaded ? 'bg-rose-700' : 'bg-slate-900')}>
                                {initials(employee.first_name, employee.last_name)}
                              </div>
                              <div className="min-w-0">
                                <p className="truncate text-sm font-semibold text-slate-950">
                                  {employee.first_name} {employee.last_name}
                                </p>
                                <p className="truncate text-[11px] text-slate-500">{employee.job_title ?? employee.department_name ?? '-'}</p>
                              </div>
                            </div>
                            <div className="mt-3 flex items-center justify-between gap-2 text-[11px] text-slate-500">
                              <span>Week load</span>
                              <span className={classNames('font-semibold', overloaded ? 'text-rose-700' : 'text-slate-900')}>
                                {formatHours(weekMinutes)}
                              </span>
                            </div>
                          </div>

                          {week.days.map((day) => (
                            <ShiftSlot
                              key={`${employee.id}-${day.date}`}
                              employeeId={employee.id}
                              shiftDate={day.date}
                              assignment={assignments.get(`${employee.id}-${day.date}`)}
                              overloaded={overloaded}
                              canEdit={canEdit}
                              onClear={(employeeId, shiftDate) => void props.onClear(employeeId, shiftDate)}
                            />
                          ))}
                        </div>
                      )
                    })}
                  </div>
                </div>
              </section>
            )
          })}
        </div>

        <DragOverlay>
          {activePattern ? (
            <div className="w-[220px]">
              <PatternPreview pattern={activePattern} dragging />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>

          {!props.data?.employees?.length && !props.busy ? (
        <div className="mt-4 rounded-lg border border-dashed border-slate-200 px-6 py-12 text-center text-sm text-slate-500">
          {ka.noAssignments}
        </div>
      ) : null}

      <div className="mt-5 flex items-center justify-end gap-3">
        <span className="text-sm text-slate-500">
          {ka.page} {props.data?.page ?? 1} / {props.data?.page_count ?? 1}
        </span>
        <button
          type="button"
          className="muted-btn"
          onClick={() => props.onPageChange(Math.max((props.data?.page ?? 1) - 1, 1))}
        >
          {ka.previous}
        </button>
        <button
          type="button"
          className="muted-btn"
          onClick={() => props.onPageChange(Math.min((props.data?.page ?? 1) + 1, props.data?.page_count ?? 1))}
        >
          {ka.next}
        </button>
      </div>
    </article>
  )
}
