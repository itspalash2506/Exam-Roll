"""Validator tests (FUTURE_UNIFIED.md §15.4).

`test_seating_allocator.py` asserts `validate(allocate(x)) == []` over
hundreds of generated plans. That assertion is worth exactly as much as the
validator's ability to say something is wrong — a `validate()` that returned
`[]` unconditionally would pass every one of those property tests. So every
invariant is also tested by BREAKING a known-good plan in one specific way
and checking the corresponding code comes back.
"""

import pytest

from app.services.seating.allocator import allocate
from app.services.seating.types import Assignment, PlanData, RoomSpec, RosterEntry
from app.services.seating.validator import validate, violation_dicts
from app.utils.roll_sort import roll_sort_key


def _entry(roll: str, offering_id="p1", exam_code="K-1", exam_id="exam-1") -> RosterEntry:
    return RosterEntry(
        student_id=f"stu-{roll}",
        offering_id=offering_id,
        roll_number=roll,
        roll_sort_key=roll_sort_key(roll),
        exam_code=exam_code,
        exam_id=exam_id,
    )


def _room(room_id="r", columns=2, seats=3, **kw) -> RoomSpec:
    return RoomSpec(
        room_id=room_id,
        seat_columns=[{"label": f"Row {i + 1}", "seats": seats} for i in range(columns)],
        blocked_seats=kw.pop("blocked_seats", []),
        seats_per_bench=kw.pop("seats_per_bench", 1),
        name=kw.pop("name", room_id),
        exam_id=kw.pop("exam_id", None),
    )


def _good_plan() -> tuple[PlanData, list[RosterEntry], list[RoomSpec]]:
    roster = [_entry(str(100 + i)) for i in range(4)]
    rooms = [_room()]
    result = allocate(roster, rooms)
    data = PlanData(
        assignments=list(result.assignments),
        rooms=rooms,
        roster=roster,
        locks=[],
        unseated=list(result.unseated),
        strategy=result.strategy,
    )
    assert validate(data) == []
    return data, roster, rooms


def _codes(data: PlanData) -> list[str]:
    return sorted(v.code for v in validate(data))


def _replace(data: PlanData, **kw) -> PlanData:
    fields = dict(
        assignments=list(data.assignments),
        rooms=list(data.rooms),
        roster=list(data.roster),
        locks=list(data.locks),
        unseated=list(data.unseated),
        strategy=dict(data.strategy),
    )
    fields.update(kw)
    return PlanData(**fields)


def test_a_correct_plan_has_no_violations():
    _good_plan()


def test_catches_a_double_booked_seat():
    data, _roster, _rooms = _good_plan()
    first = data.assignments[0]
    clash = Assignment(
        first.room_id, first.col_index, first.seat_index, first.bench_pos,
        data.assignments[1].student_id, data.assignments[1].offering_id,
    )
    broken = _replace(data, assignments=[*data.assignments[2:], first, clash],
                      unseated=[])
    codes = _codes(broken)
    assert "seat_double_booked" in codes


def test_catches_a_seat_the_room_does_not_have():
    data, _roster, _rooms = _good_plan()
    moved = [*data.assignments[1:], Assignment(
        data.assignments[0].room_id, 99, 99, 1,
        data.assignments[0].student_id, data.assignments[0].offering_id,
    )]
    assert "seat_does_not_exist" in _codes(_replace(data, assignments=moved))


def test_catches_a_blocked_seat():
    """The whole reason indices are pinned at 1-based in one place: a room
    that blocks col 1 seat 1 must not have a candidate on col 1 seat 1."""
    data, roster, rooms = _good_plan()
    blocked_room = _room(blocked_seats=[{"col": 1, "seat": 1}])
    assert "blocked_seat_used" in _codes(_replace(data, rooms=[blocked_room]))


def test_catches_a_bench_position_that_does_not_exist():
    data, _roster, _rooms = _good_plan()
    first = data.assignments[0]
    broken = [
        Assignment(first.room_id, first.col_index, first.seat_index, 2,
                   first.student_id, first.offering_id),
        *data.assignments[1:],
    ]
    assert "bench_pos_out_of_range" in _codes(_replace(data, assignments=broken))


def test_catches_a_candidate_who_vanished():
    """§15.4 invariant (d): somebody with no seat who is also not reported
    as unseated is the exact failure this project keeps paying for."""
    data, _roster, _rooms = _good_plan()
    assert _codes(_replace(data, assignments=list(data.assignments)[1:])) == [
        "plan_total_mismatch", "roster_entry_missing"
    ]


def test_catches_a_candidate_seated_twice():
    data, _roster, _rooms = _good_plan()
    first = data.assignments[0]
    duplicate = Assignment(first.room_id, 2, 3, 1, first.student_id, first.offering_id)
    codes = _codes(_replace(data, assignments=[*data.assignments, duplicate]))
    assert "seated_more_than_once" in codes


