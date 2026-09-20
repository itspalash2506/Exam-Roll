#!/usr/bin/env python
"""Opus gate — UserPromptSubmit hook.

FUTURE_UNIFIED.md §21 ranks the work where an error is invisible or
irreversible. Those tasks are designated Opus-only. This hook fires when a
prompt looks like one of them and makes the session stop and ask which model
to use, instead of quietly proceeding on whatever is loaded.

It is a prompt, not a block: the answer may legitimately be "stay on Sonnet".
What it prevents is the question never being asked.

Reads the hook payload as JSON on stdin; prints a JSON directive on stdout
when a designated task is detected, nothing otherwise. Never fails the
prompt — any error exits 0 silently, because a broken gate must not stop work.
"""

import json
import re
import sys

# Tier 1 — Opus, not negotiable. Wrong here is invisible or irreversible.
TIER1 = {
    "F04": "seating allocator + validator (§21 #4) — adjacency look-ahead, "
           "locked seats, non-rectangular rooms. A bug still renders a "
           "plausible chart.",
    "F07": "attendance/UFM model + roles (§21 #5) — concurrent clerk upserts, "
           "audit trail, legally significant record.",
    "M04": "retention janitor tier 3 + migration 0006_drop_blobs (§21 #10) — "
           "irreversible deletion of student records and JSON blobs.",
}

# Tier 2 — Opus worth it on the named slice; the rest of the prompt is Sonnet work.
TIER2 = {
    "F02": "the Room.seat_columns schema only — wrong shape propagates into "
           "F04 and F06. CRUD/API around it is Sonnet work.",
    "F06": "the reconciliation core (§17.1) only — one count, every output "
           "reads it. O1/O5/O7 layout is Sonnet work.",
    "P11": "the export race only (P1-17/P1-18: atomic rename, to_thread). "
           "The generator half is Sonnet work.",
    "M05": "P1-13/P1-14/P1-15 only — CancelledError escaping the failure "
           "handler leaves jobs permanently stranded.",
}

# Work described without its prompt ID. The milestone is the work, not the label.
KEYWORDS = {
    r"\ballocat(or|ion)\b": "F04",
    r"\bseat[_ ]assignment": "F04",
    r"\bseating plan\b": "F04",
    r"\bdrop[_ ]blobs\b": "M04",
    r"\bretention janitor\b": "M04",
    r"\b0006\b": "M04",
    r"\battendance (upsert|entry|model)\b": "F07",
    r"\bmalpractice|UFM case\b": "F07",
    r"\breconciliation\b": "F06",
    r"\bcancellederror\b": "M05",
}

ID_RE = re.compile(r"\b(F02|F04|F06|F07|M04|M05|P11)\b", re.IGNORECASE)


def detect(prompt: str) -> tuple[set[str], set[str]]:
    """Return (tier1_ids, tier2_ids) mentioned or described in the prompt."""
    hits = {m.group(1).upper() for m in ID_RE.finditer(prompt)}
    for pattern, task in KEYWORDS.items():
        if re.search(pattern, prompt, re.IGNORECASE):
            hits.add(task)
    return hits & TIER1.keys(), hits & TIER2.keys()


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    prompt = str(payload.get("prompt") or "")
    if not prompt:
        return

    tier1, tier2 = detect(prompt)
    if not tier1 and not tier2:
        return

    lines = []
    for task in sorted(tier1):
        lines.append(f"  {task} [OPUS] {TIER1[task]}")
    for task in sorted(tier2):
        lines.append(f"  {task} [OPUS if budget allows] {TIER2[task]}")
    detail = "\n".join(lines)

    named = ", ".join(sorted(tier1 | tier2))
    context = (
        "MODEL GATE (.claude/hooks/opus_gate.py). This prompt touches work "
        f"designated Opus-only in FUTURE_UNIFIED.md §21: {named}\n"
        f"{detail}\n\n"
        "Before writing any code for this task, STOP and tell the user this "
        "task is designated Opus-only, naming which one and why. You CANNOT "
        "switch the model yourself and neither can this hook — only the user "
        "can, by typing /model opus. So ask them to either switch now and "
        "re-send the prompt, or say explicitly that they want to proceed on "
        "the current model. Do not start the work until they answer. If they "
        "have already answered for this task in this session, honour that "
        "choice without asking again."
    )

    print(json.dumps({
        "systemMessage": f"Model gate: {named} is designated Opus-only (§21). "
                         "Switch with /model opus — this hook cannot switch it "
                         "for you.",
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        },
    }))


if __name__ == "__main__":
    main()
