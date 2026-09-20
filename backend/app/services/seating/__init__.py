"""Seating planner (WS-H, FUTURE_UNIFIED.md §15).

Three layers, deliberately separated:

- `types.py`     — plain data shapes, no logic at all.
- `allocator.py` — `allocate()`, a PURE function: no DB, no I/O, no clock,
                   no global `random`. Given the same inputs it returns the
                   same output, always.
- `validator.py` — `validate()`, which re-derives every invariant in §15.4
                   from the plan's actual assignment rows WITHOUT importing
                   a single line of allocator logic. A shared helper would
                   let one bug hide itself from its own check; §21 ranks
                   this pair fourth in the whole project's precision budget
                   precisely because a wrong seating chart still LOOKS right
                   to the person printing it.
- `lifecycle.py` — the only layer that touches the database.
"""
