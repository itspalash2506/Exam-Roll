import { Component } from 'react'
import { AlertTriangle } from 'lucide-react'

// Class component: React error boundaries have no hook equivalent (React 18).
// Placed at the router level (App.jsx) so a throw anywhere inside a route —
// a malformed API response, a null the component didn't guard, anything —
// shows this panel instead of an unrecoverable blank/white screen (P1-19).
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('Unhandled render error:', error, info)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6 px-6 text-center">
        <span className="flex h-14 w-14 items-center justify-center rounded-full bg-error/10 text-error">
          <AlertTriangle size={26} />
        </span>
        <div className="space-y-2">
          <p className="font-display text-h2 font-medium text-ink">Something went wrong</p>
          <p className="max-w-sm text-small text-muted">
            This page hit an unexpected error. Reloading usually fixes it — your data is safe on
            the server either way.
          </p>
        </div>
        <div className="flex gap-3">
          {/* Full hard navigation, not client-side routing — the app tree
              that just crashed shouldn't be trusted to recover in place. */}
          <button
            onClick={() => window.location.reload()}
            className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-small font-medium text-canvas transition-colors duration-fast hover:bg-primary-hover"
          >
            Reload
          </button>
          <button
            onClick={() => window.location.assign('/')}
            className="inline-flex items-center gap-2 rounded-xl border border-primary px-4 py-2 text-small font-medium text-primary transition-colors duration-fast hover:bg-highlight/20"
          >
            Go home
          </button>
        </div>
      </div>
    )
  }
}
