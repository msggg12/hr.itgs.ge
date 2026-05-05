import { Cake, MessageSquareShare, Sparkles } from 'lucide-react'

import { ka } from '../i18n/ka'
import type { CelebrationHubData } from '../types'
import { formatDate, initials } from '../utils'

type CelebrationWidgetProps = {
  data: CelebrationHubData | null
  onSendMessage?: (employeeId: string, employeeName: string) => void
}

export function CelebrationWidget(props: CelebrationWidgetProps) {
  return (
    <article className="panel-card">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">იუბილარების დაფა</h2>
          <p className="mt-1 text-sm text-slate-500">{ka.upcomingBirthdays}</p>
        </div>
        <div className="brand-soft rounded-lg border border-slate-200 p-3">
          <Sparkles className="h-5 w-5" />
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <section>
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-slate-400">{ka.upcomingBirthdays}</h3>
          <div className="space-y-3">
            {(props.data?.birthdays ?? []).map((item) => (
              <div key={item.id} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-rose-100 text-xs font-bold text-rose-700">
                  {initials(item.first_name, item.last_name)}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-slate-950">{item.first_name} {item.last_name}</p>
                  <p className="text-xs text-slate-500">{formatDate(item.date)}</p>
                </div>
                {props.onSendMessage ? (
                  <button
                    type="button"
                    className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-600 transition hover:bg-[rgba(var(--brand-primary-rgb),0.12)] hover:text-[var(--brand-primary)]"
                    onClick={() => props.onSendMessage?.(item.id, `${item.first_name} ${item.last_name}`)}
                    aria-label="Send message"
                  >
                    <MessageSquareShare className="h-4 w-4" />
                  </button>
                ) : null}
                <Cake className="h-4 w-4 text-rose-500" />
              </div>
            ))}
          </div>
        </section>

        <section>
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-slate-400">{ka.workAnniversaries}</h3>
          <div className="space-y-3">
            {(props.data?.anniversaries ?? []).map((item) => (
              <div key={item.id} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-amber-100 text-xs font-bold text-amber-700">
                  {initials(item.first_name, item.last_name)}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-slate-950">{item.first_name} {item.last_name}</p>
                  <p className="text-xs text-slate-500">{item.years_completed ?? 0} years - {formatDate(item.date)}</p>
                </div>
                {props.onSendMessage ? (
                  <button
                    type="button"
                    className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-600 transition hover:bg-[rgba(var(--brand-primary-rgb),0.12)] hover:text-[var(--brand-primary)]"
                    onClick={() => props.onSendMessage?.(item.id, `${item.first_name} ${item.last_name}`)}
                    aria-label="Send message"
                  >
                    <MessageSquareShare className="h-4 w-4" />
                  </button>
                ) : null}
                <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700">{item.years_completed ?? 0}y</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </article>
  )
}
