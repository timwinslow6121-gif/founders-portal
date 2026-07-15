"""Medicare Updates Hub — curated carrier-intel posts behind login.
Holds the update-type presentation map, the plan-affect count helper, and the
updates_bp blueprint (hub + post/edit/delete/pin + plan picker).
See docs/superpowers/specs/2026-07-15-medicare-updates-hub-design.md."""
from datetime import date, datetime
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, abort, jsonify)
from flask_login import current_user, login_required

from app.extensions import db
from app.models import CarrierUpdate, Plan, Policy

# update_type -> presentation. ONE place; template + tests agree.
UPDATE_PRESENTATION = {
    "commission":     {"label": "Commission change", "icon": "dollar",    "accent": "commission"},
    "network":        {"label": "Network update",    "icon": "network",   "accent": "network"},
    "carrier_notice": {"label": "Carrier notice",    "icon": "carrier",   "accent": "carrier"},
    "training":       {"label": "Training & webinar","icon": "training",  "accent": "training"},
    "important_date": {"label": "Important date",     "icon": "calendar",  "accent": "date"},
    "general":        {"label": "General news",       "icon": "info",      "accent": "general"},
}


def plan_affect(plan_id, agency_id):
    """For a post's optional plan_id, return {plan_id, plan_name, count} where count is the
    AGENCY active-member count for that plan (same key/grain as the carrier pages), or None
    if plan_id is falsy / the plan is missing / on any error. Defensive: never raises."""
    if not plan_id:
        return None
    try:
        plan = Plan.query.filter_by(id=plan_id, agency_id=agency_id).first()
        if plan is None:
            return None
        count = (Policy.query
                 .filter(Policy.plan_id == plan_id,
                         Policy.status == "active",
                         Policy.agency_id == agency_id)
                 .count())
        return {"plan_id": plan.id, "plan_name": plan.plan_name, "count": count}
    except Exception:
        return None


updates_bp = Blueprint("updates", __name__)

_VALID_TYPES = set(CarrierUpdate.UPDATE_TYPES)
_CARRIERS = ["Humana", "UHC", "Aetna", "BCBS", "Devoted", "HealthSpring", "Wellabe", "GTL"]


def _parse_form(form):
    """(data, error). Cleans fields; error is a message or None."""
    title = (form.get("title") or "").strip()
    body = (form.get("body") or "").strip()
    utype = (form.get("update_type") or "").strip()
    carrier = (form.get("carrier") or "").strip() or None
    if not title:
        return None, "Title is required."
    if not body:
        return None, "Message body is required."
    if utype not in _VALID_TYPES:
        return None, "Please choose a valid update type."
    if carrier and carrier not in _CARRIERS:
        return None, "Unknown carrier."
    def _date(name):
        raw = (form.get(name) or "").strip()
        if not raw:
            return None, None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date(), None
        except ValueError:
            return None, f"{name} must be a valid date."
    event_date, e1 = _date("event_date")
    if e1:
        return None, e1
    show_until, e2 = _date("show_until")
    if e2:
        return None, e2
    plan_id = None
    raw_pid = (form.get("plan_id") or "").strip()
    if raw_pid:
        try:
            plan_id = int(raw_pid)
        except ValueError:
            return None, "Invalid plan selection."
    return {"title": title, "body": body, "update_type": utype, "carrier": carrier,
            "event_date": event_date, "show_until": show_until, "plan_id": plan_id}, None


def _form_ctx(update=None, form=None):
    return dict(update=update, form=form or {}, types=CarrierUpdate.UPDATE_TYPES,
                presentation=UPDATE_PRESENTATION, carriers=_CARRIERS)


@updates_bp.route("/updates")
@login_required
def updates_hub():
    aid = current_user.agency_id
    utype = request.args.get("type") or None
    carrier = request.args.get("carrier") or None
    if utype not in _VALID_TYPES:
        utype = None
    updates = CarrierUpdate.visible_for(aid, date.today(), update_type=utype, carrier=carrier)
    affects = {u.id: plan_affect(u.plan_id, aid) for u in updates}
    return render_template("updates.html", updates=updates, affects=affects,
                           presentation=UPDATE_PRESENTATION, types=CarrierUpdate.UPDATE_TYPES,
                           carriers=_CARRIERS, sel_type=utype, sel_carrier=carrier)


@updates_bp.route("/updates/new", methods=["GET", "POST"])
@login_required
def update_new():
    if request.method == "POST":
        data, error = _parse_form(request.form)
        if error:
            flash(error, "error")
            return render_template("update_form.html", **_form_ctx(form=request.form))
        u = CarrierUpdate(agency_id=current_user.agency_id,
                          posted_by_id=current_user.id, **data)
        db.session.add(u); db.session.commit()
        flash("Update posted.", "success")
        return redirect(url_for("updates.updates_hub"))
    return render_template("update_form.html", **_form_ctx())


@updates_bp.route("/updates/<int:uid>/edit", methods=["GET", "POST"])
@login_required
def update_edit(uid):
    u = CarrierUpdate.query.filter_by(id=uid, agency_id=current_user.agency_id).first_or_404()
    if not (current_user.is_admin or u.posted_by_id == current_user.id):
        abort(403)
    if request.method == "POST":
        data, error = _parse_form(request.form)
        if error:
            flash(error, "error")
            return render_template("update_form.html", **_form_ctx(update=u, form=request.form))
        for k, v in data.items():
            setattr(u, k, v)
        db.session.commit()
        flash("Update saved.", "success")
        return redirect(url_for("updates.updates_hub"))
    return render_template("update_form.html", **_form_ctx(update=u))


@updates_bp.route("/updates/<int:uid>/delete", methods=["POST"])
@login_required
def update_delete(uid):
    if not current_user.is_admin:
        abort(403)
    u = CarrierUpdate.query.filter_by(id=uid, agency_id=current_user.agency_id).first_or_404()
    db.session.delete(u); db.session.commit()
    flash("Update deleted.", "success")
    return redirect(url_for("updates.updates_hub"))


@updates_bp.route("/updates/<int:uid>/pin", methods=["POST"])
@login_required
def update_pin(uid):
    if not current_user.is_admin:
        abort(403)
    u = CarrierUpdate.query.filter_by(id=uid, agency_id=current_user.agency_id).first_or_404()
    u.is_pinned = not u.is_pinned
    db.session.commit()
    return redirect(url_for("updates.updates_hub"))


@updates_bp.route("/updates/plan-search")
@login_required
def plan_search():
    """JSON plan picker for the post form: match carrier/plan_name/cms_plan_id."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    like = f"%{q}%"
    rows = (Plan.query
            .filter(Plan.agency_id == current_user.agency_id,
                    db.or_(Plan.plan_name.ilike(like), Plan.cms_plan_id.ilike(like),
                           Plan.carrier.ilike(like)))
            .order_by(Plan.plan_name).limit(15).all())
    return jsonify([{"id": p.id,
                     "label": f"{p.carrier} · {p.plan_name}" + (f" ({p.cms_plan_id})" if p.cms_plan_id else "")}
                    for p in rows])
