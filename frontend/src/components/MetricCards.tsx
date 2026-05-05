import { useMemo, useState } from 'react'

import {
  ArrowDownRight,
  ArrowUpRight,
  BadgeCheck,
  BriefcaseBusiness,
  CalendarClock,
  CalendarPlus,
  CircleAlert,
  ExternalLink,
  Fingerprint,
  Link2,
  MessageSquareShare,
  Unplug,
  UserCheck,
  Users
} from 'lucide-react'

import { ka } from '../i18n/ka'
import type { AnalyticsOverview, Summary, UpcomingMeetingItem, UpcomingScheduleData, WeeklyAttendancePoint } from '../types'

type ChartMetric = 'attendance' | 'late' | 'leave' | 'absences'
type TimeRange = 'this_week' | 'last_week'

type MetricCardsProps = {
  summary: Summary | null
  analytics?: AnalyticsOverview | null
  weeklyAttendance?: WeeklyAttendancePoint[]
  upcomingSchedule?: UpcomingScheduleData | null
  widgetVisibility?: Record<string, boolean>
  calendarBusy?: boolean
  onViewAttendance?: () => void
  onOpenEmployees?: () => void
  onConnectGoogleCalendar?: () => void
  onDisconnectGoogleCalendar?: () => void
  onSendMessage?: (employeeId: string, employeeName: string) => void
}

type MetricTone = {
  dot: string
  chipBg: string
  chipText: string
  bar: string
  barSoft: string
}

const chartTones: Record<ChartMetric, MetricTone> = {
  attendance: {
    dot: '#334155',
    chipBg: 'rgba(51, 65, 85, 0.12)',
    chipText: '#334155',
    bar: 'linear-gradient(180deg, #334155 0%, #1E293B 100%)',
    barSoft: 'rgba(51, 65, 85, 0.14)'
  },
  late: {
    dot: '#f59e0b',
    chipBg: 'rgba(245, 158, 11, 0.14)',
    chipText: '#b45309',
    bar: 'linear-gradient(180deg, #fbbf24 0%, #f59e0b 100%)',
    barSoft: 'rgba(245, 158, 11, 0.16)'
  },
  leave: {
    dot: '#38bdf8',
    chipBg: 'rgba(56, 189, 248, 0.16)',
    chipText: '#0369a1',
    bar: 'linear-gradient(180deg, #7dd3fc 0%, #38bdf8 100%)',
    barSoft: 'rgba(56, 189, 248, 0.16)'
  },
  absences: {
    dot: '#f87171',
    chipBg: 'rgba(248, 113, 113, 0.14)',
    chipText: '#be123c',
    bar: 'linear-gradient(180deg, #fda4af 0%, #fb7185 100%)',
    barSoft: 'rgba(248, 113, 113, 0.14)'
  }
}

function sameDay(left: Date, right: Date): boolean {
  return left.getFullYear() === right.getFullYear() && left.getMonth() === right.getMonth() && left.getDate() === right.getDate()
}

function startOfDay(value: Date): Date {
  const clone = new Date(value)
  clone.setHours(0, 0, 0, 0)
  return clone
}

function formatMeetingTime(startAt: string, endAt: string | null, isAllDay: boolean): string {
  if (isAllDay) {
    return 'მთელი დღე'
  }
  const start = new Date(startAt)
  const end = endAt ? new Date(endAt) : null
  const timeLabel = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit'
  }).format(start)
  if (!end) {
    return timeLabel
  }
  const endLabel = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit'
  }).format(end)
  return `${timeLabel} - ${endLabel}`
}

function meetingTone(item: UpcomingMeetingItem): { label: string; color: string; bg: string } {
  const title = item.title.toLowerCase()
  if (title.includes('interview') || title.includes('candidate') || title.includes('hiring')) {
    return { label: 'დაქირავება', color: '#d97706', bg: 'rgba(245, 158, 11, 0.14)' }
  }
  if (title.includes('review') || title.includes('feedback') || title.includes('1:1')) {
    return { label: 'შეფასება', color: '#0284c7', bg: 'rgba(56, 189, 248, 0.14)' }
  }
  if (title.includes('payroll') || title.includes('approval') || title.includes('ops')) {
    return { label: 'ოპერაციები', color: '#0f766e', bg: 'rgba(20, 184, 166, 0.14)' }
  }
  return { label: 'შეხვედრა', color: '#334155', bg: 'rgba(51, 65, 85, 0.1)' }
}

