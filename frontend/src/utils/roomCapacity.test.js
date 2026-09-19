import { describe, it, expect } from 'vitest'
import { roomCapacity } from './roomCapacity.js'

// Mirrors backend/tests/test_rooms_model.py's LIBRARY HALL fixture — the
// same real room (columns of 3/13/13/4, two blocked) both sides of the
// stack must agree on.
const LIBRARY_HALL_COLUMNS = [
  { label: 'Row 1', seats: 3 },
  { label: 'Row 2', seats: 13 },
  { label: 'Row 3', seats: 13 },
  { label: 'Row 4', seats: 4 },
]
const LIBRARY_HALL_BLOCKED = [{ col: 2, seat: 13 }, { col: 3, seat: 13 }]

describe('roomCapacity', () => {
  it('matches the real LIBRARY HALL capacity (31)', () => {
    expect(roomCapacity(LIBRARY_HALL_COLUMNS, LIBRARY_HALL_BLOCKED, 1)).toBe(31)
  })

  it('updates when a seat is blocked', () => {
    const columns = [{ label: 'Col 1', seats: 10 }]
    expect(roomCapacity(columns, [], 1)).toBe(10)
    expect(roomCapacity(columns, [{ col: 1, seat: 5 }], 1)).toBe(9)
  })

  it('updates when a seat is unblocked', () => {
    const columns = [{ label: 'Col 1', seats: 10 }]
    expect(roomCapacity(columns, [{ col: 1, seat: 5 }], 1)).toBe(9)
    expect(roomCapacity(columns, [], 1)).toBe(10)
  })

  it('scales with seats_per_bench', () => {
    const columns = [{ label: 'Col 1', seats: 10 }]
    expect(roomCapacity(columns, [], 2)).toBe(20)
    expect(roomCapacity(columns, [], 3)).toBe(30)
  })

  it('ignores a blocked entry naming a seat the room does not have', () => {
    const columns = [{ label: 'Col 1', seats: 5 }]
    expect(roomCapacity(columns, [{ col: 1, seat: 99 }], 1)).toBe(5)
    expect(roomCapacity(columns, [{ col: 99, seat: 1 }], 1)).toBe(5)
  })
})
