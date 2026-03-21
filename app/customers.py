"""
app/customers.py

Blueprint for customer master records — search, profile view, notes, contacts, deduplication.
Agents see only their own customers; admins see all.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Customer, CustomerNote, CustomerContact, CustomerAorHistory, Policy, User, Pharmacy

customers_bp = Blueprint("customers", __name__)


def _admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)
    return decorated


def get_customer_policies(customer):
    """
    Return all Policy records linked to a customer across all carriers.
    Primary join: Policy.mbi == customer.mbi
    Humana fallback: match on phone + DOB when MBI is null.
    """
    policies = []

    if customer.mbi:
        policies = Policy.query.filter_by(mbi=customer.mbi).order_by(Policy.carrier).all()

    # Collect carriers already found via MBI to avoid duplicates
    found_carriers = {p.carrier for p in policies}

    # Humana fallback — Humana masks the MBI, match on phone + DOB
    if "Humana" not in found_carriers and customer.phone_primary and customer.dob:
        humana_policies = (
            Policy.query
            .filter_by(carrier="Humana", phone=customer.phone_primary, dob=customer.dob)
            .all()
        )
        policies.extend(humana_policies)

    # Also match by humana_id if available
    if customer.humana_id and "Humana" not in {p.carrier for p in policies}:
        humana_by_id = Policy.query.filter_by(carrier="Humana", member_id=customer.humana_id).all()
        policies.extend(humana_by_id)

    # Sort: carrier then effective_date desc
    policies.sort(key=lambda p: (p.carrier, p.effective_date or ""))
    return policies


def _customer_query():
    """Base query scoped by current user — agents see own, admins see all."""
    q = Customer.query
    if not current_user.is_admin:
        q = q.filter_by(primary_agent_id=current_user.id)
    return q


# ---------------------------------------------------------------------------
# List + Search
# ---------------------------------------------------------------------------

@customers_bp.route("/customers")
@login_required
def customers_list():
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()

    query = _customer_query()
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Customer.full_name.ilike(like),
                Customer.phone_primary.ilike(like),
                Customer.mbi.ilike(like),
            )
        )

    customers = query.order_by(Customer.last_name, Customer.first_name).paginate(
        page=page, per_page=50, error_out=False
    )
    return render_template("customers_list.html", customers=customers, q=q)


@customers_bp.route("/customers/search")
@login_required
def customers_search():
    """AJAX JSON endpoint — live search by name, MBI, or phone."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    like = f"%{q}%"
    query = _customer_query().filter(
        db.or_(
            Customer.full_name.ilike(like),
            Customer.phone_primary.ilike(like),
            Customer.mbi.ilike(like),
        )
    ).limit(20)

    results = [
        {
            "id": c.id,
            "name": c.display_name,
            "mbi": c.mbi or "",
            "phone": c.phone_primary or "",
            "agent": c.primary_agent.display_name if c.primary_agent else "",
            "url": url_for("customers.customer_profile", customer_id=c.id),
        }
        for c in query.all()
    ]
    return jsonify(results)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@customers_bp.route("/customers/new", methods=["GET", "POST"])
@login_required
def customer_new():
    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        if not first_name or not last_name:
            flash("First and last name are required.", "error")
            return redirect(url_for("customers.customer_new"))

        customer = Customer(
            first_name=first_name,
            last_name=last_name,
            full_name=f"{first_name} {last_name}",
            mbi=request.form.get("mbi", "").strip() or None,
            phone_primary=request.form.get("phone_primary", "").strip() or None,
            email=request.form.get("email", "").strip() or None,
            dob=request.form.get("dob") or None,
            address1=request.form.get("address1", "").strip() or None,
            city=request.form.get("city", "").strip() or None,
            state=request.form.get("state", "").strip() or None,
            zip_code=request.form.get("zip_code", "").strip() or None,
            county=request.form.get("county", "").strip() or None,
            medicaid_level=request.form.get("medicaid_level") or None,
            lead_source=request.form.get("lead_source") or None,
            primary_agent_id=current_user.id,
            created_by_id=current_user.id,
            manually_edited=True,
        )
        db.session.add(customer)
        db.session.commit()
        flash(f"{customer.display_name} added.", "success")
        return redirect(url_for("customers.customer_profile", customer_id=customer.id))

    agents = User.query.filter(User.is_admin == False).order_by(User.name).all()  # noqa
    return render_template("customer_new.html", agents=agents)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@customers_bp.route("/customers/<int:customer_id>")
@login_required
def customer_profile(customer_id):
    customer = _customer_query().filter_by(id=customer_id).first_or_404()
    policies = get_customer_policies(customer)
    notes = customer.notes.limit(50).all()
    contacts = customer.contacts.all()
    aor_history = customer.aor_history.limit(20).all()
    agents = User.query.order_by(User.name).all()
    return render_template(
        "customer_profile.html",
        customer=customer,
        policies=policies,
        notes=notes,
        contacts=contacts,
        aor_history=aor_history,
        agents=agents,
        pharmacies=Pharmacy.query.order_by(Pharmacy.name).all(),
    )


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@customers_bp.route("/customers/<int:customer_id>/notes", methods=["POST"])
@login_required
def customer_add_note(customer_id):
    customer = _customer_query().filter_by(id=customer_id).first_or_404()
    note_text = request.form.get("note_text", "").strip()
    if not note_text:
        flash("Note cannot be empty.", "error")
        return redirect(url_for("customers.customer_profile", customer_id=customer_id))

    note = CustomerNote(
        customer_id=customer.id,
        agent_id=current_user.id,
        note_text=note_text,
        note_type=request.form.get("note_type", "general"),
        contact_method=request.form.get("contact_method") or None,
    )
    db.session.add(note)
    db.session.commit()
    flash("Note added.", "success")
    return redirect(url_for("customers.customer_profile", customer_id=customer_id))


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

