"""Data shapes shared by the allocator and the validator (§15.4).

Nothing in this module computes anything. That is the point: the allocator
and the validator must agree on what a seat assignment *is* while sharing no
logic whatsoever about whether a given one is correct — see the package
docstring.

Index convention, inherited unchanged from `Room` / `utils/room_capacity.py`
and depended on by everything below: **`col_index`, `seat_index` and
`bench_pos` are all 1-BASED.** `(col_index=1, seat_index=1, bench_pos=1)` is
the first place on the first bench of the first column. There is no
translation layer anywhere in this package; a `blocked_seats` entry of
`{"col": 1, "seat": 1}` names exactly that same place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class RosterEntry:
    """One candidate sitting one paper — the unit of allocation.

    The roster is `Enrollment ⋈ SessionPaper ⋈ Student` (§15.2 step 3), so a
    student enrolled in two papers of the same session appears twice; that
    is a clash, caught at session-save time, not here.
    """

    student_id: str
    offering_id: str
    roll_number: str
    # Flat, storable natural-sort key (utils/roll_sort.py). Ordering uses
    # THIS, never the raw roll string — "100" must not sort before "23".
    roll_sort_key: str
    exam_code: str
    # regular | ex | atkt | private | other (Student.status, or the
    # per-paper Enrollment.status_override when one is set).
    status: str = "regular"
    exam_id: str | None = None
    course_id: str | None = None
    course_name: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.student_id, self.offering_id)


@dataclass(frozen=True)
class RoomSpec:
    """A room as the allocator sees it: the Room row's own geometry plus the
    two facts that come from `SeatingPlanRoom` — where it sits in the room
    order, and which exam it serves.

    `exam_id is None` means "this room takes any paper in the session".
    A non-null `exam_id` means it takes only papers of that exam — §15.2
    step 5's "B.B.LLB goes to the labs and P.G. to Rooms 1–5".
    """

    room_id: str
    # [{"label": "Row 1", "seats": 6}, …] — order IS the column order.
    seat_columns: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    # [{"col": 1, "seat": 4}, …] — 1-based on both axes; blocks the whole
    # bench, i.e. every bench_pos on it.
    blocked_seats: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    seats_per_bench: int = 1
    order_index: int = 0
    exam_id: str | None = None
    name: str = ""


@dataclass(frozen=True)
class Seat:
    """A physical place. 1-based on all three axes (see module docstring)."""

    room_id: str
    col_index: int
    seat_index: int
    bench_pos: int

    @property
    def bench(self) -> tuple[str, int, int]:
        """The bench this place is on — its mates share this triple."""
        return (self.room_id, self.col_index, self.seat_index)


@dataclass(frozen=True)
class Assignment:
    """One candidate placed on one seat."""

    room_id: str
    col_index: int
    seat_index: int
    bench_pos: int
    student_id: str
    offering_id: str
    locked: bool = False

    @property
    def seat(self) -> Seat:
        return Seat(self.room_id, self.col_index, self.seat_index, self.bench_pos)

    @property
    def candidate(self) -> tuple[str, str]:
        return (self.student_id, self.offering_id)


@dataclass(frozen=True)
class Gap:
    """A real, unblocked seat the allocator deliberately left empty.

    Only ever produced to satisfy an adjacency rule: every remaining
    candidate who could have sat here would have broken it. A gap is NOT the
    same thing as a trailing empty seat the roster simply never reached,
    which is why it is recorded rather than re-derived later — after the
    fact the two look identical.
    """

    room_id: str
    col_index: int
    seat_index: int
    bench_pos: int
    reason: str = "adjacency"


@dataclass(frozen=True)
class StaleLock:
    """A lock the allocator could not honour, with the reason why.

    Never silently dropped (§15.4 invariant (d) is about candidates, but the
    same rule of honesty applies): a clerk who locked a seat and then blocked
    that bench must be told the lock is gone, not discover it on exam day.
    """

    assignment: Assignment
    reason: str


@dataclass(frozen=True)
class AllocationResult:
    assignments: tuple[Assignment, ...] = ()
    gaps: tuple[Gap, ...] = ()
    unseated: tuple[RosterEntry, ...] = ()
    stale_locks: tuple[StaleLock, ...] = ()
    strategy: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Violation:
    """One broken invariant, addressed at the thing that broke it.

    `code` is stable and machine-readable (the UI's violations panel keys
    its "go to seat" link off the coordinates); `message` is for a human.
    """

    code: str
    message: str
    room_id: str | None = None
    col_index: int | None = None
    seat_index: int | None = None
    bench_pos: int | None = None
    student_id: str | None = None
    offering_id: str | None = None
    roll_number: str | None = None


@dataclass(frozen=True)
class PlanData:
    """Everything `validate()` needs, and nothing it could cheat with.

    Deliberately NOT an `AllocationResult`: the validator's whole purpose is
    to check assignment rows that may have been hand-edited (moved, swapped,
    locked) long after any allocator ran, or read back from the database in
    a later process.
    """

    assignments: Sequence[Assignment] = ()
    rooms: Sequence[RoomSpec] = ()
    roster: Sequence[RosterEntry] = ()
    locks: Sequence[Assignment] = ()
    unseated: Sequence[RosterEntry] = ()
    strategy: Mapping[str, Any] = field(default_factory=dict)
