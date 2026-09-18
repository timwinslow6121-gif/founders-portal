"""
AEP pipeline endpoints.

Follows the Fidelity precedent: the Jinja shell renders empty, JS fetches JSON,
and every mutation returns the updated row plus changed counters so the client
repaints one row instead of reloading.

Every query here is scoped to BOTH current_user.agency_id and the owning agent
(customers.primary_agent_id). Dropping either is a data leak, so the scoping
lives in one place -- _book_query -- and no endpoint queries Customer directly.
"""
import datetime as dt

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Customer, PipelineState, PipelineConfig, is_contactable
from app.pipeline.queues import QUEUES, queue_for, queue_counts
from app.pipeline.triage import tier_for
from app.pipeline.plans import current_plan_for

pipeline_bp = Blueprint("pipeline", __name__, url_prefix="/pipeline")

# Plain language only. An agent should never have to be taught a word here.
STAGE_LABEL = {
    "contact":   "Needs a call",
    "scheduled": "Appointment set",
    "deciding":  "Thinking it over",
    "submitted": "Waiting on carrier",
    "done":      "Finished",
}
OUTCOME_LABEL = {"enrolled": "Enrolled", "kept": "Staying put", "lost": "Closed"}


def _cfg(agency_id):
    cfg = PipelineConfig.query.filter_by(agency_id=agency_id).first()
    if cfg is None:
        cfg = PipelineConfig(agency_id=agency_id)
        db.session.add(cfg)
        db.session.commit()
    return cfg


def customer_row(customer, state, cfg, today=None):
    """The ONE row shape. Every read and every write returns this."""
    today = today or dt.date.today()
    t = tier_for(customer, state, cfg, today)
    return {
        "id": customer.id,
        "name": customer.full_name or f"{customer.first_name} {customer.last_name}".strip(),
        "phone": customer.phone_primary,
        "county": customer.county,
        "track": state.track,
        "stage": state.stage,
        "stage_label": STAGE_LABEL.get(state.stage, state.stage),
        "outcome": state.outcome,
        "outcome_label": OUTCOME_LABEL.get(state.outcome or ""),
        "settled": state.stage == "done",
        "tier": t.tier,
        "rank": t.rank,
        "reason_code": t.reason_code,
        "reason_plan_id": t.plan_id,
        "reason_county": t.county,
        "reason_days_left": t.days_left,
        "queue_id": queue_for(customer, state, cfg, today),
        "attempts": state.attempts,
    }


def _book_query(agency_id, agent_id):
    """One agent's live book. The only door to Customer in this module.

    deceased_date is filtered in SQL so the counters never count the dead;
    queue_for() independently re-checks via is_contactable(), which is the
    portal's single suppression seam and may grow past deceased_date.
    """
    return (db.session.query(Customer, PipelineState)
            .join(PipelineState, PipelineState.customer_id == Customer.id)
            .filter(Customer.agency_id == agency_id,
                    PipelineState.agency_id == agency_id,
                    Customer.primary_agent_id == agent_id,
                    Customer.deceased_date.is_(None)))


@pipeline_bp.route("/")
@login_required
def index():
    return render_template("pipeline/index.html")


@pipeline_bp.route("/api/today")
@login_required
def api_today():
    today = dt.date.today()
    agency_id = current_user.agency_id
    cfg = _cfg(agency_id)
    pairs = [(c, s) for c, s in _book_query(agency_id, current_user.id).all()
             if is_contactable(c)]

    total = len(pairs)
    settled = sum(1 for _, s in pairs if s.stage == "done")
    never_contacted = sum(1 for _, s in pairs if s.attempts == 0 and s.stage == "contact")

    days_left = (cfg.season_end - today).days if cfg.season_end else None
    remaining = total - settled
    pace = None
    if days_left and days_left > 0 and remaining > 0:
        pace = -(-remaining // days_left)          # ceil, never a decimal

    buckets = {qid: [] for qid, _, _ in QUEUES}
    for c, s in pairs:
        q = queue_for(c, s, cfg, today)
        if q:
            buckets[q].append(customer_row(c, s, cfg, today))

    cards = []
    for qid, title, urgent in QUEUES:
        rows = sorted(buckets[qid], key=lambda r: (r["tier"], r["rank"], r["name"]))
        if not rows:
            continue                                # empty queues are hidden
        cards.append({"id": qid, "title": title, "urgent": urgent,
                      "count": len(rows), "rows": rows[:12]})

    return jsonify({
        "settled": settled, "total": total, "remaining": remaining,
        "days_left": days_left, "pace": pace, "never_contacted": never_contacted,
        "cards": cards,
    })


@pipeline_bp.route("/api/queue/<queue_id>")
@login_required
def api_queue(queue_id):
    today = dt.date.today()
    cfg = _cfg(current_user.agency_id)
    rows = []
    for c, s in _book_query(current_user.agency_id, current_user.id).all():
        if not is_contactable(c):
            continue
        if queue_for(c, s, cfg, today) == queue_id:
            rows.append(customer_row(c, s, cfg, today))
    rows.sort(key=lambda r: (r["tier"], r["rank"], r["name"]))
    try:
        cursor = max(0, int(request.args.get("cursor", 0)))
    except (TypeError, ValueError):
        cursor = 0
    page = rows[cursor:cursor + 25]
    return jsonify({"rows": page, "total": len(rows),
                    "next_cursor": cursor + 25 if cursor + 25 < len(rows) else None})


@pipeline_bp.route("/api/customer/<int:customer_id>")
@login_required
def api_customer(customer_id):
    c = Customer.query.filter_by(id=customer_id,
                                 agency_id=current_user.agency_id).first_or_404()
    s = PipelineState.query.filter_by(
        customer_id=c.id, agency_id=current_user.agency_id).first_or_404()
    cfg = _cfg(current_user.agency_id)
    row = customer_row(c, s, cfg)
    cp = current_plan_for(c.id, c.agency_id)
    row["current_plan"] = cp
    # Agent of record is a compliance fact, not a display preference.
    row["is_mine"] = (c.primary_agent_id == current_user.id)
    row["owner_name"] = c.primary_agent.name if c.primary_agent else None
    return jsonify(row)
