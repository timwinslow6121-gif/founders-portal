"""Baseline-ratchet CI guard — fails only when a live count EXCEEDS its baseline."""


def test_baseline_covers_every_registered_invariant(app, db_session):
    from app.integrity import REGISTRY, load_baseline
    baseline = load_baseline()
    missing = [k for k in REGISTRY if k not in baseline]
    assert not missing, f"invariants missing a baseline entry: {missing}"


def test_no_invariant_exceeds_baseline(app, db_session):
    from app.integrity import run_all, load_baseline
    baseline = load_baseline()
    with app.app_context():
        offenders = []
        for v in run_all():
            limit = baseline.get(v.key, 0)
            if v.count > limit:
                offenders.append(f"{v.key}: {v.count} > baseline {limit}")
    assert not offenders, (
        "Data-integrity REGRESSION — a count rose above its frozen baseline:\n"
        + "\n".join(offenders)
        + "\n(Fix the regression, or if intentional run "
          "scripts/audit_integrity.py --update-baseline.)")
