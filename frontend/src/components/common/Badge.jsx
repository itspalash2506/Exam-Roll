import clsx from 'clsx'

const styles = {
  queued: 'bg-muted/10 text-muted',
  pending: 'bg-warning/10 text-warning',
  processing: 'bg-primary/10 text-primary',
  completed: 'bg-success/10 text-success',
  done: 'bg-success/10 text-success',
  failed: 'bg-error/10 text-error',
  error: 'bg-error/10 text-error',
}

const labels = {
  queued: 'Queued',
  pending: 'Pending',
  processing: 'Processing',
  completed: 'Completed',
  done: 'Completed',
  failed: 'Failed',
  error: 'Error',
}

export default function Badge({ status, label, className }) {
  const key = status?.toLowerCase() ?? ''
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-caption font-medium',
        styles[key] ?? 'bg-muted/10 text-muted',
        className,
      )}
    >
      {label ?? labels[key] ?? status}
    </span>
  )
}
