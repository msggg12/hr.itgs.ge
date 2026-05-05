import { useEffect, useMemo, useState } from 'react'

import { CalendarClock, Plus, Save, Settings2, Sparkles, Trash2 } from 'lucide-react'

import type { ShiftBuilderData, ShiftBuilderPattern, ShiftBuilderSegment } from '../types'
import { classNames, formatHours } from '../utils'

type ShiftBuilderProps = {
  data: ShiftBuilderData | null
  onSave: (patternId: string | null, payload: {
    code: string
    name: string
    pattern_type: string
    cycle_length_days: number
    timezone: string
    standard_weekly_hours: number
    early_check_in_grace_minutes: number
    late_check_out_grace_minutes: number
    grace_period_minutes: number
    segments: Array<{
      day_index: number
      start_time: string
      end_time: string
      break_minutes: number
      label: string | null
    }>
  }) => Promise<void>
}

const weekdayLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function toLocalDate(timeText: string): Date {
  return new Date(`2000-01-01T${timeText}:00`)
}

function crossesMidnight(startTime: string, endTime: string): boolean {
  return toLocalDate(endTime).getTime() <= toLocalDate(startTime).getTime()
}

function calculatePlannedMinutes(startTime: string, endTime: string, breakMinutes: number): number {
  const start = toLocalDate(startTime)
  const end = toLocalDate(endTime)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return 0
  }
  if (end <= start) {
    end.setDate(end.getDate() + 1)
  }
  const totalMinutes = Math.round((end.getTime() - start.getTime()) / 60000)
  return Math.max(totalMinutes - breakMinutes, 0)
}

function createSegment(dayIndex: number, startTime = '09:00', endTime = '18:00', breakMinutes = 60, label: string | null = null): ShiftBuilderSegment {
  return {
    day_index: dayIndex,
    start_time: startTime,
    end_time: endTime,
    planned_minutes: calculatePlannedMinutes(startTime, endTime, breakMinutes),
    break_minutes: breakMinutes,
    crosses_midnight: crossesMidnight(startTime, endTime),
    label,
  }
}

function officePreset(): ShiftBuilderSegment[] {
  return [1, 2, 3, 4, 5].map((dayIndex) => createSegment(dayIndex, '09:00', '18:00', 60, 'Office'))
}

function warehousePreset(): ShiftBuilderSegment[] {
  return [1, 2, 5, 6].map((dayIndex) => createSegment(dayIndex, '08:00', '20:00', 60, 'Warehouse'))
}

function nightPreset(): ShiftBuilderSegment[] {
  return [1, 2, 3, 4, 5].map((dayIndex) => createSegment(dayIndex, '22:00', '07:00', 60, 'Night'))
}

function defaultForm() {
  return {
    code: '',
    name: '',
    pattern_type: 'fixed_weekly',
    cycle_length_days: 7,
    timezone: 'Asia/Tbilisi',
    standard_weekly_hours: 40,
    early_check_in_grace_minutes: 60,
    late_check_out_grace_minutes: 240,
    grace_period_minutes: 10,
    segments: officePreset(),
  }
}

function normalizeSegments(segments: ShiftBuilderSegment[]): ShiftBuilderSegment[] {
  return [...segments]
    .sort((left, right) => left.day_index - right.day_index)
    .map((segment) => ({
      ...segment,
      planned_minutes: calculatePlannedMinutes(segment.start_time, segment.end_time, segment.break_minutes),
      crosses_midnight: crossesMidnight(segment.start_time, segment.end_time),
    }))
}

