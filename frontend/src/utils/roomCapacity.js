// Mirrors backend/app/utils/room_capacity.py's formula exactly, for the
// live capacity chip while editing a room (before the save round-trip).
// 1-based (col, seat) indices — same convention as the backend.
export function roomCapacity(seatColumns, blockedSeats, seatsPerBench = 1) {
  const total = (seatColumns ?? []).reduce((sum, c) => sum + (c.seats || 0), 0)
  const validColumns = new Set((seatColumns ?? []).map((_, i) => i + 1))
  const blockedSet = new Set()
  for (const b of blockedSeats ?? []) {
    if (!validColumns.has(b.col)) continue
    const seatsInCol = seatColumns[b.col - 1]?.seats ?? 0
    if (b.seat < 1 || b.seat > seatsInCol) continue
    blockedSet.add(`${b.col}-${b.seat}`)
  }
  return (total - blockedSet.size) * (seatsPerBench || 1)
}
