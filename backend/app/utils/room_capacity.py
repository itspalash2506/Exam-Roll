"""Room capacity — the ONE definition of "how many seats does this room
offer" (FUTURE_UNIFIED.md §15.1, §13.1 rule 5).

    capacity = (Σ seat_columns[].seats − |blocked_seats|) × seats_per_bench

Three consumers must agree on this arithmetic exactly or seating silently
corrupts: `Room.capacity` (the ORM property), `RoomCreate.capacity` (the
live figure the editor shows before anything is saved), and the allocator
(§15.4), whose seat iteration must yield exactly `capacity` seats. Hence one
module, not three copies.

Two rules that are easy to get subtly wrong, spelled out because a later
prompt builds the allocator against them:

1. **Indices are 1-BASED.** `{"col": 1, "seat": 1}` is the first seat of the
   first column. This follows §15.1's own example (`{col: 5, seat: 4}` on a
   five-column room — impossible 0-based) and the physical sheet the model
   comes from, whose columns are labelled "Row 1".."Row 5" and whose seats
   are counted from 1. Anything iterating seats MUST use the same base.
2. **A blocked entry blocks a whole BENCH, not one person's place on it.**
   `seats` counts benches down a column; `seats_per_bench` is how many
   candidates share one bench. That is why the multiplication comes last in
   §15.1's formula: blocking bench 4 of column 5 removes all
   `seats_per_bench` places on it.

Malformed structure raises rather than guessing. A wrong capacity is
invisible — it just quietly under- or over-seats a session — which is the
P0-1 failure class this project keeps paying for.
"""

from typing import Any, Iterable, Mapping, Sequence

# §15.1: a bench seats one, two or three candidates. Not a free integer —
# the seating grid and the adjacency rules (§15.3) are built around these
# three cases only.
SEATS_PER_BENCH_CHOICES: tuple[int, ...] = (1, 2, 3)

# One candidate per bench unless told otherwise. Declared here so the ORM
# column default, the request schema's default and the pre-flush fallback in
# Room.capacity are all the same literal.
DEFAULT_SEATS_PER_BENCH = 1

# Both `col` and `seat` in blocked_seats count from here. See rule 1 above.
SEAT_INDEX_BASE = 1


def _column_seat_counts(seat_columns: Sequence[Mapping[str, Any]] | None) -> list[int]:
    """Validate the seat_columns JSON's shape and return just the counts."""
    if not seat_columns:
        return []
    counts: list[int] = []
    for position, column in enumerate(seat_columns, start=SEAT_INDEX_BASE):
        if not isinstance(column, Mapping):
            raise ValueError(
                f"seat_columns[{position}] is not an object: {column!r}"
            )
        raw = column.get("seats")
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise ValueError(
                f"seat_columns[{position}] has a non-integer 'seats' value: {raw!r}"
            )
        if raw < 0:
            raise ValueError(
                f"seat_columns[{position}] has a negative 'seats' value: {raw}"
            )
        counts.append(raw)
    return counts


