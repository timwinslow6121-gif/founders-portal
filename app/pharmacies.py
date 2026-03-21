"""
app/pharmacies.py

Admin-only blueprint for managing partner pharmacies.
Pharmacies refer customers to Founders agents; Founders pays rent in return.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Pharmacy

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


@pharmacies_bp.route("/admin/pharmacies")
@login_required
@_admin_required
def pharmacy_list():
    pharmacies = Pharmacy.query.order_by(Pharmacy.name).all()
    return render_template("pharmacies.html", pharmacies=pharmacies)


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
    pharmacy = Pharmacy.query.get_or_404(pharmacy_id)

    if request.method == "POST":
        pharmacy.name = request.form.get("name", "").strip() or pharmacy.name
        pharmacy.address1 = request.form.get("address1", "").strip() or None
        pharmacy.city = request.form.get("city", "").strip() or None
        pharmacy.state = request.form.get("state", "").strip() or None
        pharmacy.zip_code = request.form.get("zip_code", "").strip() or None
        pharmacy.phone = request.form.get("phone", "").strip() or None
        pharmacy.is_partner = request.form.get("is_partner") != "off"
        pharmacy.rent_amount = float(request.form.get("rent_amount") or 0)
        pharmacy.rent_frequency = request.form.get("rent_frequency", "monthly")
        pharmacy.contact_name = request.form.get("contact_name", "").strip() or None
        pharmacy.contact_phone = request.form.get("contact_phone", "").strip() or None
        pharmacy.contact_email = request.form.get("contact_email", "").strip() or None
        pharmacy.notes = request.form.get("notes", "").strip() or None
        db.session.commit()
        flash(f"{pharmacy.name} updated.", "success")
        return redirect(url_for("pharmacies.pharmacy_list"))

    return render_template("pharmacy_form.html", pharmacy=pharmacy)
