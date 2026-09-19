import { useRef, useState } from 'react'
import clsx from 'clsx'

// Renders a room as columns of seats (§15.1 — not rows x cols; real rooms
// are non-rectangular). blockedSeats/onToggleSeat use 1-based (col, seat)
// indices, matching the backend's utils/room_capacity.py convention exactly
// — this component must never silently pick a different base.
//
// Keyboard: a roving tabindex (only the focused seat is in the tab order —
// WAI-ARIA APG grid pattern) with arrow keys moving focus within/between
// columns and Space/Enter toggling the focused seat, so the grid is fully
// operable without a mouse (F03 §15.6, P1 accessibility requirement).
export default function SeatGrid({ seatColumns, blockedSeats, onToggleSeat, readOnly = false }) {
  const blockedSet = new Set((blockedSeats ?? []).map((b) => `${b.col}-${b.seat}`))
  const [focused, setFocused] = useState({ col: 1, seat: 1 })
  const refs = useRef({})

  const isBlocked = (col, seat) => blockedSet.has(`${col}-${seat}`)

  const focusSeat = (col, seat) => {
    const clampedCol = Math.min(Math.max(col, 1), seatColumns.length)
    const seatsInCol = seatColumns[clampedCol - 1]?.seats ?? 1
    const clampedSeat = Math.min(Math.max(seat, 1), seatsInCol)
    setFocused({ col: clampedCol, seat: clampedSeat })
    refs.current[`${clampedCol}-${clampedSeat}`]?.focus()
  }

  const handleKeyDown = (e, col, seat) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        focusSeat(col, seat + 1)
        break
      case 'ArrowUp':
        e.preventDefault()
        focusSeat(col, seat - 1)
        break
      case 'ArrowRight':
        e.preventDefault()
        focusSeat(col + 1, seat)
        break
      case 'ArrowLeft':
        e.preventDefault()
        focusSeat(col - 1, seat)
        break
      case ' ':
      case 'Enter':
        e.preventDefault()
        if (!readOnly) onToggleSeat?.(col, seat)
        break
      default:
        break
    }
  }

  return (
    <div className="flex gap-3 overflow-x-auto pb-2" role="grid" aria-label="Room seat layout">
      {seatColumns.map((column, colIdx) => {
        const col = colIdx + 1
        return (
          <div key={col} role="row" className="flex flex-col items-center gap-1.5">
            <p className="text-caption font-medium text-muted">{column.label || `Col ${col}`}</p>
            {Array.from({ length: column.seats }, (_, seatIdx) => {
              const seat = seatIdx + 1
              const blocked = isBlocked(col, seat)
              const isFocusTarget = focused.col === col && focused.seat === seat
              return (
                <button
                  key={seat}
                  ref={(el) => { refs.current[`${col}-${seat}`] = el }}
                  type="button"
                  role="gridcell"
                  tabIndex={isFocusTarget ? 0 : -1}
                  aria-pressed={blocked}
                  aria-label={`Column ${col}, seat ${seat}${blocked ? ', blocked' : ''}`}
                  disabled={readOnly}
                  onFocus={() => setFocused({ col, seat })}
                  onKeyDown={(e) => handleKeyDown(e, col, seat)}
                  onClick={() => !readOnly && onToggleSeat?.(col, seat)}
                  className={clsx(
                    'flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-caption font-medium transition-colors duration-fast focus:outline-none focus:ring-2 focus:ring-primary/50',
                    blocked
                      ? 'bg-seat-blocked/10 text-seat-blocked'
                      : 'bg-seat-empty/10 text-seat-empty hover:bg-seat-empty/20',
                    !readOnly && 'cursor-pointer',
                  )}
                >
                  {blocked ? '×' : seat}
                </button>
              )
            })}
          </div>
        )
      })}
    </div>
  )
}
