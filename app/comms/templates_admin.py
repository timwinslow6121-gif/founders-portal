"""
app/comms/templates_admin.py

SMS template CRUD routes — list, create (agent/admin), approve/reject (admin only).

Routes:
    GET  /comms/sms-templates               — list all (admin) or own (agent)
    POST /comms/sms-templates/create        — suggest new template (any logged-in user)
    POST /comms/sms-templates/<id>/approve  — approve pending template (admin only)
    POST /comms/sms-templates/<id>/reject   — reject pending template (admin only)

Status workflow: pending → approved | rejected
TCPA compliance: agents may only send templates with status='approved'.
"""

from datetime import datetime
from functools import wraps

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.comms import comms_bp
from app.extensions import db
from app.models import SmsTemplate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@comms_bp.route("/sms-templates")
@login_required
def sms_templates_list():
    """
    Admin: see all templates grouped/listed by status.
    Agent: see only templates they created (any status).
    """
    if current_user.is_admin:
        agency_id = getattr(current_user, 'agency_id', None)
        if agency_id:
            templates = SmsTemplate.query.filter_by(
                agency_id=agency_id
            ).order_by(SmsTemplate.status, SmsTemplate.created_at.desc()).all()
        else:
            templates = SmsTemplate.query.order_by(
                SmsTemplate.status, SmsTemplate.created_at.desc()
            ).all()
    else:
        agency_id = getattr(current_user, 'agency_id', None)
        query = SmsTemplate.query.filter_by(created_by_id=current_user.id)
        if agency_id:
            query = query.filter_by(agency_id=agency_id)
        templates = query.order_by(SmsTemplate.created_at.desc()).all()

    return render_template("comms/sms_templates_admin.html", templates=templates)


@comms_bp.route("/sms-templates/create", methods=["POST"])
@login_required
def sms_template_create():
    """
    Any logged-in agent or admin can suggest a new template.
    Status defaults to 'pending' until an admin reviews it.
    """
    name = request.form.get("name", "").strip()
    body = request.form.get("body", "").strip()

    if not name or not body:
        flash("Template name and body are required.", "error")
        return redirect(url_for("comms.sms_templates_list"))

    if len(body) > 160:
        flash("Template body must be 160 characters or fewer (single SMS segment).", "error")
        return redirect(url_for("comms.sms_templates_list"))

    agency_id = getattr(current_user, 'agency_id', None)
    if not agency_id:
        flash("Your account is not linked to an agency. Contact your administrator.", "error")
        return redirect(url_for("comms.sms_templates_list"))

    tmpl = SmsTemplate(
        name=name,
        body=body,
        status="pending",
        agency_id=agency_id,
        created_by_id=current_user.id,
    )
    db.session.add(tmpl)
    db.session.commit()
    flash("Template submitted for review.", "success")
    return redirect(url_for("comms.sms_templates_list"))


@comms_bp.route("/sms-templates/<int:template_id>/approve", methods=["POST"])
@login_required
@_admin_required
def sms_template_approve(template_id):
    """Admin: approve a pending template."""
    agency_id = getattr(current_user, 'agency_id', None)
    if agency_id:
        tmpl = SmsTemplate.query.filter_by(id=template_id, agency_id=agency_id).first_or_404()
    else:
        tmpl = SmsTemplate.query.get_or_404(template_id)

    tmpl.status = "approved"
    tmpl.reviewed_by_id = current_user.id
    tmpl.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash("Template approved.", "success")
    return redirect(url_for("comms.sms_templates_list"))


@comms_bp.route("/sms-templates/<int:template_id>/reject", methods=["POST"])
@login_required
@_admin_required
def sms_template_reject(template_id):
    """Admin: reject a pending template."""
    agency_id = getattr(current_user, 'agency_id', None)
    if agency_id:
        tmpl = SmsTemplate.query.filter_by(id=template_id, agency_id=agency_id).first_or_404()
    else:
        tmpl = SmsTemplate.query.get_or_404(template_id)

    tmpl.status = "rejected"
    tmpl.reviewed_by_id = current_user.id
    tmpl.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash("Template rejected.", "success")
    return redirect(url_for("comms.sms_templates_list"))
