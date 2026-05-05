import { AlertTriangle, BadgeCheck, BellRing, BriefcaseBusiness, ChevronRight, Fingerprint } from 'lucide-react'

import type { DashboardSummary, UpcomingScheduleData } from '../types'

type DashboardActionPanelProps = {
  summary: DashboardSummary | null
  upcomingSchedule: UpcomingScheduleData | null
  onOpenAttendance?: () => void
  onOpenEmployees?: () => void
}

function nextMeetingLabel(upcomingSchedule: UpcomingScheduleData | null): string {
  const nextMeeting = upcomingSchedule?.meetings?.[0]
  if (!nextMeeting) {
    return 'მომდევნო 7 დღეში შეხვედრა არ არის დაგეგმილი'
  }

  const start = new Date(nextMeeting.start_at)
  const label = new Intl.DateTimeFormat('ka-GE', {
    weekday: 'short',
    hour: 'numeric',
    minute: '2-digit'
  }).format(start)

  return `${nextMeeting.title} · ${label}`
}

export function DashboardActionPanel(props: DashboardActionPanelProps) {
  const summary = props.summary ?? {
    legal_entity_id: '',
    active_employees: 0,
    terminated_employees: 0,
    total_employees: 0,
    open_attendance_flags: 0,
    pending_leave_approvals: 0,
    devices_online: 0,
    offline_device_alerts: 0,
    open_offboarding_clearances: 0
  }

  const cards = [
    {
      title: 'დასამტკიცებელი მოთხოვნები',
      value: `${summary.pending_leave_approvals}`,
      detail: summary.pending_leave_approvals === 0 ? 'ყველა მოთხოვნა უკვე გადამოწმებულია.' : 'შვებულების მოთხოვნებს რეაგირება სჭირდება.',
      icon: BadgeCheck,
      tone: 'bg-amber-50 text-amber-700'
    },
    {
      title: 'მოწყობილობების შეტყობინებები',
      value: `${summary.offline_device_alerts}`,
      detail: summary.offline_device_alerts === 0 ? 'დასწრების ყველა მოწყობილობა გამართულად მუშაობს.' : 'მონიტორინგმა ოფლაინ ტერმინალები დააფიქსირა.',
      icon: Fingerprint,
      tone: 'bg-rose-50 text-rose-700'
    },
    {
      title: 'ოფბორდინგი',
      value: `${summary.open_offboarding_clearances}`,
      detail: summary.open_offboarding_clearances === 0 ? 'აქტიური ოფბორდინგის ქეისი არ ფიქსირდება.' : 'კლირენსისა და ფინალური გატარებების მონიტორინგი საჭიროა.',
      icon: BriefcaseBusiness,
      tone: 'bg-sky-50 text-sky-700'
    }
  ] as const

  const notices = [
    {
      title: 'დასწრების გამონაკლისები',
      body: summary.open_attendance_flags > 0 ? `${summary.open_attendance_flags} ღია attendance exception ელოდება განხილვას.` : 'ღია attendance exception ამჟამად არ ფიქსირდება.',
      icon: AlertTriangle
    },
    {
      title: 'შემდეგი შეხვედრა',
      body: nextMeetingLabel(props.upcomingSchedule),
      icon: BellRing
    }
  ] as const

  return (
    <article className="panel-card p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[12px] font-semibold uppercase tracking-[0.24em] text-slate-400">ქმედებების რიგი</p>
          <h2 className="mt-2 text-[24px] font-semibold tracking-[-0.03em] text-slate-950">ქმედებების ცენტრი</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">სწრაფი მიმოხილვა იმისა, რას უნდა მიაქციოს HR-მა ყურადღება ახლავე.</p>
        </div>
      </div>

      <div className="mt-5 grid gap-3">
        {cards.map((card) => {
          const Icon = card.icon
          return (
            <div key={card.title} className="rounded-[22px] border border-slate-200/80 bg-white/78 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className={`flex h-11 w-11 items-center justify-center rounded-full ${card.tone}`}>
                  <Icon className="h-5 w-5" />
                </div>
                <p className="text-3xl font-semibold tracking-[-0.03em] text-slate-950">{card.value}</p>
              </div>
              <p className="mt-4 text-sm font-semibold text-slate-900">{card.title}</p>
              <p className="mt-1 text-sm text-slate-500">{card.detail}</p>
            </div>
          )
        })}
      </div>

      <div className="mt-5 space-y-3">
        {notices.map((notice) => {
          const Icon = notice.icon
          return (
            <div key={notice.title} className="flex items-start gap-3 rounded-[22px] border border-slate-200/80 bg-white/72 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[rgba(var(--brand-primary-rgb),0.1)] text-[var(--brand-primary)]">
                <Icon className="h-4.5 w-4.5" />
              </div>
              <div className="min-w-0">
                <p className="font-semibold text-slate-900">{notice.title}</p>
                <p className="mt-1 text-sm text-slate-500">{notice.body}</p>
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-5 flex flex-wrap gap-3">
        <button type="button" className="primary-btn px-4 py-3 text-sm" onClick={props.onOpenAttendance}>
          დასწრების ნახვა
          <ChevronRight className="h-4 w-4" />
        </button>
        <button type="button" className="muted-btn px-4 py-3" onClick={props.onOpenEmployees}>
          თანამშრომლების გახსნა
        </button>
      </div>
    </article>
  )
}
