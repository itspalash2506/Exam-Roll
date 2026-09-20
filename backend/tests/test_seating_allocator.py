"""Allocator unit + property tests (FUTURE_UNIFIED.md §15.4, §20, §21 #4).

§21 ranks the allocator/validator pair fourth in the whole project's
precision budget for one reason: **a bug still renders a plausible chart**.
Nothing about a wrong seating plan looks wrong on paper — it is discovered
when a real candidate stands in a room with no seat, or two candidates are
sent to the same one. Example-based tests are structurally bad at finding
that, so the four invariants in §15.4 are checked over hundreds of
generated rooms, papers and strategy combinations with Hypothesis, and the
checker (`validator.py`) shares no logic with the thing it checks.
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.services.seating.allocator import (
    ADJACENCIES,
    FILL_ORDERS,
    GROUPINGS,
    ROOM_SPLITS,
    STATUS_PLACEMENTS,
    allocate,
    default_strategy,
    normalize_strategy,
    room_capacity_seats,
    room_seats,
)
from app.services.seating.types import Assignment, PlanData, RoomSpec, RosterEntry
from app.services.seating.validator import validate
from app.utils.roll_sort import roll_sort_key
from app.utils.room_capacity import room_capacity, seat_exists

# 200 examples per property is F04's "Done when" bar; deadline=None because
# a single example builds and validates a whole plan, which is far slower
# than Hypothesis's default per-example budget and would otherwise flake on
# a loaded machine rather than on a real failure.
PROPERTY = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


def _entry(roll: str, offering_id: str, exam_code: str, *, status="regular",
           exam_id="exam-1", course_name=None) -> RosterEntry:
    return RosterEntry(
        student_id=f"stu-{roll}-{offering_id}",
        offering_id=offering_id,
        roll_number=roll,
        roll_sort_key=roll_sort_key(roll),
        exam_code=exam_code,
        status=status,
        exam_id=exam_id,
        course_name=course_name,
    )


def _rect_room(room_id: str, columns: int, seats: int, **kw) -> RoomSpec:
    return RoomSpec(
        room_id=room_id,
        seat_columns=[{"label": f"Row {i + 1}", "seats": seats} for i in range(columns)],
        blocked_seats=kw.pop("blocked_seats", []),
        seats_per_bench=kw.pop("seats_per_bench", 1),
        order_index=kw.pop("order_index", 0),
        exam_id=kw.pop("exam_id", None),
        name=kw.pop("name", room_id),
    )


def _plan_data(result, roster, rooms, locks=()) -> PlanData:
    return PlanData(
        assignments=result.assignments,
        rooms=rooms,
        roster=roster,
        locks=list(locks),
        unseated=result.unseated,
        strategy=result.strategy,
    )


# ── §15.3 defaults ──────────────────────────────────────────────────────────


def test_default_strategy_matches_the_spec_table():
    """Every default in §15.3's right-hand column, verbatim."""
    assert default_strategy() == {
        "fill_order": "column_major",
        "paper_order": "by_exam_code",
        "grouping": "contiguous_by_paper",
        "adjacency": "none",
        "status_placement": "atkt_after_regular_per_paper",
        "room_split": "allow",
        "roll_order": "ascending",
        "seed": 0,
    }


def test_adjacency_default_flips_when_a_bench_is_shared():
    """§15.3's parenthetical, and Q5 (answered 2026-09-20): all occupants of
    a bench must be on different papers as soon as a bench seats more than
    one."""
    assert default_strategy([_rect_room("r", 2, 2)])["adjacency"] == "none"
    shared = [_rect_room("r", 2, 2, seats_per_bench=2)]
    assert default_strategy(shared)["adjacency"] == "no_same_paper_on_bench"


@pytest.mark.parametrize(
    "bad",
    [
        {"fill_order": "diagonal"},
        {"adjacency": "sometimes"},
        {"roll_order": "descending"},
        {"seed": "zero"},
        {"not_a_key": 1},
        {"paper_order": "manual"},  # manual with no order given
    ],
)
def test_unknown_strategy_values_are_rejected_not_ignored(bad):
    """A typo'd key that silently falls back to the default produces a plan
    that does not do what its own stored JSON says it does."""
    with pytest.raises(ValueError):
        normalize_strategy(bad, [])


# ── Seat iteration agrees with the existing capacity helper ─────────────────