export function ShiftBuilder(props: ShiftBuilderProps) {
  const [selectedId, setSelectedId] = useState<string>('new')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState(defaultForm)

  useEffect(() => {
    if (!props.data) {
      return
    }
    const selectedPattern = props.data.patterns?.find((item) => item.id === selectedId)
    if (!selectedPattern) {
      setForm(defaultForm())
      return
    }
    setForm({
      code: selectedPattern.code,
      name: selectedPattern.name,
      pattern_type: selectedPattern.pattern_type,
      cycle_length_days: selectedPattern.cycle_length_days,
      timezone: selectedPattern.timezone,
      standard_weekly_hours: selectedPattern.standard_weekly_hours,
      early_check_in_grace_minutes: selectedPattern.early_check_in_grace_minutes,
      late_check_out_grace_minutes: selectedPattern.late_check_out_grace_minutes,
      grace_period_minutes: selectedPattern.grace_period_minutes,
      segments: normalizeSegments(selectedPattern.segments.map((segment) => ({ ...segment }))),
    })
    setError('')
  }, [props.data, selectedId])

  const totalPlannedMinutes = useMemo(
    () => form.segments.reduce((sum, segment) => sum + calculatePlannedMinutes(segment.start_time, segment.end_time, segment.break_minutes), 0),
    [form.segments],
  )

  const weeklyLimitExceeded = totalPlannedMinutes > form.standard_weekly_hours * 60

  function applyPreset(kind: 'office' | 'warehouse' | 'night') {
    const preset = {
      office: {
        code: 'OFFICE-5X2',
        name: 'Office 5/2',
        pattern_type: 'fixed_weekly',
        cycle_length_days: 7,
        standard_weekly_hours: 40,
        segments: officePreset(),
      },
      warehouse: {
        code: 'WAREHOUSE-2X2',
        name: 'Warehouse 2/2',
        pattern_type: 'cycle',
        cycle_length_days: 6,
        standard_weekly_hours: 48,
        segments: warehousePreset(),
      },
      night: {
        code: 'NIGHT-5X2',
        name: 'Night Shift',
        pattern_type: 'fixed_weekly',
        cycle_length_days: 7,
        standard_weekly_hours: 40,
        segments: nightPreset(),
      },
    }[kind]

    setForm((current) => ({
      ...current,
      code: preset.code,
      name: preset.name,
      pattern_type: preset.pattern_type,
      cycle_length_days: preset.cycle_length_days,
      standard_weekly_hours: preset.standard_weekly_hours,
      segments: preset.segments,
    }))
    setError('')
  }

  function updateSegment(index: number, key: keyof ShiftBuilderSegment, value: string | number | boolean | null) {
    setForm((current) => ({
      ...current,
      segments: normalizeSegments(
        current.segments.map((segment, segmentIndex) => {
          if (segmentIndex !== index) {
            return segment
          }
          const nextSegment = { ...segment, [key]: value }
          nextSegment.planned_minutes = calculatePlannedMinutes(nextSegment.start_time, nextSegment.end_time, nextSegment.break_minutes)
          nextSegment.crosses_midnight = crossesMidnight(nextSegment.start_time, nextSegment.end_time)
          return nextSegment
        }),
      ),
    }))
  }

  async function handleSave() {
    if (!form.code.trim() || !form.name.trim()) {
      setError('Fill in both the shift code and shift name.')
      return
    }
    if (!form.segments.length) {
      setError('Add at least one working day segment.')
      return
    }
    const dayIndexes = form.segments.map((segment) => segment.day_index)
    if (new Set(dayIndexes).size !== dayIndexes.length) {
      setError('Each day index must be unique.')
      return
    }
    if (form.pattern_type === 'fixed_weekly' && form.segments.some((segment) => segment.day_index > 7)) {
      setError('Weekly patterns only support day indexes from 1 to 7.')
      return
    }
    if (form.segments.some((segment) => calculatePlannedMinutes(segment.start_time, segment.end_time, segment.break_minutes) <= 0)) {
      setError('Every shift segment must have a positive duration.')
      return
    }

    setBusy(true)
    setError('')
    try {
      await props.onSave(selectedId === 'new' ? null : selectedId, {
        code: form.code.trim(),
        name: form.name.trim(),
        pattern_type: form.pattern_type,
        cycle_length_days: form.cycle_length_days,
        timezone: form.timezone,
        standard_weekly_hours: form.standard_weekly_hours,
        early_check_in_grace_minutes: form.early_check_in_grace_minutes,
        late_check_out_grace_minutes: form.late_check_out_grace_minutes,
        grace_period_minutes: form.grace_period_minutes,
        segments: form.segments.map((segment) => ({
          day_index: Number(segment.day_index),
          start_time: segment.start_time,
          end_time: segment.end_time,
          break_minutes: Number(segment.break_minutes),
          label: segment.label?.trim() || null,
        })),
      })
      setSelectedId('new')
      setForm(defaultForm())
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel-card">
      <div className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-slate-400">Shift Control</p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950">Shift Template Builder</h2>
          <p className="mt-1 text-sm text-slate-500">
            Create weekly or rotating shift templates, define grace periods, and keep schedule assignments consistent.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <select className="input-shell min-w-[260px]" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
            <option value="new">Create New Template</option>
            {(props.data?.patterns ?? []).map((pattern) => (
              <option key={pattern.id} value={pattern.id}>
                {pattern.code} - {pattern.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="primary-btn"
            onClick={() => {
              setSelectedId('new')
              setForm(defaultForm())
            }}
          >
            <Plus className="h-4 w-4" />
            New
          </button>
        </div>
      </div>

      <div className="mb-5 grid gap-3 lg:grid-cols-3">
        <button type="button" className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4 text-left transition hover:border-slate-300" onClick={() => applyPreset('office')}>
          <div className="flex items-center gap-2 text-sm font-semibold text-sky-700">
            <Sparkles className="h-4 w-4" />
            Office 5/2
          </div>
          <p className="mt-2 text-sm text-sky-900">Monday to Friday, 09:00-18:00, with a 60-minute break.</p>
        </button>
        <button type="button" className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4 text-left transition hover:border-slate-300" onClick={() => applyPreset('warehouse')}>
          <div className="flex items-center gap-2 text-sm font-semibold text-emerald-700">
            <CalendarClock className="h-4 w-4" />
            Warehouse 2/2
          </div>
          <p className="mt-2 text-sm text-emerald-900">Twelve-hour rotating coverage with a 2-on / 2-off cadence.</p>
        </button>
        <button type="button" className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4 text-left transition hover:border-slate-300" onClick={() => applyPreset('night')}>
          <div className="flex items-center gap-2 text-sm font-semibold text-violet-700">
            <Settings2 className="h-4 w-4" />
            Night Shift
          </div>
          <p className="mt-2 text-sm text-violet-900">Monday to Friday, 22:00-07:00, designed for overnight teams.</p>
        </button>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.85fr)]">
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
          <div className="grid gap-4 md:grid-cols-2">
            <input className="input-shell" value={form.code} onChange={(event) => setForm((current) => ({ ...current, code: event.target.value }))} placeholder="Shift code" />
            <input className="input-shell" value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder="Shift name" />
            <select className="input-shell" value={form.pattern_type} onChange={(event) => setForm((current) => ({ ...current, pattern_type: event.target.value }))}>
              <option value="fixed_weekly">Weekly</option>
              <option value="cycle">Cycle</option>
            </select>
            <input className="input-shell" type="number" value={form.cycle_length_days} onChange={(event) => setForm((current) => ({ ...current, cycle_length_days: Number(event.target.value) }))} placeholder="Cycle length" />
            <input className="input-shell" value={form.timezone} onChange={(event) => setForm((current) => ({ ...current, timezone: event.target.value }))} placeholder="Timezone" />
            <input className="input-shell" type="number" step="0.5" value={form.standard_weekly_hours} onChange={(event) => setForm((current) => ({ ...current, standard_weekly_hours: Number(event.target.value) }))} placeholder="Weekly hours" />
            <input className="input-shell" type="number" value={form.grace_period_minutes} onChange={(event) => setForm((current) => ({ ...current, grace_period_minutes: Number(event.target.value) }))} placeholder="Grace period (min)" />
            <input className="input-shell" type="number" value={form.early_check_in_grace_minutes} onChange={(event) => setForm((current) => ({ ...current, early_check_in_grace_minutes: Number(event.target.value) }))} placeholder="Early check-in grace" />
            <input className="input-shell" type="number" value={form.late_check_out_grace_minutes} onChange={(event) => setForm((current) => ({ ...current, late_check_out_grace_minutes: Number(event.target.value) }))} placeholder="Late check-out grace" />
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Segments</p>
              <p className="mt-2 text-2xl font-semibold text-slate-950">{form.segments.length}</p>
            </div>
            <div className={classNames('rounded-xl border px-4 py-4', weeklyLimitExceeded ? 'border-amber-200 bg-amber-50' : 'border-emerald-200 bg-emerald-50')}>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Weekly plan</p>
              <p className="mt-2 text-2xl font-semibold text-slate-950">{formatHours(totalPlannedMinutes)}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Grace</p>
              <p className="mt-2 text-2xl font-semibold text-slate-950">{form.grace_period_minutes}m</p>
            </div>
          </div>

          {weeklyLimitExceeded ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
              The planned hours are above the standard weekly limit for this template.
            </div>
          ) : null}
          {error ? (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 break-words whitespace-pre-wrap">
              {error}
            </div>
          ) : null}

          <div className="space-y-3">
            {form.segments.map((segment, index) => {
              const plannedMinutes = calculatePlannedMinutes(segment.start_time, segment.end_time, segment.break_minutes)
              const weekdayLabel = form.pattern_type === 'fixed_weekly' && segment.day_index >= 1 && segment.day_index <= 7
                ? weekdayLabels[segment.day_index - 1]
                : `Day ${segment.day_index}`

              return (
                <div key={`${segment.day_index}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-600">{weekdayLabel}</span>
                      <span className="text-sm font-semibold text-slate-950">{formatHours(plannedMinutes)}</span>
                    </div>
                    <button
                      type="button"
                      className="flex h-10 w-10 items-center justify-center rounded-lg border border-rose-200 bg-rose-50 text-rose-600"
                      onClick={() =>
                        setForm((current) => {
                          const nextSegments = current.segments.filter((_, segmentIndex) => segmentIndex !== index)
                          return { ...current, segments: nextSegments.length ? normalizeSegments(nextSegments) : officePreset() }
                        })
                      }
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>

                  <div className="grid gap-3 md:grid-cols-[96px_repeat(4,minmax(0,1fr))]">
                    <input className="input-shell" type="number" min={1} max={366} value={segment.day_index} onChange={(event) => updateSegment(index, 'day_index', Number(event.target.value))} />
                    <input className="input-shell" type="time" value={segment.start_time} onChange={(event) => updateSegment(index, 'start_time', event.target.value)} />
                    <input className="input-shell" type="time" value={segment.end_time} onChange={(event) => updateSegment(index, 'end_time', event.target.value)} />
                    <input className="input-shell" type="number" value={segment.break_minutes} onChange={(event) => updateSegment(index, 'break_minutes', Number(event.target.value))} placeholder="Break" />
                    <input className="input-shell" value={segment.label ?? ''} onChange={(event) => updateSegment(index, 'label', event.target.value)} placeholder="Label" />
                  </div>
                </div>
              )
            })}

            <button
              type="button"
              className="muted-btn border-dashed"
              onClick={() => setForm((current) => ({ ...current, segments: normalizeSegments([...current.segments, createSegment(current.segments.length + 1)]) }))}
            >
              <Plus className="h-4 w-4" />
              Add Working Day
            </button>
          </div>

          <button type="button" className="primary-btn" onClick={() => void handleSave()} disabled={busy}>
            <Save className="h-4 w-4" />
            {busy ? 'Saving...' : 'Save Template'}
          </button>
        </div>

        <div className="space-y-3">
          {(props.data?.patterns ?? []).map((pattern: ShiftBuilderPattern) => (
            <button
              key={pattern.id}
              type="button"
              className={classNames(
                'w-full rounded-xl border p-4 text-left transition',
                selectedId === pattern.id ? 'brand-border brand-soft border' : 'border-slate-200 bg-white hover:border-slate-300',
              )}
              onClick={() => setSelectedId(pattern.id)}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">{pattern.code}</p>
                  <h3 className="mt-2 font-semibold text-slate-950">{pattern.name}</h3>
                  <p className="mt-1 text-sm text-slate-500">{pattern.pattern_type} - {pattern.standard_weekly_hours}h</p>
                </div>
                <Settings2 className="h-5 w-5 text-slate-400" />
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {normalizeSegments(pattern.segments).map((segment) => (
                  <span key={`${pattern.id}-${segment.day_index}`} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
                    {pattern.pattern_type === 'fixed_weekly' && segment.day_index <= 7 ? weekdayLabels[segment.day_index - 1] : `D${segment.day_index}`} {segment.start_time}-{segment.end_time}
                  </span>
                ))}
              </div>
              <p className="mt-4 text-xs uppercase tracking-[0.18em] text-slate-400">Assigned {pattern.assignment_count}</p>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}
