from datetime import date, timedelta
from types import SimpleNamespace
from flask import Blueprint, render_template, redirect, url_for, abort, request, Response
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Customer, CustomerNote, Policy, ImportBatch, User, AuditLog
from app.metrics import (Scope, policy_count, book_breakdown,
                         commission_totals, upcoming_terms, attribution_coverage)
from app.branding import carrier_color
from app.commission.recap import latest_period_with_data

main = Blueprint('main', __name__)


def _fmt(amount):
    return f"${amount:,.2f}"


def _urgency(term_date, today):
    days = (term_date - today).days
    if days <= 30:   return 'red',    days
    elif days <= 60: return 'amber',  days
    elif days <= 90: return 'yellow', days
    return 'green', days


def _build_dashboard_context(agent_id, today, agency_id):
    scope = Scope(agency_id=agency_id, agent_id=agent_id)
    book = book_breakdown(scope)
    period = latest_period_with_data(agency_id)
    money = commission_totals(Scope(agency_id=agency_id, agent_id=agent_id, period=period))

    raw_terms = upcoming_terms(scope, days=90)
    terms_90 = len(raw_terms)
    terms_30 = sum(1 for t in raw_terms
                   if t["term_date"] is not None and (t["term_date"] - today).days <= 30)

    # Decorate with display-only derived fields (pure date math — not a count/rate
    # recompute, so this stays out of the metrics-guard's scope).
    terms = []
    for t in raw_terms:
        urgency, days = (_urgency(t["term_date"], today) if t["term_date"] else ('green', None))
        terms.append(SimpleNamespace(
            full_name=t["member"], plan_name=t["plan"], carrier=t["carrier"],
            term_date=t["term_date"], reason=t["reason"], customer_id=t["customer_id"],
            urgency_class=urgency, days_until_term=days,
        ))

    carrier_breakdown = [{"carrier": r["key"], "count": r["count"], "pct": r["pct"],
                          "color": carrier_color(r["key"])} for r in book["by_carrier"]]

    last_batch = (ImportBatch.query.filter_by(status='success', agency_id=agency_id)
                  .order_by(ImportBatch.upload_date.desc()).first())
    last_import = last_batch.upload_date.strftime('%b %d, %Y') if last_batch else None

    # TODO: upcoming appointments query stores appointment time in note_text as
    # "Appointment: {start_time}".  A proper datetime column would be better
    # but is out of scope for Plan 04.  Plan 05+ may add an appointment_at column.
    # (Not book/money data — kept here untouched by the metrics migration.)
    upcoming_appointments = (CustomerNote.query
                .filter_by(agent_id=agent_id, agency_id=agency_id,
                            note_type="appointment_scheduled")
                .filter(CustomerNote.note_text.contains("Appointment:"))
                .order_by(CustomerNote.created_at.desc())
                .limit(5)
                .all())

    return dict(
        policy_count=policy_count(scope),
        carrier_count=len(book["by_carrier"]),
        terms_90=terms_90, terms_30=terms_30,
        upcoming_terms=terms,
        carrier_breakdown=carrier_breakdown,
        monthly_commission=_fmt(money["agent_payout"]),
        commission_period=period,
        last_import=last_import,
        upcoming_appointments=upcoming_appointments,
    )


@main.route('/')
def index():
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('main.admin_overview'))
    return redirect(url_for('main.dashboard'))


@main.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    ctx   = _build_dashboard_context(current_user.id, today, current_user.agency_id)
    return render_template('dashboard.html', viewing_agent=None, **ctx)


@main.route('/admin/agent/<int:agent_id>')
@login_required
def agent_detail(agent_id):
    if not current_user.is_admin:
        abort(403)
    agent = User.query.get_or_404(agent_id)
    today = date.today()
    ctx   = _build_dashboard_context(agent_id, today, current_user.agency_id)
    return render_template('dashboard.html', viewing_agent=agent, **ctx)