@customers_bp.route("/customers/<int:customer_id>/contacts", methods=["POST"])
@login_required
def customer_add_contact(customer_id):
    customer = _customer_query().filter_by(id=customer_id).first_or_404()
    contact_name = request.form.get("contact_name", "").strip()
    if not contact_name:
        flash("Contact name is required.", "error")
        return redirect(url_for("customers.customer_profile", customer_id=customer_id))

    contact = CustomerContact(
        customer_id=customer.id,
        contact_name=contact_name,
        relationship=request.form.get("relationship") or None,
        phone=request.form.get("phone", "").strip() or None,
        email=request.form.get("email", "").strip() or None,
        is_primary=request.form.get("is_primary") == "on",
        notes=request.form.get("notes", "").strip() or None,
    )
    db.session.add(contact)
    db.session.commit()
    flash(f"{contact_name} added as contact.", "success")
    return redirect(url_for("customers.customer_profile", customer_id=customer_id))


# ---------------------------------------------------------------------------
# Pharmacy linkage
# ---------------------------------------------------------------------------

@customers_bp.route("/customers/<int:customer_id>/pharmacy", methods=["POST"])
@login_required
def customer_link_pharmacy(customer_id):
    customer = _customer_query().filter_by(id=customer_id).first_or_404()
    pharmacy_id = request.form.get("pharmacy_id", type=int)
    customer.pharmacy_id = pharmacy_id or None
    customer.manually_edited = True
    db.session.commit()
    flash("Pharmacy updated.", "success")
    return redirect(url_for("customers.customer_profile", customer_id=customer_id))


# ---------------------------------------------------------------------------
# Admin: deduplication
# ---------------------------------------------------------------------------

@customers_bp.route("/admin/customers/duplicates")
@login_required
@_admin_required
def customer_duplicates():
    """
    Show customers that share name + DOB + phone — likely the same person
    imported from multiple carriers before MBI was resolved.
    """
    from sqlalchemy import func
    subq = (
        db.session.query(
            func.lower(Customer.first_name).label("fn"),
            func.lower(Customer.last_name).label("ln"),
            Customer.dob,
            Customer.phone_primary,
            func.count(Customer.id).label("cnt"),
        )
        .filter(Customer.dob.isnot(None), Customer.phone_primary.isnot(None))
        .group_by(
            func.lower(Customer.first_name),
            func.lower(Customer.last_name),
            Customer.dob,
            Customer.phone_primary,
        )
        .having(func.count(Customer.id) > 1)
        .subquery()
    )

    duplicate_groups = db.session.query(subq).all()
    # For each group, fetch the actual customer records
    groups = []
    for row in duplicate_groups:
        dupes = (
            Customer.query
            .filter(
                db.func.lower(Customer.first_name) == row.fn,
                db.func.lower(Customer.last_name) == row.ln,
                Customer.dob == row.dob,
                Customer.phone_primary == row.phone_primary,
            )
            .all()
        )
        if len(dupes) > 1:
            groups.append(dupes)

    return render_template("customer_duplicates.html", groups=groups)


@customers_bp.route("/admin/customers/merge", methods=["POST"])
@login_required
@_admin_required
def customer_merge():
    """
    Merge two customer records. The primary keeps its data;
    all notes/contacts/AOR history from the secondary move to the primary.
    The secondary is then deleted.
    """
    primary_id = request.form.get("primary_id", type=int)
    secondary_id = request.form.get("secondary_id", type=int)

    if not primary_id or not secondary_id or primary_id == secondary_id:
        flash("Invalid merge request.", "error")
        return redirect(url_for("customers.customer_duplicates"))

    primary = Customer.query.get_or_404(primary_id)
    secondary = Customer.query.get_or_404(secondary_id)

    # Move all child records to the primary
    CustomerNote.query.filter_by(customer_id=secondary.id).update({"customer_id": primary.id})
    CustomerContact.query.filter_by(customer_id=secondary.id).update({"customer_id": primary.id})
    CustomerAorHistory.query.filter_by(customer_id=secondary.id).update({"customer_id": primary.id})

    # Carry forward MBI/humana_id if primary is missing them
    if not primary.mbi and secondary.mbi:
        primary.mbi = secondary.mbi
    if not primary.humana_id and secondary.humana_id:
        primary.humana_id = secondary.humana_id

    db.session.delete(secondary)
    db.session.commit()
    flash(f"Merged into {primary.display_name}.", "success")
    return redirect(url_for("customers.customer_profile", customer_id=primary.id))
