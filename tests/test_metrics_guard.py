# tests/test_metrics_guard.py
"""Coherence guard (spec §6.1): book/money numbers are computed ONLY in app/metrics.py.
Fails if a route/view file introduces a new raw policy COUNT or a hardcoded split rate.
Migrate the call into metrics.py, or (rarely) add it to ALLOWLIST with a reason."""
import re, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCANNED = ["app/routes.py", "app/carriers.py", "app/commission/routes.py"]

# Files/lines knowingly still computing their own numbers (shrink over time).
# Format: (relpath, substring that identifies the allowed line)
ALLOWLIST = {
    # e.g. ("app/commission/routes.py", "_reconcile"),  # Round 2 rebuilds this
}

COUNT_RE = re.compile(r"func\.count\(\s*Policy|\.filter_by\([^)]*\)\.count\(\)|Policy\.query[\s\S]{0,80}\.count\(\)")
RATE_RE = re.compile(r"MAPD_MONTHLY_RATE|SPLIT_RATE\s*=")

def test_no_book_or_money_compute_outside_metrics():
    offenders = []
    for rel in SCANNED:
        text = (ROOT / rel).read_text()
        for ln, line in enumerate(text.splitlines(), 1):
            if COUNT_RE.search(line) or RATE_RE.search(line):
                if any(rel == a and sub in line for a, sub in ALLOWLIST):
                    continue
                offenders.append(f"{rel}:{ln}: {line.strip()}")
    assert not offenders, (
        "Book/money computed outside app/metrics.py — move it into metrics.py "
        "or allowlist with a reason:\n" + "\n".join(offenders))
