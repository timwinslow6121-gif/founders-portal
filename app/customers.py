"""
app/customers.py

Blueprint for customer master records — search, profile view, notes, contacts, deduplication.
Agents see only their own customers; admins see all.
"""

import csv
import io
import json
from datetime import datetime, date
from datetime import timedelta as _timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort, Response, current_app
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models import Customer, CustomerNote, CustomerContact, CustomerAorHistory, Policy, PolicyPayment, User, Pharmacy, SmsTemplate, CustomerSavedView, CommissionLineItem
from app import customer_provenance as cp
from app.audit import log_event
from app.plan_lane import plan_lane

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


def _name_search_filter(q_str):
    """Build a token-aware search filter for a free-text customer query.

    Splits the query on whitespace; EACH token must match the name (first/last/full)
    OR the phone OR the MBI. Tokens are AND-ed so 'robbie belk' narrows, but because
    each token matches full_name/first/last independently it tolerates a middle
    initial ('Robbie A. Belk') and any word order ('belk robbie'). A single-substring
    ILIKE on full_name alone could not match 'robbie belk' across the 'A.' — that was
    the bug. Returns a SQLAlchemy filter clause, or None for an empty query."""
    tokens = q_str.split()
    if not tokens:
        return None
    per_token = []
    for tok in tokens:
        like = f"%{tok}%"
        per_token.append(db.or_(
            Customer.full_name.ilike(like),
            Customer.first_name.ilike(like),
            Customer.last_name.ilike(like),
            Customer.phone_primary.ilike(like),
            Customer.mbi.ilike(like),
        ))
    return db.and_(*per_token)


def _apply_customer_filters(query, q_str, f_carrier, f_plan_type, f_agent_id, f_medicaid,
                            f_language=None):
    """Apply the standard customer list filters to a query. Used by both list and export routes."""
    name_filter = _name_search_filter(q_str)
    if name_filter is not None:
        query = query.filter(name_filter)
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
    if f_language:
        query = query.filter(Customer.language == f_language)
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
    f_language  = request.args.get("language", "").strip()

    query = _customer_query(include_former=include_former)

    query = _apply_customer_filters(query, q, f_carrier, f_plan_type, f_agent_id, f_medicaid,
                                    f_language)

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

    languages = [r[0] for r in
        db.session.query(Customer.language).filter_by(agency_id=current_user.agency_id)
        .filter(Customer.language.isnot(None), Customer.language != "")
        .distinct().order_by(Customer.language).all() if r[0]]

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
        f_language=f_language,
        stats={"total": total_count, "active": active_count,
               "termed": termed_count, "medicaid": medicaid_count},
        carriers=carriers, agents=agents, languages=languages,
        shared_views=shared_views,
        policy_info=policy_info,
    )


CUSTOMER_COLS = ["Name", "Preferred Name", "MBI", "DOB", "Gender",
                 "Phone", "Phone (alt)", "Email",
                 "Address", "City", "State", "Zip", "County",
                 "Medicaid Level", "Language", "Lead Source",
                 "Stage", "Agent", "Pharmacy"]

PLAN_COLS = ["Carrier", "Plan Name", "CMS Code", "Segment", "Plan Type",
             "Carrier Plan Type", "Member ID", "Effective Date"]


def _active_policies_for(customers):
    """{customer_id: [Policy]} for the exported set, with the linked Plan bucket.

    One query for the whole page rather than N+1 — the export can run over the
    entire book.
    """
    ids = [c.id for c in customers]
    if not ids:
        return {}
    pols = (Policy.query
            .options(joinedload(Policy.plan))
            .filter(Policy.agency_id == current_user.agency_id,
                    Policy.customer_id.in_(ids),
                    Policy.status == "active")
            .order_by(Policy.carrier, Policy.id)
            .all())
    out = {}
    for p in pols:
        out.setdefault(p.customer_id, []).append(p)
    return out


def _bucket_type(p):
    """Authoritative plan type: the LINKED BUCKET, never Policy.plan_type.

    Policy.plan_type carries CARRIER vocabulary — UHC types most Part C policies
    "MA" whether or not they include drug coverage, so ~2,133 of 2,272 active UHC
    rows say MA while only ~15 are truly MA-only. metrics._by_plan_type() derives
    the mix from the bucket for exactly this reason; the export must too.
    """
    plan = getattr(p, "plan", None)
    return (getattr(plan, "plan_type", None) or "").strip()


def _split_primary_medical(pols):
    """(primary_medical_policy_or_None, ['Medigap Plan G', ...]) for the rest.

    Uses the shared plan_lane classifier so "primary medical" means the same
    thing here as it does in the merge logic.
    """
    primary, others = None, []
    for p in pols:
        lane = plan_lane(_bucket_type(p) or p.plan_type)
        if lane == "primary_medical" and primary is None:
            primary = p
        else:
            label = (getattr(getattr(p, "plan", None), "plan_name", None)
                     or p.plan_name or p.carrier or "").strip()
            if label:
                others.append(label)
    return primary, others


def _customer_cells(c):
    return [
        c.display_name,
        c.preferred_name or "",
        c.mbi or "",
        c.dob.strftime("%m/%d/%Y") if c.dob else "",
        c.gender or "",
        c.phone_primary or "",
        c.phone_secondary or "",
        c.email or "",
        c.address1 or "",
        c.city or "",
        c.state or "",
        c.zip_code or "",
        c.county or "",
        c.medicaid_level or "",
        c.language or "",
        c.lead_source or "",
        c.deal_stage or "Active",
        c.primary_agent.display_name if c.primary_agent else "",
        c.pharmacy.name if c.pharmacy else "",
    ]


