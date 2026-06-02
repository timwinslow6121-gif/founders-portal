"""
app/carriers.py

Admin-managed plan database. Admins add/edit plans; agents view read-only.
Plans track lifecycle (current/legacy/sunset), benefits snapshot, and
commission rates per plan per year.
"""

import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models import Plan, Customer, Policy

carriers_bp = Blueprint("carriers", __name__)

PLAN_TYPES = [
    ("mapd",    "MAPD — Medicare Advantage + Part D"),
    ("pdp",     "PDP — Standalone Drug Plan"),
    ("medigap", "Medigap / Medicare Supplement"),
    ("dvh",     "Dental / Vision / Hearing"),
    ("gtl",     "GTL / Life / Hospital Indemnity"),
    ("other",   "Other"),
]

PLAN_SUBTYPES = [
    ("",        "N/A"),
    ("hmo",     "HMO"),
    ("ppo",     "PPO"),
    ("pffs",    "PFFS"),
    ("hmo_pos", "HMO-POS"),
]

STATUSES = [
    ("current",      "Current — actively marketed"),
    ("legacy",       "Legacy — available but not preferred"),
    ("sunset",       "Sunset — terminated, no new enrollments"),
    ("discontinued", "Discontinued — fully closed"),
]

COMM_TYPES = [
    ("pmpm",            "Per Member Per Month (PMPM)"),
    ("percent_premium", "Percent of Premium"),
    ("flat_annual",     "Flat Annual"),
]

CARRIERS = [
    "Aetna", "BCBS", "Devoted", "Healthspring", "Humana",
    "Medico", "UHC", "Wellable", "GTL", "Other",
]

PLAN_LETTERS = ["A", "B", "C", "D", "F", "G", "K", "L", "M", "N"]


def _parse_details(details_json_str):
    """Parse plan.details_json string into a dict. Returns {} on null/error."""
    if not details_json_str:
        return {}
    try:
        return json.loads(details_json_str)
    except (json.JSONDecodeError, TypeError):
        return {}


# Benefit field keys serialized into Plan.details_json via the admin form.
# MUST stay in sync with the form input `name=...` attributes in plan_form.html.
BENEFIT_KEYS = [
    "inpatient_hospital", "inpatient_hospital_note",
    "outpatient_surgery",
    "snf",
    "ambulance",
    "urgent_care_copay",
    "dental_allowance", "dental_note",
    "vision_allowance", "vision_note",
    "otc_allowance", "otc_note",
    "healthy_food_card",
    "transportation",
    "gym",
    "hearing", "hearing_note",
    "drug_deductible", "drug_deductible_exempt_tiers",
]


def _serialize_benefits(existing_json_str, form):
    """
    Merge structured form fields into details_json, PRESERVING any existing keys
    not in BENEFIT_KEYS (e.g., CMS sync output fields not exposed in the form).

    Returns: JSON string suitable for assigning to plan.details_json.
    """
    existing = {}
    if existing_json_str:
        try:
            existing = json.loads(existing_json_str)
        except (json.JSONDecodeError, TypeError):
            existing = {}
    for key in BENEFIT_KEYS:
        raw = form.get(key, "")
        val = raw.strip() if isinstance(raw, str) else raw
        existing[key] = val if val else None
    return json.dumps(existing)


def _base_query():
    return Plan.query.filter_by(agency_id=current_user.agency_id)


@carriers_bp.route("/carriers")
@login_required
def plan_list():
    year      = request.args.get("year", type=int) or 2026
    carrier   = request.args.get("carrier", "all")
    plan_type = request.args.get("plan_type", "all")
    status    = request.args.get("status", "current")

    q = _base_query()
    if year:
        q = q.filter_by(year=year)
    if carrier != "all":
        q = q.filter_by(carrier=carrier)
    if plan_type != "all":
        q = q.filter_by(plan_type=plan_type)
    if status != "all":
        q = q.filter_by(status=status)

    plans = q.order_by(Plan.carrier, Plan.plan_type, Plan.plan_name).all()

    # Available filter values
    years    = (db.session.query(func.distinct(Plan.year))
                .filter_by(agency_id=current_user.agency_id)
                .order_by(Plan.year.desc()).all())
    years    = [r[0] for r in years] or [2026]
    carriers = (db.session.query(func.distinct(Plan.carrier))
                .filter_by(agency_id=current_user.agency_id)
                .order_by(Plan.carrier).all())
    carriers = [r[0] for r in carriers]

    # Pre-compute member counts to prevent N+1 queries in template
    plan_ids = [p.id for p in plans]
    member_counts = {}
    if plan_ids:
        rows = (db.session.query(Policy.plan_id, func.count(Policy.id))
                .filter(
                    Policy.plan_id.in_(plan_ids),
                    Policy.status == 'active',
                    Policy.agency_id == current_user.agency_id,
                )
                .group_by(Policy.plan_id)
                .all())
        member_counts = {plan_id: count for plan_id, count in rows}

    # Pre-parse details_json for each plan (avoids JSON parsing in template)
    details_map = {p.id: _parse_details(p.details_json) for p in plans}

    return render_template("plan_list.html",
        plans=plans,
        member_counts=member_counts,
        details_map=details_map,
        years=years,
        carriers=carriers,
        plan_types=PLAN_TYPES,
        statuses=STATUSES,
        selected_year=year,
        selected_carrier=carrier,
        selected_plan_type=plan_type,
        selected_status=status,
    )


