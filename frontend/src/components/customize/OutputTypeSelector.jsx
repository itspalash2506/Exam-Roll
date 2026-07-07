import { CheckCircle, Lock } from 'lucide-react'
import clsx from 'clsx'

const OUTPUT_TYPES = [
  {
    id: 'subject_wise',
    label: 'Subject-wise Roll Number List',
    description: 'One sheet with all subjects as columns and roll numbers as rows',
    available: true,
  },
  {
    id: 'hall_ticket',
    label: 'Hall Ticket Generator',
    description: 'Generate individual hall tickets per student with seat assignment',
    available: false,
  },
  {
    id: 'seating_plan',
    label: 'Seating Plan',
    description: 'Create room-wise seating arrangements from the roll list',
    available: false,
  },
  {
    id: 'attendance_sheet',
    label: 'Attendance Sheet',
    description: 'Blank attendance register with roll numbers pre-filled',
    available: false,
  },
]

export default function OutputTypeSelector({ value, onChange }) {
  return (
    <div className="space-y-3">
      <p className="text-caption font-medium uppercase tracking-wide text-muted">Output Format</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {OUTPUT_TYPES.map((type) => {
          const selected = value === type.id && type.available
          return (
            <button
              key={type.id}
              type="button"
              disabled={!type.available}
              onClick={() => type.available && onChange?.(type.id)}
              className={clsx(
                'relative flex flex-col items-start rounded-2xl border p-4 text-left transition-all duration-fast ease-standard',
                type.available
                  ? selected
                    ? 'border-primary bg-primary/5 shadow-warm'
                    : 'border-line bg-surface hover:border-primary/40 hover:shadow-warm cursor-pointer'
                  : 'border-line bg-canvas/60 cursor-not-allowed opacity-60',
              )}
            >
              {!type.available && (
                <span className="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full bg-line px-2 py-0.5 text-caption text-muted">
                  <Lock size={10} /> Coming Soon
                </span>
              )}
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
