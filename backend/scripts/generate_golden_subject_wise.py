"""One-off: (re)generate tests/golden/subject_wise.xlsx from the fixture in
tests/test_export_golden.py. Run this only when a generator change is
deliberate — otherwise the golden-file test in that file is what should be
failing, not this script silently regenerating over the evidence.

Usage (from backend/):
    python scripts/generate_golden_subject_wise.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from test_export_golden import _GOLDEN_PATH, _generate_fixture_bytes  # noqa: E402

if __name__ == "__main__":
    _GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GOLDEN_PATH.write_bytes(_generate_fixture_bytes())
    print(f"Wrote {_GOLDEN_PATH} ({_GOLDEN_PATH.stat().st_size} bytes)")
