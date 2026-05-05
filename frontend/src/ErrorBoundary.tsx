import { Component, type ErrorInfo, type ReactNode } from 'react'

type ErrorBoundaryProps = {
  children: ReactNode
}

type ErrorBoundaryState = {
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    error: null
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('HRMS fatal render error', error, info)
  }

  render() {
    if (!this.state.error) {
      return this.props.children
    }

    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6 py-12">
        <section className="grid w-full max-w-2xl gap-4 rounded-2xl border border-rose-200 bg-white p-8 shadow-sm">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-rose-500">Application Error</p>
            <h1 className="mt-3 text-3xl font-semibold text-slate-950">The page hit a runtime error.</h1>
            <p className="mt-2 text-sm text-slate-500">
              Reload the page once. If it happens again, the error details below will help us fix it quickly.
            </p>
          </div>
          <pre className="overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700 whitespace-pre-wrap">
            {this.state.error.message || String(this.state.error)}
          </pre>
          <button className="primary-btn w-fit" type="button" onClick={() => window.location.reload()}>
            Reload Page
          </button>
        </section>
      </main>
    )
  }
}
