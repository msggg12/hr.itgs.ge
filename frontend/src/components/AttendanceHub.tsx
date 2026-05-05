import { useEffect, useMemo, useState } from 'react'

import { AlertTriangle, BarChart3, CalendarDays, ChevronLeft, ChevronRight, Download, PencilLine, ShieldAlert, Users, X } from 'lucide-react'

import { downloadFile, getJson } from '../api'
import type { AttendanceHubData, AttendanceHubReportRow, AttendancePersonalReportData, ShiftAssignment, ShiftPlannerData } from '../types'
import { classNames, formatHours } from '../utils'

type AttendanceHubProps = {
  data: AttendanceHubData | null
  shiftPlannerData: ShiftPlannerData | null
  attendanceImportBusy: boolean
  selectedMonth: string
  onPreviousMonth: () => void
  onNextMonth: () => void
  onMonthChange: (value: string) => void
  onAssignShift: (
    employeeId: string,
    payload: {
      shiftPatternId?: string | null
      shiftDate: string
      startTime?: string
      endTime?: string
    }
  ) => Promise<void>
  onClearShift: (employeeId: string, shiftDate: string) => Promise<void>
  onImportSmartPss: (file: File) => Promise<void>
  onDepartmentChange: (departmentId: string) => void
}

type AttendanceTab = 'schedule' | 'reports'
type ExportBusyKey = 'personal-csv' | 'personal-xlsx' | 'team-csv' | 'team-xlsx'

type AssignmentEditorState = {
  employeeId: string
  employeeName: string
  shiftDate: string
  currentAssignment: ShiftAssignment | null
}

function weekBucketKey(shiftDate: string): string {
  const value = new Date(`${shiftDate}T00:00:00`)
  const offset = (value.getDay() + 6) % 7
  value.setDate(value.getDate() - offset)
  return value.toISOString().slice(0, 10)
}

function manualShiftMinutes(startTime: string, endTime: string): { plannedMinutes: number; crossesMidnight: boolean } | null {
  if (!startTime || !endTime) {
    return null
  }
  const [startHour, startMinute] = startTime.split(':').map((value) => Number.parseInt(value, 10))
  const [endHour, endMinute] = endTime.split(':').map((value) => Number.parseInt(value, 10))
  if ([startHour, startMinute, endHour, endMinute].some((value) => Number.isNaN(value))) {
    return null
  }
  let startTotal = startHour * 60 + startMinute
  let endTotal = endHour * 60 + endMinute
  let crossesMidnight = false
  if (endTotal <= startTotal) {
    endTotal += 24 * 60
    crossesMidnight = true
  }
  const plannedMinutes = endTotal - startTotal
  if (plannedMinutes <= 0 || plannedMinutes > 24 * 60) {
    return null
  }
  return { plannedMinutes, crossesMidnight }
}

function triggerBrowserDownload(blob: Blob, fileName: string) {
  const url = window.URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.URL.revokeObjectURL(url)
}

function monthValueFromDate(value: string): string {
  return value.slice(0, 7)
}

function toMonthStart(value: string): string {
  return `${value}-01`
}

function firstSegmentSummary(pattern: ShiftPlannerData['patterns'][number]): string {
  const segment = pattern.segments[0]
  if (!segment) {
    return 'No shift segments'
  }
  const endTime = 'end_time' in segment ? (segment.end_time as string) : ''
  return `${segment.start_time}${endTime ? `-${endTime}` : ''} • ${formatHours(segment.planned_minutes)}`
}

