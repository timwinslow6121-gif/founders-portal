"""One-time cleanup: collapse legacy Humana commission stubs into their real
customer, using the carrier_id_crosswalk built by seed_humana_crosswalk.py. A stub
is merged ONLY when the crosswalk corroborates it maps to a DIFFERENT real
(stub=False) customer — lonely stubs are never touched. Uses the existing audited
merge_customers (fill-blanks-only, reattaches all children, refuses contradictions).

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/cleanup_humana_stubs.py \
      --agency 1 [--apply]
Dry-run by default.
"""
import argparse

from app import create_app
from app.extensions import db
from app.models import Customer, CarrierIdCrosswalk, Policy, User


def plan_cleanup(agency_id):
    """Return [{stub_id, keeper_id, grpnbr}] safe merges. A legacy Humana stub is
    paired to a keeper when the stub's MBI (stored in humana_id by the old importer)
    matches a Humana crosswalk row whose customer is a DIFFERENT real (stub=False)
    customer. Only corroborated pairs are returned; lonely stubs are never listed."""
    # map: MBI -> (real customer_id, GrpNbr) from crosswalk rows pointing at real customers
    real_by_mbi = {}
    for row in CarrierIdCrosswalk.query.filter_by(agency_id=agency_id, carrier="Humana"):
        if not (row.mbi or "").strip():
            continue
        cust = Customer.query.get(row.customer_id)
        if cust is not None and not cust.stub:
            real_by_mbi[row.mbi.strip()] = (cust.id, row.carrier_key)
    pairs = []
    stubs = Customer.query.filter_by(agency_id=agency_id, stub=True,
                                     source="commission_import").all()
    for stub in stubs:
        mbi = (stub.humana_id or stub.mbi or "").strip()
        if not mbi:
            continue
        hit = real_by_mbi.get(mbi)
        if hit and hit[0] != stub.id:
            pairs.append({"stub_id": stub.id, "keeper_id": hit[0], "grpnbr": hit[1],
                          "tier": "mbi"})
    return pairs


def _norm_name(c):
    return (c.full_name or "").strip().lower()


def plan_cleanup_by_name_eff(agency_id, carrier="Humana"):
    """Second tier: pair a legacy stub to a real customer by NAME + policy EFFECTIVE
    DATE, but ONLY when it is safe — proven against the whole book that no two
    DIFFERENT real people share a name + non-Jan-1 effective date:

      1. the stub's <carrier>-policy effective date is NOT Jan 1 (the AEP mass-date,
         where thousands of plans share Jan 1 — a weak, coincidence-prone match);
      2. that (normalized name, eff-date) matches EXACTLY ONE real (stub=False)
         <carrier> customer;
      3. the name is not shared by 3+ customers total (the two-David-Whites guard).

    Carrier-parameterized so it can whittle any carrier's stubs once their BOB
    customers exist (VERIFY 0 true name+non-Jan1-eff collisions for that carrier
    first — proven for Humana + Devoted; UHC had 1, so it is NOT safe as-is).
    Read-only: returns [{stub_id, keeper_id, eff, tier:'name_eff'}]. Lonely /
    Jan-1 / ambiguous / shared-name stubs are never listed."""
    from collections import defaultdict

    # Index every <carrier> customer's (normalized name, eff-date) -> set of customer
    # ids, split by stub vs real, plus a whole-book name-count for the shared-name guard.
    real_by_key = defaultdict(set)   # (name, eff) -> {real customer ids}
    name_count = defaultdict(int)    # normalized name -> total customers with it
    stub_effs = {}                   # stub id -> (name, eff)

    seen_names = set()
    q = (db.session.query(Customer, Policy.effective_date)
         .join(Policy, Policy.customer_id == Customer.id)
         .filter(Customer.agency_id == agency_id,
                 Policy.carrier.ilike(f"{carrier}%"),
                 Policy.effective_date.isnot(None)))
    for cust, eff in q.all():
        nm = _norm_name(cust)
        if not nm or eff is None:
            continue
        key = (nm, eff)
        if not cust.stub:
            real_by_key[key].add(cust.id)
        elif cust.source == "commission_import":
            stub_effs[cust.id] = key
        # count distinct customer ids per name once
        if (cust.id, nm) not in seen_names:
            seen_names.add((cust.id, nm))
            name_count[nm] += 1

    pairs = []
    for stub_id, (nm, eff) in stub_effs.items():
        if eff.month == 1 and eff.day == 1:
            continue                       # Jan-1 AEP mass-date — too weak
        if name_count.get(nm, 0) > 2:
            continue                       # name shared by 3+ — David-White guard
        reals = real_by_key.get((nm, eff), set())
        if len(reals) != 1:
            continue                       # 0 = commission-only island; >1 = ambiguous
        keeper_id = next(iter(reals))
        if keeper_id != stub_id:
            pairs.append({"stub_id": stub_id, "keeper_id": keeper_id,
                          "eff": eff.isoformat(), "tier": "name_eff"})
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--tier", choices=["mbi", "name_eff", "both"], default="mbi",
                    help="mbi = crosswalk-MBI corroborated (default); "
                         "name_eff = name + non-Jan-1 eff-date unique match; both = union")
    ap.add_argument("--carrier", default="Humana",
                    help="carrier for the name_eff tier (default Humana). "
                         "VERIFY 0 name+non-Jan1-eff collisions for that carrier first.")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        from app.customers import merge_customers
        actor = User.query.filter_by(agency_id=args.agency).first()

        pairs = []
        if args.tier in ("mbi", "both"):
            pairs += plan_cleanup(args.agency)
        if args.tier in ("name_eff", "both"):
            pairs += plan_cleanup_by_name_eff(args.agency, carrier=args.carrier)
        # de-dup by stub_id (a stub could qualify under both tiers) — keep first (mbi wins)
        seen, deduped = set(), []
        for p in pairs:
            if p["stub_id"] in seen:
                continue
            seen.add(p["stub_id"])
            deduped.append(p)
        pairs = deduped

        print(f"{'APPLY' if args.apply else 'DRY-RUN'} [tier={args.tier}]: "
              f"{len(pairs)} stub→real merges")
        for p in pairs:
            tag = p.get("grpnbr") or p.get("eff") or ""
            print(f"  stub {p['stub_id']} → keeper {p['keeper_id']} "
                  f"[{p.get('tier','?')} {tag}]")
            if args.apply:
                merge_customers(p["keeper_id"], [p["stub_id"]], args.agency, actor)
        if args.apply:
            db.session.commit()


if __name__ == "__main__":
    main()
