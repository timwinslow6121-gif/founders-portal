"""
app/pharmacies.py

Admin-only blueprint for managing partner pharmacies.
Pharmacies refer customers to Founders agents; Founders pays rent in return.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models import Pharmacy, Customer, Policy, User

pharmacies_bp = Blueprint("pharmacies", __name__)


def _admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)
    return decorated


def _pharmacy_stats(pharmacy_id, agency_id):
    """
    Return per-agent customer counts and carrier/plan breakdown for one pharmacy.
    All queries scoped to agency_id.
    """
    # Per-agent customer counts
    agent_rows = (
        db.session.query(User.id, User.name, func.count(Customer.id).label("count"))
        .join(Customer, Customer.primary_agent_id == User.id)
        .filter(Customer.pharmacy_id == pharmacy_id, Customer.agency_id == agency_id)
        .group_by(User.id, User.name)
        .order_by(func.count(Customer.id).desc())
        .all()
    )

    total = sum(r.count for r in agent_rows)

    # Per-carrier breakdown (via Policy, joining on MBI)
    carrier_rows = (
        db.session.query(Policy.carrier, func.count(Policy.id).label("count"))
        .join(Customer, Customer.mbi == Policy.mbi)
        .filter(
            Customer.pharmacy_id == pharmacy_id,
            Customer.agency_id == agency_id,
            Policy.agency_id == agency_id,
            Policy.status == "active",
        )
        .group_by(Policy.carrier)
        .order_by(func.count(Policy.id).desc())
        .all()
    )

    # Per-agent × carrier breakdown
    agent_carrier_rows = (
        db.session.query(
            User.id.label("agent_id"),
            User.name.label("agent_name"),
            Policy.carrier,
            func.count(Policy.id).label("count"),
        )
        .join(Customer, Customer.primary_agent_id == User.id)
        .join(Policy, Policy.mbi == Customer.mbi)
        .filter(
            Customer.pharmacy_id == pharmacy_id,
            Customer.agency_id == agency_id,
            Policy.agency_id == agency_id,
            Policy.status == "active",
        )
        .group_by(User.id, User.name, Policy.carrier)
        .order_by(User.name, func.count(Policy.id).desc())
        .all()
    )

    return {
        "total": total,
        "agents": agent_rows,
        "carriers": carrier_rows,
        "agent_carriers": agent_carrier_rows,
    }


@pharmacies_bp.route("/admin/pharmacies")
@login_required
@_admin_required
def pharmacy_list():
    agency_id  = current_user.agency_id
    pharmacies = Pharmacy.query.filter_by(agency_id=agency_id).order_by(Pharmacy.name).all()

    stats = {p.id: _pharmacy_stats(p.id, agency_id) for p in pharmacies}

    return render_template("pharmacies.html",
                           pharmacies=pharmacies,
                           stats=stats)


@pharmacies_bp.route("/admin/pharmacies/<int:pharmacy_id>/agents", methods=["POST"])
@login_required
@_admin_required
def pharmacy_set_agents(pharmacy_id):
    """Replace agent assignments for a pharmacy (checkbox form submit)."""
    pharmacy = Pharmacy.query.filter_by(
        id=pharmacy_id, agency_id=current_user.agency_id
    ).first_or_404()

    agent_ids = request.form.getlist("agent_ids", type=int)
    agents    = User.query.filter(User.id.in_(agent_ids),
                                  User.agency_id == current_user.agency_id).all()
    pharmacy.agents = agents
    db.session.commit()
    flash(f"Agents updated for {pharmacy.name}.", "success")
    return redirect(url_for("pharmacies.pharmacy_list"))


@pharmacies_bp.route("/admin/pharmacies/new", methods=["GET", "POST"])
@login_required
@_admin_required
def pharmacy_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Pharmacy name is required.", "error")
            return redirect(url_for("pharmacies.pharmacy_new"))

        pharmacy = Pharmacy(
            agency_id=current_user.agency_id,
            name=name,
            address1=request.form.get("address1", "").strip() or None,
            city=request.form.get("city", "").strip() or None,
            state=request.form.get("state", "").strip() or None,
            zip_code=request.form.get("zip_code", "").strip() or None,
            phone=request.form.get("phone", "").strip() or None,
            is_partner=request.form.get("is_partner") != "off",
            rent_amount=float(request.form.get("rent_amount") or 0),
            rent_frequency=request.form.get("rent_frequency", "monthly"),
            contact_name=request.form.get("contact_name", "").strip() or None,
            contact_phone=request.form.get("contact_phone", "").strip() or None,
            contact_email=request.form.get("contact_email", "").strip() or None,
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(pharmacy)
        db.session.commit()
        flash(f"{pharmacy.name} added.", "success")
        return redirect(url_for("pharmacies.pharmacy_list"))

    return render_template("pharmacy_form.html", pharmacy=None)


@pharmacies_bp.route("/admin/pharmacies/<int:pharmacy_id>", methods=["GET", "POST"])
@login_required
@_admin_required
def pharmacy_edit(pharmacy_id):
    pharmacy = Pharmacy.query.filter_by(
        id=pharmacy_id, agency_id=current_user.agency_id
    ).first_or_404()

    if request.method == "POST":
        pharmacy.name          = request.form.get("name", "").strip() or pharmacy.name
        pharmacy.address1      = request.form.get("address1", "").strip() or None
        pharmacy.city          = request.form.get("city", "").strip() or None
        pharmacy.state         = request.form.get("state", "").strip() or None
        pharmacy.zip_code      = request.form.get("zip_code", "").strip() or None
        pharmacy.phone         = request.form.get("phone", "").strip() or None
        pharmacy.is_partner    = request.form.get("is_partner") != "off"
        pharmacy.rent_amount   = float(request.form.get("rent_amount") or 0)
        pharmacy.rent_frequency = request.form.get("rent_frequency", "monthly")
        pharmacy.contact_name  = request.form.get("contact_name", "").strip() or None
        pharmacy.contact_phone = request.form.get("contact_phone", "").strip() or None
        pharmacy.contact_email = request.form.get("contact_email", "").strip() or None
        pharmacy.notes         = request.form.get("notes", "").strip() or None
        db.session.commit()
        flash(f"{pharmacy.name} updated.", "success")
        return redirect(url_for("pharmacies.pharmacy_list"))

    return render_template("pharmacy_form.html", pharmacy=pharmacy)
