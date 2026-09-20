"""The seating allocator (FUTURE_UNIFIED.md §15.3, §15.4).

A deterministic greedy placement, not a constraint solver. §15.4 is explicit
about that, and the reason is the one in §21 #4: a solver that occasionally
returns a different-but-also-valid plan would make "re-run and compare"
useless, and a seating bug is invisible — a wrong chart still prints
beautifully and is only discovered when a real candidate has no seat.

Three properties this module is written to guarantee:

1. **Pure.** No database, no filesystem, no clock, no network, no global
   `random`. `allocate()` is a function of its arguments alone.
2. **Deterministic.** Every ordering decision breaks ties on stable data
   (`roll_sort_key`, then `roll_number`, then the ids). There is no
   randomness in the algorithm today — `seed` is normalised, carried on the
   result and stored on the plan so that a future strategy that *does* need
   a random element has exactly one legitimate source for it,
   `random.Random(strategy["seed"])`, and never the module-global `random`.
   Inventing a shuffle nobody asked for would be worse than an unused key.
3. **Never silent.** Every candidate is either assigned a seat or listed in
   `unseated`; every seat skipped for adjacency is listed in `gaps`; every
   lock that could not be honoured is listed in `stale_locks`. The whole
   class of bug this project keeps paying for (P0-1) is a default applied
   quietly, so nothing here is dropped without being named.

Index convention: 1-based on all three axes, matching `Room` and
`utils/room_capacity.py` verbatim. No translation happens anywhere in this
file — see `types.py`.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from app.services.seating.types import (
    AllocationResult,
    Assignment,
    Gap,
    RoomSpec,
    RosterEntry,
    Seat,
    StaleLock,
)

logger = logging.getLogger(__name__)

# ── Strategy keys (§15.3, verbatim) ─────────────────────────────────────────
# The table in §15.3 is the contract. An unknown key or an unknown value is
# rejected rather than ignored: a typo'd strategy that silently falls back to
# the default is a plan that does not do what its own stored JSON says.

FILL_ORDERS = ("column_major", "row_major", "serpentine_columns")
PAPER_ORDERS = ("by_exam_code", "by_course_then_code", "manual")
GROUPINGS = ("contiguous_by_paper", "interleave_papers")
ADJACENCIES = ("none", "no_same_paper_on_bench", "no_same_paper_neighbours")
STATUS_PLACEMENTS = ("mixed", "atkt_after_regular_per_paper", "atkt_rooms")
ROOM_SPLITS = ("allow", "paper_never_split")
ROLL_ORDERS = ("ascending",)  # §15.3: "fixed"

_ALLOWED: dict[str, tuple[str, ...]] = {
    "fill_order": FILL_ORDERS,
    "paper_order": PAPER_ORDERS,
    "grouping": GROUPINGS,
    "adjacency": ADJACENCIES,
    "status_placement": STATUS_PLACEMENTS,
    "room_split": ROOM_SPLITS,
    "roll_order": ROLL_ORDERS,
}

# `manual` paper_order reads its order from here: a list of offering_ids.
# Papers not named in it follow, ordered by exam_code — an omitted paper is
# placed last, never dropped.
MANUAL_ORDER_KEY = "manual_paper_order"

STRATEGY_KEYS = frozenset({*_ALLOWED, MANUAL_ORDER_KEY, "seed"})

# The status that `atkt_after_regular_per_paper` / `atkt_rooms` push to the
# back. §12.1 found three classes on the sheets — Regular / Ex / ATKT — and
# only ATKT is named in §15.3's key, so `ex` is ordered with the regulars.
ATKT_STATUS = "atkt"


def default_strategy(rooms: Sequence[RoomSpec] | None = None) -> dict[str, Any]:
    """§15.3's default column, exactly.

    `adjacency` is the one default that depends on the rooms: `none`
    normally, `no_same_paper_on_bench` as soon as any room seats more than
    one candidate per bench. That is Q5, answered 2026-09-20 (§23.1) — all
    occupants of a bench must be on different papers; front/back is
    irrelevant, side-by-side only.
    """
    shares_a_bench = any((r.seats_per_bench or 1) > 1 for r in (rooms or ()))
    return {
        "fill_order": "column_major",
        "paper_order": "by_exam_code",
        "grouping": "contiguous_by_paper",
        "adjacency": "no_same_paper_on_bench" if shares_a_bench else "none",
        "status_placement": "atkt_after_regular_per_paper",
        "room_split": "allow",
        "roll_order": "ascending",
        "seed": 0,
    }


def normalize_strategy(
    strategy: Mapping[str, Any] | None, rooms: Sequence[RoomSpec] | None = None
) -> dict[str, Any]:
    """Overlay `strategy` on the defaults, rejecting anything unrecognised."""
    merged = default_strategy(rooms)
    for key, value in (strategy or {}).items():
        if key not in STRATEGY_KEYS:
            raise ValueError(
                f"unknown strategy key {key!r}; allowed keys are "
                f"{sorted(STRATEGY_KEYS)}"
            )
        merged[key] = value

    for key, allowed in _ALLOWED.items():
        if merged[key] not in allowed:
            raise ValueError(
                f"strategy[{key!r}] = {merged[key]!r} is not one of {list(allowed)}"
            )

    seed = merged.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"strategy['seed'] must be an int, got {seed!r}")

    manual = merged.get(MANUAL_ORDER_KEY)
    if manual is not None:
        if not isinstance(manual, (list, tuple)) or not all(
            isinstance(x, str) for x in manual
        ):
            raise ValueError(
                f"strategy[{MANUAL_ORDER_KEY!r}] must be a list of offering ids"
            )
        merged[MANUAL_ORDER_KEY] = list(manual)
    if merged["paper_order"] == "manual" and not merged.get(MANUAL_ORDER_KEY):
        raise ValueError(
            "paper_order='manual' needs a non-empty "
            f"strategy[{MANUAL_ORDER_KEY!r}] listing the offering ids in order"
        )
    return merged


# ── Room geometry ───────────────────────────────────────────────────────────
# Re-derived here from `seat_columns` rather than imported from
# room_capacity, for one narrow reason: the allocator must produce EXACTLY
# the seats that module's `seat_exists` predicate accepts, and the way to
# keep that honest is for the tests to compare two independent derivations
# (see tests/test_seating_allocator.py), not for both to call one function
# that could be off by one in agreement with itself.


def _seat_counts(room: RoomSpec) -> list[int]:
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


def _blocked(room: RoomSpec, counts: Sequence[int]) -> set[tuple[int, int]]:
    """The benches this room has taken out of service, 1-based, deduplicated,
    ignoring entries that do not name a bench the room actually has (the
    room editor refuses to save those; this is the read path being defensive
    about a row written around it)."""
    out: set[tuple[int, int]] = set()
    for position, entry in enumerate(room.blocked_seats or (), start=1):
        if not isinstance(entry, Mapping):
            raise ValueError(
                f"room {room.room_id}: blocked_seats[{position}] is not an object"
            )
        col, seat = entry.get("col"), entry.get("seat")
        for label, value in (("col", col), ("seat", seat)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(
                    f"room {room.room_id}: blocked_seats[{position}] has a "
                    f"non-integer {label!r}: {value!r}"
                )
        if 1 <= col <= len(counts) and 1 <= seat <= counts[col - 1]:
            out.add((col, seat))
    return out


def _bench_positions(room: RoomSpec) -> range:
    per_bench = room.seats_per_bench or 1
    if not isinstance(per_bench, int) or isinstance(per_bench, bool) or per_bench < 1:
        raise ValueError(
            f"room {room.room_id}: seats_per_bench must be >= 1, got {per_bench!r}"
        )
    return range(1, per_bench + 1)


def room_seats(room: RoomSpec, fill_order: str) -> list[Seat]:
    """Every usable place in the room, in the order the strategy fills them.

    Blocked benches are omitted entirely — every `bench_pos` on a blocked
    bench, since `blocked_seats` takes a whole bench out of service
    (room_capacity.py rule 2, which is why §15.1's capacity formula
    multiplies by `seats_per_bench` last).
    """
    counts = _seat_counts(room)
    blocked = _blocked(room, counts)
    positions = list(_bench_positions(room))
    seats: list[Seat] = []

    def add(col: int, seat: int) -> None:
        if (col, seat) in blocked:
            return
        for pos in positions:
            seats.append(Seat(room.room_id, col, seat, pos))

    if fill_order == "column_major":
        for col in range(1, len(counts) + 1):
            for seat in range(1, counts[col - 1] + 1):
                add(col, seat)
    elif fill_order == "serpentine_columns":
        # Boustrophedon down the columns: column 1 front-to-back, column 2
        # back-to-front, and so on. The column ORDER never reverses, only the
        # direction of travel within one.
        for col in range(1, len(counts) + 1):
            rows = range(1, counts[col - 1] + 1)
            for seat in (rows if col % 2 == 1 else reversed(rows)):
                add(col, seat)
    elif fill_order == "row_major":
        # Across the front bench of every column, then the second bench of
        # every column… Columns are ragged, so a column that has run out is
        # simply skipped rather than padded with seats that do not exist.
        deepest = max(counts, default=0)
        for seat in range(1, deepest + 1):
            for col in range(1, len(counts) + 1):
                if seat <= counts[col - 1]:
                    add(col, seat)
    else:  # pragma: no cover — normalize_strategy rejects anything else
        raise ValueError(f"unknown fill_order {fill_order!r}")
    return seats


def room_capacity_seats(room: RoomSpec) -> int:
    """How many candidates this room can hold. Independent of fill order."""
    counts = _seat_counts(room)
    blocked = _blocked(room, counts)
    return (sum(counts) - len(blocked)) * (room.seats_per_bench or 1)


# ── Roster ordering (§15.4 line 1) ──────────────────────────────────────────


def _is_atkt(entry: RosterEntry) -> bool:
    return (entry.status or "").strip().lower() == ATKT_STATUS


def _paper_ranks(
    roster: Iterable[RosterEntry], strategy: Mapping[str, Any]
) -> dict[str, tuple]:
    """A sort rank per offering_id, per `paper_order`.

    Ties always fall through to `offering_id` so that two papers sharing an
    exam code (which UNIQUE(org, exam, exam_code) forbids within one exam,
    but not across two exams in the same session) still order stably.
    """
    order = strategy["paper_order"]
    papers: dict[str, RosterEntry] = {}
    for entry in roster:
        papers.setdefault(entry.offering_id, entry)

    if order == "manual":
        manual = list(strategy.get(MANUAL_ORDER_KEY) or ())
        position = {offering_id: i for i, offering_id in enumerate(manual)}
        # A paper the caller forgot to list goes LAST, in exam-code order —
        # never dropped, and never silently first.
        return {
            offering_id: (
                position.get(offering_id, len(position)),
                entry.exam_code if offering_id not in position else "",
                offering_id,
            )
            for offering_id, entry in papers.items()
        }

    if order == "by_course_then_code":
        return {
            offering_id: (
                entry.course_name or entry.course_id or "",
                entry.exam_code,
                offering_id,
            )
            for offering_id, entry in papers.items()
        }

    # by_exam_code (the default, and what the workbook's Room Dist does)
    return {
        offering_id: (entry.exam_code, offering_id)
        for offering_id, entry in papers.items()
    }


def _sort_key(
    entry: RosterEntry, ranks: Mapping[str, tuple], strategy: Mapping[str, Any]
) -> tuple:
    placement = strategy["status_placement"]
    # `atkt_rooms` pushes every ATKT candidate behind every regular one
    # GLOBALLY, so they flow into the trailing rooms — that is what makes
    # them "ATKT rooms" without the allocator needing a separate room tag.
    phase = 1 if (placement == "atkt_rooms" and _is_atkt(entry)) else 0
    # `atkt_after_regular_per_paper` keeps them inside their own paper block,
    # just at the end of it (the workbook's older-prefix cohort).
    within = 1 if (placement == "atkt_after_regular_per_paper" and _is_atkt(entry)) else 0
    return (
        phase,
        ranks[entry.offering_id],
        within,
        # roll_order is fixed ascending (§15.3); roll_sort_key is what makes
        # "100" sort after "23" instead of before it (§18).
        entry.roll_sort_key,
        entry.roll_number,
        entry.student_id,
        entry.offering_id,
    )


def _interleave(entries: Sequence[RosterEntry], ranks: Mapping[str, tuple]) -> list[RosterEntry]:
    """Round-robin across papers, preserving each paper's internal order.

    §15.4: "round-robin across papers per bench so that adjacency holds".
    This only changes the ORDER candidates are offered in; the adjacency
    rule itself is still enforced seat by seat below, so interleaving is a
    heuristic that makes the rule cheap to satisfy, never a substitute for
    checking it.
    """
    blocks: dict[str, list[RosterEntry]] = defaultdict(list)
    for entry in entries:  # entries already in _sort_key order
        blocks[entry.offering_id].append(entry)
    ordered_papers = sorted(blocks, key=lambda oid: ranks[oid])
    out: list[RosterEntry] = []
    index = 0
    while len(out) < len(entries):
        emitted = False
        for offering_id in ordered_papers:
            block = blocks[offering_id]
            if index < len(block):
                out.append(block[index])
                emitted = True
        if not emitted:  # pragma: no cover — loop guard
            break
        index += 1
    return out


def order_roster(
    roster: Sequence[RosterEntry], strategy: Mapping[str, Any]
) -> list[RosterEntry]:
    """The roster in the order candidates are offered seats."""
    ranks = _paper_ranks(roster, strategy)
    ordered = sorted(roster, key=lambda e: _sort_key(e, ranks, strategy))
    if strategy["grouping"] != "interleave_papers":
        return ordered
    # Interleave within each status phase separately, so `atkt_rooms` still
    # holds: every regular is offered a seat before any ATKT candidate.
    phases: dict[int, list[RosterEntry]] = defaultdict(list)
    for entry in ordered:
        phases[_sort_key(entry, ranks, strategy)[0]].append(entry)
    out: list[RosterEntry] = []
    for phase in sorted(phases):
        out.extend(_interleave(phases[phase], ranks))
    return out


# ── Adjacency (§15.3 `adjacency`, Q5 answered 2026-09-20) ───────────────────


def _neighbour_seats(seat: Seat, counts: Sequence[int], positions: Sequence[int], rule: str
                     ) -> list[Seat]:
    """Every seat whose occupant this seat's occupant may not share a paper
    with, under `rule`.

    - `no_same_paper_on_bench`: the other places on the SAME bench. Q5 is
      explicit — side-by-side only; the candidate in front of you is not a
      problem, because they cannot see your paper.
    - `no_same_paper_neighbours`: that, plus the bench in front, the bench
      behind, and the benches immediately left and right in the neighbouring
      columns.
    """
    if rule == "none":
        return []
    out = [
        Seat(seat.room_id, seat.col_index, seat.seat_index, pos)
        for pos in positions
        if pos != seat.bench_pos
    ]
    if rule == "no_same_paper_neighbours":
        candidates = [
            (seat.col_index, seat.seat_index - 1),
            (seat.col_index, seat.seat_index + 1),
            (seat.col_index - 1, seat.seat_index),
            (seat.col_index + 1, seat.seat_index),
        ]
        for col, index in candidates:
            if 1 <= col <= len(counts) and 1 <= index <= counts[col - 1]:
                out.extend(
                    Seat(seat.room_id, col, index, pos) for pos in positions
                )
    return out


# ── Locks ───────────────────────────────────────────────────────────────────


def _index_locks(
    locked: Sequence[Assignment], rooms: Sequence[RoomSpec]
) -> tuple[dict[Seat, Assignment], list[StaleLock]]:
    """Split the incoming locks into the ones that can be honoured and the
    ones that cannot, with a reason for each of the latter.

    A lock naming a seat that no longer exists, or a bench that has since
    been blocked, is NOT honoured — honouring it would put a candidate on a
    seat the room does not offer, which is the one outcome this whole module
    exists to prevent. It is returned as a `StaleLock` instead, so the caller
    can tell the clerk their lock is gone rather than letting them find out
    on exam day.

    Structurally impossible input (two locks on one seat, one candidate
    locked twice) raises: the database's own UNIQUE constraints make it
    unreachable from the app, so it means the caller built the list wrong.
    """
    geometry: dict[str, tuple[list[int], set[tuple[int, int]], list[int]]] = {}
    for room in rooms:
        counts = _seat_counts(room)
        geometry[room.room_id] = (
            counts,
            _blocked(room, counts),
            list(_bench_positions(room)),
        )

    honoured: dict[Seat, Assignment] = {}
    by_candidate: dict[tuple[str, str], Seat] = {}
    stale: list[StaleLock] = []

    for lock in locked:
        seat = lock.seat
        if seat in honoured:
            raise ValueError(
                f"two locks name the same seat {seat}: "
                f"{honoured[seat].candidate} and {lock.candidate}"
            )
        if lock.candidate in by_candidate:
            raise ValueError(
                f"candidate {lock.candidate} is locked to two seats: "
                f"{by_candidate[lock.candidate]} and {seat}"
            )

        if seat.room_id not in geometry:
            stale.append(StaleLock(lock, "room is not part of this plan"))
            continue
        counts, blocked, positions = geometry[seat.room_id]
        if not (1 <= seat.col_index <= len(counts)) or not (
            1 <= seat.seat_index <= counts[seat.col_index - 1]
        ):
            stale.append(StaleLock(lock, "seat no longer exists in this room"))
            continue
        if seat.bench_pos not in positions:
            stale.append(StaleLock(lock, "bench position no longer exists"))
            continue
        if (seat.col_index, seat.seat_index) in blocked:
            stale.append(StaleLock(lock, "bench has since been blocked"))
            continue

        honoured[seat] = lock
        by_candidate[lock.candidate] = seat

    return honoured, stale


# ── Placement ───────────────────────────────────────────────────────────────


def _fits(room: RoomSpec, entry: RosterEntry) -> bool:
    """§15.2 step 5: a room tagged with an exam serves only that exam."""
    return room.exam_id is None or entry.exam_id == room.exam_id


def _fill_room(
    room: RoomSpec,
    queue: list[RosterEntry],
    occupancy: dict[Seat, str],
    taken: set[Seat],
    strategy: Mapping[str, Any],
) -> tuple[list[Assignment], list[Gap]]:
    """Walk this room's seats in fill order, taking candidates off the front
    of `queue` (which is mutated).

    The adjacency look-ahead is §15.4's, verbatim: when the next candidate
    would violate the rule at this seat, look ahead in the roster for the
    first who would not; if none exists, leave the seat empty and record a
    gap. Checking only against ALREADY-placed neighbours is sufficient
    because the rule is pairwise and symmetric — when the neighbour is filled
    later, it is checked against this seat in turn.
    """
    counts = _seat_counts(room)
    positions = list(_bench_positions(room))
    rule = strategy["adjacency"]
    placed: list[Assignment] = []
    gaps: list[Gap] = []

    for seat in room_seats(room, strategy["fill_order"]):
        if seat in taken:
            continue  # a locked candidate already holds it
        if not queue:
            break
        forbidden = {
            occupancy[n]
            for n in _neighbour_seats(seat, counts, positions, rule)
            if n in occupancy
        }
        chosen = -1
        any_compatible = False
        for i, entry in enumerate(queue):
            if not _fits(room, entry):
                continue
            any_compatible = True
            if entry.offering_id in forbidden:
                continue
            chosen = i
            break
        if chosen < 0:
            if any_compatible:
                # Somebody could have sat here; the adjacency rule is what
                # stopped them. That is a gap, and it is recorded.
                gaps.append(Gap(seat.room_id, seat.col_index, seat.seat_index,
                                seat.bench_pos))
            continue
        entry = queue.pop(chosen)
        occupancy[seat] = entry.offering_id
        taken.add(seat)
        placed.append(
            Assignment(
                room_id=seat.room_id,
                col_index=seat.col_index,
                seat_index=seat.seat_index,
                bench_pos=seat.bench_pos,
                student_id=entry.student_id,
                offering_id=entry.offering_id,
                locked=False,
            )
        )
    return placed, gaps


def _pools_never_split(
    ordered: Sequence[RosterEntry],
    rooms: Sequence[RoomSpec],
    free_seats: Mapping[str, int],
    lock_rooms: Mapping[tuple[str, str], str],
    strategy: Mapping[str, Any],
) -> tuple[dict[str, list[RosterEntry]], list[RosterEntry]]:
    """`room_split = paper_never_split`: first-fit whole papers into rooms.

    A paper some of whose candidates are already LOCKED into a room is bound
    to that room — a lock outranks the split preference, because the clerk
    put it there on purpose. If a paper's locks are spread over two rooms it
    is already split and cannot be unsplit without moving a lock, so it binds
    to whichever room holds more of them (ties by room order) and the
    preference is simply not achievable for that paper; nothing is dropped.
    """
    ranks = _paper_ranks(ordered, strategy)
    blocks: dict[str, list[RosterEntry]] = defaultdict(list)
    for entry in ordered:
        blocks[entry.offering_id].append(entry)

    remaining = dict(free_seats)
    pools: dict[str, list[RosterEntry]] = {room.room_id: [] for room in rooms}
    unplaceable: list[RosterEntry] = []

    for offering_id in sorted(blocks, key=lambda oid: ranks[oid]):
        block = blocks[offering_id]
        bound: dict[str, int] = defaultdict(int)
        for entry in block:
            room_id = lock_rooms.get(entry.key)
            if room_id is not None:
                bound[room_id] += 1
        if bound:
            order = {room.room_id: i for i, room in enumerate(rooms)}
            target = min(bound, key=lambda rid: (-bound[rid], order.get(rid, 1 << 30)))
        else:
            target = next(
                (
                    room.room_id
                    for room in rooms
                    if _fits(room, block[0]) and remaining.get(room.room_id, 0) >= len(block)
                ),
                None,
            )
        if target is None:
            # No single room can hold this paper. Honest outcome: its
            # candidates go to `unseated` with everyone else who did not fit,
            # rather than quietly splitting the paper the strategy forbade
            # splitting.
            unplaceable.extend(block)
            continue
        pools[target].extend(block)
        remaining[target] = remaining.get(target, 0) - len(block)

    return pools, unplaceable


def allocate(
    roster: Sequence[RosterEntry],
    rooms: Sequence[RoomSpec],
    strategy: Mapping[str, Any] | None = None,
    locked: Sequence[Assignment] = (),
) -> AllocationResult:
    """Place every candidate on the roster into a seat (§15.4).

    Returns assignments (locked ones included, unmoved), the seats skipped to
    satisfy adjacency, the candidates who did not fit, and the locks that
    could not be honoured. Raises `ValueError` only for structurally invalid
    input — a malformed room, an unknown strategy value, a duplicated roster
    entry, contradictory locks — never for "it did not all fit", which is a
    result, not an error.
    """
    rooms = sorted(rooms, key=lambda r: (r.order_index, r.room_id))
    strategy = normalize_strategy(strategy, rooms)

    seen: set[tuple[str, str]] = set()
    for entry in roster:
        if entry.key in seen:
            raise ValueError(
                f"roster contains {entry.key} twice — a (student, paper) pair "
                "is unique by construction (UNIQUE(student_id, offering_id))"
            )
        seen.add(entry.key)

    honoured, stale = _index_locks(locked, rooms)
    by_candidate = {lock.candidate: seat for seat, lock in honoured.items()}

    # A lock for somebody who is not on this roster cannot be honoured
    # either: seating them would put a candidate in the room who is not
    # sitting the exam. Reported, never silently applied.
    rostered = {entry.key for entry in roster}
    for seat, lock in sorted(honoured.items(), key=lambda kv: _seat_sort(kv[0])):
        if lock.candidate not in rostered:
            stale.append(StaleLock(lock, "candidate is not on this session's roster"))
    honoured = {
        seat: lock for seat, lock in honoured.items() if lock.candidate in rostered
    }
    by_candidate = {lock.candidate: seat for seat, lock in honoured.items()}

    occupancy: dict[Seat, str] = {
        seat: lock.offering_id for seat, lock in honoured.items()
    }
    taken: set[Seat] = set(honoured)

    to_place = [e for e in roster if e.key not in by_candidate]
    ordered = order_roster(to_place, strategy)

    locks_per_room: dict[str, int] = defaultdict(int)
    for seat in honoured:
        locks_per_room[seat.room_id] += 1
    free_seats = {
        room.room_id: room_capacity_seats(room) - locks_per_room[room.room_id]
        for room in rooms
    }

    assignments: list[Assignment] = [
        Assignment(
            room_id=seat.room_id,
            col_index=seat.col_index,
            seat_index=seat.seat_index,
            bench_pos=seat.bench_pos,
            student_id=lock.student_id,
            offering_id=lock.offering_id,
            locked=True,
        )
        for seat, lock in honoured.items()
    ]
    gaps: list[Gap] = []

    if strategy["room_split"] == "paper_never_split":
        lock_rooms = {cand: seat.room_id for cand, seat in by_candidate.items()}
        pools, unplaceable = _pools_never_split(
            ordered, rooms, free_seats, lock_rooms, strategy
        )
        leftovers: list[RosterEntry] = list(unplaceable)
        for room in rooms:
            queue = pools[room.room_id]
            placed, room_gaps = _fill_room(room, queue, occupancy, taken, strategy)
            assignments.extend(placed)
            gaps.extend(room_gaps)
            leftovers.extend(queue)  # whatever _fill_room could not seat
        unseated = leftovers
    else:
        queue = list(ordered)
        for room in rooms:
            placed, room_gaps = _fill_room(room, queue, occupancy, taken, strategy)
            assignments.extend(placed)
            gaps.extend(room_gaps)
        unseated = queue

    room_order = {room.room_id: i for i, room in enumerate(rooms)}
    assignments.sort(
        key=lambda a: (
            room_order.get(a.room_id, 1 << 30),
            a.room_id,
            a.col_index,
            a.seat_index,
            a.bench_pos,
        )
    )
    gaps.sort(
        key=lambda g: (
            room_order.get(g.room_id, 1 << 30),
            g.room_id,
            g.col_index,
            g.seat_index,
            g.bench_pos,
        )
    )
    ranks = _paper_ranks(roster, strategy)
    unseated.sort(key=lambda e: _sort_key(e, ranks, strategy))
    stale.sort(key=lambda s: (s.assignment.room_id, s.assignment.col_index,
                              s.assignment.seat_index, s.assignment.bench_pos))

    return AllocationResult(
        assignments=tuple(assignments),
        gaps=tuple(gaps),
        unseated=tuple(unseated),
        stale_locks=tuple(stale),
        strategy=strategy,
    )


def _seat_sort(seat: Seat) -> tuple:
    return (seat.room_id, seat.col_index, seat.seat_index, seat.bench_pos)
