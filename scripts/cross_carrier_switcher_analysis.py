"""READ-ONLY cross-carrier switcher analysis. Writes NOTHING.

For every DB-active policy that is NOT in its OWN carrier's current BOB (a
"held / stale-active" row), check whether that person has a NEWER active
enrollment in a DIFFERENT carrier's BOB (= they SWITCHED). True current carrier
= newest effective date across ALL carriers we have books for.

Match keys (per Tim's rules):
  - MBI       — works for UHC/Aetna/Devoted/HealthSpring (their BOBs carry it).
  - name+dob  — the universal key; REQUIRED for Humana (its BOB masks the MBI),
                and used as corroboration everywhere. (Address shown for the
                human to confirm; never match on dob alone.)

Carriers with BOBs: UHC, Humana, Aetna, Devoted, HealthSpring.
NOT covered (no BOB yet): BCBS, Wellabe, GTL — a person who switched TO one of
those cannot be detected here; those rows stay "unresolved / possible-OOB".

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/cross_carrier_switcher_analysis.py
"""
import os
from collections import defaultdict
from datetime import date
import pandas as pd
from app import create_app
from app.extensions import db
from app.models import Policy, Customer
from app.upload import _detect_carrier, _dedupe_bob_records
from app.parsers import parse_carrier_file

BOBS = {
    "UHC": "docs/Carrier BOB DL/July 2026 period/UHC/UHC book of business.xlsx",
    "Humana": "docs/Carrier BOB DL/July 2026 period/Humana/Humana Book of business.xlsx",
    "Aetna": "docs/Carrier BOB DL/July 2026 period/Aetna/Aetna Book of Business.xlsx",
    "Devoted": "docs/Carrier BOB DL/July 2026 period/Devoted/Devoted Book of business.xlsx",
    "HealthSpring": "docs/Carrier BOB DL/July 2026 period/HealthSpring/Healthspring Book of Business.xlsx",
}
CARRIERS_WITH_BOB = set(BOBS)  # note: DB stores "Healthspring"; normalize below


def _norm_carrier(c):
    return (c or "").strip().lower()


def _nk(name):
    return " ".join((name or "").strip().lower().split())


def _eff(r):
    e = r.get("effective_date")
    return e if isinstance(e, date) else date.min


def _last6(mbi):
    """Last 6 of an MBI — the cross-carrier bridge to Humana (whose BOB masks the
    MBI as XXXXX + last 6). Returns '' if too short."""
    m = (mbi or "").strip().upper()
    return m[-6:] if len(m) >= 6 else ""


