import { CheckCircle } from 'lucide-react'
import clsx from 'clsx'

// The only output format this app actually generates. The three
// higher-effort formats that used to sit here as locked "Coming Soon" tiles
// (hall tickets, seating plans, attendance sheets) advertised features that
// did not exist; removed rather than shipped as vaporware (P3-70,
// DECISIONS.md 2026-09-20). They return as real tiles once Gate F builds them.
const OUTPUT_TYPES = [
  {
    id: 'subject_wise',
    label: 'Subject-wise Roll Number List',
    description: 'One sheet with all subjects as columns and roll numbers as rows',
  },
]

export default function OutputTypeSelector({ value, onChange }) {
  return (
    <div className="space-y-3">
      <p className="text-caption font-medium uppercase tracking-wide text-muted">Output Format</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {OUTPUT_TYPES.map((type) => {
          const selected = value === type.id
          return (
            <button
              key={type.id}
              type="button"
              onClick={() => onChange?.(type.id)}
              className={clsx(
                'relative flex flex-col items-start rounded-2xl border p-4 text-left transition-all duration-fast ease-standard',
                selected
                  ? 'border-primary bg-primary/5 shadow-warm'
                  : 'border-line bg-surface hover:border-primary/40 hover:shadow-warm cursor-pointer',
              )}
            >
              {selected && (
                <CheckCircle size={18} className="absolute right-3 top-3 text-primary" />
              )}
              <p className={clsx('text-small font-semibold', selected ? 'text-primary' : 'text-ink')}>
                {type.label}
              </p>
              <p className="mt-1 text-caption text-muted">{type.description}</p>
            </button>
          )
        })}
      </div>
    </div>
  )
}
