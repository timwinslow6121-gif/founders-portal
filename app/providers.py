"""
app/providers.py

Agency-shared provider directory (tribal knowledge). Senior agents + admins edit
(can_edit_shared_data); all agents view. Delete is admin-only. Drives the
plan-detail Network Snapshot panel.
"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Provider, can_edit_shared_data
from app.carriers import CARRIERS

providers_bp = Blueprint("providers", __name__)

PLAN_STATUS = ["in_network", "out_of_network"]
BILLS_OON = ["yes", "no", "unknown"]

# Category-grouped type suggestions (browse aid; free text still allowed).
TYPE_GROUPS = [
    ("Specialties", ["Family medicine", "Cardiology", "Gastroenterology", "Dermatology",
                     "OB/GYN", "Urology", "Nephrology", "Pulmonology", "ENT", "Podiatry",
                     "Oncology", "Orthopedics"]),
    ("Facilities & centers", ["Hospital", "Surgical center", "Urgent care", "Rehab center",
                              "Skilled nursing facility", "Imaging / radiology", "Lab"]),
    ("Groups & systems", ["Provider group"]),
    ("Ancillary & equipment", ["DME", "Home health", "Hospice", "Physical therapy",
                               "Behavioral / mental health", "Optometry / ophthalmology",
                               "Audiology", "Chiropractic", "Dentist"]),
]


def _can_edit():
    if not can_edit_shared_data(current_user):
        abort(403)


@providers_bp.route("/providers")
@login_required
def provider_list():
    provs = (Provider.query
             .filter_by(agency_id=current_user.agency_id)
             .order_by(Provider.county, Provider.name).all())
    # group by county for the template
    by_county = {}
    for p in provs:
        by_county.setdefault(p.county or "—", []).append(p)
    return render_template("providers_list.html",
                           by_county=by_county,
                           can_edit=can_edit_shared_data(current_user))


@providers_bp.route("/providers/new", methods=["GET", "POST"])
@login_required
def provider_new():
    _can_edit()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Provider name is required.", "error")
            return redirect(url_for("providers.provider_new"))
        p = Provider(
            agency_id=current_user.agency_id, name=name,
            provider_type=request.form.get("provider_type", "").strip() or None,
            city=request.form.get("city", "").strip() or None,
            county=request.form.get("county", "").strip() or None,
            phone=request.form.get("phone", "").strip() or None,
            notes=request.form.get("notes", "").strip() or None,
            group=request.form.get("group", "").strip() or None,
            created_by_id=current_user.id,
        )
        db.session.add(p); db.session.flush()
        p.set_carriers(request.form.getlist("carriers"))
        db.session.commit()
        flash(f"{p.name} added.", "success")
        return redirect(url_for("providers.provider_list"))
    return render_template("providers_form.html", provider=None,
                           carriers=CARRIERS, type_groups=TYPE_GROUPS,
                           selected_carriers=set())


@providers_bp.route("/providers/<int:provider_id>/edit", methods=["GET", "POST"])
@login_required
def provider_edit(provider_id):
    _can_edit()
    p = Provider.query.filter_by(id=provider_id,
                                 agency_id=current_user.agency_id).first_or_404()
    if request.method == "POST":
        p.name          = request.form.get("name", "").strip() or p.name
        p.provider_type = request.form.get("provider_type", "").strip() or None
        p.city          = request.form.get("city", "").strip() or None
        p.county        = request.form.get("county", "").strip() or None
        p.phone         = request.form.get("phone", "").strip() or None
        p.group         = request.form.get("group", "").strip() or None
        p.notes         = request.form.get("notes", "").strip() or None
        p.set_carriers(request.form.getlist("carriers"))
        db.session.commit()
        flash(f"{p.name} updated.", "success")
        return redirect(url_for("providers.provider_list"))
    from app.models import Plan
    plans = (Plan.query.filter_by(agency_id=current_user.agency_id, status="current")
             .order_by(Plan.carrier, Plan.plan_name).all())
    return render_template("providers_form.html", provider=p,
                           carriers=CARRIERS, type_groups=TYPE_GROUPS,
                           selected_carriers=set(p.carrier_names),
                           plans=plans, plans_by_id={pl.id: pl for pl in plans},
                           plan_flags=p.plan_flags,
                           plan_status=PLAN_STATUS, bills_oon=BILLS_OON)


@providers_bp.route("/providers/<int:provider_id>/plan-flag", methods=["POST"])
@login_required
def provider_add_plan_flag(provider_id):
    _can_edit()
    p = Provider.query.filter_by(id=provider_id,
                                 agency_id=current_user.agency_id).first_or_404()
    plan_id = int(request.form.get("plan_id") or 0)
    from app.models import Plan
    plan = Plan.query.filter_by(id=plan_id, agency_id=current_user.agency_id).first()
    if not plan:
        flash("Pick a plan.", "error")
        return redirect(url_for("providers.provider_edit", provider_id=provider_id))
    p.set_plan_flag(plan_id, request.form.get("status", "in_network"),
                    request.form.get("bills_oon") or "unknown", current_user.agency_id)
    db.session.commit()
    flash("Plan flag saved.", "success")
    return redirect(url_for("providers.provider_edit", provider_id=provider_id))


@providers_bp.route("/providers/<int:provider_id>/plan-flag/<int:plan_id>/delete", methods=["POST"])
@login_required
def provider_remove_plan_flag(provider_id, plan_id):
    _can_edit()
    p = Provider.query.filter_by(id=provider_id,
                                 agency_id=current_user.agency_id).first_or_404()
    p.remove_plan_flag(plan_id); db.session.commit()
    flash("Plan flag removed.", "success")
    return redirect(url_for("providers.provider_edit", provider_id=provider_id))


@providers_bp.route("/providers/<int:provider_id>/delete", methods=["POST"])
@login_required
def provider_delete(provider_id):
    if not current_user.is_admin:
        abort(403)
    p = Provider.query.filter_by(id=provider_id,
                                 agency_id=current_user.agency_id).first_or_404()
    p.set_carriers([])          # clear join rows
    db.session.delete(p); db.session.commit()
    flash("Provider deleted.", "success")
    return redirect(url_for("providers.provider_list"))
