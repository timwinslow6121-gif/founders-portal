"""Sort a BOB plan row into an EXISTING Plan bucket. NEVER creates a bucket — a miss
returns plan_id=None so the caller can park + queue it for human review. This is the
jelly-bean sorter: match a bean to a bucket that already exists."""
from typing import Optional
from app.extensions import db
from app.models import Plan
from app.plan_codes import (classify_plan, extract_contract_code, cms_plan_id_of,
                            medigap_letter, PERPETUAL)


def _alias_hit(carrier, plan_name, year, agency_id):
    """Match by the reviewed plan_name / plan_name_aliases on existing buckets."""
    nm = (plan_name or "").strip().lower()
    if not nm:
        return None
    with db.session.no_autoflush:
        for p in Plan.query.filter_by(agency_id=agency_id, carrier=carrier).all():
            if p.plan_name and p.plan_name.strip().lower() == nm:
                return p
            if p.plan_name_aliases:
                for a in p.plan_name_aliases.split(","):
                    if a.strip().lower() == nm:
                        return p
    return None


def find_plan_bucket(carrier, rec, plan_year, agency_id) -> dict:
    carrier = (carrier or "").strip()
    plan_name = rec.get("plan_name") or ""
    kind = classify_plan(rec.get("plan_type") or "", plan_name)
    out = {"plan_id": None, "contract_code": None, "plan_year": plan_year,
           "matched_by": None}
    if kind == "year_bound":
        code = extract_contract_code(carrier, rec)
        out["contract_code"] = code
        cms_id = cms_plan_id_of(code) if code else None
        if cms_id:
            with db.session.no_autoflush:
                p = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                         cms_plan_id=cms_id, year=plan_year).first()
            if p:
                out.update(plan_id=p.id, matched_by="code")
                return out
        # no code, or code has no seeded bucket → try the reviewed alias
        p = _alias_hit(carrier, plan_name, plan_year, agency_id)
        if p:
            out.update(plan_id=p.id, matched_by="alias")
        return out
    if kind == "medigap":
        out["plan_year"] = PERPETUAL
        letter = medigap_letter(plan_name)
        if letter:
            with db.session.no_autoflush:
                p = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                         plan_letter=letter, year=PERPETUAL).first()
            if p:
                out.update(plan_id=p.id, matched_by="letter")
        return out
    # named (DVH/dental/GTL/hospital-indemnity)
    out["plan_year"] = PERPETUAL
    p = _alias_hit(carrier, plan_name, PERPETUAL, agency_id)
    if p and p.year == PERPETUAL:
        out.update(plan_id=p.id, matched_by="name")
    return out