def _plan_cells(p):
    if p is None:
        return [""] * len(PLAN_COLS)
    plan = getattr(p, "plan", None)
    return [
        p.carrier or "",
        (getattr(plan, "plan_name", None) or p.plan_name or ""),
        (getattr(plan, "cms_plan_id", None) or ""),
        (p.contract_code or "").split("-")[-1] if (p.contract_code or "").count("-") == 2 else "",
        _bucket_type(p),
        p.plan_type or "",
        p.member_id or "",
        p.effective_date.strftime("%m/%d/%Y") if p.effective_date else "",
    ]


def _filter_description(*, q_str, f_carrier, f_plan_type, f_agent_id, f_medicaid,
                        f_language, include_former, per_policy, emitted):
    """One human-readable line describing what this export IS.

    An exported CSV outlives the screen it came from — it gets emailed to a
    carrier, dropped in Drive, opened next AEP. Without this line a filtered
    list is indistinguishable from the whole book, which is exactly how someone
    concludes "we only have 235 BCBS members" from a Rebekah-only export.
    """
    parts = []
    if q_str:
        parts.append(f"Search={q_str}")
    if f_carrier:
        parts.append(f"Carrier={f_carrier}")
    if f_plan_type:
        parts.append(f"Plan type={f_plan_type}")
    if f_agent_id and current_user.is_admin:
        agent = User.query.filter_by(id=f_agent_id,
                                     agency_id=current_user.agency_id).first()
        parts.append(f"Agent={agent.name if agent else f_agent_id}")
    if f_medicaid:
        parts.append(f"Medicaid={f_medicaid}")
    if f_language:
        parts.append(f"Language={f_language}")
    if include_former:
        parts.append("Includes former-AOR customers")

    # A non-admin only ever sees their own book — that IS a filter, and one the
    # reader of the file cannot infer from the rows.
    if not current_user.is_admin:
        parts.append(f"Agent={current_user.name} (own book)")

    scope = "one row per active policy" if per_policy else "one row per customer"
    filters = " · ".join(parts) if parts else "no filters (whole book)"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (f"# Founders portal export · {stamp} · {emitted} rows · {scope} "
            f"· Filters: {filters}")


@customers_bp.route("/customers/export")
@login_required
def customers_export():
    q_str          = request.args.get("q", "").strip()
    f_carrier      = request.args.get("carrier", "").strip()
    f_plan_type    = request.args.get("plan_type", "").strip()
    f_agent_id     = request.args.get("agent_id", type=int)
    f_medicaid     = request.args.get("medicaid", "").strip()
    f_language     = request.args.get("language", "").strip()
    include_former = request.args.get("include_former") == "1"

    query = _customer_query(include_former=include_former)

    query = _apply_customer_filters(query, q_str, f_carrier, f_plan_type, f_agent_id, f_medicaid,
                                    f_language)

    rows = query.options(
        joinedload(Customer.primary_agent),
        joinedload(Customer.pharmacy),
    ).order_by(Customer.last_name, Customer.first_name).all()

    # mode=policies -> one row per ACTIVE POLICY (reconcile against a carrier book).
    # default       -> one row per CUSTOMER (who do I contact).
    per_policy = request.args.get("mode", "").strip() == "policies"

    policies_by_customer = _active_policies_for(rows)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CUSTOMER_COLS + PLAN_COLS +
                    ([] if per_policy else ["Other Active Plans"]))

    emitted = 0
    for c in rows:
        pols = policies_by_customer.get(c.id, [])
        if per_policy:
            # a customer with no active policy still deserves a row, so the
            # export never silently drops people the filters matched
            for p in (pols or [None]):
                writer.writerow(_customer_cells(c) + _plan_cells(p))
                emitted += 1
        else:
            primary, others = _split_primary_medical(pols)
            writer.writerow(_customer_cells(c) + _plan_cells(primary) +
                            ["; ".join(others)])
            emitted += 1

    note = _filter_description(
        q_str=q_str, f_carrier=f_carrier, f_plan_type=f_plan_type,
        f_agent_id=f_agent_id, f_medicaid=f_medicaid, f_language=f_language,
        include_former=include_former, per_policy=per_policy, emitted=emitted)
    output = note + "\n" + buf.getvalue()
    kind = "policies" if per_policy else "customers"
    filename = f"{kind}_export_{datetime.today().strftime('%Y%m%d')}.csv"
    log_event("customer_export_csv", category="export",
              detail=f"{kind} CSV export", record_count=emitted)
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

    # Search must NARROW the filtered list, never escape it. This endpoint used
    # to apply the name filter alone, so searching from a page filtered to one
    # agent still returned every other agent's customers.
    include_former = request.args.get("include_former") == "1"
    query = _apply_customer_filters(
        _customer_query(include_former=include_former),
        q,
        request.args.get("carrier", "").strip(),
        request.args.get("plan_type", "").strip(),
        request.args.get("agent_id", type=int),
        request.args.get("medicaid", "").strip(),
        request.args.get("language", "").strip(),
    )
    query = query.limit(20)

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

    can_edit = current_user.is_admin or _is_current_aor(customer)
    field_conflicts = {c["field"]: c for c in cp.list_conflicts(customer)}

    log_event("customer_view", category="data_access",
              detail="viewed customer profile", customer_id=customer.id)

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
        can_edit=can_edit,
        field_conflicts=field_conflicts,
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
# Inline field editing
# ---------------------------------------------------------------------------