def _pair(entry: Mapping[str, Any], position: int) -> tuple[int, int]:
    if not isinstance(entry, Mapping):
        raise ValueError(f"blocked_seats[{position}] is not an object: {entry!r}")
    col, seat = entry.get("col"), entry.get("seat")
    for label, value in (("col", col), ("seat", seat)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(
                f"blocked_seats[{position}] has a non-integer '{label}' value: {value!r}"
            )
    return col, seat


def seat_exists(seat_counts: Sequence[int], col: int, seat: int) -> bool:
    """Is (col, seat) a real seat in a room with these column seat counts?

    1-based on both axes (see the module docstring). The allocator's seat
    iteration and this predicate must describe the same set of seats.
    """
    lo = SEAT_INDEX_BASE
    if not (lo <= col < lo + len(seat_counts)):
        return False
    return lo <= seat < lo + seat_counts[col - lo]


def find_invalid_blocked_seats(
    seat_columns: Sequence[Mapping[str, Any]] | None,
    blocked_seats: Sequence[Mapping[str, Any]] | None,
) -> list[tuple[int, tuple[int, int]]]:
    """Return `(position, (col, seat))` for every blocked entry that does not
    name a real seat — an out-of-range column, or a seat past the end of a
    real column. Position is 1-based, for error messages that point at the
    offending entry.
    """
    seat_counts = _column_seat_counts(seat_columns)
    bad: list[tuple[int, tuple[int, int]]] = []
    for position, entry in enumerate(blocked_seats or (), start=SEAT_INDEX_BASE):
        col, seat = _pair(entry, position)
        if not seat_exists(seat_counts, col, seat):
            bad.append((position, (col, seat)))
    return bad


def find_duplicate_blocked_seats(
    blocked_seats: Sequence[Mapping[str, Any]] | None,
) -> list[tuple[int, tuple[int, int]]]:
    """Return `(position, (col, seat))` for every blocked entry that repeats
    one already listed. Listing the same seat twice is ambiguous data, not a
    second blocked seat: counted naively it would subtract twice and make
    capacity disagree with the number of seats the allocator actually skips.
    """
    seen: set[tuple[int, int]] = set()
    dupes: list[tuple[int, tuple[int, int]]] = []
    for position, entry in enumerate(blocked_seats or (), start=SEAT_INDEX_BASE):
        pair = _pair(entry, position)
        if pair in seen:
            dupes.append((position, pair))
        seen.add(pair)
    return dupes


def blocked_seat_set(
    seat_columns: Sequence[Mapping[str, Any]] | None,
    blocked_seats: Sequence[Mapping[str, Any]] | None,
) -> set[tuple[int, int]]:
    """The set of real seats this room blocks — deduplicated, and ignoring
    entries that name a seat the room does not have.

    Ignoring them here is NOT a silent default: `RoomCreate` refuses to save
    such an entry in the first place (with an error naming it), so this is
    the read path being defensive about a row written around the schema.
    Counting a phantom seat would shrink capacity below what the allocator
    can actually fill, which is the harder failure to see.
    """
    seat_counts = _column_seat_counts(seat_columns)
    return {
        pair
        for pair in (
            _pair(entry, position)
            for position, entry in enumerate(blocked_seats or (), start=SEAT_INDEX_BASE)
        )
        if seat_exists(seat_counts, *pair)
    }


def room_capacity(
    seat_columns: Sequence[Mapping[str, Any]] | None,
    blocked_seats: Sequence[Mapping[str, Any]] | None,
    seats_per_bench: int = 1,
) -> int:
    """(Σ seats − |blocked|) × seats_per_bench — §15.1's formula, verbatim.

    Worked against the real room the model was derived from (§12.1):
    LIBRARY HALL has columns of 3, 13, 13 and 4 benches = 33, two of them
    blocked, one candidate per bench → (33 − 2) × 1 = 31.
    """
    if not isinstance(seats_per_bench, int) or isinstance(seats_per_bench, bool):
        raise ValueError(f"seats_per_bench must be an integer, got {seats_per_bench!r}")
    if seats_per_bench < 1:
        raise ValueError(f"seats_per_bench must be >= 1, got {seats_per_bench}")
    total = sum(_column_seat_counts(seat_columns))
    blocked = len(blocked_seat_set(seat_columns, blocked_seats))
    return (total - blocked) * seats_per_bench


def as_mappings(items: Iterable[Any] | None) -> list[Mapping[str, Any]]:
    """Accept either raw JSON dicts (what the DB hands back) or Pydantic
    models (what a request body parses into) and return plain mappings, so
    every function above has exactly one input shape to reason about."""
    out: list[Mapping[str, Any]] = []
    for item in items or ():
        out.append(item if isinstance(item, Mapping) else item.model_dump())
    return out
