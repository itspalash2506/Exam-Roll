import { useEffect, useState } from 'react'
import { Plus, Minus } from 'lucide-react'
import Button from '../common/Button.jsx'
import SeatGrid from './SeatGrid.jsx'
import { roomCapacity } from '../../utils/roomCapacity.js'

const SEATS_PER_BENCH_CHOICES = [1, 2, 3]

// §15.1 Option 2 — the per-room custom editor: add/remove a column, change
// a column's seat count, click seats to block/unblock, rename, deactivate.
// A room created via "Generate rooms" (Option 1) is just a normal Room
// afterward and lands here unchanged.
export default function RoomEditor({ room, onSave, saving = false }) {
  const [name, setName] = useState(room.name)
  const [building, setBuilding] = useState(room.building ?? '')
  const [isActive, setIsActive] = useState(room.is_active)
  const [seatColumns, setSeatColumns] = useState(room.seat_columns)
  const [blockedSeats, setBlockedSeats] = useState(room.blocked_seats)
  const [seatsPerBench, setSeatsPerBench] = useState(room.seats_per_bench)
  const [notes, setNotes] = useState(room.notes ?? '')

  // Re-sync if a different room is loaded into the same editor instance.
  useEffect(() => {
    setName(room.name)
    setBuilding(room.building ?? '')
    setIsActive(room.is_active)
    setSeatColumns(room.seat_columns)
    setBlockedSeats(room.blocked_seats)
    setSeatsPerBench(room.seats_per_bench)
    setNotes(room.notes ?? '')
  }, [room.id])

  const capacity = roomCapacity(seatColumns, blockedSeats, seatsPerBench)

  const toggleSeat = (col, seat) => {
    setBlockedSeats((prev) => {
      const exists = prev.some((b) => b.col === col && b.seat === seat)
      return exists
        ? prev.filter((b) => !(b.col === col && b.seat === seat))
        : [...prev, { col, seat }]
    })
  }

  const addColumn = () => {
    setSeatColumns((prev) => [...prev, { label: `Col ${prev.length + 1}`, seats: 1 }])
  }

  const removeColumn = () => {
    if (seatColumns.length <= 1) return
    const lastCol = seatColumns.length
    setSeatColumns((prev) => prev.slice(0, -1))
    setBlockedSeats((prev) => prev.filter((b) => b.col !== lastCol))
  }

  const adjustColumnSeats = (colIdx, delta) => {
    setSeatColumns((prev) =>
      prev.map((c, i) => (i === colIdx ? { ...c, seats: Math.max(1, c.seats + delta) } : c)),
    )
    // A shrink can strand a blocked seat past the new count — drop it
    // rather than let the editor hold data the backend would reject.
    setBlockedSeats((prev) => {
      const col = colIdx + 1
      const newSeats = Math.max(1, seatColumns[colIdx].seats + delta)
      return prev.filter((b) => b.col !== col || b.seat <= newSeats)
    })
  }

  const handleSave = () => {
    onSave({
      name,
      building: building || null,
      is_active: isActive,
      seat_columns: seatColumns,
      blocked_seats: blockedSeats,
      seats_per_bench: seatsPerBench,
      notes: notes || null,
    })
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-4">
        <div className="space-y-1.5">
          <label className="text-caption font-medium uppercase tracking-wide text-muted">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-caption font-medium uppercase tracking-wide text-muted">Building</label>
          <input
            value={building}
            onChange={(e) => setBuilding(e.target.value)}
            className="rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-caption font-medium uppercase tracking-wide text-muted">Seats per bench</label>
          <select
            value={seatsPerBench}
            onChange={(e) => setSeatsPerBench(Number(e.target.value))}
            className="rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          >
            {SEATS_PER_BENCH_CHOICES.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 text-small text-ink">
          <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
          Active
        </label>
        <div
          data-testid="capacity-chip"
          className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-highlight/40 px-3 py-1.5 text-small font-semibold text-ink"
        >
          Capacity: {capacity}
        </div>
      </div>

      <div className="rounded-2xl border border-line bg-surface p-5 shadow-warm space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-small font-semibold text-ink">Seat layout</h3>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={addColumn}>
              <Plus size={14} /> Column
            </Button>
            <Button variant="secondary" size="sm" onClick={removeColumn} disabled={seatColumns.length <= 1}>
              <Minus size={14} /> Column
            </Button>
          </div>
        </div>

        <SeatGrid seatColumns={seatColumns} blockedSeats={blockedSeats} onToggleSeat={toggleSeat} />

        <div className="flex flex-wrap gap-3 border-t border-line pt-4">
          {seatColumns.map((c, i) => (
            <div key={i} className="flex items-center gap-1.5 rounded-xl border border-line px-2 py-1">
              <span className="text-caption text-muted">{c.label || `Col ${i + 1}`}</span>
              <button
                type="button"
                onClick={() => adjustColumnSeats(i, -1)}
                className="flex h-5 w-5 items-center justify-center rounded text-muted hover:bg-line/60"
              >
                <Minus size={11} />
              </button>
              <span className="w-5 text-center text-caption font-medium text-ink">{c.seats}</span>
              <button
                type="button"
                onClick={() => adjustColumnSeats(i, 1)}
                className="flex h-5 w-5 items-center justify-center rounded text-muted hover:bg-line/60"
              >
                <Plus size={11} />
              </button>
            </div>
          ))}
        </div>
        <p className="text-caption text-muted">Click a seat to block/unblock it. Arrow keys move focus, Space toggles.</p>
      </div>

      <div className="space-y-1.5">
        <label className="text-caption font-medium uppercase tracking-wide text-muted">Notes</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="w-full rounded-xl border border-line px-3 py-2 text-small text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      <Button variant="primary" onClick={handleSave} loading={saving}>
        Save room
      </Button>
    </div>
  )
}