@main.route("/admin/audit-log")
@login_required
def admin_audit_log():
    if not current_user.is_admin:
        abort(403)
    q = AuditLog.query.filter_by(agency_id=current_user.agency_id)
    cat = request.args.get("category")
    sev = request.args.get("severity")
    if cat:
        q = q.filter(AuditLog.category == cat)
    if sev:
        q = q.filter(AuditLog.severity == sev)
    page = request.args.get("page", 1, type=int)
    logs = q.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False)
    return render_template("audit_log.html", logs=logs, cat=cat, sev=sev)


@main.route('/admin')
@login_required
def admin_overview():
    if not current_user.is_admin:
        abort(403)
    today = date.today()
    agency_id = current_user.agency_id
    scope = Scope(agency_id=agency_id)
    book = book_breakdown(scope)
    period = latest_period_with_data(agency_id)
    money = commission_totals(Scope(agency_id=agency_id, period=period))
    cov = attribution_coverage(scope)

    carrier_rows = [{"carrier": r["key"], "count": r["count"], "pct": r["pct"],
                     "color": carrier_color(r["key"])} for r in book["by_carrier"]]

    agent_rows = []
    for r in book["by_agent"]:
        if r["agent_id"] is None:
            continue
        a_scope = Scope(agency_id=agency_id, agent_id=r["agent_id"])
        a_money = commission_totals(Scope(agency_id=agency_id, agent_id=r["agent_id"], period=period))
        a_terms = upcoming_terms(a_scope, days=30)
        agent_rows.append({
            "agent_id": r["agent_id"], "name": r["key"], "count": r["count"],
            "pct_of_agency": r["pct"], "terms_30": len(a_terms),
            "payout": _fmt(a_money["agent_payout"]),
            "top_carriers": book_breakdown(a_scope)["by_carrier"][:3],
        })

    return render_template('admin_overview.html',
        total_policies=policy_count(scope),
        coverage=cov,
        terms_30=len(upcoming_terms(scope, days=30)),
        terms_90=len(upcoming_terms(scope, days=90)),
        commission_period=period,
        agency_payout=_fmt(money["agent_payout"]),
        founders_keep=_fmt(money["founders_keep"]),
        carrier_rows=carrier_rows,
        agent_rows=agent_rows,
        carrier_color=carrier_color,
        reconciliation_url=url_for('commission.admin_reconciliation_view'),
        today=today)


@main.route('/admin/integrity')
@login_required
def admin_integrity():
    if not current_user.is_admin:
        abort(403)
    from app.integrity import run_all, load_baseline
    baseline = load_baseline()
    violations = run_all()
    rows = []
    for v in violations:
        base = baseline.get(v.key, 0)
        rows.append({"key": v.key, "domain": v.domain, "severity": v.severity,
                     "count": v.count, "baseline": base, "delta": v.count - base,
                     "description": v.description, "sample": v.sample})
    by_domain = {}
    for r in rows:
        by_domain.setdefault(r["domain"], []).append(r)
    return render_template("admin_integrity.html", by_domain=by_domain,
                           total=sum(r["count"] for r in rows))


@main.route('/admin/unattributed-policies')
@login_required
def unattributed_policies():
    if not current_user.is_admin:
        abort(403)
    rows = (Policy.query
            .filter(Policy.status == "active", Policy.agent_id.is_(None),
                    Policy.agency_id == current_user.agency_id)
            .order_by(Policy.carrier, Policy.agent_id_carrier).all())

    mbis = [p.mbi for p in rows if p.mbi]
    mbi_to_customer = {}
    if mbis:
        mbi_to_customer = dict(Customer.query
            .filter(Customer.mbi.in_(mbis), Customer.agency_id == current_user.agency_id)
            .with_entities(Customer.mbi, Customer.id).all())

    policy_rows = [{
        "carrier": p.carrier,
        "agent_id_carrier": p.agent_id_carrier,
        "member": f"{p.first_name} {p.last_name}".strip(),
        "customer_id": mbi_to_customer.get(p.mbi),
    } for p in rows]

    return render_template('unattributed_policies.html', rows=policy_rows)