@customers_bp.route("/customers/<int:customer_id>/field", methods=["POST"])
@login_required
def customer_set_field(customer_id):
    """Inline-save a single provenance-tracked field via the provenance engine."""
    customer = _customer_query(include_former=True).filter_by(id=customer_id).first_or_404()
    if not (current_user.is_admin or _is_current_aor(customer)):
        return jsonify({"ok": False, "error": "not authorized to edit this customer"}), 403

    field = (request.form.get("field") or "").strip()
    if field not in cp.PROVENANCE_FIELDS:
        return jsonify({"ok": False, "error": f"{field} is not an editable field"}), 400

    value = (request.form.get("value") or "").strip() or None
    if field == "dob" and value:
        from datetime import date as _date
        try:
            _date.fromisoformat(value)
        except ValueError:
            return jsonify({"ok": False, "error": "invalid date (use YYYY-MM-DD)"}), 400
    if field == "mbi" and value:
        owner = (Customer.query
                 .filter(Customer.agency_id == current_user.agency_id,
                         Customer.mbi == value, Customer.id != customer.id)
                 .first())
        if owner is not None:
            return jsonify({"ok": False, "merge_with": owner.id,
                            "merge_with_name": owner.display_name,
                            "error": f"That MBI belongs to {owner.display_name}. "
                                     "Same person? Review a merge."}), 409
    try:
        cp.set_human_value(customer, field, value, current_user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"customer_set_field {customer_id}.{field}: {e}")
        return jsonify({"ok": False, "error": "could not save"}), 400
    val = getattr(customer, field)
    return jsonify({"ok": True, "field": field,
                    "value": val.isoformat() if isinstance(val, date) else val,
                    "trust": cp.trust_of(customer, field)})


@customers_bp.route("/customers/<int:customer_id>/resolve-conflict", methods=["POST"])
@login_required
def customer_resolve_conflict(customer_id):
    """Resolve a field conflict (keep_current | take_incoming) via the engine."""
    customer = _customer_query(include_former=True).filter_by(id=customer_id).first_or_404()
    if not (current_user.is_admin or _is_current_aor(customer)):
        return jsonify({"ok": False, "error": "not authorized"}), 403

    field = (request.form.get("field") or "").strip()
    choose = (request.form.get("choose") or "").strip()
    if choose not in ("keep_current", "take_incoming"):
        return jsonify({"ok": False, "error": "invalid choice"}), 400
    if field not in cp.PROVENANCE_FIELDS:
        return jsonify({"ok": False, "error": "invalid field"}), 400

    try:
        cp.resolve_conflict(customer, field, choose, current_user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"customer_resolve_conflict {customer_id}.{field}: {e}")
        return jsonify({"ok": False, "error": "could not resolve"}), 400
    val = getattr(customer, field)
    return jsonify({"ok": True, "field": field,
                    "value": val.isoformat() if isinstance(val, date) else val,
                    "has_unresolved_conflicts": bool(customer.has_unresolved_conflicts)})


# ---------------------------------------------------------------------------
# Admin: deduplication
# ---------------------------------------------------------------------------

def _cluster_row_context(customer, agency_id):
    """Per-row context for the duplicate-merge UI so a human can judge a name_only cluster."""
    pols = (Policy.query
            .filter(Policy.agency_id == agency_id, Policy.customer_id == customer.id)
            .with_entities(Policy.carrier).all())
    carriers = sorted({p.carrier for p in pols if p.carrier})
    return {
        "customer": customer,
        "carriers": carriers,
        "policy_count": len(pols),
        "source": customer.source or "-",
        "stub": customer.stub,
        "dob": customer.dob,
        "mbi": customer.mbi or "-",
        "agent": (customer.primary_agent.email if customer.primary_agent else "-"),
    }


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
            # The template iterates `{% for mbi, rows in groups %}` — emit a
            # (label, rows) tuple like the agent duplicates_list view does. These
            # groups are clustered by name+DOB+phone (no single shared MBI), so the
            # label is the shared MBI if any row has one, else the shared name.
            label = next((d.mbi for d in dupes if d.mbi), None) or dupes[0].display_name
            groups.append((label, dupes))

    from app.dedup import find_no_mbi_clusters, is_lane_merge_candidate
    raw_clusters = find_no_mbi_clusters(current_user.agency_id)
    no_mbi_clusters = []
    for cl in raw_clusters:
        rows = (Customer.query
                .filter(Customer.agency_id == current_user.agency_id,
                        Customer.id.in_(cl.member_ids))
                .all())
        if not rows:
            continue
        keeper = next((r for r in rows if r.id == cl.keeper_id), rows[0])
        no_mbi_clusters.append({
            "signal": cl.signal,
            "keeper": keeper,
            "reissued_candidate": (REISSUED_MBI_MERGE_ENABLED
                                   and is_lane_merge_candidate(rows)),
            "rows": [_cluster_row_context(r, current_user.agency_id) for r in rows],
        })

    return render_template("customer_duplicates.html", groups=groups,
                           no_mbi_clusters=no_mbi_clusters)


@customers_bp.route("/admin/customers/merge", methods=["POST"])
@login_required
@_admin_required
def customer_merge():
    """Merge one or more secondary customer records into the primary via the
    merge_customers engine. Fill-blanks-only reconcile; the engine refuses
    contradictory clusters (differing DOB/MBI). Admin-only."""
    primary_id = request.form.get("primary_id", type=int)
    secondary_ids = request.form.getlist("secondary_id", type=int)
    if not primary_id or not secondary_ids or primary_id in secondary_ids:
        flash("Invalid merge request.", "error")
        return redirect(url_for("customers.customer_duplicates"))

    res = merge_customers(primary_id, secondary_ids, current_user.agency_id, current_user)
    if not res["ok"]:
        db.session.rollback()
        flash(f"Merge blocked: {res['error']}.", "error")
        return redirect(url_for("customers.customer_duplicates"))
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"customer_merge commit failed: {e}")
        flash("Merge could not be completed (database conflict). No changes were made.", "error")
        return redirect(url_for("customers.customer_duplicates"))
    flash(f"Merged {res.get('merged', 0)} record(s); filled {', '.join(res.get('filled') or [])}.",
          "success")
    return redirect(url_for("customers.customer_profile", customer_id=primary_id))


