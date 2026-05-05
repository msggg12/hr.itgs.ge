import { useMemo, useState } from 'react'

import { Download, FileSpreadsheet, LockKeyhole, RefreshCw, Wallet } from 'lucide-react'

import { downloadFile } from '../api'
import type { PayrollHubData } from '../types'
import { formatMoney } from '../utils'

async function triggerDownload(path: string, fallbackName?: string) {
  const { blob, fileName } = await downloadFile(path)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName ?? fallbackName ?? 'download.bin'
  anchor.click()
  URL.revokeObjectURL(url)
}

type PayrollHubProps = {
  data: PayrollHubData | null
  monthValue: string
  departmentId: string
  onMonthChange: (value: string) => void
  onDepartmentChange: (value: string) => void
  onGenerateDraft: () => Promise<void>
  onMarkPaid: (timesheetId: string, payload: { payment_method: string; payment_reference: string | null; note: string | null }) => Promise<void>
}

export function PayrollHub(props: PayrollHubProps) {
  const [busyId, setBusyId] = useState('')
  const [draftBusy, setDraftBusy] = useState(false)

  const exportPath = useMemo(() => {
    if (!props.data) {
      return ''
    }
    const suffix = props.departmentId ? `?department_id=${encodeURIComponent(props.departmentId)}` : ''
    return `/payroll/export/${props.data.year}/${props.data.month}${suffix}`
  }, [props.data, props.departmentId])

  async function handleMarkPaid(timesheetId: string) {
    setBusyId(timesheetId)
    try {
      await props.onMarkPaid(timesheetId, {
        payment_method: 'bank_transfer',
        payment_reference: `AUTO-${Date.now()}`,
        note: 'Locked from payroll hub'
      })
    } finally {
      setBusyId('')
    }
  }

  async function handleGenerateDraft() {
    setDraftBusy(true)
    try {
      await props.onGenerateDraft()
    } finally {
      setDraftBusy(false)
    }
  }

  return (
    <section className="glass-panel p-5">
      <div className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-action-400">Payroll Engine</p>
          <h2 className="mt-2 text-xl font-semibold text-navy-900">ხელფასების draft გენერაცია და გადახდები</h2>
          <p className="mt-1 text-sm text-slatepro-500">აირჩიეთ თვე და დეპარტამენტი, შექმენით monthly draft და შემდეგ დააფიქსირეთ გადახდები payslip-ებთან ერთად.</p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <label className="space-y-1">
            <span className="text-xs font-semibold uppercase tracking-[0.24em] text-slatepro-400">Month</span>
            <input
              type="month"
              value={props.monthValue}
              onChange={(event) => props.onMonthChange(event.target.value)}
              className="w-full rounded-2xl border border-slatepro-200 bg-white px-3 py-2.5 text-sm text-slatepro-700 outline-none transition focus:border-action-400"
            />
          </label>

          <label className="space-y-1">
            <span className="text-xs font-semibold uppercase tracking-[0.24em] text-slatepro-400">Department</span>
            <select
              value={props.departmentId}
              onChange={(event) => props.onDepartmentChange(event.target.value)}
              className="w-full rounded-2xl border border-slatepro-200 bg-white px-3 py-2.5 text-sm text-slatepro-700 outline-none transition focus:border-action-400"
            >
              <option value="">ყველა დეპარტამენტი</option>
              {(props.data?.departments ?? []).map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name_ka ?? department.name_en ?? department.code ?? department.id}
                </option>
              ))}
            </select>
          </label>

          <div className="flex items-end gap-2">
            <button
              type="button"
              className="brand-button inline-flex w-full items-center justify-center gap-2 rounded-2xl px-4 py-3 font-semibold text-white"
              onClick={() => void handleGenerateDraft()}
              disabled={draftBusy || !props.data?.permissions.can_generate_draft}
            >
              <RefreshCw className={`h-4 w-4 ${draftBusy ? 'animate-spin' : ''}`} />
              {draftBusy ? 'გენერირდება...' : 'Monthly Draft'}
            </button>
            <button
              type="button"
              className="inline-flex items-center justify-center gap-2 rounded-2xl border border-slatepro-200 bg-white px-4 py-3 text-sm font-semibold text-slatepro-700"
              onClick={() => exportPath && void triggerDownload(exportPath)}
              disabled={!exportPath || !props.data?.permissions.can_export}
            >
              <Download className="h-4 w-4" />
              CSV
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-4">
        {(props.data?.items ?? []).map((item) => (
          <article key={item.id} className="rounded-[28px] border border-slatepro-100 bg-white p-4">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <p className="font-semibold text-navy-900">{item.employee_name} • {item.employee_number}</p>
                <div className="mt-2 flex flex-wrap gap-3 text-sm text-slatepro-500">
                  <span>{item.department_name ?? 'No department'}</span>
                  <span>{item.salary_type === 'hourly' ? 'Hourly' : 'Monthly Fixed'}</span>
                  <span>Base: {formatMoney(item.base_salary)}</span>
                  <span>Worked: {item.worked_hours}h</span>
                  <span>OT: {item.overtime_hours}h</span>
                  <span>Gross: {formatMoney(item.gross_pay)}</span>
                  <span>Net: {formatMoney(item.net_pay)}</span>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <span className={`rounded-full px-3 py-1 text-xs font-semibold ${item.status === 'locked' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                  {item.status}
                </span>
                {props.data ? (
                  <>
                    <button
                      type="button"
                      className="inline-flex items-center gap-2 rounded-2xl border border-slatepro-200 bg-white px-4 py-3 text-sm font-semibold text-slatepro-700"
                      onClick={() =>
                        void triggerDownload(
                          `/timesheets/${item.employee_id}/${props.data!.year}/${props.data!.month}/export.xlsx`,
                          `timesheet_${item.employee_number}_${props.data!.year}_${props.data!.month}.xlsx`
                        )
                      }
                    >
                      <FileSpreadsheet className="h-4 w-4" />
                      Excel
                    </button>
                    <button
                      type="button"
                      className="inline-flex items-center gap-2 rounded-2xl border border-slatepro-200 bg-white px-4 py-3 text-sm font-semibold text-slatepro-700"
                      onClick={() =>
                        void triggerDownload(
                          `/timesheets/${item.employee_id}/${props.data!.year}/${props.data!.month}/export.pdf`,
                          `timesheet_${item.employee_number}_${props.data!.year}_${props.data!.month}.pdf`
                        )
                      }
                    >
                      <Download className="h-4 w-4" />
                      PDF
                    </button>
                  </>
                ) : null}
                {item.payslip_url ? (
                  <a className="inline-flex items-center gap-2 rounded-2xl border border-slatepro-200 bg-white px-4 py-3 text-sm font-semibold text-slatepro-700" href={item.payslip_url} target="_blank" rel="noreferrer">
                    <Download className="h-4 w-4" />
                    Payslip PDF
                  </a>
                ) : null}
                {!item.payment_id ? (
                  <button type="button" className="brand-button inline-flex items-center gap-2 rounded-2xl px-4 py-3 font-semibold text-white" onClick={() => void handleMarkPaid(item.id)} disabled={busyId === item.id}>
                    <LockKeyhole className="h-4 w-4" />
                    {busyId === item.id ? 'მუშავდება...' : 'Mark as Paid'}
                  </button>
                ) : (
                  <div className="inline-flex items-center gap-2 rounded-2xl bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700">
                    <Wallet className="h-4 w-4" />
                    {item.payment_method ?? 'paid'}
                  </div>
                )}
              </div>
            </div>
          </article>
        ))}

        {props.data && props.data.items.length === 0 ? (
          <div className="rounded-[28px] border border-dashed border-slatepro-200 bg-white px-6 py-10 text-center text-sm text-slatepro-500">
            ამ თვე/დეპარტამენტისთვის payroll draft ჯერ არ არსებობს. გამოიყენეთ `Monthly Draft` ღილაკი.
          </div>
        ) : null}
      </div>
    </section>
  )
}