def test_seat_iteration_is_one_based_and_matches_room_capacity():
    """The allocator derives room geometry independently of
    utils/room_capacity.py (so a shared off-by-one cannot hide). This test
    is where the two derivations are made to agree."""
    columns = [
        {"label": "Row 1", "seats": 3},
        {"label": "Row 2", "seats": 13},
        {"label": "Row 3", "seats": 13},
        {"label": "Row 4", "seats": 4},
    ]
    blocked = [{"col": 2, "seat": 13}, {"col": 3, "seat": 13}]
    room = RoomSpec(
        room_id="library", seat_columns=columns, blocked_seats=blocked,
        seats_per_bench=1, name="LIBRARY HALL",
    )
    seats = room_seats(room, "column_major")
    assert len(seats) == room_capacity(columns, blocked, 1) == 31
    assert room_capacity_seats(room) == 31
    # 1-based on both axes, and every produced seat is one the existing
    # `seat_exists` predicate agrees exists.
    counts = [c["seats"] for c in columns]
    assert seats[0].col_index == 1 and seats[0].seat_index == 1 and seats[0].bench_pos == 1
    assert all(seat_exists(counts, s.col_index, s.seat_index) for s in seats)
    assert all((s.col_index, s.seat_index) != (2, 13) for s in seats)


def test_blocking_a_bench_removes_every_place_on_it():
    """room_capacity.py rule 2: a blocked entry takes the whole BENCH out of
    service, which is why §15.1's formula multiplies by seats_per_bench
    last."""
    room = _rect_room("r", 2, 2, seats_per_bench=3, blocked_seats=[{"col": 1, "seat": 1}])
    seats = room_seats(room, "column_major")
    assert len(seats) == (4 - 1) * 3 == 9
    assert all((s.col_index, s.seat_index) != (1, 1) for s in seats)


@pytest.mark.parametrize(
    "fill_order,expected",
    [
        ("column_major", [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3)]),
        ("row_major", [(1, 1), (2, 1), (1, 2), (2, 2), (1, 3), (2, 3)]),
        ("serpentine_columns", [(1, 1), (1, 2), (1, 3), (2, 3), (2, 2), (2, 1)]),
    ],
)
def test_fill_orders(fill_order, expected):
    room = _rect_room("r", 2, 3)
    got = [(s.col_index, s.seat_index) for s in room_seats(room, fill_order)]
    assert got == expected


def test_row_major_skips_columns_that_have_run_out():
    """Real rooms are ragged (LIBRARY HALL is 3/13/13/4). Row-major must not
    invent a seat in a short column to keep its grid rectangular."""
    room = RoomSpec(
        room_id="r",
        seat_columns=[{"label": "a", "seats": 1}, {"label": "b", "seats": 3}],
    )
    assert [(s.col_index, s.seat_index) for s in room_seats(room, "row_major")] == [
        (1, 1), (2, 1), (2, 2), (2, 3)
    ]


# ── The Room 1 / column 1 fixture ───────────────────────────────────────────


def test_allocator_reproduces_room1_column1_ordering():
    """§20's fixture: Room 1's first column comes out as 24109301, 302, 304,
    305, 306, 308 under the default strategy.

    SYNTHETIC RECONSTRUCTION, and labelled as such deliberately. The real
    source workbook (`MSW etc A.xlsx`) was never provided to this
    repository and does not exist anywhere in it, so this roster and room
    were built BACKWARD from the expected output documented in
    FUTURE_UNIFIED.md §12.1 ("Room 1 column 1: 24109301 … 24109308
    (K-3678)") rather than derived from real data. It is a regression pin
    on the documented ordering — column-major, roll-ascending, contiguous
    by paper — not evidence that the allocator reproduces the real
    workbook. Re-derive it from the real file when the centre provides one;
    §23.2's Q18 (is `Room 4` one room of 7 columns or two rooms?) is still
    open for the same reason.

    The gap at 303 and 307 is the point of the assertion: the column must
    follow the ROSTER in ascending order, not count upward from the first
    roll.
    """
    present = ["24109301", "24109302", "24109304", "24109305", "24109306", "24109308"]
    rest = [str(24109308 + i) for i in range(1, 25)]  # 24109309 … 24109333
    roster = [_entry(roll, "off-K3678", "K-3678") for roll in present + rest]
    # Six columns of six benches, one candidate per bench — a plain
    # rectangular room in the shape §12.1 describes for Rooms 1–3.
    room = _rect_room("room-1", columns=6, seats=6, name="Room No 1")

    result = allocate(roster, [room])

    assert result.strategy == default_strategy([room])
    assert result.unseated == ()
    assert result.gaps == ()
    column_one = [
        a.student_id for a in result.assignments if a.col_index == 1
    ]
    assert column_one == [f"stu-{roll}-off-K3678" for roll in present]
    # …and column 2 continues where column 1 stopped (§12.1: "continues
    # down column 2, then the next paper begins").
    column_two = [a.student_id for a in result.assignments if a.col_index == 2]
    assert column_two == [f"stu-{roll}-off-K3678" for roll in rest[:6]]
    assert validate(_plan_data(result, roster, [room])) == []


