import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import Button from '../common/Button.jsx'

// A student enrolled in >=2 papers of the same session is a real timetable
// error to report to the university (§15.2 step 4) — publishing (F04) is
// refused until each clash here is acknowledged or resolved.
export default function ClashPanel({ clashes, onAcknowledge, acknowledging }) {
  if (!clashes || clashes.length === 0) return null
  return (
    <div className="rounded-2xl border border-warning/30 bg-highlight/30 p-4 space-y-2">
      <p className="flex items-center gap-1.5 text-small font-semibold text-warning">
        <AlertTriangle size={15} /> {clashes.length} timetable clash{clashes.length > 1 ? 'es' : ''}
      </p>
      <ul className="space-y-1.5">
        {clashes.map((c) => (
          <li key={c.student_id} className="flex items-center justify-between gap-3 text-small text-ink">
            <span>
              Roll <code className="font-medium">{c.roll_number}</code> is enrolled in both{' '}
              {c.exam_codes.join(' and ')}
            </span>
            {c.acknowledged ? (
              <span className="flex items-center gap-1 text-caption text-success"><CheckCircle2 size={13} /> Acknowledged</span>
            ) : (
              <Button
                variant="secondary"
                size="sm"
                loading={acknowledging === c.student_id}
                onClick={() => onAcknowledge(c.student_id)}
              >
                Acknowledge
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
