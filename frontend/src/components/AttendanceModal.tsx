import { ka } from '../i18n/ka'
import type { AttendanceHistoryItem } from '../types'
import { classNames, formatDateTime } from '../utils'

type AttendanceModalProps = {
  open: boolean
  employeeName: string
  rows: AttendanceHistoryItem[]
  onClose: () => void
}

export function AttendanceModal(props: AttendanceModalProps) {
  if (!props.open) {
    return null
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4 backdrop-blur-sm">
      <div className="w-full max-w-3xl rounded-xl border border-slate-200 bg-white p-6 shadow-panel">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">{ka.attendanceHistory}</p>
            <h3 className="mt-2 text-2xl font-semibold text-slate-950">{props.employeeName}</h3>
          </div>
          <button type="button" className="muted-btn px-4 py-2" onClick={props.onClose}>
            {ka.close}
          </button>
        </div>
        <div className="max-h-[60vh] overflow-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-[0.18em] text-slate-400">
              <tr>
                <th className="px-3 py-3">{ka.status}</th>
                <th className="px-3 py-3">{ka.device}</th>
                <th className="px-3 py-3">{ka.monitoringCenter}</th>
                <th className="px-3 py-3">{ka.attendanceDetail}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {props.rows.map((row, index) => (
                <tr key={`${row.id}-${index}`} className="bg-white hover:bg-slate-50">
                  <td className="px-3 py-3">
                    <span className={classNames('rounded-full px-3 py-1 text-xs font-semibold', row.direction === 'out' ? 'bg-action-50 text-action-600' : 'bg-emerald-50 text-emerald-700')}>
                      {row.direction === 'out' ? ka.exit : ka.entry}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-slate-700">{row.device_name ?? '-'}</td>
                  <td className="px-3 py-3 text-slate-500">{formatDateTime(row.event_ts)}</td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-2">
                      {row.is_late ? (
                        <span className="rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700">
                          {ka.lateArrival}: {row.late_minutes ?? 0}m
                        </span>
                      ) : null}
                      {row.is_overtime ? (
                        <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700">
                          {ka.overtime}: {row.overtime_minutes ?? 0}m
                        </span>
                      ) : null}
                      {!row.is_late && !row.is_overtime ? (
                        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
                          {Math.round((row.weekly_minutes ?? 0) / 60)}h / 40h
                        </span>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