def _humana_last6_index(path):
    """Read the Humana BOB directly and index ACTIVE rows by (name+dob) -> last6 of
    the masked 'Medicare No'. The normal parser drops the masked value; here we keep
    the last-6 as a bridge key. Returns dict[(nk_name, dob)] = set(last6)."""
    idx = defaultdict(set)
    tail_to_names = defaultdict(set)   # last6 -> set of (nk_name, dob) for reverse lookup
    df = pd.read_excel(path, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    for _, r in df.iterrows():
        status = str(r.get("Status") or "").strip().lower()
        # Humana active = not termed/inactive; be permissive, the DB side gates too.
        if status and status not in ("active", "enrolled", "a"):
            # only skip clearly-inactive; keep unknown/blank
            if status in ("inactive", "termed", "disenrolled", "t"):
                continue
        med = str(r.get("Medicare No") or "").strip().upper()
        t = med[-6:] if med.startswith("XXXXX") and len(med) == 11 else ""
        if not t:
            continue
        first = str(r.get("MbrFirstName") or "").strip()
        last = str(r.get("MbrLastName") or "").strip()
        nm = _nk("%s %s" % (first, last))
        dobraw = r.get("Birth Date")
        dob = None
        if pd.notna(dobraw) and str(dobraw).strip():
            try:
                dob = pd.to_datetime(dobraw).date()
            except Exception:
                dob = None
        if nm and dob:
            idx[(nm, dob)].add(t)
            tail_to_names[t].add((nm, dob))
    return idx, tail_to_names


def main():
    app = create_app()
    with app.app_context():
        # --- 1. Parse every BOB; index active rows by MBI and by name+dob ---
        bob_by_mbi = {}                     # mbi -> list of (carrier, rec)
        bob_by_namedob = defaultdict(list)  # (nk(name), dob) -> list of (carrier, rec)
        bob_active_keys = defaultdict(set)  # carrier(lower) -> set of mbis present (for "in own BOB?")
        bob_active_namedob = defaultdict(set)  # carrier(lower) -> set of (nk,dob)

        # Humana masked-MBI bridge: (name,dob) -> set(last6), built by reading the
        # Humana BOB directly (the parser drops the masked value).
        humana_last6 = {}
        if os.path.exists(BOBS["Humana"]):
            humana_last6, _ = _humana_last6_index(BOBS["Humana"])
        for want, path in BOBS.items():
            if not os.path.exists(path):
                print("  (missing BOB: %s)" % want); continue
            det = _detect_carrier(path, os.path.basename(path))
            recs = _dedupe_bob_records(parse_carrier_file(det, path))
            cl = _norm_carrier(det)
            for r in recs:
                if r.get("status") != "active":
                    continue
                mbi = (r.get("mbi") or "").upper()
                nm = _nk(r.get("full_name") or ("%s %s" % (r.get("first_name") or "", r.get("last_name") or "")))
                dob = r.get("dob")
                r = dict(r); r["_carrier"] = det
                if mbi:
                    bob_by_mbi.setdefault(mbi, []).append((det, r))
                    bob_active_keys[cl].add(mbi)
                if nm and dob:
                    bob_by_namedob[(nm, dob)].append((det, r))
                    bob_active_namedob[cl].add((nm, dob))

        # --- 2. DB active policies for the 5 carriers; find held rows ---
        results = defaultdict(list)   # category -> rows
        for carrier in ["UHC", "Humana", "Aetna", "Devoted", "Healthspring"]:
            cl = _norm_carrier(carrier)
            pols = Policy.query.filter_by(carrier=carrier, status="active").all()
            for p in pols:
                c = db.session.get(Customer, p.customer_id) if p.customer_id else None
                if not c:
                    results["no_customer"].append((carrier, p, None, None)); continue
                mbi = (c.mbi or "").upper()
                nm = _nk(c.full_name)
                dob = c.dob
                # is this person in their OWN carrier's current BOB?
                in_own = ((mbi and mbi in bob_active_keys[cl]) or
                          (nm and dob and (nm, dob) in bob_active_namedob[cl]))
                if in_own:
                    continue   # not held — present in own book, fine
                # HELD. Look for a NEWER active enrollment in a DIFFERENT carrier.
                cands = []
                if mbi:
                    cands += [(oc, r) for (oc, r) in bob_by_mbi.get(mbi, []) if _norm_carrier(oc) != cl]
                if nm and dob:
                    cands += [(oc, r) for (oc, r) in bob_by_namedob.get((nm, dob), []) if _norm_carrier(oc) != cl]
                # dedupe candidates
                seen = set(); uniq = []
                for oc, r in cands:
                    k = (_norm_carrier(oc), r.get("mbi"), r.get("effective_date"))
                    if k not in seen:
                        seen.add(k); uniq.append((oc, r))
                if uniq:
                    # newest eff across candidates
                    best = max(uniq, key=lambda t: _eff(t[1]))
                    p_eff = p.effective_date or date.min
                    if _eff(best[1]) >= p_eff:
                        results["switcher"].append((carrier, p, c, best))
                    else:
                        results["elsewhere_but_older"].append((carrier, p, c, best))
                    continue

                # No full-MBI/name+dob candidate in the other books. For NON-Humana
                # held rows, try the Humana last-6 bridge: same name+dob AND the held
                # row's full-MBI last-6 present in Humana's masked BOB = switched to
                # Humana. (Never last-6 alone — require name+dob too.)
                if cl != "humana" and nm and dob and mbi:
                    t6 = _last6(mbi)
                    if t6 and t6 in humana_last6.get((nm, dob), set()):
                        results["switcher_to_humana_last6"].append((carrier, p, c, ("Humana(last6=%s)" % t6, {})))
                        continue

                # not in own BOB, not found anywhere
                if p.term_date:
                    results["held_has_termdate"].append((carrier, p, c, None))
                else:
                    results["unresolved_no_match"].append((carrier, p, c, None))

        # --- 3. Report ---
        print("\n" + "=" * 72)
        print("CROSS-CARRIER SWITCHER ANALYSIS (read-only; 5 carriers with BOBs)")
        print("=" * 72)
        for cat in ["switcher", "switcher_to_humana_last6", "elsewhere_but_older",
                    "held_has_termdate", "unresolved_no_match", "no_customer"]:
            rows = results.get(cat, [])
            print("\n### %s: %d" % (cat.upper(), len(rows)))
            for item in rows[:60]:
                carrier, p, c, best = item
                nm = (c.full_name if c else "?")
                if best:
                    oc, r = best
                    print("   %-11s pol %-6s %-24s dob=%s | -> %s eff=%s plan=%r (was %s eff=%s)"
                          % (carrier, p.id, nm, (c.dob if c else "?"), oc,
                             r.get("effective_date"), r.get("plan_name"),
                             carrier, p.effective_date))
                else:
                    print("   %-11s pol %-6s %-24s dob=%s mbi=%s eff=%s term=%s"
                          % (carrier, p.id, nm, (c.dob if c else "?"),
                             (c.mbi if c else "?"), p.effective_date, p.term_date))
            if len(rows) > 60:
                print("   ... +%d more" % (len(rows) - 60))
        print("\n(SWITCHER = held in own BOB + a NEWER active enrollment in another of the 5.")
        print(" UNRESOLVED_NO_MATCH = not in own BOB + not found in the other 4 -> could be a")
        print(" switch to BCBS/Wellabe/GTL [no BOB yet] or a stale term. Leave held.)")


if __name__ == "__main__":
    main()
