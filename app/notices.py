"""Agency Notice Board — the public-safe board on the pre-login page.
Holds the AEP-countdown helper, the notice-type presentation map, the board
read, and (added in the admin task) the notices_bp CRUD blueprint.
See docs/superpowers/specs/2026-07-14-login-redesign-agency-notice-board-design.md."""
from datetime import date, datetime

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, abort)
from flask_login import current_user, login_required

from app.extensions import db
from app.models import AgencyNotice

# notice_type -> presentation. ONE place; template + tests agree on this.
NOTICE_PRESENTATION = {
    "info":  {"accent": "info",  "icon": "info"},
    "alert": {"accent": "alert", "icon": "alert"},
}


def next_aep(today):
    """(days, year) until the next AEP start (Oct 15). days>=0 (0 on Oct 15);
    rolls to next year once Oct 15 has passed. year = calendar year of that Oct 15."""
    aep = date(today.year, 10, 15)
    if today > aep:
        aep = date(today.year + 1, 10, 15)
    return (aep - today).days, aep.year


def board_notices(agency_id, today=None):
    """Visible notices for the login board (thin seam over the model)."""
    return AgencyNotice.visible_for(agency_id, today or date.today())


notices_bp = Blueprint("notices", __name__)

_VALID_TYPES = set(AgencyNotice.NOTICE_TYPES)


def _parse_form(form):
    """Return (data, error). data has cleaned fields; error is a message or None."""
    title = (form.get("title") or "").strip()
    body = (form.get("body") or "").strip()
    ntype = (form.get("notice_type") or "").strip()
    if not title:
        return None, "Title is required."
    if not body:
        return None, "Message body is required."
    if ntype not in _VALID_TYPES:
        return None, "Please choose a valid notice type."
    try:
        priority = int(form.get("priority") or 0)
    except ValueError:
        return None, "Priority must be a number."
    show_until_raw = (form.get("show_until") or "").strip()
    show_until = None
    if show_until_raw:
        try:
            show_until = datetime.strptime(show_until_raw, "%Y-%m-%d").date()
        except ValueError:
            return None, "Show-until must be a valid date."
    return {
        "title": title, "body": body, "notice_type": ntype,
        "priority": priority, "show_until": show_until,
        "is_active": form.get("is_active") == "on",
    }, None


@notices_bp.route("/admin/notices")
@login_required
def admin_notices():
    if not current_user.is_admin:
        abort(403)
    today = date.today()
    notices = (AgencyNotice.query
               .filter_by(agency_id=current_user.agency_id)
               .order_by(AgencyNotice.priority.desc(), AgencyNotice.created_at.desc())
               .all())
    return render_template("admin_notices.html", notices=notices, today=today,
                           presentation=NOTICE_PRESENTATION)


@notices_bp.route("/admin/notices/new", methods=["GET", "POST"])
@login_required
def admin_notice_new():
    if not current_user.is_admin:
        abort(403)
    if request.method == "POST":
        data, error = _parse_form(request.form)
        if error:
            flash(error, "error")
            return render_template("admin_notice_form.html", notice=None,
                                   form=request.form, types=AgencyNotice.NOTICE_TYPES)
        n = AgencyNotice(agency_id=current_user.agency_id,
                         created_by_id=current_user.id, **data)
        db.session.add(n); db.session.commit()
        flash("Notice added.", "success")
        return redirect(url_for("notices.admin_notices"))
    return render_template("admin_notice_form.html", notice=None,
                           form={}, types=AgencyNotice.NOTICE_TYPES)


@notices_bp.route("/admin/notices/<int:notice_id>/edit", methods=["GET", "POST"])
@login_required
def admin_notice_edit(notice_id):
    if not current_user.is_admin:
        abort(403)
    n = AgencyNotice.query.filter_by(
        id=notice_id, agency_id=current_user.agency_id).first_or_404()
    if request.method == "POST":
        data, error = _parse_form(request.form)
        if error:
            flash(error, "error")
            return render_template("admin_notice_form.html", notice=n,
                                   form=request.form, types=AgencyNotice.NOTICE_TYPES)
        for k, v in data.items():
            setattr(n, k, v)
        db.session.commit()
        flash("Notice updated.", "success")
        return redirect(url_for("notices.admin_notices"))
    return render_template("admin_notice_form.html", notice=n,
                           form={}, types=AgencyNotice.NOTICE_TYPES)


@notices_bp.route("/admin/notices/<int:notice_id>/delete", methods=["POST"])
@login_required
def admin_notice_delete(notice_id):
    if not current_user.is_admin:
        abort(403)
    n = AgencyNotice.query.filter_by(
        id=notice_id, agency_id=current_user.agency_id).first_or_404()
    db.session.delete(n); db.session.commit()
    flash("Notice deleted.", "success")
    return redirect(url_for("notices.admin_notices"))