# ── Ordering rules ──────────────────────────────────────────────────────────


def test_rolls_sort_numerically_not_lexicographically():
    """§18: "100" must not come before "23"."""
    roster = [_entry(r, "p1", "K-1") for r in ("100", "23", "9")]
    result = allocate(roster, [_rect_room("r", 1, 3)])
    assert [a.student_id for a in result.assignments] == [
        "stu-9-p1", "stu-23-p1", "stu-100-p1"
    ]


def test_atkt_candidates_come_after_regulars_within_their_paper():
    roster = [
        _entry("500", "p1", "K-1", status="atkt"),
        _entry("100", "p1", "K-1", status="regular"),
        _entry("300", "p1", "K-1", status="ex"),
    ]
    result = allocate(roster, [_rect_room("r", 1, 3)])
    # `ex` is NOT pushed back — §15.3's key names ATKT only.
    assert [a.student_id for a in result.assignments] == [
        "stu-100-p1", "stu-300-p1", "stu-500-p1"
    ]


def test_atkt_rooms_pushes_every_atkt_behind_every_regular():
    roster = [
        _entry("100", "p1", "K-1", status="atkt"),
        _entry("200", "p2", "K-2", status="regular"),
    ]
    result = allocate(
        roster, [_rect_room("r", 1, 2)], {"status_placement": "atkt_rooms"}
    )
    assert [a.student_id for a in result.assignments] == ["stu-200-p2", "stu-100-p1"]


def test_paper_order_by_course_then_code():
    roster = [
        _entry("1", "p1", "K-9", course_name="M.Com"),
        _entry("2", "p2", "K-1", course_name="M.Sc"),
    ]
    result = allocate(roster, [_rect_room("r", 1, 2)], {"paper_order": "by_course_then_code"})
    assert [a.offering_id for a in result.assignments] == ["p1", "p2"]


def test_manual_paper_order_puts_an_unlisted_paper_last_never_drops_it():
    roster = [_entry("1", "p1", "K-1"), _entry("2", "p2", "K-2"), _entry("3", "p3", "K-3")]
    result = allocate(
        roster,
        [_rect_room("r", 1, 3)],
        {"paper_order": "manual", "manual_paper_order": ["p3", "p1"]},
    )
    assert [a.offering_id for a in result.assignments] == ["p3", "p1", "p2"]


def test_interleave_papers_round_robins():
    roster = [_entry(f"1{i}", "p1", "K-1") for i in range(3)] + [
        _entry(f"2{i}", "p2", "K-2") for i in range(3)
    ]
    result = allocate(roster, [_rect_room("r", 1, 6)], {"grouping": "interleave_papers"})
    assert [a.offering_id for a in result.assignments] == [
        "p1", "p2", "p1", "p2", "p1", "p2"
    ]


# ── Adjacency ───────────────────────────────────────────────────────────────


def test_no_same_paper_on_bench_separates_bench_mates():
    """Q5: all occupants of a bench are on different papers; front/back is
    irrelevant, so the bench BEHIND may hold the same paper."""
    roster = [_entry(f"1{i}", "p1", "K-1") for i in range(2)] + [
        _entry(f"2{i}", "p2", "K-2") for i in range(2)
    ]
    room = _rect_room("r", 1, 2, seats_per_bench=2)
    result = allocate(roster, [room], {"adjacency": "no_same_paper_on_bench"})
    by_bench: dict[tuple[int, int], set[str]] = {}
    for a in result.assignments:
        by_bench.setdefault((a.col_index, a.seat_index), set()).add(a.offering_id)
    assert all(len(papers) == 2 for papers in by_bench.values())
    assert result.unseated == ()
    assert validate(_plan_data(result, roster, [room])) == []


