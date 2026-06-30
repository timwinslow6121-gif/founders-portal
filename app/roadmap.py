"""Roadmap & Changelog + bug intake. Everyone sees the same shared board (no
private/public split); wont_fix/dismissed items are off it (still in the
submitter's own ?mine=1 view + the admin filter). See
docs/superpowers/specs/2026-06-29-roadmap-changelog-bug-intake-design.md."""
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user, login_required

from app.extensions import db
from app.models import RoadmapItem
from app.audit import log_event

roadmap_bp = Blueprint("roadmap", __name__)

_COLUMNS = ("planned", "in_progress", "shipped")
_EDITABLE_TEXT = ("title", "issue_text", "fix_text", "type", "status", "priority")


def _shared_items(agency_id):
    """All non-hidden items for this agency. Ordered by id desc (newest first);
    the template groups by column + shows shipped_on per card, so a portable
    id-desc order is enough (avoids cross-DB NULLS-ordering quirks)."""
    return (RoadmapItem.query
            .filter_by(agency_id=agency_id)
            .filter(~RoadmapItem.status.in_(list(RoadmapItem._HIDDEN_STATUSES)))
            .order_by(RoadmapItem.id.desc())
            .all())


@roadmap_bp.route("/roadmap")
@login_required
def roadmap_board():
    aid = current_user.agency_id
    mine_only = request.args.get("mine") == "1"
    if mine_only:
        items = (RoadmapItem.query
                 .filter_by(agency_id=aid, submitted_by_id=current_user.id)
                 .order_by(RoadmapItem.id.desc()).all())
    else:
        items = _shared_items(aid)
    columns = {c: [] for c in _COLUMNS}
    for it in items:
        col = it.column
        if col in columns:
            columns[col].append(it)
        # 'hidden' items only reach here via ?mine=1; show them in a separate list
    mine_hidden = [it for it in items if it.column == "hidden"] if mine_only else []
    return render_template("roadmap.html", columns=columns, mine_only=mine_only,
                           mine_hidden=mine_hidden)


@roadmap_bp.route("/roadmap/<int:item_id>/edit", methods=["POST"])
@login_required
def roadmap_edit(item_id):
    if not current_user.is_admin:
        abort(403)
    item = RoadmapItem.query.filter_by(
        id=item_id, agency_id=current_user.agency_id).first_or_404()
    for field in _EDITABLE_TEXT:
        if field in request.form:
            val = (request.form.get(field) or "").strip() or None
            setattr(item, field, val)
    # title is NOT NULL — never blank it
    if "title" in request.form and not (request.form.get("title") or "").strip():
        item.title = item.title  # keep existing
    raw_date = (request.form.get("shipped_on") or "").strip()
    if raw_date:
        try:
            item.shipped_on = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            pass
    db.session.commit()
    log_event("roadmap_edit", category="roadmap",
              detail=f"#{item.id} -> status={item.status} priority={item.priority}")
    flash("Roadmap item updated.", "success")
    return redirect(url_for("roadmap.roadmap_board"))


@roadmap_bp.route("/roadmap/submit", methods=["POST"])
@login_required
def roadmap_submit():
    title = (request.form.get("title") or "").strip()
    issue = (request.form.get("issue_text") or "").strip()
    if not title:
        flash("Please give your report a short title.", "error")
        return redirect(url_for("roadmap.roadmap_board"))
    item = RoadmapItem(agency_id=current_user.agency_id, type="bug_fix",
                       status="submitted", title=title[:200], issue_text=issue or None,
                       submitted_by_id=current_user.id)
    db.session.add(item)
    db.session.commit()
    log_event("roadmap_submit", category="roadmap", detail=f"#{item.id} {title}")
    flash("Got it — we've received your report. You can track it here under "
          '"My submissions".', "success")
    return redirect(url_for("roadmap.roadmap_board"))
