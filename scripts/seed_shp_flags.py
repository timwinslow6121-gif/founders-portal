"""
Set PipelineState.shp_flag from the Cannon Pharmacy NC State Health Plan list.

NC State Health Plan Medicare retirees on the 70/30 plan must call the State
themselves during ITS open enrollment (Oct 12-30 for 2027) to opt out of the
Humana group PPO. Inaction enrolls them automatically. That deadline closes five
weeks before Medicare AEP ends, which is why the pipeline treats an unconfirmed
retiree as Tier 1.

MATCHING -- exact MBI, corroborated, never fuzzy:

  1. MBI must resolve to exactly ONE portal customer. 0 or 2+ -> refused.
  2. DOB must agree where both sides have one. A disagreement -> refused
     outright: same MBI + different DOB means one of the two records is wrong,
     and this script must not decide which.
  3. Surname must agree. First name must agree OR be a known short form
     (Phillip/Phil). Anything else -> refused to the review list.

Name-only matching is deliberately NOT a fallback. It produced the documented
COUCHELL -> Andrea Horstmann mis-link in this codebase. A wrong shp_flag puts a
customer in Tier 1 under a deadline that is not theirs and implies their
retiree status was verified when it was not.

SCOPE, stated honestly: this list is Cannon Pharmacy Main's patients only, so it
finds mostly Brian's book and almost nobody else's. It is a floor, not a census.

Usage:
  ./venv/bin/python3 scripts/seed_shp_flags.py            # dry run
  ./venv/bin/python3 scripts/seed_shp_flags.py --apply
"""
import sys, os, re, argparse, unicodedata, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
from app.extensions import db
from app.models import Customer, PipelineState

DEFAULT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "Medicare 2027 Plan Info", "SHP Retirees",
    "State Health Plan 70-30 & 80-20 to ensure accuracy.xlsx")

# Short forms seen in this data. Deliberately tiny and explicit -- a broad
# nickname table invites the false positives exact-ID matching exists to avoid.
SHORT_FORMS = {("phillip", "phil"), ("phil", "phillip")}


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Za-z ]", " ", s).lower().split())


def _file_name_parts(raw):
    """'Faggart, Phillip' -> ('phillip', 'faggart')."""
    raw = str(raw or "").strip()
    if "," in raw:
        last, first = raw.split(",", 1)
        fp, lp = _norm(first).split(), _norm(last).split()
        return (fp[0] if fp else ""), (lp[0] if lp else "")
    p = _norm(raw).split()
    return (p[0], p[-1]) if len(p) >= 2 else (_norm(raw), "")


def _first_agrees(a, b):
    return a == b or (a, b) in SHORT_FORMS


def run(apply=False, agency_id=1, path=None):
    path = path or DEFAULT_FILE
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)["Sheet1"]
    rows = [r for r in list(ws.iter_rows(values_only=True))[1:] if r and r[0]]

    by_mbi = {}
    for c in Customer.query.filter(Customer.agency_id == agency_id,
                                   Customer.mbi.isnot(None)).all():
        by_mbi.setdefault(str(c.mbi).strip().upper(), []).append(c)

    setting, already, refused = [], [], []
    no_mbi = not_in_portal = 0

    for r in rows:
        name, dob_cell, plan, mbi_cell = r[0], r[1], r[2], r[7]
        if not mbi_cell or not str(mbi_cell).strip():
            no_mbi += 1
            continue
        mbi = str(mbi_cell).strip().upper()
        cands = by_mbi.get(mbi, [])
        if not cands:
            not_in_portal += 1
            continue
        if len(cands) > 1:
            refused.append((name, "MBI matches %d customers" % len(cands)))
            continue

        c = cands[0]
        fdob = dob_cell.date() if hasattr(dob_cell, "date") else None
        if c.dob and fdob and c.dob != fdob:
            refused.append((name, "DOB disagrees (portal %s vs file %s)" % (c.dob, fdob)))
            continue

        ffirst, flast = _file_name_parts(name)
        cf, cl = _norm(c.first_name).split(), _norm(c.last_name).split()
        if not (cf and cl) or cl[0] != flast or not _first_agrees(ffirst, cf[0]):
            refused.append((name, "name disagrees with portal %r" % c.full_name))
            continue

        state = PipelineState.query.filter_by(customer_id=c.id).first()
        if state is None:
            refused.append((name, "no pipeline_state row"))
            continue
        if state.shp_flag:
            already.append((name, c.full_name))
            continue
        setting.append((name, c, state, plan))

    print("%s -- shp_flag from the Cannon SHP list (agency %d)\n"
          % ("APPLY" if apply else "DRY RUN", agency_id))
    print("  file rows                     : %d" % len(rows))
    print("  no MBI in the file            : %d  (not Medicare / not on file)" % no_mbi)
    print("  MBI not in the portal         : %d" % not_in_portal)
    print("  already flagged               : %d" % len(already))
    print("  WILL SET shp_flag             : %d" % len(setting))
    print("  refused                       : %d" % len(refused))
    if setting:
        print("\n  by plan: %s" % dict(collections.Counter(s[3] for s in setting)))
        print("\n  setting:")
        for nm, c, _, plan in setting[:40]:
            print("     %-26s -> %-24s %-12s %s"
                  % (nm, c.full_name, c.county or "-", plan))
        if len(setting) > 40:
            print("     ... and %d more" % (len(setting) - 40))
    if refused:
        print("\n  REFUSED -- needs a human:")
        for nm, why in refused:
            print("     %-26s %s" % (nm, why))

    if apply:
        for _, _, state, _ in setting:
            state.shp_flag = True
        db.session.commit()
        print("\n  Applied: %d flagged." % len(setting))
    else:
        print("\n  Nothing was written. Re-run with --apply.")
    return {"set": len(setting), "refused": len(refused), "already": len(already)}


if __name__ == "__main__":
    from app import create_app
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--agency", type=int, default=1)
    ap.add_argument("--file", default=None)
    args = ap.parse_args()
    with create_app().app_context():
        run(apply=args.apply, agency_id=args.agency, path=args.file)
