import { useEffect, useMemo, useState } from 'react'

import { Building2, Cpu, Plus, Save, Search, Server, ShieldCheck, Waypoints } from 'lucide-react'

import type { DeviceRegistryData, DeviceRegistryItem } from '../types'
import { classNames, formatDateTime } from '../utils'

type DeviceRegistryPanelProps = {
  data: DeviceRegistryData | null
  legalEntityId: string
  onSave: (deviceId: string | null, payload: {
    legal_entity_id: string
    brand: string
    transport: string
    device_type: string
    device_name: string
    model: string
    serial_number: string
    host: string
    port: number
    api_base_url: string | null
    username: string | null
    password_ciphertext: string | null
    device_timezone: string
    is_active: boolean
    poll_interval_seconds: number
    metadata: Record<string, unknown>
  }) => Promise<void>
}

const brandDefaults = {
  zk: {
    transport: 'sdk_bridge',
    label: 'ZKTeco / SDK Bridge',
    note: 'C3/C3100 კონტროლერისთვის გამოიყენეთ local SDK bridge იმავე LAN-ში.'
  },
  dahua: {
    transport: 'http_cgi',
    label: 'Dahua / CGI',
    note: 'ფილიალის ქსელისთვის რეკომენდებულია local edge middleware.'
  },
  suprema: {
    transport: 'biostar',
    label: 'Suprema / BioStar',
    note: 'BioStar API bridge ან middleware უნდა იყოს ხელმისაწვდომი.'
  }
} as const

const deviceTypeLabels: Record<string, string> = {
  biometric_terminal: 'ბიომეტრიული ტერმინალი',
  rfid_card_reader: 'RFID ბარათის წამკითხველი',
  access_control_gate: 'საკონტროლო გეითი'
}

const emptyForm = {
  brand: 'zk',
  transport: 'sdk_bridge',
  device_type: 'biometric_terminal',
  device_name: '',
  model: '',
  serial_number: '',
  host: '',
  port: '80',
  api_base_url: '',
  username: '',
  password_ciphertext: '',
  device_timezone: 'Asia/Tbilisi',
  is_active: true,
  poll_interval_seconds: '60'
}

