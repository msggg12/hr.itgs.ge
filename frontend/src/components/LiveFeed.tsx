import { useState } from 'react'

import { MessageSquareShare, MoreVertical, WifiOff } from 'lucide-react'

import { ka } from '../i18n/ka'
import type { FeedEvent } from '../types'
import { formatDateTime, initials } from '../utils'

function toneClasses(event: FeedEvent): string {
  if (event.device_status === 'offline') {
    return 'bg-rose-50 text-rose-600'
  }
  if (event.direction === 'out') {
    return 'bg-amber-50 text-amber-600'
  }
  return 'bg-emerald-50 text-emerald-600'
}

type LiveFeedProps = {
  feed: FeedEvent[]
  onViewDetails?: (event: FeedEvent) => void
  onSendMessage?: (employeeId: string, employeeName: string) => void
}

export function LiveFeed(props: LiveFeedProps) {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)

  return (
    <article className="panel-card p-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">{ka.monitoringCenter}</h2>
          <p className="mt-1 text-sm text-slate-500">{ka.liveAttendanceFeed} - device / სისტემური ჩანაწერები</p>
        </div>
      </div>

      <div className="mt-5 space-y-4">
        {props.feed.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-10 text-center text-sm text-slate-500">{ka.noEvents}</div>
        ) : null}

        {props.feed.slice(0, 5).map((event) => {
          const menuId = `${event.event_type}-${event.event_id}`
          const employeeName = `${event.first_name ?? ''} ${event.last_name ?? ''}`.trim()
          return (
            <div key={menuId} className="flex items-start gap-3 rounded-2xl border border-slate-100 bg-white p-3">
              <div className="flex h-11 w-11 items-center justify-center overflow-hidden rounded-full bg-slate-100 text-sm font-semibold text-slate-700">
                {event.device_status === 'offline' ? <WifiOff className="h-4 w-4" /> : initials(event.first_name, event.last_name)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="truncate font-semibold text-slate-900">
                        {event.device_status === 'offline'
                          ? `${ka.deviceOffline}: ${event.device_name}`
                          : `${event.first_name ?? ''} ${event.last_name ?? ''}`}
                      </p>
                      {event.employee_id && props.onSendMessage ? (
                        <button
                          type="button"
                          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-600 transition hover:bg-[rgba(var(--brand-primary-rgb),0.12)] hover:text-[var(--brand-primary)]"
                          onClick={() => props.onSendMessage?.(event.employee_id!, employeeName)}
                          aria-label="Send message"
                        >
                          <MessageSquareShare className="h-4 w-4" />
                        </button>
                      ) : null}
                    </div>
                    <p className="mt-1 truncate text-sm text-slate-500">
                      {event.device_status === 'offline'
                        ? `${event.location_name ?? event.device_name} • ${event.host}`
                        : `${event.direction === 'out' ? ka.exit : ka.entry} • ${event.employee_number ?? '-'} • ${event.location_name ?? event.device_name}`}
                    </p>
                  </div>

                  <div className="relative">
                    <button
                      type="button"
                      className="rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                      onClick={() => setOpenMenuId((current) => (current === menuId ? null : menuId))}
                    >
                      <MoreVertical className="h-4 w-4" />
                    </button>
                    {openMenuId === menuId ? (
                      <div className="absolute right-0 top-10 z-20 min-w-[11rem] rounded-2xl border border-slate-200 bg-white p-2 shadow-[0_18px_40px_rgba(15,23,42,0.14)]">
                        <button
                          type="button"
                          className="flex w-full items-center rounded-xl px-3 py-2 text-left text-sm font-medium text-slate-700 transition hover:bg-slate-100"
                          onClick={() => {
                            props.onViewDetails?.(event)
                            setOpenMenuId(null)
                          }}
                        >
                          View Details
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${toneClasses(event)}`}>
                    {event.device_status === 'offline' ? 'Device' : event.direction === 'out' ? 'OUT' : 'IN'}
                  </span>
                  <span className="text-xs text-slate-400">{formatDateTime(event.ts)}</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </article>
  )
}
