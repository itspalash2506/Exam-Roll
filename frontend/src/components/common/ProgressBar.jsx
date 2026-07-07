import clsx from 'clsx'

const trackColor = (status) => {
  if (status === 'completed' || status === 'done') return 'bg-success'
  if (status === 'failed' || status === 'error') return 'bg-error'
  return 'bg-primary'
}

export default function ProgressBar({ value = 0, status, message, className }) {
  const pct = Math.min(100, Math.max(0, value))
  const isActive = status === 'processing' || status === 'queued'

  return (
    <div className={clsx('space-y-1.5', className)}>
      <div className="flex items-center justify-between text-caption text-muted">
        <span>{message || 'Processing…'}</span>
        <span className="font-medium text-ink">{pct}%</span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-line">
        <div
          className={clsx(
            'h-full rounded-full transition-all duration-slow ease-standard',
            trackColor(status),
            isActive && 'animate-pulse',
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