export function DeviceRegistryPanel(props: DeviceRegistryPanelProps) {
  const [editing, setEditing] = useState<DeviceRegistryItem | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [selectedTenantId, setSelectedTenantId] = useState(props.legalEntityId)
  const [form, setForm] = useState(emptyForm)

  useEffect(() => {
    if (editing) {
      setSelectedTenantId(editing.legal_entity_id)
      setForm({
        brand: editing.brand,
        transport: editing.transport,
        device_type: editing.device_type,
        device_name: editing.device_name,
        model: editing.model,
        serial_number: editing.serial_number,
        host: editing.host,
        port: `${editing.port}`,
        api_base_url: editing.api_base_url ?? '',
        username: editing.username ?? '',
        password_ciphertext: editing.password_ciphertext ?? '',
        device_timezone: editing.device_timezone,
        is_active: editing.is_active,
        poll_interval_seconds: `${editing.poll_interval_seconds}`
      })
      setError('')
      return
    }

    setSelectedTenantId(props.legalEntityId)
    setForm(emptyForm)
    setError('')
  }, [editing, props.legalEntityId])

  const filteredItems = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) {
      return props.data?.items ?? []
    }
    return (props.data?.items ?? []).filter((item) =>
      [item.device_name, item.brand, item.host, item.serial_number, item.model, item.tenant_name ?? '']
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(query))
    )
  }, [props.data, search])

  const currentBrand = brandDefaults[form.brand as keyof typeof brandDefaults]
  const tenantCount = props.data?.tenants?.length ?? 0

  function resetForCreate() {
    setEditing(null)
    setSelectedTenantId(props.legalEntityId)
    setForm(emptyForm)
    setError('')
  }

  async function handleSave() {
    if (!selectedTenantId) {
      setError('აირჩიეთ კომპანია, რომელსაც ეს მოწყობილობა ეკუთვნის.')
      return
    }
    if (!form.device_name.trim()) {
      setError('შეიყვანეთ მოწყობილობის სახელი.')
      return
    }
    if (!form.host.trim()) {
      setError('შეიყვანეთ მოწყობილობის IP ან hostname.')
      return
    }
    if (!Number(form.port) || Number(form.port) < 1 || Number(form.port) > 65535) {
      setError('პორტი უნდა იყოს 1-დან 65535-მდე.')
      return
    }
    if (!Number(form.poll_interval_seconds) || Number(form.poll_interval_seconds) < 10) {
      setError('განახლების ინტერვალი მინიმუმ 10 წამი უნდა იყოს.')
      return
    }

    setBusy(true)
    setError('')
    try {
      await props.onSave(editing?.id ?? null, {
        legal_entity_id: selectedTenantId,
        brand: form.brand,
        transport: form.transport,
        device_type: form.device_type,
        device_name: form.device_name.trim(),
        model: form.model.trim() || 'Unknown Model',
        serial_number: form.serial_number.trim() || 'N/A',
        host: form.host.trim(),
        port: Number(form.port),
        api_base_url: form.api_base_url.trim() || null,
        username: form.username.trim() || null,
        password_ciphertext: form.password_ciphertext.trim() || null,
        device_timezone: form.device_timezone.trim() || 'Asia/Tbilisi',
        is_active: form.is_active,
        poll_interval_seconds: Number(form.poll_interval_seconds),
        metadata: {
          onboarding_mode: form.brand === 'dahua' ? 'edge-preferred' : 'direct'
        }
      })
      resetForCreate()
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel-card space-y-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="section-kicker">Device Registry</p>
          <h2 className="section-title">ბიომეტრია და edge middleware</h2>
          <p className="mt-1 text-sm text-slate-500">მოწყობილობა იბმება კონკრეტულ tenant-ზე, ხოლო subdomain რეჟიმში სხვა tenant-ზე შეცვლა იბლოკება.</p>
        </div>
        <button type="button" className="primary-btn" onClick={resetForCreate}>
          <Plus className="h-4 w-4" />
          ახალი მოწყობილობა
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <Server className="h-4 w-4 text-slate-500" />
            რეგისტრირებული მოწყობილობები
          </div>
            <p className="mt-3 text-3xl font-semibold text-slate-950">{props.data?.items?.length ?? 0}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <ShieldCheck className="h-4 w-4 text-slate-500" />
            აქტიური ჩანაწერები
          </div>
          <p className="mt-3 text-3xl font-semibold text-slate-950">{(props.data?.items ?? []).filter((item) => item.is_active).length}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <Building2 className="h-4 w-4 text-slate-500" />
            ხელმისაწვდომი tenant-ები
          </div>
          <p className="mt-3 text-3xl font-semibold text-slate-950">{tenantCount}</p>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)]">
        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
            <div className="mb-4 flex items-center gap-2 font-semibold text-slate-900">
              <Waypoints className="h-4 w-4 text-slate-600" />
              Edge middleware გაშვება
            </div>
            <div className="space-y-3 text-sm text-slate-600">
              <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                <p className="font-semibold text-slate-900">1. Local LAN</p>
                <p className="mt-1">თუ ტერმინალი ცენტრალურ ოფისშია, მიუთითეთ მისი შიდა IP, ბრენდი და შესაბამისი transport.</p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                <p className="font-semibold text-slate-900">2. Remote branch</p>
                <p className="mt-1">ფილიალის ქსელში გაუშვით <code>docker-compose.edge.yml</code>, შემდეგ აქ მიუთითეთ იმავე LAN-ზე არსებული მოწყობილობის IP.</p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-950 px-4 py-3 text-xs text-slate-100">
                docker compose -f docker-compose.edge.yml up -d
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="relative mb-4">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                className="input-shell pl-11"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="ძებნა: მოწყობილობა, tenant, IP, serial"
              />
            </div>

            <div className="space-y-3">
              {filteredItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={classNames(
                    'flex w-full items-start justify-between rounded-2xl border px-4 py-4 text-left transition',
                    editing?.id === item.id ? 'border-slate-400 bg-slate-50' : 'border-slate-200 bg-white hover:border-slate-300'
                  )}
                  onClick={() => setEditing(item)}
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-slate-950">{item.device_name}</span>
                      <span className={classNames(
                        'rounded-full px-2 py-1 text-[11px] font-semibold',
                        item.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'
                      )}>
                        {item.is_active ? 'აქტიური' : 'გამორთული'}
                      </span>
                      {tenantCount > 1 ? (
                        <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-600">
                          {item.tenant_name ?? 'Tenant'}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 text-sm text-slate-600">
                      {item.brand.toUpperCase()} • {deviceTypeLabels[item.device_type] ?? item.device_type} • {item.transport}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {item.host}:{item.port} • {item.serial_number}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">ბოლო კავშირი: {formatDateTime(item.last_seen_at)}</p>
                  </div>
                  <Server className="mt-1 h-5 w-5 shrink-0 text-slate-400" />
                </button>
              ))}

              {!filteredItems.length ? (
                <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-10 text-center text-sm text-slate-500">
                  ჩანაწერები ვერ მოიძებნა.
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
          <div className="mb-4 flex items-center gap-2 font-semibold text-slate-900">
            <Cpu className="h-4 w-4 text-slate-600" />
            {editing ? 'მოწყობილობის რედაქტირება' : 'ახალი მოწყობილობა'}
          </div>

          <div className="mb-4 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
            <p className="font-semibold text-slate-900">{currentBrand.label}</p>
            <p className="mt-1">{currentBrand.note}</p>
          </div>

          {error ? (
            <div className="mb-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 break-words whitespace-pre-wrap">
              {error}
            </div>
          ) : null}

          <div className="grid gap-3 md:grid-cols-2">
            {tenantCount > 1 ? (
              <select className="input-shell md:col-span-2" value={selectedTenantId} onChange={(event) => setSelectedTenantId(event.target.value)}>
                {(props.data?.tenants ?? []).map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>{tenant.trade_name}</option>
                ))}
              </select>
            ) : null}

            <select
              className="input-shell"
              value={form.brand}
              onChange={(event) => {
                const brand = event.target.value as keyof typeof brandDefaults
                setForm((current) => ({ ...current, brand, transport: brandDefaults[brand].transport }))
              }}
            >
              <option value="zk">ZKTeco</option>
              <option value="dahua">Dahua</option>
              <option value="suprema">Suprema</option>
            </select>

            <select className="input-shell" value={form.transport} onChange={(event) => setForm((current) => ({ ...current, transport: event.target.value }))}>
              <option value="sdk_bridge">SDK Bridge</option>
              <option value="adms">ADMS</option>
              <option value="adms_push">ADMS Push</option>
              <option value="raw_socket">Raw Socket</option>
              <option value="http_cgi">HTTP CGI</option>
              <option value="biostar">BioStar</option>
            </select>

            <select className="input-shell md:col-span-2" value={form.device_type} onChange={(event) => setForm((current) => ({ ...current, device_type: event.target.value }))}>
              <option value="biometric_terminal">ბიომეტრიული ტერმინალი</option>
              <option value="rfid_card_reader">RFID ბარათის წამკითხველი</option>
              <option value="access_control_gate">საკონტროლო გეითი</option>
            </select>

            <input className="input-shell md:col-span-2" value={form.device_name} onChange={(event) => setForm((current) => ({ ...current, device_name: event.target.value }))} placeholder="მოწყობილობის სახელი" />
            <input className="input-shell" value={form.model} onChange={(event) => setForm((current) => ({ ...current, model: event.target.value }))} placeholder="მოდელი" />
            <input className="input-shell" value={form.serial_number} onChange={(event) => setForm((current) => ({ ...current, serial_number: event.target.value }))} placeholder="სერიული ნომერი" />
            <input className="input-shell" value={form.host} onChange={(event) => setForm((current) => ({ ...current, host: event.target.value }))} placeholder="IP / Hostname" />
            <input className="input-shell" value={form.port} onChange={(event) => setForm((current) => ({ ...current, port: event.target.value }))} placeholder="პორტი" />
            <input className="input-shell md:col-span-2" value={form.api_base_url} onChange={(event) => setForm((current) => ({ ...current, api_base_url: event.target.value }))} placeholder="API base URL (არასავალდებულო)" />
            <input className="input-shell" value={form.username} onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))} placeholder="მომხმარებელი" />
            <input className="input-shell" value={form.password_ciphertext} onChange={(event) => setForm((current) => ({ ...current, password_ciphertext: event.target.value }))} placeholder="პაროლი" />
            <input className="input-shell" value={form.device_timezone} onChange={(event) => setForm((current) => ({ ...current, device_timezone: event.target.value }))} placeholder="Timezone" />
            <input className="input-shell" value={form.poll_interval_seconds} onChange={(event) => setForm((current) => ({ ...current, poll_interval_seconds: event.target.value }))} placeholder="განახლების ინტერვალი (წამი)" />
          </div>

          <label className="mt-4 flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={form.is_active} onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))} />
            აქტიური მოწყობილობა
          </label>

          <button type="button" className="primary-btn mt-4" onClick={() => void handleSave()} disabled={busy}>
            <Save className="h-4 w-4" />
            {busy ? 'ინახება...' : 'შენახვა'}
          </button>
        </div>
      </div>
    </section>
  )
}