@carriers_bp.route("/carriers/<int:plan_id>")
@login_required
def plan_detail(plan_id):
    plan = _base_query().filter_by(id=plan_id).first_or_404()

    # Plans this one succeeded (predecessor chain)
    predecessors = Plan.query.filter_by(
        successor_plan_id=plan_id, agency_id=current_user.agency_id
    ).all()

    # Customers currently on this plan (matched by carrier + plan_name)
    aliases = [a.strip() for a in (plan.plan_name_aliases or "").split(",") if a.strip()]
    name_matches = [plan.plan_name] + aliases
    customers_on_plan = (
        Policy.query
        .filter(
            Policy.carrier == plan.carrier,
            Policy.plan_name.in_(name_matches),
            Policy.status == "active",
            Policy.agency_id == current_user.agency_id,
        )
        .order_by(Policy.full_name)
        .limit(200)
        .all()
    )

    # Also match by cms_plan_id if set
    if plan.cms_plan_id:
        # Some BOB files store the plan ID directly
        id_matches = (
            Policy.query
            .filter(
                Policy.carrier == plan.carrier,
                Policy.plan_name.ilike(f"%{plan.cms_plan_id}%"),
                Policy.status == "active",
                Policy.agency_id == current_user.agency_id,
                Policy.id.notin_([p.id for p in customers_on_plan]),
            )
            .limit(50).all()
        )
        customers_on_plan = customers_on_plan + id_matches

    details = _parse_details(plan.details_json)

    return render_template("plan_detail.html",
        plan=plan,
        predecessors=predecessors,
        customers_on_plan=customers_on_plan,
        plan_types=dict(PLAN_TYPES),
        statuses=dict(STATUSES),
        details=details,
    )


@carriers_bp.route("/admin/carriers/new", methods=["GET", "POST"])
@login_required
def plan_new():
    if not current_user.is_admin:
        abort(403)

    if request.method == "POST":
        cms_id = request.form.get("cms_plan_id", "").strip() or None
        plan = Plan(
            agency_id        = current_user.agency_id,
            carrier          = request.form.get("carrier", "").strip(),
            plan_name        = request.form.get("plan_name", "").strip(),
            year             = int(request.form.get("year") or 2026),
            plan_type        = request.form.get("plan_type", "mapd"),
            plan_subtype     = request.form.get("plan_subtype") or None,
            is_dsnp          = bool(request.form.get("is_dsnp")),
            is_csnp          = bool(request.form.get("is_csnp")),
            is_5star         = bool(request.form.get("is_5star")),
            star_rating      = float(request.form.get("star_rating") or 0) or None,
            cms_plan_id      = cms_id,
            plan_letter      = request.form.get("plan_letter") or None,
            external_id      = request.form.get("external_id", "").strip() or None,
            status           = request.form.get("status", "current"),
            is_commissionable= bool(request.form.get("is_commissionable")),
            auto_transitioned= bool(request.form.get("auto_transitioned")),
            successor_plan_id= int(request.form.get("successor_plan_id") or 0) or None,
            service_area     = request.form.get("service_area", "").strip() or None,
            monthly_premium  = float(request.form.get("monthly_premium") or 0) or None,
            annual_oopm      = float(request.form.get("annual_oopm") or 0) or None,
            pcp_copay        = request.form.get("pcp_copay", "").strip() or None,
            specialist_copay = request.form.get("specialist_copay", "").strip() or None,
            er_copay         = request.form.get("er_copay", "").strip() or None,
            drug_tier1       = request.form.get("drug_tier1", "").strip() or None,
            drug_tier2       = request.form.get("drug_tier2", "").strip() or None,
            drug_tier3       = request.form.get("drug_tier3", "").strip() or None,
            comm_type        = request.form.get("comm_type", "pmpm"),
            comm_initial     = float(request.form.get("comm_initial") or 0) or None,
            comm_renewal     = float(request.form.get("comm_renewal") or 0) or None,
            comm_trueup      = float(request.form.get("comm_trueup") or 0) or None,
            hra_bonus        = float(request.form.get("hra_bonus") or 0) or None,
            comm_notes       = request.form.get("comm_notes", "").strip() or None,
            plan_name_aliases= request.form.get("plan_name_aliases", "").strip() or None,
            friendly_name    = request.form.get("friendly_name", "").strip() or None,
            created_by_id    = current_user.id,
        )
        plan.sob_url    = (request.form.get("sob_url", "") or "").strip() or None
        plan.drug_tier4 = (request.form.get("drug_tier4", "") or "").strip() or None
        plan.drug_tier5 = (request.form.get("drug_tier5", "") or "").strip() or None
        plan.details_json = _serialize_benefits(plan.details_json, request.form)
        db.session.add(plan)
        db.session.commit()
        flash(f"{plan.carrier} — {plan.plan_name} ({plan.year}) added.", "success")
        return redirect(url_for("carriers.plan_detail", plan_id=plan.id))

    # Candidate successor plans for the dropdown
    existing_plans = _base_query().order_by(Plan.carrier, Plan.year.desc(), Plan.plan_name).all()
    details = {}

    return render_template("plan_form.html",
        plan=None,
        carriers=CARRIERS,
        plan_types=PLAN_TYPES,
        plan_subtypes=PLAN_SUBTYPES,
        statuses=STATUSES,
        comm_types=COMM_TYPES,
        plan_letters=PLAN_LETTERS,
        existing_plans=existing_plans,
        details=details,
    )


