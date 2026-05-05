import { Trophy } from 'lucide-react'

import type { AnalyticsOverview } from '../types'
import { classNames } from '../utils'

export function TopPerformers(props: { analytics: AnalyticsOverview | null }) {
  const rows = props.analytics?.top_performers ?? []

  return (
    <article className="panel-card border border-slate-200/80 bg-white shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <p className="section-kicker">ეფექტიანობა</p>
          <h2 className="section-title text-xl">ტოპ 3 შემსრულება</h2>
          <p className="mt-1 text-sm text-slate-500">(სამუშაო საათები / გეგმილი) − სანქციები</p>
        </div>
        <div className="rounded-xl border border-amber-100 bg-amber-50 p-3 text-amber-700">
          <Trophy className="h-5 w-5" />
        </div>
      </div>
      <div className="space-y-3">
        {rows.length ? (
          rows.map((row, index) => (
            <div
              key={row.employee_id}
              className="flex items-center justify-between gap-3 rounded-xl border border-slate-100 bg-slate-50/80 px-4 py-3"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--brand-primary)] text-xs font-bold text-white">
                  {index + 1}
                </span>
                <div className="min-w-0">
                  <p className="truncate font-semibold text-slate-900">{row.full_name}</p>
                  <p className="text-xs text-slate-500">Score {(row.score * 100).toFixed(1)}%</p>
                </div>
              </div>
              <span
                className={classNames(
                  'shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide',
                  row.status === 'present' && 'bg-emerald-100 text-emerald-800',
                  row.status === 'late' && 'bg-amber-100 text-amber-800',
                  row.status === 'absent' && 'bg-rose-100 text-rose-800'
                )}
              >
                {row.status === 'present' ? 'აქ' : row.status === 'late' ? 'დაგვიანება' : 'არა'}
              </span>
            </div>
          ))
        ) : (
          <p className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">No data available</p>
        )}
      </div>
    </article>
  )
}