def test_adjacency_leaves_a_recorded_gap_when_nobody_fits():
    """§15.4: "if none exists, leave the seat empty and record a gap." One
    paper, two to a bench — the second place on every bench is unfillable,
    and the candidates who could not sit are unseated, not lost."""
    roster = [_entry(str(i), "p1", "K-1") for i in range(4)]
    room = _rect_room("r", 1, 2, seats_per_bench=2)
    result = allocate(roster, [room], {"adjacency": "no_same_paper_on_bench"})
    assert len(result.assignments) == 2
    assert [(g.col_index, g.seat_index, g.bench_pos) for g in result.gaps] == [
        (1, 1, 2), (1, 2, 2)
    ]
    assert len(result.unseated) == 2
    assert validate(_plan_data(result, roster, [room])) == []


def test_no_same_paper_neighbours_also_separates_front_back_and_sideways():
    roster = [_entry(str(i), "p1", "K-1") for i in range(4)]
    room = _rect_room("r", 2, 2)
    result = allocate(roster, [room], {"adjacency": "no_same_paper_neighbours"})
    # A 2x2 grid of one paper under a 4-neighbour rule: only the diagonal
    # pair can sit.
    assert len(result.assignments) == 2
    assert validate(_plan_data(result, roster, [room])) == []


# ── Rooms, exams, splitting ─────────────────────────────────────────────────


def test_a_room_tagged_with_an_exam_takes_only_that_exams_papers():
    """§15.2 step 5 — B.B.LLB goes to the labs, P.G. to Rooms 1–5."""
    pg = [_entry("1", "p1", "K-1", exam_id="pg")]
    law = [_entry("2", "p2", "K-2", exam_id="law")]
    rooms = [
        _rect_room("lab", 1, 1, order_index=0, exam_id="law"),
        _rect_room("room1", 1, 1, order_index=1, exam_id="pg"),
    ]
    result = allocate(pg + law, rooms)
    placed = {a.student_id: a.room_id for a in result.assignments}
    assert placed == {"stu-2-p2": "lab", "stu-1-p1": "room1"}
    assert validate(_plan_data(result, pg + law, rooms)) == []


def test_paper_never_split_keeps_a_paper_in_one_room():
    small = [_entry(f"1{i}", "p1", "K-1") for i in range(2)]
    big = [_entry(f"2{i}", "p2", "K-2") for i in range(3)]
    rooms = [_rect_room("a", 1, 3, order_index=0), _rect_room("b", 1, 3, order_index=1)]
    result = allocate(small + big, rooms, {"room_split": "paper_never_split"})
    rooms_used = {}
    for a in result.assignments:
        rooms_used.setdefault(a.offering_id, set()).add(a.room_id)
    assert all(len(v) == 1 for v in rooms_used.values())
    assert result.unseated == ()


def test_paper_never_split_reports_an_unplaceable_paper_rather_than_splitting_it():
    big = [_entry(str(i), "p1", "K-1") for i in range(5)]
    rooms = [_rect_room("a", 1, 3, order_index=0), _rect_room("b", 1, 3, order_index=1)]
    result = allocate(big, rooms, {"room_split": "paper_never_split"})
    assert result.assignments == ()
    assert len(result.unseated) == 5
    assert validate(_plan_data(result, big, rooms)) == []


def test_room_split_allow_flows_across_rooms_in_order():
    roster = [_entry(str(i), "p1", "K-1") for i in range(4)]
    rooms = [_rect_room("a", 1, 2, order_index=0), _rect_room("b", 1, 2, order_index=1)]
    result = allocate(roster, rooms)
    assert [a.room_id for a in result.assignments] == ["a", "a", "b", "b"]


# ── Locks ───────────────────────────────────────────────────────────────────


def test_locked_seats_are_never_moved():
    roster = [_entry(str(i), "p1", "K-1") for i in range(3)]
    room = _rect_room("r", 1, 3)
    lock = Assignment("r", 1, 3, 1, "stu-0-p1", "p1", locked=True)
    result = allocate(roster, [room], None, [lock])
    placed = {a.student_id: (a.col_index, a.seat_index) for a in result.assignments}
    assert placed["stu-0-p1"] == (1, 3)
    assert validate(_plan_data(result, roster, [room], [lock])) == []