@carriers_bp.route("/admin/carriers/<int:plan_id>/edit", methods=["GET", "POST"])
@login_required
def plan_edit(plan_id):
    if not current_user.is_admin:
        abort(403)

    plan = _base_query().filter_by(id=plan_id).first_or_404()

    if request.method == "POST":
        plan.carrier          = request.form.get("carrier", plan.carrier)
        plan.plan_name        = request.form.get("plan_name", plan.plan_name).strip()
        plan.year             = int(request.form.get("year") or plan.year)
        plan.plan_type        = request.form.get("plan_type", plan.plan_type)
        plan.plan_subtype     = request.form.get("plan_subtype") or None
        plan.is_dsnp          = bool(request.form.get("is_dsnp"))
        plan.is_csnp          = bool(request.form.get("is_csnp"))
        plan.is_5star         = bool(request.form.get("is_5star"))
        plan.star_rating      = float(request.form.get("star_rating") or 0) or None
        plan.cms_plan_id      = request.form.get("cms_plan_id", "").strip() or None
        plan.plan_letter      = request.form.get("plan_letter") or None
        plan.external_id      = request.form.get("external_id", "").strip() or None
        plan.status           = request.form.get("status", plan.status)
        plan.is_commissionable= bool(request.form.get("is_commissionable"))
        plan.auto_transitioned= bool(request.form.get("auto_transitioned"))
        plan.successor_plan_id= int(request.form.get("successor_plan_id") or 0) or None
        plan.service_area     = request.form.get("service_area", "").strip() or None
        plan.monthly_premium  = float(request.form.get("monthly_premium") or 0) or None
        plan.annual_oopm      = float(request.form.get("annual_oopm") or 0) or None
        plan.pcp_copay        = request.form.get("pcp_copay", "").strip() or None
        plan.specialist_copay = request.form.get("specialist_copay", "").strip() or None
        plan.er_copay         = request.form.get("er_copay", "").strip() or None
        plan.drug_tier1       = request.form.get("drug_tier1", "").strip() or None
        plan.drug_tier2       = request.form.get("drug_tier2", "").strip() or None
        plan.drug_tier3       = request.form.get("drug_tier3", "").strip() or None
        plan.comm_type        = request.form.get("comm_type", plan.comm_type)
        plan.comm_initial     = float(request.form.get("comm_initial") or 0) or None
        plan.comm_renewal     = float(request.form.get("comm_renewal") or 0) or None
        plan.comm_trueup      = float(request.form.get("comm_trueup") or 0) or None
        plan.hra_bonus        = float(request.form.get("hra_bonus") or 0) or None
        plan.comm_notes       = request.form.get("comm_notes", "").strip() or None
        plan.plan_name_aliases= request.form.get("plan_name_aliases", "").strip() or None
        plan.friendly_name    = request.form.get("friendly_name", "").strip() or None
        plan.sob_url    = (request.form.get("sob_url", "") or "").strip() or None
        plan.drug_tier4 = (request.form.get("drug_tier4", "") or "").strip() or None
        plan.drug_tier5 = (request.form.get("drug_tier5", "") or "").strip() or None
        plan.details_json = _serialize_benefits(plan.details_json, request.form)
        db.session.commit()
        flash(f"{plan.plan_name} updated.", "success")
        return redirect(url_for("carriers.plan_detail", plan_id=plan.id))

    existing_plans = (_base_query()
                      .filter(Plan.id != plan_id)
                      .order_by(Plan.carrier, Plan.year.desc(), Plan.plan_name).all())
    details = _parse_details(plan.details_json)

    return render_template("plan_form.html",
        plan=plan,
        carriers=CARRIERS,
        plan_types=PLAN_TYPES,
        plan_subtypes=PLAN_SUBTYPES,
        statuses=STATUSES,
        comm_types=COMM_TYPES,
        plan_letters=PLAN_LETTERS,
        existing_plans=existing_plans,
        details=details,
    )
