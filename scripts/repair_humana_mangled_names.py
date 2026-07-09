"""One-time repair: fix Humana commission customers whose name was mangled by the old
name-parser ('LAST SUFFIX FIRST' → stored as first='Jr', real first name dropped).

The old _humana_name took the token right after the last name as the first name, so
'MORGAN JR BILLY N' became first='Jr', last='Morgan' → 'Jr Morgan' (Billy lost). The
parser is now fixed; this backfills the EXISTING corrupted customers from the raw Humana
commission file's GrpName, keyed by the commission PID (= Policy.member_id / customer's
carrier_member_id). Recomputes the correct name via the fixed _humana_name +
normalize_person_name. Skips manually_edited customers. Read-only unless --apply.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/repair_humana_mangled_names.py \
      --agency 1 --commission "docs/Commission DL/.../CommissionData (5).xlsx" [--apply]
"""
import argparse
import xml.etree.ElementTree as ET

from app import create_app
from app.extensions import db
from app.models import Customer, Policy
from app.commission.normalizers import _humana_name
from app.names import normalize_person_name

_SUFFIX = {"JR", "SR", "II", "III", "IV", "V"}


def _grpname_by_pid(path):
    """PID → GrpName from the raw Humana commission file (Excel-2003 XML)."""
    raw = open(path, encoding="utf-8", errors="replace").read()
    raw = '<?xml version="1.0"?>\n' + raw[raw.find("<Workbook"):]
    root = ET.fromstring(raw)
    ns = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}
    rows = root.findall(".//ss:Row", ns)

    def cells(r):
        out = []
        for c in r.findall("ss:Cell", ns):
            d = c.find("ss:Data", ns)
            out.append((d.text or "") if d is not None else "")
        return out

    hdr = cells(rows[0])
    idx = {h: i for i, h in enumerate(hdr)}

    def g(r, n):
        i = idx.get(n)
        return r[i] if i is not None and i < len(r) else ""

    out = {}
    for row in rows[1:]:
        r = cells(row)
        pid = g(r, "PID").strip()
        grp = g(r, "GrpName").strip()
        if pid and grp and pid not in out:
            out[pid] = grp
    return out


def _is_mangled(cust):
    return (cust.first_name or "").upper().strip(".") in _SUFFIX


def repair(agency_id, commission_path, apply=False):
    pid2grp = _grpname_by_pid(commission_path)
    counts = {"fixed": 0, "skipped_manual": 0, "no_grpname": 0}
    fixes = []
    # mangled customers = Humana commission customers whose first_name is a suffix
    mangled = (Customer.query
               .filter(Customer.agency_id == agency_id,
                       db.func.upper(Customer.first_name).in_(list(_SUFFIX)))
               .all())
    for cust in mangled:
        # find the commission PID from any of this customer's Humana policies
        pid = None
        for pol in Policy.query.filter_by(agency_id=agency_id, carrier="Humana",
                                          customer_id=cust.id).all():
            if (pol.member_id or "").isdigit():
                pid = pol.member_id; break
        grp = pid2grp.get(pid) if pid else None
        if not grp:
            counts["no_grpname"] += 1
            continue
        if cust.manually_edited:
            counts["skipped_manual"] += 1
            continue
        _, gf, gl = _humana_name(grp)
        first, mi, last, full = normalize_person_name(f"{gl}, {gf}")
        fixes.append((cust.full_name, full))
        counts["fixed"] += 1
        if apply:
            cust.first_name = first
            cust.last_name = last
            cust.full_name = full
    counts["fixes"] = fixes
    if apply:
        db.session.commit()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--commission", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        res = repair(args.agency, args.commission, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] Humana mangled-name repair, agency {args.agency}:")
        print(f"  fixed:          {res['fixed']}")
        print(f"  skipped_manual: {res['skipped_manual']}")
        print(f"  no_grpname:     {res['no_grpname']}")
        for old, new in res["fixes"]:
            print(f"    '{old}'  ->  '{new}'")


if __name__ == "__main__":
    main()
