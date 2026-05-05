import { useEffect } from 'react'

import { X } from 'lucide-react'

import { classNames } from '../utils'

export type ToastItem = {
  id: string
  tone: 'success' | 'error' | 'warning'
  message: string
}

type ToastStackProps = {
  items: ToastItem[]
  onDismiss: (id: string) => void
}

export function ToastStack(props: ToastStackProps) {
  useEffect(() => {
    if (!props.items.length) {
      return
    }
    const timers = props.items.map((item) =>
      window.setTimeout(() => props.onDismiss(item.id), 4500)
    )
    return () => timers.forEach((t) => window.clearTimeout(t))
  }, [props.items, props.onDismiss])

  if (!props.items.length) {
    return null
  }

  return (
    <div className="pointer-events-none fixed bottom-6 right-6 z-[100] flex max-w-md flex-col gap-2">
      {props.items.map((item) => (
        <div
          key={item.id}
          className={classNames(
            'pointer-events-auto flex items-start gap-3 rounded-xl border px-4 py-3 text-sm shadow-lg',
            item.tone === 'success'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
              : item.tone === 'warning'
                ? 'border-amber-200 bg-amber-50 text-amber-950'
                : 'border-rose-200 bg-rose-50 text-rose-900'
          )}
        >
          <p className="min-w-0 flex-1 break-words">{item.message}</p>
          <button type="button" className="rounded-lg p-1 text-current opacity-60 hover:opacity-100" onClick={() => props.onDismiss(item.id)}>
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  )
}
