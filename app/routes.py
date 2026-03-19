from datetime import date, timedelta
from types import SimpleNamespace
from flask import Blueprint, render_template, redirect, url_for, abort, request, Response
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models import Policy, ImportBatch, User

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


def _build_dashboard_context(agent_id, today):
    ninety_days = today + timedelta(days=90)
    thirty_days = today + timedelta(days=30)

    base         = Policy.query.filter_by(status='active', agent_id=agent_id)
    policy_count = base.count()
    carrier_count = (db.session.query(func.count(func.distinct(Policy.carrier)))
                     .filter_by(status='active', agent_id=agent_id)
                     .scalar() or 0)

    raw_terms = (
        base.filter(
            Policy.term_date.isnot(None),
            Policy.term_date >= today,
            Policy.term_date <= ninety_days,
        )
        .order_by(Policy.term_date.asc()).all()
    )

    upcoming_terms = []
    for p in raw_terms:
        urgency, days = _urgency(p.term_date, today)
        wrapped = SimpleNamespace(
            **{col.name: getattr(p, col.name) for col in p.__table__.columns},
            urgency_class=urgency,
            days_until_term=days,
        )
        upcoming_terms.append(wrapped)

    terms_90 = len(upcoming_terms)
    terms_30 = sum(1 for p in upcoming_terms if p.days_until_term <= 30)

    carrier_rows = (
        db.session.query(Policy.carrier, func.count(Policy.id).label('count'))
        .filter_by(status='active', agent_id=agent_id)
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
    last_batch  = (ImportBatch.query.filter_by(status='success')
                   .order_by(ImportBatch.upload_date.desc()).first())
    last_import = last_batch.upload_date.strftime('%b %d, %Y') if last_batch else None

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
    )


@main.route('/')
def index():
    return redirect(url_for('main.dashboard'))


@main.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    ctx   = _build_dashboard_context(current_user.id, today)
    return render_template('dashboard.html', viewing_agent=None, **ctx)


@main.route('/admin/agent/<int:agent_id>')
@login_required
def agent_detail(agent_id):
    if not current_user.is_admin:
        abort(403)
    agent = User.query.get_or_404(agent_id)
    today = date.today()
    ctx   = _build_dashboard_context(agent_id, today)
    return render_template('dashboard.html', viewing_agent=agent, **ctx)


@main.route('/admin')
@login_required
def admin_overview():
    if not current_user.is_admin:
        abort(403)

    today       = date.today()
    ninety_days = today + timedelta(days=90)
    thirty_days = today + timedelta(days=30)

    total_policies      = Policy.query.filter_by(status='active').count()
    total_terms_90      = (Policy.query.filter(
                               Policy.status=='active',
                               Policy.term_date.isnot(None),
                               Policy.term_date >= today,
                               Policy.term_date <= ninety_days).count())
    total_terms_30      = (Policy.query.filter(
                               Policy.status=='active',
                               Policy.term_date.isnot(None),
                               Policy.term_date >= today,
                               Policy.term_date <= thirty_days).count())
    total_monthly_gross = round(total_policies * MAPD_MONTHLY_RATE, 2)

    agency_carriers = (
        db.session.query(Policy.carrier, func.count(Policy.id).label('count'))
        .filter_by(status='active')
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
        count = Policy.query.filter_by(status='active', agent_id=agent.id).count()
        if count == 0:
            continue
        t30 = (Policy.query.filter(Policy.status=='active', Policy.agent_id==agent.id,
                                    Policy.term_date.isnot(None),
                                    Policy.term_date >= today,
                                    Policy.term_date <= thirty_days).count())
        t90 = (Policy.query.filter(Policy.status=='active', Policy.agent_id==agent.id,
                                    Policy.term_date.isnot(None),
                                    Policy.term_date >= today,
                                    Policy.term_date <= ninety_days).count())
        top_carriers = (
            db.session.query(Policy.carrier, func.count(Policy.id).label('count'))
            .filter_by(status='active', agent_id=agent.id)
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


@main.route('/terminations')
@login_required
def terminations():
    today       = date.today()
    ninety_days = today + timedelta(days=90)

    # Filters from query string
    urgency_filter = request.args.get('urgency', 'all')
    carrier_filter = request.args.get('carrier', 'all')

    base = Policy.query.filter(
        Policy.agent_id == current_user.id,
        Policy.status == 'active',
        Policy.term_date.isnot(None),
        Policy.term_date >= today,
        Policy.term_date <= ninety_days,
    )

    if carrier_filter != 'all':
        base = base.filter(Policy.carrier == carrier_filter)

    raw = base.order_by(Policy.term_date.asc()).all()

    # Wrap with urgency
    all_terms = []
    for p in raw:
        urgency, days = _urgency(p.term_date, today)
        from types import SimpleNamespace
        w = SimpleNamespace(
            **{col.name: getattr(p, col.name) for col in p.__table__.columns},
            urgency_class=urgency,
            days_until_term=days,
        )
        all_terms.append(w)

    # Apply urgency filter after wrapping
    if urgency_filter == 'critical':
        terms = [t for t in all_terms if t.days_until_term <= 30]
    elif urgency_filter == 'warning':
        terms = [t for t in all_terms if 30 < t.days_until_term <= 60]
    elif urgency_filter == 'watch':
        terms = [t for t in all_terms if 60 < t.days_until_term <= 90]
    else:
        terms = all_terms

    # Counts for filter tabs
    counts = {
        'all':      len(all_terms),
        'critical': sum(1 for t in all_terms if t.days_until_term <= 30),
        'warning':  sum(1 for t in all_terms if 30 < t.days_until_term <= 60),
        'watch':    sum(1 for t in all_terms if 60 < t.days_until_term <= 90),
    }

    # Carrier list for dropdown
    carriers = sorted(set(t.carrier for t in all_terms))

    return render_template('terminations.html',
        terms=terms,
        counts=counts,
        carriers=carriers,
        urgency_filter=urgency_filter,
        carrier_filter=carrier_filter,
        today=today,
    )


@main.route('/terminations/export')
@login_required
def terminations_export():
    import csv, io
    today       = date.today()
    ninety_days = today + timedelta(days=90)

    urgency_filter = request.args.get('urgency', 'all')
    carrier_filter = request.args.get('carrier', 'all')

    base = Policy.query.filter(
        Policy.agent_id == current_user.id,
        Policy.status == 'active',
        Policy.term_date.isnot(None),
        Policy.term_date >= today,
        Policy.term_date <= ninety_days,
    )
    if carrier_filter != 'all':
        base = base.filter(Policy.carrier == carrier_filter)

    raw = base.order_by(Policy.term_date.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Member Name', 'DOB', 'Phone', 'Carrier', 'Plan',
                     'Effective Date', 'Term Date', 'Days Remaining', 'Urgency'])

    for p in raw:
        urgency, days = _urgency(p.term_date, today)
        if urgency_filter == 'critical' and days > 30: continue
        if urgency_filter == 'warning' and not (30 < days <= 60): continue
        if urgency_filter == 'watch' and not (60 < days <= 90): continue

        writer.writerow([
            p.full_name or f"{p.first_name} {p.last_name}",
            p.dob.strftime('%m/%d/%Y') if p.dob else '',
            p.phone or '',
            p.carrier,
            p.plan_name or '',
            p.effective_date.strftime('%m/%d/%Y') if p.effective_date else '',
            p.term_date.strftime('%m/%d/%Y') if p.term_date else '',
            days,
            urgency.upper(),
        ])

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="terminations_{today}.csv"'}
    )
