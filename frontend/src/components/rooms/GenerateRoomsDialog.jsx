import { useState } from 'react'
import Modal from '../common/Modal.jsx'
import Button from '../common/Button.jsx'

// §15.1 Option 1 — N identical rooms, one uniform column layout each.
// Validation is deliberately mirrored client-side (not just trusted to the
// 422 from the backend) so a mistake is caught before the round-trip.
export function validateGenerateForm({ count, columns, seatsPerColumn, namePattern }) {
  const errors = {}
  if (!Number.isInteger(count) || count < 1) errors.count = 'Must be at least 1'
  if (!Number.isInteger(columns) || columns < 1) errors.columns = 'Must be at least 1'
  if (!Number.isInteger(seatsPerColumn) || seatsPerColumn < 1) {
    errors.seatsPerColumn = 'Must be at least 1'
  }
  if (!namePattern.includes('{n}')) errors.namePattern = "Must contain '{n}'"
  return errors
}

export default function GenerateRoomsDialog({ open, onClose, onGenerate, generating = false }) {
  const [count, setCount] = useState(5)
  const [columns, setColumns] = useState(4)
  const [seatsPerColumn, setSeatsPerColumn] = useState(10)
  const [seatsPerBench, setSeatsPerBench] = useState(1)
  const [namePattern, setNamePattern] = useState('Room No {n}')
  const [errors, setErrors] = useState({})

  const handleSubmit = () => {
    const validationErrors = validateGenerateForm({ count, columns, seatsPerColumn, namePattern })
    setErrors(validationErrors)
    if (Object.keys(validationErrors).length > 0) return
    onGenerate({
      count,
      columns,
      seats_per_column: seatsPerColumn,
      seats_per_bench: seatsPerBench,
      name_pattern: namePattern,
    })
  }

  const field = (label, value, setValue, key, type = 'number') => (
    <div className="space-y-1.5">
      <label className="text-caption font-medium uppercase tracking-wide text-muted">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => setValue(type === 'number' ? Number(e.target.value) : e.target.value)}
        className="w-full rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
      />
      {errors[key] && <p className="text-caption text-error">{errors[key]}</p>}
    </div>
  )

  return (
    <Modal open={open} onClose={onClose} title="Generate rooms">
      <div className="space-y-4">
        {field('Number of rooms', count, setCount, 'count')}
        {field('Columns per room', columns, setColumns, 'columns')}
        {field('Seats per column', seatsPerColumn, setSeatsPerColumn, 'seatsPerColumn')}
        <div className="space-y-1.5">
          <label className="text-caption font-medium uppercase tracking-wide text-muted">Seats per bench</label>
          <select
            value={seatsPerBench}
            onChange={(e) => setSeatsPerBench(Number(e.target.value))}
            className="w-full rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          >
            {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        {field('Name pattern', namePattern, setNamePattern, 'namePattern', 'text')}
        <Button variant="primary" className="w-full" onClick={handleSubmit} loading={generating}>
          Generate
        </Button>
      </div>
    </Modal>
  )
}
