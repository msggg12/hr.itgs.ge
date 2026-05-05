import { useEffect, useState } from 'react'

import { Archive, Laptop, Save, UserPlus } from 'lucide-react'

import type { WarehouseData, WarehouseItem } from '../types'
import { formatMoney } from '../utils'

type WarehousePanelProps = {
  data: WarehouseData | null
  onSaveItem: (itemId: string | null, payload: {
    category_id: string | null
    asset_tag: string
    asset_name: string
    brand: string | null
    model: string | null
    serial_number: string | null
    current_condition: string
    current_status: string
    purchase_date: string | null
    purchase_cost: number
    currency_code: string
    assigned_department_id: string | null
    notes: string | null
  }) => Promise<void>
  onAssign: (itemId: string, payload: {
    employee_id: string
    assigned_at: string
    expected_return_at: string | null
    condition_on_issue: string
    note: string | null
    employee_signature_name: string
  }) => Promise<void>
}

export function WarehousePanel(props: WarehousePanelProps) {
  const [selectedId, setSelectedId] = useState<string>('new')
  const [busy, setBusy] = useState(false)
  const [itemForm, setItemForm] = useState({
    category_id: '',
    asset_tag: '',
    asset_name: '',
    brand: '',
    model: '',
    serial_number: '',
    current_condition: 'new',
    current_status: 'in_stock',
    purchase_date: '',
    purchase_cost: 0,
    currency_code: 'GEL',
    assigned_department_id: '',
    notes: ''
  })
  const [assignForm, setAssignForm] = useState({
    employee_id: '',
    assigned_at: new Date().toISOString().slice(0, 16),
    expected_return_at: '',
    condition_on_issue: 'good',
    note: '',
    employee_signature_name: ''
  })

  useEffect(() => {
    const selected = props.data?.items?.find((item) => item.id === selectedId)
    if (!selected) {
      setItemForm({
        category_id: '',
        asset_tag: '',
        asset_name: '',
        brand: '',
        model: '',
        serial_number: '',
        current_condition: 'new',
        current_status: 'in_stock',
        purchase_date: '',
        purchase_cost: 0,
        currency_code: 'GEL',
        assigned_department_id: '',
        notes: ''
      })
      return
    }
    setItemForm({
      category_id: props.data?.categories?.find((category) => category.name_en === selected.category_name || category.name_ka === selected.category_name)?.id ?? '',
      asset_tag: selected.asset_tag,
      asset_name: selected.asset_name,
      brand: selected.brand ?? '',
      model: selected.model ?? '',
      serial_number: selected.serial_number ?? '',
      current_condition: selected.current_condition,
      current_status: selected.current_status,
      purchase_date: selected.purchase_date ?? '',
      purchase_cost: selected.purchase_cost,
      currency_code: selected.currency_code,
      assigned_department_id: '',
      notes: selected.notes ?? ''
    })
  }, [props.data, selectedId])

  async function handleSaveItem() {
    setBusy(true)
    try {
      await props.onSaveItem(selectedId === 'new' ? null : selectedId, {
        category_id: itemForm.category_id || null,
        asset_tag: itemForm.asset_tag,
        asset_name: itemForm.asset_name,
        brand: itemForm.brand || null,
        model: itemForm.model || null,
        serial_number: itemForm.serial_number || null,
        current_condition: itemForm.current_condition,
        current_status: itemForm.current_status,
        purchase_date: itemForm.purchase_date || null,
        purchase_cost: Number(itemForm.purchase_cost || 0),
        currency_code: itemForm.currency_code,
        assigned_department_id: itemForm.assigned_department_id || null,
        notes: itemForm.notes || null
      })
      setSelectedId('new')
    } finally {
      setBusy(false)
    }
  }

  async function handleAssign() {
    if (selectedId === 'new') {
      return
    }
    setBusy(true)
    try {
      await props.onAssign(selectedId, {
        employee_id: assignForm.employee_id,
        assigned_at: assignForm.assigned_at,
        expected_return_at: assignForm.expected_return_at || null,
        condition_on_issue: assignForm.condition_on_issue,
        note: assignForm.note || null,
        employee_signature_name: assignForm.employee_signature_name
      })
      setAssignForm((current) => ({ ...current, note: '', employee_signature_name: '' }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel-card">
      <div className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-slate-400">Warehouse</p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950">ინვენტარი და handover</h2>
          <p className="mt-1 text-sm text-slate-500">აქტივი იქმნება, რედაქტირდება და თანამშრომელზე გადაცემისას ციფრული handover ფორმა ივსება.</p>
        </div>
        <select className="input-shell min-w-[280px]" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
          <option value="new">ახალი აქტივი</option>
          {(props.data?.items ?? []).map((item) => (
            <option key={item.id} value={item.id}>
              {item.asset_tag} - {item.asset_name}
            </option>
          ))}
        </select>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(350px,0.85fr)]">
        <div className="space-y-6">
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="mb-4 flex items-center gap-2 font-semibold text-slate-950">
              <Archive className="h-4 w-4 text-action-600" />
              Asset Editor
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <select className="input-shell" value={itemForm.category_id} onChange={(event) => setItemForm((current) => ({ ...current, category_id: event.target.value }))}>
                <option value="">Category</option>
                {(props.data?.categories ?? []).map((item) => <option key={item.id} value={item.id}>{item.name_ka ?? item.name_en}</option>)}
              </select>
              <input className="input-shell" value={itemForm.asset_tag} onChange={(event) => setItemForm((current) => ({ ...current, asset_tag: event.target.value }))} placeholder="Asset Tag" />
              <input className="input-shell" value={itemForm.asset_name} onChange={(event) => setItemForm((current) => ({ ...current, asset_name: event.target.value }))} placeholder="Asset Name" />
              <input className="input-shell" value={itemForm.brand} onChange={(event) => setItemForm((current) => ({ ...current, brand: event.target.value }))} placeholder="Brand" />
              <input className="input-shell" value={itemForm.model} onChange={(event) => setItemForm((current) => ({ ...current, model: event.target.value }))} placeholder="Model" />
              <input className="input-shell" value={itemForm.serial_number} onChange={(event) => setItemForm((current) => ({ ...current, serial_number: event.target.value }))} placeholder="Serial Number" />
              <select className="input-shell" value={itemForm.current_condition} onChange={(event) => setItemForm((current) => ({ ...current, current_condition: event.target.value }))}>
                <option value="new">new</option>
                <option value="excellent">excellent</option>
                <option value="good">good</option>
                <option value="fair">fair</option>
                <option value="damaged">damaged</option>
                <option value="retired">retired</option>
                <option value="lost">lost</option>
              </select>
              <select className="input-shell" value={itemForm.current_status} onChange={(event) => setItemForm((current) => ({ ...current, current_status: event.target.value }))}>
                <option value="in_stock">in_stock</option>
                <option value="assigned">assigned</option>
                <option value="repair">repair</option>
                <option value="retired">retired</option>
                <option value="disposed">disposed</option>
                <option value="lost">lost</option>
              </select>
              <input className="input-shell" type="date" value={itemForm.purchase_date} onChange={(event) => setItemForm((current) => ({ ...current, purchase_date: event.target.value }))} />
              <input className="input-shell" type="number" value={itemForm.purchase_cost} onChange={(event) => setItemForm((current) => ({ ...current, purchase_cost: Number(event.target.value) }))} placeholder="Purchase Cost" />
            </div>
            <textarea className="input-shell mt-4 min-h-[110px]" value={itemForm.notes} onChange={(event) => setItemForm((current) => ({ ...current, notes: event.target.value }))} placeholder="Notes" />
            <button type="button" className="brand-button mt-4 inline-flex items-center gap-2 rounded-2xl px-4 py-3 font-semibold text-white" onClick={() => void handleSaveItem()} disabled={busy}>
              <Save className="h-4 w-4" />
              {busy ? 'ინახება...' : 'აქტივის შენახვა'}
            </button>
          </div>

          {selectedId !== 'new' ? (
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <div className="mb-4 flex items-center gap-2 font-semibold text-slate-950">
                <UserPlus className="h-4 w-4 text-action-600" />
                Assign to Employee
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <select className="input-shell" value={assignForm.employee_id} onChange={(event) => setAssignForm((current) => ({ ...current, employee_id: event.target.value }))}>
                  <option value="">Employee</option>
                  {(props.data?.employees ?? []).map((item) => <option key={item.id} value={item.id}>{item.full_name}</option>)}
                </select>
                <input className="input-shell" type="datetime-local" value={assignForm.assigned_at} onChange={(event) => setAssignForm((current) => ({ ...current, assigned_at: event.target.value }))} />
                <input className="input-shell" type="datetime-local" value={assignForm.expected_return_at} onChange={(event) => setAssignForm((current) => ({ ...current, expected_return_at: event.target.value }))} />
                <select className="input-shell" value={assignForm.condition_on_issue} onChange={(event) => setAssignForm((current) => ({ ...current, condition_on_issue: event.target.value }))}>
                  <option value="new">new</option>
                  <option value="excellent">excellent</option>
                  <option value="good">good</option>
                  <option value="fair">fair</option>
                  <option value="damaged">damaged</option>
                </select>
                <input className="input-shell md:col-span-2" value={assignForm.employee_signature_name} onChange={(event) => setAssignForm((current) => ({ ...current, employee_signature_name: event.target.value }))} placeholder="Employee signature / full name" />
              </div>
              <textarea className="input-shell mt-4 min-h-[96px]" value={assignForm.note} onChange={(event) => setAssignForm((current) => ({ ...current, note: event.target.value }))} placeholder="Handover note" />
              <button type="button" className="brand-button mt-4 inline-flex items-center gap-2 rounded-2xl px-4 py-3 font-semibold text-white" onClick={() => void handleAssign()} disabled={busy}>
                <Laptop className="h-4 w-4" />
                {busy ? 'იგზავნება...' : 'თანამშრომელზე გადაცემა'}
              </button>
            </div>
          ) : null}
        </div>

        <div className="space-y-3">
          {(props.data?.items ?? []).map((item: WarehouseItem) => (
            <button key={item.id} type="button" className={`w-full rounded-xl border p-4 text-left transition ${selectedId === item.id ? 'brand-border brand-soft border' : 'border-slate-200 bg-white hover:border-slate-300'}`} onClick={() => setSelectedId(item.id)}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">{item.asset_tag}</p>
                  <h3 className="mt-2 font-semibold text-slate-950">{item.asset_name}</h3>
                  <p className="mt-1 text-sm text-slate-500">{item.brand ?? '-'} {item.model ?? ''}</p>
                </div>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">{item.current_status}</span>
              </div>
              <div className="mt-4 grid gap-2 text-sm text-slate-600">
                <p>Assigned: {item.assigned_employee_name ?? 'No one'}</p>
                <p>Condition: {item.current_condition}</p>
                <p>Value: {formatMoney(item.purchase_cost)}</p>
              </div>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}