def test_catches_somebody_who_is_not_on_the_roster():
    data, _roster, _rooms = _good_plan()
    ghost = Assignment("r", 2, 3, 1, "stu-ghost", "p1")
    assert "not_on_roster" in _codes(_replace(data, assignments=[*data.assignments, ghost]))


def test_catches_an_unseated_report_that_contradicts_the_seats():
    data, roster, _rooms = _good_plan()
    assert "unseated_but_seated" in _codes(_replace(data, unseated=[roster[0]]))


def test_catches_a_moved_lock():
    data, _roster, _rooms = _good_plan()
    first = data.assignments[0]
    lock = Assignment("r", 2, 3, 1, first.student_id, first.offering_id, locked=True)
    assert "locked_seat_moved" in _codes(_replace(data, locks=[lock]))


def test_a_lock_on_a_since_blocked_bench_is_not_treated_as_moved():
    """Blocking a bench somebody was locked to removes the lock by that act
    — otherwise the seat-blocking feature would poison a plan forever. The
    allocator reports it as a stale lock instead; that is where the honesty
    lives."""
    roster = [_entry("100")]
    rooms = [_room(columns=1, seats=2, blocked_seats=[{"col": 1, "seat": 2}])]
    lock = Assignment("r", 1, 2, 1, "stu-100", "p1", locked=True)
    result = allocate(roster, rooms, None, [lock])
    data = PlanData(
        assignments=list(result.assignments), rooms=rooms, roster=roster,
        locks=[lock], unseated=list(result.unseated), strategy=result.strategy,
    )
    assert validate(data) == []
    assert [s.reason for s in result.stale_locks] == ["bench has since been blocked"]


def test_catches_an_adjacency_violation_on_a_bench():
    roster = [_entry("100"), _entry("101")]
    rooms = [_room(columns=1, seats=1, seats_per_bench=2)]
    both_same_paper = [
        Assignment("r", 1, 1, 1, "stu-100", "p1"),
        Assignment("r", 1, 1, 2, "stu-101", "p1"),
    ]
    data = PlanData(
        assignments=both_same_paper, rooms=rooms, roster=roster, locks=[],
        unseated=[], strategy={"adjacency": "no_same_paper_on_bench"},
    )
    violations = validate(data)
    assert [v.code for v in violations] == ["adjacency_violation"]
    # Reported once per PAIR, not once per occupant.
    assert len(violations) == 1
    # …and the same seats are fine when the rule is `none`.
    assert validate(_replace(data, strategy={"adjacency": "none"})) == []


def test_front_and_back_are_not_neighbours_on_the_bench_rule():
    """Q5 (§23.1, 2026-09-20): side-by-side only. Two candidates on the same
    paper on consecutive benches of one column is legal."""
    roster = [_entry("100"), _entry("101")]
    rooms = [_room(columns=1, seats=2)]
    data = PlanData(
        assignments=[
            Assignment("r", 1, 1, 1, "stu-100", "p1"),
            Assignment("r", 1, 2, 1, "stu-101", "p1"),
        ],
        rooms=rooms, roster=roster, locks=[], unseated=[],
        strategy={"adjacency": "no_same_paper_on_bench"},
    )
    assert validate(data) == []
    # …but the wider rule does catch them.
    assert [v.code for v in validate(
        _replace(data, strategy={"adjacency": "no_same_paper_neighbours"})
    )] == ["adjacency_violation"]


def test_catches_a_candidate_in_a_room_reserved_for_another_exam():
    roster = [_entry("100", exam_id="pg")]
    rooms = [_room(columns=1, seats=1, exam_id="law")]
    data = PlanData(
        assignments=[Assignment("r", 1, 1, 1, "stu-100", "p1")],
        rooms=rooms, roster=roster, locks=[], unseated=[], strategy={},
    )
    assert [v.code for v in validate(data)] == ["room_exam_mismatch"]


def test_catches_an_assignment_in_a_room_that_is_not_in_the_plan():
    data, _roster, _rooms = _good_plan()
    stray = [
        Assignment("elsewhere", 1, 1, 1, a.student_id, a.offering_id)
        if i == 0 else a
        for i, a in enumerate(data.assignments)
    ]
    assert "unknown_room" in _codes(_replace(data, assignments=stray))


def test_violation_dicts_round_trips_every_field():
    data, _roster, _rooms = _good_plan()
    broken = _replace(data, assignments=list(data.assignments)[1:])
    payload = violation_dicts(validate(broken))
    assert payload and set(payload[0]) == {
        "code", "message", "room_id", "col_index", "seat_index", "bench_pos",
        "student_id", "offering_id", "roll_number",
    }


def test_malformed_room_geometry_raises_rather_than_validating_silently():
    data, _roster, _rooms = _good_plan()
    junk = RoomSpec(room_id="r", seat_columns=[{"label": "x", "seats": "six"}])
    with pytest.raises(ValueError):
        validate(_replace(data, rooms=[junk]))