# The reissued-MBI/lane-aware merge override is now ENABLED — it calls the
# corrected lane-aware merge (merge_customers_lane_aware, below), which resolves
# the current primary-medical plan + MBI and preserves coexisting products
# (Medigap/ancillary) instead of blindly terming the loser's stale-MBI policy.
# See docs/superpowers/specs/2026-07-24-corrected-lane-aware-merge-design.md.
REISSUED_MBI_MERGE_ENABLED = True


@customers_bp.route("/admin/customers/merge-reissued-mbi", methods=["POST"])
@login_required
@_admin_required
def customer_merge_reissued_mbi():
    """Reconcile two records that are the SAME person (reissued MBI, carrier
    switcher, or coexisting-product duplicate). Gate: same non-null DOB
    (re-validated server-side; different DOB = different person, refused).
    Delegates to the lane-aware merge engine, which resolves the current
    primary-medical plan + MBI, terms only a superseded primary-medical policy,
    and keeps coexisting products (Medigap/ancillary) active. Admin-only."""
    if not REISSUED_MBI_MERGE_ENABLED:
        flash("The reissued-MBI merge is temporarily disabled pending a redesign "
              "(it does not yet handle coexisting products like DVH/Medigap correctly). "
              "No changes were made.", "error")
        return redirect(url_for("customers.customer_duplicates"))
    agency_id = current_user.agency_id
    keeper_id = request.form.get("keeper_id", type=int)
    loser_id = request.form.get("loser_id", type=int)
    if not keeper_id or not loser_id or keeper_id == loser_id:
        flash("Invalid reissued-MBI merge request.", "error")
        return redirect(url_for("customers.customer_duplicates"))

    keeper = Customer.query.filter_by(id=keeper_id, agency_id=agency_id).first_or_404()
    loser = Customer.query.filter_by(id=loser_id, agency_id=agency_id).first_or_404()

    # Re-validate the gate server-side — never trust the form. Only different
    # DOB is refused; same-MBI, diff-MBI, and coexistence pairs are all valid.
    if keeper.dob and loser.dob and keeper.dob != loser.dob:
        flash("These records have different DOBs — not the same person.", "error")
        return redirect(url_for("customers.customer_duplicates"))

    try:
        res = merge_customers_lane_aware(keeper.id, [loser.id], agency_id, current_user)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"lane-aware merge route failed: {e}")
        flash("Merge could not be completed (database conflict). No changes were made.", "error")
        return redirect(url_for("customers.customer_duplicates"))
    if not res["ok"]:
        db.session.rollback()
        flash(f"Merge blocked: {res['error']}.", "error")
        return redirect(url_for("customers.customer_duplicates"))
    if res["needs_review"]:
        flash(f"Merged {keeper.display_name}. Two primary-medical plans couldn't be "
              "auto-resolved — review which is current on the profile.", "info")
    else:
        n = len(res["superseded_policy_ids"])
        flash(f"Merged into {keeper.display_name}." + (f" Superseded {n} plan(s)." if n else ""),
              "success")
    return redirect(url_for("customers.customer_profile", customer_id=keeper.id))


# ---------------------------------------------------------------------------
# Lane-aware corrected merge (spec 2026-07-24-corrected-lane-aware-merge-design.md)
# ---------------------------------------------------------------------------

import re as _re
_MBI_L = "ACDEFGHJKMNPQRTUVWXY"
_MBI_RE = _re.compile(
    r"^[1-9][%(L)s][0-9%(L)s][0-9][%(L)s][0-9%(L)s][0-9][%(L)s][%(L)s][0-9][0-9]$"
    % {"L": _MBI_L})


def _is_valid_mbi(v):
    return bool(v) and bool(_MBI_RE.match(str(v).strip().upper()))


def _eff_type_of(p):
    """Policy plan_type, falling back to the linked Plan's plan_type when blank."""
    t = (p.plan_type or "").strip()
    if t:
        return t
    if p.plan_id:
        from app.models import Plan
        pl = db.session.get(Plan, p.plan_id)
        if pl and pl.plan_type:
            return pl.plan_type
    return ""


def _eff_code_of(p):
    """Policy contract_code, falling back to the linked Plan's cms_plan_id."""
    c = (p.contract_code or "").strip()
    if c:
        return c
    if p.plan_id:
        from app.models import Plan
        pl = db.session.get(Plan, p.plan_id)
        if pl and pl.cms_plan_id:
            return pl.cms_plan_id
    return ""


