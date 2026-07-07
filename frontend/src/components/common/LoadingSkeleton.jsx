import clsx from 'clsx'

export function SkeletonLine({ width = 'w-full', height = 'h-4', className }) {
  return (
    <div
      className={clsx('animate-pulse rounded-lg bg-line', width, height, className)}
    />
  )
}

export function SkeletonCard({ className }) {
  return (
    <div className={clsx('rounded-2xl border border-line bg-surface p-5 shadow-warm space-y-3', className)}>
      <SkeletonLine width="w-1/3" height="h-3" />
      <SkeletonLine width="w-2/3" height="h-6" />
      <SkeletonLine width="w-1/2" height="h-3" />
    </div>
  )
}

export default function LoadingSkeleton({ rows = 3, card = false }) {
  if (card) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: rows }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    )
  }
  return (
    <div className="space-y-3 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonLine key={i} width={i % 3 === 0 ? 'w-3/4' : i % 2 === 0 ? 'w-full' : 'w-5/6'} />
      ))}
    </div>
  )
}
