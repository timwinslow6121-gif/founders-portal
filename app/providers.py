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

BILLS_PPO_OON = ["yes", "no", "unknown"]
# Suggested specialties for the datalist (free text — not enforced).
TYPE_SUGGESTIONS = ["Family medicine", "Gastroenterology", "Cardiology",
                    "Dentist", "Orthopedics", "Dermatology", "Oncology",
                    "OB/GYN", "Pulmonology", "Nephrology", "Urology"]


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
            created_by_id=current_user.id,
        )
        db.session.add(p); db.session.flush()
        p.set_carriers(request.form.getlist("carriers"))
        db.session.commit()
        flash(f"{p.name} added.", "success")
        return redirect(url_for("providers.provider_list"))
    return render_template("providers_form.html", provider=None,
                           carriers=CARRIERS, bills_opts=BILLS_PPO_OON,
                           type_suggestions=TYPE_SUGGESTIONS, selected_carriers=set())


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
        p.bills_ppo_oon = request.form.get("bills_ppo_oon") or "unknown"
        p.notes         = request.form.get("notes", "").strip() or None
        p.set_carriers(request.form.getlist("carriers"))
        db.session.commit()
        flash(f"{p.name} updated.", "success")
        return redirect(url_for("providers.provider_list"))
    return render_template("providers_form.html", provider=p,
                           carriers=CARRIERS, bills_opts=BILLS_PPO_OON,
                           type_suggestions=TYPE_SUGGESTIONS,
                           selected_carriers=set(p.carrier_names))


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