def merge_customers_lane_aware(keeper_id, loser_ids, agency_id, actor):
    """Lane-aware corrected merge (spec 2026-07-24-corrected-lane-aware-merge).
    Consolidates same-person duplicates: resolves the current MBI + primary-medical
    supersession BEFORE calling the untouched merge_customers engine, then terms the
    superseded primary-medical policy (and closes its AOR chapter) after. Keeps all
    coexisting products (Medigap/ancillary) active. Same-DOB required."""
    from app.plan_lane import resolve_primary_medical
    from app.upload import _close_open_aor_on_term

    keeper = Customer.query.filter_by(id=keeper_id, agency_id=agency_id).first()
    losers = (Customer.query.filter(Customer.agency_id == agency_id,
                                    Customer.id.in_(loser_ids),
                                    Customer.id != keeper_id).all())
    if not keeper or not losers:
        return {"ok": False, "error": "keeper/losers not found", "merged": 0,
                "current_mbi": None, "superseded_policy_ids": [], "needs_review": False}

    everyone = [keeper] + losers
    dobs = {c.dob for c in everyone if c.dob is not None}
    if len(dobs) > 1:
        return {"ok": False, "error": "different DOB — not the same person", "merged": 0,
                "current_mbi": None, "superseded_policy_ids": [], "needs_review": False}

    ids = [c.id for c in everyone]
    policies = Policy.query.filter(Policy.agency_id == agency_id,
                                   Policy.customer_id.in_(ids),
                                   Policy.status == "active").all()
    r = resolve_primary_medical(policies, plan_type_of=_eff_type_of, code_of=_eff_code_of)

    # Current MBI = current primary-medical plan's MBI if valid; else the single
    # valid MBI present across the records.
    current = r["current"]
    current_mbi = None
    if current and _is_valid_mbi(current.member_id):
        current_mbi = current.member_id.strip().upper()
    else:
        valid = {c.mbi.strip().upper() for c in everyone if _is_valid_mbi(c.mbi)}
        if len(valid) == 1:
            current_mbi = next(iter(valid))
        elif len(valid) > 1:
            # two real MBIs + no unambiguous current plan -> refuse (don't guess)
            return {"ok": False, "error": "can't determine current MBI — resolve the "
                    "primary-medical plan first", "merged": 0, "current_mbi": None,
                    "superseded_policy_ids": [], "needs_review": True}

    # Assign the current MBI to the keeper without ever having two rows hold it at
    # once (ix_customers_mbi is a partial unique index — Postgres raises on a
    # transient duplicate even mid-transaction). Donor-clear-first: null the MBI on
    # EVERY record (keeper + losers) and flush, THEN set it on the keeper. Also nulls
    # any other differing MBI / non-MBI policy number.
    for c in everyone:
        if c.mbi:
            c.mbi = None
    db.session.flush()                       # release all MBIs before re-assigning
    if current_mbi:
        keeper.mbi = current_mbi

    # Term the superseded primary-medical policies + close their AOR chapter BEFORE
    # the merge, so it rides the engine's single commit (merge_customers commits
    # internally via log_event; doing the term AFTER would be a second commit whose
    # failure path could falsely report "no changes" while the merge is committed —
    # the exact atomic-ordering bug the shipped override's opus review caught). The
    # AOR chapter is closed on whichever customer currently owns it (the policy may
    # still be on a loser at this point); the merge then re-homes it onto the keeper.
    superseded_ids = []
    if not r["needs_review"] and current is not None:
        term_date = (current.effective_date - _timedelta(days=1)) if current.effective_date else None
        for sp in r["supersede"]:
            p = db.session.get(Policy, sp.id)
            if p and p.status == "active":
                owner = db.session.get(Customer, p.customer_id)
                p.status = "termed"
                p.term_date = term_date
                p.term_reason = "Superseded (merge)"
                if owner:
                    _close_open_aor_on_term(owner, p.carrier, term_date)
                superseded_ids.append(p.id)
    db.session.flush()

    res = merge_customers(keeper_id, loser_ids, agency_id, actor)
    if not res["ok"]:
        db.session.rollback()
        return {"ok": False, "error": res["error"], "merged": 0,
                "current_mbi": None, "superseded_policy_ids": [], "needs_review": False}

    # merge_customers committed internally. No second commit needed.
    return {"ok": True, "merged": res.get("merged", 0), "current_mbi": current_mbi,
            "superseded_policy_ids": superseded_ids, "needs_review": r["needs_review"],
            "error": None}


# ---------------------------------------------------------------------------
# No-MBI merge engine (Item 2 — collapses dup clusters with or without MBI)
# ---------------------------------------------------------------------------

# Fields the engine will fill on a blank keeper from losers.  Never overwrites.
_MERGE_FILL_FIELDS = (
    "mbi", "humana_id", "dob", "gender",
    "phone_primary", "phone_secondary",
    "email", "address1", "city", "state", "zip_code", "county",
    "medicaid_level", "medicaid_id", "lead_source", "preferred_name",
)


def _merge_precedence_key(c):
    """Sort key: manually_edited(2) > non-stub(1) > stub(0); newer id breaks ties."""
    return (2 if c.manually_edited else (0 if c.stub else 1), c.id)


