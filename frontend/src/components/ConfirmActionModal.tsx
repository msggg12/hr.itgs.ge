import { AlertTriangle } from 'lucide-react'

import { classNames } from '../utils'

type ConfirmActionModalProps = {
  open: boolean
  title: string
  body: string
  confirmLabel: string
  cancelLabel?: string
  busy?: boolean
  tone?: 'danger' | 'warning'
  onClose: () => void
  onConfirm: () => void
}

export function ConfirmActionModal(props: ConfirmActionModalProps) {
  if (!props.open) {
    return null
  }

  const dangerTone = props.tone !== 'warning'

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/65 px-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-[28px] border border-white/10 bg-[linear-gradient(180deg,rgba(19,24,35,0.98)_0%,rgba(12,17,27,0.98)_100%)] p-6 shadow-[0_28px_80px_rgba(2,6,23,0.42)]">
        <div className="flex items-start gap-4">
          <div
            className={classNames(
              'flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border',
              dangerTone
                ? 'border-rose-400/25 bg-rose-500/12 text-rose-200'
                : 'border-amber-400/25 bg-amber-500/12 text-amber-200'
            )}
          >
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-400">Confirmation</p>
            <h3 className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-white">{props.title}</h3>
            <p className="mt-3 text-sm leading-6 text-slate-300">{props.body}</p>
          </div>
        </div>

        <div className="mt-7 flex items-center justify-end gap-3">
          <button type="button" className="muted-btn border-white/10 bg-white/5 px-5 py-3 text-slate-200 hover:bg-white/10" onClick={props.onClose} disabled={props.busy}>
            {props.cancelLabel ?? 'Cancel'}
          </button>
          <button
            type="button"
            className={classNames(
              'inline-flex items-center justify-center rounded-xl px-5 py-3 text-sm font-semibold text-white transition',
              dangerTone
                ? 'bg-[linear-gradient(180deg,#f15b6c_0%,#d93b52_100%)] shadow-[0_12px_28px_rgba(217,59,82,0.28)] hover:bg-[linear-gradient(180deg,#ee5062_0%,#cb3348_100%)]'
                : 'bg-[linear-gradient(180deg,#f0b24c_0%,#d79324_100%)] shadow-[0_12px_28px_rgba(215,147,36,0.24)] hover:bg-[linear-gradient(180deg,#ebb048_0%,#cb881a_100%)]'
            )}
            onClick={props.onConfirm}
            disabled={props.busy}
          >
            {props.busy ? 'Please wait...' : props.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
