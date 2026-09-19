import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SeatGrid from './SeatGrid.jsx'

const COLUMNS = [
  { label: 'Col 1', seats: 3 },
  { label: 'Col 2', seats: 2 },
]

describe('SeatGrid', () => {
  it('renders every seat and marks blocked ones', () => {
    render(<SeatGrid seatColumns={COLUMNS} blockedSeats={[{ col: 1, seat: 2 }]} onToggleSeat={() => {}} />)
    expect(screen.getByLabelText('Column 1, seat 2, blocked')).toBeInTheDocument()
    expect(screen.getByLabelText('Column 1, seat 1')).toBeInTheDocument()
  })

  it('calls onToggleSeat with 1-based (col, seat) on click', async () => {
    const onToggleSeat = vi.fn()
    render(<SeatGrid seatColumns={COLUMNS} blockedSeats={[]} onToggleSeat={onToggleSeat} />)
    await userEvent.click(screen.getByLabelText('Column 2, seat 1'))
    expect(onToggleSeat).toHaveBeenCalledWith(2, 1)
  })

  it('moves focus with arrow keys and toggles the focused seat with Space', async () => {
    const onToggleSeat = vi.fn()
    const user = userEvent.setup()
    render(<SeatGrid seatColumns={COLUMNS} blockedSeats={[]} onToggleSeat={onToggleSeat} />)
    await user.tab() // roving tabindex starts at (1,1) — Tab lands there first
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByLabelText('Column 1, seat 2')).toHaveFocus()
    await userEvent.keyboard(' ')
    expect(onToggleSeat).toHaveBeenCalledWith(1, 2)
  })

  it('does not toggle seats when readOnly', async () => {
    const onToggleSeat = vi.fn()
    render(<SeatGrid seatColumns={COLUMNS} blockedSeats={[]} onToggleSeat={onToggleSeat} readOnly />)
    await userEvent.click(screen.getByLabelText('Column 1, seat 1'))
    expect(onToggleSeat).not.toHaveBeenCalled()
  })
})
