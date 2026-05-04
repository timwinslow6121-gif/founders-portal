"""
app/carriers.py

Admin-managed plan database. Admins add/edit plans; agents view read-only.
Plans track lifecycle (current/legacy/sunset), benefits snapshot, and
commission rates per plan per year.
"""

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

    return render_template("plan_list.html",
        plans=plans,
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

    return render_template("plan_detail.html",
        plan=plan,
        predecessors=predecessors,
        customers_on_plan=customers_on_plan,
        plan_types=dict(PLAN_TYPES),
        statuses=dict(STATUSES),
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
            created_by_id    = current_user.id,
        )
        db.session.add(plan)
        db.session.commit()
        flash(f"{plan.carrier} — {plan.plan_name} ({plan.year}) added.", "success")
        return redirect(url_for("carriers.plan_detail", plan_id=plan.id))

    # Candidate successor plans for the dropdown
    existing_plans = _base_query().order_by(Plan.carrier, Plan.year.desc(), Plan.plan_name).all()

    return render_template("plan_form.html",
        plan=None,
        carriers=CARRIERS,
        plan_types=PLAN_TYPES,
        plan_subtypes=PLAN_SUBTYPES,
        statuses=STATUSES,
        comm_types=COMM_TYPES,
        plan_letters=PLAN_LETTERS,
        existing_plans=existing_plans,
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
        db.session.commit()
        flash(f"{plan.plan_name} updated.", "success")
        return redirect(url_for("carriers.plan_detail", plan_id=plan.id))

    existing_plans = (_base_query()
                      .filter(Plan.id != plan_id)
                      .order_by(Plan.carrier, Plan.year.desc(), Plan.plan_name).all())

    return render_template("plan_form.html",
        plan=plan,
        carriers=CARRIERS,
        plan_types=PLAN_TYPES,
        plan_subtypes=PLAN_SUBTYPES,
        statuses=STATUSES,
        comm_types=COMM_TYPES,
        plan_letters=PLAN_LETTERS,
        existing_plans=existing_plans,
    )
