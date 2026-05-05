import { useMemo } from 'react'

import { CalendarClock, CalendarPlus, ExternalLink, Link2, MessageSquareShare, Unplug } from 'lucide-react'

import type { UpcomingMeetingItem, UpcomingScheduleData } from '../types'

export type UpcomingSchedulePanelProps = {
  upcomingSchedule: UpcomingScheduleData | null
  calendarBusy?: boolean
  onConnectGoogleCalendar?: () => void
  onDisconnectGoogleCalendar?: () => void
  onSendMessage?: (employeeId: string, employeeName: string) => void
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

export function UpcomingSchedulePanel(props: UpcomingSchedulePanelProps) {
  const upcomingSchedule = props.upcomingSchedule ?? null
  const groupedSchedule = useMemo(() => groupMeetings(upcomingSchedule?.meetings ?? []), [upcomingSchedule?.meetings])

  return (
    <article className="panel-card flex min-h-[34rem] flex-col rounded-[30px] border border-white/55 p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[12px] font-semibold uppercase tracking-[0.24em] text-slate-400">Google Calendar</p>
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
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[rgba(var(--brand-primary-rgb),0.1)] text-[var(--brand-primary)]">
            <CalendarClock className="h-5 w-5" />
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
  )
}
