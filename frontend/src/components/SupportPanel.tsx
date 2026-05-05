import { CircleHelp, LifeBuoy, ShieldCheck } from 'lucide-react'

export function SupportPanel() {
  return (
    <div className="space-y-6">
      <section className="panel-card rounded-[30px]">
        <div className="flex items-start gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-[20px] bg-slate-950 text-white shadow-[0_18px_30px_rgba(15,23,42,0.18)]">
            <CircleHelp className="h-6 w-6" />
          </div>
          <div>
            <p className="text-[12px] font-semibold uppercase tracking-[0.28em] text-slate-400">Help & Support</p>
            <h2 className="mt-3 text-[30px] font-semibold tracking-[-0.04em] text-slate-950">Operations Support</h2>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-500">
              This space keeps the utility navigation wired and gives admins a stable place for help workflows while we keep the design work moving.
            </p>
          </div>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-3">
        <article className="panel-card rounded-[26px]">
          <LifeBuoy className="h-5 w-5 text-slate-950" />
          <h3 className="mt-4 text-lg font-semibold text-slate-950">Admin Triage</h3>
          <p className="mt-2 text-sm leading-6 text-slate-500">Use the dashboard live feed, attendance tools, and employee profiles first when investigating daily HR issues.</p>
        </article>
        <article className="panel-card rounded-[26px]">
          <ShieldCheck className="h-5 w-5 text-slate-950" />
          <h3 className="mt-4 text-lg font-semibold text-slate-950">Access & Integrations</h3>
          <p className="mt-2 text-sm leading-6 text-slate-500">Slack, Google Calendar, and company email status now live under Apps & Integrations for faster troubleshooting.</p>
        </article>
        <article className="panel-card rounded-[26px]">
          <CircleHelp className="h-5 w-5 text-slate-950" />
          <h3 className="mt-4 text-lg font-semibold text-slate-950">Design Safe Zone</h3>
          <p className="mt-2 text-sm leading-6 text-slate-500">This support panel is intentionally lightweight so we can continue improving UX without changing business workflows.</p>
        </article>
      </div>
    </div>
  )
}
