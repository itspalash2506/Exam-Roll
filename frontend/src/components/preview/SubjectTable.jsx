import { useState, useMemo } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import clsx from 'clsx'

const PREVIEW_ROWS = 10

export default function SubjectTable({ extractedData }) {
  const [showAll, setShowAll] = useState(false)

  const { students = [], subjects = [] } = extractedData ?? {}

  const subjectCodes = useMemo(
    () => subjects.map((s) => s.code),
    [subjects],
  )

  const visibleStudents = showAll ? students : students.slice(0, PREVIEW_ROWS)

  // Count per subject
  const counts = useMemo(() => {
    const map = {}
    subjects.forEach((s) => { map[s.code] = 0 })
    students.forEach((st) => {
      st.subjects?.forEach((code) => {
        if (map[code] !== undefined) map[code]++
      })
    })
    return map
  }, [students, subjects])

  if (!students.length || !subjects.length) {
    return (
      <div className="rounded-2xl border border-line bg-surface p-8 text-center text-small text-muted shadow-warm">
        No extracted data to preview.
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-line bg-surface shadow-warm overflow-hidden">
      <div className="border-b border-line px-5 py-3">
        <h3 className="text-small font-semibold text-ink">
          Extracted Data Preview
          <span className="ml-2 font-normal text-muted">
            ({students.length} students · {subjects.length} subjects)
          </span>
        </h3>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-small">
          <thead>
            <tr className="bg-highlight/50">
              <th className="sticky left-0 z-10 bg-highlight/50 px-4 py-3 text-left text-caption font-semibold text-ink whitespace-nowrap">
                Roll No.
              </th>
              {subjects.map((s) => (
                <th key={s.code} className="px-4 py-3 text-center text-caption font-semibold text-ink whitespace-nowrap min-w-[90px]">
                  <div>{s.code}</div>
                  {s.name && <div className="font-normal text-muted truncate max-w-[100px]">{s.name}</div>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {visibleStudents.map((student, idx) => (
              <tr
                key={student.roll_number}
                className={idx % 2 === 1 ? 'bg-canvas/60' : 'bg-surface'}
              >
                <td className={clsx('sticky left-0 px-4 py-2.5 font-mono text-caption font-medium text-ink whitespace-nowrap', idx % 2 === 1 ? 'bg-canvas/60' : 'bg-surface')}>
                  {student.roll_number}
                </td>
                {subjectCodes.map((code) => {
                  const enrolled = student.subjects?.includes(code)
                  return (
                    <td key={code} className="px-4 py-2.5 text-center text-caption">
                      {enrolled ? (
                        <span className="font-bold text-success">✓</span>
                      ) : (
                        <span className="text-muted/40">—</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}

            {/* Count row */}
            <tr className="border-t-2 border-secondary/50 bg-highlight">
              <td className="sticky left-0 bg-highlight px-4 py-2.5 text-caption font-bold text-ink whitespace-nowrap">
                Count
              </td>
              {subjectCodes.map((code) => (
                <td key={code} className="px-4 py-2.5 text-center text-caption font-bold text-ink">
                  {counts[code] ?? 0}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      {students.length > PREVIEW_ROWS && (
        <div className="border-t border-line px-5 py-3 text-center">
          <button
            onClick={() => setShowAll((v) => !v)}
            className="inline-flex items-center gap-1.5 text-caption font-medium text-primary hover:text-primary-hover"
          >
            {showAll ? (
              <><ChevronUp size={14} /> Show fewer rows</>
            ) : (
              <><ChevronDown size={14} /> Show all {students.length} students</>
            )}
          </button>
        </div>
      )}
    </div>
  )
}
