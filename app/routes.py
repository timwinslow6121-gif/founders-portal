from datetime import date, timedelta
from types import SimpleNamespace
from flask import Blueprint, render_template, redirect, url_for, abort, request, Response
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models import Customer, CustomerNote, Policy, ImportBatch, User, AuditLog

main = Blueprint('main', __name__)

MAPD_MONTHLY_RATE = 28.91
SPLIT_RATE        = 0.55


def _fmt(amount):
    return f"${amount:,.2f}"


def _urgency(term_date, today):
    days = (term_date - today).days
    if days <= 30:   return 'red',    days
    elif days <= 60: return 'amber',  days
    elif days <= 90: return 'yellow', days
    return 'green', days


def _build_dashboard_context(agent_id, today, agency_id):
    ninety_days = today + timedelta(days=90)
    thirty_days = today + timedelta(days=30)

    base         = Policy.query.filter_by(status='active', agent_id=agent_id, agency_id=agency_id)
    policy_count = base.count()
    carrier_count = (db.session.query(func.count(func.distinct(Policy.carrier)))
                     .filter_by(status='active', agent_id=agent_id, agency_id=agency_id)
                     .scalar() or 0)

    raw_terms = (
        base.filter(
            Policy.term_date.isnot(None),
            Policy.term_date >= today,
            Policy.term_date <= ninety_days,
        )
        .order_by(Policy.term_date.asc()).all()
    )

    # Build MBI→customer_id lookup for clickable term links
    mbis = [p.mbi for p in raw_terms if p.mbi]
    mbi_to_customer = {}
    if mbis:
        rows = (Customer.query
                .filter(Customer.mbi.in_(mbis), Customer.agency_id == agency_id)
                .with_entities(Customer.mbi, Customer.id).all())
        mbi_to_customer = {r.mbi: r.id for r in rows}

    upcoming_terms = []
    for p in raw_terms:
        urgency, days = _urgency(p.term_date, today)
        wrapped = SimpleNamespace(
            **{col.name: getattr(p, col.name) for col in p.__table__.columns},
            urgency_class=urgency,
            days_until_term=days,
            customer_id=mbi_to_customer.get(p.mbi),
        )
        upcoming_terms.append(wrapped)

    terms_90 = len(upcoming_terms)
    terms_30 = sum(1 for p in upcoming_terms if p.days_until_term <= 30)

    carrier_rows = (
        db.session.query(Policy.carrier, func.count(Policy.id).label('count'))
        .filter_by(status='active', agent_id=agent_id, agency_id=agency_id)
        .group_by(Policy.carrier)
        .order_by(func.count(Policy.id).desc()).all()
    )

    carrier_breakdown = []
    total_gross = 0.0
    for row in carrier_rows:
        pct      = round(row.count / policy_count * 100, 1) if policy_count else 0
        gross    = round(row.count * MAPD_MONTHLY_RATE, 2)
        your_cut = round(gross * SPLIT_RATE, 2)
        total_gross += gross
        carrier_breakdown.append({
            'carrier':       row.carrier,
            'count':         row.count,
            'pct':           pct,
            'gross_monthly': _fmt(gross),
            'your_monthly':  _fmt(your_cut),
        })

    total_your  = round(total_gross * SPLIT_RATE, 2)
    last_batch  = (ImportBatch.query.filter_by(status='success', agency_id=agency_id)
                   .order_by(ImportBatch.upload_date.desc()).first())
    last_import = last_batch.upload_date.strftime('%b %d, %Y') if last_batch else None

    # TODO: upcoming appointments query stores appointment time in note_text as
    # "Appointment: {start_time}".  A proper datetime column would be better
    # but is out of scope for Plan 04.  Plan 05+ may add an appointment_at column.
    upcoming = (CustomerNote.query
                .filter_by(agent_id=agent_id, agency_id=agency_id,
                            note_type="appointment_scheduled")
                .filter(CustomerNote.note_text.contains("Appointment:"))
                .order_by(CustomerNote.created_at.desc())
                .limit(5)
                .all())

    return dict(
        policy_count=policy_count,
        carrier_count=carrier_count,
        terms_90=terms_90,
        terms_30=terms_30,
        upcoming_terms=upcoming_terms,
        carrier_breakdown=carrier_breakdown,
        monthly_commission=_fmt(total_your),
        annual_commission=_fmt(total_your * 12),
        total_gross_monthly=_fmt(total_gross),
        last_import=last_import,
        upcoming_appointments=upcoming,
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

    today       = date.today()
    ninety_days = today + timedelta(days=90)
    thirty_days = today + timedelta(days=30)

    agency_id           = current_user.agency_id
    total_policies      = Policy.query.filter_by(status='active', agency_id=agency_id).count()
    total_terms_90      = (Policy.query.filter(
                               Policy.status=='active',
                               Policy.agency_id==agency_id,
                               Policy.term_date.isnot(None),
                               Policy.term_date >= today,
                               Policy.term_date <= ninety_days).count())
    total_terms_30      = (Policy.query.filter(
                               Policy.status=='active',
                               Policy.agency_id==agency_id,
                               Policy.term_date.isnot(None),
                               Policy.term_date >= today,
                               Policy.term_date <= thirty_days).count())
    total_monthly_gross = round(total_policies * MAPD_MONTHLY_RATE, 2)

    agency_carriers = (
        db.session.query(Policy.carrier, func.count(Policy.id).label('count'))
        .filter_by(status='active', agency_id=agency_id)
        .group_by(Policy.carrier)
        .order_by(func.count(Policy.id).desc()).all()
    )
    agency_carrier_rows = [
        {'carrier': r.carrier, 'count': r.count,
         'pct': round(r.count / total_policies * 100, 1) if total_policies else 0}
        for r in agency_carriers
    ]

    agents = (User.query
              .filter(User.email != 'admin@foundersinsuranceagency.com')
              .order_by(User.name).all())

    agent_rows = []
    for agent in agents:
        count = Policy.query.filter_by(
            status='active', agent_id=agent.id, agency_id=agency_id
        ).count()
        if count == 0:
            continue
        t30 = (Policy.query.filter(Policy.status=='active', Policy.agent_id==agent.id,
                                    Policy.agency_id==agency_id,
                                    Policy.term_date.isnot(None),
                                    Policy.term_date >= today,
                                    Policy.term_date <= thirty_days).count())
        t90 = (Policy.query.filter(Policy.status=='active', Policy.agent_id==agent.id,
                                    Policy.agency_id==agency_id,
                                    Policy.term_date.isnot(None),
                                    Policy.term_date >= today,
                                    Policy.term_date <= ninety_days).count())
        top_carriers = (
            db.session.query(Policy.carrier, func.count(Policy.id).label('count'))
            .filter_by(status='active', agent_id=agent.id, agency_id=agency_id)
            .group_by(Policy.carrier)
            .order_by(func.count(Policy.id).desc())
            .limit(3).all()
        )
        monthly_gross = round(count * MAPD_MONTHLY_RATE, 2)
        monthly_yours = round(monthly_gross * SPLIT_RATE, 2)
        agent_rows.append({
            'agent':         agent,
            'count':         count,
            'pct_of_agency': round(count / total_policies * 100, 1) if total_policies else 0,
            'terms_30':      t30,
            'terms_90':      t90,
            'term_urgency':  'red' if t30 > 0 else ('amber' if t90 > 0 else 'green'),
            'monthly_gross': _fmt(monthly_gross),
            'monthly_yours': _fmt(monthly_yours),
            'annual_yours':  _fmt(monthly_yours * 12),
            'top_carriers':  top_carriers,
        })

    agent_rows.sort(key=lambda x: x['count'], reverse=True)

    return render_template('admin_overview.html',
        total_policies=total_policies,
        total_terms_90=total_terms_90,
        total_terms_30=total_terms_30,
        total_monthly_gross=_fmt(total_monthly_gross),
        total_monthly_split=_fmt(round(total_monthly_gross * SPLIT_RATE, 2)),
        total_annual_split=_fmt(round(total_monthly_gross * SPLIT_RATE * 12, 2)),
        agency_carrier_rows=agency_carrier_rows,
        agent_rows=agent_rows,
        today=today,
    )


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
