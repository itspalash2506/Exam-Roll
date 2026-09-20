"""The independent seating validator (FUTURE_UNIFIED.md §15.4).

**This module imports nothing from `allocator.py`, by design.** Only the
inert data shapes in `types.py` are shared. Every predicate below — which
seats a room actually has, which benches are blocked, which seats count as
neighbours — is re-derived here from the room's own `seat_columns` /
`blocked_seats` JSON rather than reusing the allocator's helpers (or even
`utils/room_capacity.py`). A shared off-by-one in a 1-based seat index would
otherwise be invisible: the allocator would produce the wrong seats and its
own checker would happily agree they were the right ones.

§15.4's own justification for the separation is the workbook's `Room 4`,
whose two printed `TOTAL` cells (30 and 11) do not add up to the block's 41
without knowing which sub-block each covers. Arithmetic that a human got
wrong on paper is exactly the arithmetic the app must own, and own twice.

`validate()` never raises for bad plan content: a malformed plan is a list of
violations, because the caller's job is to show them to a clerk, not to
crash. It raises only on structurally unusable ROOM geometry, which cannot
come from the room editor.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from app.services.seating.types import Assignment, PlanData, RoomSpec, Violation


def _counts(room: RoomSpec) -> list[int]:
    counts: list[int] = []
    for position, column in enumerate(room.seat_columns or (), start=1):
        raw = column.get("seats") if isinstance(column, Mapping) else None
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            raise ValueError(
                f"room {room.room_id}: seat_columns[{position}] has a bad "
                f"'seats' value: {raw!r}"
            )
        counts.append(raw)
    return counts


def _exists(counts: Sequence[int], col: int, seat: int) -> bool:
    """1-based on both axes — the same convention `Room.blocked_seats`,
    `utils/room_capacity.seat_exists` and the allocator all use. Written out
    longhand here rather than imported; see the module docstring."""
    if col < 1 or col > len(counts):
        return False
    return 1 <= seat <= counts[col - 1]


def _blocked(room: RoomSpec, counts: Sequence[int]) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for entry in room.blocked_seats or ():
        if not isinstance(entry, Mapping):
            continue
        col, seat = entry.get("col"), entry.get("seat")
        if isinstance(col, int) and isinstance(seat, int) and not isinstance(col, bool):
            if _exists(counts, col, seat):
                out.add((col, seat))
    return out


def _neighbours(
    col: int, seat: int, bench_pos: int, counts: Sequence[int], per_bench: int, rule: str
) -> list[tuple[int, int, int]]:
    """Seats whose occupant must not share a paper with (col, seat, bench_pos).

    `no_same_paper_on_bench` — the other places on the same bench, and only
    those (Q5, §23.1: side-by-side only; front/back is irrelevant because a
    candidate cannot read the paper of someone facing away).
    `no_same_paper_neighbours` — also the bench ahead, behind, left and right.
    """
    if rule == "none":
        return []
    out = [(col, seat, p) for p in range(1, per_bench + 1) if p != bench_pos]
    if rule == "no_same_paper_neighbours":
        for c, s in ((col, seat - 1), (col, seat + 1), (col - 1, seat), (col + 1, seat)):
            if _exists(counts, c, s):
                out.extend((c, s, p) for p in range(1, per_bench + 1))
    return out


def validate(plan: PlanData) -> list[Violation]:
    """Every §15.4 invariant, checked against the plan's actual rows."""
    violations: list[Violation] = []

    rooms_by_id: dict[str, RoomSpec] = {room.room_id: room for room in plan.rooms}
    geometry: dict[str, tuple[list[int], set[tuple[int, int]], int]] = {}
    for room_id, room in rooms_by_id.items():
        counts = _counts(room)
        per_bench = room.seats_per_bench or 1
        geometry[room_id] = (counts, _blocked(room, counts), per_bench)

    roster_by_key = {e.key: e for e in plan.roster}
    unseated_keys = [e.key for e in plan.unseated]
    rule = (plan.strategy or {}).get("adjacency", "none")

    def roll(key: tuple[str, str]) -> str | None:
        entry = roster_by_key.get(key)
        return entry.roll_number if entry else None

    # ── Seats: exist, unblocked, used at most once ──────────────────────────
    seat_owner: dict[tuple[str, int, int, int], Assignment] = {}
    for a in plan.assignments:
        coord = (a.room_id, a.col_index, a.seat_index, a.bench_pos)
        if coord in seat_owner:
            other = seat_owner[coord]
            violations.append(Violation(
                code="seat_double_booked",
                message=(
                    f"seat {a.room_id} col {a.col_index} seat {a.seat_index} "
                    f"pos {a.bench_pos} holds two candidates: "
                    f"{roll(other.candidate) or other.student_id} and "
                    f"{roll(a.candidate) or a.student_id}"
                ),
                room_id=a.room_id, col_index=a.col_index,
                seat_index=a.seat_index, bench_pos=a.bench_pos,
                student_id=a.student_id, offering_id=a.offering_id,
                roll_number=roll(a.candidate),
            ))
            continue
        seat_owner[coord] = a

        if a.room_id not in geometry:
            violations.append(Violation(
                code="unknown_room",
                message=f"assignment names room {a.room_id}, which is not in this plan",
                room_id=a.room_id, col_index=a.col_index,
                seat_index=a.seat_index, bench_pos=a.bench_pos,
                student_id=a.student_id, offering_id=a.offering_id,
                roll_number=roll(a.candidate),
            ))
            continue

        counts, blocked, per_bench = geometry[a.room_id]
        if not _exists(counts, a.col_index, a.seat_index):
            violations.append(Violation(
                code="seat_does_not_exist",
                message=(
                    f"room {rooms_by_id[a.room_id].name or a.room_id} has no "
                    f"col {a.col_index} seat {a.seat_index}"
                ),
                room_id=a.room_id, col_index=a.col_index,
                seat_index=a.seat_index, bench_pos=a.bench_pos,
                student_id=a.student_id, offering_id=a.offering_id,
                roll_number=roll(a.candidate),
            ))
        elif (a.col_index, a.seat_index) in blocked:
            violations.append(Violation(
                code="blocked_seat_used",
                message=(
                    f"col {a.col_index} seat {a.seat_index} of room "
                    f"{rooms_by_id[a.room_id].name or a.room_id} is blocked"
                ),
                room_id=a.room_id, col_index=a.col_index,
                seat_index=a.seat_index, bench_pos=a.bench_pos,
                student_id=a.student_id, offering_id=a.offering_id,
                roll_number=roll(a.candidate),
            ))
        if not (1 <= a.bench_pos <= per_bench):
            violations.append(Violation(
                code="bench_pos_out_of_range",
                message=(
                    f"bench position {a.bench_pos} does not exist on a bench "
                    f"seating {per_bench}"
                ),
                room_id=a.room_id, col_index=a.col_index,
                seat_index=a.seat_index, bench_pos=a.bench_pos,
                student_id=a.student_id, offering_id=a.offering_id,
                roll_number=roll(a.candidate),
            ))

        room = rooms_by_id[a.room_id]
        entry = roster_by_key.get(a.candidate)
        if room.exam_id is not None and entry is not None and entry.exam_id != room.exam_id:
            violations.append(Violation(
                code="room_exam_mismatch",
                message=(
                    f"{entry.roll_number} sits {entry.exam_code}, but room "
                    f"{room.name or room.room_id} is reserved for another exam"
                ),
                room_id=a.room_id, col_index=a.col_index,
                seat_index=a.seat_index, bench_pos=a.bench_pos,
                student_id=a.student_id, offering_id=a.offering_id,
                roll_number=entry.roll_number,
            ))

    # ── Candidates: on the roster, seated exactly once ──────────────────────
    seats_by_candidate: dict[tuple[str, str], list[Assignment]] = defaultdict(list)
    for a in plan.assignments:
        seats_by_candidate[a.candidate].append(a)

    for candidate, placements in sorted(seats_by_candidate.items()):
        if candidate not in roster_by_key:
            a = placements[0]
            violations.append(Violation(
                code="not_on_roster",
                message=(
                    f"student {a.student_id} is seated for paper {a.offering_id} "
                    "but is not on this session's roster"
                ),
                room_id=a.room_id, col_index=a.col_index,
                seat_index=a.seat_index, bench_pos=a.bench_pos,
                student_id=a.student_id, offering_id=a.offering_id,
            ))
        if len(placements) > 1:
            a = placements[0]
            where = ", ".join(
                f"{p.room_id}/{p.col_index}/{p.seat_index}/{p.bench_pos}"
                for p in placements
            )
            violations.append(Violation(
                code="seated_more_than_once",
                message=f"{roll(candidate) or a.student_id} is seated {len(placements)} times: {where}",
                room_id=a.room_id, col_index=a.col_index,
                seat_index=a.seat_index, bench_pos=a.bench_pos,
                student_id=a.student_id, offering_id=a.offering_id,
                roll_number=roll(candidate),
            ))

    unseated_set = set(unseated_keys)
    for key, entry in sorted(roster_by_key.items()):
        seated = key in seats_by_candidate
        if seated and key in unseated_set:
            violations.append(Violation(
                code="unseated_but_seated",
                message=(
                    f"{entry.roll_number} is reported unseated but holds a seat"
                ),
                student_id=entry.student_id, offering_id=entry.offering_id,
                roll_number=entry.roll_number,
            ))
        elif not seated and key not in unseated_set:
            # The §15.4 (d) invariant: nobody disappears quietly.
            violations.append(Violation(
                code="roster_entry_missing",
                message=(
                    f"{entry.roll_number} ({entry.exam_code}) has no seat and "
                    "is not reported as unseated"
                ),
                student_id=entry.student_id, offering_id=entry.offering_id,
                roll_number=entry.roll_number,
            ))

    seen_unseated: set[tuple[str, str]] = set()
    for entry in plan.unseated:
        if entry.key not in roster_by_key:
            violations.append(Violation(
                code="unseated_not_on_roster",
                message=(
                    f"{entry.roll_number} is reported unseated but is not on "
                    "the roster"
                ),
                student_id=entry.student_id, offering_id=entry.offering_id,
                roll_number=entry.roll_number,
            ))
        if entry.key in seen_unseated:
            violations.append(Violation(
                code="unseated_listed_twice",
                message=f"{entry.roll_number} is listed as unseated twice",
                student_id=entry.student_id, offering_id=entry.offering_id,
                roll_number=entry.roll_number,
            ))
        seen_unseated.add(entry.key)

    # ── Locks: never moved ──────────────────────────────────────────────────
    # A lock is expected to be honoured only if it is still honourable: its
    # seat must still exist, still be unblocked, and its candidate must still
    # be on the roster. A clerk who blocks the bench somebody was locked to
    # has removed the lock by that act; failing the plan forever afterwards
    # would make the seat-blocking feature unusable. The allocator reports
    # those as `stale_locks` so the clerk is told — that is where the
    # honesty lives, not here.
    placed_at: dict[tuple[str, str], tuple[str, int, int, int]] = {
        cand: (p[0].room_id, p[0].col_index, p[0].seat_index, p[0].bench_pos)
        for cand, p in seats_by_candidate.items()
    }
    for lock in plan.locks:
        if lock.room_id not in geometry:
            continue
        counts, blocked, per_bench = geometry[lock.room_id]
        if not _exists(counts, lock.col_index, lock.seat_index):
            continue
        if (lock.col_index, lock.seat_index) in blocked:
            continue
        if not (1 <= lock.bench_pos <= per_bench):
            continue
        if lock.candidate not in roster_by_key:
            # An un-rostered candidate must NOT be seated, lock or no lock.
            if lock.candidate in placed_at:
                violations.append(Violation(
                    code="stale_lock_seated",
                    message=(
                        f"student {lock.student_id} is locked into a seat but "
                        "is not on this session's roster"
                    ),
                    room_id=lock.room_id, col_index=lock.col_index,
                    seat_index=lock.seat_index, bench_pos=lock.bench_pos,
                    student_id=lock.student_id, offering_id=lock.offering_id,
                ))
            continue
        want = (lock.room_id, lock.col_index, lock.seat_index, lock.bench_pos)
        got = placed_at.get(lock.candidate)
        if got != want:
            violations.append(Violation(
                code="locked_seat_moved",
                message=(
                    f"{roll(lock.candidate)} is locked to "
                    f"{lock.room_id} col {lock.col_index} seat "
                    f"{lock.seat_index} pos {lock.bench_pos} but is "
                    + (f"at {got[0]} col {got[1]} seat {got[2]} pos {got[3]}"
                       if got else "not seated at all")
                ),
                room_id=lock.room_id, col_index=lock.col_index,
                seat_index=lock.seat_index, bench_pos=lock.bench_pos,
                student_id=lock.student_id, offering_id=lock.offering_id,
                roll_number=roll(lock.candidate),
            ))

    # ── Adjacency ───────────────────────────────────────────────────────────
    if rule != "none":
        paper_at: dict[tuple[str, int, int, int], str] = {
            coord: a.offering_id for coord, a in seat_owner.items()
        }
        reported: set[frozenset] = set()
        for coord, a in sorted(seat_owner.items()):
            room_id, col, seat, pos = coord
            if room_id not in geometry:
                continue
            counts, _blk, per_bench = geometry[room_id]
            for c, s, p in _neighbours(col, seat, pos, counts, per_bench, rule):
                other = paper_at.get((room_id, c, s, p))
                if other is None or other != a.offering_id:
                    continue
                pair = frozenset({coord, (room_id, c, s, p)})
                if pair in reported:
                    continue
                reported.add(pair)
                violations.append(Violation(
                    code="adjacency_violation",
                    message=(
                        f"{roll(a.candidate) or a.student_id} at col {col} seat "
                        f"{seat} pos {pos} and the candidate at col {c} seat {s} "
                        f"pos {p} both sit {a.offering_id} — the plan's "
                        f"adjacency rule is {rule}"
                    ),
                    room_id=room_id, col_index=col, seat_index=seat,
                    bench_pos=pos, student_id=a.student_id,
                    offering_id=a.offering_id, roll_number=roll(a.candidate),
                ))

    # ── Totals (§15.4's last line) ──────────────────────────────────────────
    per_room: dict[str, int] = defaultdict(int)
    for a in plan.assignments:
        per_room[a.room_id] += 1
    if sum(per_room.values()) != len(plan.assignments):  # pragma: no cover
        violations.append(Violation(
            code="room_total_mismatch",
            message=(
                f"room totals sum to {sum(per_room.values())} but the plan "
                f"holds {len(plan.assignments)} assignments"
            ),
        ))

    expected = len(roster_by_key) - len(unseated_set)
    distinct_seated = len(seats_by_candidate)
    if distinct_seated != expected:
        violations.append(Violation(
            code="plan_total_mismatch",
            message=(
                f"{distinct_seated} candidates are seated; roster size "
                f"({len(roster_by_key)}) minus unseated ({len(unseated_set)}) "
                f"is {expected}"
            ),
        ))

    return violations


def violation_dicts(violations: Sequence[Violation]) -> list[dict[str, Any]]:
    """Wire form for the API layer, kept here so the field names have one
    definition rather than one per router."""
    return [
        {
            "code": v.code,
            "message": v.message,
            "room_id": v.room_id,
            "col_index": v.col_index,
            "seat_index": v.seat_index,
            "bench_pos": v.bench_pos,
            "student_id": v.student_id,
            "offering_id": v.offering_id,
            "roll_number": v.roll_number,
        }
        for v in violations
    ]