def test_a_lock_on_a_since_blocked_bench_is_reported_not_honoured():
    """§15.5's "block a seat → re-run preserving locks" has an edge the
    spec does not spell out: the blocked seat might be the locked one.
    Honouring the lock would seat a candidate on a bench that is out of
    service, so the lock is dropped — loudly."""
    roster = [_entry("1", "p1", "K-1")]
    room = _rect_room("r", 1, 2, blocked_seats=[{"col": 1, "seat": 2}])
    lock = Assignment("r", 1, 2, 1, "stu-1-p1", "p1", locked=True)
    result = allocate(roster, [room], None, [lock])
    assert [s.reason for s in result.stale_locks] == ["bench has since been blocked"]
    assert [(a.col_index, a.seat_index) for a in result.assignments] == [(1, 1)]
    assert validate(_plan_data(result, roster, [room], [lock])) == []


def test_a_lock_for_a_candidate_off_the_roster_is_reported_not_seated():
    roster = [_entry("1", "p1", "K-1")]
    room = _rect_room("r", 1, 2)
    lock = Assignment("r", 1, 1, 1, "stu-ghost", "p1", locked=True)
    result = allocate(roster, [room], None, [lock])
    assert [s.reason for s in result.stale_locks] == [
        "candidate is not on this session's roster"
    ]
    assert all(a.student_id != "stu-ghost" for a in result.assignments)


def test_contradictory_locks_raise_rather_than_being_guessed_at():
    roster = [_entry("1", "p1", "K-1"), _entry("2", "p1", "K-1")]
    room = _rect_room("r", 1, 2)
    with pytest.raises(ValueError, match="same seat"):
        allocate(roster, [room], None, [
            Assignment("r", 1, 1, 1, "stu-1-p1", "p1", True),
            Assignment("r", 1, 1, 1, "stu-2-p1", "p1", True),
        ])
    with pytest.raises(ValueError, match="two seats"):
        allocate(roster, [room], None, [
            Assignment("r", 1, 1, 1, "stu-1-p1", "p1", True),
            Assignment("r", 1, 2, 1, "stu-1-p1", "p1", True),
        ])


def test_a_duplicated_roster_entry_raises():
    entry = _entry("1", "p1", "K-1")
    with pytest.raises(ValueError, match="twice"):
        allocate([entry, entry], [_rect_room("r", 1, 2)])


# ── Shortfall ───────────────────────────────────────────────────────────────


def test_unseated_is_the_exact_shortfall_and_nobody_is_dropped():
    roster = [_entry(str(i), "p1", "K-1") for i in range(10)]
    room = _rect_room("r", 1, 4)
    result = allocate(roster, [room])
    assert len(result.assignments) == 4
    assert len(result.unseated) == 6
    seated = {a.student_id for a in result.assignments}
    assert seated | {e.student_id for e in result.unseated} == {
        e.student_id for e in roster
    }
    assert validate(_plan_data(result, roster, [room])) == []


# ── Property tests (§15.4 invariants a–d) ───────────────────────────────────


@st.composite
def _rooms(draw):
    count = draw(st.integers(min_value=1, max_value=3))
    rooms = []
    for index in range(count):
        columns = draw(st.integers(min_value=1, max_value=8))
        seat_columns = [
            {"label": f"Row {c + 1}", "seats": draw(st.integers(min_value=1, max_value=20))}
            for c in range(columns)
        ]
        every_seat = [
            (c + 1, s + 1)
            for c, column in enumerate(seat_columns)
            for s in range(column["seats"])
        ]
        blocked = draw(
            st.lists(
                st.sampled_from(every_seat),
                unique=True,
                max_size=min(4, len(every_seat)),
            )
        )
        rooms.append(
            RoomSpec(
                room_id=f"room-{index}",
                seat_columns=seat_columns,
                blocked_seats=[{"col": c, "seat": s} for c, s in blocked],
                seats_per_bench=draw(st.sampled_from([1, 1, 1, 2, 3])),
                order_index=index,
                name=f"Room {index}",
            )
        )
    return rooms


