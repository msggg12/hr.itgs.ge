import { Activity, BadgeCheck } from 'lucide-react'
import { CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { ka } from '../i18n/ka'
import type { AnalyticsOverview } from '../types'

export function Insights(props: { analytics: AnalyticsOverview | null }) {
  const staffPresenceRatio = props.analytics?.staff_presence_ratio
  const presenceData = props.analytics
    ? [
        { name: ka.presentNow, value: staffPresenceRatio?.present ?? 0, color: '#10b981' },
        { name: ka.awayNow, value: staffPresenceRatio?.away ?? 0, color: '#2563eb' }
      ]
    : []

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <article className="panel-card">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">{ka.weeklyHoursTrend}</h2>
            <p className="mt-1 text-sm text-slate-500">{ka.attendance}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-action-600">
            <Activity className="h-5 w-5" />
          </div>
        </div>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={props.analytics?.weekly_hours_trend ?? []}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 12 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 12 }} axisLine={false} tickLine={false} />
              <Tooltip />
              <Line type="monotone" dataKey="worked_hours" stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </article>

      <article className="panel-card">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">{ka.staffPresenceRatio}</h2>
            <p className="mt-1 text-sm text-slate-500">{ka.monitoringCenter}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-emerald-600">
            <BadgeCheck className="h-5 w-5" />
          </div>
        </div>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={presenceData} dataKey="value" nameKey="name" innerRadius={74} outerRadius={104} paddingAngle={4}>
                {presenceData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {presenceData.map((entry) => (
            <div key={entry.name} className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: entry.color }} />
                {entry.name}
              </div>
              <p className="mt-2 text-2xl font-semibold tracking-[-0.02em] text-slate-950">{entry.value}</p>
            </div>
          ))}
        </div>
      </article>
    </div>
  )
}