def merge_customers(keeper_id, loser_ids, agency_id, actor):
    """Collapse loser customers into the keeper.

    The caller owns the transaction — call db.session.commit() after this
    returns ok=True.  This function never commits or rolls back.

    Returns:
        dict with keys ok, merged, filled, moved, error.
        ok=False means nothing was changed.
    """
    keeper = Customer.query.filter_by(id=keeper_id, agency_id=agency_id).first()
    if keeper is None:
        return {"ok": False, "merged": 0, "filled": [], "moved": {},
                "error": "keeper not found"}

    losers = (
        Customer.query
        .filter(
            Customer.agency_id == agency_id,
            Customer.id.in_(loser_ids),
            Customer.id != keeper_id,
        )
        .all()
    )
    if not losers:
        return {"ok": True, "merged": 0, "filled": [], "moved": {}, "error": None}

    # Refuse the whole merge if DOBs or MBIs contradict across the cluster.
    everyone = [keeper] + losers
    dobs = {c.dob for c in everyone if c.dob is not None}
    mbis = {c.mbi for c in everyone if c.mbi}
    if len(dobs) > 1 or len(mbis) > 1:
        return {"ok": False, "merged": 0, "filled": [], "moved": {},
                "error": "contradictory dob or mbi in cluster"}

    # All mutations run under no_autoflush: this function does a sequence of
    # synchronize_session=False bulk UPDATEs + per-row changes + deletes, and a
    # mid-sequence autoflush (any query triggers one) can push partial state to
    # Postgres in a constraint-violating order — the keeper adopting a loser's MBI
    # before the donor-clear flushes (ix_customers_mbi UniqueViolation), or an AOR
    # customer_id update flushing before keeper.id is settled. Suppressing autoflush
    # stages everything and lets it land together at the caller's commit. Invisible
    # on SQLite; reproduced live on Postgres 2026-07-17 (Annie Maready 3-way + shared
    # Humana AOR chapters). See docs/superpowers/specs/2026-07-17-merge-engine-autoflush-fix-design.md.
    with db.session.no_autoflush:
        loser_ids_resolved = [l.id for l in losers]

        # Count PolicyPayments that will follow transitively (via Policy.customer_id).
        # PolicyPayment has no customer_id column — linkage is through policy_id.
        loser_policy_ids = [
            p.id for p in
            Policy.query.filter(Policy.customer_id.in_(loser_ids_resolved)).all()
        ]
        pp_count = (
            PolicyPayment.query
            .filter(PolicyPayment.policy_id.in_(loser_policy_ids))
            .count()
        ) if loser_policy_ids else 0

        moved = {}

        # Reattach all child models that DO have a customer_id column.
        # Scope is customer_id.in_(loser_ids_resolved): the losers were already fetched
        # agency-scoped (Customer.agency_id == agency_id above), so any row pointing at a
        # loser IS this agency's row. We deliberately do NOT also filter on model.agency_id
        # here — Policy.agency_id is nullable with no ondelete, so a legacy NULL-agency
        # policy would be silently skipped by that filter and then orphaned when the loser
        # is deleted, re-introducing the exact ForeignKeyViolation this reattach prevents.
        for model in (Policy, CustomerNote, CustomerContact, CommissionLineItem):
            n = (
                model.query
                .filter(model.customer_id.in_(loser_ids_resolved))
                .update({"customer_id": keeper.id}, synchronize_session=False)
            )
            moved[model.__name__] = n

        # CustomerAorHistory needs special handling because of
        # UniqueConstraint("customer_id", "carrier", "effective_date",
        #                  name="uq_aor_customer_carrier_date").
        # A blind bulk UPDATE collides when keeper and loser share the same
        # (carrier, effective_date) enrollment chapter — this is the normal case
        # when merging duplicate records of the same person.
        # Fix: move only chapters the keeper does NOT already have; delete the rest
        # (they represent the same chapter, already present on the keeper).
        #
        # NULL effective_date: Postgres treats NULLs as distinct in a unique index,
        # so two (carrier, NULL) rows never collide at the DB level.  We mirror that
        # here: only consider a collision when effective_date IS NOT NULL.
        keeper_aor_set = {
            (row.carrier, row.effective_date)
            for row in CustomerAorHistory.query.filter_by(customer_id=keeper.id).all()
            if row.effective_date is not None
        }
        loser_aors = (
            CustomerAorHistory.query
            .filter(CustomerAorHistory.customer_id.in_(loser_ids_resolved))
            .all()
        )
        aor_moved = 0
        for row in loser_aors:
            key = (row.carrier, row.effective_date)
            if row.effective_date is not None and key in keeper_aor_set:
                # Duplicate chapter — drop the loser copy; keeper already has it.
                db.session.delete(row)
            else:
                row.customer_id = keeper.id
                if row.effective_date is not None:
                    keeper_aor_set.add(key)  # prevent a second loser from colliding
                aor_moved += 1
        moved["CustomerAorHistory"] = aor_moved

        # C1: Repoint both MatchSuggestion FK columns so delete(loser) never
        # raises a ForeignKeyViolation.  MatchSuggestion.agency_id is nullable
        # (confirmed in models.py) — a stale NULL-agency suggestion could still
        # reference a loser.  We intentionally omit the agency_id filter here so
        # we catch any dangling row regardless of its agency_id value (the loser
        # ids are already agency-scoped upstream, so there is no cross-tenant risk
        # in updating without the agency guard).
        from app.models import MatchSuggestion
        MatchSuggestion.query.filter(
            MatchSuggestion.stub_customer_id.in_(loser_ids_resolved)
        ).update({"stub_customer_id": keeper.id}, synchronize_session=False)
        MatchSuggestion.query.filter(
            MatchSuggestion.suggested_customer_id.in_(loser_ids_resolved)
        ).update({"suggested_customer_id": keeper.id}, synchronize_session=False)

        # CarrierIdCrosswalk needs the same collision handling as CustomerAorHistory
        # because of UNIQUE (agency_id, carrier, carrier_key) — a crosswalk row can
        # legitimately point at a stub loser (the seed's MBI match can land on a
        # stub when a real+stub share humana_id), and a blind bulk UPDATE would
        # collide if keeper and loser already share a (carrier, carrier_key).
        # Mirror the CustomerAorHistory pattern: move keys the keeper lacks,
        # delete duplicates the keeper already has. Must happen BEFORE the loser
        # delete below or a leftover row raises ForeignKeyViolation on Postgres
        # (CarrierIdCrosswalk.customer_id has no ondelete cascade at the FK).
        from app.models import CarrierIdCrosswalk
        keeper_xw_set = {
            (row.carrier, row.carrier_key)
            for row in CarrierIdCrosswalk.query.filter_by(customer_id=keeper.id).all()
        }
        loser_xws = (
            CarrierIdCrosswalk.query
            .filter(CarrierIdCrosswalk.customer_id.in_(loser_ids_resolved))
            .all()
        )
        xw_moved = 0
        for row in loser_xws:
            key = (row.carrier, row.carrier_key)
            if key in keeper_xw_set:
                # Duplicate key — drop the loser copy; keeper already has it.
                db.session.delete(row)
            else:
                row.customer_id = keeper.id
                keeper_xw_set.add(key)  # prevent a second loser from colliding
                xw_moved += 1
        moved["CarrierIdCrosswalk"] = xw_moved

        # Report PolicyPayment transitively (moved via their policies above).
        moved["PolicyPayment"] = pp_count

        # Fill blank keeper fields from losers, highest-precedence source first.
        fillers = sorted(losers, key=_merge_precedence_key, reverse=True)
        filled = []
        # Fields under a UNIQUE index (Postgres partial index ix_customers_mbi):
        # setting BOTH rows' mbi in one flush is unsafe even inside no_autoflush.
        # SQLAlchemy's flush batches same-table UPDATEs into one executemany
        # ordered by ascending primary key, and ix_customers_mbi is a
        # non-deferrable constraint (checked per-row as the executemany runs,
        # not at transaction end) — so if keeper.id < donor.id (the common case:
        # real keeper has the lower id, stub donor the higher one), the keeper's
        # mbi-adopt UPDATE is emitted and checked BEFORE the donor's clear,
        # and Postgres raises UniqueViolation even though both changes are in
        # the same flush. The only safe order is: clear the donor and flush
        # THAT alone first (releasing the value in the DB), then set it on the
        # keeper. The explicit flush() below is not suppressed by no_autoflush
        # (that context only stops *implicit* autoflushes on query); it runs
        # fine. (Reproduced by the Devoted 'Rene Barger' stub→real merge, and by
        # any keeper-id-less-than-donor-id case generally.)
        _UNIQUE_FILL_FIELDS = {"mbi"}
        for fld in _MERGE_FILL_FIELDS:
            if getattr(keeper, fld, None):
                continue
            for src in fillers:
                v = getattr(src, fld, None)
                if v:
                    if fld in _UNIQUE_FILL_FIELDS:
                        setattr(src, fld, None)      # donor releases the unique value
                        db.session.flush()           # ...and it lands in the DB now
                        setattr(keeper, fld, v)       # ...before the keeper adopts it
                    else:
                        setattr(keeper, fld, v)
                    filled.append(fld)
                    break

        # Explicit flush before deleting losers: every reattachment above (Policy/
        # CustomerNote/CustomerContact/CommissionLineItem bulk UPDATEs, the
        # CustomerAorHistory/CarrierIdCrosswalk per-row customer_id reassignments,
        # the MatchSuggestion repoints, the MBI fill) must land in the DB BEFORE
        # a loser is deleted. Otherwise SQLAlchemy's delete-cascade FK-nullify for
        # the loser's relationships re-queries the DB, sees those children still
        # pointing at the loser (their Python-side reassignment hasn't been
        # flushed), and nulls a NOT NULL customer_id out from under us — a
        # regression no_autoflush would otherwise reintroduce here (the pre-fix
        # code's incidental per-query autoflushes happened to flush this first).
        db.session.flush()

        # Delete emptied losers.
        for loser in losers:
            db.session.delete(loser)

        log_event(
            action="customer_merge",
            category="admin",
            detail=(
                f"keeper={keeper.id} losers={loser_ids_resolved} "
                f"filled={filled} moved={moved}"
            ),
            user=actor,
            customer_id=keeper.id,
            record_count=len(losers),
            agency_id_override=agency_id,
        )

        return {
            "ok": True,
            "merged": len(losers),
            "filled": filled,
            "moved": moved,
            "error": None,
        }


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


