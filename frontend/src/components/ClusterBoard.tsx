import { Cpu, HardDrive, ServerCog } from 'lucide-react'

import { ka } from '../i18n/ka'
import type { MonitoringData } from '../types'
import { classNames, formatDateTime } from '../utils'

export function ClusterBoard(props: { monitoring: MonitoringData | null }) {
  return (
    <article className="panel-card">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">{ka.clusterBoard}</h2>
          <p className="mt-1 text-sm text-slate-500">{ka.connectivity}</p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-action-600">
          <ServerCog className="h-5 w-5" />
        </div>
      </div>

      <div className="space-y-4">
        {props.monitoring?.nodes?.map((node, index) => {
          const details = (node.details ?? node.metadata ?? {}) as Record<string, unknown>
          const cpu = Number(details.cpu_percent ?? 0)
          const memory = Number(details.memory_percent ?? 0)
          const online = (node.status ?? 'down') === 'ok'
          return (
            <div key={`${node.node_code}-${node.service_name ?? index}`} className="rounded-xl border border-slate-200 bg-white p-5">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">{node.node_role}</p>
                  <h3 className="mt-2 text-lg font-semibold text-slate-950">{node.node_code}</h3>
                  <p className="mt-1 text-sm text-slate-500">{node.base_url ?? node.region ?? '-'}</p>
                </div>
                <div className={classNames('rounded-full border px-3 py-1 text-xs font-semibold', online ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700')}>
                  {online ? ka.online : ka.offline}
                </div>
              </div>
              <div className="mt-5 grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                  <div className="flex items-center justify-between text-sm text-slate-600">
                    <span className="inline-flex items-center gap-2"><Cpu className="h-4 w-4" />{ka.cpu}</span>
                    <span>{cpu.toFixed(1)}%</span>
                  </div>
                  <div className="mt-3 h-2 rounded-full bg-slate-200">
                    <div className="h-full rounded-full bg-action-500" style={{ width: `${Math.min(cpu, 100)}%` }} />
                  </div>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                  <div className="flex items-center justify-between text-sm text-slate-600">
                    <span className="inline-flex items-center gap-2"><HardDrive className="h-4 w-4" />{ka.memory}</span>
                    <span>{memory.toFixed(1)}%</span>
                  </div>
                  <div className="mt-3 h-2 rounded-full bg-slate-200">
                    <div className="h-full rounded-full bg-emerald-500" style={{ width: `${Math.min(memory, 100)}%` }} />
                  </div>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between text-xs uppercase tracking-[0.18em] text-slate-400">
                <span>{node.service_name ?? 'api'}</span>
                <span>{formatDateTime(node.last_heartbeat_at)}</span>
              </div>
            </div>
          )
        })}
      </div>
    </article>
  )
}