export function AttendanceHub(props: AttendanceHubProps) {
  const [tab, setTab] = useState<AttendanceTab>('schedule')
  const [editMode, setEditMode] = useState(false)
  const [personalRange, setPersonalRange] = useState({ start: '', end: '' })
  const [personalBusy, setPersonalBusy] = useState(false)
  const [personalError, setPersonalError] = useState('')
  const [personalReport, setPersonalReport] = useState<AttendancePersonalReportData | null>(null)
  const [exportBusy, setExportBusy] = useState<ExportBusyKey | null>(null)
  const [assignmentEditor, setAssignmentEditor] = useState<AssignmentEditorState | null>(null)
  const [selectedPatternId, setSelectedPatternId] = useState('')
  const [manualStartTime, setManualStartTime] = useState('')
  const [manualEndTime, setManualEndTime] = useState('')
  const [assignmentBusy, setAssignmentBusy] = useState(false)
  const [attendanceImportError, setAttendanceImportError] = useState('')

  const canManage = props.data?.can_manage_schedule ?? false
  const tabs: AttendanceTab[] = canManage ? ['schedule', 'reports'] : ['schedule']
  const availablePatterns = props.shiftPlannerData?.patterns ?? []

  const assignmentMap = useMemo(() => {
    const map = new Map<string, ShiftAssignment>()
    for (const assignment of props.shiftPlannerData?.assignments ?? []) {
      map.set(`${assignment.employee_id}-${assignment.shift_date}`, assignment)
    }
    return map
  }, [props.shiftPlannerData])

  const assignmentEditorEmployee = useMemo(
    () => props.shiftPlannerData?.employees.find((employee) => employee.id === assignmentEditor?.employeeId) ?? null,
    [assignmentEditor?.employeeId, props.shiftPlannerData?.employees],
  )

  const manualTiming = useMemo(
    () => manualShiftMinutes(manualStartTime, manualEndTime),
    [manualEndTime, manualStartTime],
  )

  const projectedWeeklyMinutes = useMemo(() => {
    if (!assignmentEditor || !assignmentEditorEmployee) {
      return 0
    }
    const weekKey = weekBucketKey(assignmentEditor.shiftDate)
    const currentWeekMinutes = assignmentEditorEmployee.weekly_minutes_map?.[weekKey] ?? 0
    const currentAssignmentMinutes = assignmentEditor.currentAssignment && weekBucketKey(assignmentEditor.currentAssignment.shift_date) === weekKey
      ? assignmentEditor.currentAssignment.planned_minutes
      : 0
    const nextPlannedMinutes = manualTiming
      ? manualTiming.plannedMinutes
      : (assignmentEditor.currentAssignment?.shift_pattern_id === selectedPatternId
          ? assignmentEditor.currentAssignment?.planned_minutes ?? 0
          : (() => {
              const pattern = availablePatterns.find((item) => item.id === selectedPatternId)
              if (!pattern) {
                return 0
              }
              const selectedDate = new Date(`${assignmentEditor.shiftDate}T00:00:00`)
              const dayIndex = pattern.pattern_type === 'fixed_weekly'
                ? ((selectedDate.getDay() + 6) % 7) + 1
                : 1
              const segment = pattern.segments.find((item) => item.day_index === dayIndex)
              return segment?.planned_minutes ?? 0
            })())
    return Math.max(currentWeekMinutes - currentAssignmentMinutes + nextPlannedMinutes, 0)
  }, [assignmentEditor, assignmentEditorEmployee, availablePatterns, manualTiming, selectedPatternId])

  const weeklyOverLimit = projectedWeeklyMinutes > 40 * 60

  useEffect(() => {
    if (!tabs.includes(tab)) {
      setTab('schedule')
    }
  }, [tab, tabs])

  useEffect(() => {
    if (!canManage) {
      setEditMode(false)
      setAssignmentEditor(null)
    }
  }, [canManage])

  useEffect(() => {
    if (!props.data) {
      return
    }
    setPersonalRange({
      start: props.data.month_start,
      end: props.data.month_end,
    })
  }, [props.data?.month_start, props.data?.month_end])

  useEffect(() => {
    if (!assignmentEditor) {
      setSelectedPatternId('')
      setManualStartTime('')
      setManualEndTime('')
      return
    }
    setSelectedPatternId(assignmentEditor.currentAssignment?.shift_pattern_id ?? '')
    setManualStartTime(assignmentEditor.currentAssignment?.start_time ?? '')
    setManualEndTime(assignmentEditor.currentAssignment?.end_time ?? '')
  }, [assignmentEditor])

  useEffect(() => {
    if (!personalRange.start || !personalRange.end) {
      return
    }
    let cancelled = false
    setPersonalBusy(true)
    setPersonalError('')
    void getJson<AttendancePersonalReportData>('/ux/attendance-personal-report', {
      start_date: personalRange.start,
      end_date: personalRange.end,
    })
      .then((payload) => {
        if (!cancelled) {
          setPersonalReport(payload)
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setPersonalError(error.message)
        }
      })
      .finally(() => {
        if (!cancelled) {
          setPersonalBusy(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [personalRange.start, personalRange.end])

  const activePersonalReport = personalReport ?? (props.data ? {
    start_date: props.data.month_start,
    end_date: props.data.month_end,
    summary: props.data.personal_summary,
    days: props.data.personal_days,
  } : null)

  async function downloadAttendanceExport(path: string, params: Record<string, string | null | undefined>, busyKey: ExportBusyKey) {
    setExportBusy(busyKey)
    try {
      const { blob, fileName } = await downloadFile(path, params)
      triggerBrowserDownload(blob, fileName ?? `${busyKey}.${busyKey.includes('xlsx') ? 'xlsx' : 'csv'}`)
    } finally {
      setExportBusy(null)
    }
  }

  function openAssignmentEditor(employeeId: string, employeeName: string, shiftDate: string) {
    if (!canManage || !editMode) {
      return
    }
    setAssignmentEditor({
      employeeId,
      employeeName,
      shiftDate,
      currentAssignment: assignmentMap.get(`${employeeId}-${shiftDate}`) ?? null,
    })
  }

  async function saveInlineAssignment() {
    if (!assignmentEditor) {
      return
    }
    const useManualTimes = Boolean(manualStartTime && manualEndTime)
    if (!useManualTimes && !selectedPatternId) {
      return
    }
    if (useManualTimes && !manualTiming) {
      return
    }
    setAssignmentBusy(true)
    try {
      await props.onAssignShift(assignmentEditor.employeeId, {
        shiftPatternId: useManualTimes ? null : selectedPatternId,
        shiftDate: assignmentEditor.shiftDate,
        startTime: useManualTimes ? manualStartTime : undefined,
        endTime: useManualTimes ? manualEndTime : undefined,
      })
      setAssignmentEditor(null)
    } finally {
      setAssignmentBusy(false)
    }
  }

  async function clearInlineAssignment() {
    if (!assignmentEditor) {
      return
    }
    setAssignmentBusy(true)
    try {
      await props.onClearShift(assignmentEditor.employeeId, assignmentEditor.shiftDate)
      setAssignmentEditor(null)
    } finally {
      setAssignmentBusy(false)
    }
  }

  if (!props.data) {
    return (
      <section className="panel-card p-6">
        <p className="text-sm text-slate-500">Loading attendance hub...</p>
      </section>
    )
  }

  const personalReportPanel = (
    <article className="panel-card p-5 sm:p-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <BarChart3 className="h-4 w-4 text-slate-500" />
          My Attendance Report
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="date"
            className="input-shell"
            value={personalRange.start}
            onChange={(event) => setPersonalRange((current) => ({ ...current, start: event.target.value }))}
          />
          <input
            type="date"
            className="input-shell"
            value={personalRange.end}
            onChange={(event) => setPersonalRange((current) => ({ ...current, end: event.target.value }))}
          />
          <button
            type="button"
            className="muted-btn"
            disabled={exportBusy === 'personal-csv'}
            onClick={() => void downloadAttendanceExport('/ux/attendance-personal-report/export', {
              start_date: personalRange.start,
              end_date: personalRange.end,
              format: 'csv',
            }, 'personal-csv')}
          >
            <Download className="h-4 w-4" />
            {exportBusy === 'personal-csv' ? 'Exporting...' : 'Export CSV'}
          </button>
          <button
            type="button"
            className="muted-btn"
            disabled={exportBusy === 'personal-xlsx'}
            onClick={() => void downloadAttendanceExport('/ux/attendance-personal-report/export', {
              start_date: personalRange.start,
              end_date: personalRange.end,
              format: 'xlsx',
            }, 'personal-xlsx')}
          >
            <Download className="h-4 w-4" />
            {exportBusy === 'personal-xlsx' ? 'Exporting...' : 'Export Excel'}
          </button>
        </div>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-5">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Present</p>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{activePersonalReport?.summary.present_days ?? 0}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Absent</p>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{activePersonalReport?.summary.absent_days ?? 0}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Leave</p>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{activePersonalReport?.summary.leave_days ?? 0}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Sick</p>
          <p className="mt-2 text-2xl font-semibold text-slate-950">{activePersonalReport?.summary.sick_days ?? 0}</p>
        </div>
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-4">
          <p className="text-xs uppercase tracking-[0.2em] text-rose-500">Exceptions</p>
          <p className="mt-2 text-2xl font-semibold text-rose-900">{activePersonalReport?.summary.exception_days ?? 0}</p>
        </div>
      </div>

      {personalError ? (
        <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {personalError}
        </div>
      ) : null}

      <div className="mt-5 overflow-x-auto">
        <table className="min-w-full text-left">
          <thead className="border-b border-slate-100 bg-slate-50/80">
            <tr className="text-xs uppercase tracking-[0.16em] text-slate-400">
              <th className="px-4 py-3 font-semibold">Date</th>
              <th className="px-4 py-3 font-semibold">Status</th>
              <th className="px-4 py-3 font-semibold">Shift</th>
              <th className="px-4 py-3 font-semibold">Check In</th>
              <th className="px-4 py-3 font-semibold">Check Out</th>
              <th className="px-4 py-3 font-semibold">Hours</th>
              <th className="px-4 py-3 font-semibold">Late</th>
              <th className="px-4 py-3 font-semibold">Exception</th>
            </tr>
          </thead>
          <tbody>
            {personalBusy ? (
              <tr>
                <td colSpan={8} className="px-4 py-6 text-sm text-slate-500">Loading personal attendance...</td>
              </tr>
            ) : (
              (activePersonalReport?.days ?? []).map((day) => (
                <tr key={day.date} className="border-b border-slate-100 last:border-b-0">
                  <td className="px-4 py-3 text-sm text-slate-700">{day.date}</td>
                  <td className="px-4 py-3 text-sm font-semibold text-slate-900">{day.icon || '•'} {day.status}</td>
                  <td className="px-4 py-3 text-sm text-slate-700">{day.shift_label ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-slate-700">{day.check_in_label ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-slate-700">{day.check_out_label ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-slate-700">{formatHours(day.total_minutes)}</td>
                  <td className="px-4 py-3 text-sm text-slate-700">{day.late_minutes ? `${day.late_minutes}m` : '—'}</td>
                  <td className="px-4 py-3 text-sm text-rose-700">{day.exception_label ?? '—'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </article>
  )

  const reportsPanel = (
    <article className="table-shell">
      <div className="flex flex-col gap-4 border-b border-slate-100 px-5 py-5 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h3 className="text-xl font-semibold text-slate-900">Team Movement Report</h3>
          <p className="mt-1 text-sm text-slate-500">Worked hours, late days, overtime, leave, and attendance exceptions for the selected range.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <label className="muted-btn cursor-pointer">
            <input
              type="file"
              accept=".csv,text/csv,application/vnd.ms-excel"
              className="hidden"
              disabled={props.attendanceImportBusy}
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (!file) {
                  return
                }
                setAttendanceImportError('')
                void props.onImportSmartPss(file)
                  .catch((error: Error) => setAttendanceImportError(error.message))
                  .finally(() => {
                    event.target.value = ''
                  })
              }}
            />
            <Download className="h-4 w-4" />
            {props.attendanceImportBusy ? 'Importing SmartPSS...' : 'Import SmartPSS CSV'}
          </label>
          <button
            type="button"
            className="muted-btn"
            disabled={exportBusy === 'team-csv'}
            onClick={() => void downloadAttendanceExport('/ux/attendance-team-report/export', {
              start_date: props.data.month_start,
              end_date: props.data.month_end,
              department_id: props.data.selected_department_id,
              format: 'csv',
            }, 'team-csv')}
          >
            <Download className="h-4 w-4" />
            {exportBusy === 'team-csv' ? 'Exporting...' : 'Export Team Summary CSV'}
          </button>
          <button
            type="button"
            className="muted-btn"
            disabled={exportBusy === 'team-xlsx'}
            onClick={() => void downloadAttendanceExport('/ux/attendance-team-report/export', {
              start_date: props.data.month_start,
              end_date: props.data.month_end,
              department_id: props.data.selected_department_id,
              format: 'xlsx',
            }, 'team-xlsx')}
          >
            <Download className="h-4 w-4" />
            {exportBusy === 'team-xlsx' ? 'Exporting...' : 'Export Team Summary Excel'}
          </button>
        </div>
      </div>
      {attendanceImportError ? (
        <div className="mx-5 mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {attendanceImportError}
        </div>
      ) : null}
      <div className="overflow-x-auto">
        <table className="min-w-full text-left">
          <thead className="border-b border-slate-100 bg-slate-50/80">
            <tr className="text-xs uppercase tracking-[0.16em] text-slate-400">
              <th className="px-4 py-3 font-semibold">Employee</th>
              <th className="px-4 py-3 font-semibold">Hours</th>
              <th className="px-4 py-3 font-semibold">Late Days</th>
              <th className="px-4 py-3 font-semibold">Overtime</th>
              <th className="px-4 py-3 font-semibold">Present</th>
              <th className="px-4 py-3 font-semibold">Absent</th>
              <th className="px-4 py-3 font-semibold">Leave</th>
              <th className="px-4 py-3 font-semibold">Sick</th>
              <th className="px-4 py-3 font-semibold">Exceptions</th>
            </tr>
          </thead>
          <tbody>
            {props.data.reports.map((report: AttendanceHubReportRow) => (
              <tr key={report.employee_id} className="border-b border-slate-100 last:border-b-0">
                <td className="px-4 py-3">
                  <p className="font-semibold text-slate-900">{report.employee_name}</p>
                  <p className="text-xs text-slate-500">{report.job_title ?? report.department_name ?? report.employee_number}</p>
                </td>
                <td className="px-4 py-3 text-sm text-slate-700">{formatHours(report.total_minutes)}</td>
                <td className="px-4 py-3 text-sm text-slate-700">{report.late_days}</td>
                <td className="px-4 py-3 text-sm text-slate-700">{formatHours(report.overtime_minutes)}</td>
                <td className="px-4 py-3 text-sm text-slate-700">{report.present_days}</td>
                <td className="px-4 py-3 text-sm text-slate-700">{report.absent_days}</td>
                <td className="px-4 py-3 text-sm text-slate-700">{report.leave_days}</td>
                <td className="px-4 py-3 text-sm text-slate-700">{report.sick_days}</td>
                <td className="px-4 py-3 text-sm text-rose-700">{report.exception_days ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  )

  return (
    <section className="space-y-6">
      <article className="panel-card p-5 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="section-kicker">Attendance Control</p>
            <h2 className="section-title">Attendance & Shifts</h2>
            <p className="mt-2 max-w-3xl text-sm text-slate-500">
              Department schedules, team planning, and strict attendance calculations with a {props.data.grace_period_minutes}-minute grace window.
            </p>
          </div>
          {canManage ? (
            <div className="flex flex-wrap items-center gap-3">
              {props.data.can_select_department ? (
                <select
                  className="input-shell min-w-[220px]"
                  value={props.data.selected_department_id ?? ''}
                  onChange={(event) => props.onDepartmentChange(event.target.value)}
                >
                  {props.data.departments.map((department) => (
                    <option key={department.id} value={department.id}>
                      {department.name}
                    </option>
                  ))}
                </select>
              ) : null}
              <button
                type="button"
                className={classNames('muted-btn', editMode && 'border-action-200 bg-action-50 text-action-700')}
                onClick={() => setEditMode((current) => !current)}
              >
                <PencilLine className="h-4 w-4" />
                {editMode ? 'Done Editing' : 'Edit Schedule'}
              </button>
            </div>
          ) : null}
        </div>

        {canManage ? (
          <div className="mt-5 grid gap-4 md:grid-cols-4">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                <Users className="h-4 w-4 text-slate-500" />
                Team Scope
              </div>
              <p className="mt-3 text-2xl font-semibold text-slate-950">{props.data.team_rows.length}</p>
              <p className="mt-1 text-xs text-slate-500">{props.data.selected_department_name ?? 'Department scope'}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                <BarChart3 className="h-4 w-4 text-slate-500" />
                Worked Hours
              </div>
              <p className="mt-3 text-2xl font-semibold text-slate-950">{formatHours(activePersonalReport?.summary.total_minutes ?? props.data.personal_summary.total_minutes)}</p>
              <p className="mt-1 text-xs text-slate-500">My selected range</p>
            </div>
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-amber-700">
                <ShieldAlert className="h-4 w-4" />
                Late Days
              </div>
              <p className="mt-3 text-2xl font-semibold text-amber-900">{activePersonalReport?.summary.late_days ?? props.data.personal_summary.late_days}</p>
              <p className="mt-1 text-xs text-amber-700">After +{props.data.grace_period_minutes} minutes</p>
            </div>
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-rose-700">
                <ShieldAlert className="h-4 w-4" />
                Exceptions
              </div>
              <p className="mt-3 text-2xl font-semibold text-rose-900">{activePersonalReport?.summary.exception_days ?? props.data.personal_summary.exception_days ?? 0}</p>
              <p className="mt-1 text-xs text-rose-700">Missing checkout and review-required days</p>
            </div>
          </div>
        ) : null}
      </article>

      {canManage ? (
        <div className="flex flex-wrap gap-2">
          {tabs.map((tabKey) => (
            <button
              key={tabKey}
              type="button"
              className={classNames(
                'rounded-2xl border px-4 py-2.5 text-sm font-semibold transition',
                tab === tabKey ? 'border-action-200 bg-action-50 text-action-700' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50',
              )}
              onClick={() => setTab(tabKey)}
            >
              {tabKey === 'schedule' ? 'Schedule' : 'Reports'}
            </button>
          ))}
        </div>
      ) : null}

      {canManage && tab === 'schedule' ? (
        <article className="table-shell">
          <div className="flex flex-col gap-4 border-b border-slate-100 px-5 py-5 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <h3 className="text-xl font-semibold text-slate-900">Department Schedule Grid</h3>
              <p className="mt-1 text-sm text-slate-500">
                Monthly schedule and attendance status for {props.data.selected_department_name ?? 'your team'}.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" className="muted-btn px-3 py-3" onClick={props.onPreviousMonth}>
                <ChevronLeft className="h-4 w-4" />
              </button>
              <label className="inline-flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm font-semibold text-slate-700">
                <CalendarDays className="h-4 w-4 text-slate-500" />
                <input
                  type="month"
                  className="bg-transparent text-sm font-semibold text-slate-700 outline-none"
                  value={monthValueFromDate(props.selectedMonth)}
                  onChange={(event) => props.onMonthChange(toMonthStart(event.target.value))}
                />
              </label>
              <button type="button" className="muted-btn px-3 py-3" onClick={props.onNextMonth}>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full border-separate border-spacing-0 text-left">
              <thead className="border-b border-slate-100 bg-slate-50/80">
                <tr className="text-xs uppercase tracking-[0.16em] text-slate-400">
                  <th className="sticky left-0 z-10 min-w-[220px] bg-slate-50/95 px-4 py-4 font-semibold">Employee</th>
                  {props.data.days.map((day) => (
                    <th key={day.date} className="min-w-[112px] px-3 py-4 text-center font-semibold">
                      <p>{day.label}</p>
                      <p className="mt-1 text-[10px] normal-case tracking-normal text-slate-500">{day.date.slice(8)}</p>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {props.data.team_rows.map((row) => (
                  <tr key={row.employee_id} className="border-b border-slate-100 last:border-b-0">
                    <td className="sticky left-0 z-10 min-w-[220px] border-r border-slate-100 bg-white px-4 py-4 align-top">
                      <p className="font-semibold text-slate-900">{row.employee_name}</p>
                      <p className="mt-1 text-xs text-slate-500">{row.job_title ?? row.department_name ?? row.employee_number}</p>
                    </td>
                    {row.day_statuses.map((day) => {
                      const currentAssignment = assignmentMap.get(`${row.employee_id}-${day.date}`) ?? null
                      const cellEditable = editMode && canManage
                      const employeePlannerRow = props.shiftPlannerData?.employees.find((employee) => employee.id === row.employee_id) ?? null
                      const weeklyMinutes = employeePlannerRow?.weekly_minutes_map?.[weekBucketKey(day.date)] ?? 0
                      const weeklyWarning = weeklyMinutes > 40 * 60
                      return (
                        <td key={`${row.employee_id}-${day.date}`} className="px-2 py-3 align-top">
                          <button
                            type="button"
                            className={classNames(
                              'w-full rounded-2xl border px-2 py-3 text-center transition',
                              day.status === 'leave' && 'border-sky-200 bg-sky-50',
                              day.status === 'sick' && 'border-rose-200 bg-rose-50',
                              day.status === 'present' && !day.exception_label && 'border-emerald-200 bg-emerald-50/70',
                              day.exception_label && 'border-amber-200 bg-amber-50',
                              day.status === 'absent' && 'border-slate-200 bg-slate-100',
                              !day.status && 'border-slate-100 bg-slate-50/70',
                              cellEditable && 'cursor-pointer hover:-translate-y-0.5 hover:shadow-md',
                            )}
                            onClick={() => openAssignmentEditor(row.employee_id, row.employee_name, day.date)}
                            disabled={!cellEditable}
                          >
                            <div className="flex items-center justify-center gap-1 text-lg leading-none">
                              <span>{day.icon || '•'}</span>
                              {weeklyWarning ? <AlertTriangle className="h-3.5 w-3.5 text-amber-500" /> : null}
                            </div>
                            <p className="mt-2 text-[11px] font-semibold text-slate-700">{day.shift_label ?? day.label ?? '—'}</p>
                            {(day.check_in_label || day.check_out_label) ? (
                              <p className="mt-1 text-[10px] text-slate-500">
                                {day.check_in_label ?? '--'} / {day.check_out_label ?? '--'}
                              </p>
                            ) : null}
                            {day.exception_label ? (
                              <p className="mt-1 text-[10px] font-semibold text-amber-700">{day.exception_label}</p>
                            ) : null}
                            {cellEditable ? (
                              <p className="mt-1 text-[10px] font-semibold text-action-600">
                                {currentAssignment ? 'Edit shift' : 'Assign shift'}
                              </p>
                            ) : null}
                          </button>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ) : null}

      {canManage && tab === 'reports' ? reportsPanel : null}

      {personalReportPanel}

      {assignmentEditor ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 px-4">
          <div className="w-full max-w-2xl rounded-[28px] border border-slate-200 bg-white p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-action-500">Inline Shift Assignment</p>
                <h3 className="mt-2 text-2xl font-semibold text-slate-950">{assignmentEditor.employeeName}</h3>
                <p className="mt-1 text-sm text-slate-500">{assignmentEditor.shiftDate}</p>
              </div>
              <button type="button" className="muted-btn px-3 py-3" onClick={() => setAssignmentEditor(null)} disabled={assignmentBusy}>
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
              Current shift: <span className="font-semibold text-slate-900">{assignmentEditor.currentAssignment?.pattern_name ?? 'No shift assigned'}</span>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
              <div className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Quick Select Pattern</p>
                <select
                  className="input-shell w-full"
                  value={selectedPatternId}
                  onChange={(event) => {
                    setSelectedPatternId(event.target.value)
                    if (event.target.value) {
                      setManualStartTime('')
                      setManualEndTime('')
                    }
                  }}
                  disabled={assignmentBusy || !availablePatterns.length}
                >
                  <option value="">Select shift template</option>
                  {availablePatterns.map((pattern) => (
                    <option key={pattern.id} value={pattern.id}>
                      {pattern.code} · {pattern.name}
                    </option>
                  ))}
                </select>
                {selectedPatternId ? (
                  <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                    {(() => {
                      const selectedPattern = availablePatterns.find((pattern) => pattern.id === selectedPatternId)
                      return selectedPattern ? firstSegmentSummary(selectedPattern) : 'No shift template selected'
                    })()}
                  </div>
                ) : null}
                {!availablePatterns.length ? (
                  <div className="rounded-2xl border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-500">
                    No shift templates are available for assignment yet.
                  </div>
                ) : null}
              </div>

              <div className="space-y-3 rounded-2xl border border-slate-200 bg-white px-4 py-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Manual Override</p>
                  <p className="mt-1 text-sm text-slate-500">Enter custom times for a one-off shift on this specific date.</p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="space-y-2 text-sm text-slate-600">
                    <span className="font-medium text-slate-700">Start Time</span>
                    <input
                      type="time"
                      className="input-shell w-full"
                      value={manualStartTime}
                      onChange={(event) => {
                        setManualStartTime(event.target.value)
                        if (event.target.value) {
                          setSelectedPatternId('')
                        }
                      }}
                      disabled={assignmentBusy}
                    />
                  </label>
                  <label className="space-y-2 text-sm text-slate-600">
                    <span className="font-medium text-slate-700">End Time</span>
                    <input
                      type="time"
                      className="input-shell w-full"
                      value={manualEndTime}
                      onChange={(event) => {
                        setManualEndTime(event.target.value)
                        if (event.target.value) {
                          setSelectedPatternId('')
                        }
                      }}
                      disabled={assignmentBusy}
                    />
                  </label>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                  {manualTiming
                    ? `Custom shift duration: ${formatHours(manualTiming.plannedMinutes)}`
                    : 'Use this when you need a one-off custom shift instead of a reusable template.'}
                </div>
              </div>
            </div>

            {weeklyOverLimit ? (
              <div className="mt-4 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  <p className="font-semibold">Warning: This schedule exceeds 40 hours/week.</p>
                  <p className="mt-1 text-amber-700">Projected weekly total: {formatHours(projectedWeeklyMinutes)} for the Monday-Sunday week containing this shift.</p>
                </div>
              </div>
            ) : null}

            <div className="mt-6 flex flex-wrap justify-end gap-2">
              {assignmentEditor.currentAssignment ? (
                <button type="button" className="muted-btn text-rose-700" onClick={() => void clearInlineAssignment()} disabled={assignmentBusy}>
                  {assignmentBusy ? 'Working...' : 'Clear Shift'}
                </button>
              ) : null}
              <button type="button" className="muted-btn" onClick={() => setAssignmentEditor(null)} disabled={assignmentBusy}>
                Cancel
              </button>
              <button
                type="button"
                className="primary-btn"
                onClick={() => void saveInlineAssignment()}
                disabled={assignmentBusy || ((!selectedPatternId) && !(manualTiming && manualStartTime && manualEndTime))}
              >
                {assignmentBusy ? 'Saving...' : 'Save Shift'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}