# ---------------------------------------------------------------------------
# Unassigned customers (admin) — commission stubs with no agent yet (#1c)
# ---------------------------------------------------------------------------

def _suggested_agent_id(customer):
    """Best-guess agent for an unassigned customer: the agent resolved on its
    commission line item (matched by MBI). Returns (agent_id, basis) or (None, '')."""
    if not customer.mbi:
        return None, ""
    from app.models import CommissionLineItem
    li = (CommissionLineItem.query
          .filter_by(agency_id=customer.agency_id, mbi=customer.mbi)
          .filter(CommissionLineItem.agent_id.isnot(None))
          .first())
    if li:
        return li.agent_id, f"{li.carrier} commission writing agent"
    return None, ""


def _needs_interval_count(aid):
    have_iv = (db.session.query(CustomerAorHistory.customer_id)
               .filter(CustomerAorHistory.agency_id == aid).distinct())
    return (Customer.query
            .filter(Customer.agency_id == aid, Customer.primary_agent_id.isnot(None))
            .filter(~Customer.id.in_(have_iv)).count())


def _needs_interval_items(aid):
    have_iv = (db.session.query(CustomerAorHistory.customer_id)
               .filter(CustomerAorHistory.agency_id == aid).distinct())
    rows = (Customer.query
            .filter(Customer.agency_id == aid, Customer.primary_agent_id.isnot(None))
            .filter(~Customer.id.in_(have_iv))
            .order_by(Customer.full_name).all())
    return [{"c": c, "agent_name": (c.primary_agent.display_name if c.primary_agent else None)}
            for c in rows]


