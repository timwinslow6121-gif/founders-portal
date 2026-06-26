"""Data-Integrity Radar CLI. Read-only.
  ./venv/bin/python3 scripts/audit_integrity.py             # table + exit 1 if regressed
  ./venv/bin/python3 scripts/audit_integrity.py --json
  ./venv/bin/python3 scripts/audit_integrity.py --update-baseline   # re-freeze
On VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/audit_integrity.py
"""
import sys
import json
import os

# Allow import from app module when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.integrity import run_all, load_baseline, BASELINE_PATH


def build_report():
    """Build a data-integrity report: list of dicts with counts vs baselines.

    Returns:
        list[dict]: Each dict has keys: key, domain, severity, count, baseline,
                    delta, description, sample
    """
    baseline = load_baseline()
    out = []
    for v in run_all():
        base = baseline.get(v.key, 0)
        out.append({
            "key": v.key,
            "domain": v.domain,
            "severity": v.severity,
            "count": v.count,
            "baseline": base,
            "delta": v.count - base,
            "description": v.description,
            "sample": v.sample
        })
    return out


def main(argv):
    """Run the CLI, handling --json, --update-baseline, or table output."""
    app = create_app()
    with app.app_context():
        if "--update-baseline" in argv:
            new = {v.key: v.count for v in run_all()}
            BASELINE_PATH.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n")
            print(f"baseline updated: {new}")
            return 0

        report = build_report()

        if "--json" in argv:
            print(json.dumps([{k: r[k] for k in
                  ("key", "domain", "severity", "count", "baseline")} for r in report]))
            return 0

        # Default: table output
        regressed = False
        print(f"{'KEY':28} {'DOMAIN':12} {'SEV':5} {'COUNT':>7} {'BASE':>7} {'Δ':>6}")
        print("-" * 78)
        for r in report:
            flag = "  <== REGRESSION" if r["delta"] > 0 else ""
            if r["delta"] > 0:
                regressed = True
            print(f"{r['key']:28} {r['domain']:12} {r['severity']:5} "
                  f"{r['count']:7} {r['baseline']:7} {r['delta']:6}{flag}")

        return 1 if regressed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
