"""
app/customers.py

Blueprint for customer master records — search, profile view, notes, contacts, deduplication.
Agents see only their own customers; admins see all.
"""

import csv
import io
import json
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort, Response
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models import Customer, CustomerNote, CustomerContact, CustomerAorHistory, Policy, PolicyPayment, User, Pharmacy, SmsTemplate, CustomerSavedView

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
    All queries scoped to customer's agency_id.
    """
    policies = []
    agency_id = customer.agency_id

    # FK-first: policies explicitly linked to this customer (works for no-MBI carriers).
    policies = Policy.query.filter_by(
        customer_id=customer.id, agency_id=agency_id
    ).order_by(Policy.carrier).all()
    seen_ids = {p.id for p in policies}

    # MBI join (legacy link) — add any not already found via FK.
    if customer.mbi:
        for p in Policy.query.filter_by(mbi=customer.mbi, agency_id=agency_id).all():
            if p.id not in seen_ids:
                policies.append(p)
                seen_ids.add(p.id)

    # Collect carriers already found via FK/MBI to avoid duplicate Humana queries
    found_carriers = {p.carrier for p in policies}

    # Humana fallback — Humana masks the MBI, match on phone + DOB
    if "Humana" not in found_carriers and customer.phone_primary and customer.dob:
        humana_policies = (
            Policy.query
            .filter_by(carrier="Humana", phone=customer.phone_primary,
                       dob=customer.dob, agency_id=agency_id)
            .all()
        )
        for p in humana_policies:
            if p.id not in seen_ids:
                policies.append(p)
                seen_ids.add(p.id)

    # Also match by humana_id if available
    if customer.humana_id and "Humana" not in {p.carrier for p in policies}:
        humana_by_id = Policy.query.filter_by(
            carrier="Humana", member_id=customer.humana_id, agency_id=agency_id
        ).all()
        for p in humana_by_id:
            if p.id not in seen_ids:
                policies.append(p)
                seen_ids.add(p.id)

    # Sort: carrier then effective_date desc
    policies.sort(key=lambda p: (p.carrier, p.effective_date or ""))
    return policies


def _customer_query(include_former=False):
    """
    Base query scoped by agency and agent visibility rules.

    Admin: sees all customers.
    Agent (default): only customers where primary_agent_id = me (current AOR).
    Agent (include_former=True): also customers where agent appears in
      AOR history but is no longer primary — read-only in the UI.
    """
    q = Customer.query.filter_by(agency_id=current_user.agency_id)
    if not current_user.is_admin:
        if include_former:
            # Current AOR OR ever appeared in AOR history for this agency
            former_ids = (
                db.session.query(CustomerAorHistory.customer_id)
                .filter_by(agent_id=current_user.id, agency_id=current_user.agency_id)
                .distinct()
                .subquery()
            )
            q = q.filter(
                db.or_(
                    Customer.primary_agent_id == current_user.id,
                    Customer.id.in_(former_ids),
                )
            )
        else:
            q = q.filter_by(primary_agent_id=current_user.id)
    return q


def _is_current_aor(customer):
    """True if the logged-in user is the current AOR for this customer, or is admin."""
    if current_user.is_admin:
        return True
    return customer.primary_agent_id == current_user.id


def _apply_customer_filters(query, q_str, f_carrier, f_plan_type, f_agent_id, f_medicaid):
    """Apply the standard customer list filters to a query. Used by both list and export routes."""
    if q_str:
        like = f"%{q_str}%"
        query = query.filter(
            db.or_(
                Customer.full_name.ilike(like),
                Customer.phone_primary.ilike(like),
                Customer.mbi.ilike(like),
            )
        )
    if f_carrier or f_plan_type:
        # Base policy filter (carrier / plan_type), scoped to agency.
        base = Policy.query.filter(Policy.agency_id == current_user.agency_id)
        if f_carrier:
            base = base.filter(Policy.carrier == f_carrier)
        if f_plan_type:
            # "all_ma" = any Medicare Advantage subtype; specific values filter exactly
            if f_plan_type == "all_ma":
                base = base.filter(Policy.plan_type.in_(["MAPD", "MA", "DSNP", "CSNP"]))
            else:
                base = base.filter(Policy.plan_type == f_plan_type)

        # FK-first: customer_ids directly linked to matching policies (works for
        # no-MBI carriers like Humana/BCBS).
        fk_ids = (base.filter(Policy.customer_id.isnot(None))
                      .with_entities(Policy.customer_id).distinct())

        # MBI fallback: customers whose MBI matches a matching policy's MBI
        # (covers any policy whose customer_id FK was not backfilled).
        mbi_subq = (base.filter(Policy.mbi.isnot(None))
                        .with_entities(Policy.mbi).distinct())
        mbi_ids = (db.session.query(Customer.id)
                   .filter(Customer.agency_id == current_user.agency_id,
                           Customer.mbi.isnot(None),
                           Customer.mbi.in_(mbi_subq)))

        query = query.filter(Customer.id.in_(fk_ids.union(mbi_ids)))
    if f_agent_id and current_user.is_admin:
        query = query.filter(Customer.primary_agent_id == f_agent_id)
    if f_medicaid:
        if f_medicaid == "none":
            query = query.filter(
                db.or_(Customer.medicaid_level.is_(None), Customer.medicaid_level == "")
            )
        else:
            query = query.filter(Customer.medicaid_level == f_medicaid)
    return query


# ---------------------------------------------------------------------------
# List + Search
# ---------------------------------------------------------------------------

@customers_bp.route("/customers")
@login_required
def customers_list():
    page           = request.args.get("page", 1, type=int)
    q              = request.args.get("q", "").strip()
    sort           = request.args.get("sort", "name")
    dir_           = request.args.get("dir", "asc")
    include_former = request.args.get("include_former") == "1"

    # New filter params
    f_carrier   = request.args.get("carrier", "").strip()
    f_plan_type = request.args.get("plan_type", "").strip()
    f_agent_id  = request.args.get("agent_id", type=int)
    f_medicaid  = request.args.get("medicaid", "").strip()

    query = _customer_query(include_former=include_former)

    query = _apply_customer_filters(query, q, f_carrier, f_plan_type, f_agent_id, f_medicaid)

    _sort_cols = {
        "name":     [Customer.last_name, Customer.first_name],
        "stage":    [Customer.deal_stage, Customer.last_name],
        "pharmacy": [Customer.pharmacy_id, Customer.last_name],
    }
    order_cols = _sort_cols.get(sort, _sort_cols["name"])
    if dir_ == "desc":
        order_cols = [c.desc() for c in order_cols]

    customer_page = query.order_by(*order_cols).paginate(
        page=page, per_page=50, error_out=False
    )

    # Summary stats — computed on full filtered set (not just current page)
    total_count    = query.count()
    active_count   = query.filter(Customer.deal_stage == "Active").count()
    termed_count   = query.filter(Customer.deal_stage == "Termed").count()
    medicaid_count = query.filter(
        Customer.medicaid_level.isnot(None), Customer.medicaid_level != ""
    ).count()

    # Dropdown options for filter bar
    carriers = [r[0] for r in
        db.session.query(Policy.carrier).filter_by(agency_id=current_user.agency_id)
        .distinct().order_by(Policy.carrier).all() if r[0]]

    agents = (User.query.filter_by(agency_id=current_user.agency_id)
              .filter(User.is_admin == False)
              .order_by(User.name).all()) if current_user.is_admin else []

    # Shared saved views visible to this user
    shared_views = CustomerSavedView.query.filter_by(
        agency_id=current_user.agency_id, is_shared=True
    ).order_by(CustomerSavedView.name).all()

    # Mark which customers are former (not current AOR) for the template
    if not current_user.is_admin and include_former:
        for c in customer_page.items:
            c.is_former = (c.primary_agent_id != current_user.id)
    else:
        for c in customer_page.items:
            c.is_former = False

    # Build a policy-info lookup for the current page — single query, no N+1.
    # For each MBI, pick the most recently effective active policy.
    page_mbis = [c.mbi for c in customer_page.items if c.mbi]
    policy_info = {}  # mbi → {carrier, plan_type, plan_name, effective_date}
    if page_mbis:
        from app.models import Plan as PlanModel
        rows = (
            db.session.query(
                Policy.mbi, Policy.carrier, Policy.plan_type,
                Policy.plan_name, Policy.effective_date,
                PlanModel.friendly_name,
            )
            .outerjoin(PlanModel, Policy.plan_id == PlanModel.id)
            .filter(
                Policy.agency_id == current_user.agency_id,
                Policy.mbi.in_(page_mbis),
                Policy.status != "termed",
            )
            .order_by(Policy.mbi, Policy.effective_date.desc().nullslast())
            .all()
        )
        # Keep only the first (most recent) row per MBI
        seen = set()
        for row in rows:
            if row.mbi not in seen:
                seen.add(row.mbi)
                display_name = row.friendly_name or row.plan_name or ""
                policy_info[row.mbi] = {
                    "carrier":        row.carrier or "",
                    "plan_type":      row.plan_type or "",
                    "plan_name":      display_name,
                    "effective_date": row.effective_date,
                }

    return render_template(
        "customers_list.html",
        customers=customer_page,
        q=q, sort=sort, dir=dir_, include_former=include_former,
        f_carrier=f_carrier, f_plan_type=f_plan_type,
        f_agent_id=str(f_agent_id) if f_agent_id else "", f_medicaid=f_medicaid,
        stats={"total": total_count, "active": active_count,
               "termed": termed_count, "medicaid": medicaid_count},
        carriers=carriers, agents=agents,
        shared_views=shared_views,
        policy_info=policy_info,
    )


@customers_bp.route("/customers/export")
@login_required
def customers_export():
    q_str          = request.args.get("q", "").strip()
    f_carrier      = request.args.get("carrier", "").strip()
    f_plan_type    = request.args.get("plan_type", "").strip()
    f_agent_id     = request.args.get("agent_id", type=int)
    f_medicaid     = request.args.get("medicaid", "").strip()
    include_former = request.args.get("include_former") == "1"

    query = _customer_query(include_former=include_former)

    query = _apply_customer_filters(query, q_str, f_carrier, f_plan_type, f_agent_id, f_medicaid)

    rows = query.options(
        joinedload(Customer.primary_agent),
        joinedload(Customer.pharmacy),
    ).order_by(Customer.last_name, Customer.first_name).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "MBI", "Phone", "Email", "DOB", "Address", "City", "State", "Zip",
                     "Medicaid Level", "Stage", "Agent", "Pharmacy"])
    for c in rows:
        writer.writerow([
            c.display_name,
            c.mbi or "",
            c.phone_primary or "",
            c.email or "",
            c.dob.strftime("%m/%d/%Y") if c.dob else "",
            c.address1 or "",
            c.city or "",
            c.state or "",
            c.zip_code or "",
            c.medicaid_level or "",
            c.deal_stage or "Active",
            c.primary_agent.display_name if c.primary_agent else "",
            c.pharmacy.name if c.pharmacy else "",
        ])

    output = buf.getvalue()
    filename = f"customers_export_{datetime.today().strftime('%Y%m%d')}.csv"
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@customers_bp.route("/customers/saved-views", methods=["POST"])
@login_required
def save_customer_view():
    data      = request.get_json(force=True)
    name      = (data.get("name") or "").strip()
    state     = data.get("state")
    is_shared = bool(data.get("is_shared")) and current_user.is_admin
    if not name or not state:
        return jsonify({"error": "name and state required"}), 400
    if len(name) > 128:
        return jsonify({"error": "name too long (max 128 chars)"}), 400
    view = CustomerSavedView(
        agency_id  = current_user.agency_id,
        created_by = current_user.id,
        name       = name,
        state_json = json.dumps(state),
        is_shared  = is_shared,
    )
    db.session.add(view)
    db.session.commit()
    return jsonify({"id": view.id, "name": view.name, "is_shared": view.is_shared})


@customers_bp.route("/customers/saved-views/<int:view_id>", methods=["DELETE"])
@login_required
def delete_customer_view(view_id):
    view = CustomerSavedView.query.filter_by(
        id=view_id, agency_id=current_user.agency_id
    ).first_or_404()
    if view.created_by != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(view)
    db.session.commit()
    return jsonify({"ok": True})


@customers_bp.route("/customers/saved-views/<int:view_id>/toggle-shared", methods=["POST"])
@login_required
def toggle_shared_view(view_id):
    if not current_user.is_admin:
        abort(403)
    view = CustomerSavedView.query.filter_by(
        id=view_id, agency_id=current_user.agency_id
    ).first_or_404()
    view.is_shared = not view.is_shared
    db.session.commit()
    return jsonify({"is_shared": view.is_shared})


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
            agency_id=current_user.agency_id,
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
    # Allow access if current AOR OR former AOR (include_former=True scope)
    customer = _customer_query(include_former=True).filter_by(id=customer_id).first_or_404()
    is_current = _is_current_aor(customer)

    policies    = get_customer_policies(customer)
    notes       = customer.notes.limit(50).all()
    contacts    = customer.contacts.all()
    aor_history = customer.aor_history.limit(20).all()
    agents      = User.query.order_by(User.name).all()

    # Find when this agent's AOR ended (for former-AOR banner)
    former_end_date = None
    if not is_current and not current_user.is_admin:
        last_aor = (CustomerAorHistory.query
                    .filter_by(customer_id=customer.id, agent_id=current_user.id)
                    .filter(CustomerAorHistory.end_date.isnot(None))
                    .order_by(CustomerAorHistory.end_date.desc())
                    .first())
        if last_aor:
            former_end_date = last_aor.end_date

    agency_id = current_user.agency_id
    approved_templates = SmsTemplate.query.filter_by(
        agency_id=agency_id, status="approved"
    ).order_by(SmsTemplate.name).all() if agency_id else []

    # Payment history for this customer's policies
    policy_ids = [p.id for p in policies] if policies else []
    payments = []
    if policy_ids:
        payments = (PolicyPayment.query
                    .filter(PolicyPayment.policy_id.in_(policy_ids),
                            PolicyPayment.agency_id == agency_id)
                    .order_by(PolicyPayment.statement_date.desc())
                    .all())

    return render_template(
        "customer_profile.html",
        customer=customer,
        policies=policies,
        notes=notes,
        contacts=contacts,
        aor_history=aor_history,
        agents=agents,
        pharmacies=Pharmacy.query.order_by(Pharmacy.name).all(),
        approved_templates=approved_templates,
        is_current_aor=is_current,
        former_end_date=former_end_date,
        payments=payments,
    )


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@customers_bp.route("/customers/<int:customer_id>/notes", methods=["POST"])
@login_required
def customer_add_note(customer_id):
    customer = _customer_query(include_former=True).filter_by(id=customer_id).first_or_404()
    if not _is_current_aor(customer):
        flash("You are no longer AOR for this customer and cannot add notes.", "error")
        return redirect(url_for("customers.customer_profile", customer_id=customer_id))
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
    customer = _customer_query(include_former=True).filter_by(id=customer_id).first_or_404()
    if not _is_current_aor(customer):
        flash("You are no longer AOR for this customer.", "error")
        return redirect(url_for("customers.customer_profile", customer_id=customer_id))
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
    customer = _customer_query(include_former=True).filter_by(id=customer_id).first_or_404()
    if not _is_current_aor(customer):
        flash("You are no longer AOR for this customer.", "error")
        return redirect(url_for("customers.customer_profile", customer_id=customer_id))
    pharmacy_id = request.form.get("pharmacy_id", type=int)
    customer.pharmacy_id = pharmacy_id or None
    customer.manually_edited = True
    db.session.commit()
    flash("Pharmacy updated.", "success")
    return redirect(url_for("customers.customer_profile", customer_id=customer_id))


@customers_bp.route("/customers/<int:customer_id>/sms-consent", methods=["POST"])
@login_required
def customer_toggle_sms_consent(customer_id):
    """
    Toggle SMS consent on/off for a customer.
    Granting consent records the current UTC timestamp.
    Revoking consent sets sms_consent_at back to NULL.
    """
    customer = _customer_query(include_former=True).filter_by(id=customer_id).first_or_404()
    if not _is_current_aor(customer):
        flash("You are no longer AOR for this customer.", "error")
        return redirect(url_for("customers.customer_profile", customer_id=customer_id))
    if customer.sms_consent_at is None:
        customer.sms_consent_at = datetime.utcnow()
        customer.manually_edited = True
        db.session.commit()
        flash("SMS consent granted.", "success")
    else:
        customer.sms_consent_at = None
        customer.manually_edited = True
        db.session.commit()
        flash("SMS consent revoked.", "success")
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
        .filter(
            Customer.agency_id == current_user.agency_id,
            Customer.dob.isnot(None),
            Customer.phone_primary.isnot(None),
        )
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
                Customer.agency_id == current_user.agency_id,
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

    primary = Customer.query.filter_by(
        id=primary_id, agency_id=current_user.agency_id
    ).first_or_404()
    secondary = Customer.query.filter_by(
        id=secondary_id, agency_id=current_user.agency_id
    ).first_or_404()

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


# ---------------------------------------------------------------------------
# MBI-based duplicate detection + merge (agent-facing, D-07 / D-08 / D-22)
# ---------------------------------------------------------------------------

def get_duplicate_mbi_count(agency_id, agent_id=None, is_admin=False):
    """Return number of MBI groups with duplicates visible to this user."""
    dupe_mbis = (db.session.query(Customer.mbi)
                 .filter(Customer.agency_id == agency_id, Customer.mbi.isnot(None))
                 .group_by(Customer.mbi)
                 .having(func.count(Customer.id) > 1)
                 .all())
    if is_admin:
        return len(dupe_mbis)
    if agent_id is None:
        return 0
    count = 0
    for row in dupe_mbis:
        rows = Customer.query.filter_by(agency_id=agency_id, mbi=row.mbi).all()
        if any(r.primary_agent_id == agent_id for r in rows):
            count += 1
    return count


@customers_bp.route('/customers/duplicates')
@login_required
def duplicates_list():
    agency_id = current_user.agency_id

    # Find MBIs that appear on >1 customer (within agency)
    dupe_mbis = (db.session.query(Customer.mbi)
                 .filter(Customer.agency_id == agency_id, Customer.mbi.isnot(None))
                 .group_by(Customer.mbi)
                 .having(func.count(Customer.id) > 1)
                 .all())
    mbi_list = [row.mbi for row in dupe_mbis]

    # Build groups: list of (mbi, [Customer, Customer, ...])
    groups = []
    for mbi in mbi_list:
        rows = Customer.query.filter_by(agency_id=agency_id, mbi=mbi).all()
        # For agents (non-admin): only show groups where at least one row is theirs
        if not current_user.is_admin:
            if not any(r.primary_agent_id == current_user.id for r in rows):
                continue
        groups.append((mbi, rows))

    return render_template('customer_duplicates.html', groups=groups)


@customers_bp.route('/customers/merge/<int:a_id>/<int:b_id>')
@login_required
def merge_view(a_id, b_id):
    agency_id = current_user.agency_id
    a = Customer.query.filter_by(id=a_id, agency_id=agency_id).first_or_404()
    b = Customer.query.filter_by(id=b_id, agency_id=agency_id).first_or_404()

    if a.mbi != b.mbi or a.mbi is None:
        flash("Customers do not share an MBI; cannot merge.", "error")
        return redirect(url_for('customers.duplicates_list'))

    # Authorization: agent must own at least one of the two records
    if not current_user.is_admin:
        if a.primary_agent_id != current_user.id and b.primary_agent_id != current_user.id:
            abort(403)

    return render_template('customer_merge.html', a=a, b=b)


@customers_bp.route('/customers/merge/<int:a_id>/<int:b_id>', methods=['POST'])
@login_required
def execute_merge(a_id, b_id):
    agency_id = current_user.agency_id
    canonical_id = request.form.get('canonical_id', type=int)
    if canonical_id not in (a_id, b_id):
        flash("Invalid canonical selection.", "error")
        return redirect(url_for('customers.merge_view', a_id=a_id, b_id=b_id))

    discarded_id = a_id if canonical_id == b_id else b_id

    canonical = Customer.query.filter_by(id=canonical_id, agency_id=agency_id).first_or_404()
    discarded = Customer.query.filter_by(id=discarded_id, agency_id=agency_id).first_or_404()

    if canonical.mbi != discarded.mbi or canonical.mbi is None:
        flash("Cannot merge customers with different MBIs.", "error")
        return redirect(url_for('customers.duplicates_list'))

    # Authorization: agent must own at least one of the two records
    if not current_user.is_admin:
        if canonical.primary_agent_id != current_user.id and discarded.primary_agent_id != current_user.id:
            abort(403)

    # Handle AOR unique constraint collision (customer_id, carrier, effective_date)
    existing_aor_keys = {(a.carrier, a.effective_date) for a in canonical.aor_history}
    for aor in list(discarded.aor_history):
        if (aor.carrier, aor.effective_date) in existing_aor_keys:
            db.session.delete(aor)
        else:
            aor.customer_id = canonical.id

    # Migrate notes and contacts (no unique constraints to worry about)
    CustomerNote.query.filter_by(customer_id=discarded.id).update({'customer_id': canonical.id})
    CustomerContact.query.filter_by(customer_id=discarded.id).update({'customer_id': canonical.id})

    discarded_label = f"{discarded.first_name} {discarded.last_name}".strip() or f"id={discarded.id}"
    canonical_label = f"{canonical.first_name} {canonical.last_name}".strip() or f"id={canonical.id}"

    db.session.delete(discarded)
    db.session.commit()

    flash(f"Merged {discarded_label} into {canonical_label}.", "success")
    return redirect(url_for('customers.customer_profile', customer_id=canonical.id))