def _needs_match_items(aid):
    """NULL-customer agent_commission/chargeback line items — payments that never
    got tied to a Customer record. Shows what's known + a resolve_payment_identity
    suggestion (tier + would-be customer) without writing anything."""
    rows = (CommissionLineItem.query
            .filter_by(agency_id=aid, customer_id=None)
            .filter(CommissionLineItem.classification.in_(["agent_commission", "chargeback"]))
            .order_by(CommissionLineItem.statement_date.desc()).all())
    items = []
    for li in rows:
        sid = None
        sname = None
        tier = None
        try:
            sid, sname, tier = _peek_match_suggestion(li, aid)
        except Exception:
            pass
        items.append({"li": li, "suggested_customer_id": sid, "suggested_customer_name": sname,
                      "tier": tier})
    return items


def _peek_match_suggestion(li, aid):
    """Read-only preview of resolve_payment_identity's match — runs the matchers
    inside a SAVEPOINT and rolls back so nothing is written by viewing the hub."""
    from app.identity import resolve_payment_identity
    nested = db.session.begin_nested()
    try:
        result = resolve_payment_identity(li, aid)
    finally:
        nested.rollback()
    if result.get("action") == "linked" and result.get("customer_id"):
        cust = db.session.get(Customer, result["customer_id"])
        return result["customer_id"], (cust.display_name if cust else None), result.get("tier")
    return None, None, None


def _needs_name_items(aid):
    """Active policies with no first/last name — Policy has no member_name column,
    so this is a blank-name check (matches the counts query)."""
    rows = (Policy.query
            .filter(Policy.agency_id == aid, Policy.status == "active",
                    db.or_(Policy.first_name.is_(None), Policy.first_name == ""),
                    db.or_(Policy.last_name.is_(None), Policy.last_name == ""))
            .order_by(Policy.id).all())
    return [{"p": p} for p in rows]


@customers_bp.route("/customers/unassigned")
@login_required
def customers_unassigned():
    """Needs Identity hub: every record lacking a known identity/origin, in one
    place. Categories: agent | match | name | interval. (Repurposed from the old
    unassigned-only view per the 2026-06-22 identity-recovery spec.) Each category
    shows a suggested action (assign agent / confirm match / fill name / interval
    auto-recovers via the derivation script) so AJ can resolve in one click — with
    the basis shown for transparency."""
    if not current_user.is_admin:
        abort(403)
    aid = current_user.agency_id
    cat = request.args.get("cat", "agent")
    agents = (User.query.filter_by(agency_id=aid)
              .filter(User.email != "admin@foundersinsuranceagency.com")
              .order_by(User.name).all())

    counts = {
        "agent": Customer.query.filter_by(agency_id=aid, primary_agent_id=None).count(),
        "match": CommissionLineItem.query.filter_by(agency_id=aid, customer_id=None)
                 .filter(CommissionLineItem.classification.in_(["agent_commission", "chargeback"])).count(),
        "name": Policy.query.filter(Policy.agency_id == aid, Policy.status == "active",
                 db.or_(Policy.first_name.is_(None), Policy.first_name == ""),
                 db.or_(Policy.last_name.is_(None), Policy.last_name == "")).count(),
        "interval": _needs_interval_count(aid),
    }

    items = []
    if cat == "agent":
        rows = (Customer.query.filter_by(agency_id=aid, primary_agent_id=None)
                .order_by(Customer.full_name).all())
        for c in rows:
            sid, basis = _suggested_agent_id(c)
            sname = next((a.display_name for a in agents if a.id == sid), None)
            items.append({"c": c, "suggested_id": sid, "suggested_name": sname, "basis": basis})
    elif cat == "match":
        items = _needs_match_items(aid)
    elif cat == "name":
        items = _needs_name_items(aid)
    elif cat == "interval":
        items = _needs_interval_items(aid)

    return render_template("customers_unassigned.html",
        items=items, agents=agents, cat=cat, counts=counts)


@customers_bp.route("/customers/<int:customer_id>/set-agent", methods=["POST"])
@login_required
def customer_set_agent(customer_id):
    """Admin: assign (or change) a customer's primary agent. Opens the AOR interval
    from the customer's policy data when present (carrier + effective_date)."""
    if not current_user.is_admin:
        abort(403)
    customer = Customer.query.filter_by(
        id=customer_id, agency_id=current_user.agency_id).first_or_404()
    agent_id = request.form.get("agent_id", type=int)
    agent = User.query.filter_by(id=agent_id, agency_id=current_user.agency_id).first()
    if not agent:
        flash("Pick a valid agent.", "error")
        return redirect(request.referrer or url_for("customers.customers_unassigned"))
    customer.primary_agent_id = agent.id
    # Open the AOR interval that was skipped at import, if we have policy facts.
    pol = Policy.query.filter_by(customer_id=customer.id).first()
    if pol and pol.effective_date and pol.carrier:
        exists = CustomerAorHistory.query.filter_by(
            customer_id=customer.id, carrier=pol.carrier,
            effective_date=pol.effective_date).first()
        if not exists:
            db.session.add(CustomerAorHistory(
                agency_id=customer.agency_id, customer_id=customer.id, agent_id=agent.id,
                carrier=pol.carrier, effective_date=pol.effective_date,
                end_date=(None if pol.carrier == "BCBS" else pol.term_date),
                source="manual_assign"))
    db.session.commit()
    log_event("customer_set_agent", category="admin",
              detail=f"customer {customer.id} → agent {agent.id} ({agent.display_name})",
              customer_id=customer.id)
    flash(f"{customer.display_name} assigned to {agent.display_name}.", "success")
    return redirect(request.referrer or url_for("customers.customers_unassigned"))
