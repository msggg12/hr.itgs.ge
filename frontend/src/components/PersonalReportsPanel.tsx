import { Clock3, MapPinned } from 'lucide-react'

import type { PersonalReportsData } from '../types'
import { formatDateTime } from '../utils'

type PersonalReportsPanelProps = {
  data: PersonalReportsData | null
}

export function PersonalReportsPanel(props: PersonalReportsPanelProps) {
  return (
    <section className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
      <section className="panel-card space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="section-kicker">ESS Reports</p>
            <h2 className="section-title">მოძრაობის ლოგი</h2>
          </div>
          <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
            {props.data?.summary?.month_start ?? '-'}
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Late Days</div>
            <div className="mt-2 text-2xl font-semibold text-rose-700">{props.data?.summary?.late_days ?? 0}</div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-xs uppercase tracking-[0.2em] text-slate-400">OT Hours</div>
            <div className="mt-2 text-2xl font-semibold text-amber-700">{props.data?.summary?.overtime_hours ?? 0}</div>
          </div>
        </div>
        <div className="space-y-3">
          {(props.data?.movement_log ?? []).map((item) => (
            <div key={item.id} className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-4 py-3">
              <div>
                <div className="font-medium text-slate-900">{item.device_name}</div>
                <div className="mt-1 text-xs text-slate-500">{formatDateTime(item.event_ts)} • {item.source_type}</div>
              </div>
              <div className={`rounded-full px-3 py-1 text-xs font-semibold ${item.direction === 'out' ? 'bg-sky-50 text-sky-700' : 'bg-emerald-50 text-emerald-700'}`}>
                {item.direction.toUpperCase()}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel-card space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="section-kicker">Monthly Control</p>
            <h2 className="section-title">დაგვიანება და ზეგანაკვეთური</h2>
          </div>
          <Clock3 className="h-5 w-5 text-slate-400" />
        </div>
        <div className="space-y-3">
          {(props.data?.lateness_overtime_report ?? []).slice(0, 20).map((item) => (
            <div key={`${item.id}-${item.event_ts}`} className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="font-medium text-slate-900">{formatDateTime(item.event_ts)}</div>
                  <div className="mt-1 text-xs text-slate-500">{item.device_name ?? 'Device N/A'}</div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {item.is_late ? <span className="rounded-full bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-700">Late {item.late_minutes}m</span> : null}
                  {item.is_overtime ? <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">OT {item.overtime_minutes}m</span> : null}
                </div>
              </div>
            </div>
          ))}
          {!props.data?.lateness_overtime_report?.length ? (
            <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-5 py-10 text-sm text-slate-500">
              <MapPinned className="mb-3 h-5 w-5 text-slate-400" />
              მიმდინარე თვეში ჩანაწერები ჯერ არ არის.
            </div>
          ) : null}
        </div>
      </section>
    </section>
  )
}
