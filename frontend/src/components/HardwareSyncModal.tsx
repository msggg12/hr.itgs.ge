import { Fingerprint, Server, X } from 'lucide-react'

import { ka } from '../i18n/ka'
import type { GridItem, OptionItem } from '../types'

type HardwareSyncModalProps = {
  open: boolean
  employee: GridItem | null
  devices: OptionItem[]
  selectedDeviceIds: string[]
  onToggleDevice: (deviceId: string) => void
  onSelectAll: () => void
  onClearAll: () => void
  onClose: () => void
  onSubmit: () => void
}

export function HardwareSyncModal(props: HardwareSyncModalProps) {
  if (!props.open || !props.employee) {
    return null
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4 backdrop-blur-sm">
      <section className="w-full max-w-2xl rounded-xl border border-slate-200 bg-white p-6 shadow-panel">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">{ka.syncDevices}</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950">
              {props.employee.first_name} {props.employee.last_name}
            </h2>
            <p className="mt-1 text-sm text-slate-500">Select specific devices for this employee&apos;s physical access sync.</p>
            <p className="mt-1 text-sm text-slate-500">Checked devices will be added. Unchecked previously synced devices will be removed on save.</p>
            <p className="mt-1 text-sm text-slate-500">{ka.selectedDevices}: {props.selectedDeviceIds.length}</p>
          </div>
          <button type="button" className="rounded-lg border border-slate-200 p-3 text-slate-500 transition hover:bg-slate-50" onClick={props.onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          <button type="button" className="muted-btn text-sm" onClick={props.onSelectAll} disabled={props.devices.length === 0}>
            Select All
          </button>
          <button type="button" className="muted-btn text-sm" onClick={props.onClearAll} disabled={props.selectedDeviceIds.length === 0}>
            Clear
          </button>
        </div>

        <div className="mt-4 grid gap-3">
          {props.devices.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-300 px-6 py-12 text-center text-sm text-slate-500">
              {ka.noDevices}
            </div>
          ) : null}
          {props.devices.map((device) => {
            const selected = props.selectedDeviceIds.includes(device.id)
            return (
              <label
                key={device.id}
                className={[
                  'flex cursor-pointer items-center justify-between rounded-xl border px-4 py-4 transition',
                  selected ? 'border-action-200 bg-action-50' : 'border-slate-200 bg-white hover:bg-slate-50'
                ].join(' ')}
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-700">
                    <Server className="h-5 w-5" />
                  </div>
                  <div>
                    <p className="font-semibold text-slate-950">{device.device_name}</p>
                    <p className="text-sm text-slate-500">{device.brand} - {device.host}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Fingerprint className={selected ? 'h-5 w-5 text-action-600' : 'h-5 w-5 text-slate-300'} />
                  <input type="checkbox" checked={selected} onChange={() => props.onToggleDevice(device.id)} />
                </div>
              </label>
            )
          })}
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button type="button" className="muted-btn" onClick={props.onClose}>
            {ka.cancel}
          </button>
          <button type="button" className="primary-btn" onClick={props.onSubmit}>
            {ka.runSync}
          </button>
        </div>
      </section>
    </div>
  )
}
