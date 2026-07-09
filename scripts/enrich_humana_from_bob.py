"""Enrich Humana customers from the FULL Humana BOB (the AJ export with all 85 cols +
inactive rows), matched by Humana ID. Three jobs, all safe:

  1. FILL-BLANKS-ONLY on the customer: dob, gender, phone_primary/secondary, address1,
     city, state, zip_code, county — only where the customer's field is currently blank
     and the customer is NOT manually_edited. Never overwrites a non-blank value.
  2. AUTO-TERM: if the BOB row has an 'Inactive Date' and the customer's Humana policy is
     still active, term it (status='termed', term_date=inactive date). The full BOB
     includes inactive rows the active-only parser drops — this is the term signal.
  3. FIX MBI COLUMN: if the customer's humana_id holds an 11-char MBI-format value (not a
     H-prefixed Humana ID) and .mbi is blank, copy it into .mbi (leave humana_id).

The BOB's Medicare No is MASKED (XXXXX+last6) so the real MBI can't be filled from it.
Match key = Humana ID (customers.humana_id, when it's a real H-prefixed ID) — the reliable
1:1 key. Read-only unless --apply. DB backup + dry-run review first.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/enrich_humana_from_bob.py \
      --agency 1 --bob "docs/Carrier BOB DL/July 2026 period/Humana/Humana Book of business.xlsx" [--apply]
"""
import argparse
import datetime

import openpyxl

from app import create_app
from app.extensions import db
from app.models import Customer, Policy

# customer attr -> BOB column header
_FILL = {
    "dob": "Birth Date",
    "gender": "Gender",
    "phone_primary": "Primary Phone",
    "phone_secondary": "Secondary Phone",
    "address1": "Resident Address",
    "city": "Resident City",
    "state": "Resident State",
    "zip_code": "Resident Zip Code",
    "county": "Resident County",
}


def _is_mbi(v):
    v = (v or "").strip().upper()
    return len(v) == 11 and v[0].isdigit() and v.isalnum()


def _to_date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    if not v:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            pass
    return None


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _bob_by_humana_id(path):
    """Humana ID (upper) -> dict of the BOB fields we use. Later active row wins for
    fill data; inactive date captured from whichever row carries it."""
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    hdr = list(next(it))
    idx = {h: i for i, h in enumerate(hdr)}

    def g(row, name):
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else None

    out = {}
    for row in it:
        if not row:
            continue
        hid = str(g(row, "Humana ID") or "").strip().upper()
        if not hid:
            continue
        rec = out.setdefault(hid, {"inactive": None, "fields": {}})
        inact = _to_date(g(row, "Inactive Date"))
        # keep the LATEST inactive date (a plan-change row may term earlier)
        if inact and (rec["inactive"] is None or inact > rec["inactive"]):
            rec["inactive"] = inact
        # an ACTIVE row (no inactive date) is the best source of current contact fields
        prefer = inact is None or not rec["fields"]
        if prefer:
            rec["fields"] = {attr: g(row, col) for attr, col in _FILL.items()}
    wb.close()
    return out


def enrich(agency_id, bob_path, apply=False):
    bob = _bob_by_humana_id(bob_path)
    counts = {"filled_fields": 0, "customers_filled": 0, "termed": 0, "mbi_moved": 0,
              "no_bob_match": 0}
    fill_detail = {}
    custs = (Customer.query
             .join(Policy, Policy.customer_id == Customer.id)
             .filter(Customer.agency_id == agency_id, Policy.carrier == "Humana")
             .distinct().all())
    for c in custs:
        hid = (c.humana_id or "").strip().upper()

        # (3) MBI-in-wrong-column fix
        if _is_mbi(c.humana_id) and _blank(c.mbi):
            counts["mbi_moved"] += 1
            if apply:
                c.mbi = c.humana_id.strip().upper()

        rec = bob.get(hid) if hid.startswith("H") else None
        if rec is None:
            counts["no_bob_match"] += 1
            continue

        # (1) fill-blanks (skip manually_edited)
        if not c.manually_edited:
            filled_here = 0
            for attr, val in rec["fields"].items():
                if not _blank(getattr(c, attr, None)):
                    continue
                nv = _to_date(val) if attr == "dob" else (str(val).strip() if val not in (None, "Unavailable") else None)
                if _blank(nv):
                    continue
                counts["filled_fields"] += 1
                filled_here += 1
                fill_detail[attr] = fill_detail.get(attr, 0) + 1
                if apply:
                    setattr(c, attr, nv)
            if filled_here:
                counts["customers_filled"] += 1

        # (2) auto-term the Humana policy if the BOB says inactive
        if rec["inactive"]:
            pol = Policy.query.filter_by(agency_id=agency_id, carrier="Humana",
                                         customer_id=c.id, status="active").first()
            if pol:
                counts["termed"] += 1
                if apply:
                    pol.status = "termed"
                    pol.term_date = rec["inactive"]
                    pol.term_reason = pol.term_reason or "Humana BOB inactive"

    counts["fill_by_field"] = fill_detail
    if apply:
        db.session.commit()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--bob", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        res = enrich(args.agency, args.bob, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] Humana BOB enrichment, agency {args.agency}:")
        print(f"  customers with fields filled: {res['customers_filled']}")
        print(f"  total fields filled:          {res['filled_fields']}")
        for f, n in sorted(res["fill_by_field"].items(), key=lambda x: -x[1]):
            print(f"      {f}: {n}")
        print(f"  policies auto-termed (BOB inactive): {res['termed']}")
        print(f"  MBI moved humana_id->mbi:            {res['mbi_moved']}")
        print(f"  customers not in BOB:                {res['no_bob_match']}")


if __name__ == "__main__":
    main()
