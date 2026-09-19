import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import toast from 'react-hot-toast'
import Button from '../common/Button.jsx'
import { getExams, createExam, getColleges, createCollege } from '../../api/client.js'

const SELECT_CLASS =
  'w-full rounded-xl border border-line bg-surface px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary'
const INPUT_CLASS = SELECT_CLASS

/** One picker: a select plus an inline "+ New" create form (§14.3). Generic
 * over exam/college since both are the same shape — fetch a list, pick one
 * or create one, files aren't accepted until both this and its sibling
 * have a value (enforced by the caller, ExamCollegePicker below). */
function OnePicker({ label, queryKey, fetchList, create, extractOptions, value, onChange, createFields }) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [newValues, setNewValues] = useState({})
  const [submitting, setSubmitting] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: async () => extractOptions((await fetchList()).data),
  })
  const options = data ?? []

  const handleCreate = async () => {
    const primaryField = createFields[0].name
    if (!newValues[primaryField]?.trim()) return
    setSubmitting(true)
    try {
      const res = await create(newValues)
      await queryClient.invalidateQueries({ queryKey })
      onChange(res.data.id)
      setCreating(false)
      setNewValues({})
    } catch (err) {
      toast.error(err.message || `Could not create ${label.toLowerCase()}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-caption text-muted">{label}</span>
        <button
          type="button"
          onClick={() => setCreating((v) => !v)}
          className="flex items-center gap-1 text-caption font-medium text-primary hover:text-primary-hover"
        >
          <Plus size={12} /> New
        </button>
      </div>

      {!creating ? (
        <select
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value || null)}
          disabled={isLoading}
          className={SELECT_CLASS}
        >
          <option value="">{isLoading ? 'Loading…' : `Select ${label.toLowerCase()}…`}</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>{o.label}</option>
          ))}
        </select>
      ) : (
        <div className="space-y-2 rounded-xl border border-line bg-canvas p-3">
          {createFields.map((f) => (
            <input
              key={f.name}
              type="text"
              placeholder={f.placeholder}
              value={newValues[f.name] ?? ''}
              onChange={(e) => setNewValues((v) => ({ ...v, [f.name]: e.target.value }))}
              className={INPUT_CLASS}
            />
          ))}
          <div className="flex gap-2">
            <Button size="sm" variant="primary" onClick={handleCreate} loading={submitting}>
              Create
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setCreating(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

/** §14.3 — "Which exam? Which college's sheet is this?" Files are not
 * accepted until both are set (Upload.jsx checks isComplete before
 * rendering the DropZone). The AI's course/semester guess pre-fills
 * nothing here by design: it never creates an exam by itself — the AI
 * labels, the user decides. */
export default function ExamCollegePicker({ examId, collegeId, onChangeExam, onChangeCollege }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-5 shadow-warm space-y-4">
      <div>
        <h3 className="text-small font-semibold text-ink">Which exam is this for?</h3>
        <p className="text-caption text-muted">
          Choose the exam and the college this attestation sheet belongs to before adding files.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <OnePicker
          label="Exam"
          queryKey={['exams']}
          fetchList={getExams}
          create={createExam}
          extractOptions={(exams) => exams.map((e) => ({ id: e.id, label: e.title }))}
          value={examId}
          onChange={onChangeExam}
          createFields={[{ name: 'title', placeholder: 'e.g. M.Com Sem 3 — Sept 2026' }]}
        />
        <OnePicker
          label="College"
          queryKey={['colleges']}
          fetchList={getColleges}
          create={createCollege}
          extractOptions={(colleges) => colleges.map((c) => ({ id: c.id, label: c.name }))}
          value={collegeId}
          onChange={onChangeCollege}
          createFields={[{ name: 'name', placeholder: 'e.g. Gyan Ganga College' }]}
        />
      </div>
    </div>
  )
}
