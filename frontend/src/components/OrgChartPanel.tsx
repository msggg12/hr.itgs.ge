import { Building2, GitBranchPlus } from 'lucide-react'

import type { OrgChartData, OrgChartNode } from '../types'
import { initials } from '../utils'

type OrgChartPanelProps = {
  data: OrgChartData | null
}

function TreeNode(props: { node: OrgChartNode; childrenByManager: Record<string, OrgChartNode[]> }) {
  const children = props.childrenByManager[props.node.id] ?? []
  return (
    <div className="space-y-3">
      <div className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-900 text-sm font-semibold text-white">
            {initials(props.node.full_name.split(' ')[0], props.node.full_name.split(' ')[1])}
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-slate-900">{props.node.full_name}</div>
            <div className="mt-1 text-sm text-slate-600">{props.node.role_title ?? 'თანამშრომელი'}</div>
            <div className="mt-1 text-xs text-slate-500">{props.node.department_name ?? 'Department N/A'} • {props.node.employee_number}</div>
          </div>
        </div>
      </div>
      {children.length ? (
        <div className="ml-5 border-l border-slate-200 pl-5">
          <div className="grid gap-3 xl:grid-cols-2">
            {children.map((child) => (
              <TreeNode key={child.id} node={child} childrenByManager={props.childrenByManager} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export function OrgChartPanel(props: OrgChartPanelProps) {
  const nodes = props.data?.nodes ?? []
  const childrenByManager = nodes.reduce<Record<string, OrgChartNode[]>>((acc, node) => {
    if (node.manager_id) {
      acc[node.manager_id] = [...(acc[node.manager_id] ?? []), node]
    }
    return acc
  }, {})
  const roots = nodes.filter((node) => !node.manager_id)

  return (
    <section className="panel-card space-y-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="section-kicker">Org Chart</p>
          <h2 className="section-title">ხაზობრივი მენეჯერები და სტრუქტურა</h2>
        </div>
        <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
          <Building2 className="h-4 w-4 text-slate-500" />
          {nodes.length} თანამშრომელი
        </div>
      </div>

      {!roots.length ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-6 py-10 text-sm text-slate-500">
          Org chart ჯერ არ არის კონფიგურირებული.
        </div>
      ) : (
        <div className="space-y-4">
          {roots.map((node) => (
            <div key={node.id}>
              <div className="mb-3 inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
                <GitBranchPlus className="h-4 w-4" />
                Root Node
              </div>
              <TreeNode node={node} childrenByManager={childrenByManager} />
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
