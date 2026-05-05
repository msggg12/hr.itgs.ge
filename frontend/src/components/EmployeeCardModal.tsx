import { CreditCard, Save, X } from 'lucide-react'

import type { GridItem } from '../types'

type EmployeeCardModalProps = {
  open: boolean
  employee: GridItem | null
  cardNumber: string
  busy: boolean
  onCardNumberChange: (value: string) => void
  onClose: () => void
  onSubmit: () => void
}

export function EmployeeCardModal(props: EmployeeCardModalProps) {
  if (!props.open || !props.employee) {
    return null
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4 backdrop-blur-sm">
      <section className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-panel">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">RFID card</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950">
              {props.employee.first_name} {props.employee.last_name}
            </h2>
            <p className="mt-1 text-sm text-slate-500">Current: {props.employee.card_numbers || '-'}</p>
          </div>
          <button type="button" className="rounded-lg border border-slate-200 p-3 text-slate-500 transition hover:bg-slate-50" onClick={props.onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>

        <label className="mt-6 grid gap-2">
          <span className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <CreditCard className="h-4 w-4 text-slate-500" />
            Card number
          </span>
          <input
            className="input-shell"
            value={props.cardNumber}
            onChange={(event) => props.onCardNumberChange(event.target.value)}
            placeholder="RFID / card number"
            autoFocus
          />
        </label>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button type="button" className="muted-btn" onClick={props.onClose}>
            Cancel
          </button>
          <button type="button" className="primary-btn" onClick={props.onSubmit} disabled={props.busy}>
            <Save className="h-4 w-4" />
            {props.busy ? 'Saving...' : 'Save and sync'}
          </button>
        </div>
      </section>
    </div>
  )
}