function groupMeetings(items: UpcomingMeetingItem[]): Array<{ title: string; items: UpcomingMeetingItem[] }> {
  const now = new Date()
  const today = startOfDay(now)
  const tomorrow = new Date(today)
  tomorrow.setDate(tomorrow.getDate() + 1)
  const weekLimit = new Date(today)
  weekLimit.setDate(weekLimit.getDate() + 7)

  const grouped = {
    დღეს: [] as UpcomingMeetingItem[],
    ხვალ: [] as UpcomingMeetingItem[],
    'ამ კვირაში': [] as UpcomingMeetingItem[]
  }

  for (const item of items) {
    const start = new Date(item.start_at)
    const day = startOfDay(start)
    if (sameDay(day, today)) {
      grouped['დღეს'].push(item)
      continue
    }
    if (sameDay(day, tomorrow)) {
      grouped['ხვალ'].push(item)
      continue
    }
    if (day >= today && day < weekLimit) {
      grouped['ამ კვირაში'].push(item)
    }
  }

  return Object.entries(grouped)
    .filter(([, rows]) => rows.length > 0)
    .map(([title, rows]) => ({ title, items: rows }))
}

function KpiCard(props: {
  label: string
  value: string
  trend: string
  comparison: string
  context: string
  icon: typeof Users
  positive?: boolean
  onClick?: () => void
}) {
  const Icon = props.icon
  const TrendIcon = props.positive === false ? ArrowDownRight : ArrowUpRight

  return (
    <button
      type="button"
      className={`metric-card flex w-full flex-col gap-4 rounded-[24px] border border-white/55 text-left transition ${props.onClick ? 'hover:-translate-y-0.5 hover:shadow-[0_18px_34px_rgba(15,23,42,0.08)]' : ''}`}
      disabled={!props.onClick}
      onClick={props.onClick}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[rgba(var(--brand-primary-rgb),0.1)] text-[var(--brand-primary)] shadow-inner">
          <Icon className="h-5 w-5" />
        </div>
        <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold ${props.positive === false ? 'bg-rose-50 text-rose-600' : 'bg-emerald-50 text-emerald-600'}`}>
          <TrendIcon className="h-3.5 w-3.5" />
          {props.trend}
        </span>
      </div>
      <div>
        <p className="text-[12px] font-semibold uppercase tracking-[0.2em] text-slate-400">{props.label}</p>
        <p className="mt-3 text-[34px] font-semibold tracking-[-0.04em] text-slate-950">{props.value}</p>
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-slate-700">{props.comparison}</p>
        <p className="text-sm text-slate-500">{props.context}</p>
      </div>
    </button>
  )
}

export function MetricCards(props: MetricCardsProps) {
  const [activeMetric, setActiveMetric] = useState<ChartMetric>('attendance')
  const [timeRange, setTimeRange] = useState<TimeRange>('this_week')
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)

  const summary = props.summary ?? {
    scope: 'company',
    active_employees: 0,
    terminated_employees: 0,
    pending_approvals: 0,
    online_devices: 0,
    pending_leave_requests: 0,
    last_punch_at: null,
    last_punch_direction: null,
    is_checked_in: false,
  }
  const analytics = props.analytics ?? null
  const weeklyAttendance = props.weeklyAttendance ?? []
  const upcomingSchedule = props.upcomingSchedule ?? null
  const fallbackSeries = {
    labels: weeklyAttendance.length > 0 ? weeklyAttendance.map((item) => item.label) : ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    this_week: {
      attendance: weeklyAttendance.length > 0 ? weeklyAttendance.map((item) => item.count) : [0, 0, 0, 0, 0, 0, 0],
      late: [0, 0, 0, 0, 0, 0, 0],
      leave: [0, 0, 0, 0, 0, 0, 0],
      absences: [0, 0, 0, 0, 0, 0, 0]
    },
    last_week: {
      attendance: [0, 0, 0, 0, 0, 0, 0],
      late: [0, 0, 0, 0, 0, 0, 0],
      leave: [0, 0, 0, 0, 0, 0, 0],
      absences: [0, 0, 0, 0, 0, 0, 0]
    }
  }

  const labels = weeklyAttendance.length > 0 ? weeklyAttendance.map((item) => item.label) : ['ორშ', 'სამ', 'ოთხ', 'ხუთ', 'პარ', 'შაბ', 'კვი']
  const dashboardSeries = analytics?.dashboard_series ?? fallbackSeries
  const chartLabels = dashboardSeries.labels.length > 0 ? dashboardSeries.labels : labels
  const totalEmployees = Math.max(analytics?.staff_presence_ratio?.total ?? 0, summary.active_employees, ...dashboardSeries[timeRange].attendance, 0)

  const seriesMap = useMemo(() => dashboardSeries[timeRange], [dashboardSeries, timeRange])

  const activeSeries = seriesMap[activeMetric]
  const maxValue = Math.max(1, ...activeSeries)
  const gridValues = [maxValue, Math.round(maxValue * 0.66), Math.round(maxValue * 0.33), 0]
  const tone = chartTones[activeMetric]

  const presentNow = analytics?.staff_presence_ratio?.present ?? seriesMap.attendance[seriesMap.attendance.length - 1] ?? 0
  const absentNow = analytics?.staff_presence_ratio?.away ?? Math.max(0, totalEmployees - presentNow)
  const lateNow = seriesMap.late[seriesMap.late.length - 1] ?? 0
  const attendanceRate = totalEmployees ? Math.round((presentNow / totalEmployees) * 100) : 0
  const groupedSchedule = useMemo(() => groupMeetings(upcomingSchedule?.meetings ?? []), [upcomingSchedule?.meetings])
  const showSummaryCards = props.widgetVisibility?.summary_cards ?? true
  const showAnalytics = props.widgetVisibility?.analytics ?? true
  const showUpcomingSchedule = props.widgetVisibility?.upcoming_schedule ?? true

  const kpis = [
    {
      label: 'აქტიური თანამშრომლები',
      value: `${summary.active_employees}`,
      trend: `${summary.active_employees}`,
      comparison: 'გასულ კვირასთან შედარებით',
      context: `დღეს დასწრება ${attendanceRate}%`,
      icon: Users,
      positive: true,
      onClick: props.onOpenEmployees
    },
    {
      label: 'დღეს ადგილზე',
      value: `${presentNow}`,
      trend: `${presentNow}`,
      comparison: 'გუშინდელთან შედარებით',
      context: `ამჟამად გასულია ${absentNow}`,
      icon: UserCheck,
      positive: true,
      onClick: props.onViewAttendance
    },
    {
      label: 'მოლოდინში',
      value: `${summary.pending_approvals}`,
      trend: summary.pending_approvals === 0 ? '0' : `${Math.max(1, Math.round(summary.pending_approvals * 0.4))}`,
      comparison: summary.pending_approvals === 0 ? 'რიგი ცარიელია' : 'საჭიროებს განხილვას',
      context: summary.pending_approvals === 0 ? 'ყველა მოთხოვნა დამუშავებულია' : 'შვებულება და სახელფასო ქმედებები ღიაა',
      icon: BadgeCheck,
      positive: summary.pending_approvals < 3,
      onClick: props.onViewAttendance
    },
    {
      label: 'ონლაინ მოწყობილობები',
      value: `${summary.online_devices}`,
      trend: `${Math.max(0, summary.online_devices - Math.max(0, absentNow - lateNow))}`,
      comparison: 'ამჟამად ონლაინ',
      context: `${Math.max(0, totalEmployees - summary.online_devices)} წერტილი არ იუწყება`,
      icon: Fingerprint,
      positive: true
    }
  ] as const

  const personalLastPunchLabel = summary.last_punch_at
    ? new Intl.DateTimeFormat('en-GB', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit'
      }).format(new Date(summary.last_punch_at))
    : 'No punches yet'

  const scopedKpis = summary.scope === 'self'
    ? [
        {
          label: 'My Pending Leaves',
          value: `${summary.pending_leave_requests ?? summary.pending_approvals}`,
          trend: `${summary.pending_leave_requests ?? summary.pending_approvals}`,
          comparison: 'Open requests',
          context: 'Submitted requests waiting for decision',
          icon: CalendarClock,
          positive: (summary.pending_leave_requests ?? summary.pending_approvals) === 0,
          onClick: props.onViewAttendance
        },
        {
          label: 'Last Punch',
          value: summary.last_punch_direction ? summary.last_punch_direction.toUpperCase() : '--',
          trend: summary.last_punch_direction ? personalLastPunchLabel : 'No data',
          comparison: 'Latest attendance event',
          context: personalLastPunchLabel,
          icon: Fingerprint,
          positive: summary.last_punch_direction === 'in'
        },
        {
          label: 'Attendance Status',
          value: summary.is_checked_in ? 'IN' : 'OUT',
          trend: summary.is_checked_in ? 'Checked In' : 'Checked Out',
          comparison: 'Current day status',
          context: summary.is_checked_in ? 'You currently have an open work segment.' : 'No open work segment detected.',
          icon: UserCheck,
          positive: summary.is_checked_in
        },
        {
          label: 'This Week',
          value: `${weeklyAttendance.reduce((total, item) => total + item.count, 0)}`,
          trend: `${weeklyAttendance.filter((item) => item.count > 0).length} days`,
          comparison: 'Attendance activity',
          context: 'Days with recorded attendance activity this week',
          icon: CalendarPlus,
          positive: true,
          onClick: props.onViewAttendance
        }
      ] as const
    : kpis

  const hoveredValue = hoveredIndex != null ? activeSeries[hoveredIndex] : null
  const hasLeftPane = showSummaryCards || showAnalytics

  if (!hasLeftPane && !showUpcomingSchedule) {
    return null
  }

  return (
    <section className={hasLeftPane && showUpcomingSchedule ? 'grid gap-5 xl:grid-cols-[minmax(0,1.62fr)_minmax(340px,0.88fr)]' : 'grid gap-5'}>
      {hasLeftPane ? (
        <div className="space-y-5">
          {showSummaryCards ? (
            <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-4">
              {scopedKpis.map((item) => (
                <KpiCard
                  key={item.label}
                  label={item.label}
                  value={item.value}
                  trend={item.trend}
                  comparison={item.comparison}
                  context={item.context}
                  icon={item.icon}
                  positive={item.positive}
                  onClick={item.onClick}
                />
              ))}
            </div>
          ) : null}

          {showAnalytics ? (
            <article className="panel-card rounded-[30px] border border-white/55 p-5 sm:p-6">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="max-w-2xl">
              <p className="text-[12px] font-semibold uppercase tracking-[0.32em] text-slate-400">ძირითადი ანალიტიკა</p>
              <h2 className="mt-3 text-[30px] font-semibold tracking-[-0.04em] text-slate-950">თანამშრომელთა ანალიზი</h2>
              <p className="mt-2 text-sm leading-6 text-slate-500">
                კვირის ჭრილში დასწრება, დაგვიანება, შვებულება და არყოფნა, რათა HR-მა სწრაფად დაინახოს რისკები.
              </p>
            </div>
            <div className="flex w-full max-w-[38rem] flex-wrap items-center justify-end gap-2 self-start">
              {props.onViewAttendance ? (
                <button type="button" className="muted-btn px-4 py-2.5 text-xs" onClick={props.onViewAttendance}>
                  View Details
                </button>
              ) : null}
              {([
                ['this_week', 'ეს კვირა'],
                ['last_week', 'წინა კვირა']
              ] as Array<[TimeRange, string]>).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setTimeRange(key)}
                  className={`rounded-full px-3 py-2 text-[11px] font-semibold transition ${timeRange === key ? 'text-white shadow-[0_10px_20px_rgba(32,81,189,0.18)]' : 'border border-slate-200 bg-white/80 text-slate-600 hover:bg-slate-50'}`}
                  style={timeRange === key ? { background: '#2051BD' } : undefined}
                >
                  {label}
                </button>
              ))}
              {([
                ['attendance', 'დასწრება'],
                ['late', 'დაგვიანება'],
                ['leave', 'შვებულება'],
                ['absences', 'არყოფნა']
              ] as Array<[ChartMetric, string]>).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setActiveMetric(key)}
                  className={`min-w-[5.3rem] rounded-full px-2.5 py-2 text-center text-[11px] font-semibold transition ${activeMetric === key ? 'text-white' : 'border border-slate-200 bg-white/80 text-slate-600 hover:bg-slate-50'}`}
                  style={activeMetric === key ? { background: chartTones[key].dot } : undefined}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="relative mt-5 rounded-[28px] border border-slate-200/80 bg-[rgba(255,255,255,0.68)] px-4 py-4 sm:px-5">
            {hoveredIndex != null && hoveredValue != null ? (
              <div
                className="pointer-events-none absolute z-10 rounded-2xl border border-slate-200 bg-white/95 px-3 py-2 shadow-xl"
                style={{ left: `calc(${((hoveredIndex + 0.5) / activeSeries.length) * 100}% - 76px)`, top: 16 }}
              >
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">{chartLabels[hoveredIndex]}</p>
                <p className="mt-1 text-sm font-semibold text-slate-900">{hoveredValue}</p>
              </div>
            ) : null}

            <div className="grid grid-cols-[40px_minmax(0,1fr)] gap-3">
              <div className="relative h-[14rem]">
                {gridValues.map((value, index) => (
                  <div key={`${value}-${index}`} className="absolute left-0 text-[11px] font-medium text-slate-400" style={{ bottom: `${(value / maxValue) * 100}%`, transform: 'translateY(50%)' }}>
                    {value}
                  </div>
                ))}
              </div>

              <div className="relative h-[14rem]">
                {gridValues.map((value, index) => (
                  <div key={`line-${value}-${index}`} className="absolute left-0 right-0 border-t border-dashed border-slate-200/90" style={{ bottom: `${(value / maxValue) * 100}%` }} />
                ))}

                <div className="relative grid h-full grid-cols-7 gap-2.5 pt-2">
                  {activeSeries.map((value, index) => {
                    const barHeight = value <= 0 ? 0 : (value / maxValue) * 100
                    return (
                      <div
                        key={`${chartLabels[index]}-${activeMetric}`}
                        className="flex h-full flex-col justify-end"
                        onMouseEnter={() => setHoveredIndex(index)}
                        onMouseLeave={() => setHoveredIndex(null)}
                      >
                        <div className="flex flex-1 items-end justify-center">
                          <div className="flex h-full w-full flex-col justify-end">
                            <div
                              className="w-full rounded-[18px] border border-white/50 transition duration-200"
                              style={{
                                height: `${barHeight}%`,
                                background: hoveredIndex === index ? tone.bar : tone.bar,
                                boxShadow: hoveredIndex === index ? '0 14px 24px rgba(15,23,42,0.14)' : '0 10px 18px rgba(15,23,42,0.08)'
                              }}
                            />
                            <div className="mt-2 h-1.5 rounded-full" style={{ background: tone.barSoft }} />
                          </div>
                        </div>
                        <div className="mt-2 text-center">
                          <p className="text-xs font-semibold text-slate-600">{chartLabels[index]}</p>
                          <p className="mt-1 text-[11px] text-slate-400">{value}</p>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
            </article>
          ) : null}
        </div>
      ) : null}

      {showUpcomingSchedule ? (
      <article className="panel-card flex min-h-[34rem] flex-col rounded-[30px] border border-white/55 p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[12px] font-semibold uppercase tracking-[0.24em] text-slate-400">მარჯვენა პანელი</p>
            <h3 className="mt-2 text-[24px] font-semibold tracking-[-0.03em] text-slate-950">მომავალი განრიგი</h3>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              {upcomingSchedule?.connected ? `დაკავშირებულია: ${upcomingSchedule.google_email ?? 'Google Calendar'}` : 'თქვენი შემდეგი შეხვედრები და გუნდის ჩანაწერები ერთ სივრცეში.'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {upcomingSchedule?.connected ? (
              <>
                <a
                  className="primary-btn px-3 py-2 text-xs"
                  href="https://calendar.google.com/calendar/u/0/r/eventedit"
                  target="_blank"
                  rel="noreferrer"
                >
                  <CalendarPlus className="h-4 w-4" />
                  ღონისძიების შექმნა
                </a>
                <button
                  type="button"
                  className="muted-btn px-3 py-2 text-xs"
                  onClick={props.onDisconnectGoogleCalendar}
                  disabled={props.calendarBusy}
                >
                  <Unplug className="h-4 w-4" />
                  გათიშვა
                </button>
              </>
            ) : (
              <button
                type="button"
                className="primary-btn px-3 py-2 text-xs"
                onClick={props.onConnectGoogleCalendar}
                disabled={props.calendarBusy}
              >
                <Link2 className="h-4 w-4" />
                დაკავშირება
              </button>
            )}
          </div>
        </div>

        <div className="mt-4 flex-1 overflow-hidden">
          <div className="h-full space-y-4 overflow-y-auto pr-1">
            {!upcomingSchedule?.configured ? (
              <div className="rounded-[24px] border border-dashed border-slate-200 bg-white/70 px-5 py-10 text-center text-sm text-slate-500">
                Google Calendar ჯერ არ არის კონფიგურირებული ამ სერვერზე.
              </div>
            ) : null}

            {upcomingSchedule?.configured && !upcomingSchedule.connected ? (
              <div className="rounded-[24px] border border-dashed border-slate-200 bg-white/70 px-5 py-10 text-center text-sm text-slate-500">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[rgba(var(--brand-primary-rgb),0.12)] text-[var(--brand-primary)]">
                  <CalendarClock className="h-5 w-5" />
                </div>
                <p className="font-medium text-slate-700">დააკავშირეთ სამუშაო Google Calendar, რომ აქ გამოჩნდეს შეხვედრები.</p>
                {upcomingSchedule.error ? <p className="mt-2 text-xs text-rose-600">{upcomingSchedule.error}</p> : null}
              </div>
            ) : null}

            {upcomingSchedule?.connected && groupedSchedule.length === 0 ? (
              <div className="rounded-[24px] border border-dashed border-slate-200 bg-white/70 px-5 py-10 text-center text-sm text-slate-500">
                დაკავშირებულ Google Calendar-ში მომავალი შეხვედრები ვერ მოიძებნა.
              </div>
            ) : null}

            {upcomingSchedule?.connected
              ? groupedSchedule.map((group) => (
                  <section key={group.title} className="space-y-3">
                    <div className="flex items-center justify-between">
                      <h4 className="text-[12px] font-semibold uppercase tracking-[0.24em] text-slate-400">{group.title}</h4>
                      <span className="text-xs text-slate-400">{group.items.length} ჩანაწერი</span>
                    </div>

                    <div className="space-y-3">
                      {group.items.map((item) => {
                        const badge = meetingTone(item)
                        return (
                          <div key={item.id} className="rounded-[24px] border border-slate-200/80 bg-white/82 p-4 shadow-sm shadow-slate-900/5">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: badge.color }} />
                                  <span className="rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ background: badge.bg, color: badge.color }}>
                                    {badge.label}
                                  </span>
                                </div>
                                <p className="mt-3 text-base font-semibold text-slate-950">{item.title}</p>
                                <p className="mt-1 text-sm text-slate-500">{item.organizer ?? 'Google Calendar ღონისძიება'}</p>
                              </div>
                              {item.link ? (
                                <div className="flex shrink-0 items-center gap-2">
                                  {item.employee_id && props.onSendMessage ? (
                                    <button
                                      type="button"
                                      className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-600 transition hover:bg-[rgba(var(--brand-primary-rgb),0.12)] hover:text-[var(--brand-primary)]"
                                      onClick={() => props.onSendMessage?.(item.employee_id!, item.employee_name ?? item.organizer ?? 'Employee')}
                                      aria-label="Send message"
                                    >
                                      <MessageSquareShare className="h-4 w-4" />
                                    </button>
                                  ) : null}
                                  <a
                                    className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2.5 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-200"
                                    href={item.link}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    გახსნა
                                    <ExternalLink className="h-3.5 w-3.5" />
                                  </a>
                                </div>
                              ) : item.employee_id && props.onSendMessage ? (
                                <button
                                  type="button"
                                  className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-600 transition hover:bg-[rgba(var(--brand-primary-rgb),0.12)] hover:text-[var(--brand-primary)]"
                                  onClick={() => props.onSendMessage?.(item.employee_id!, item.employee_name ?? item.organizer ?? 'Employee')}
                                  aria-label="Send message"
                                >
                                  <MessageSquareShare className="h-4 w-4" />
                                </button>
                              ) : null}
                            </div>
                            <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                              <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-600">
                                <CalendarClock className="h-3.5 w-3.5" />
                                {formatMeetingTime(item.start_at, item.end_at, item.is_all_day)}
                              </span>
                              {item.location ? <span className="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-600">{item.location}</span> : null}
                              {item.employee_name ? <span className="rounded-full bg-[rgba(var(--brand-primary-rgb),0.1)] px-2.5 py-1 font-semibold text-[var(--brand-primary)]">{item.employee_name}</span> : null}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </section>
                ))
              : null}
          </div>
        </div>

        <div className="mt-4 rounded-[24px] border border-slate-200/70 bg-white/72 p-3.5">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-full bg-[rgba(var(--brand-primary-rgb),0.1)] text-[var(--brand-primary)]">
              <CircleAlert className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <p className="font-semibold text-slate-900">კალენდრის მოქმედებები</p>
              <p className="mt-1 text-sm text-slate-500">
                {upcomingSchedule?.connected ? 'შექმენით ახალი ჩანაწერი ან გახსენით არსებული შეხვედრა პირდაპირ ამ პანელიდან.' : 'დააკავშირეთ კალენდარი, რომ ჩაირთოს ჯგუფური განრიგი, ბმულები და სწრაფი ქმედებები.'}
              </p>
            </div>
          </div>
        </div>
      </article>
      ) : null}
    </section>
  )
}
