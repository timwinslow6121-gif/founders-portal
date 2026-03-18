from datetime import date, timedelta
from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models import Policy, ImportBatch

main = Blueprint('main', __name__)

MAPD_MONTHLY_RATE = 28.91
SPLIT_RATE = 0.55

@main.route('/')
def index():
    return redirect(url_for('main.dashboard'))

@main.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    ninety_days = today + timedelta(days=90)
    thirty_days = today + timedelta(days=30)

    policy_count = Policy.query.filter_by(status='active').count()
    carrier_count = db.session.query(func.count(func.distinct(Policy.carrier))).filter_by(status='active').scalar() or 0

    upcoming_terms = (
        Policy.query
        .filter(Policy.status == 'active', Policy.term_date.isnot(None),
                Policy.term_date >= today, Policy.term_date <= ninety_days)
        .order_by(Policy.term_date.asc()).all()
    )
    terms_90 = len(upcoming_terms)
    terms_30 = sum(1 for p in upcoming_terms if p.term_date and p.term_date <= thirty_days)

    carrier_rows = (
        db.session.query(Policy.carrier, func.count(Policy.id).label('count'))
        .filter_by(status='active').group_by(Policy.carrier)
        .order_by(func.count(Policy.id).desc()).all()
    )

    carrier_breakdown = []
    total_gross = 0.0
    for row in carrier_rows:
        pct = round((row.count / policy_count * 100), 1) if policy_count else 0
        gross = round(row.count * MAPD_MONTHLY_RATE, 2)
        your_cut = round(gross * SPLIT_RATE, 2)
        total_gross += gross
        carrier_breakdown.append({
            'carrier': row.carrier, 'count': row.count, 'pct': pct,
            'gross_monthly': _fmt(gross), 'your_monthly': _fmt(your_cut),
        })

    total_your = round(total_gross * SPLIT_RATE, 2)

    last_batch = ImportBatch.query.filter_by(status='success').order_by(ImportBatch.upload_date.desc()).first()
    last_import = last_batch.upload_date.strftime('%b %d, %Y') if last_batch else None

    return render_template('dashboard.html',
        policy_count=policy_count, carrier_count=carrier_count,
        terms_90=terms_90, terms_30=terms_30, upcoming_terms=upcoming_terms,
        carrier_breakdown=carrier_breakdown,
        monthly_commission=_fmt(total_your), annual_commission=_fmt(total_your * 12),
        total_gross_monthly=_fmt(total_gross), last_import=last_import,
    )

def _fmt(amount):
    return f"${amount:,.2f}"