def _term_priority(term_reason):
    """Return priority tier for a termination reason.
    high   = unknown / involuntary / plan cancelled — needs agent action
    low    = agent_initiated — we moved them, just confirm new plan
    death  = deceased — send condolences, low action priority
    """
    if term_reason == 'death':          return 'death'
    if term_reason == 'agent_initiated': return 'low'
    return 'high'  # None / 'involuntary' / 'plan_cancelled' / anything else


@main.route('/terminations')
@login_required
def terminations():
    today      = date.today()
    thirty_days = today + timedelta(days=30)

    carrier_filter = request.args.get('carrier', 'all')
    priority_filter = request.args.get('priority', 'all')

    base = Policy.query.filter(
        Policy.agent_id == current_user.id,
        Policy.agency_id == current_user.agency_id,
        Policy.status == 'active',
        Policy.term_date.isnot(None),
        Policy.term_date >= today,
        Policy.term_date <= thirty_days,
    )
    if carrier_filter != 'all':
        base = base.filter(Policy.carrier == carrier_filter)

    raw = base.order_by(Policy.term_date.asc()).all()

    # Resolve customer_id via MBI for profile links
    mbis = [p.mbi for p in raw if p.mbi]
    mbi_to_customer = {}
    if mbis:
        rows = (Customer.query
                .filter(Customer.mbi.in_(mbis), Customer.agency_id == current_user.agency_id)
                .with_entities(Customer.mbi, Customer.id).all())
        mbi_to_customer = {r.mbi: r.id for r in rows}

    all_terms = []
    for p in raw:
        _, days = _urgency(p.term_date, today)
        priority = _term_priority(p.term_reason)
        all_terms.append(SimpleNamespace(
            **{col.name: getattr(p, col.name) for col in p.__table__.columns},
            days_until_term=days,
            priority=priority,
            customer_id=mbi_to_customer.get(p.mbi),
        ))

    # Apply priority filter
    if priority_filter == 'high':
        terms = [t for t in all_terms if t.priority == 'high']
    elif priority_filter == 'low':
        terms = [t for t in all_terms if t.priority == 'low']
    elif priority_filter == 'death':
        terms = [t for t in all_terms if t.priority == 'death']
    else:
        terms = all_terms

    counts = {
        'all':   len(all_terms),
        'high':  sum(1 for t in all_terms if t.priority == 'high'),
        'low':   sum(1 for t in all_terms if t.priority == 'low'),
        'death': sum(1 for t in all_terms if t.priority == 'death'),
    }
    carriers = sorted(set(t.carrier for t in all_terms))

    return render_template('terminations.html',
        terms=terms,
        counts=counts,
        carriers=carriers,
        priority_filter=priority_filter,
        carrier_filter=carrier_filter,
        today=today,
    )


@main.route('/terminations/set-reason', methods=['POST'])
@login_required
def terminations_set_reason():
    """Inline AJAX — agent sets term_reason + new carrier/plan on a policy."""
    policy_id    = request.form.get('policy_id', type=int)
    term_reason  = request.form.get('term_reason', '').strip() or None
    new_carrier  = request.form.get('new_carrier', '').strip() or None
    new_plan_name = request.form.get('new_plan_name', '').strip() or None

    policy = Policy.query.filter_by(
        id=policy_id,
        agent_id=current_user.id,
        agency_id=current_user.agency_id,
    ).first_or_404()

    policy.term_reason   = term_reason
    policy.new_carrier   = new_carrier
    policy.new_plan_name = new_plan_name
    db.session.commit()
    return '', 204


@main.route('/policy/set-commission-type', methods=['POST'])
@login_required
def policy_set_commission_type():
    """Inline AJAX — agent flags a policy as initial or renewal commission."""
    policy_id       = request.form.get('policy_id', type=int)
    commission_type = request.form.get('commission_type', '').strip() or None
    if commission_type not in (None, 'initial', 'renewal'):
        return '', 400

    policy = Policy.query.filter_by(
        id=policy_id,
        agency_id=current_user.agency_id,
    ).first_or_404()

    policy.commission_type = commission_type
    db.session.commit()
    return '', 204