@st.composite
def _roster(draw, capacity: int):
    papers = draw(st.integers(min_value=1, max_value=6))
    # Sometimes short of capacity, sometimes over it — invariant (d) is only
    # interesting when the roster does not fit.
    size = draw(st.integers(min_value=0, max_value=min(capacity + 10, 200)))
    entries = []
    for i in range(size):
        paper = i % papers
        entries.append(
            _entry(
                str(100000 + i),
                f"paper-{paper}",
                f"K-{paper:03d}",
                status=draw(st.sampled_from(["regular", "regular", "ex", "atkt"])),
            )
        )
    return entries


@st.composite
def _strategy(draw):
    return {
        "fill_order": draw(st.sampled_from(FILL_ORDERS)),
        "paper_order": draw(st.sampled_from(["by_exam_code", "by_course_then_code"])),
        "grouping": draw(st.sampled_from(GROUPINGS)),
        "adjacency": draw(st.sampled_from(ADJACENCIES)),
        "status_placement": draw(st.sampled_from(STATUS_PLACEMENTS)),
        "room_split": draw(st.sampled_from(ROOM_SPLITS)),
        "roll_order": "ascending",
        "seed": draw(st.integers(min_value=0, max_value=1000)),
    }


@st.composite
def _scenario(draw):
    rooms = draw(_rooms())
    capacity = sum(room_capacity_seats(r) for r in rooms)
    return draw(_roster(capacity)), rooms, draw(_strategy())


@PROPERTY
@given(_scenario())
def test_property_validate_of_allocate_is_always_empty(scenario):
    """Invariant (a), strengthened: the validator finds nothing wrong with
    an allocation under ANY strategy combination — not merely when capacity
    suffices, because an over-subscribed roster is a legitimate result
    (everyone who did not fit is reported), not a broken plan."""
    roster, rooms, strategy = scenario
    result = allocate(roster, rooms, strategy)
    assert validate(_plan_data(result, roster, rooms)) == []


@PROPERTY
@given(_scenario())
def test_property_same_input_and_seed_gives_an_identical_plan(scenario):
    """Invariant (b). Byte-identical, including the order of every list, so
    that "re-run and diff" is a usable way to review a change."""
    roster, rooms, strategy = scenario
    first = allocate(roster, rooms, strategy)
    second = allocate(roster, rooms, strategy)
    assert first == second


@PROPERTY
@given(_scenario(), st.integers(min_value=0, max_value=7))
def test_property_locked_seats_are_never_moved(scenario, how_many):
    """Invariant (c). Lock a handful of seats from a first run, re-run, and
    every one of them must still hold the same candidate."""
    roster, rooms, strategy = scenario
    first = allocate(roster, rooms, strategy)
    if not first.assignments:
        return
    step = max(1, len(first.assignments) // max(1, how_many or 1))
    locks = [
        Assignment(a.room_id, a.col_index, a.seat_index, a.bench_pos,
                   a.student_id, a.offering_id, locked=True)
        for a in first.assignments[::step][:how_many]
    ]
    second = allocate(roster, rooms, strategy, locks)
    placed = {a.candidate: a.seat for a in second.assignments}
    for lock in locks:
        assert placed.get(lock.candidate) == lock.seat
        assert second.stale_locks == ()
    assert validate(_plan_data(second, roster, rooms, locks)) == []


@PROPERTY
@given(_rooms(), st.integers(min_value=0, max_value=200))
def test_property_unseated_is_exactly_the_capacity_shortfall(rooms, size):
    """Invariant (d), in the conditions where "shortfall" is well-defined:
    one paper, no adjacency rule, no exam-tagged rooms, splitting allowed.
    (With an adjacency rule a seat can be legitimately unusable, and with
    `paper_never_split` a paper larger than every room is unplaceable even
    when the total capacity is ample — both are covered by the example
    tests above, where the exact expected numbers are written out.)"""
    capacity = sum(room_capacity_seats(r) for r in rooms)
    roster = [_entry(str(100000 + i), "p1", "K-1") for i in range(size)]
    result = allocate(roster, rooms, {"adjacency": "none", "room_split": "allow"})
    assert len(result.unseated) == max(0, size - capacity)
    assert len(result.assignments) == min(size, capacity)
    # …and nobody is in neither list.
    assert {a.candidate for a in result.assignments} | {
        e.key for e in result.unseated
    } == {e.key for e in roster}
